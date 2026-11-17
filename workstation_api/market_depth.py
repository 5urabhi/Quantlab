"""Original Dhan 20/200-level market-depth capture and historical evidence lab.

Read-only real-time recording uses Dhan's binary WebSocket format. Arbitrary
past order books are NOT offered by Dhan's historical OHLCV API. Users may
import authorized timestamped depth CSV; no snapshots are synthesized from
minute candles. Quotes are paired only when both sides were observed within
one local second; capture timestamps are local receive times, not exchange
event timestamps. No trade/order APIs and no credentials in saved evidence.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from hashlib import sha256
from pathlib import Path
from threading import Event, RLock
from urllib.parse import quote
from zoneinfo import ZoneInfo
import csv
import io
import json
import math
import os
import re
import shutil
import struct
import time
import uuid

from . import service

DEPTH_ID = re.compile(r"^NSE_(EQ|FNO):[0-9]{1,12}$")
REC_ID = re.compile(r"^depth_[a-f0-9]{16}$")
MARCH = re.compile(r"^[a-z0-9_-]{2,36}$")
MAX_ORIGINAL_BYTES = 30 * 1024 * 1024
MAX_CSV_ROWS = 250_000
MAX_SNAPSHOTS = 60_000
NSE_TZ = ZoneInfo("Asia/Kolkata")
STOP_SIGNALS: dict[str, Event] = {}
LOCK = RLock()


def _root() -> Path:
    root = service.DATA / "research_workspace" / "market_depth"
    if root.is_symlink() or root.parent.is_symlink():
        raise ValueError("Unsafe historical order book storage directory")
    root.mkdir(parents=True,exist_ok=True)
    return root


def _id() -> str:
    return "depth_" + uuid.uuid4().hex[:16]


def _path(session_id: str) -> Path:
    if not REC_ID.fullmatch(session_id or ""):
        raise ValueError("Unknown depth capture session")
    folder = _root()/session_id
    if folder.is_symlink():
        raise ValueError("Unsafe market depth session")
    return folder


def _level(price: float, qty: int, orders: int) -> dict:
    if not math.isfinite(price) or price <= 0 or not 0 < qty <= 2**32 - 1:
        raise ValueError("Invalid original order book level")
    if not 0 < orders <= 2**32-1:
        raise ValueError("Invalid original number of resting orders")
    return {"price": round(price, 8), "quantity": qty, "orders": orders}


def _validate_snapshot(snapshot: dict, levels: int) -> dict:
    if levels not in (20,200):
        raise ValueError("Only original 20- or 200-level snapshots are supported")
    bid = snapshot.get("bid",[])
    ask = snapshot.get("ask",[])
    if not bid or not ask or len(bid)>levels or len(ask)>levels:
        raise ValueError("A snapshot requires both sides and bounded observed levels")
    def checked(side: list[dict], reverse: bool) -> list[dict]:
        out = []
        for value in side:
            raw = _level(float(value["price"]), int(value["quantity"]),int(value["orders"]))
            out.append(raw)
        prices=[r["price"] for r in out]
        if prices != sorted(prices,reverse=reverse) or len(prices)!=len(set(prices)):
            raise ValueError("Order book levels must have ordered, distinct prices")
        return out
    bids=checked(bid,True)
    asks=checked(ask,False)
    if bids[0]["price"] >= asks[0]["price"]:
        raise ValueError("Original order book best bid must be below best ask")
    return {**snapshot,"bid":bids,"ask":asks,
            "full_depth":len(bids)==levels and len(asks)==levels}


def _save(session_id: str, snapshots: list[dict], *,
          method: str, provider: str, instrument: str,
          depth: int, original_digest: str,
          capture_start: str = "", imported_bytes: bytes | None = None) -> dict:
    root=_root()
    folder=_path(session_id)
    staging=root/("."+session_id+".pending")
    if folder.exists() or staging.exists():
        raise ValueError("Depth session already exists")
    staging.mkdir(mode=0o700)
    try:
        if imported_bytes is not None:
            (staging/"source.csv").write_bytes(imported_bytes)
        output=staging/"snapshots.jsonl"
        with output.open("w",encoding="utf-8") as fd:
            for snapshot in snapshots:
                fd.write(json.dumps(snapshot,sort_keys=True,
                                    ensure_ascii=True,allow_nan=False)+"\n")
        result={
            "id":session_id,"method":method,"provider":provider,
            "identity":instrument,"depth_levels":depth,"snapshots":len(snapshots),
            "full_depth_snapshots":sum(bool(x["full_depth"]) for x in snapshots),
            "first_received":snapshots[0]["received_utc"] if snapshots else None,
            "last_received":snapshots[-1]["received_utc"] if snapshots else None,
            "created_utc":datetime.now(timezone.utc).isoformat(),
            "capture_started":capture_start or None,
            "original_sha256":original_digest,
            "normalized_sha256":sha256(output.read_bytes()).hexdigest(),
            "source_evidence_complete":bool(snapshots),
            "time_basis":("local_receive_clock" if method=="dhan_live_websocket"
                          else "original_provider_timestamp"),
            "observations_are_historical_only_after_capture":True,
            "independently_market_certified":False,
            "warning":"No historical order book was fabricated from OHLCV. "
                      "Recorded live receive times are not exchange timestamps; "
                      "historical CSV rights and timestamp fidelity require review.",
        }
        (staging/"receipt.json").write_text(
            json.dumps(result,indent=2,ensure_ascii=True,allow_nan=False),
            encoding="utf-8")
        staging.rename(folder)
        return result
    except Exception:
        shutil.rmtree(staging,ignore_errors=True)
        raise


def packet_stream(blob: bytes, depth: int) -> list[dict]:
    """Decode stacked real Dhan depth frames with protocol-specific headers.

    Dhan 20-depth uses the last uint32 as an ignorable sequence, while
    200-depth uses that field as NoOfRows. A 200-depth frame may therefore
    contain fewer than 200 levels: packet length is 12 + 16*NoOfRows.
    Never promote control packets or unsupported payload layouts to quotes.
    """
    if depth not in (20, 200):
        raise ValueError("Unsupported depth level count")
    max_packet = 12 + depth * 16
    if not isinstance(blob, (bytes, bytearray)) or not blob:
        return []
    if len(blob) > max_packet * 50:
        raise ValueError("Depth feed frame exceeds safe decoded length")
    out = []
    offset = 0
    while offset < len(blob):
        if len(blob) - offset < 12:
            raise ValueError("Truncated Dhan depth packet header")
        length, code, segment, secid, seq_or_rows = struct.unpack_from(
            "<hBBiI", blob, offset)
        if code not in (41, 51):
            raise ValueError("Not a bid/ask full-depth binary packet")
        if segment not in (1, 2) or secid <= 0:
            raise ValueError("Dhan market-depth header has invalid exchange/security ID")
        count = 20 if depth == 20 else seq_or_rows
        if not 1 <= count <= depth:
            raise ValueError("Invalid declared depth row count")
        if length != 12 + count * 16 or offset + length > len(blob):
            raise ValueError("Unexpected Dhan full-depth binary packet size")
        levels = []
        for i in range(count):
            price, quantity, orders = struct.unpack_from(
                "<dII", blob, offset + 12 + i * 16)
            if price == 0 and quantity == 0 and orders == 0:
                continue
            levels.append(_level(price, quantity, orders))
        out.append({
            "side": "bid" if code == 41 else "ask",
            "security_id": str(secid),
            "segment_code": segment,
            "message_sequence": seq_or_rows if depth == 20 else None,
            "declared_rows": count,
            "levels": levels,
            "raw_packet_sha256": sha256(blob[offset:offset+length]).hexdigest(),
        })
        offset += length
    return out

def _snapshot(bid: dict,ask: dict,identity: str,
              observed_at: datetime,depth: int) -> dict:
    return _validate_snapshot({
        "identity":identity,
        "received_utc":observed_at.astimezone(timezone.utc).isoformat(),
        "timestamp_kind":"local_receive",
        "bid":bid["levels"],"ask":ask["levels"],
        "bid_packet_sha256":bid["raw_packet_sha256"],
        "ask_packet_sha256":ask["raw_packet_sha256"],
        "sequence_bid":bid["message_sequence"],
        "sequence_ask":ask["message_sequence"],
    },depth)


def _live_endpoint(depth: int,client: str,token: str) -> str:
    if depth not in (20,200) or not re.fullmatch(r"[0-9]{4,20}",client):
        raise ValueError("Dhan depth requires a valid local client ID")
    if not token or len(token)>4096:
        raise ValueError("Dhan token unavailable from local ignored .env")
    base=("wss://depth-api-feed.dhan.co/twentydepth" if depth==20 else
          "wss://full-depth-api.dhan.co/twohundreddepth")
    return (base+"?token="+quote(token,safe="")+
            "&clientId="+quote(client,safe="")+"&authType=2")


def start_live(identity: str, depth: int = 20, duration_seconds: int = 120,
               *, session_id: str, progress=None) -> dict:
    if not DEPTH_ID.fullmatch(identity or ""):
        raise ValueError("Choose an explicit NSE EQ/FNO Security ID")
    if depth not in (20,200) or not 10 <= duration_seconds <= 1800:
        raise ValueError("Depth recorder allows 20/200 levels and 10–1800 seconds")
    if not REC_ID.fullmatch(session_id):
        raise ValueError("Invalid capture session ID")
    token=os.getenv("DHAN_ACCESS_TOKEN","").strip()
    client=os.getenv("DHAN_CLIENT_ID","").strip()
    url=_live_endpoint(depth,client,token)
    try:
        from websockets.sync.client import connect
    except ImportError as exc:
        raise ValueError("Install the local websockets dependency before recording") from exc
    seg,security=identity.split(":")
    if depth==20:
        request={"RequestCode":23,"InstrumentCount":1,
                 "InstrumentList":[{"ExchangeSegment":seg,"SecurityId":security}]}
    else:
        request={"RequestCode":23,"ExchangeSegment":seg,"SecurityId":security}
    signal=Event()
    with LOCK:
        if session_id in STOP_SIGNALS:
            raise ValueError("Capture already started")
        STOP_SIGNALS[session_id]=signal
    start=datetime.now(timezone.utc)
    until=time.monotonic()+duration_seconds
    snapshots=[]
    last={}
    raw_hash=sha256()
    reconnects=0
    try:
        while time.monotonic()<until and not signal.is_set():
            if reconnects>=4:
                break
            try:
                # Never surface the URL because the Dhan authentication token
                # is necessarily in its query string per the official protocol.
                with connect(url,open_timeout=12,close_timeout=3,
                             max_size=12+(depth*16)*50) as ws:
                    ws.send(json.dumps(request))
                    while time.monotonic()<until and not signal.is_set():
                        try:
                            payload=ws.recv(timeout=1.0)
                        except TimeoutError:
                            continue
                        if not isinstance(payload,bytes):
                            continue
                        now=datetime.now(timezone.utc)
                        raw_hash.update(payload)
                        try:
                            packets=packet_stream(payload,depth)
                        except ValueError:
                            # The feed also sends keepalive/control packets.
                            continue
                        for packet in packets:
                            if (packet["security_id"] != security or
                                packet["segment_code"] != (1 if seg=="NSE_EQ" else 2)):
                                continue
                            last[packet["side"]]=(packet,now)
                            if "bid" in last and "ask" in last:
                                bid,bid_time=last["bid"]
                                ask,ask_time=last["ask"]
                                if abs((bid_time-ask_time).total_seconds()) <= 1.0:
                                    try:
                                        snapshot=_snapshot(bid,ask,identity,now,depth)
                                    except ValueError:
                                        continue
                                    snapshots.append(snapshot)
                                    last.clear()
                                    if len(snapshots)>=MAX_SNAPSHOTS:
                                        signal.set()
                                        break
                        if progress and len(snapshots)%25==0:
                            elapsed=(datetime.now(timezone.utc)-start).total_seconds()
                            progress(min(95,100*elapsed/duration_seconds),
                                     f"Recording {len(snapshots)} original depth snapshots")
            except Exception:
                # No provider URLs, tokens, or raw server responses in errors.
                reconnects+=1
                if reconnects>=4 or signal.is_set():
                    break
                time.sleep(min(8,reconnects*2))
        if not snapshots:
            raise ValueError("Dhan depth feed did not yield a valid paired snapshot; "
                             "verify live market entitlement and trading hours")
        return _save(session_id,snapshots,method="dhan_live_websocket",
                     provider="dhan_live",instrument=identity,depth=depth,
                     original_digest=raw_hash.hexdigest(),
                     capture_start=start.isoformat())
    finally:
        with LOCK:
            STOP_SIGNALS.pop(session_id,None)


def stop_live(session_id: str) -> dict:
    if not REC_ID.fullmatch(session_id):
        raise ValueError("Invalid depth recording ID")
    with LOCK:
        signal=STOP_SIGNALS.get(session_id)
        if signal is None:
            return {"id":session_id,"state":"not_recording"}
        signal.set()
        return {"id":session_id,"state":"stop_requested"}


def import_csv(payload: bytes, identity: str, provider: str,
               depth: int, *, confirm_authorized: bool) -> dict:
    if not confirm_authorized:
        raise ValueError("Confirm permission to store historical depth snapshots")
    if not DEPTH_ID.fullmatch(identity or "") or depth not in (20,200):
        raise ValueError("Exact NSE Security ID and 20/200 depth are required")
    if not MARCH.fullmatch(provider or ""):
        raise ValueError("Enter an approved short provider name")
    if not payload or len(payload)>MAX_ORIGINAL_BYTES:
        raise ValueError("Historical depth CSV must be at most 30 MB")
    try:
        data=payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Historical order book CSV must be UTF-8") from exc
    reader=csv.DictReader(io.StringIO(data,newline=""))
    fields={"timestamp_utc","side","level","price","quantity","orders"}
    if not fields.issubset(reader.fieldnames or []):
        raise ValueError("Provide timestamp_utc,side,level,price,quantity,orders columns")
    grouped:dict[str,dict[str,dict[int,dict]]]={}
    count=0
    for row in reader:
        count+=1
        if count>MAX_CSV_ROWS:
            raise ValueError("Source exceeds 250000 order-book level rows")
        ts=str(row["timestamp_utc"]).strip()
        try:
            stamp=datetime.fromisoformat(ts.replace("Z","+00:00"))
            if stamp.tzinfo is None:
                raise ValueError("Timestamp has no source timezone")
            stamp=stamp.astimezone(timezone.utc)
            if stamp>datetime.now(timezone.utc)+timedelta(minutes=1):
                raise ValueError("Future depth timestamp")
            ts=stamp.isoformat()
            level=int(row["level"])
            side=str(row["side"]).lower().strip()
            detail=_level(float(row["price"]),int(row["quantity"]),int(row["orders"]))
        except (TypeError,ValueError,OverflowError,KeyError) as exc:
            raise ValueError("Invalid timestamp, level or original depth price") from exc
        if side not in ("bid","ask") or not 1<=level<=depth:
            raise ValueError("Invalid original depth side or level number")
        group=grouped.setdefault(ts,{"bid":{},"ask":{}})
        if level in group[side]:
            raise ValueError("Repeated order-book level for a snapshot")
        group[side][level]=detail
    snapshots=[]
    for stamp,books in sorted(grouped.items()):
        if not books["bid"] or not books["ask"]:
            raise ValueError("Historical snapshot missing bid or ask side")
        for side in ("bid","ask"):
            levels=sorted(books[side])
            if levels!=list(range(1,len(levels)+1)):
                raise ValueError("Historical depth levels must start at one without gaps")
        snap={
            "identity":identity,"received_utc":stamp,
            "timestamp_kind":"provider_supplied",
            "bid":[books["bid"][i] for i in sorted(books["bid"])],
            "ask":[books["ask"][i] for i in sorted(books["ask"])],
        }
        snapshots.append(_validate_snapshot(snap,depth))
        if len(snapshots)>MAX_SNAPSHOTS:
            raise ValueError("Too many snapshots per historical source")
    if not snapshots:
        raise ValueError("Historical depth file contains no paired snapshots")
    return _save(_id(),snapshots,method="licensed_historical_csv",
                 provider=provider,instrument=identity,depth=depth,
                 original_digest=sha256(payload).hexdigest(),
                 imported_bytes=payload)


def catalog(limit: int = 50) -> dict:
    if not 1<=limit<=100:
        raise ValueError("Invalid depth catalog limit")
    results=[]
    for path in sorted(_root().iterdir(),key=lambda p:p.stat().st_mtime_ns,reverse=True):
        if len(results)>=limit:
            break
        if not path.is_dir() or path.is_symlink() or not REC_ID.fullmatch(path.name):
            continue
        receipt=path/"receipt.json"
        if not receipt.is_file() or receipt.is_symlink() or receipt.stat().st_size>20_000:
            continue
        try:
            results.append(json.loads(receipt.read_text(encoding="utf-8")))
        except (ValueError,OSError):
            continue
    return {"captures":results,"historical_depth_download_supported":False,
            "live_recording_supported":True,
            "note":"Dhan's WebSocket captures depth from the moment you record, "
                    "not before. Past order books require an authorized archive."}


def _load(session_id: str,limit: int = 5000) -> tuple[dict,list[dict]]:
    if not 1<=limit<=5000:
        raise ValueError("Market depth analysis allows at most 5000 snapshots")
    folder=_path(session_id)
    receipt=folder/"receipt.json"
    data=folder/"snapshots.jsonl"
    if any(p.is_symlink() for p in (receipt,data)) or not receipt.is_file() or not data.is_file():
        raise ValueError("Stored market depth evidence unavailable")
    info=json.loads(receipt.read_text(encoding="utf-8"))
    if sha256(data.read_bytes()).hexdigest()!=info.get("normalized_sha256"):
        raise ValueError("Stored depth evidence SHA-256 mismatch")
    rows=[]
    with data.open("r",encoding="utf-8") as fd:
        for line in fd:
            if len(rows)>=limit:
                break
            rows.append(json.loads(line))
    return info,rows


def analyze(session_id: str,limit: int = 1500) -> dict:
    info,snapshots=_load(session_id,limit)
    metrics=[]
    previous_mid=None
    for item in snapshots:
        checked=_validate_snapshot(item,info["depth_levels"])
        bids=checked["bid"]
        asks=checked["ask"]
        bid,ask=bids[0]["price"],asks[0]["price"]
        mid=(bid+ask)/2
        bid_qty=sum(r["quantity"] for r in bids)
        ask_qty=sum(r["quantity"] for r in asks)
        spread_bps=(ask-bid)/mid*10_000
        imbalance=(bid_qty-ask_qty)/max(1,bid_qty+ask_qty)
        metrics.append({
            "timestamp":checked["received_utc"],
            "mid_price":mid,
            "spread_bps":spread_bps,
            "bid_depth":bid_qty,"ask_depth":ask_qty,
            "imbalance":imbalance,
            "bid_levels":len(bids),"ask_levels":len(asks),
            "return_from_previous_mid_bps":(
                (mid/previous_mid-1)*10000 if previous_mid else None),
            "full_depth":checked["full_depth"],
        })
        previous_mid=mid
    return {
        "id":session_id,"identity":info["identity"],
        "captured_snapshots":info["snapshots"],
        "analyzed_snapshots":len(metrics),
        "metrics":metrics,
        "summary":{
            "average_spread_bps":sum(x["spread_bps"] for x in metrics)/len(metrics),
            "average_imbalance":sum(x["imbalance"] for x in metrics)/len(metrics),
            "full_depth_fraction":sum(x["full_depth"] for x in metrics)/len(metrics),
            "source_clock":info["time_basis"],
        },
        "warning":"These are recorded order-book snapshots, not historical OHLCV or "
                  "a validated execution simulator. Local receipt times can differ "
                  "from exchange event times; no missing quotes are invented.",
    }
