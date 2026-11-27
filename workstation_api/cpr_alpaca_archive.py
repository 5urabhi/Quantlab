"""Opt-in, read-only daily Alpaca ETF proxy archive.

US-listed proxies are not foreign exchange index/futures feeds. These are
retrospectively retrieved raw bars with conservative assumed availability,
not point-in-time provider vintages or prospective receipt evidence.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from urllib.request import Request, build_opener, ProxyHandler
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
import csv
import io
import json
import math
import os
import sqlite3

from . import market_context as m, context_feeds as feeds
from . import alpha_retraining, recorder_storage

URL="https://data.alpaca.markets/v2/stocks/bars"
NY=ZoneInfo("America/New_York")
MAX_BODY=2_000_000


def credentials():
    for key_name,secret_name in (("APCA_API_KEY_ID","APCA_API_SECRET_KEY"),
                                 ("ALPACA_API_KEY","ALPACA_SECRET_KEY"),
                                 ("ALPACA_API_KEY_ID","ALPACA_API_SECRET_KEY")):
        key,secret=os.getenv(key_name,"").strip(),os.getenv(secret_name,"").strip()
        if key and secret:
            return key,secret
    return None


def _http(params,key,secret):
    try:
        opener=build_opener(ProxyHandler({}),feeds._NoRedirect())
        request=Request(URL+"?"+urlencode(params),headers={"APCA-API-KEY-ID":key,
            "APCA-API-SECRET-KEY":secret,"Accept":"application/json"})
        with opener.open(request,timeout=15) as response:
            if response.status!=200:
                raise ValueError("Alpaca HTTP "+str(response.status))
            raw=response.read(MAX_BODY+1)
        if len(raw)>MAX_BODY or any(x.encode() in raw for x in (key,secret)):
            raise ValueError("Unsafe or oversized Alpaca response discarded")
        return raw
    except HTTPError as exc:
        raise ValueError("Alpaca HTTP "+str(exc.code)) from None
    except (URLError,OSError,TimeoutError):
        raise ValueError("Alpaca network unavailable") from None


def normalize(factor,rows,start,stop,received):
    values={}
    for row in rows:
        stamp=m._stamp(row["t"]).astimezone(NY)
        day=stamp.date()
        if stamp.hour or stamp.minute or stamp.second or stamp.microsecond:
            raise ValueError("Expected New York midnight daily bar")
        if not start<=day<stop:
            continue
        # Allow the whole NY calendar day to finish plus 15 minutes.
        # The raw historical bar could include later corrections; this
        # is a conservative archive assumption, not receipt proof.
        known=(datetime.combine(day+timedelta(days=1),datetime.min.time(),NY)
               +timedelta(minutes=15)).astimezone(timezone.utc)
        if known>received:
            continue
        o,h,l,c,v=(float(row[k]) for k in ("o","h","l","c","v"))
        if not all(math.isfinite(x) for x in (o,h,l,c,v)) or min(o,h,l,c,v)<=0 or not l<=min(o,c)<=max(o,c)<=h:
            raise ValueError("Invalid observed Alpaca OHLCV")
        event=m._iso(stamp.astimezone(timezone.utc))
        if event in values and values[event]!=(m._iso(known),c):
            raise ValueError("Conflicting daily Alpaca bar")
        values[event]=(m._iso(known),c)
    buf=io.StringIO();writer=csv.writer(buf,lineterminator="\n");writer.writerow(m.HEADER)
    for event,(known,close) in sorted(values.items()):
        writer.writerow((factor,event,known,close))
    return buf.getvalue(),len(values)


def backfill(start,stop,*,feed="iex",confirmed=False,live_guard=None):
    if confirmed is not True:
        raise ValueError("Review Alpaca source permissions and archive assumptions")
    if feed not in ("iex","sip"):
        raise ValueError("Unsupported Alpaca equity feed")
    now=m._now()
    if live_guard is not None:live_guard()
    if (live_guard is None and not alpha_retraining.safe_window(now)) or not 0<(stop-start).days<=120 or stop>now.astimezone(feeds.IST).date():
        raise ValueError("Use a completed bounded range outside Indian market priority hours")
    auth=credentials()
    if not auth:
        return {"state":"alpaca_credentials_not_configured","factors":{}}
    left=start-timedelta(days=10)
    symbols=[v[0] for v in m.ALPACA_PROXIES.values()]
    params={"symbols":",".join(symbols),"timeframe":"1Day",
            "start":datetime.combine(left,datetime.min.time(),NY).isoformat(),
            "end":datetime.combine(stop,datetime.min.time(),NY).isoformat(),
            "feed":feed,"adjustment":"raw","asof":"-","limit":5000,"sort":"asc"}
    try:
        raw=_http(params,*auth)
        payload=json.loads(raw)
        bars=payload["bars"]
        if not isinstance(bars,dict) or payload.get("next_page_token"):
            raise ValueError("Incomplete bounded Alpaca response")
        if set(bars)-set(symbols):
            raise ValueError("Unexpected Alpaca symbol")
    except (ValueError,KeyError,TypeError,OSError) as exc:
        reason=str(exc) if isinstance(exc,ValueError) and str(exc).startswith(("Alpaca HTTP","Alpaca network","Incomplete bounded","Unexpected Alpaca")) else type(exc).__name__
        return {"state":"alpaca_archive_unavailable","reason":reason,"factors":{}}
    received=m._now();out={}
    for factor,(symbol,_,_) in m.ALPACA_PROXIES.items():
        if live_guard is not None:live_guard()
        try:
            text,n=normalize(factor,bars.get(symbol,[]),left,stop,received)
            if not n:
                out[factor]={"state":"no_completed_bars"}
                continue
            if not recorder_storage.allow("market_context",dropped=n):
                out[factor]={"state":"storage_paused"}
                continue
            saved=m.ingest(text,"Alpaca:"+feed+":"+symbol+":1Day:raw","archive",True,
                           now=received,original_report=raw.decode("utf-8"))
            if saved["inserted"]:
                recorder_storage.saved("market_context",m._iso(received),n)
            out[factor]={"state":"saved" if saved["inserted"] else "already_present",
                         "rows":n,"receipt_sha256":saved["receipt_sha256"]}
        except (ValueError,OSError,KeyError,TypeError,OverflowError,sqlite3.Error) as exc:
            out[factor]={"state":"unavailable","reason":type(exc).__name__}
    return {"state":"alpaca_archive_attempt_finished","feed":feed,"factors":out,
            "warning":"Raw US-listed ETF daily proxies, not index levels, live Asian prices, vintage-certified history or actual historical receipts."}


def recent_rows(factor,rows,received,*,intraday):
    """Completed bars only; true availability is the actual receipt."""
    seen={}
    for row in rows:
        stamp=m._stamp(row["t"])
        if intraday:
            if stamp.minute%5 or stamp.second or stamp.microsecond:
                raise ValueError("Unexpected five-minute Alpaca clock")
            event=stamp+timedelta(minutes=5)
            if event>received:
                continue
            o,h,l,c,v=(float(row[k]) for k in ("o","h","l","c","v"))
            if not all(math.isfinite(x) for x in (o,h,l,c,v)) or min(o,h,l,c,v)<=0 or not l<=min(o,c)<=max(o,c)<=h:
                raise ValueError("Invalid completed Alpaca OHLCV")
        else:
            # Reuse exact daily archive semantics and identical event
            # identity, without reusing its assumed historical availability.
            local=stamp.astimezone(NY)
            csv_text,n=normalize(factor,[row],local.date(),local.date()+timedelta(days=1),received)
            if not n:
                continue
            event=stamp
            c=float(row["c"])
        if event in seen and seen[event]!=c:
            raise ValueError("Conflicting Alpaca observations")
        seen[event]=c
    return sorted(seen.items())


def collect_recent(feed,*,intraday=False,stop=None):
    if feed not in ("iex","sip"):
        raise ValueError("Unsupported Alpaca equity feed")
    auth=credentials()
    if auth is None:
        raise ValueError("Alpaca credentials not configured")
    now=m._now()
    catalog=m.ALPACA_INTRADAY_PROXIES if intraday else m.ALPACA_PROXIES
    timeframe="5Min" if intraday else "1Day"
    left=now-timedelta(hours=2) if intraday else now-timedelta(days=12)
    params={"symbols":",".join(v[0] for v in catalog.values()),"timeframe":timeframe,
            "start":left.isoformat(),"end":now.isoformat(),"feed":feed,
            "adjustment":"raw","asof":"-","limit":1000,"sort":"asc"}
    raw=_http(params,*auth)
    payload=json.loads(raw);bars=payload["bars"]
    if not isinstance(bars,dict) or payload.get("next_page_token") or set(bars)-{v[0] for v in catalog.values()}:
        raise ValueError("Incomplete or unexpected Alpaca response")
    received=m._now();count=0
    for factor,(symbol,_,_) in catalog.items():
        if stop is not None and stop.is_set():
            break
        rows=recent_rows(factor,bars.get(symbol,[]),received,intraday=intraday)
        if rows:
            count+=feeds._save_factor(factor,"Alpaca:"+feed+":"+symbol+":"+timeframe+":raw",rows,raw,received)
    return count
