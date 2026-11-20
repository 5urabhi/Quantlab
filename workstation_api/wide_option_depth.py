"""Wide read-only BANKNIFTY 20-level capture: 100 contracts per ATM wing.

100 *option contracts* above the nearest listed ATM strike and 100 below,
each wing balanced 50 CE + 50 PE across 50 real strike levels. Never infer
or fabricate contracts, quotes, prices, depth packets, or broker fills.

Dhan permits 50 instruments per twentydepth WebSocket. At most FOUR sockets
are opened (200 instruments total), leaving a fifth connection for another
live feed. All selected instruments are subscribed simultaneously; updates
are stored at bounded, per-contract rates in the existing shared database.
"""
from __future__ import annotations

from datetime import datetime
from queue import Empty, Full, Queue
from threading import Event, RLock, Thread
import json
import math
import os
import time

from . import auto_option_depth as auto
from . import market_depth, option_chain_live

MODE = "atm_contracts_100_each"
CONTRACTS_PER_WING = 100
STRIKE_LEVELS_PER_WING = CONTRACTS_PER_WING // 2
MAX_CONNECTIONS = 4
PER_CONNECTION = 50
MAX_CONTRACTS = MAX_CONNECTIONS * PER_CONNECTION
NEAR_ATM_FAST_SECONDS = 3
SOCKET_RECV_LIMIT = 1_000_000
QUEUE_MAX = 2500


def _verified(quote: dict, expiry: str) -> bool:
    identity = quote.get("identity")
    lot = quote.get("lot_size")
    ltp = quote.get("ltp")
    strike = quote.get("strike")
    return bool(
        quote.get("contract_master_verified")
        and isinstance(identity, str) and auto.SAFE_ID.fullmatch(identity)
        and quote.get("expiry") == expiry
        and quote.get("option_type") in ("CE", "PE")
        and isinstance(lot, int) and lot > 0
        and isinstance(ltp, (int, float)) and math.isfinite(ltp) and ltp > 0
        and isinstance(strike, (int, float)) and math.isfinite(strike) and strike > 0
    )


def select_atm_contracts(chain: dict, cfg: dict, previous_ids=()) -> list[dict]:
    """Select real CE+PE pairs from exactly 50 listed strikes in each direction.

    The nearest *listed* strike is the ATM anchor. Do not assume a constant
    strike increment; some expiries can have different listing intervals.
    Only strikes with both independently verified CE and PE original source
    identities are counted. Missing contracts are reported, not invented.
    """
    spot = chain.get("underlying_spot")
    expiry = chain.get("expiry")
    if (not isinstance(spot, (int, float)) or not math.isfinite(spot)
            or spot <= 0 or not isinstance(expiry, str) or not expiry):
        raise ValueError("BANKNIFTY original chain has no valid spot/expiry")
    pairs: dict[float, dict[str, dict]] = {}
    for q in chain.get("contracts", []):
        if not isinstance(q, dict) or not _verified(q, expiry):
            continue
        strike = float(q["strike"])
        side = q["option_type"]
        # Never select ambiguous duplicate source observations for one term.
        if side not in pairs.setdefault(strike, {}):
            pairs[strike][side] = q
    if not pairs:
        return []
    atm = min(pairs, key=lambda strike: (abs(strike - spot), strike))
    above = sorted((strike for strike, sides in pairs.items()
                    if strike > atm and "CE" in sides and "PE" in sides))
    below = sorted((strike for strike, sides in pairs.items()
                    if strike < atm and "CE" in sides and "PE" in sides),
                   reverse=True)
    chosen_above = above[:STRIKE_LEVELS_PER_WING]
    chosen_below = below[:STRIKE_LEVELS_PER_WING]
    selected = []
    used_ids = set()
    for wing, strikes in (("above", chosen_above), ("below", chosen_below)):
        for rank, strike in enumerate(strikes):
            for side in ("CE", "PE"):
                q = pairs[strike][side]
                identity = q["identity"]
                if identity in used_ids:
                    continue
                used_ids.add(identity)
                selected.append({
                    "identity": identity, "security_id": identity.split(":")[1],
                    "side": side, "strike": strike, "expiry": expiry,
                    "lot_size": q["lot_size"], "ltp": float(q["ltp"]),
                    "bid": q.get("bid"), "ask": q.get("ask"),
                    "volume": q.get("volume") if isinstance(q.get("volume"), int) else 0,
                    "chain_received_utc": chain.get("received_utc"),
                    "wing": wing, "atm_strike": atm,
                    "priority_depth": rank == 0,
                })
    # Deterministic packing and no hidden substitution across wings.
    return selected


def socket_groups(selected: list[dict]) -> list[list[dict]]:
    """Four bounded 50-contract subscriptions, no duplicate IDs."""
    if len(selected) > MAX_CONTRACTS:
        raise ValueError("200-contract limit exceeded")
    ids = [c["security_id"] for c in selected]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate Dhan security ID in 20-level subscription")
    if any(not isinstance(x, str) or not x.isdigit() for x in ids):
        raise ValueError("Unverified Dhan security ID")
    return [selected[i:i + PER_CONNECTION]
            for i in range(0, len(selected), PER_CONNECTION)]


def subscription(group: list[dict]) -> dict:
    """Provider documented RequestCode=23, maximum 50 instruments."""
    if not 1 <= len(group) <= PER_CONNECTION:
        raise ValueError("Dhan twentydepth supports 1-50 IDs per socket")
    return {"RequestCode": 23, "InstrumentCount": len(group),
            "InstrumentList": [
                {"ExchangeSegment": "NSE_FNO", "SecurityId": item["security_id"]}
                for item in group]}


def _read_socket(index: int, group: list[dict], url: str,
                 stop: Event, abort: Event, inbox: Queue,
                 connected: set[int], connected_lock: RLock,
                 sample_seconds: int) -> None:
    """Read one WebSocket, pair original book halves, enqueue sampled pairs.

    DB writes are performed exclusively by the coordinator to prevent four
    WebSocket readers fighting over SQLite write locks.
    """
    from websockets.sync.client import connect
    chosen = {c["security_id"]: c for c in group}
    pending: dict = {}
    last_emitted: dict[str, float] = {}
    try:
        with connect(url, open_timeout=12, close_timeout=3,
                     max_size=SOCKET_RECV_LIMIT) as socket:
            socket.send(json.dumps(subscription(group)))
            with connected_lock:
                connected.add(index)
                auto._status_update(sockets_connected=len(connected),
                                    connected=True,
                                    state="connected_waiting_for_packets")
            while not stop.is_set() and not abort.is_set() and auto._market_open():
                try:
                    raw = socket.recv(timeout=1)
                except TimeoutError:
                    continue
                if not isinstance(raw, bytes):
                    continue
                now = auto._now()
                books = auto._paired_books(raw, chosen, pending, now)
                if not books:
                    continue
                with auto.LOCK:
                    auto.STATE["received_pairs"] += len(books)
                    auto.STATE["last_packet_utc"] = now.isoformat()
                stamp = time.monotonic()
                for book, candidate in books:
                    interval = (NEAR_ATM_FAST_SECONDS if candidate["priority_depth"]
                                else sample_seconds)
                    key = candidate["identity"]
                    if stamp - last_emitted.get(key, 0) < interval:
                        continue
                    try:
                        inbox.put_nowait((book, candidate))
                        last_emitted[key] = stamp
                    except Full:
                        with auto.LOCK:
                            auto.STATE["dropped_depth_samples"] = (
                                auto.STATE.get("dropped_depth_samples", 0) + 1)
    except Exception as exc:
        # The WebSocket URL contains an access token: never log exception text.
        if not stop.is_set() and auto._market_open():
            auto._status_update(last_error="Dhan 20-level socket " +
                                str(index + 1) + " interrupted (" +
                                type(exc).__name__ + "); reconnecting",
                                state="connection_or_source_error")
            abort.set()
    finally:
        with connected_lock:
            connected.discard(index)
            auto._status_update(sockets_connected=len(connected),
                                connected=bool(connected))


def _select(cfg: dict, previous_ids=()) -> list[dict]:
    auto._refresh_master_if_needed()
    expiries = option_chain_live.expiries()
    chain = option_chain_live.chain(expiries["nearest_expiry"], force_refresh=True)
    age = abs((auto._now() - datetime.fromisoformat(chain["received_utc"])).total_seconds())
    if age > 90:
        raise ValueError("Original Dhan BANKNIFTY chain is stale")
    selected = select_atm_contracts(chain, cfg, previous_ids)
    counts = {"above": 0, "below": 0}
    for c in selected:
        counts[c["wing"]] += 1
    missing = []
    for wing in ("above", "below"):
        if counts[wing] < CONTRACTS_PER_WING:
            missing.append(wing + ": " + str(counts[wing]) + "/100 verified contracts")
    auto._status_update(
        last_chain_utc=chain["received_utc"],
        chain_spot=chain["underlying_spot"],
        current_expiry=chain["expiry"],
        atm_strike=selected[0]["atm_strike"] if selected else None,
        contracts_above=counts["above"],
        contracts_below=counts["below"],
        selection_warning=(
            "Incomplete source-verified ATM wings (" + ", ".join(missing) +
            "); missing depth is never fabricated" if missing else None),
    )
    return selected


def run(stop: Event) -> None:
    """Record 100 contracts above and 100 below ATM; stop on quota or errors."""
    failures = 0
    previous: list[dict] = []
    session_id: str | None = None
    daily_saved = 0
    from uuid import uuid4
    while not stop.is_set():
        cfg = auto._config()
        if not cfg["enabled"] or cfg.get("selection_mode") != MODE:
            auto._status_update(connected=False, state="disabled")
            return
        if not auto._market_open():
            auto._status_update(state="armed_waiting_for_nse_hours",
                                connected=False, sockets_connected=0)
            stop.wait(20)
            continue
        day = auto._now().astimezone(auto.IST).strftime("%Y%m%d")
        if session_id is None or not session_id.startswith("auto20_" + day):
            session_id = "auto20_" + day + "_" + uuid4().hex[:10]
            daily_saved = auto._daily_count(auto._now())
            previous = []
            auto._status_update(
                session_id=session_id, snapshots_saved=0, received_pairs=0,
                selection_events=0, invalid_pairs=0, latest={},
                contracts=[], sockets_connected=0, dropped_depth_samples=0,
                contracts_above=0, contracts_below=0, last_error=None)
        if daily_saved >= auto.MAX_DAILY_SNAPSHOTS:
            auto._status_update(state="daily_storage_limit_reached",
                                connected=False)
            stop.wait(45)
            continue
        try:
            auto._status_update(state="selecting_verified_ce_pe", connected=False)
            selected = _select(cfg, [c["identity"] for c in previous])
            if not selected:
                auto._status_update(state="no_eligible_option_contracts",
                                    contracts=[], last_error=(
                                        "No complete real Dhan CE/PE strike pairs "
                                        "near BANKNIFTY ATM; retrying."))
                stop.wait(30)
                continue
            groups = socket_groups(selected)
            auto._selection_receipt(session_id, selected)
            previous = selected
            with auto.LOCK:
                auto.STATE["contracts"] = selected
                auto.STATE["selection_events"] += 1
                auto.STATE["last_error"] = None
                auto.STATE["sockets_requested"] = len(groups)
            token, client = option_chain_live._credentials()
            url = market_depth._live_endpoint(20, client, token)
            abort = Event()
            inbox: Queue = Queue(maxsize=QUEUE_MAX)
            connected: set[int] = set()
            connected_lock = RLock()
            workers = [
                Thread(target=_read_socket,
                       args=(i, group, url, stop, abort, inbox, connected,
                             connected_lock, cfg["sample_seconds"]),
                       daemon=True, name="quantlab-banknifty-depth-" + str(i))
                for i, group in enumerate(groups)]
            for worker in workers:
                worker.start()
            started = time.monotonic()
            next_refresh = started + auto.CHAIN_REFRESH_SECONDS
            last_seen = started
            try:
                while not stop.is_set() and not abort.is_set() and auto._market_open():
                    if daily_saved >= auto.MAX_DAILY_SNAPSHOTS:
                        auto._status_update(state="daily_storage_limit_reached")
                        break
                    if os.getenv("DHAN_ACCESS_TOKEN", "").strip() != token:
                        break  # Reconnect using explicitly renewed Dhan credentials.
                    if time.monotonic() >= next_refresh or auto._config() != cfg:
                        updated_cfg = auto._config()
                        updated = _select(updated_cfg,
                                          tuple(c["identity"] for c in selected))
                        if ([c["identity"] for c in updated] !=
                            [c["identity"] for c in selected] or updated_cfg != cfg):
                            previous = selected
                            break  # Close old sockets before subscribing new IDs.
                        for old, newer in zip(selected, updated):
                            old.update(newer)
                        next_refresh = time.monotonic() + auto.CHAIN_REFRESH_SECONDS
                    try:
                        book, candidate = inbox.get(timeout=1)
                    except Empty:
                        if time.monotonic() - last_seen > 35:
                            auto._status_update(state="connected_no_depth_packets",
                                last_error="No fresh paired Dhan 20-level packets "
                                           "in 35 seconds; inspect source access.")
                        continue
                    last_seen = time.monotonic()
                    feature = auto._features(book, candidate, cfg["lots"])
                    if auto._store_book(session_id, book, feature):
                        daily_saved += 1
                        with auto.LOCK:
                            auto.STATE["snapshots_saved"] += 1
                            auto.STATE["latest"][candidate["identity"]] = {
                                **feature,
                                "best_bid": book["bid"][0]["price"],
                                "best_ask": book["ask"][0]["price"],
                                "bid_levels": len(book["bid"]),
                                "ask_levels": len(book["ask"]),
                                "source": "original_dhan_twentydepth",
                            }
                            auto.STATE["state"] = "recording_original_depth"
                            auto.STATE["last_error"] = None
            finally:
                abort.set()
                for worker in workers:
                    worker.join(timeout=4)
                auto._status_update(connected=False, sockets_connected=0)
            failures = 0
        except Exception as exc:
            failures += 1
            auto._status_update(
                state="connection_or_source_error", connected=False,
                sockets_connected=0,
                last_error="Wide Dhan 20-level capture interrupted (" +
                           type(exc).__name__ + "); retrying safely.")
            stop.wait(min(auto.MAX_RECONNECT_DELAY_SECONDS,
                          3 * (2 ** min(failures, 4))))
