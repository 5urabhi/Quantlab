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


def _armed() -> bool:
    return bool(auto._config()["enabled"])


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
    qualified = [rows[0] for key, rows in by_term.items()
                 if len(rows) == 1 and len(by_id[rows[0]["identity"]]) == 1]
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
                cutoff = received.timestamp()-SCORE_WINDOW_SECONDS
                while prior and prior[0][0] < cutoff:
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
        if _armed() and should_store:
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
    if len(history) < 2:
        return {"score": 0., "move_60s_pct": None,
                "move_5m_pct": None, "volume_increase": 0}
    now = history[-1][0]
    ref_60 = next((record for record in history if record[0] >= now-60),
                  history[0])
    ref_300 = history[0]
    last = history[-1]
    if last[1] < ref_300[1] or (
            last[1] == ref_300[1] and last[3] <= ref_300[3]):
        return {"score": 0., "move_60s_pct": None,
                "move_5m_pct": None, "volume_increase": 0}
    change60 = (last[2]/ref_60[2]-1)*100 if ref_60[2] > 0 else 0.
    change300 = (last[2]/ref_300[2]-1)*100 if ref_300[2] > 0 else 0.
    gain_volume = max(0, last[3]-ref_300[3])
    # A new Dhan last-trade timestamp is itself source evidence even if
    # aggregate volume has not yet advanced in the broker's quote packet.
    # Volume confirms activity, but cannot veto an observed option price jump.
    importance = max(abs(change60),abs(change300))
    score = round(min(100., max(0., (importance-5)*2
                   + min(20., gain_volume/1000.))), 2)
    return {"score": score, "move_60s_pct": round(change60,2),
            "move_5m_pct": round(change300,2),
            "volume_increase": gain_volume}


def ranked_opportunities(limit: int = 40) -> list[dict]:
    """Only truly observed, fresh moving option quotes can win depth slots."""
    now = _utc()
    with LOCK:
        rows = []
        for row in LATEST.values():
            if not row.get("quote_received_utc") or row.get("score", 0) < 12:
                continue
            age = (now-datetime.fromisoformat(row["quote_received_utc"])).total_seconds()
            if 0 <= age <= 45:
                rows.append({k: row.get(k) for k in
                    ("identity","expiry","strike","option_type","price",
                     "volume","open_interest","score","move_60s_pct",
                     "move_5m_pct","volume_increase","quote_received_utc")})
        return sorted(rows,key=lambda r:(-r["score"],r["identity"]))[:max(0,min(limit,80))]


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
        _set(connected=False,state="stopped" if not stop.is_set() else "stopping")
        os.close(fd)


def resume_if_armed() -> None:
    global WORKER,STOP,SHUTTING_DOWN
    if not _armed():
        return
    with LOCK:
        SHUTTING_DOWN=False
        if WORKER is not None and WORKER.is_alive():
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
    with LOCK:
        recent = sum(1 for item in LATEST.values()
                     if item.get("quote_received_utc") and
                     0 <= (now-datetime.fromisoformat(
                         item["quote_received_utc"])).total_seconds() <= 60)
        snapshot = dict(STATUS)
        snapshot["observed_contracts"] = sum(
            bool(entry.get("quote_received_utc")) for entry in LATEST.values())
        snapshot["recent_price_contracts"] = recent
        snapshot["queue_depth"] = WRITES.qsize()
        snapshot["opportunity_count"] = sum(
            item.get("score",0)>=12 and bool(item.get("quote_received_utc"))
            for item in LATEST.values())
    return {**snapshot,"armed":_armed(),"market_regular_hours":auto._market_open(),
            "source":"Dhan v2 original NSE_FNO Quote(4) and OI(5) packets",
            "read_only":True,"shared_library":"dhan_shared",
            "continuous_20_depth_for_all":False,
            "note":"Subscribed does not prove trades or packets for each contract; "
                   "venue-silent options and source gaps remain explicit."}


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
