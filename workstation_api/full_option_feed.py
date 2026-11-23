"""Dhan-only, read-only BANKNIFTY option universe: continuous source Quote/OI feed.

Uses ONE Dhan v2 market-feed WebSocket (the fifth alongside four 20-level
depth sockets). Every current master-verified listed CE/PE identity is
subscribed up to Dhan's documented 5000-instrument limit, in batches of 100.
Source timestamps, decoded packet hashes, loss counters, and unknown source
intervals are explicit. There are no orders, synthetic ticks, backfills, or
guarantees that silent/illiquid instruments produce trades.
"""
from __future__ import annotations

from collections import deque
from datetime import date, datetime, timezone, timedelta
from hashlib import sha256
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, RLock, Thread
from urllib.parse import quote
import fcntl
import json
import math
import os
import sqlite3
import struct
import time

from . import auto_option_depth as auto, dhan_option_chain, live_market, option_chain_live

LOCK = RLock()
STOP = Event()
WORKER: Thread | None = None
SHUTTING_DOWN = False
MAX_INSTRUMENTS = 5000
BATCH_SIZE = 100
MAX_FRAME_BYTES = 2_000_000
MAX_QUEUE = 25_000
MAX_DAILY_EVENTS = 2_000_000
DISCOVER_SECONDS = 600
MAX_TRADE_LAG_SECONDS = 120
SCORE_WINDOW_SECONDS = 300
MAX_EVENTS_PER_CONTRACT = 512
MAX_DISPLAY = 100
STATUS = {
    "state": "stopped", "connected": False,
    "requested_contracts": 0, "source_contracts": 0,
    "unsubscribed_due_to_capacity": 0, "observed_contracts": 0,
    "recent_price_contracts": 0, "quote_packets": 0,
    "oi_packets": 0, "stored_events": 0, "dropped_events": 0,
    "rejected_frames": 0, "ignored_stale_trades": 0,
    "unchanged_quote_packets": 0, "unchanged_oi_packets": 0,
    "last_quote_received_utc": None, "last_error": None,
    "session_id": None, "opportunity_count": 0,
}
CATALOG: dict[str, dict] = {}
LATEST: dict[str, dict] = {}
HISTORY: dict[str, deque] = {}
WRITES: Queue = Queue(maxsize=MAX_QUEUE)
STORAGE_INITIALIZED = False
STORAGE_LOCK = RLock()


def _utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _set(**fields) -> None:
    with LOCK:
        STATUS.update(fields)


def _consent_path() -> Path:
    return auto._root() / "banknifty_all_option_quote_consent.json"


def _consented() -> bool:
    path = _consent_path()
    if path.is_symlink() or not path.is_file():
        return False
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        return isinstance(record, dict) and record.get("enabled") is True
    except (ValueError, OSError, UnicodeError):
        return False


def _set_consent(enabled: bool) -> None:
    path = _consent_path()
    if path.is_symlink():
        raise ValueError("Unsafe Dhan full-option consent path")
    temporary = path.with_name(path.name+".tmp")
    if temporary.is_symlink():
        raise ValueError("Unsafe temporary Dhan consent path")
    descriptor = os.open(str(temporary), os.O_CREAT|os.O_WRONLY|os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({"enabled": enabled,
                       "read_only_quote_and_oi": True}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary,path)
        os.chmod(path,0o600)
    finally:
        temporary.unlink(missing_ok=True)


def _armed() -> bool:
    return bool(_consented() and auto._config()["enabled"])


def enable(*, confirm_live_quote_stream: bool) -> dict:
    """Separate opt-in; does not restart or disarm existing depth sockets."""
    if not confirm_live_quote_stream:
        raise ValueError("Explicitly approve the full Dhan options Quote/OI stream")
    if not auto._config()["enabled"]:
        raise ValueError("Arm existing Dhan read-only automatic recording first")
    if live_market.status().get("active"):
        raise ValueError("Stop the separate manual live feed before using the fifth Dhan connection")
    if not os.getenv("DHAN_ACCESS_TOKEN","").strip():
        raise ValueError("Configure a local Dhan token before starting the option feed")
    _set_consent(True)
    resume_if_armed()
    return status()


def disable() -> dict:
    _set_consent(False)
    disarmed()
    return status()


def _safe_master_contracts(master: dict, expiries: list[str],
                           *, today: date, spot: float | None = None) -> list[dict]:
    """Deduplicate strictly by both source ID and economic contract terms."""
    if not master.get("fresh") or not master.get("available"):
        raise ValueError("Fresh original Dhan instrument master required")
    active = {day for day in expiries if day >= today.isoformat()}
    if not active:
        raise ValueError("No current Dhan-reported BANKNIFTY expiries")
    by_term: dict[tuple, list[dict]] = {}
    by_id: dict[str, list[dict]] = {}
    for row in master.get("by_id", {}).values():
        if not isinstance(row, dict) or row.get("expiry") not in active:
            continue
        ident = row.get("identity")
        option_type = row.get("option_type")
        strike = row.get("strike")
        lot = row.get("lot_size")
        if (not isinstance(ident, str) or not auto.SAFE_ID.fullmatch(ident)
                or option_type not in ("CE", "PE")
                or not isinstance(strike, (int, float))
                or not math.isfinite(strike) or strike <= 0
                or not isinstance(lot, int) or lot < 1):
            continue
        key = (row["expiry"], round(float(strike), 4), option_type)
        by_term.setdefault(key, []).append(row)
        by_id.setdefault(ident, []).append(row)
    # Preserve the original instrument master term provenance: by_id can
    # overwrite repeated IDs, while its by_terms map retains ambiguities.
    source_terms = master.get("by_terms", {})
    source_ids: dict[str, int] = {}
    for original_rows in source_terms.values():
        for original in original_rows:
            identity = original.get("identity") if isinstance(original, dict) else None
            if isinstance(identity, str):
                source_ids[identity] = source_ids.get(identity, 0) + 1
    qualified = [rows[0] for key, rows in by_term.items()
                 if len(rows) == 1 and len(by_id[rows[0]["identity"]]) == 1
                 and (not source_terms or len(source_terms.get(key, [])) == 1)
                 and source_ids.get(rows[0]["identity"], 1) == 1]
    def order(row: dict):
        return (row["expiry"],
                abs(row["strike"] - spot) if spot and math.isfinite(spot) else 0,
                row["strike"], row["option_type"])
    return sorted(qualified, key=order)


def _discover() -> tuple[list[dict], int]:
    auto._refresh_master_if_needed()
    expiries = option_chain_live.expiries()["expiries"]
    master = option_chain_live._contracts()
    today = _utc().astimezone(auto.IST).date()
    # A recent genuine source spot helps choose an explicit partial-capacity
    # priority if there ever are more than 5000 listed contracts.
    with auto.LOCK:
        spot = auto.STATE.get("chain_spot")
    options = _safe_master_contracts(master, expiries, today=today, spot=spot)
    if not options:
        raise ValueError("No fresh, uniquely mapped original BANKNIFTY options")
    return options[:MAX_INSTRUMENTS], max(0, len(options)-MAX_INSTRUMENTS)


def _subscribe_batches(contracts: list[dict]) -> list[dict]:
    """Each Dhan Quote mode subscription message has at most 100 instruments."""
    if len(contracts) > MAX_INSTRUMENTS:
        raise ValueError("Dhan market feed maximum 5000 instruments exceeded")
    messages = []
    for start in range(0, len(contracts), BATCH_SIZE):
        batch = contracts[start:start+BATCH_SIZE]
        messages.append({
            "RequestCode": 17, "InstrumentCount": len(batch),
            "InstrumentList": [
                {"ExchangeSegment": "NSE_FNO",
                 "SecurityId": row["identity"].split(":")[1]}
                for row in batch],
        })
    return messages


def decode_quote_frames(blob: bytes) -> list[dict]:
    """Decode official v2 binary Quote(4), OI(5); never guess other bodies.

    One WebSocket frame may contain multiple concatenated Dhan packets.
    Exchange last-trade timestamp exists only on quotes, not OI packets.
    """
    if not isinstance(blob, bytes) or len(blob) > MAX_FRAME_BYTES:
        raise ValueError("Unsupported Dhan market feed frame")
    out = []
    at = 0
    while at < len(blob):
        if len(blob)-at < 8:
            raise ValueError("Truncated Dhan 8-byte feed header")
        code, length, segment, secid = struct.unpack_from("<BHBI", blob, at)
        if length < 8 or at+length > len(blob):
            raise ValueError("Invalid source packet length")
        raw = blob[at:at+length]
        if segment == 2 and secid > 0 and code == 4:
            if length != 50:
                raise ValueError("Invalid Dhan Quote packet size")
            (ltp, ltq, ltt, atp, volume, sell_quantity, buy_quantity,
             day_open, day_close, day_high, day_low) = struct.unpack_from(
                 "<fHIfIIIffff", raw, 8)
            if (math.isfinite(ltp) and ltp > 0 and ltt >= 1_400_000_000
                    and math.isfinite(atp) and volume >= 0):
                out.append({
                    "kind": "quote", "security_id": str(secid),
                    "price": round(float(ltp), 4), "ltq": int(ltq),
                    "trade_epoch": int(ltt), "volume": int(volume),
                    "sell_quantity": int(sell_quantity),
                    "buy_quantity": int(buy_quantity),
                    "packet_sha256": sha256(raw).hexdigest(),
                })
        elif segment == 2 and secid > 0 and code == 5:
            if length != 12:
                raise ValueError("Invalid Dhan OI packet size")
            out.append({"kind": "oi", "security_id": str(secid),
                        "oi": struct.unpack_from("<I", raw, 8)[0],
                        "packet_sha256": sha256(raw).hexdigest()})
        # Prev close, market status, index response and disconnect messages
        # are not live option trades and never converted into quote events.
        at += length
    return out


def _init_storage() -> None:
    global STORAGE_INITIALIZED
    with STORAGE_LOCK:
        if STORAGE_INITIALIZED and live_market.shared_market_data.database_path().is_file():
            return
        live_market._init_db()
        with live_market._database() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS dhan_option_live_events(
                identity TEXT NOT NULL,
                received_utc TEXT NOT NULL,
                exchange_trade_utc TEXT,
                kind TEXT NOT NULL CHECK(kind IN ('quote','oi')),
                price REAL, volume INTEGER, open_interest INTEGER,
                last_trade_quantity INTEGER,
                packet_sha256 TEXT NOT NULL,
                session_id TEXT NOT NULL,
                PRIMARY KEY(identity,received_utc,packet_sha256)
            );
            CREATE INDEX IF NOT EXISTS dhan_live_quote_by_contract
              ON dhan_option_live_events(identity,received_utc);
            CREATE INDEX IF NOT EXISTS dhan_live_quote_by_session
              ON dhan_option_live_events(session_id,received_utc);
            CREATE INDEX IF NOT EXISTS dhan_live_quote_received
              ON dhan_option_live_events(received_utc);
            """)
        STORAGE_INITIALIZED = True


def _ingest(event: dict, received: datetime, session: str) -> None:
    """Keep original received quote events; score only fresh real trade changes."""
    secid = event["security_id"]
    identity = "NSE_FNO:" + secid
    received_iso = _iso(received)
    with LOCK:
        contract = CATALOG.get(identity)
        if contract is None:
            return
        previous = LATEST.get(identity, {})
        entry = dict(previous)
        entry.update({
            "identity": identity, "strike": contract["strike"],
            "expiry": contract["expiry"], "option_type": contract["option_type"],
            "lot_size": contract["lot_size"],
            "last_packet_received_utc": received_iso,
        })
        should_store = True
        if event["kind"] == "quote":
            # A source Quote packet may legitimately carry a Dhan last trade
            # from hours ago. Distinguish packet DELIVERY from a RECENT trade.
            # Do not turn old last-trade prices into new timestamped trades.
            entry["last_quote_packet_received_utc"] = received_iso
            if event["packet_sha256"] == previous.get("packet_sha256"):
                should_store = False
                STATUS["unchanged_quote_packets"] += 1
            event_epoch = event["trade_epoch"]
            event_age = received.timestamp()-event_epoch
            fresh = -5 <= event_age <= MAX_TRADE_LAG_SECONDS
            if fresh and should_store and (not previous.get("trade_epoch")
                          or event_epoch >= previous["trade_epoch"]):
                entry.update({
                    "price": event["price"], "volume": event["volume"],
                    "last_trade_quantity": event["ltq"],
                    "trade_epoch": event_epoch,
                    "quote_received_utc": received_iso,
                })
                prior = HISTORY.setdefault(identity, deque(
                    maxlen=MAX_EVENTS_PER_CONTRACT))
                # Distinct original packets, not polling repeats.
                if (not previous.get("packet_sha256")
                        or event["packet_sha256"] != previous["packet_sha256"]):
                    prior.append((received.timestamp(), event_epoch,
                                  event["price"], event["volume"]))
                # Retain the last pre-window source trade as a real
                # comparison anchor. Deleting every older print made a
                # genuine 5-minute return impossible to calculate.
                cutoff = event_epoch - SCORE_WINDOW_SECONDS - 30
                while len(prior) > 1 and prior[1][1] <= cutoff:
                    prior.popleft()
                entry["packet_sha256"] = event["packet_sha256"]
                score = _opportunity(prior)
                entry.update(score)
            elif not fresh:
                STATUS["ignored_stale_trades"] += 1
                should_store = False
            elif previous.get("trade_epoch") and event_epoch < previous["trade_epoch"]:
                STATUS["ignored_stale_trades"] += 1
                should_store = False
            STATUS["quote_packets"] += 1
            STATUS["last_quote_received_utc"] = received_iso
        else:
            if event["oi"] == previous.get("open_interest"):
                should_store = False
                STATUS["unchanged_oi_packets"] += 1
            else:
                entry["open_interest"] = event["oi"]
                entry["oi_received_utc"] = received_iso
            STATUS["oi_packets"] += 1
        LATEST[identity] = entry
        # The owning read-only socket worker already checks persisted consent
        # before decoding the frame. Avoid opening a JSON settings file once
        # per instrument packet across thousands of active contracts.
        if should_store:
            row = (
                identity, received_iso,
                _iso(datetime.fromtimestamp(event["trade_epoch"],timezone.utc))
                    if event["kind"] == "quote" else None,
                event["kind"], event.get("price"), event.get("volume"),
                event.get("oi"), event.get("ltq"),
                event["packet_sha256"], session,
            )
            try:
                WRITES.put_nowait(row)
            except Full:
                STATUS["dropped_events"] += 1


def _opportunity(history: deque) -> dict:
    """Research movement over *observed* Dhan trade times only.

    An option trading for seven seconds has an observed seven-second move,
    NOT a measured 60-second or 300-second return. Longer windows require
    original trades straddling their respective horizons. Never interpolate.
    """
    empty = {"score": 0., "move_60s_pct": None, "move_5m_pct": None,
             "observed_change_pct": None, "observed_span_seconds": 0,
             "volume_increase": 0, "distinct_trade_times": 0}
    if len(history) < 2:
        return empty
    first, last = history[0], history[-1]
    trade_times = {item[1] for item in history}
    span = max(0, last[1] - first[1])
    if (len(trade_times) < 2 or span <= 0
            or first[2] <= 0 or last[2] <= 0):
        return {**empty, "observed_span_seconds": span,
                "distinct_trade_times": len(trade_times)}
    volume_gain = max(0, last[3] - first[3])
    observed = round((last[2] / first[2] - 1) * 100, 2)

    def window_change(seconds: int, max_anchor_lag: int) -> float | None:
        threshold = last[1] - seconds
        anchors = [row for row in history
                   if row[1] <= threshold
                   and threshold - row[1] <= max_anchor_lag
                   and row[2] > 0]
        if not anchors:
            return None
        anchor = max(anchors, key=lambda row: row[1])
        return round((last[2] / anchor[2] - 1) * 100, 2)

    move60 = window_change(60, 15)
    move300 = window_change(300, 30)
    # A confirmed sub-minute jump (e.g. 99 -> 500) remains visible and
    # research-rankable without falsely claiming five minutes of history.
    importance = max(abs(observed),
                     abs(move60) if move60 is not None else 0.,
                     abs(move300) if move300 is not None else 0.)
    score = round(min(100., max(0.,
                  (importance - 5) * 2 + min(20., volume_gain / 1000.))), 2)
    return {"score": score, "move_60s_pct": move60,
            "move_5m_pct": move300, "observed_change_pct": observed,
            "observed_span_seconds": span, "volume_increase": volume_gain,
            "distinct_trade_times": len(trade_times)}


def _eligible_for_depth(row: dict) -> tuple[bool, str]:
    """Source-activity filter, *not* a liquidity/fill or profitability claim.

    Every option stays in the full-universe stream and in saved history.
    Penny-print percentage spikes must not consume scarce deep-book slots.
    """
    price = row.get("price")
    span = row.get("observed_span_seconds", 0)
    volume_gain = row.get("volume_increase", 0)
    if not isinstance(price, (int, float)) or not 25 <= price <= 2000:
        return False, "premium_outside_25_to_2000"
    if not isinstance(span, (int, float)) or span < 1:
        return False, "insufficient_distinct_trade_times"
    if not isinstance(volume_gain, (int, float)) or volume_gain < 100:
        return False, "insufficient_recent_volume_change"
    if row.get("score", 0) < 12:
        return False, "below_activity_threshold"
    return True, "passes_source_activity_screen"


def _ranked_candidates(limit: int, *, for_depth: bool) -> list[dict]:
    """Separate all observed movers from candidates for 20-level promotion."""
    now = _utc()
    if not isinstance(limit, int) or not 0 <= limit <= 80:
        raise ValueError("Select up to 80 source-observed option candidates")
    with LOCK:
        rows = []
        for row in LATEST.values():
            if not row.get("quote_received_utc") or row.get("score", 0) < 12:
                continue
            age = (now-datetime.fromisoformat(
                row["quote_received_utc"])).total_seconds()
            if not 0 <= age <= 45:
                continue
            eligible, reason = _eligible_for_depth(row)
            if for_depth and not eligible:
                continue
            fields = ("identity", "expiry", "strike", "option_type",
                      "price", "volume", "open_interest", "score",
                      "move_60s_pct", "move_5m_pct",
                      "observed_change_pct", "observed_span_seconds",
                      "distinct_trade_times", "volume_increase",
                      "quote_received_utc")
            candidate = {key: row.get(key) for key in fields}
            candidate.update(
                {"eligible_for_depth": eligible, "screen_reason": reason})
            rows.append(candidate)
        return sorted(rows, key=lambda row:
                      (-int(row["eligible_for_depth"]), -row["score"],
                       -row["volume_increase"], row["identity"]))[:limit]


def ranked_opportunities(limit: int = 40) -> list[dict]:
    """ALL source-observed movers, including penny options for research."""
    return _ranked_candidates(limit, for_depth=False)


def ranked_depth_candidates(limit: int = 40) -> list[dict]:
    """Only source-activity-screened movers may replace rotating depth IDs."""
    return _ranked_candidates(limit, for_depth=True)


def _write_batches(stop: Event) -> None:
    saved = 0
    day = None
    try:
        _init_storage()
        while not stop.is_set() or not WRITES.empty():
            current_day = _utc().astimezone(auto.IST).date()
            if current_day != day:
                day = current_day
                midnight_ist = datetime.combine(
                    day, datetime.min.time(), tzinfo=auto.IST)
                with live_market._database() as db:
                    saved = int(db.execute(
                        "SELECT COUNT(*) FROM dhan_option_live_events "
                        "WHERE received_utc>=? AND received_utc<?",
                        (_iso(midnight_ist), _iso(midnight_ist +
                            timedelta(days=1)))).fetchone()[0])
            batch = []
            try:
                batch.append(WRITES.get(timeout=.25))
            except Empty:
                continue
            while len(batch) < 250:
                try:
                    batch.append(WRITES.get_nowait())
                except Empty:
                    break
            if saved + len(batch) > MAX_DAILY_EVENTS:
                with LOCK:
                    STATUS["dropped_events"] += len(batch)
                    STATUS["state"] = "recording_storage_cap_reached"
                continue
            try:
                with live_market._database() as db:
                    before = db.total_changes
                    db.executemany("""
                      INSERT OR IGNORE INTO dhan_option_live_events
                      (identity,received_utc,exchange_trade_utc,kind,price,
                       volume,open_interest,last_trade_quantity,packet_sha256,session_id)
                      VALUES(?,?,?,?,?,?,?,?,?,?)""",batch)
                    inserted = db.total_changes-before
                saved += inserted
                with LOCK:
                    STATUS["stored_events"] += inserted
            except sqlite3.Error:
                # Fail closed and count what this process could not persist.
                with LOCK:
                    STATUS["dropped_events"] += len(batch)
                    STATUS["state"] = "storage_write_error"
    except (OSError, sqlite3.Error, ValueError):
        _set(state="storage_unavailable",last_error="Original option stream storage unavailable")


def _session_rollover() -> None:
    with LOCK:
        LATEST.clear()
        HISTORY.clear()
        STATUS.update({
            "quote_packets": 0, "oi_packets": 0,
            "stored_events": 0, "dropped_events": 0,
            "rejected_frames": 0, "ignored_stale_trades": 0,
            "unchanged_quote_packets": 0, "unchanged_oi_packets": 0,
            "last_quote_received_utc": None,
        })


def _run(stop: Event) -> None:
    root = auto._root()
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / "banknifty_full_option_feed.lock"
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            _set(state="another_local_worker",last_error="Another QuantLab option feed is active")
            return
        failures = 0
        day = ""
        writer_stop = Event()
        writer = Thread(target=_write_batches,args=(writer_stop,),
                        daemon=True,name="quantlab-full-option-feed-writer")
        writer.start()
        try:
            while not stop.is_set():
                if not _armed():
                    _set(state="disabled",connected=False)
                    return
                if not auto._market_open():
                    _set(state="armed_waiting_for_nse_hours",connected=False)
                    stop.wait(15)
                    continue
                # Four automatic depth sockets + one option quote socket = five.
                # The old manual ticker/depth pair cannot also run concurrently.
                if live_market.status().get("active"):
                    _set(state="manual_live_session_conflict",connected=False,
                         last_error="Stop the separate manual Trading Cockpit live stream to release the fifth Dhan socket")
                    stop.wait(10)
                    continue
                current_day = _utc().astimezone(auto.IST).date().isoformat()
                if day != current_day:
                    day = current_day
                    _session_rollover()
                try:
                    contracts, excess = _discover()
                    selected = {row["identity"]:row for row in contracts}
                    with LOCK:
                        CATALOG.clear()
                        CATALOG.update(selected)
                    _set(state="connecting",last_error=None,
                         requested_contracts=len(contracts),source_contracts=len(contracts)+excess,
                         unsubscribed_due_to_capacity=excess)
                    token, client = option_chain_live._credentials()
                    url = ("wss://api-feed.dhan.co?version=2&token=" + quote(token,safe="")
                           + "&clientId="+quote(client,safe="")+"&authType=2")
                    from websockets.sync.client import connect
                    session = "options_"+day.replace("-","")+"_"+str(int(time.time()))
                    with connect(url,open_timeout=12,close_timeout=3,
                                 max_size=MAX_FRAME_BYTES) as socket:
                            for msg in _subscribe_batches(contracts):
                                socket.send(json.dumps(msg))
                                if stop.is_set():break
                                stop.wait(.03)
                            _set(state="subscribed_awaiting_quotes",connected=True,
                                 session_id=session)
                            failures = 0
                            until = time.monotonic()+DISCOVER_SECONDS
                            while not stop.is_set() and _armed() and auto._market_open():
                                if os.getenv("DHAN_ACCESS_TOKEN","").strip()!=token:
                                    break
                                if time.monotonic() >= until:
                                    updated, _ = _discover()
                                    if [row["identity"] for row in updated] != [
                                            row["identity"] for row in contracts]:
                                        break
                                    until = time.monotonic()+DISCOVER_SECONDS
                                try:
                                    payload = socket.recv(timeout=1)
                                except TimeoutError:
                                    continue
                                if not isinstance(payload,bytes):
                                    continue
                                received = _utc()
                                try:
                                    decoded = decode_quote_frames(payload)
                                except ValueError:
                                    with LOCK:
                                        STATUS["rejected_frames"]+=1
                                    continue
                                for event in decoded:
                                    _ingest(event,received,session)
                                if decoded:
                                    _set(state="streaming_original_quotes")
                    _set(connected=False)
                except Exception as exc:
                    # Never log WebSocket URLs or token-bearing exception strings.
                    failures+=1
                    _set(state="connection_or_source_error",connected=False,
                         last_error="Dhan full-option monitor interrupted ("+
                                    type(exc).__name__+"); retrying safely")
                    stop.wait(min(60,3*2**min(failures,4)))
        finally:
            writer_stop.set()
            writer.join(timeout=15)
            if writer.is_alive():
                _set(state="storage_flush_incomplete",
                     last_error="Pending original price events are still flushing; keep local server running")
    finally:
        with LOCK:
            flushing = STATUS.get("state") == "storage_flush_incomplete"
        if flushing:
            _set(connected=False)
        else:
            _set(connected=False,state="stopped" if not stop.is_set() else "stopping")
        os.close(fd)


def _restart_after_stopped(previous: Thread) -> None:
    previous.join()
    if not SHUTTING_DOWN and _armed():
        resume_if_armed()


def resume_if_armed() -> None:
    global WORKER,STOP,SHUTTING_DOWN
    if not _armed():
        return
    with LOCK:
        SHUTTING_DOWN=False
        if WORKER is not None and WORKER.is_alive():
            if STOP.is_set():
                Thread(target=_restart_after_stopped,args=(WORKER,),
                       daemon=True,name="quantlab-full-option-rearm").start()
            return
        STOP=Event()
        WORKER=Thread(target=_run,args=(STOP,),daemon=True,
                      name="quantlab-banknifty-full-options")
        WORKER.start()


def disarmed() -> None:
    STOP.set()
    _set(state="stopping",connected=False)


def suspend_for_shutdown() -> None:
    global SHUTTING_DOWN
    SHUTTING_DOWN=True
    STOP.set()
    _set(state="local_server_stopping",connected=False)


def status() -> dict:
    now = _utc()
    def recent(stamp: str | None, seconds: int) -> bool:
        if not stamp:
            return False
        try:
            age = (now - datetime.fromisoformat(stamp)).total_seconds()
            return 0 <= age <= seconds
        except (ValueError, TypeError):
            return False

    with LOCK:
        by_expiry: dict[str, dict] = {}
        for identity, contract in CATALOG.items():
            expiry = contract["expiry"]
            row = by_expiry.setdefault(expiry, {
                "expiry": expiry, "subscribed": 0, "with_any_quote": 0,
                "fresh_quote_60s": 0, "with_any_oi": 0,
                "received_quote_packet_ids": 0, "source_quote_60s": 0,
                "stale_quote_packet_only": 0, "never_received_quote_packet": 0,
                "oi_only": 0, "never_quoted": 0,
                "activity_screen_passed_45s": 0})
            row["subscribed"] += 1
            item = LATEST.get(identity, {})
            has_quote = bool(item.get("quote_received_utc"))
            has_source_packet = bool(item.get("last_quote_packet_received_utc"))
            has_oi = bool(item.get("oi_received_utc"))
            row["with_any_quote"] += int(has_quote)
            row["received_quote_packet_ids"] += int(has_source_packet)
            row["source_quote_60s"] += int(
                recent(item.get("last_quote_packet_received_utc"), 60))
            row["stale_quote_packet_only"] += int(
                has_source_packet and not has_quote)
            row["never_received_quote_packet"] += int(not has_source_packet)
            row["fresh_quote_60s"] += int(
                recent(item.get("quote_received_utc"), 60))
            row["with_any_oi"] += int(has_oi)
            row["oi_only"] += int(has_oi and not has_source_packet)
            row["never_quoted"] += int(not has_quote)
            eligible, _ = _eligible_for_depth(item)
            row["activity_screen_passed_45s"] += int(
                eligible and recent(item.get("quote_received_utc"), 45))

        snapshot = dict(STATUS)
        snapshot["observed_contracts"] = sum(
            row["with_any_quote"] for row in by_expiry.values())
        snapshot["recent_price_contracts"] = sum(
            row["fresh_quote_60s"] for row in by_expiry.values())
        snapshot["source_quote_delivered_contracts"] = sum(
            row["received_quote_packet_ids"] for row in by_expiry.values())
        snapshot["recent_source_quote_contracts"] = sum(
            row["source_quote_60s"] for row in by_expiry.values())
        snapshot["stale_source_quote_only_contracts"] = sum(
            row["stale_quote_packet_only"] for row in by_expiry.values())
        snapshot["never_received_source_quote_ids"] = sum(
            row["never_received_quote_packet"] for row in by_expiry.values())
        snapshot["observed_oi_contracts"] = sum(
            row["with_any_oi"] for row in by_expiry.values())
        snapshot["requested_not_yet_quoted"] = sum(
            row["never_quoted"] for row in by_expiry.values())
        snapshot["queue_depth"] = WRITES.qsize()
        snapshot["coverage_by_expiry"] = sorted(
            by_expiry.values(), key=lambda row: row["expiry"])
        snapshot["opportunity_count"] = sum(
            item.get("score", 0) >= 12 and
            recent(item.get("quote_received_utc"), 45)
            for item in LATEST.values())
        snapshot["depth_candidate_count"] = sum(
            _eligible_for_depth(item)[0] and
            recent(item.get("quote_received_utc"), 45)
            for item in LATEST.values())
    return {**snapshot, "armed": _armed(),
            "full_universe_consent": _consented(),
            "depth_armed": bool(auto._config()["enabled"]),
            "market_regular_hours": auto._market_open(),
            "source": "Dhan v2 original NSE_FNO Quote(4) and OI(5) packets",
            "read_only": True, "shared_library": "dhan_shared",
            "continuous_20_depth_for_all": False,
            "note": "All contracts remain subscribed and recorded. "
                    "Dhan does not guarantee source packet emission for "
                    "silent contracts; each expiry has separate observed "
                    "quote and OI evidence. Price movers and candidates "
                    "for detailed-book promotion are not identical."}


def contracts_page(offset: int = 0, limit: int = 100) -> dict:
    if not isinstance(offset,int) or offset<0 or offset>MAX_INSTRUMENTS:
        raise ValueError("Invalid contract page offset")
    if not 1<=limit<=MAX_DISPLAY:
        raise ValueError("Request 1–100 contracts per page")
    with LOCK:
        result=[]
        for identity, contract in sorted(CATALOG.items(),
                                        key=lambda pair:(
                                            pair[1]["expiry"],pair[1]["strike"],
                                            pair[1]["option_type"])):
            merged={k:contract.get(k) for k in
                    ("identity","expiry","strike","option_type","lot_size")}
            latest=LATEST.get(identity,{})
            for key in ("price","volume","open_interest","score",
                        "move_60s_pct","move_5m_pct","volume_increase",
                        "quote_received_utc"):
                merged[key]=latest.get(key)
            result.append(merged)
        count=len(result)
    return {"total":count,"offset":offset,"limit":limit,
            "contracts":result[offset:offset+limit],
            "original_source_only":True}


def saved_history(identity: str, limit: int = 250) -> dict:
    if not auto.SAFE_ID.fullmatch(identity) or not 1<=limit<=1000:
        raise ValueError("Choose an exact verified NSE_FNO identity and <=1000 records")
    _init_storage()
    with live_market._database() as db:
        rows=db.execute("""
          SELECT received_utc,exchange_trade_utc,price,volume,open_interest,kind
            FROM dhan_option_live_events
           WHERE identity=? ORDER BY received_utc DESC LIMIT ?""",
            (identity,limit)).fetchall()
    return {"identity":identity,"events":[{
        "received_utc":row[0],"exchange_trade_utc":row[1],
        "price":row[2],"volume":row[3],"open_interest":row[4],
        "kind":row[5]} for row in reversed(rows)],
        "source":"Original Dhan Quote/OI received packets; incomplete when disconnected."}
