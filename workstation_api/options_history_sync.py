"""Explicit, bounded BANKNIFTY expired-option receipt acquisition.

Reuse the existing rolling-option cache; no separate market-price database,
broker orders, or synthetic depth. Receipt request windows do not certify
continuous observed contract/session coverage.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta
from threading import Lock
import json
import re
import time

from . import expired_options_backtest as exp, market_patterns, service, dhan_auth

MAX_DAYS=366
MAX_RECEIPTS=20000
MAX_REQUESTS=8200
MAX_CONSECUTIVE_REJECTIONS=66
MAX_REJECTIONS=132
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
    chunks=sum(len(list(exp._rolling_windows(a,b))) for a,b in eligible)
    days=sum((b-a).days for a,b in eligible)
    return {"start_date":start_date,"end_date":end_date,"wings":wings,
            "eligible_intervals":[{"from":a.isoformat(),"through":(b-timedelta(days=1)).isoformat()} for a,b in eligible],
            "eligible_calendar_days":days,"excluded_active_calendar_days":(stop-start).days-days,
            "full_scope_request_estimate":chunks*2*len(exp._offsets(wings)),
            "max_missing_requests":MAX_REQUESTS,"read_only":True,"orders_enabled":False,
            "warning":"Two consecutive inclusive calendar dates per request, based on authenticated Dhan success. Single-day remainders use the previous date. Near monthly only; active expiries excluded. A full year can require thousands of sequential calls; cancel/resume reuses saved receipts. No historical bid/ask or depth. Checked windows do not certify continuous prices."}


def _key(body):
    return {k:v for k,v in body.items() if k not in ("fromDate","toDate")}


def _record_observed(audit,rows,start,stop):
    if audit is None:
        return
    left,right=start.isoformat(),stop.isoformat()
    for row in rows:
        day=row["session_ist"]
        if not left<=day<right:
            continue
        stamp=datetime.fromisoformat(row["timestamp_utc"]).astimezone(exp.IST)
        minute=stamp.hour*60+stamp.minute-555
        if 0<=minute<375:
            key=(row["side"],row["origin_offset"],day)
            audit[key]=audit.get(key,0)|(1<<minute)


def _saved_windows(start,stop,wings,*,observed=None,statistics=None):
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
            a,last=date.fromisoformat(body["fromDate"]),date.fromisoformat(body["toDate"])
            b=last+timedelta(days=1)
            if b<=start or a>=stop:
                continue
            if not a<last or (last-a).days>30 or p!=exp._cache_path(body) or envelope.get("source")!=SOURCE:
                raise ValueError("Receipt identity mismatch")
            payload=exp._get_cached(body)
            if payload is None:
                raise ValueError("Receipt disappeared")
            # A valid empty response is still request evidence, not proof
            # of observed price coverage. Never silently replace it.
            rows=exp._normalize(payload,body)
            _record_observed(observed,rows,start,stop)
            if statistics is not None:
                statistics["empty_verified_receipts"]+=int(not rows)
            coverage[key].append((a,b))
            reused+=1
        except (ValueError,TypeError,KeyError,OSError,AttributeError,UnicodeError):
            rejected+=1
    return coverage,reused,rejected


def run(*,start_date,end_date,wings=3,progress=None,fetcher=None,today=None,request_limit=None,should_stop=None):
    today=today or exp._ist_today()
    start,stop,eligible=_scope(start_date,end_date,wings,today)
    if not LOCK.acquire(blocking=False):
        raise ValueError("An expired-option history acquisition is already running")
    try:
        if progress:
            progress(1,"Verifying existing expired-option receipt windows")
        observed={};statistics={"empty_verified_receipts":0}
        coverage,reused,rejected=_saved_windows(start,stop,wings,observed=observed,statistics=statistics)
        requests=[]
        for side in ("CALL","PUT"):
            for offset in exp._offsets(wings):
                for a,b in eligible:
                    for x,y in market_patterns.missing_windows(a,b,coverage[(side,offset)]):
                        for lo,hi in exp._rolling_windows(x,y):
                            requests.append(exp._request_body(lo,hi,"MONTH",0,offset,side))
        # Stable date-major order, latest first, ATM before wider strikes.
        # Deduplicate paired boundary requests generated by disjoint gaps.
        requests=list({exp._cache_path(body).name:body for body in requests}.values())
        rank={offset:i for i,offset in enumerate(exp._offsets(wings))}
        requests.sort(key=lambda b:(-date.fromisoformat(b["fromDate"]).toordinal(),rank[b["strike"]],b["drvOptionType"]))
        if len(requests)>MAX_REQUESTS:
            raise ValueError("Missing request scope exceeds bounded limit; shorten the date range")
        if requests and fetcher is None:
            profile=dhan_auth.check_profile()
            if not profile.get("ok"):
                raise ValueError("Verify Dhan historical-data access in Connections before downloading")
        if request_limit is not None and (type(request_limit) is not int or not 1<=request_limit<=MAX_REQUESTS):
            raise ValueError("Invalid bounded automatic request limit")
        downloaded=0
        exact_reused=0
        empty=0
        usable=0
        rejected_requests=[]
        consecutive=0
        attempted=0
        completed=0
        stopped_early=False
        for body in requests:
            if (request_limit is not None and attempted>=request_limit) or (should_stop is not None and should_stop()):
                stopped_early=True
                break
            if progress:
                progress(min(95,5+90*attempted/max(1,len(requests))),
                         f"Option history {attempted}/{len(requests)}; {body['fromDate']}..{body['toDate']} {body['drvOptionType']} {body['strike']}")
            attempted+=1
            payload=exp._get_cached(body)
            if payload is not None:
                exact_reused+=1
                rows=exp._normalize(payload,body)
            else:
                try:
                    if fetcher is None:
                        # The exact REST encoding succeeded with urllib and
                        # all nine fields. Do not repeat four encodings.
                        time.sleep(.45)
                        payload=exp._original_response_once(body)
                    else:
                        payload=fetcher(body)
                except exp.RollingInputError:
                    consecutive+=1
                    rejected_requests.append({"from":body["fromDate"],"through":body["toDate"],
                                              "side":body["drvOptionType"],"strike":body["strike"],
                                              "code":"DH-905"})
                    # Do not mark rejected windows checked. Avoid flooding
                    # the endpoint on persistent systematic rejection.
                    if consecutive>=MAX_CONSECUTIVE_REJECTIONS or len(rejected_requests)>=MAX_REJECTIONS:
                        stopped_early=True
                        break
                    continue
                if not isinstance(payload,dict) or not isinstance(payload.get("data"),dict):
                    raise ValueError("Invalid Dhan expired-option history payload")
                rows=exp._normalize(payload,body)
                exp._save_cache(body,payload)
                downloaded+=1
            _record_observed(observed,rows,start,stop)
            consecutive=0
            completed+=1
            empty+=not bool(rows)
            usable+=sum(start_date<=r["session_ist"]<=end_date for r in rows)
        if progress:
            progress(100,"Saved original receipts; some request windows remain" if rejected_requests or attempted<len(requests) else "Saved original receipts; inspect observed coverage")
        return {**preview(start_date,end_date,wings,today),
                "existing_verified_receipts":reused,"unreadable_receipts_encountered":rejected,
                "empty_verified_receipts":statistics["empty_verified_receipts"],
                "observed_rolling_minute_slots":sum(v.bit_count() for v in observed.values()),
                "observed_offset_session_pairs":len(observed),
                "observed_session_dates":len({k[2] for k in observed}),
                "planned_missing_requests":len(requests),"new_receipts":downloaded,
                "processed_windows":completed,"rejected_requests":rejected_requests,
                "unattempted_requests":len(requests)-attempted,"stopped_early":stopped_early,
                "exact_cache_reuses":exact_reused,"empty_processed_receipts":empty,
                "usable_rows_in_processed_receipts":usable,
                "state":"partial_requests" if rejected_requests or attempted<len(requests) else "request_windows_checked","continuous_coverage_certified":False,
                "note":"Counts describe processed receipts, not deduplicated contracts. Both inclusive dates are retained during the regular session. Verified windows are reused; rejected or unattempted windows remain eligible on resume. No original historical depth has been downloaded."}
    finally:
        LOCK.release()
