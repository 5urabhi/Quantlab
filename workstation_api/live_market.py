"""Live Dhan ticker + 20-level NSE order book for QuantLab Trading Copilot.

A single read-only local session uses two broker WebSockets: ticker prices
(IDX_I spot plus optionally a NSE security) and depth (only NSE_EQ/NSE_FNO).
Verified observations are appended to the existing shared_market.sqlite3.
No OHLCV history is fabricated, no order API is imported, and no credentials
or authenticated URLs are returned, persisted or logged.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from contextlib import contextmanager
from hashlib import sha256
from threading import Event, RLock, Thread, Condition
from urllib.parse import quote
from zoneinfo import ZoneInfo
import json
import math
import os
import sqlite3
import struct
import time
import uuid

from . import index_spot, market_depth, service, shared_market_data

IST = ZoneInfo("Asia/Kolkata")
LOCK = RLock()
CHANGED = Condition(LOCK)
ACTIVE: dict = {}
WORKERS: list[Thread] = []
STOP = Event()
MAX_SAVED_BOOKS = 30_000  # session safety bound; display keeps receiving
STALE_AFTER_SECONDS = 8
MAX_TICK_LATENCY_SECONDS = 45
DB_INITIALIZED = False
DB_SETUP_LOCK = RLock()
SESSION_ID = ""
INDEX = {"INDEX:BANKNIFTY": ("IDX_I", "25"),
         "INDEX:NIFTY50": ("IDX_I", "13")}
SEGMENT_CODE = {0: "IDX_I", 1: "NSE_EQ", 2: "NSE_FNO", 4: "BSE_EQ"}


@contextmanager
def _database():
    path = shared_market_data.database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _init_db() -> None:
    global DB_INITIALIZED
    with DB_SETUP_LOCK:
        if DB_INITIALIZED and shared_market_data.database_path().is_file():
            return
        with _database() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS live_ticks(
                identity TEXT NOT NULL,
                exchange_utc TEXT NOT NULL,
                received_utc TEXT NOT NULL,
                price REAL NOT NULL,
                packet_sha256 TEXT NOT NULL,
                session_id TEXT NOT NULL,
                PRIMARY KEY(identity,exchange_utc,packet_sha256)
            );
            CREATE TABLE IF NOT EXISTS live_minute_bars(
                identity TEXT NOT NULL,
                minute_utc TEXT NOT NULL,
                session_ist TEXT NOT NULL,
                open REAL NOT NULL, high REAL NOT NULL,
                low REAL NOT NULL, close REAL NOT NULL,
                tick_count INTEGER NOT NULL,
                first_exchange_utc TEXT NOT NULL,
                last_exchange_utc TEXT NOT NULL,
                last_received_utc TEXT NOT NULL,
                PRIMARY KEY(identity,minute_utc)
            );
            CREATE INDEX IF NOT EXISTS live_bar_recent
              ON live_minute_bars(identity,minute_utc);
            CREATE TABLE IF NOT EXISTS live_depth_books(
                identity TEXT NOT NULL,
                received_utc TEXT NOT NULL,
                session_id TEXT NOT NULL,
                book_json TEXT NOT NULL,
                packet_pair_sha256 TEXT NOT NULL,
                PRIMARY KEY(identity,received_utc)
            );
            CREATE INDEX IF NOT EXISTS live_book_recent
              ON live_depth_books(identity,received_utc);
        """)
        DB_INITIALIZED = True


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def decode_marketfeed(blob: bytes) -> list[dict]:
    """Parse only Dhan v2 8-byte-header ticker packets (code 2).

    Index code 1 is not documented with a stable binary body in Dhan's
    market-feed reference; intentionally do not guess its price layout.
    """
    if not isinstance(blob, bytes) or len(blob) > 250_000:
        raise ValueError("Invalid live market-feed frame")
    position, result = 0, []
    while position < len(blob):
        if len(blob) - position < 8:
            raise ValueError("Truncated Dhan market-feed header")
        code, length, segment, sid = struct.unpack_from("<BHBI", blob, position)
        if length < 8 or position + length > len(blob):
            raise ValueError("Invalid Dhan market-feed packet length")
        packet = blob[position:position+length]
        if code == 2 and length == 16 and segment in SEGMENT_CODE and sid > 0:
            price, epoch = struct.unpack_from("<fI", packet, 8)
            if math.isfinite(price) and price > 0 and epoch >= 1_400_000_000:
                result.append({
                    "exchange_segment": SEGMENT_CODE[segment],
                    "security_id": str(sid), "price": float(price),
                    "exchange_utc": _iso(datetime.fromtimestamp(epoch,timezone.utc)),
                    "packet_sha256": sha256(packet).hexdigest(),
                })
        # Dhan sends prev-close, status, index-code-1 and disconnect packets.
        # These are NOT verified trades, so cannot be used as minute bars.
        position += length
    return result


def _update(**changes) -> None:
    with CHANGED:
        ACTIVE.update(changes)
        ACTIVE["revision"] = ACTIVE.get("revision", 0) + 1
        CHANGED.notify_all()


def _public_book(book: dict | None) -> dict | None:
    if not book:
        return None
    bids, asks = book["bid"], book["ask"]
    bid_qty = sum(level["quantity"] for level in bids)
    ask_qty = sum(level["quantity"] for level in asks)
    best_bid, best_ask = bids[0]["price"], asks[0]["price"]
    mid = (best_bid + best_ask) / 2
    return {
        "identity": book["identity"],
        "received_utc": book["received_utc"],
        "bid": bids, "ask": asks,
        "best_bid": best_bid, "best_ask": best_ask,
        "spread_bps": round((best_ask-best_bid)/mid*10000, 2),
        "imbalance": round((bid_qty-ask_qty)/max(1,bid_qty+ask_qty), 4),
        "bid_levels": len(bids), "ask_levels": len(asks),
        "full_depth": book.get("full_depth",False),
        "source_clock": "local_receive_not_exchange",
    }


def status() -> dict:
    with LOCK:
        state = dict(ACTIVE)
        book = _public_book(state.pop("latest_book",None))
        quotes = dict(state.pop("quotes", {}))
        state.pop("source_identity_map",None)
    now = datetime.now(timezone.utc)
    safe_quotes = {}
    for identity, item in quotes.items():
        copy = dict(item)
        copy["age_seconds"] = max(0,round((now-_utc(item["received_utc"])).total_seconds(),1))
        copy["fresh"] = copy["age_seconds"] <= STALE_AFTER_SECONDS and state.get("active",False)
        safe_quotes[identity] = copy
    if book:
        book["age_seconds"] = max(0,round((now-_utc(book["received_utc"])).total_seconds(),1))
        book["fresh"] = (book["age_seconds"] <= STALE_AFTER_SECONDS
                          and state.get("depth_connection")=="connected"
                          and state.get("active",False))
    state["quotes"] = safe_quotes
    state["latest_book"] = book
    state["market_mode"] = "LIVE" if state.get("active") else "OFFLINE"
    state["client_id_configured"] = bool(os.getenv("DHAN_CLIENT_ID","").strip())
    state["book_source"] = "Dhan original 20-level NSE_EQ/NSE_FNO" if state.get("depth_identity") else None
    state["depth_supported_for_index"] = False
    state["shared_library"] = shared_market_data.SHARED_ID
    state["read_only"] = True
    return state


def ingest_tick(identity: str, packet: dict, *, received: datetime | None = None,
                session_id: str = "offline_test") -> bool:
    """Persist one verified ticker observation; do not backfill missing minutes."""
    if identity not in INDEX and not market_depth.DEPTH_ID.fullmatch(identity):
        raise ValueError("Unsupported exact ticker identity")
    now = received or datetime.now(timezone.utc)
    event = _utc(packet["exchange_utc"])
    if abs((now-event).total_seconds()) > MAX_TICK_LATENCY_SECONDS:
        return False
    price = float(packet["price"])
    if not math.isfinite(price) or price <= 0:
        return False
    raw_sha = str(packet["packet_sha256"])
    if len(raw_sha) != 64 or any(c not in "0123456789abcdef" for c in raw_sha):
        raise ValueError("Original ticker packet missing SHA-256 evidence")
    minute = event.replace(second=0,microsecond=0)
    session = minute.astimezone(IST)
    if session.weekday() >= 5 or not (
        (session.hour == 9 and session.minute >= 15)
        or (10 <= session.hour <= 14)
        or (session.hour == 15 and session.minute <= 29)):
        return False
    minute_utc = _iso(minute)
    event_utc = _iso(event)
    receive_utc = _iso(now)
    _init_db()
    with _database() as db:
        inserted = db.execute("""INSERT OR IGNORE INTO live_ticks
             (identity,exchange_utc,received_utc,price,packet_sha256,session_id)
             VALUES(?,?,?,?,?,?)""",
            (identity,event_utc,receive_utc,price,raw_sha,session_id)).rowcount
        if not inserted:
            return False
        db.execute("""INSERT INTO live_minute_bars
            (identity,minute_utc,session_ist,open,high,low,close,tick_count,
             first_exchange_utc,last_exchange_utc,last_received_utc)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(identity,minute_utc) DO UPDATE SET
              high=MAX(high,excluded.high), low=MIN(low,excluded.low),
              close=CASE WHEN excluded.last_exchange_utc>=last_exchange_utc
                THEN excluded.close ELSE close END,
              open=CASE WHEN excluded.first_exchange_utc<first_exchange_utc
                THEN excluded.open ELSE open END,
              first_exchange_utc=MIN(first_exchange_utc,excluded.first_exchange_utc),
              last_exchange_utc=MAX(last_exchange_utc,excluded.last_exchange_utc),
              last_received_utc=excluded.last_received_utc,
              tick_count=tick_count+1""",
            (identity,minute_utc,session.date().isoformat(),
             price,price,price,price,1,event_utc,event_utc,receive_utc))
    return True


def minute_series(identity: str, limit: int = 500) -> dict:
    if identity not in INDEX and not market_depth.DEPTH_ID.fullmatch(identity):
        raise ValueError("Invalid live instrument")
    if not 1 <= limit <= 5000:
        raise ValueError("Select at most 5000 observed minute bars")
    _init_db()
    cutoff = _iso(datetime.now(timezone.utc).replace(second=0,microsecond=0))
    with _database() as db:
        rows = db.execute("""SELECT minute_utc,session_ist,open,high,low,close,tick_count
            FROM live_minute_bars WHERE identity=? AND minute_utc<?
            ORDER BY minute_utc DESC LIMIT ?""",
            (identity,cutoff,limit+1)).fetchall()
    bars = [{
        "timestamp_utc":stamp, "session_ist":day,
        "open":op,"high":hi,"low":lo,"close":cl,
        # Trade volume is NOT available from LTP ticks; zero is a missing field.
        "volume":0,"observed_tick_count":count,
    } for stamp,day,op,hi,lo,cl,count in reversed(rows[:limit])]
    return {
        "identity":identity,"rows":bars,"has_more":len(rows)>limit,
        "interval_minutes":1,"basis":"Dhan_live_ticker_observed_LTP_minute_aggregate",
        "source_warning":"Live-tick-derived OHLC has no authenticated traded volume, "
                         "missing intervals are never synthesized, and tick delivery "
                         "can be incomplete. Current unfinished minute is excluded.",
    }


def _receive_ticker(record: dict) -> None:
    with LOCK:
        if not ACTIVE.get("active"):
            return
        identities = ACTIVE.get("source_identity_map",{})
        identity = identities.get((record["exchange_segment"],record["security_id"]))
        session = ACTIVE.get("session_id","")
    if identity is None:
        return
    now = datetime.now(timezone.utc)
    valid = ingest_tick(identity,record,received=now,session_id=session)
    if not valid:
        return
    with CHANGED:
        quotes = ACTIVE.setdefault("quotes",{})
        quotes[identity] = {
            "price":round(record["price"],4),
            "exchange_utc":record["exchange_utc"],
            "received_utc":_iso(now),
            "source":"Dhan live ticker (not an option trade fill)",
        }
        ACTIVE["ticks"] = ACTIVE.get("ticks",0)+1
        ACTIVE["revision"] = ACTIVE.get("revision",0)+1
        CHANGED.notify_all()
    if identity in INDEX and ACTIVE.get("auto_audit",False):
        try:
            from . import trading_cockpit
            original = minute_series(identity,limit=250)
            completed = original["rows"]
            if len(completed) < 30:
                return
            last_bar = completed[-1]["timestamp_utc"]
            with LOCK:
                if ACTIVE.get("last_audit_bar")==last_bar:
                    return
                ACTIVE["last_audit_bar"]=last_bar
            trading_cockpit.observe_and_score(identity,completed)
        except (ValueError,OSError,sqlite3.Error):
            _update(audit_state="needs_review")


def _ticker_worker(stop: Event, subscriptions: list[dict], url: str) -> None:
    try:
        from websockets.sync.client import connect
    except ImportError:
        _update(ticker_connection="missing_websockets_dependency")
        return
    attempts=0
    while not stop.is_set():
        try:
            with connect(url,open_timeout=10,close_timeout=2,max_size=200_000) as ws:
                ws.send(json.dumps({"RequestCode":15,"InstrumentCount":len(subscriptions),
                                    "InstrumentList":subscriptions}))
                _update(ticker_connection="connected",last_error=None)
                attempts=0
                while not stop.is_set():
                    try:
                        data=ws.recv(timeout=1)
                    except TimeoutError:
                        continue
                    if not isinstance(data,bytes):
                        continue
                    try:
                        packets=decode_marketfeed(data)
                    except ValueError:
                        _update(ticker_decode_errors=ACTIVE.get("ticker_decode_errors",0)+1)
                        continue
                    for packet in packets:
                        _receive_ticker(packet)
        except Exception:
            attempts+=1
            _update(ticker_connection="reconnecting",
                    ticker_note="Dhan ticker socket interrupted; checking token, permissions and network",
                    reconnect_attempts=attempts)
            stop.wait(min(20,2**min(attempts,4)))
    _update(ticker_connection="stopped")


def _receive_depth(book: dict) -> None:
    safe = _public_book(book)
    if safe is None:
        return
    with CHANGED:
        ACTIVE["latest_book"]=book
        ACTIVE["depth_snapshots"]=ACTIVE.get("depth_snapshots",0)+1
        ACTIVE["revision"]=ACTIVE.get("revision",0)+1
        CHANGED.notify_all()
        last_saved=ACTIVE.get("last_saved_book_utc")
        saved=ACTIVE.get("saved_books",0)
    if saved>=MAX_SAVED_BOOKS:
        _update(depth_recording="storage_limit_reached")
        return
    if last_saved and (_utc(book["received_utc"])-_utc(last_saved)).total_seconds()<1:
        return
    _init_db()
    pair_sha=sha256((book["bid_packet_sha256"]+book["ask_packet_sha256"]).encode()).hexdigest()
    with _database() as db:
        db.execute("""INSERT OR IGNORE INTO live_depth_books
            (identity,received_utc,session_id,book_json,packet_pair_sha256)
            VALUES(?,?,?,?,?)""",(book["identity"],book["received_utc"],
                ACTIVE.get("session_id",""),json.dumps(book,sort_keys=True),pair_sha))
    _update(saved_books=saved+1,last_saved_book_utc=book["received_utc"],
            depth_recording="sampled_at_most_1_snapshot_per_second")


def _depth_worker(stop: Event, identity: str, url: str) -> None:
    try:
        from websockets.sync.client import connect
    except ImportError:
        _update(depth_connection="missing_websockets_dependency")
        return
    segment,secid=identity.split(":")
    packet_request={"RequestCode":23,"InstrumentCount":1,
                    "InstrumentList":[{"ExchangeSegment":segment,"SecurityId":secid}]}
    attempts=0
    while not stop.is_set():
        last={}
        try:
            with connect(url,open_timeout=10,close_timeout=2,max_size=250_000) as ws:
                ws.send(json.dumps(packet_request))
                _update(depth_connection="connected")
                attempts=0
                while not stop.is_set():
                    try:
                        blob=ws.recv(timeout=1)
                    except TimeoutError:
                        continue
                    if not isinstance(blob,bytes):
                        continue
                    now=datetime.now(timezone.utc)
                    try:
                        packets=market_depth.packet_stream(blob,20)
                    except ValueError:
                        continue
                    for p in packets:
                        if (p["security_id"]!=secid or
                            p["segment_code"]!=(1 if segment=="NSE_EQ" else 2)):
                            continue
                        last[p["side"]]=(p,now)
                        if "bid" in last and "ask" in last:
                            bid,bt=last["bid"]
                            ask,at=last["ask"]
                            if abs((bt-at).total_seconds())<=1:
                                try:
                                    book=market_depth._snapshot(bid,ask,identity,now,20)
                                    _receive_depth(book)
                                except (ValueError,sqlite3.Error,OSError):
                                    _update(depth_recording="invalid_or_storage_error")
                                last.clear()
        except Exception:
            attempts+=1
            _update(depth_connection="reconnecting",
                    depth_note="Dhan depth feed interrupted; verify full-depth entitlement",
                    reconnect_attempts=attempts)
            stop.wait(min(20,2**min(attempts,4)))
    _update(depth_connection="stopped")


def start(index_identity: str, depth_identity: str = "", auto_audit: bool = False) -> dict:
    """Start authorized live ticker+optional 20-level capture in local server."""
    global WORKERS,STOP,SESSION_ID
    if index_identity not in INDEX:
        raise ValueError("Choose BANKNIFTY or NIFTY 50 index")
    if depth_identity and not market_depth.DEPTH_ID.fullmatch(depth_identity):
        raise ValueError("20-level depth requires an exact NSE_EQ/NSE_FNO Security ID")
    client=os.getenv("DHAN_CLIENT_ID","").strip()
    token=os.getenv("DHAN_ACCESS_TOKEN","").strip()
    if not client or not token:
        raise ValueError("Configure Dhan client ID and access token in the cockpit connection form")
    if not client.isdigit() or not 4<=len(client)<=20 or len(token)>4096:
        raise ValueError("Invalid locally stored Dhan live market credentials")
    with LOCK:
        if any(worker.is_alive() for worker in WORKERS):
            raise ValueError("A live stream is already active or shutting down; stop it before restarting")
        STOP=Event()
        SESSION_ID="live_"+uuid.uuid4().hex[:16]
        index_segment,index_sid=INDEX[index_identity]
        subscriptions=[{"ExchangeSegment":index_segment,"SecurityId":index_sid}]
        mapping={(index_segment,index_sid):index_identity}
        if depth_identity:
            seg,sid=depth_identity.split(":")
            subscriptions.append({"ExchangeSegment":seg,"SecurityId":sid})
            mapping[(seg,sid)]=depth_identity
        ACTIVE.clear()
        ACTIVE.update({
            "session_id":SESSION_ID,"active":True,"index_identity":index_identity,
            "depth_identity":depth_identity or None,"ticker_connection":"connecting",
            "depth_connection":"connecting" if depth_identity else "not_subscribed",
            "started_utc":_iso(datetime.now(timezone.utc)),
            "auto_audit":auto_audit,"last_audit_bar":None,"audit_state":"ready",
            "ticks":0,"depth_snapshots":0,"saved_books":0,"ticker_decode_errors":0,
            "quotes":{},"latest_book":None,"revision":1,
            "source_identity_map":mapping,
            "depth_recording":"sampled_at_most_1_snapshot_per_second" if depth_identity else "not_subscribed",
        })
        # Keep authentication inside local threads only, never in public status.
        ticker_url=("wss://api-feed.dhan.co?version=2&token="+quote(token,safe="")+
                    "&clientId="+quote(client,safe="")+"&authType=2")
        workers=[Thread(target=_ticker_worker,args=(STOP,subscriptions,ticker_url),
                        daemon=True,name="quantlab-dhan-ticker")]
        if depth_identity:
            depth_url=market_depth._live_endpoint(20,client,token)
            workers.append(Thread(target=_depth_worker,args=(STOP,depth_identity,depth_url),
                                  daemon=True,name="quantlab-dhan-depth20"))
        WORKERS=workers
    _init_db()
    for worker in workers:
        worker.start()
    return status()


def stop() -> dict:
    with CHANGED:
        if not ACTIVE.get("active"):
            return status()
        ACTIVE["active"]=False
        ACTIVE["stopped_utc"]=_iso(datetime.now(timezone.utc))
        ACTIVE["revision"]=ACTIVE.get("revision",0)+1
        STOP.set()
        CHANGED.notify_all()
    return status()


def events():
    """Server-sent events: push only observed status/book/quote changes."""
    last=-1
    while True:
        with CHANGED:
            CHANGED.wait_for(lambda: ACTIVE.get("revision",0)!=last,timeout=10)
            last=ACTIVE.get("revision",0)
        yield "data: "+json.dumps(status(),ensure_ascii=True,allow_nan=False)+"\n\n"


def latest_depth_history(identity: str, limit: int = 150) -> dict:
    if not market_depth.DEPTH_ID.fullmatch(identity):
        raise ValueError("Choose exact NSE_EQ/NSE_FNO security ID")
    if not 1<=limit<=500:
        raise ValueError("Depth replay allows up to 500 stored samples")
    _init_db()
    with _database() as db:
        rows=db.execute("""SELECT book_json FROM live_depth_books
            WHERE identity=? ORDER BY received_utc DESC LIMIT ?""",
            (identity,limit)).fetchall()
    return {"identity":identity,"source":"original_Dhan_20_level_saved_live_sample",
            "sampling":"at_most_one_observed_pair_per_second",
            "snapshots":[_public_book(json.loads(raw)) for (raw,) in reversed(rows)],
            "historical_download_supported":False,
            "note":"These order books were recorded from live Dhan packets on this computer. "
                   "Missing historical depth cannot be reconstructed from 1-minute candles."}


def _reset_for_tests() -> None:
    """Offline tests only: terminate in-memory state, never delete any market data."""
    global WORKERS,STOP,DB_INITIALIZED
    with CHANGED:
        STOP.set()
        ACTIVE.clear()
        WORKERS=[]
        DB_INITIALIZED=False
        CHANGED.notify_all()
