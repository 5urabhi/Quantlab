"""Opt-in, local, read-only market context collector.

No guessed provider symbols, no trading calls, no secret-bearing URLs in
status or logs. Latest-vintage daily data is usable only from real receipt.
Worker is independent of Dhan capture and the research executor.
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone, date, time as clock
from hashlib import sha256
from pathlib import Path
from threading import Event, Lock, Thread
from zoneinfo import ZoneInfo
import csv
import io
import json
import math
import os
import re
import sqlite3
import time

import httpx

from . import service, market_context as m, context_events as events, advanced_options as ao
from . import shared_market_data, recorder_storage

FRED_URL="https://api.stlouisfed.org/fred/"
TWELVE_URL="https://api.twelvedata.com/time_series"
FRED_SERIES={"SP500_CLOSE":"SP500","NASDAQ_CLOSE":"NASDAQCOM","NIKKEI_CLOSE":"NIKKEI225",
             "US_VIX_CLOSE":"VIXCLS","USDINR_CLOSE":"DEXINUS","BRENT_CLOSE":"DCOILBRENTEU","US10Y":"DGS10"}
DEFAULT={"enabled":False,"fred":True,"news":True,"mappings":[]}
MAX_MAPPINGS=8
IST=ZoneInfo("Asia/Kolkata")
_LOCK=Lock()
_SYNC_LOCK=Lock()
_STOP=Event()
_WAKE=Event()
_THREAD=None
_REQUESTED=False
_RESULTS={}
_LAST_ATTEMPT={}
_LAST_SYNC=None
_MIN_REQUEST_INTERVAL=60
_LAST_REQUEST=0.
MAX_BODY=2_000_000


def _path():
    return service.DATA/"research_workspace"/"market_context_feeds.json"


def _validate(config):
    if not isinstance(config,dict) or set(config)!=set(DEFAULT):
        raise ValueError("Invalid market context feed configuration")
    if any(type(config[k]) is not bool for k in ("enabled","fred","news")):
        raise ValueError("Feed enablement must be boolean")
    rows=config["mappings"]
    if not isinstance(rows,list) or len(rows)>MAX_MAPPINGS:
        raise ValueError("At most eight reviewed Twelve Data instruments per worker")
    seen=set();out=[]
    for r in rows:
        if not isinstance(r,dict) or set(r)!={"factor","symbol","exchange"}:
            raise ValueError("Mapping requires factor, symbol and exact provider exchange")
        factor=r["factor"];symbol=r["symbol"];exchange=r["exchange"]
        if factor not in m.FACTORS or m.FACTORS[factor][0] not in ("daily_return","intraday_return") or factor in seen:
            raise ValueError("Mapping requires a distinct supported price factor")
        if factor in FRED_SERIES and config["fred"]:
            raise ValueError("Do not map a factor already assigned to FRED")
        if not isinstance(symbol,str) or not re.fullmatch(r"[A-Za-z0-9_.:/=\-]{1,40}",symbol):
            raise ValueError("Enter the exact authorized provider symbol")
        if not isinstance(exchange,str) or not re.fullmatch(r"[A-Za-z0-9_. /&()\-]{1,60}",exchange):
            raise ValueError("Enter the exact provider exchange from instrument metadata")
        seen.add(factor);out.append({"factor":factor,"symbol":symbol,"exchange":exchange})
    return {**config,"mappings":out}


def _config():
    path=_path()
    if not path.exists():
        return dict(DEFAULT)
    if path.is_symlink() or path.stat().st_size>32_000:
        raise ValueError("Unsafe feed configuration file")
    return _validate(json.loads(path.read_text(encoding="utf-8")))


def configure(config,confirm):
    if confirm is not True:
        raise ValueError("Review data-source terms, permissions and instrument identities before enabling")
    value=_validate(config)
    path=_path();path.parent.mkdir(parents=True,exist_ok=True)
    with _LOCK:
        tmp=path.with_name("."+path.name+".tmp")
        if path.is_symlink() or tmp.is_symlink():
            raise ValueError("Unsafe local configuration")
        try:
            with tmp.open("w",encoding="utf-8") as f:
                json.dump(value,f,sort_keys=True)
            os.replace(tmp,path)
        finally:
            tmp.unlink(missing_ok=True)
    _WAKE.set()
    return status()


def status():
    try:
        config=_config();error=None
    except (ValueError,OSError,TypeError,KeyError):
        config=dict(DEFAULT);error="Local feed configuration is invalid; automatic collection is disabled"
    with _LOCK:
        return {"config":config,"configuration_error":error,"worker_running":bool(_THREAD and _THREAD.is_alive()),
                "sync_running":_SYNC_LOCK.locked(),"last_sync_utc":_LAST_SYNC,"sources":dict(_RESULTS),
                "fred_key_configured":bool(os.getenv("FRED_API_KEY","").strip()),
                "twelve_key_configured":bool(os.getenv("TWELVE_DATA_API_KEY","").strip()),
                "fred_catalog":dict(FRED_SERIES),"max_mappings":MAX_MAPPINGS,
                "note":"Actual provider responses and entitlements remain unverified until collected. The worker runs only while QuantLab is open. Local receipt times are not exchange publication times."}


def _http(url,params=None):
    # Fixed hosts only; no redirects, no retries, no credentials in exceptions.
    try:
        with httpx.Client(timeout=httpx.Timeout(10.,connect=5.),follow_redirects=False,trust_env=False) as client:
            with client.stream("GET",url,params=params or {},headers={"User-Agent":"QuantLab-local-research/1.0","Accept":"application/json, application/rss+xml, text/xml, application/xml"}) as response:
                if response.status_code!=200:
                    raise ValueError("Provider HTTP "+str(response.status_code))
                chunks=[];size=0
                for chunk in response.iter_bytes():
                    size+=len(chunk)
                    if size>MAX_BODY:
                        raise ValueError("Provider payload exceeded size limit")
                    chunks.append(chunk)
                return b"".join(chunks)
    except httpx.HTTPError:
        raise ValueError("Provider network unavailable") from None


def _level(v):
    v=float(v)
    if not math.isfinite(v):
        raise ValueError("Invalid provider value")
    return v


def _fred_rows(raw,received):
    payload=json.loads(raw)
    rows=payload.get("observations")
    if not isinstance(rows,list) or not rows or len(rows)>32:
        raise ValueError("No bounded FRED observations")
    out={}
    for r in rows:
        if r["value"]==".":
            continue
        # Date marker, not a claimed exact event or release timestamp.
        day=date.fromisoformat(r["date"])
        event=datetime.combine(day,clock.min,timezone.utc)
        if event<=received:
            out[event]=_level(r["value"])
    if not out:
        raise ValueError("No finite FRED observations")
    return sorted(out.items())


def _twelve_rows(raw,mapping,received):
    payload=json.loads(raw)
    meta=payload.get("meta")
    kind=m.FACTORS[mapping["factor"]][0]
    interval="5min" if kind=="intraday_return" else "1day"
    if payload.get("status")!="ok" or not isinstance(meta,dict) or str(meta.get("symbol","")).upper()!=mapping["symbol"].upper() or str(meta.get("exchange","")).casefold()!=mapping["exchange"].casefold() or meta.get("interval")!=interval:
        raise ValueError("Provider entitlement or exact instrument metadata not verified")
    values=payload.get("values")
    if not isinstance(values,list) or not values or len(values)>32:
        raise ValueError("No bounded time-series observations")
    out={}
    zone=ZoneInfo(meta["exchange_timezone"]) if interval=="1day" else timezone.utc
    for row in values:
        if interval=="5min":
            start=datetime.strptime(row["datetime"],"%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            event=start+timedelta(minutes=5)
        else:
            d=date.fromisoformat(row["datetime"])
            # Deliberately use end of exchange-local day, not a guessed close.
            event=datetime.combine(d+timedelta(days=1),clock.min,zone).astimezone(timezone.utc)
        if event>received:
            continue
        value=_level(row["close"])
        if value<=0:
            raise ValueError("Nonpositive provider price")
        if event in out and out[event]!=value:
            raise ValueError("Conflicting time-series rows")
        out[event]=value
    if not out:
        raise ValueError("No completed provider bars")
    return sorted(out.items())


def _save_factor(factor,source,rows,raw,received):
    # Do not turn repeated downloads of unchanged bars into fresh signals.
    # Compare the last stored value for each event; revised values get a new
    # actual receipt, never a retroactive replacement.
    changed=[]
    if shared_market_data.database_path().is_file():
        with closing(ao._read_database()) as db:
            if m._exists(db,"market_context_observations"):
                for event,value in rows:
                    old=db.execute("""SELECT o.value,i.source FROM market_context_observations o
                      JOIN market_context_imports i USING(receipt_sha256)
                      WHERE o.factor=? AND o.event_utc=? AND i.mode='receipt'
                      ORDER BY i.imported_utc DESC,o.available_utc DESC LIMIT 1""",(factor,m._iso(event))).fetchone()
                    if old and old[1]!=source:
                        raise ValueError("Factor already assigned to a different source")
                    if not old or old[0]!=value:
                        changed.append((event,value))
            else:
                changed=rows
    else:
        changed=rows
    if not changed:
        return 0
    if not recorder_storage.allow("market_context",dropped=len(changed)):
        raise ValueError("Shared storage is paused or below free-space reserve")
    buf=io.StringIO();writer=csv.writer(buf,lineterminator="\n")
    writer.writerow(m.HEADER)
    for event,value in changed:
        writer.writerow((factor,m._iso(event),m._iso(received),value))
    result=m.ingest(buf.getvalue(),source,"receipt",True,now=received,original_report=raw.decode("utf-8"))
    if result["inserted"]:
        recorder_storage.saved("market_context",m._iso(received),len(changed))
    return len(changed) if result["inserted"] else 0


def _record(key,state,detail,**extra):
    with _LOCK:
        _RESULTS[key]={"state":state,"detail":detail,"attempt_utc":m._iso(m._now()),**extra}


def _task(key,cadence,action,force):
    now=time.monotonic()
    with _LOCK:
        last=_LAST_ATTEMPT.get(key)
        if last is not None and now-last<(min(cadence,60) if force else cadence):
            return
        _LAST_ATTEMPT[key]=now
    try:
        count=action()
        _record(key,"received" if count else "unchanged","Source response accepted",new_rows=count)
    except (ValueError,OSError,KeyError,TypeError,OverflowError,sqlite3.Error):
        # Do not return raw exception text from JSON, providers or key URLs.
        _record(key,"unavailable","Source unavailable, invalid, not entitled, conflicting identity or storage paused; inspect configuration")
    except Exception:
        _record(key,"unavailable","Provider response could not be safely processed")


def sync_once(config,*,force=False,now=None,stop=None):
    global _LAST_SYNC
    config=_validate(config)
    if stop is None:
        stop=Event()
    if not _SYNC_LOCK.acquire(blocking=False):
        return
    try:
        now=now or m._now()
        fred=os.getenv("FRED_API_KEY","").strip()
        twelve=os.getenv("TWELVE_DATA_API_KEY","").strip()
        if config["fred"]:
            for factor,series in FRED_SERIES.items():
                if stop.is_set():return
                if not fred:
                    _record("fred:"+factor,"not_configured","Set FRED_API_KEY locally")
                    continue
                def fetch(factor=factor,series=series):
                    raw=_http(FRED_URL+"series/observations",{"api_key":fred,"file_type":"json","series_id":series,"sort_order":"desc","limit":12})
                    received=m._now()
                    return _save_factor(factor,"FRED:"+series,_fred_rows(raw,received),raw,received)
                _task("fred:"+factor,3600,fetch,force)
        # Intraday collection limited to India's pre-open/session; daily
        # instruments remain hourly. Never label delayed bars realtime.
        local=now.astimezone(IST)
        market_window=local.weekday()<5 and clock(8,30)<=local.time().replace(tzinfo=None)<=clock(15,40)
        for row in config["mappings"]:
            if stop.is_set():return
            factor=row["factor"];intraday=m.FACTORS[factor][0]=="intraday_return"
            key="twelve:"+factor
            if not twelve:
                _record(key,"not_configured","Set TWELVE_DATA_API_KEY locally")
                continue
            if intraday and not (market_window or force):
                continue
            def fetch(row=row,intraday=intraday,factor=factor):
                raw=_http(TWELVE_URL,{"apikey":twelve,"symbol":row["symbol"],"exchange":row["exchange"],
                    "interval":"5min" if intraday else "1day","timezone":"UTC","outputsize":12,
                    "format":"JSON","adjust":"none"})
                received=m._now()
                source="Twelve Data:"+row["symbol"]+":"+row["exchange"]+(":5min" if intraday else ":1day")
                return _save_factor(factor,source,_twelve_rows(raw,row,received),raw,received)
            _task(key,300 if intraday else 3600,fetch,force)
            if stop.wait(1.2):return
        if config["news"]:
            for name,url in events.SOURCES.items():
                if stop.is_set():return
                def fetch(name=name,url=url):
                    raw=_http(url);received=m._now()
                    if not recorder_storage.allow("market_context_events",dropped=1):
                        raise ValueError("Shared storage paused")
                    n=events.save(name,raw,received)
                    recorder_storage.saved("market_context_events",m._iso(received))
                    return n
                _task("news:"+name,1800,fetch,force)
        if config["fred"]:
            if not fred:
                _record("calendar","not_configured","Set FRED_API_KEY locally")
            elif not stop.is_set():
                def fetch():
                    raw=_http(FRED_URL+"releases/dates",{"api_key":fred,"file_type":"json","include_release_dates_with_no_data":"true",
                        "sort_order":"asc","limit":1000,"realtime_start":now.date().isoformat(),
                        "realtime_end":(now.date()+timedelta(days=14)).isoformat()})
                    if not recorder_storage.allow("market_context_events",dropped=1):
                        raise ValueError("Shared storage paused")
                    received=m._now()
                    n=events.save(events.CALENDAR,raw,received)
                    recorder_storage.saved("market_context_events",m._iso(received))
                    return n
                _task("calendar",21600,fetch,force)
    finally:
        with _LOCK:
            _LAST_SYNC=m._iso(m._now())
        _SYNC_LOCK.release()


def _loop():
    global _REQUESTED
    while not _STOP.is_set():
        _WAKE.clear()
        with _LOCK:
            requested=_REQUESTED;_REQUESTED=False
        try:
            config=_config()
            if config["enabled"] or requested:
                sync_once(config,force=requested,stop=_STOP)
        except (ValueError,OSError,TypeError,KeyError):
            _record("configuration","unavailable","Invalid local feed configuration")
        if not _STOP.is_set():
            _WAKE.wait(30)


def start():
    global _THREAD
    with _LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return
        _STOP.clear()
        _THREAD=Thread(target=_loop,name="quantlab-context-feeds",daemon=True)
        _THREAD.start()


def request_sync(confirm):
    global _REQUESTED,_LAST_REQUEST
    if confirm is not True:
        raise ValueError("Confirm authorized read-only source requests")
    _config()
    with _LOCK:
        now=time.monotonic()
        if _SYNC_LOCK.locked() or _REQUESTED:
            raise ValueError("Context synchronization already running or queued")
        if _LAST_REQUEST and now-_LAST_REQUEST<_MIN_REQUEST_INTERVAL:
            raise ValueError("Wait at least one minute between manual sync requests")
        _LAST_REQUEST=now;_REQUESTED=True
    start();_WAKE.set()
    return {"queued":True,"read_only":True}


def shutdown():
    _STOP.set();_WAKE.set()
    # In-flight bounded HTTP request can finish; never stop the Dhan recorder
    # to wait on optional sources.
    thread=_THREAD
    if thread:
        thread.join(timeout=1.)
