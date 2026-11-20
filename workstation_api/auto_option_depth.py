"""Opt-in BANKNIFTY CE/PE 20-level recorder; no broker trading operations.

The local QuantLab process, if armed, selects verified live Dhan contracts
around the actual BANKNIFTY ATM strike, subscribing to original NSE_FNO depth,
and adds timestamped original snapshots to the existing shared Market Library.
Only market-hours packets are recorded. Historical depth is NEVER backfilled
from OHLC, and sample VWAPs are not broker fills or executable guarantees.
"""
from __future__ import annotations

from datetime import datetime, time as dtime, timezone
from hashlib import sha256
from pathlib import Path
from threading import Event, RLock, Thread
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
import fcntl
import json
import math
import os
import re
import sqlite3
import time
import uuid

from index_research.dhan_data import MASTER_URL
from . import dhan_workspace, live_market, market_depth, option_chain_live, shared_market_data

IST = ZoneInfo("Asia/Kolkata")
LOCK = RLock()
STORAGE_LOCK = RLock()
STORAGE_READY: Path | None = None
STOP = Event()
WORKER: Thread | None = None
RESTART_PENDING = False
SHUTTING_DOWN = False
STATE: dict = {
    "state": "disabled", "connected": False, "session_id": None,
    "snapshots_saved": 0, "received_pairs": 0, "invalid_pairs": 0,
    "selection_events": 0, "last_error": None, "last_chain_utc": None,
    "last_packet_utc": None, "contracts": [], "latest": {},
}
DEFAULTS = {
    "enabled": False, "target_premium": 300.0, "tolerance": 75.0,
    "per_side": 2, "lots": 3, "sample_seconds": 30,
    "selection_mode": "atm_contracts_100_each",
    "allow_token_renewal": False,
}
MAX_INSTRUMENTS = 6
MAX_DAILY_SNAPSHOTS = 200_000
CHAIN_REFRESH_SECONDS = 75
MAX_RECONNECT_DELAY_SECONDS = 60
MAX_MASTER_BYTES = 100 * 1024 * 1024
SAFE_ID = re.compile(r"^NSE_FNO:[0-9]{1,12}$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _market_open(now: datetime | None = None) -> bool:
    ist = (now or _now()).astimezone(IST)
    return (ist.weekday() < 5 and
            dtime(9, 15) <= ist.time().replace(tzinfo=None) < dtime(15, 30))


def _root() -> Path:
    return market_depth._root()


def _settings_path() -> Path:
    return _root() / "auto_banknifty_20_level.json"


def _config() -> dict:
    path = _settings_path()
    if path.is_symlink():
        # Never trust a symlinked settings file or infer permission from it.
        return dict(DEFAULTS)
    if not path.is_file():
        # User-authorized read-only BANKNIFTY collection is the normal default:
        # when an API token is already locally configured, launch both CE/PE
        # collectors with the workstation. An explicit Stop persists disabled.
        return {**DEFAULTS, "enabled": bool(os.getenv("DHAN_ACCESS_TOKEN", "").strip())}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return _validate_config(raw)
    except (ValueError, TypeError, OSError):
        # Never auto-arm on malformed saved settings.
        return dict(DEFAULTS)


def _validate_config(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("Automatic depth settings must be a JSON object")
    result = dict(DEFAULTS)
    mode = raw.get("selection_mode", DEFAULTS["selection_mode"])
    if mode not in ("atm_contracts_100_each", "premium"):
        raise ValueError("Unknown automatic depth selection mode")
    result["selection_mode"] = mode
    if not isinstance(raw.get("enabled", False), bool):
        raise ValueError("Automatic depth consent must be boolean")
    result["enabled"] = raw.get("enabled", False)
    if not isinstance(raw.get("allow_token_renewal", False), bool):
        raise ValueError("Dhan token-renewal consent must be boolean")
    result["allow_token_renewal"] = raw.get("allow_token_renewal", False)
    for key in ("target_premium", "tolerance"):
        value = raw.get(key, DEFAULTS[key])
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value)):
            raise ValueError("Premium and tolerance must be finite numbers")
        value = float(value)
        if key == "target_premium" and not 50 <= value <= 10_000:
            raise ValueError("Choose a premium from INR 50 to 10,000")
        if key == "tolerance" and not 5 <= value <= 500:
            raise ValueError("Choose a tolerance from INR 5 to 500")
        result[key] = value
    for key, smallest, largest in (("per_side", 1, 3), ("lots", 1, 20),
                                   ("sample_seconds", 1, 60)):
        value = raw.get(key, DEFAULTS[key])
        if isinstance(value, bool) or not isinstance(value, int) or not smallest <= value <= largest:
            raise ValueError("Invalid automatic depth lot, contract or sampling limit")
        result[key] = (max(30, value) if key == "sample_seconds" and
                       mode == "atm_contracts_100_each" else value)
    return result


def _save_config(cfg: dict) -> None:
    folder = _root()
    path = _settings_path()
    if path.is_symlink():
        raise ValueError("Unsafe automatic recorder settings path")
    tmp = folder / ("auto_banknifty_" + uuid.uuid4().hex[:12] + ".tmp")
    try:
        fd = os.open(str(tmp), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(cfg, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _status_update(**changes) -> None:
    with LOCK:
        STATE.update(changes)


def status() -> dict:
    cfg = _config()
    with LOCK:
        state = dict(STATE)
        state["contracts"] = [dict(row) for row in STATE.get("contracts", [])]
        state["latest"] = {k: dict(v) for k, v in STATE.get("latest", {}).items()}
        state["observed_by_contract"] = dict(STATE.get("observed_by_contract", {}))
        state["socket_last_paired_utc"] = dict(STATE.get("socket_last_paired_utc", {}))
    now = _now()
    market_open = _market_open(now)
    def _age(stamp) -> float:
        try:
            return max(0., (now - datetime.fromisoformat(stamp)).total_seconds())
        except (ValueError, TypeError, KeyError):
            return 999999.
    subscribed = {c["identity"] for c in state["contracts"]}
    observed = state["observed_by_contract"]
    wide = cfg["selection_mode"] == "atm_contracts_100_each"
    for identity, info in state["latest"].items():
        # The stored sample may be deliberately 30s old even when fresh
        # original packet pairs are arriving. Never confuse those clocks.
        age = _age(info.get("received_utc"))
        feed_age = _age(observed.get(identity)) if wide else age
        source_fresh = (state.get("connected", False) and market_open
                        and feed_age <= 10)
        info["age_seconds"] = round(age, 1)
        info["feed_age_seconds"] = round(feed_age, 1) if feed_age < 999999 else None
        info["feed_fresh"] = source_fresh
        info["fresh"] = source_fresh if wide else (
            state.get("connected", False) and market_open and age <= 10)
    state["contracts_with_saved_books"] = len(subscribed & set(state["latest"]))
    state["contracts_with_recent_packets"] = sum(
        1 for identity in subscribed
        if _age(observed.get(identity)) <= 10 and state.get("connected")
        and market_open) if wide else state["contracts_with_saved_books"]
    state["sockets_with_recent_pairs"] = sum(
        1 for ts in state["socket_last_paired_utc"].values()
        if _age(ts) <= 60 and state.get("connected") and market_open)
    # Aggregate only; no broker credentials or raw packet data are exposed.
    state.pop("observed_by_contract", None)
    state.pop("socket_last_paired_utc", None)
    return {
        **state, "settings": cfg, "armed": cfg["enabled"],
        "requested_contracts_above": (100 if cfg["selection_mode"] == "atm_contracts_100_each" else None),
        "requested_contracts_below": (100 if cfg["selection_mode"] == "atm_contracts_100_each" else None),
        "market_regular_hours": _market_open(now),
        "read_only": True, "historical_depth_download_supported": False,
        "shared_library": "dhan_shared",
        "note": ("Source is Dhan 20-level original NSE_FNO packets. "
                 "Captures run only while the local QuantLab server is running "
                 "and the regular NSE clock window is open. Exchange holidays "
                 "are inferred only from actual incoming packets. "
                 "Local receipt timestamps are not exchange event times."),
    }


def select_contracts(chain: dict, cfg: dict, previous_ids=()) -> list[dict]:
    """Select independently verified CE and PE IDs near the preferred LTP.

    Existing selections get a small hysteresis preference to reduce socket
    churn, but stale/invalid/expired or out-of-tolerance IDs never survive.
    """
    cfg = _validate_config(cfg)
    expected_expiry = chain.get("expiry")
    pool: dict[str, list[dict]] = {"CE": [], "PE": []}
    for quote in chain.get("contracts", []):
        side = quote.get("option_type")
        identity = quote.get("identity")
        ltp = quote.get("ltp")
        lot = quote.get("lot_size")
        if (side not in pool or not isinstance(identity, str)
                or not SAFE_ID.fullmatch(identity)
                or not quote.get("contract_master_verified")
                or not quote.get("quote_valid")
                or quote.get("expiry") != expected_expiry
                or not isinstance(ltp, (int, float)) or not math.isfinite(ltp)
                or abs(ltp - cfg["target_premium"]) > cfg["tolerance"]
                or not isinstance(lot, int) or lot < 1
                or not isinstance(quote.get("volume"), int)
                or quote["volume"] <= 0):
            continue
        bid, ask = quote.get("bid"), quote.get("ask")
        if not (isinstance(bid, (int, float)) and isinstance(ask, (int, float))
                and 0 < bid <= ask and math.isfinite(bid) and math.isfinite(ask)):
            continue
        pool[side].append({
            "identity": identity, "security_id": identity.split(":")[1],
            "side": side, "strike": float(quote["strike"]),
            "expiry": expected_expiry, "lot_size": lot, "ltp": float(ltp),
            "bid": float(bid), "ask": float(ask),
            "volume": int(quote["volume"]),
            "chain_received_utc": chain.get("received_utc"),
        })
    result = []
    for side in ("CE", "PE"):
        candidates = pool[side]
        candidates.sort(key=lambda c: (
            abs(c["ltp"] - cfg["target_premium"]), -c["volume"], c["strike"]))
        if candidates:
            best_dist = abs(candidates[0]["ltp"] - cfg["target_premium"])
            candidates.sort(key=lambda c: (
                0 if (c["identity"] in previous_ids and
                      abs(c["ltp"] - cfg["target_premium"]) <= best_dist + 15)
                else 1,
                abs(c["ltp"] - cfg["target_premium"]), -c["volume"]))
        result.extend(candidates[:cfg["per_side"]])
    return result[:MAX_INSTRUMENTS]


def _subscription(choices: list[dict]) -> dict:
    ids = list(dict.fromkeys(x["security_id"] for x in choices))
    if not 1 <= len(ids) <= MAX_INSTRUMENTS or any(not x.isdigit() for x in ids):
        raise ValueError("Automatic depth needs 1–6 verified NSE_FNO option IDs")
    return {
        "RequestCode": 23, "InstrumentCount": len(ids),
        "InstrumentList": [
            {"ExchangeSegment": "NSE_FNO", "SecurityId": x} for x in ids],
    }


def _depth_vwap(levels: list[dict], units: int) -> float | None:
    if units <= 0:
        return None
    remaining = units
    cost = 0.
    for level in levels:
        qty = max(0, int(level["quantity"]))
        amount = min(qty, remaining)
        cost += amount * float(level["price"])
        remaining -= amount
        if remaining == 0:
            return round(cost / units, 4)
    return None  # Never imply the 20 displayed levels can fill unavailable size.


def _features(book: dict, contract: dict, lots: int) -> dict:
    bids, asks = book["bid"], book["ask"]
    bid_qty = sum(x["quantity"] for x in bids)
    ask_qty = sum(x["quantity"] for x in asks)
    bid, ask = bids[0]["price"], asks[0]["price"]
    mid = (bid + ask) / 2
    units = lots * contract["lot_size"]
    return {
        "identity": contract["identity"], "side": contract["side"],
        "expiry": contract["expiry"], "strike": contract["strike"],
        "lot_size_verified": contract["lot_size"], "lots": lots,
        "units": units, "selected_chain_ltp": contract["ltp"],
        "chain_received_utc": contract["chain_received_utc"],
        "spread_bps": round((ask - bid) / mid * 10_000, 3),
        "book_imbalance_20": round((bid_qty - ask_qty) /
                                    max(1, bid_qty + ask_qty), 5),
        "bid_quantity_20": bid_qty, "ask_quantity_20": ask_qty,
        "top_bid_quantity": bids[0]["quantity"],
        "top_ask_quantity": asks[0]["quantity"],
        "buy_vwap_for_units": _depth_vwap(asks, units),
        "sell_vwap_for_units": _depth_vwap(bids, units),
        "full_20_levels": book.get("full_depth", False),
        "received_utc": book["received_utc"],
        "clock_basis": "local_receive_utc_not_exchange",
    }


def _storage() -> None:
    global STORAGE_READY
    current = shared_market_data.database_path()
    with STORAGE_LOCK:
        if STORAGE_READY == current and current.is_file():
            return
        live_market._init_db()
        with live_market._database() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS auto_banknifty_depth_selections(
                session_id TEXT NOT NULL, changed_utc TEXT NOT NULL,
                identity TEXT NOT NULL, option_side TEXT NOT NULL,
                expiry TEXT NOT NULL, strike REAL NOT NULL,
                lot_size INTEGER NOT NULL, selected_ltp REAL NOT NULL,
                chain_received_utc TEXT NOT NULL,
                PRIMARY KEY(session_id, changed_utc, identity)
            );
            CREATE INDEX IF NOT EXISTS auto_depth_selection_recent
                ON auto_banknifty_depth_selections(identity, changed_utc);
            CREATE TABLE IF NOT EXISTS auto_banknifty_depth_features(
                identity TEXT NOT NULL, received_utc TEXT NOT NULL,
                session_id TEXT NOT NULL, feature_json TEXT NOT NULL,
                book_pair_sha256 TEXT NOT NULL,
                PRIMARY KEY(identity, received_utc)
            );
            CREATE INDEX IF NOT EXISTS auto_depth_features_recent
                ON auto_banknifty_depth_features(identity, received_utc);
            """)
        STORAGE_READY = current


def _selection_receipt(session_id: str, choices: list[dict]) -> None:
    changed = _now().isoformat()
    _storage()
    with live_market._database() as db:
        for c in choices:
            db.execute("""INSERT OR IGNORE INTO auto_banknifty_depth_selections
              VALUES(?,?,?,?,?,?,?,?,?)""", (
                session_id, changed, c["identity"], c["side"],
                c["expiry"], c["strike"], c["lot_size"], c["ltp"],
                c["chain_received_utc"]))


def _daily_count(now: datetime) -> int:
    session_day = now.astimezone(IST).strftime("%Y%m%d")
    _storage()
    with live_market._database() as db:
        return int(db.execute(
            "SELECT COUNT(*) FROM live_depth_books WHERE session_id LIKE ?",
            ("auto20_" + session_day + "_%",)).fetchone()[0])


def _store_book(session_id: str, book: dict, feature: dict) -> bool:
    _storage()
    pair_hash = sha256(
        (book["bid_packet_sha256"] + book["ask_packet_sha256"]).encode()
    ).hexdigest()
    enriched = {**book, "collection_mode": "auto_banknifty_20_level",
                "computed_features": feature,
                "source": "original_Dhan_full_market_depth_websocket"}
    with live_market._database() as db:
        changed = db.execute(
            """INSERT OR IGNORE INTO live_depth_books
                 (identity,received_utc,session_id,book_json,packet_pair_sha256)
                 VALUES(?,?,?,?,?)""",
            (book["identity"], book["received_utc"], session_id,
             json.dumps(enriched, sort_keys=True), pair_hash)).rowcount
        if changed:
            db.execute(
                """INSERT OR IGNORE INTO auto_banknifty_depth_features
                 (identity,received_utc,session_id,feature_json,book_pair_sha256)
                 VALUES(?,?,?,?,?)""",
                (book["identity"], book["received_utc"], session_id,
                 json.dumps(feature, sort_keys=True), pair_hash))
    return bool(changed)


def _paired_books(blob: bytes, chosen: dict[str, dict],
                  pending: dict, received: datetime) -> list[tuple[dict,dict]]:
    """Pair only source bids/asks of the SAME contract within one second."""
    output = []
    try:
        packets = market_depth.packet_stream(blob, 20)
    except ValueError:
        return output
    for packet in packets:
        if packet["segment_code"] != 2:
            continue
        security = packet["security_id"]
        if security not in chosen:
            continue
        key = (security, packet["side"])
        pending[key] = (packet, received)
        opposite = (security, "ask" if packet["side"] == "bid" else "bid")
        if opposite not in pending:
            continue
        other, last_received = pending[opposite]
        if abs((received - last_received).total_seconds()) > 1.0:
            continue
        bid = packet if packet["side"] == "bid" else other
        ask = packet if packet["side"] == "ask" else other
        try:
            identity = chosen[security]["identity"]
            book = market_depth._snapshot(bid, ask, identity, received, 20)
            output.append((book, chosen[security]))
        except (ValueError, KeyError, TypeError):
            pass
        pending.pop(key, None)
        pending.pop(opposite, None)
    # Unpaired half-books are never retained across long disconnects.
    for key, (_, stamped) in list(pending.items()):
        if (received - stamped).total_seconds() > 2:
            pending.pop(key, None)
    return output


def _refresh_master_if_needed() -> None:
    original = option_chain_live._contracts()
    if original.get("available") and original.get("fresh") and original.get("by_id"):
        return
    target = dhan_workspace._master()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / ("banknifty_master_" + uuid.uuid4().hex[:10] + ".csv.tmp")
    try:
        request = Request(MASTER_URL, headers={"User-Agent": "QuantLabLocalReadOnly/1.0"})
        with urlopen(request, timeout=45) as response:
            raw = response.read(MAX_MASTER_BYTES + 1)
        if not raw or len(raw) > MAX_MASTER_BYTES or b"," not in raw[:500]:
            raise ValueError("Dhan instrument master download failed validation")
        temporary.write_bytes(raw)
        stat = temporary.stat()
        parsed = option_chain_live._master_lookup(
            str(temporary), stat.st_mtime_ns, stat.st_size)
        if not parsed.get("available") or not parsed.get("by_id"):
            raise ValueError(
                "Dhan master download has no verified BANKNIFTY CE/PE IDs")
        os.replace(temporary, target)
        option_chain_live._master_lookup.cache_clear()
    finally:
        temporary.unlink(missing_ok=True)


def _fetch_selected(cfg: dict, previous_ids=()) -> list[dict]:
    _refresh_master_if_needed()
    current = option_chain_live.expiries()
    snapshot = option_chain_live.chain(
        current["nearest_expiry"], force_refresh=True)
    stamp = datetime.fromisoformat(snapshot["received_utc"])
    if abs((_now() - stamp).total_seconds()) > 90:
        raise ValueError("Dhan option-chain snapshot is stale")
    selected = select_contracts(snapshot, cfg, previous_ids)
    _status_update(
        last_chain_utc=snapshot["received_utc"],
        chain_spot=snapshot["underlying_spot"],
        current_expiry=snapshot["expiry"],
        selection_warning=(
            "Both CE and PE are not available near the selected premium"
            if len({c["side"] for c in selected}) < 2 else None))
    return selected


def _run(stop: Event) -> None:
    lock_file = _root() / "auto_banknifty_20_level.lock"
    fd = os.open(str(lock_file), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            _status_update(state="other_local_worker", connected=False,
                           last_error="Another local QuantLab process already owns the recorder")
            return
        if _config()["selection_mode"] == "atm_contracts_100_each":
            # The wide collector uses four bounded WebSockets and a single
            # SQLite writer. The legacy premium collector stays available.
            from . import wide_option_depth
            wide_option_depth.run(stop)
            return
        failures = 0
        selection: list[dict] = []
        session_id = None
        daily_saved = 0
        next_master_attempt = 0.
        while not stop.is_set():
            cfg = _config()
            if not cfg["enabled"]:
                _status_update(state="disabled", connected=False, contracts=[])
                return
            if not _market_open():
                _status_update(state="armed_waiting_for_nse_hours",
                               connected=False, contracts=[],
                               selection_warning=None)
                stop.wait(20)
                continue
            today = _now().astimezone(IST).strftime("%Y%m%d")
            if session_id is None or not session_id.startswith("auto20_" + today):
                session_id = "auto20_" + today + "_" + uuid.uuid4().hex[:10]
                daily_saved = _daily_count(_now())
                selection = []
                _status_update(session_id=session_id, snapshots_saved=0,
                               received_pairs=0, selection_events=0,
                               invalid_pairs=0, latest={}, contracts=[],
                               last_error=None)
            if daily_saved >= MAX_DAILY_SNAPSHOTS:
                _status_update(state="daily_storage_limit_reached", connected=False)
                stop.wait(60)
                continue
            try:
                _status_update(state="selecting_verified_ce_pe", connected=False)
                selected = _fetch_selected(cfg, [c["identity"] for c in selection])
                if not selected:
                    _status_update(state="no_eligible_option_contracts",
                                   contracts=[], connected=False,
                                   last_error="No Dhan-verified CE or PE near the target premium; "
                                              "inspect premium tolerance and official master")
                    stop.wait(30)
                    continue
                ids = {c["security_id"]: c for c in selected}
                _selection_receipt(session_id, selected)
                selection = selected
                with LOCK:
                    STATE["contracts"] = selected
                    STATE["selection_events"] += 1
                    STATE["last_error"] = None
                token, client = option_chain_live._credentials()
                url = market_depth._live_endpoint(20, client, token)
                from websockets.sync.client import connect
                with connect(url, open_timeout=12, close_timeout=3,
                             max_size=12 + (20 * 16) * 100) as socket:
                    socket.send(json.dumps(_subscription(selected)))
                    _status_update(state="connected_waiting_for_packets", connected=True)
                    failures = 0
                    pending: dict = {}
                    last_sample = {}
                    next_refresh = time.monotonic() + CHAIN_REFRESH_SECONDS
                    initial_cfg = cfg
                    last_packet_monotonic = time.monotonic()
                    while not stop.is_set() and _market_open():
                        if time.monotonic() >= next_refresh or _config() != initial_cfg:
                            new_cfg = _config()
                            # Resubscribe by reconnecting only when exact IDs change.
                            # Dhan docs/support disagree on 20-depth unsubscribe codes.
                            updated = _fetch_selected(new_cfg, tuple(c["identity"] for c in selected))
                            if ([c["identity"] for c in updated] !=
                                    [c["identity"] for c in selected] or new_cfg != cfg):
                                selection = selected
                                break
                            next_refresh = time.monotonic() + CHAIN_REFRESH_SECONDS
                            for candidate in updated:
                                ids[candidate["security_id"]].update(candidate)
                            selected = updated
                            with LOCK:
                                STATE["contracts"] = updated
                        try:
                            payload = socket.recv(timeout=1)
                        except TimeoutError:
                            if time.monotonic() - last_packet_monotonic > 35:
                                _status_update(state="connected_no_depth_packets",
                                               last_error="No original paired Dhan depth packets received "
                                                          "for 35 seconds; verify 20-level entitlement")
                            continue
                        if not isinstance(payload, bytes):
                            continue
                        if daily_saved >= MAX_DAILY_SNAPSHOTS:
                            _status_update(state="daily_storage_limit_reached")
                            break
                        now = _now()
                        for book, candidate in _paired_books(payload, ids, pending, now):
                            last_packet_monotonic = time.monotonic()
                            with LOCK:
                                STATE["received_pairs"] += 1
                                STATE["last_packet_utc"] = now.isoformat()
                            ident = candidate["identity"]
                            previous = last_sample.get(ident, 0.)
                            if time.monotonic() - previous < cfg["sample_seconds"]:
                                continue
                            if daily_saved >= MAX_DAILY_SNAPSHOTS:
                                break
                            feature = _features(book, candidate, cfg["lots"])
                            if _store_book(session_id, book, feature):
                                last_sample[ident] = time.monotonic()
                                daily_saved += 1
                                with LOCK:
                                    STATE["snapshots_saved"] += 1
                                    STATE["latest"][ident] = {
                                        **feature, "best_bid": book["bid"][0]["price"],
                                        "best_ask": book["ask"][0]["price"],
                                        "bid_levels": len(book["bid"]),
                                        "ask_levels": len(book["ask"]),
                                        "source": "original_dhan_twentydepth",
                                    }
                                    STATE["state"] = "recording_original_depth"
                                    STATE["last_error"] = None
                        if daily_saved >= MAX_DAILY_SNAPSHOTS:
                            _status_update(state="daily_storage_limit_reached")
                            break
                    _status_update(connected=False)
            except Exception as exc:
                failures += 1
                # Authenticated WebSocket URLs contain secrets. Only display
                # the Python exception TYPE, never exception.str/raw URI.
                _status_update(state="connection_or_source_error", connected=False,
                               last_error=(
                                   "Automatic Dhan depth collection blocked (" +
                                   type(exc).__name__ +
                                   "). Check Dhan depth entitlement, token, "
                                   "official master and local network."))
                stop.wait(min(MAX_RECONNECT_DELAY_SECONDS, 3 * (2 ** min(failures, 4))))
                selection = []
    finally:
        _status_update(connected=False,
                       state="disabled" if stop.is_set() else STATE.get("state", "stopped"))
        os.close(fd)


def _restart_after_stopped(previous: Thread) -> None:
    global RESTART_PENDING
    # A quick Stop->Arm click cannot leave a persistent enabled setting
    # with no running worker. Wait for the old socket to release its lock.
    previous.join()
    with LOCK:
        RESTART_PENDING = False
    if not SHUTTING_DOWN and _config()["enabled"]:
        _ensure_worker()


def _ensure_worker() -> None:
    global WORKER, STOP, RESTART_PENDING
    with LOCK:
        if SHUTTING_DOWN:
            return
        if WORKER is not None and WORKER.is_alive():
            if STOP.is_set() and not RESTART_PENDING:
                RESTART_PENDING = True
                Thread(target=_restart_after_stopped, args=(WORKER,),
                       daemon=True, name="quantlab-auto-depth-rearm").start()
            return
        STOP = Event()
        WORKER = Thread(target=_run, args=(STOP,), daemon=True,
                        name="quantlab-banknifty-auto-20-depth")
        WORKER.start()


def arm(settings: dict, *, confirm_live_data: bool) -> dict:
    if not confirm_live_data:
        raise ValueError("Explicitly authorize read-only Dhan 20-level live recording")
    if not os.getenv("DHAN_ACCESS_TOKEN", "").strip():
        raise ValueError("Configure a Dhan access token locally before arming")
    normalized = _validate_config({**settings, "enabled": True})
    with LOCK:
        _save_config(normalized)
        _ensure_worker()
    return status()


def disarm() -> dict:
    with LOCK:
        _save_config({**_config(), "enabled": False})
        STOP.set()
        STATE["connected"] = False
        STATE["state"] = "stopping"
    return status()


def resume_if_armed() -> None:
    global SHUTTING_DOWN
    SHUTTING_DOWN = False
    # Start automatically with a locally configured Dhan token; explicit disarm persists.
    if _config()["enabled"]:
        _ensure_worker()


def suspend_for_shutdown() -> None:
    """Stop sockets on local server shutdown without removing user consent."""
    global SHUTTING_DOWN
    SHUTTING_DOWN = True
    STOP.set()
    with LOCK:
        if STATE.get("connected"):
            STATE["state"] = "local_server_stopping"
        STATE["connected"] = False
