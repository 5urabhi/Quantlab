"""BANKNIFTY constituent quote capture on spare slots of the existing Dhan feed.

No additional connection, option displacement, orders, historical fabrication or
dealer-position inference. This module samples original NSE_EQ quote packets;
aggregated buy/sell quantities are displayed liquidity, not executed trade flow.
"""
from __future__ import annotations

from contextlib import closing
from datetime import date, datetime, time as clock_time, timedelta, timezone
from zoneinfo import ZoneInfo
from hashlib import sha256
from urllib.request import Request, urlopen
from urllib.error import URLError
from pathlib import Path
from queue import Empty, Full, Queue
from threading import RLock
import csv
import io
import json
import math
import os
import re
import sqlite3
import struct
import time
import uuid

from . import dhan_workspace, live_market, market_inventory, pit_index, recorder_storage, service, shared_market_data

STREAM = "banknifty_constituent_quotes"
MAX_MEMBERS = 50
MAX_QUEUE = 2048
SAMPLE_SECONDS = 2
MAX_AGE = 30
HORIZONS = (1, 5, 10, 30, 60)
LOCK = RLock()
SYMBOL = re.compile(r"^[A-Z0-9&_.-]{1,40}$")
IDENTITY = re.compile(r"^NSE_EQ:[0-9]{1,12}$")
CURRENT_MEMBERS_URL = "https://www.niftyindices.com/IndexConstituent/ind_niftybanklist.csv"
MAX_CURRENT_CSV = 65536


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _local_day(dt):
    return dt.astimezone(live_market.IST).date()


def _folder():
    return service.DATA / "dhan" / "banknifty_constituents"


def _safe_folder():
    folder = _folder()
    if folder.is_symlink() or folder.parent.is_symlink() or service.DATA.is_symlink():
        raise ValueError("Unsafe constituent settings directory")
    if not folder.resolve().is_relative_to(service.DATA.resolve()):
        raise ValueError("Unsafe constituent settings directory")
    return folder


def _write_json(path, value):
    if path.is_symlink():
        raise ValueError("Unsafe constituent settings file")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("." + path.name + "." + uuid.uuid4().hex)
    try:
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, allow_nan=False, sort_keys=True)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def enabled():
    try:
        p = _safe_folder() / "consent.json"
        return p.is_file() and not p.is_symlink() and p.stat().st_size < 4096 and json.loads(p.read_text()).get("enabled") is True
    except (ValueError, OSError, AttributeError, TypeError):
        return False


def set_enabled(value):
    if type(value) is not bool:
        raise ValueError("Explicit boolean capture consent is required")
    _write_json(_safe_folder() / "consent.json", {"enabled": value, "read_only": True})
    if not value:
        CAPTURE.disconnect("disabled_by_user")
    return status()


def _parse_current_csv(text):
    reader=csv.DictReader(io.StringIO(text))
    cols={str(x).strip().casefold():x for x in (reader.fieldnames or [])}
    if "symbol" not in cols or "series" not in cols or "isin code" not in cols:
        raise ValueError("Official constituent CSV does not have Symbol, Series and ISIN Code")
    members={}
    for row in reader:
        symbol=str(row.get(cols["symbol"]) or "").strip().upper()
        series=str(row.get(cols["series"]) or "").strip().upper()
        isin=str(row.get(cols["isin code"]) or "").strip().upper()
        if not SYMBOL.fullmatch(symbol) or series!="EQ" or not re.fullmatch(r"IN[A-Z0-9]{10}",isin) or symbol in members:
            raise ValueError("Official constituent CSV contains invalid or ambiguous member identity")
        members[symbol]=isin
    if not 5<=len(members)<=MAX_MEMBERS or len(set(members.values()))!=len(members):
        raise ValueError("Official constituent CSV has an implausible or duplicate membership")
    return members


def refresh_current_membership(opener=urlopen,now=None):
    """Download the public official list; no extrapolation or historical backdate."""
    now=now or _now()
    day=_local_day(now)
    request=Request(CURRENT_MEMBERS_URL,headers={"Accept":"text/csv,application/octet-stream,*/*",
                                                "User-Agent":"QuantLab/1.0 read-only research"})
    try:
        with opener(request,timeout=15) as response:
            if hasattr(response,"geturl") and response.geturl().split("?",1)[0].lower()!=CURRENT_MEMBERS_URL.lower():
                raise ValueError("Official constituent download redirected unexpectedly")
            raw=response.read(MAX_CURRENT_CSV+1)
    except (OSError,URLError,TimeoutError):
        raise ValueError("Official NSE Indices constituent CSV unavailable; use the dated membership source or retry.") from None
    if not raw or len(raw)>MAX_CURRENT_CSV:
        raise ValueError("Official constituent CSV is empty or oversized")
    text=raw.decode("utf-8-sig")
    members=_parse_current_csv(text)
    # Store the original decoded CSV, including any UTF-8 BOM on the wire.
    original=raw.decode("utf-8")
    receipt={"date":day.isoformat(),"retrieved_utc":_iso(now),"source":CURRENT_MEMBERS_URL,
             "original_csv":original,"sha256":sha256(raw).hexdigest(),"symbols":sorted(members)}
    path=_safe_folder()/("current_members_"+day.isoformat()+"_"+receipt["sha256"][:16]+".json")
    if not path.exists():
        _write_json(path,receipt)
    return {"date":day.isoformat(),"symbols":sorted(members),"source_sha256":receipt["sha256"],
            "capture_state":"Membership saved; enabled recording subscribes on the next normal shared-feed connection. No existing stream was stopped."}


def _current_membership(day,instruments,as_of):
    folder=_safe_folder()
    paths=sorted(folder.glob("current_members_"+day.isoformat()+"_*.json"))[:64]
    candidates=[]
    for path in paths:
        try:
            if path.is_symlink() or path.stat().st_size>MAX_CURRENT_CSV*2:
                continue
            receipt=json.loads(path.read_text(encoding="utf-8"))
            retrieved=datetime.fromisoformat(receipt["retrieved_utc"])
            if receipt["source"]!=CURRENT_MEMBERS_URL or receipt["date"]!=day.isoformat() or _local_day(retrieved)!=day or retrieved>as_of:
                continue
            raw=receipt["original_csv"].encode("utf-8")
            if sha256(raw).hexdigest()!=receipt["sha256"]:
                continue
            members=_parse_current_csv(raw.decode("utf-8-sig"))
            if sorted(members)!=receipt["symbols"]:
                continue
            candidates.append((retrieved,receipt,members))
        except (OSError,ValueError,TypeError,KeyError,UnicodeError):
            continue
    if not candidates:
        return None
    retrieved,receipt,members=max(candidates,key=lambda x:x[0])
    resolved={}
    for symbol,isin in members.items():
        matches=[r["id"] for r in instruments or [] if r.get("symbol","").upper()==symbol
                 and r.get("exchange_segment")=="NSE_EQ" and r.get("regular_eq")
                 and r.get("trading_symbol_verified") and IDENTITY.fullmatch(str(r.get("id","")))
                 and (not r.get("isin") or r.get("isin")==isin)]
        if len(matches)==1:
            resolved[symbol]=matches[0]
    if len(set(resolved.values()))!=len(resolved):
        raise ValueError("Ambiguous current constituent IDs")
    return {"date":day.isoformat(),"symbols":sorted(members),"resolved":resolved,
            "source_sha256":receipt["sha256"],"covered_through":day.isoformat(),
            "source":CURRENT_MEMBERS_URL,"retrieved_utc":_iso(retrieved)}


def membership(day, instruments=None, *, as_of=None):
    """Current official list is valid only after capture on that same date."""
    current=_current_membership(day,instruments,as_of or _now())
    if current is not None:
        return current
    result = pit_index.query("banknifty_pit", day.isoformat(),
                             (day + timedelta(days=1)).isoformat(), instruments)
    members = result["asof_members"]
    if not 1 <= len(members) <= MAX_MEMBERS or len(set(members)) != len(members) or not all(SYMBOL.fullmatch(x) for x in members):
        raise ValueError("Invalid dated constituent membership")
    resolved = {}
    for row in result["resolved"]:
        symbol, identity = row.get("pit_symbol"), row.get("id")
        if symbol in members and isinstance(identity, str) and IDENTITY.fullmatch(identity):
            resolved[symbol] = identity
    if len(set(resolved.values())) != len(resolved):
        raise ValueError("Ambiguous constituent security identities")
    return {"date": day.isoformat(), "symbols": sorted(members), "resolved": resolved,
            "source_sha256": result["source_sha256"], "covered_through": result["covered_through"]}


def subscription_plan(used, day=None, *, capture_allowed=None):
    if not isinstance(used, int) or not 0 <= used <= 5000:
        raise ValueError("Invalid shared socket capacity")
    if not (enabled() if capture_allowed is None else capture_allowed):
        return None, {}, "not_enabled"
    day = day or _local_day(_now())
    try:
        master = dhan_workspace.catalog()
        info = membership(day, master)
    except (ValueError, OSError, KeyError, TypeError):
        return None, {}, "dated_membership_or_master_unavailable"
    # Never pick arbitrary partial members based on a stale weight list.
    # If all exact identities cannot fit, options and index tickers win.
    if len(info["resolved"]) != len(info["symbols"]):
        return None, info, "unresolved_constituent_identity"
    if len(info["resolved"]) > 5000 - used:
        return None, info, "insufficient_spare_capacity"
    rows = [{"ExchangeSegment":"NSE_EQ", "SecurityId":identity.split(":")[1]}
            for identity in info["resolved"].values()]
    return {"RequestCode":17, "InstrumentCount":len(rows), "InstrumentList":rows}, info, "awaiting_quotes"


def decode_quote(raw, code, segment, sid):
    if segment != 1 or code != 4 or sid <= 0 or len(raw) != 50:
        return None
    ltp, ltq, ltt, atp, volume, sell, buy, op, prev, high, low = struct.unpack_from("<fHIfIIIffff", raw, 8)
    if not math.isfinite(ltp) or ltp <= 0 or ltt < 1_400_000_000:
        return None
    return {"kind":"constituent_quote", "identity":"NSE_EQ:"+str(sid),
            "price":float(ltp), "trade_epoch":int(ltt), "volume":int(volume),
            "atp":float(atp) if math.isfinite(atp) and atp>0 else None,
            "buy_quantity":int(buy), "sell_quantity":int(sell),
            "packet_sha256":sha256(raw).hexdigest()}


def _setup(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS banknifty_constituent_quotes(
      identity TEXT NOT NULL, symbol TEXT NOT NULL, session_ist TEXT NOT NULL,
      received_utc TEXT NOT NULL, exchange_trade_utc TEXT NOT NULL,
      price REAL NOT NULL CHECK(price>0), volume INTEGER NOT NULL,
      atp REAL, buy_quantity INTEGER NOT NULL, sell_quantity INTEGER NOT NULL,
      packet_sha256 TEXT NOT NULL, session_id TEXT NOT NULL,
      membership_sha256 TEXT NOT NULL,
      PRIMARY KEY(identity,received_utc,packet_sha256)
    );
    CREATE INDEX IF NOT EXISTS bank_constituent_session
      ON banknifty_constituent_quotes(session_ist,symbol,received_utc);
    CREATE INDEX IF NOT EXISTS bank_constituent_receipt
      ON banknifty_constituent_quotes(received_utc);
    """)


class Capture:
    def __init__(self):
        self.lock = RLock()
        self.queue = Queue(maxsize=MAX_QUEUE)
        self.session = None
        self.info = {}
        self.mapping = {}
        self.connected = False
        self.state = "not_subscribed"
        self.last = {}
        self.saved = 0
        self.dropped = 0
        self.stale = 0
        self.sampled_out = 0
        self.last_saved_utc = None

    def begin(self, session, info, state):
        with self.lock:
            self.session = session
            self.info = info
            self.mapping = {v:k for k,v in info.get("resolved",{}).items()} if state=="awaiting_quotes" else {}
            self.connected = bool(self.mapping)
            self.state = state
            self.last = {}

    def end(self, session):
        with self.lock:
            if self.session == session:
                self.connected = False
                self.state = "disconnected" if self.mapping else self.state

    def disconnect(self, reason="disconnected"):
        with self.lock:
            self.connected = False
            self.state = reason

    def submit(self, event, received, session):
        with self.lock:
            identity = event["identity"]
            if not self.connected or session != self.session or identity not in self.mapping:
                return
            trade = datetime.fromtimestamp(event["trade_epoch"],timezone.utc)
            age = (received-trade).total_seconds()
            local = trade.astimezone(live_market.IST)
            minute = local.hour*60 + local.minute
            if not -2<=age<=MAX_AGE or local.date().isoformat()!=self.info["date"] or not 555<=minute<930 or local.weekday()>=5:
                self.stale += 1
                return
            prev = self.last.get(identity)
            if prev and (event["trade_epoch"]<prev[2] or event["packet_sha256"]==prev[1] or received.timestamp()-prev[0]<SAMPLE_SECONDS):
                self.sampled_out += 1
                return
            row = (identity, self.mapping[identity], local.date().isoformat(), _iso(received),
                   _iso(trade), event["price"], event["volume"], event["atp"],
                   event["buy_quantity"], event["sell_quantity"], event["packet_sha256"],
                   session, self.info["source_sha256"])
            try:
                self.queue.put_nowait(row)
            except Full:
                self.dropped += 1
                self.state = "capture_queue_overflow"
                return
            self.last[identity] = (received.timestamp(),event["packet_sha256"],event["trade_epoch"])

    def writer(self, stop):
        initialized = False
        while not stop.is_set() or not self.queue.empty():
            try:
                batch = [self.queue.get(timeout=.5)]
            except Empty:
                continue
            # Coalesce writes for a short bounded interval instead of opening
            # SQLite for every quote. This never blocks the socket receiver.
            until = time.monotonic()+.20
            while len(batch)<128 and time.monotonic()<until:
                try:
                    batch.append(self.queue.get(timeout=max(.001,until-time.monotonic())))
                except Empty:
                    break
            try:
                if not recorder_storage.allow(STREAM,dropped=len(batch)):
                    with self.lock:
                        self.dropped += len(batch)
                    continue
                with live_market._database() as db:
                    db.execute("PRAGMA busy_timeout=500")
                    if not initialized:
                        _setup(db)
                        initialized = True
                    prior = db.total_changes
                    db.executemany("INSERT OR IGNORE INTO banknifty_constituent_quotes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",batch)
                    count = db.total_changes-prior
                recorder_storage.saved(STREAM,batch[-1][3],count=count)
                with self.lock:
                    self.saved += count
                    self.last_saved_utc = batch[-1][3]
                    if self.connected:
                        self.state = "recording_sampled_quotes"
            except (OSError,sqlite3.Error,ValueError):
                initialized = False
                recorder_storage.failure(STREAM,"constituent_write_failed",dropped=len(batch))
                with self.lock:
                    self.dropped += len(batch)
                    self.state = "storage_error"
            finally:
                for _ in batch:
                    self.queue.task_done()

    def status(self):
        with self.lock:
            return {"state":self.state,"connected":self.connected,"requested":dict(self.mapping),
                    "membership":dict(self.info),"saved":self.saved,"dropped":self.dropped,
                    "ignored_stale":self.stale,"sampled_or_duplicate":self.sampled_out,
                    "queue_depth":self.queue.qsize(),"last_saved_utc":self.last_saved_utc,
                    "sample_seconds":SAMPLE_SECONDS}


CAPTURE = Capture()


def status():
    current=CAPTURE.status()
    allowed=enabled()
    if allowed and not current["connected"] and current["state"] in ("not_enabled","not_subscribed","disabled_by_user"):
        current["state"]="enabled_waiting_for_shared_connection"
    elif not allowed:
        current["state"]="disabled_by_user"
    return {**current,"enabled":allowed,"read_only":True,
            "storage":recorder_storage.status(STREAM),
            "note":"Constituent recording uses spare slots on the existing all-option Quote/OI socket. Enablement applies at the next normal connection. No option subscription is displaced; no sixth socket is opened."}


def _parse_weights(text):
    reader = csv.DictReader(io.StringIO(text.strip()))
    if reader.fieldnames != ["symbol","weight_pct"]:
        raise ValueError("CSV columns must be exactly symbol,weight_pct")
    weights = {}
    for row in reader:
        symbol = str(row["symbol"] or "").strip().upper()
        weight = float(row["weight_pct"])
        if None in row or row.get("weight_pct") is None or symbol in weights or not SYMBOL.fullmatch(symbol) or not math.isfinite(weight) or not 0<weight<=100:
            raise ValueError("Invalid, duplicate or nonpositive weight")
        weights[symbol] = weight
        if len(weights)>MAX_MEMBERS:
            raise ValueError("Too many constituents")
    total = sum(weights.values())
    if abs(total-100)>.1:
        raise ValueError("Weights must contain every dated member exactly once and sum to 100% within 0.1 percentage point")
    return weights, total


def save_weights(snapshot_date, text, source, confirm):
    """User-supplied dated percentage weights, with strict membership and provenance."""
    if confirm is not True or not isinstance(text,str) or len(text)>16000 or not isinstance(source,str) or not 3<=len(source.strip())<=300:
        raise ValueError("Provide reviewed source weights, a source label and explicit confirmation")
    day = date.fromisoformat(snapshot_date)
    if day>_local_day(_now()):
        raise ValueError("Weight snapshot cannot be future dated")
    info = membership(day)
    weights,total = _parse_weights(text)
    if set(weights)!=set(info['symbols']):
        raise ValueError('Weights must contain every dated member exactly once')
    body = {"snapshot_date":day.isoformat(),"source":source.strip(),"recorded_utc":_iso(_now()),
            "source_csv_sha256":sha256(text.encode()).hexdigest(),"original_csv":text,"membership_sha256":info["source_sha256"],
            "weights_pct":weights,"reported_weight_sum_pct":total,
            "independently_verified":False}
    # Preserve each version and its actual receipt time; never replace past evidence.
    key = sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()[:16]
    _write_json(_safe_folder()/("weights_"+day.isoformat()+"_"+key+".json"),body)
    return {k:v for k,v in body.items() if k!='original_csv'}


def _weights_for(day, asof, members):
    try:
        folder = _safe_folder()
        if not folder.is_dir():
            return None
        candidates = []
        with os.scandir(folder) as entries:
            for i, entry in enumerate(entries):
                if i>=1000:
                    # Refuse incomplete searches rather than pretend latest.
                    return None
                if not re.fullmatch(r"weights_\d{4}-\d{2}-\d{2}_[0-9a-f]{16}\.json",entry.name) or not entry.is_file(follow_symlinks=False) or entry.stat().st_size>50000:
                    continue
                value = json.loads(Path(entry.path).read_text())
                snapshot = date.fromisoformat(value["snapshot_date"])
                recorded = datetime.fromisoformat(value["recorded_utc"])
                w = value["weights_pct"]
                if not 0<=(day-snapshot).days<=35 or recorded>asof or set(w)!=set(members) or sha256(value["original_csv"].encode()).hexdigest()!=value["source_csv_sha256"]:
                    continue
                raw_weights,raw_sum = _parse_weights(value['original_csv'])
                if raw_weights!=w or abs(raw_sum-value['reported_weight_sum_pct'])>1e-8:
                    continue
                if any(type(x) not in (int,float) or not math.isfinite(x) or not 0<x<=100 for x in w.values()) or abs(sum(w.values())-100)>.1:
                    continue
                candidates.append(value)
        return {k:v for k,v in max(candidates,key=lambda x:(x["snapshot_date"],x["recorded_utc"])).items() if k!='original_csv'} if candidates else None
    except (OSError,ValueError,TypeError,KeyError,AttributeError,OverflowError):
        return None


def _quote(db, symbol, day, target):
    low = _iso(target-timedelta(seconds=MAX_AGE))
    hi = _iso(target)
    row = db.execute("""SELECT identity,received_utc,exchange_trade_utc,price,volume,atp,buy_quantity,sell_quantity,packet_sha256,membership_sha256
        FROM banknifty_constituent_quotes
        WHERE session_ist=? AND symbol=? AND received_utc>=? AND received_utc<=?
        ORDER BY received_utc DESC LIMIT 1""",(day.isoformat(),symbol,low,hi)).fetchone()
    if not row:
        return None
    trade = datetime.fromisoformat(row[2])
    if not 0<=(target-trade).total_seconds()<=MAX_AGE:
        return None
    return dict(zip(("identity","received_utc","exchange_trade_utc","price","volume","atp","buy_quantity","sell_quantity","packet_sha256","membership_sha256"),row))


def opening_sample(db, symbol, day, target):
    """Last eligible quote in the first 30 seconds of the regular session.

    This is an observed opening sample, not the exchange's official open.
    Never use a sample later than the requested cutoff.
    """
    start = datetime.combine(day, clock_time(9, 15), ZoneInfo("Asia/Kolkata"))
    end = min(target, start + timedelta(seconds=MAX_AGE))
    if end < start:
        return None
    sample = _quote(db, symbol, day, end)
    if not sample:
        return None
    if datetime.fromisoformat(sample["received_utc"]) < start or datetime.fromisoformat(sample["exchange_trade_utc"]) < start:
        return None
    return sample


def session_return(current, opening):
    if not current or not opening or current["identity"] != opening["identity"] or opening["price"] <= 0:
        return {"session_return_pct": None, "session_anchor_utc": None}
    return {"session_return_pct": 100*(current["price"]/opening["price"]-1),
            "session_anchor_utc": opening["received_utc"]}


def calculate_row(current, anchor, baselines, weight, index_anchor):
    out = {"return_pct":None,"volume_delta":None,"relative_volume":None,
           "baseline_sessions":0,"atp_deviation_pct":None,"displayed_quantity_imbalance":None,
           "contribution_pp":None,"approx_index_points":None}
    if not current:
        return out
    if current["atp"] and current["atp"]>0:
        out["atp_deviation_pct"] = 100*(current["price"]/current["atp"]-1)
    total = current["buy_quantity"]+current["sell_quantity"]
    if total>0:
        out["displayed_quantity_imbalance"] = (current["buy_quantity"]-current["sell_quantity"])/total
    if not anchor or anchor["identity"]!=current["identity"] or anchor["price"]<=0:
        return out
    r = current["price"]/anchor["price"]-1
    out["return_pct"] = 100*r
    if current["volume"]>=anchor["volume"]:
        out["volume_delta"] = current["volume"]-anchor["volume"]
        valid = [v for v in baselines if v is not None and v>=0]
        out["baseline_sessions"] = len(valid)
        if len(valid)>=5 and sum(valid)>0:
            out["relative_volume"] = out["volume_delta"]/(sum(valid)/len(valid))
    if weight is not None:
        out["contribution_pp"] = weight*r
        if index_anchor is not None:
            out["approx_index_points"] = index_anchor*(weight/100)*r
    return out


def _index_anchor(db, target):
    try:
        row = db.execute("""SELECT price,exchange_utc FROM live_ticks
           WHERE identity='INDEX:BANKNIFTY' AND exchange_utc>=? AND exchange_utc<=? AND received_utc<=?
           ORDER BY exchange_utc DESC LIMIT 1""",
           (_iso(target-timedelta(seconds=MAX_AGE)),_iso(target),_iso(target))).fetchone()
        return float(row[0]) if row and math.isfinite(row[0]) and row[0]>0 else None
    except sqlite3.OperationalError:
        return None


def analyze(horizon=5, as_of=""):
    if horizon not in HORIZONS:
        raise ValueError("Choose 1, 5, 10, 30 or 60 minutes")
    now = _now()
    target = datetime.fromisoformat(as_of.replace("Z","+00:00")) if as_of else now
    if target.tzinfo is None or target>now:
        raise ValueError("Analysis time must be timezone-aware and not in the future")
    target = target.astimezone(timezone.utc)
    day = _local_day(target)
    start = target-timedelta(minutes=horizon)
    blockers = []
    try:
        info = membership(day,as_of=target)
    except (OSError,ValueError,TypeError,KeyError):
        info = {"date":day.isoformat(),"symbols":[]}
        blockers.append("Dated BANKNIFTY membership is unavailable for this session. Sync reviewed membership evidence.")
    members = info["symbols"]
    snapshot = _weights_for(day,target,members) if members else None
    weights = snapshot["weights_pct"] if snapshot else {}
    if not snapshot:
        blockers.append("No reviewed, timely, complete weight snapshot known by this analysis time. Weighted metrics are unavailable.")
    rows = []
    index = None
    path = shared_market_data.database_path()
    if members and market_inventory._safe_file(path) and _local_day(start)==day:
        try:
            with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=.5)) as db:
                db.execute("PRAGMA query_only=ON")
                db.execute("PRAGMA trusted_schema=OFF")
                deadline=time.monotonic()+2.0
                db.set_progress_handler(lambda:int(time.monotonic()>deadline),5000)
                prior = [date.fromisoformat(r[0]) for r in db.execute(
                    "SELECT DISTINCT session_ist FROM banknifty_constituent_quotes WHERE session_ist<? ORDER BY session_ist DESC LIMIT 10",(day.isoformat(),))]
                index = _index_anchor(db,start)
                for symbol in members:
                    current, anchor = _quote(db,symbol,day,target), _quote(db,symbol,day,start)
                    baseline = []
                    for previous in prior:
                        shift = timedelta(days=(day-previous).days)
                        c,a = _quote(db,symbol,previous,target-shift),_quote(db,symbol,previous,start-shift)
                        if current and c and a and c["identity"]==a["identity"]==current["identity"] and c["volume"]>=a["volume"]:
                            baseline.append(c["volume"]-a["volume"])
                    opening = opening_sample(db, symbol, day, target)
                    rows.append({"symbol":symbol,"weight_pct":weights.get(symbol),"current":current,"anchor":anchor,
                                 **calculate_row(current,anchor,baseline,weights.get(symbol),index),
                                 **session_return(current,opening)})
        except (sqlite3.Error,OSError,ValueError,TypeError):
            rows=[]
            blockers.append("Stored quote query could not complete; data remains unavailable. Retry without interrupting the recorder.")
    if not rows:
        rows=[{"symbol":s,"weight_pct":weights.get(s),"current":None,"anchor":None,
               **calculate_row(None,None,[],weights.get(s),None),
               **session_return(None,None)} for s in members]
    observed=[r for r in rows if r["return_pct"] is not None]
    weighted=[r for r in observed if r["weight_pct"] is not None]
    coverage=sum(r["weight_pct"] for r in weighted) if snapshot else None
    complete=bool(snapshot and len(weighted)==len(members) and members)
    if len(observed)<len(members):
        blockers.append("Incomplete aligned constituent quotes. Unobserved moves are not zero-filled.")
    if index is None:
        blockers.append("No fresh original BANKNIFTY spot anchor; point contributions are unavailable.")
    return {"as_of_utc":_iso(target),"anchor_utc":_iso(start),"session_ist":day.isoformat(),"horizon_minutes":horizon,
            "membership":info,"weight_snapshot":snapshot,"rows":rows,"expected_members":len(members),
            "observed_members":len(observed),"observed_weight_pct":coverage,"complete_weighted_coverage":complete,
            "weighted_return_pct":sum(r["contribution_pp"] for r in weighted) if complete else None,
            "weighted_breadth_pct":sum(r["weight_pct"]*(1 if r["return_pct"]>0 else -1 if r["return_pct"]<0 else 0) for r in weighted) if complete else None,
            "partial_contribution_pp":sum(r["contribution_pp"] for r in weighted) if weighted else None,
            "spot_anchor":index,"blockers":blockers,
            "note":"Descriptive price pressure using sampled, receipt-time-aligned original quotes and user-reviewed dated weights (not exact live index weights). Relative volume compares same-time intervals over available prior recorded sessions; at least five are required. ATP and displayed quantity imbalance are not aggressor flow. No calibrated forecast or trade recommendation."}


def import_archived_weights(receipt_id,filename,snapshot_date,confirm_reviewed):
    """Normalize exact percent columns from an authorized, hash-checked local CSV.
    The original file remains immutable in the intake archive. Never fetch a
    network source, guess publication dates, units, symbols or index membership.
    """
    from . import nse_source_automation as intake
    if confirm_reviewed is not True or not re.fullmatch(r"intake_[0-9a-f]{16}",receipt_id or ""):
        raise ValueError("Select a reviewed saved intake receipt")
    name=intake._safe_name(filename)
    if not name.lower().endswith(".csv"):
        raise ValueError("Select an original CSV (not an extracted or arbitrary file)")
    root=service.DATA/"nse"/"authorized_intake"/receipt_id
    metadata=root/"SOURCE_INTAKE.json"
    file=root/"originals"/name
    if not market_inventory._safe_file(metadata) or not market_inventory._safe_file(file) or metadata.stat().st_size>256000 or not 0<file.stat().st_size<=200000:
        raise ValueError("Saved original weight CSV or receipt is unavailable")
    value=json.loads(metadata.read_text())
    if value.get("id")!=receipt_id or value.get("source")!="user_provided_local_export":
        raise ValueError("Receipt identity mismatch")
    matches=[r for r in value.get("files",[]) if r.get("name")==name]
    raw=file.read_bytes()
    digest=sha256(raw).hexdigest()
    if len(matches)!=1 or len(raw)!=matches[0].get("bytes") or digest!=matches[0].get("original_sha256"):
        raise ValueError("Archived source bytes no longer match intake SHA-256")
    reader=csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    cols=reader.fieldnames or []
    symbols=[c for c in cols if c.strip().casefold() in ("symbol","ticker")]
    weights=[c for c in cols if c.strip().casefold() in ("weight_pct","weightage","weightage (%)","weight (%)","weight")]
    if len(symbols)!=1 or len(weights)!=1:
        raise ValueError("Source must have one Symbol/Ticker and one explicitly reviewed percentage Weight column")
    out=io.StringIO()
    writer=csv.writer(out,lineterminator="\n")
    writer.writerow(["symbol","weight_pct"])
    for i,row in enumerate(reader):
        if i>=MAX_MEMBERS or None in row:
            raise ValueError("Source CSV must contain exactly the dated BANKNIFTY members, not multiple indices")
        symbol=row.get(symbols[0])
        weight=row.get(weights[0])
        if symbol is None or weight is None:
            raise ValueError("Missing original symbol or weight")
        writer.writerow([symbol.strip().upper(),weight.strip().removesuffix("%").strip()])
    return save_weights(snapshot_date,out.getvalue(),
                        ("Authorized local intake "+receipt_id+" / "+name[:90]+" / original SHA-256 "+digest),True)
