"""Optional exact constituent FUTSTK/OPTSTK capture on spare shared feed capacity.

Only fresh local master records with explicit underlying symbol or security ID
are eligible. No derivative symbol-prefix matching, extra socket or displacement.
Futures select the unique nearest expiry; stock options are explicitly selected.
"""
from __future__ import annotations
from contextlib import closing
from datetime import date,datetime,timedelta,timezone
from functools import lru_cache
from queue import Queue,Empty,Full
from threading import RLock
import csv
import json
import math
import re
import sqlite3
import time

from . import banknifty_constituents as bank, dhan_workspace, option_chain_live, live_market, market_inventory, recorder_storage, shared_market_data

ID=re.compile(r"^NSE_FNO:[0-9]{1,12}$")
MAX_OPTIONS=50
MAX_CONTRACTS=100
STREAM="constituent_derivative_events"
LOCK=RLock()

def _now():
    return datetime.now(timezone.utc)

def _config():
    p=bank._safe_folder()/"derivative_consent.json"
    if not p.is_file() or p.is_symlink() or p.stat().st_size>12000:
        return {"enabled":False,"option_ids":[]}
    try:
        value=json.loads(p.read_text())
        ids=value.get("option_ids",[])
        if not isinstance(ids,list) or len(ids)>MAX_OPTIONS or any(not isinstance(x,str) or not ID.fullmatch(x) for x in ids):
            raise ValueError("Invalid saved derivative choices")
        return {"enabled":value.get("enabled") is True,"option_ids":sorted(set(ids))}
    except (OSError,ValueError,TypeError,AttributeError):
        return {"enabled":False,"option_ids":[]}

def enabled():
    try:
        return _config()["enabled"]
    except (OSError,ValueError):
        return False

@lru_cache(maxsize=3)
def _catalog(filename,mtime_ns,size,day_text,member_pairs):
    members=dict(member_pairs)
    by_security={v.split(":")[1]:k for k,v in members.items()}
    day=date.fromisoformat(day_text)
    items={}
    duplicate=set()
    with open(filename,encoding="utf-8-sig",newline="") as fd:
        reader=csv.DictReader(fd)
        cols=option_chain_live._fields(reader)
        field=lambda *names:option_chain_live._get_field(cols,*names)
        sec=field("SECURITY_ID","SEM_SMST_SECURITY_ID")
        exch=field("EXCH_ID","SEM_EXM_EXCH_ID")
        seg=field("SEGMENT","SEM_SEGMENT")
        kind=field("INSTRUMENT","SEM_INSTRUMENT_NAME")
        expiry=field("SM_EXPIRY_DATE","EXPIRY_DATE","SEM_EXPIRY_DATE")
        lot=field("LOT_SIZE","SEM_LOT_UNITS")
        symbol=field("UNDERLYING_SYMBOL")
        under_id=field("UNDERLYING_SECURITY_ID")
        strike=field("STRIKE_PRICE","SEM_STRIKE_PRICE")
        side=field("OPTION_TYPE","SEM_OPTION_TYPE")
        if not all((sec,exch,seg,kind,expiry,lot)) or not (symbol or under_id):
            raise ValueError("Local master lacks explicit derivative underlying identity columns; refresh the authorized detailed master")
        for row in reader:
            k=row[kind].strip().upper()
            if row[exch].strip().upper()!="NSE" or row[seg].strip().upper() not in ("D","NSE_FNO","FNO","F") or k not in ("FUTSTK","OPTSTK"):
                continue
            sym=(row.get(symbol) or "").strip().upper() if symbol else ""
            sid=(row.get(under_id) or "").strip() if under_id else ""
            a=sym if sym in members else None
            b=by_security.get(sid)
            if a and b and a!=b:
                continue
            member=a or b
            if not member or (sym and sym!=member) or (sid and sid!=members[member].split(":")[1]):
                continue
            identity="NSE_FNO:"+row[sec].strip()
            if not ID.fullmatch(identity):
                continue
            try:
                exp=date.fromisoformat(row[expiry].strip()[:10])
                units=float(row[lot])
                if exp<day or not math.isfinite(units) or not units.is_integer() or not 1<=units<=1000000:
                    continue
                strike_value=float(row[strike]) if k=="OPTSTK" and strike else None
                opt=row[side].strip().upper() if k=="OPTSTK" and side else None
                if k=="OPTSTK" and (strike_value is None or not math.isfinite(strike_value) or strike_value<=0 or opt not in ("CE","PE")):
                    continue
            except (ValueError,TypeError,KeyError):
                continue
            item={"identity":identity,"underlying":member,"instrument":k,"expiry":exp.isoformat(),
                  "lot_size":int(units),"strike":strike_value,"option_type":opt}
            if identity in items:
                duplicate.add(identity)
            items[identity]=item
    return tuple(sorted((x for key,x in items.items() if key not in duplicate),
                        key=lambda x:(x["underlying"],x["instrument"],x["expiry"],x["strike"] or 0,x["option_type"] or "",x["identity"])))

def discover(day=None):
    day=day or bank._local_day(_now())
    info=bank.membership(day,dhan_workspace.catalog())
    if len(info["resolved"])!=len(info["symbols"]):
        raise ValueError("Dated constituent equity identities are not fully resolved")
    p=dhan_workspace._master()
    if not market_inventory._safe_file(p):
        raise ValueError("Refresh the authorized local master")
    st=p.stat()
    if not 0<st.st_size<=option_chain_live.MAX_MASTER_BYTES or not 0<=_now().timestamp()-st.st_mtime<=48*3600:
        raise ValueError("Derivative master is oversized, stale or has an invalid timestamp")
    items=list(_catalog(str(p),st.st_mtime_ns,st.st_size,day.isoformat(),tuple(sorted(info["resolved"].items()))))
    futures=[]
    missing=[]
    for member in info["symbols"]:
        candidates=[x for x in items if x["underlying"]==member and x["instrument"]=="FUTSTK"]
        nearest=[x for x in candidates if x["expiry"]==candidates[0]["expiry"]] if candidates else []
        if len(nearest)==1:
            futures.append(nearest[0])
        else:
            missing.append(member)
    return info,futures,[x for x in items if x["instrument"]=="OPTSTK"],missing

def catalog(symbol="",offset=0,limit=100):
    if type(offset) is not int or type(limit) is not int or not 0<=offset<=100000 or not 1<=limit<=100:
        raise ValueError("Invalid contract pagination")
    info,futures,options,missing=discover()
    if symbol and symbol not in info["symbols"]:
        raise ValueError("Choose an exact dated constituent")
    filtered=[x for x in options if not symbol or x["underlying"]==symbol]
    return {"membership":info,"nearest_futures":futures,"unresolved_futures":missing,
            "options":filtered[offset:offset+limit],"option_count":len(filtered),"has_more":offset+limit<len(filtered),
            "offset":offset,"selected_option_ids":_config()["option_ids"],
            "note":"Local exact master discovery only. Missing or ambiguous contracts are not guessed; discovery does not establish live entitlement."}

def configure(value,option_ids,confirm):
    if type(value) is not bool or (value and confirm is not True) or not isinstance(option_ids,list) or len(option_ids)>MAX_OPTIONS or any(not isinstance(x,str) or not ID.fullmatch(x) for x in option_ids):
        raise ValueError("Review the local shared-feed consent and at most 50 exact stock-option IDs")
    ids=sorted(set(option_ids))
    if value:
        _,_,available,_=discover()
        if not set(ids)<=set(x["identity"] for x in available):
            raise ValueError("Some selected stock-option identities are stale or unavailable")
    with LOCK:
        bank._write_json(bank._safe_folder()/"derivative_consent.json",{"enabled":value,"option_ids":ids})
        if not value:
            CAPTURE.disconnect("disabled_by_user")
    return status()

def plan(used,*,allowed=True):
    if not allowed or not enabled():
        return [],{},"not_enabled"
    try:
        info,futures,options,missing=discover()
        selected=set(_config()["option_ids"])
        chosen=futures+[x for x in options if x["identity"] in selected]
        if selected-set(x["identity"] for x in options):
            return [],{},"selected_option_expired_or_unresolved"
        if not chosen:
            return [],{},"no_exact_derivative_contracts"
        if len(chosen)>MAX_CONTRACTS or not 0<=used<=5000 or len(chosen)>5000-used:
            return [],{},"insufficient_spare_capacity"
        mapping={x["identity"]:{**x,"membership_sha256":info["source_sha256"]} for x in chosen}
        messages=[{"RequestCode":17,"InstrumentCount":len(chosen),"InstrumentList":[{"ExchangeSegment":"NSE_FNO","SecurityId":x["identity"].split(":")[1]} for x in chosen]}]
        return messages,mapping,"awaiting_quotes_partial_futures" if missing else "awaiting_quotes"
    except (ValueError,OSError,KeyError,TypeError):
        return [],{},"dated_master_or_membership_unavailable"

def _setup(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS constituent_derivative_events(
      identity TEXT NOT NULL, underlying TEXT NOT NULL, instrument TEXT NOT NULL,
      expiry TEXT NOT NULL, strike REAL, option_type TEXT, lot_size INTEGER NOT NULL,
      received_utc TEXT NOT NULL, exchange_trade_utc TEXT, kind TEXT NOT NULL,
      price REAL, volume INTEGER, open_interest INTEGER, packet_sha256 TEXT NOT NULL,
      session_id TEXT NOT NULL, membership_sha256 TEXT NOT NULL,
      PRIMARY KEY(identity,received_utc,packet_sha256)
    );
    CREATE INDEX IF NOT EXISTS constituent_derivative_kind
      ON constituent_derivative_events(identity,kind,received_utc);
    CREATE INDEX IF NOT EXISTS constituent_derivative_receipt
      ON constituent_derivative_events(received_utc);
    """)

class Capture:
    def __init__(self):
        self.lock=RLock()
        self.queue=Queue(maxsize=2048)
        self.mapping={}
        self.session=None
        self.connected=False
        self.state="not_subscribed"
        self.last={}
        self.saved=0
        self.dropped=0
        self.sampled=0
        self.stale=0
    def begin(self,session,mapping,state):
        with self.lock:
            self.mapping=dict(mapping)
            self.session=session
            self.connected=bool(mapping)
            self.state=state
            self.last={}
    def owns(self,event,session):
        with self.lock:
            # Ownership persists for the entire subscribed session even when
            # paused, so derivative events cannot fall into index option logic.
            return self.session==session and ("NSE_FNO:"+str(event.get("security_id",""))) in self.mapping
    def end(self,session):
        with self.lock:
            if self.session==session:
                self.connected=False
                if self.mapping:
                    self.state="disconnected"
    def disconnect(self,reason="disconnected"):
        with self.lock:
            self.connected=False
            self.state=reason
    def submit(self,event,received,session):
        with self.lock:
            identity="NSE_FNO:"+str(event.get("security_id",""))
            if not self.connected or session!=self.session or identity not in self.mapping:
                return
            row=self.mapping[identity]
            kind=event["kind"]
            if kind not in ("quote","oi"):
                return
            local=received.astimezone(live_market.IST)
            if local.weekday()>=5 or not 555<=local.hour*60+local.minute<930 or local.date().isoformat()>row["expiry"]:
                self.stale+=1
                return
            trade=None
            if kind=="quote":
                trade=datetime.fromtimestamp(event["trade_epoch"],timezone.utc)
                if not -2<=(received-trade).total_seconds()<=30 or bank._local_day(trade)!=local.date():
                    self.stale+=1
                    return
            key=(identity,kind)
            previous=self.last.get(key)
            if previous and (received.timestamp()-previous[0]<2 or (kind=="quote" and previous[1]==event["packet_sha256"]) or (trade and previous[2] and trade.timestamp()<previous[2])):
                self.sampled+=1
                return
            try:
                self.queue.put_nowait((identity,row["underlying"],row["instrument"],row["expiry"],row["strike"],row["option_type"],row["lot_size"],
                    bank._iso(received),bank._iso(trade) if trade else None,kind,event.get("price"),event.get("volume"),event.get("oi"),
                    event["packet_sha256"],session,row["membership_sha256"]))
            except Full:
                self.dropped+=1
                self.state="queue_overflow"
                return
            self.last[key]=(received.timestamp(),event["packet_sha256"],trade.timestamp() if trade else None)
    def writer(self,stop):
        initialized=False
        while not stop.is_set() or not self.queue.empty():
            try:
                batch=[self.queue.get(timeout=.4)]
            except Empty:
                continue
            deadline=time.monotonic()+.2
            while len(batch)<128 and time.monotonic()<deadline:
                try:
                    batch.append(self.queue.get(timeout=max(.001,deadline-time.monotonic())))
                except Empty:
                    break
            try:
                if not recorder_storage.allow(STREAM,dropped=len(batch)):
                    with self.lock:self.dropped+=len(batch)
                    continue
                with live_market._database() as db:
                    db.execute("PRAGMA busy_timeout=400")
                    if not initialized:
                        _setup(db);initialized=True
                    before=db.total_changes
                    db.executemany("INSERT OR IGNORE INTO constituent_derivative_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",batch)
                    count=db.total_changes-before
                recorder_storage.saved(STREAM,batch[-1][7],count=count)
                with self.lock:
                    self.saved+=count
                    if self.connected:self.state="recording_sampled_derivatives"
            except (OSError,sqlite3.Error,ValueError):
                initialized=False
                recorder_storage.failure(STREAM,"constituent_derivative_write_failed",dropped=len(batch))
                with self.lock:
                    self.dropped+=len(batch)
                    self.state="storage_error"
            finally:
                for _ in batch:self.queue.task_done()
    def status(self):
        with self.lock:
            return {"state":self.state,"connected":self.connected,"requested":list(self.mapping.values()),
                    "saved":self.saved,"dropped":self.dropped,"sampled":self.sampled,"stale":self.stale,"queue_depth":self.queue.qsize()}

CAPTURE=Capture()

def status():
    return {**CAPTURE.status(),**_config(),"storage":recorder_storage.status(STREAM),"orders_enabled":False,
            "note":"Optional sampled futures and explicitly selected stock options; takes effect on next natural connection. No sixth socket or option displacement."}

def analysis(horizon=5,as_of=""):
    if horizon not in bank.HORIZONS:
        raise ValueError("Choose an approved lookback")
    now=_now()
    cutoff=datetime.fromisoformat(as_of.replace("Z","+00:00")) if as_of else now
    if cutoff.tzinfo is None or cutoff>now:
        raise ValueError("Use an actual timezone-aware timestamp")
    cutoff=cutoff.astimezone(timezone.utc)
    anchor=cutoff-timedelta(minutes=horizon)
    day=bank._local_day(cutoff)
    beginning=datetime.combine(day,datetime.min.time(),tzinfo=live_market.IST).astimezone(timezone.utc)
    rows=[]
    path=shared_market_data.database_path()
    if market_inventory._safe_file(path) and bank._local_day(anchor)==day:
        with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=.4)) as db:
            db.execute("PRAGMA query_only=ON")
            db.execute("PRAGMA trusted_schema=OFF")
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='constituent_derivative_events' AND type='table'").fetchone():
                deadline=time.monotonic()+2
                db.set_progress_handler(lambda:int(time.monotonic()>deadline),5000)
                db.execute("BEGIN")
                found=db.execute("""SELECT DISTINCT identity,underlying,instrument,expiry,strike,option_type,lot_size
                  FROM constituent_derivative_events WHERE received_utc>=? AND received_utc<=?
                  ORDER BY underlying,instrument,expiry,strike,option_type,identity LIMIT 201""",(bank._iso(beginning),bank._iso(cutoff))).fetchall()
                if len(found)>200 or len({x[0] for x in found})!=len(found):
                    raise ValueError("Too many distinct archived selections; inspect the exact source inventory")
                def lookup(identity,kind,end):
                    age=30 if kind=="quote" else 120
                    start=max(beginning,end-timedelta(seconds=age))
                    row=db.execute("""SELECT received_utc,exchange_trade_utc,price,volume,open_interest,packet_sha256
                      FROM constituent_derivative_events WHERE identity=? AND kind=? AND received_utc>=? AND received_utc<=?
                      ORDER BY received_utc DESC LIMIT 1""",(identity,kind,bank._iso(start),bank._iso(end))).fetchone()
                    if not row:
                        return None
                    if kind=="quote" and (not row[1] or not 0<=(end-datetime.fromisoformat(row[1])).total_seconds()<=30):
                        return None
                    return dict(zip(("received_utc","exchange_trade_utc","price","volume","open_interest","packet_sha256"),row))
                for item in found:
                    identity=item[0]
                    cur,old=lookup(identity,"quote",cutoff),lookup(identity,"quote",anchor)
                    oi,oldoi=lookup(identity,"oi",cutoff),lookup(identity,"oi",anchor)
                    rows.append({**dict(zip(("identity","underlying","instrument","expiry","strike","option_type","lot_size"),item)),
                        "quote":cur,"oi":oi,
                        "return_pct":100*(cur["price"]/old["price"]-1) if cur and old and old["price"]>0 else None,
                        "volume_delta":cur["volume"]-old["volume"] if cur and old and cur["volume"]>=old["volume"] else None,
                        "oi_delta":oi["open_interest"]-oldoi["open_interest"] if oi and oldoi else None})
    return {"rows":rows,"as_of_utc":bank._iso(cutoff),"horizon_minutes":horizon,
            "note":"Original sampled derivative receipts only. Quote age ≤30s, OI receipt age ≤120s; OI has no exchange trade timestamp. Missing values are unavailable. Reported volume/OI units and participant direction are not inferred."}
