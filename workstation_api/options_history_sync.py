"""Explicit, bounded BANKNIFTY expired-option receipt acquisition.

Reuse the existing rolling-option cache; no separate market-price database,
broker orders, or synthetic depth. Receipt request windows do not certify
continuous observed contract/session coverage.
"""
from collections import defaultdict
from datetime import date, timedelta
from threading import Lock
import json
import re
import time

from . import expired_options_backtest as exp, market_patterns, service, dhan_auth

MAX_DAYS=366
MAX_RECEIPTS=4096
MAX_REQUESTS=300
LOCK=Lock()
SOURCE="Dhan v2 /charts/rollingoption"


def _intervals(start,stop,today):
    """Contiguous calendar spans with a conservatively expired near series."""
    runs=[]
    cursor=start
    while cursor<stop:
        if not exp._expired_eligible(cursor,expiry_flag="MONTH",expiry_code=0,today=today):
            cursor+=timedelta(days=1)
            continue
        first=cursor
        while cursor<stop and exp._expired_eligible(cursor,expiry_flag="MONTH",expiry_code=0,today=today):
            cursor+=timedelta(days=1)
        runs.append((first,cursor))
    return runs


def _scope(start_date,end_date,wings,today):
    start=date.fromisoformat(start_date)
    end=date.fromisoformat(end_date)
    if start.isoformat()!=start_date or end.isoformat()!=end_date:
        raise ValueError("Enter exact ISO dates")
    if not start<=end<today or (end-start).days>=MAX_DAYS:
        raise ValueError("Choose at most 366 calendar days ending before today's IST date")
    if type(wings) is not int or not 0<=wings<=5:
        raise ValueError("Choose zero to five near-expiry rolling strike wings")
    stop=end+timedelta(days=1)
    return start,stop,_intervals(start,stop,today)


def preview(start_date,end_date,wings=3,today=None):
    today=today or exp._ist_today()
    start,stop,eligible=_scope(start_date,end_date,wings,today)
    chunks=sum(len(list(exp._chunks(a,b))) for a,b in eligible)
    days=sum((b-a).days for a,b in eligible)
    return {"start_date":start_date,"end_date":end_date,"wings":wings,
            "eligible_intervals":[{"from":a.isoformat(),"through":(b-timedelta(days=1)).isoformat()} for a,b in eligible],
            "eligible_calendar_days":days,"excluded_active_calendar_days":(stop-start).days-days,
            "full_scope_request_estimate":chunks*2*len(exp._offsets(wings)),
            "max_missing_requests":MAX_REQUESTS,"read_only":True,"orders_enabled":False,
            "warning":"Near monthly rolling strikes only; original 1-minute OHLC/IV/OI/volume requested. Active contracts excluded. No historical bid/ask or depth. Actual missing requests depend on verified saved receipt intervals; a requested interval is not proof of usable prices."}


def _key(body):
    return {k:v for k,v in body.items() if k not in ("fromDate","toDate")}


def _saved_windows(start,stop,wings):
    root=service.DATA/"dhan_expired_options"
    coverage=defaultdict(list)
    reused=0
    rejected=0
    if not root.exists():
        return coverage,reused,rejected
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Unsafe expired-option cache location")
    keys={(side,offset):_key(exp._request_body(start,min(stop,start+timedelta(days=1)),
            "MONTH",0,offset,side)) for side in ("CALL","PUT") for offset in exp._offsets(wings)}
    paths=[]
    for p in root.iterdir():
        if re.fullmatch(r"[0-9a-f]{64}\.json",p.name):
            paths.append(p)
            if len(paths)>MAX_RECEIPTS:
                raise ValueError("Expired-option receipt scan limit exceeded; use source inspection")
    for p in paths:
        try:
            if p.is_symlink() or not p.is_file() or p.stat().st_size>exp.MAX_RESPONSE_BYTES+5000:
                raise ValueError("Unsafe or oversized receipt")
            envelope=json.loads(p.read_text(encoding="utf-8"))
            body=envelope["request"]
            key=(body.get("drvOptionType"),body.get("strike"))
            if key not in keys or _key(body)!=keys[key]:
                continue
            a,b=date.fromisoformat(body["fromDate"]),date.fromisoformat(body["toDate"])
            if b<=start or a>=stop:
                continue
            if not a<b or (b-a).days>30 or p!=exp._cache_path(body) or envelope.get("source")!=SOURCE:
                raise ValueError("Receipt identity mismatch")
            payload=exp._get_cached(body)
            if payload is None:
                raise ValueError("Receipt disappeared")
            # A valid empty response is still request evidence, not proof
            # of observed price coverage. Never silently replace it.
            exp._normalize(payload,body)
            coverage[key].append((a,b))
            reused+=1
        except (ValueError,TypeError,KeyError,OSError,AttributeError,UnicodeError):
            rejected+=1
    return coverage,reused,rejected


def run(*,start_date,end_date,wings=3,progress=None,fetcher=None,today=None):
    today=today or exp._ist_today()
    start,stop,eligible=_scope(start_date,end_date,wings,today)
    if not LOCK.acquire(blocking=False):
        raise ValueError("An expired-option history acquisition is already running")
    try:
        if progress:
            progress(1,"Verifying existing expired-option receipt windows")
        coverage,reused,rejected=_saved_windows(start,stop,wings)
        requests=[]
        for side in ("CALL","PUT"):
            for offset in exp._offsets(wings):
                for a,b in eligible:
                    for x,y in market_patterns.missing_windows(a,b,coverage[(side,offset)]):
                        for lo,hi in exp._chunks(x,y):
                            requests.append(exp._request_body(lo,hi,"MONTH",0,offset,side))
        if len(requests)>MAX_REQUESTS:
            raise ValueError("More than 300 missing request windows; choose a shorter date range")
        if requests and fetcher is None:
            profile=dhan_auth.check_profile()
            if not profile.get("ok"):
                raise ValueError("Verify Dhan historical-data access in Connections before downloading")
        downloaded=0
        exact_reused=0
        empty=0
        usable=0
        for i,body in enumerate(requests):
            if progress:
                progress(5+90*i/max(1,len(requests)),f"Checking option history {i+1}/{len(requests)}")
            # Recheck exact cache after planning, preserve invalid receipts
            # and stop on corruption rather than overwriting original evidence.
            payload=exp._get_cached(body)
            if payload is not None:
                exact_reused+=1
                rows=exp._normalize(payload,body)
            else:
                if fetcher is None:
                    time.sleep(.45)
                    payload=exp._original_response(body)
                else:
                    payload=fetcher(body)
                if not isinstance(payload,dict) or not isinstance(payload.get("data"),dict):
                    raise ValueError("Invalid Dhan expired-option history payload")
                rows=exp._normalize(payload,body)
                exp._save_cache(body,payload)
                downloaded+=1
            empty+=not bool(rows)
            usable+=len(rows)
        if progress:
            progress(100,"Saved original rolling-option receipts; inspect observed coverage")
        return {**preview(start_date,end_date,wings,today),
                "existing_verified_receipts":reused,"unreadable_receipts_encountered":rejected,
                "planned_missing_requests":len(requests),"new_receipts":downloaded,
                "exact_cache_reuses":exact_reused,"empty_processed_receipts":empty,
                "usable_rows_in_processed_receipts":usable,
                "state":"request_windows_checked","continuous_coverage_certified":False,
                "note":"Counts describe processed receipts, not deduplicated contracts. Previously saved windows are reused. Partial failures retain completed receipts; retry skips verified windows. No original historical depth has been downloaded."}
    finally:
        LOCK.release()
