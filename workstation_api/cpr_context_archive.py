"""Bounded, opt-in FRED/ALFRED historical context archive.

The FRED API returns real-time periods (calendar dates), not precise market
release timestamps. Delay each vintage until noon UTC on the following day
rather than pretending to know the same-day publication time. Preserve the
original payload and label this as ARCHIVE research, never receipt evidence.
"""
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
import csv
import io
import json
import os
import sqlite3

from . import context_feeds as feeds, market_context as m
from . import recorder_storage, shared_market_data, alpha_retraining
from . import advanced_options as ao

MAX_ROWS=5000
MAX_DAYS=120
VINTAGE_FLOOR="1776-07-04"


def normalize(factor,raw,start,stop,received):
    payload=json.loads(raw)
    rows=payload.get("observations")
    if (not isinstance(rows,list) or len(rows)>MAX_ROWS or
        payload.get("count")!=len(rows) or payload.get("offset")!=0):
        raise ValueError("Incomplete bounded real-time-period response")
    observations={}
    rejected=0
    for row in rows:
        if row.get("value")==".":
            continue
        event=date.fromisoformat(row["date"])
        vintage=date.fromisoformat(row["realtime_start"])
        if not start<=event<stop or vintage<event:
            rejected+=1
            continue
        # A provider vintage marks a day, not an exact time. Noon UTC on the
        # following day is later than the end of that day in US time zones.
        known=datetime.combine(vintage+timedelta(days=1),datetime.min.time(),timezone.utc)+timedelta(hours=12)
        if known>received:
            rejected+=1
            continue
        observed=datetime.combine(event,datetime.min.time(),timezone.utc)
        value=feeds._level(row["value"])
        if m.FACTORS[factor][0]=="daily_return" and value<=0:
            rejected+=1
            continue
        key=(m._iso(observed),m._iso(known))
        if key in observations and observations[key]!=value:
            raise ValueError("Conflicting values at identical vintage date")
        observations[key]=value
    buf=io.StringIO()
    writer=csv.writer(buf,lineterminator="\n")
    writer.writerow(m.HEADER)
    for (event,known),value in sorted(observations.items()):
        writer.writerow((factor,event,known,value))
    return buf.getvalue(),len(observations),rejected


def _fetch_vintages(key,series,left,stop):
    params={"api_key":key,"file_type":"json","series_id":series,
            "output_type":1,"realtime_start":VINTAGE_FLOOR,
            "realtime_end":m._now().date().isoformat(),
            "observation_start":left.isoformat(),
            "observation_end":(stop-timedelta(days=1)).isoformat(),
            "limit":MAX_ROWS,"offset":0}
    attempts=[]
    # A bounded real-time interval can avoid asking for pre-history vintages.
    # Initial-release-only is a distinct, documented output format.
    # Never substitute today's latest revised values into an archive.
    for method,overrides in (("all_vintages",{}),
                             ("bounded_vintages",{"realtime_start":left.isoformat()}),
                             ("initial_release_only",{"output_type":4,"realtime_start":left.isoformat()})):
        if not alpha_retraining.safe_window(m._now()):
            raise ValueError("Historical requests paused for market priority")
        try:
            raw=feeds._http(feeds.FRED_URL+"series/observations",{**params,**overrides})
            attempts.append({"method":method,"state":"response_received"})
            return raw,method,attempts
        except ValueError as exc:
            message=str(exc)
            if not message.startswith("Provider HTTP 400"):
                raise
            attempts.append({"method":method,"state":"unavailable","reason":message})
            if any(x in message for x in ("key_rejected","source_restriction","series_unavailable")):
                break
    return None,None,attempts


def backfill(start,stop,*,confirmed=False):
    now=m._now()
    if confirmed is not True:
        raise ValueError("Explicit authorization and review of FRED/ALFRED source terms required")
    if not alpha_retraining.safe_window(now):
        raise ValueError("Run historical downloads outside Indian market priority hours")
    if not 0<(stop-start).days<=MAX_DAYS or stop>now.astimezone(feeds.IST).date():
        raise ValueError("Use a completed range up to 120 calendar days, end exclusive")
    key=os.getenv("FRED_API_KEY","").strip()
    if not key:
        return {"state":"fred_key_not_configured","factors":{}}
    result={}
    left=start-timedelta(days=10)
    for factor,series in feeds.FRED_SERIES.items():
        if not alpha_retraining.safe_window(m._now()):
            result[factor]={"state":"paused_market_priority"}
            continue
        try:
            raw,method,attempts=_fetch_vintages(key,series,left,stop)
            if raw is None:
                result[factor]={"state":"unavailable","reason":"No supported historical vintage response",
                                "attempts":attempts}
                continue
            received=m._now()
            csv_text,n,rejected=normalize(factor,raw,left,stop,received)
            if not n:
                result[factor]={"state":"no_eligible_vintage_rows","rejected":rejected}
                continue
            if not recorder_storage.allow("market_context",dropped=n):
                result[factor]={"state":"storage_paused"}
                continue
            saved=m.ingest(csv_text,"FRED:"+series,"archive",True,now=received,
                           original_report=raw.decode("utf-8"))
            if saved["inserted"]:
                recorder_storage.saved("market_context",m._iso(received),n)
            result[factor]={"state":"saved" if saved["inserted"] else "already_present",
                            "rows":n,"rejected":rejected,"receipt_sha256":saved["receipt_sha256"],
                            "method":method,"attempts":attempts}
        except (ValueError,OSError,KeyError,TypeError,OverflowError,sqlite3.Error) as exc:
            # Never emit raw provider exceptions or credential-bearing URLs.
            detail=str(exc) if isinstance(exc,ValueError) and str(exc).startswith(
                ("Provider HTTP ","Provider network unavailable","Source differs from existing series",
                 "Incomplete bounded real-time","Conflicting values")) else type(exc).__name__
            result[factor]={"state":"unavailable","reason":detail}
    return {"state":"archive_attempt_finished","factors":result,
            "warning":"Provider vintage date + one day at noon UTC is a conservative assumed availability; "
                      "not verified intraday release time. No GIFT NIFTY or live futures history is fabricated."}


def inventory():
    if not shared_market_data.database_path().is_file():
        return {"state":"no_context_database","factors":[]}
    with closing(ao._read_database()) as db:
        if not m._exists(db,"market_context_observations"):
            return {"state":"no_context_tables","factors":[]}
        rows=db.execute("""SELECT o.factor,i.mode,COUNT(*),MIN(o.event_utc),MAX(o.event_utc),
             MIN(o.available_utc),MAX(o.available_utc)
             FROM market_context_observations o JOIN market_context_imports i USING(receipt_sha256)
             GROUP BY o.factor,i.mode ORDER BY o.factor,i.mode LIMIT 200""").fetchall()
    return {"state":"available" if rows else "no_context_observations",
            "factors":[dict(zip(("factor","mode","rows","first_event","last_event",
                                 "first_available","last_available"),r)) for r in rows]}
