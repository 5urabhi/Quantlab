"""Read-only Alpaca BOATS 5-minute overnight ETF trade bars.

US-listed ETF proxies, not local cash indices or GIFT NIFTY. The free
historical feed has a documented 15-minute delay. Use a 20-minute
post-bar-close archive assumption and actual later receipt times for
prospective work. No order or Dhan API, no fabricated missing bars.
"""
from contextlib import closing
from datetime import date, datetime, time, timedelta
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import math
import os
import sqlite3
import time as walltime
import uuid

from . import cpr_alpaca_archive as alpaca
from . import global_market_archive as g, service, shared_market_data, recorder_storage

SYMBOLS={
    "SPY":"US S&P 500 ETF","QQQ":"US Nasdaq 100 ETF",
    "EWY":"South Korea ETF","FXI":"China ETF","EWJ":"Japan ETF",
    "EWT":"Taiwan ETF","EWS":"Singapore ETF","EWH":"Hong Kong ETF",
    "EWA":"Australia ETF","KBE":"US banks ETF",
}
NY=ZoneInfo("America/New_York")
STEP=timedelta(minutes=5)
LAG=timedelta(minutes=20)
MAX_PAGES=4
MAX_WINDOWS=16
NOTE="US-listed BOATS overnight ETF trade bars, not official cash indices. Archive lag 20 minutes after bar close is an assumption; receipt mode uses actual import time. Missing bars are not filled."


def identity(symbol):
    if symbol not in SYMBOLS:
        raise ValueError("Unsupported overnight ETF")
    return "ALPACA:BOATS:"+symbol+":TRADE"


def session(day):
    """NY 20:00 previous calendar day to 04:00 ET on the Indian date.

    This is a reference time range, not proof of a trading day. Holiday
    closures and absent trades must be observed rather than filled.
    """
    left=datetime.combine(day-timedelta(days=1),time(20),NY).astimezone(g.UTC)
    right=datetime.combine(day,time(4),NY).astimezone(g.UTC)
    return left,right


def _stamp(value):
    if not isinstance(value,str):
        raise ValueError("Invalid provider timestamp")
    dt=datetime.fromisoformat(value.replace("Z","+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Missing provider timezone")
    return dt.astimezone(g.UTC)


def _floor(value):
    return value.replace(minute=value.minute//5*5,second=0,microsecond=0)


def normalize(raw, start, stop, received):
    """Validate each original page before writing; stop is exclusive."""
    if not isinstance(raw,bytes) or not 0<len(raw)<=alpaca.MAX_BODY:
        raise ValueError("Invalid bounded BOATS response")
    data=json.loads(raw)
    bars=data.get("bars")
    if bars is None:
        bars={}
    if not isinstance(bars,dict) or set(bars)-set(SYMBOLS):
        raise ValueError("Unexpected BOATS symbols")
    token=data.get("next_page_token")
    if token is not None and (not isinstance(token,str) or not 0<len(token)<=4096):
        raise ValueError("Invalid BOATS page token")
    output={}
    for symbol,values in bars.items():
        if not isinstance(values,list):
            raise ValueError("Invalid BOATS bar series")
        seen=set();rows=[]
        for bar in values:
            event=_stamp(bar["t"]);end=event+STEP
            if event!=_floor(event) or not start<=event<stop or end+LAG>received:
                raise ValueError("Out-of-range, incomplete, misaligned or not yet available BOATS bar")
            ref_start,ref_end=session(event.astimezone(g.IST).date())
            if not ref_start<=event<ref_end:
                raise ValueError("Bar outside overnight reference session")
            if event in seen:
                raise ValueError("Duplicate BOATS timestamp")
            seen.add(event)
            o,h,l,c=(g._number(bar[k],positive=True) for k in ("o","h","l","c"))
            v=g._number(bar["v"],positive=True)
            if not l<=min(o,c)<=max(o,c)<=h:
                raise ValueError("Inconsistent BOATS OHLC")
            rows.append((identity(symbol),"5m",g._iso(event),g._iso(end),o,h,l,c,v,g._iso(received)))
        if rows:
            output[symbol]=sorted(rows,key=lambda r:r[2])
    return output,token


def fetch_window(start,stop,*,mode,confirmed=False,now=None):
    """Bounded historical endpoint; never request data newer than the delay."""
    if confirmed is not True or mode not in ("archive","receipt"):
        raise ValueError("Review Alpaca data rights and availability before collecting")
    now=now or g._now()
    if start.tzinfo is None or stop.tzinfo is None or start!=_floor(start) or stop!=_floor(stop):
        raise ValueError("Require aligned timezone-aware bounds")
    if not timedelta(0)<stop-start<=timedelta(days=7) or stop+LAG>now:
        raise ValueError("Request a completed range up to seven days")
    auth=alpaca.credentials()
    if not auth:
        raise ValueError("Alpaca credentials missing")
    if not recorder_storage.allow("global_market_bars"):
        raise ValueError("Shared storage paused")
    params={"symbols":",".join(SYMBOLS),"timeframe":"5Min",
            "start":g._iso(start),"end":g._iso(stop-STEP),
            "feed":"boats","adjustment":"raw","asof":"-","limit":10000,"sort":"asc"}
    pages=[];tokens=set();seen=set()
    counts={symbol:0 for symbol in SYMBOLS}
    for _ in range(MAX_PAGES):
        raw=alpaca._http(params,*auth)
        received=g._now()
        groups,token=normalize(raw,start,stop,received)
        for symbol,rows in groups.items():
            for row in rows:
                key=(symbol,row[2])
                if key in seen:
                    raise ValueError("Overlapping BOATS pages")
                seen.add(key)
            counts[symbol]+=len(rows)
        pages.append((raw,received,groups))
        if token is None:
            break
        if token in tokens:
            raise ValueError("Repeated BOATS pagination token")
        tokens.add(token);params["page_token"]=token
    else:
        raise ValueError("BOATS page bound reached; request a shorter range")
    # Save only after all provider pages have been validated. Each
    # symbol/page transaction is independently idempotent and bounded.
    inserted=upgraded=0;receipts=[]
    lag=int(LAG.total_seconds()/60) if mode=="archive" else None
    for raw,received,groups in pages:
        for symbol,rows in groups.items():
            if not recorder_storage.allow("global_market_bars"):
                raise ValueError("Shared storage paused")
            key=[sha256(raw).hexdigest(),mode,lag,"alpaca_boats_5min_raw_v1",identity(symbol)]
            result=g.store_validated_rows(rows,raw,mode,lag,received,key)
            inserted+=result["inserted"];upgraded+=result.get("archive_upgraded",0)
            receipts.append(result["receipt_sha256"])
            if result["inserted"]:
                recorder_storage.saved("global_market_bars",g._iso(received),count=result["inserted"])
    return {"state":"observed" if receipts else "empty_provider_response",
            "from_utc":g._iso(start),"to_exclusive_utc":g._iso(stop),
            "counts":counts,"inserted":inserted,"archive_upgraded":upgraded,
            "receipts":receipts,"pages":len(pages),"note":NOTE}


def _window_key(start,stop):
    return "boats_5m_archive_v1:"+g._iso(start)+":"+g._iso(stop)+":20"


def _existing_window(start,stop):
    path=shared_market_data.database_path()
    if not path.is_file():
        return None
    with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='global_market_boats_windows' AND type='table'").fetchone():
            return None
        row=db.execute("SELECT summary FROM global_market_boats_windows WHERE window_key=?",
                       (_window_key(start,stop),)).fetchone()
        if not row:
            return None
        result=json.loads(row[0])
        hashes=result.get("receipts",[])
        # Empty windows are explicitly recorded but not treated as proof
        # of history availability; retry on an explicit subsequent run.
        if not hashes or not all(db.execute("SELECT 1 FROM global_market_receipts WHERE receipt_sha256=?",(h,)).fetchone() for h in hashes):
            return None
        return {**result,"state":"existing_observed_window","inserted":0,"archive_upgraded":0}


def _save_window(start,stop,result):
    path=shared_market_data.database_path()
    path.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(path,timeout=2)) as db, db:
        db.execute("""CREATE TABLE IF NOT EXISTS global_market_boats_windows(
            window_key TEXT PRIMARY KEY, summary TEXT NOT NULL)""")
        db.execute("INSERT OR REPLACE INTO global_market_boats_windows VALUES(?,?)",
                   (_window_key(start,stop),json.dumps(result,sort_keys=True)))


def backfill(start,stop,*,confirmed=False,max_windows=8,repair=False,progress=None):
    """Use Indian dates, end exclusive. Resume observed seven-day windows.

    An observed window is not complete market history. Empty windows
    remain explicitly unverified. Requests are independent of Dhan.
    """
    today=g._now().astimezone(g.IST).date()
    if confirmed is not True or not 0<(stop-start).days<=1827 or stop>today:
        raise ValueError("Review permissions and choose completed dates within five years")
    if type(max_windows) is not int or not 1<=max_windows<=MAX_WINDOWS:
        raise ValueError("Invalid bounded window limit")
    windows=[];attempts=0;day=stop
    counts=dict.fromkeys(SYMBOLS,0)
    while day>start:
        left_day=max(start,day-timedelta(days=7))
        left,_=session(left_day)
        _,right=session(day-timedelta(days=1))
        # DST changes may add an hour; the start-to-end interval is
        # still less than seven days because each night lasts eight.
        existing=None if repair else _existing_window(left,right)
        if existing is not None:
            outcome=existing
        else:
            if attempts>=max_windows:
                break
            attempts+=1
            try:
                outcome=fetch_window(left,right,mode="archive",confirmed=True)
                _save_window(left,right,outcome)
            except (ValueError,OSError,KeyError,TypeError,OverflowError,sqlite3.Error) as exc:
                # _http returns sanitized provider errors; do not expose
                # arbitrary raw response content or credentials.
                reason=str(exc) if isinstance(exc,ValueError) and str(exc).startswith(("Alpaca HTTP ","Alpaca network")) else type(exc).__name__
                windows.append({"from_date":str(left_day),"to_date_exclusive":str(day),"state":"paused_or_unavailable","reason":reason})
                break
            walltime.sleep(.25)
        for symbol,n in outcome["counts"].items():
            counts[symbol]+=n
        entry={"from_date":str(left_day),"to_date_exclusive":str(day),
               **{k:v for k,v in outcome.items() if k not in ("receipts","note")}}
        windows.append(entry)
        if progress is not None:
            progress(entry)
        day=left_day
    return {"state":"range_attempted" if day==start else "remaining_range_not_attempted",
            "from_date":str(start),"to_date_exclusive":str(stop),"remaining_to_exclusive":str(day),
            "counts":counts,"windows":windows,"note":NOTE}


def _config_path():
    return service.DATA/"research_workspace"/"alpaca_boats.json"


def enabled():
    path=_config_path()
    if not path.exists():
        return False
    if path.is_symlink() or path.stat().st_size>8192:
        raise ValueError("Unsafe overnight configuration")
    return json.loads(path.read_text(encoding="utf-8"))=={"version":1,"enabled":True}


def configure(value,*,confirmed=False):
    if value is True and (confirmed is not True or not alpaca.credentials()):
        raise ValueError("Review permission and configure existing Alpaca credentials")
    path=_config_path()
    if path.is_symlink():
        raise ValueError("Unsafe overnight configuration")
    if value is False:
        path.unlink(missing_ok=True)
        return {"enabled":False}
    if value is not True:
        raise ValueError("Use a boolean enablement")
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name("."+path.name+"."+uuid.uuid4().hex)
    try:
        tmp.write_text(json.dumps({"version":1,"enabled":True}),encoding="utf-8")
        os.replace(tmp,path)
    finally:
        tmp.unlink(missing_ok=True)
    return {"enabled":True,"note":NOTE}


def live_bounds(now):
    day=now.astimezone(g.IST).date()
    start,end=session(day)
    if day.weekday()>=5 or not start+STEP+LAG<=now<=end+LAG+STEP:
        return None
    stop=min(end,_floor(now-LAG))
    left=max(start,stop-timedelta(hours=1))
    return (left,stop) if stop>left else None


def collect_recent(*,now=None):
    now=now or g._now()
    bounds=live_bounds(now)
    if not bounds:
        return 0
    result=fetch_window(*bounds,mode="receipt",confirmed=True,now=now)
    return result["inserted"]


def features(db,day,cutoff,*,mode="archive"):
    """Delayed as-of session and rolling returns; no stale price substitution."""
    if mode not in ("archive","receipt") or cutoff.tzinfo is None or cutoff.astimezone(g.IST).date()!=day:
        raise ValueError("Invalid overnight feature cutoff")
    start,end=session(day)
    expected_end=min(end,_floor(cutoff-LAG))
    known="archive_known_utc" if mode=="archive" else "receipt_known_utc"
    expected=max(0,int((expected_end-start)/STEP))
    exists=g._table_exists(db)
    result={}
    for symbol,label in SYMBOLS.items():
        row={"symbol":symbol,"label":label,"state":"missing","session_return_bps":None,
             "trailing_30m_bps":None,"observed_bars":0,"reference_slots":expected,
             "coverage_ratio":None,"latest_bar_end_utc":None,"latest_known_utc":None,
             "age_minutes":None,"mode":mode,"proxy_not_cash":True}
        if exists and expected:
            bars=db.execute("""SELECT bar_start_utc,bar_end_utc,open,close,"""+known+"""
                FROM global_market_bars WHERE identity=? AND resolution='5m'
                AND bar_start_utc>=? AND bar_end_utc<=? AND """+known+"""<=?
                ORDER BY bar_start_utc""",(identity(symbol),g._iso(start),g._iso(expected_end),g._iso(cutoff))).fetchall()
            row["observed_bars"]=len(bars);row["coverage_ratio"]=len(bars)/expected
            if bars:
                last=bars[-1];last_end=_stamp(last[1])
                row.update(latest_bar_end_utc=last[1],latest_known_utc=last[4],
                           age_minutes=(cutoff-last_end).total_seconds()/60,state="stale")
                # Known delay is expected; tolerate at most two further
                # five-minute slots relative to the latest possible bar.
                if expected_end-last_end<=2*STEP and cutoff-last_end<=LAG+3*STEP:
                    row["state"]="observed_proxy"
                    first=bars[0]
                    if _stamp(first[0])==start:
                        row["session_return_bps"]=10000*(last[3]/first[2]-1)
                    target=last_end-timedelta(minutes=30)
                    anchor=next((b for b in reversed(bars) if _stamp(b[1])==target),None)
                    if anchor is not None:
                        row["trailing_30m_bps"]=10000*(last[3]/anchor[3]-1)
        result[symbol]=row
    return result
