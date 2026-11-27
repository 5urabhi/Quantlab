"""Explicit, bounded BANKNIFTY expired-option receipt acquisition.

Reuse the existing rolling-option cache; no separate market-price database,
broker orders, or synthetic depth. Receipt request windows do not certify
continuous observed contract/session coverage.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta
from threading import Lock
from hashlib import sha256
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import fcntl
import os
import json
import re
import time

from . import expired_options_backtest as exp, market_patterns, service, dhan_auth

MAX_DAYS=366
MAX_RECEIPTS=20000
MAX_REQUESTS=8200
MAX_NEAR_WINGS=10
MAX_CONSECUTIVE_REJECTIONS=66
REQUEST_START_SPACING=.45
MAX_REJECTIONS=132
LOCK=Lock()
SOURCE="Dhan v2 /charts/rollingoption"
# Process-local planning summaries only; research continues to verify raw receipts.
_SCAN_ROOT=None
_SCAN_CACHE={}



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
    if type(wings) is not int or not 0<=wings<=MAX_NEAR_WINGS:
        raise ValueError("Choose zero to ten near-expiry rolling strike wings")
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


def _record_observed(audit,rows,start,stop,*,count_days=None):
    if audit is None:
        return 0
    added=0
    left,right=start.isoformat(),stop.isoformat()
    for row in rows:
        day=row["session_ist"]
        if not left<=day<right:
            continue
        stamp=datetime.fromisoformat(row["timestamp_utc"]).astimezone(exp.IST)
        minute=stamp.hour*60+stamp.minute-555
        if 0<=minute<375:
            key=(row["side"],row["origin_offset"],day)
            before=audit.get(key,0)
            audit[key]=before|(1<<minute)
            if count_days is not None and day in count_days and before!=audit[key]:
                added+=1
    return added


def _signature(path):
    s=path.stat()
    return s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns


def _verified_summary(path,signature):
    """Read/verify once, keep compact observed-minute masks, not prices."""
    if path.is_symlink() or not path.is_file() or signature[2]>exp.MAX_RESPONSE_BYTES+5000:
        raise ValueError("Unsafe or oversized receipt")
    envelope=json.loads(path.read_text(encoding="utf-8"))
    body=envelope["request"]
    # Other original receipt families share this directory.
    if envelope.get("source")!=SOURCE:
        return None
    a,last=date.fromisoformat(body["fromDate"]),date.fromisoformat(body["toDate"])
    b=last+timedelta(days=1)
    if not a<last or (last-a).days>30 or path!=exp._cache_path(body):
        raise ValueError("Receipt identity mismatch")
    payload=envelope["payload"]
    raw=json.dumps(payload,sort_keys=True,separators=(",",":")).encode()
    if sha256(raw).hexdigest()!=envelope["sha256"] or not isinstance(payload.get("data"),dict):
        raise ValueError("Receipt integrity mismatch")
    rows=exp._normalize(payload,body)
    masks={}
    _record_observed(masks,rows,a,b)
    if _signature(path)!=signature or path.is_symlink():
        raise ValueError("Receipt changed during verification")
    return body,a,b,masks,not bool(rows)


def _saved_windows(start,stop,wings,*,observed=None,statistics=None):
    global _SCAN_ROOT
    root=service.DATA/"dhan_expired_options"
    coverage=defaultdict(list)
    reused=0
    rejected=0
    if str(root)!=_SCAN_ROOT:
        _SCAN_CACHE.clear()
        _SCAN_ROOT=str(root)
    if not root.exists():
        _SCAN_CACHE.clear()
        return coverage,reused,rejected
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Unsafe expired-option cache location")
    keys={(side,offset):_key(exp._request_body(start,min(stop,start+timedelta(days=1)),
            "MONTH",0,offset,side)) for side in ("CALL","PUT") for offset in exp._offsets(wings)}
    paths=[]
    for p in root.iterdir():
        if re.fullmatch(r"[0-9a-f]{64}[.]json",p.name):
            paths.append(p)
            if len(paths)>MAX_RECEIPTS:
                raise ValueError("Expired-option receipt scan limit exceeded; use source inspection")
    present={p.name for p in paths}
    for name in list(_SCAN_CACHE):
        if name not in present:
            del _SCAN_CACHE[name]
    left,right=start.isoformat(),stop.isoformat()
    for p in paths:
        try:
            if p.is_symlink() or not p.is_file():
                raise ValueError("Unsafe receipt")
            signature=_signature(p)
            cached=_SCAN_CACHE.get(p.name)
            if cached is not None and cached[0]==signature:
                summary=cached[1]
            else:
                summary=_verified_summary(p,signature)
                _SCAN_CACHE[p.name]=(signature,summary)
            if summary is None:
                continue
            body,a,b,masks,empty=summary
            key=(body.get("drvOptionType"),body.get("strike"))
            if key not in keys or _key(body)!=keys[key] or b<=start or a>=stop:
                continue
            if observed is not None:
                for k,mask in masks.items():
                    if left<=k[2]<right:
                        observed[k]=observed.get(k,0)|mask
            if statistics is not None:
                statistics["empty_verified_receipts"]+=int(empty)
            coverage[key].append((a,b))
            reused+=1
        except (ValueError,TypeError,KeyError,OSError,AttributeError,UnicodeError):
            _SCAN_CACHE.pop(p.name,None)
            rejected+=1
    return coverage,reused,rejected


def _eligible_dates(eligible):
    return {a+timedelta(days=i) for a,b in eligible for i in range((b-a).days)}


def _add_checked(checked,key,a,b,eligible):
    checked.update((key,d) for i in range((b-a).days) if (d:=a+timedelta(days=i)) in eligible)



def _prioritize(requests,offset_rank,priority_sessions):
    """Known observed market sessions before speculative calendar requests.
    Do not omit other missing windows or infer holidays from absent bars.
    """
    priority=set(priority_sessions or ())
    def key(body):
        left=date.fromisoformat(body["fromDate"])
        right=date.fromisoformat(body["toDate"])
        observed=any((left+timedelta(days=i)).isoformat() in priority for i in range((right-left).days+1))
        return (not observed,offset_rank[body["strike"]]>10,-left.toordinal(),offset_rank[body["strike"]],body["drvOptionType"])
    return sorted(requests,key=key)


@contextmanager
def acquisition_lock():
    """One canonical history writer across the backend and local CLI."""
    if not LOCK.acquire(blocking=False):
        raise ValueError("An expired-option history acquisition is already running")
    fd=None
    try:
        root=service.DATA/"dhan_expired_options"
        root.mkdir(parents=True,exist_ok=True)
        if root.is_symlink():
            raise ValueError("Unsafe expired-option cache location")
        fd=os.open(root/".acquisition.lock",os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Another local expired-option acquisition is running") from None
        yield
    finally:
        if fd is not None:
            os.close(fd)
        LOCK.release()


@contextmanager
def _window_reader(fetcher, pipeline):
    """Bounded one-window lookahead; only the caller verifies/writes receipts.

    One network worker, one pending response, and a single shared start
    clock. The next request overlaps local normalization and atomic save,
    not an unbounded queue. A discarded in-flight response is never marked
    checked. A throttle response from that request still stops acquisition.
    """
    pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix="option-fetch") if pipeline else None
    pending=None
    last_start=None

    def fetch(body):
        nonlocal last_start
        payload=exp._get_cached(body)
        if payload is not None:
            return payload,True
        if fetcher is None:
            if pipeline:
                if last_start is not None:
                    delay=REQUEST_START_SPACING-(time.monotonic()-last_start)
                    if delay>0:
                        time.sleep(delay)
                last_start=time.monotonic()
            else:
                time.sleep(REQUEST_START_SPACING)
            payload=exp._original_response_once(body)
        else:
            payload=fetcher(body)
        if not isinstance(payload,dict) or not isinstance(payload.get("data"),dict):
            raise ValueError("Invalid Dhan expired-option history payload")
        return payload,False

    def read(body):
        nonlocal pending
        if pool is None:
            return fetch(body)
        if pending is None:
            pending=(body,pool.submit(fetch,body))
        expected,future=pending
        if expected!=body:
            raise RuntimeError("Option prefetch request identity mismatch")
        pending=None
        return future.result()

    def prefetch(body):
        nonlocal pending
        if pool is not None and pending is None:
            pending=(body,pool.submit(fetch,body))

    try:
        yield read,prefetch
    finally:
        if pool is not None:
            try:
                if pending is not None:
                    _,future=pending
                    if not future.cancel():
                        try:
                            future.result()
                        except exp.RollingRateLimitError:
                            # A rate limit must not be hidden by cancellation
                            # or a local verification failure.
                            raise
                        except Exception:
                            # Unconsumed window remains eligible on resume.
                            pass
            finally:
                pool.shutdown(wait=True,cancel_futures=True)


def run(*,start_date,end_date,wings=3,progress=None,fetcher=None,today=None,request_limit=None,should_stop=None,
        priority_sessions=None,on_counts=None,pipeline=None):
    today=today or exp._ist_today()
    start,stop,eligible=_scope(start_date,end_date,wings,today)
    priority_sessions=tuple(priority_sessions or ())
    if len(priority_sessions)>MAX_DAYS or any(not isinstance(d,str) or date.fromisoformat(d).isoformat()!=d for d in priority_sessions):
        raise ValueError("Invalid observed session priority dates")
    with acquisition_lock():
        if progress:
            progress(1,"Verifying existing expired-option receipt windows")
        observed={};statistics={"empty_verified_receipts":0}
        coverage,reused,rejected=_saved_windows(start,stop,wings,observed=observed,statistics=statistics)
        dates=_eligible_dates(eligible)
        checked=set()
        for key,windows in coverage.items():
            for a,b in windows:
                _add_checked(checked,key,max(a,start),min(b,stop),dates)
        total_pairs=len(dates)*2*len(exp._offsets(wings))
        known_days={d.isoformat() for d in dates}&set(priority_sessions)
        known_expected=len(known_days)*2*len(exp._offsets(wings))*375
        known_minutes=sum(mask.bit_count() for key,mask in observed.items() if key[2] in known_days)
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
        requests=_prioritize(requests,rank,priority_sessions)
        if len(requests)>MAX_REQUESTS:
            raise ValueError("Missing request scope exceeds bounded limit; shorten the date range")
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
        begun=time.monotonic()
        scan_counts={"eligible_offset_date_pairs":total_pairs,"checked_offset_date_pairs":len(checked)}
        def counts():
            elapsed=max(.001,time.monotonic()-begun)
            return {**scan_counts,"scope_start":start_date,"scope_end":end_date,"scope_wings":wings,
                    "known_observed_minute_slots":known_minutes,"known_expected_minute_slots":known_expected,
                    "known_market_dates":len(known_days),"checked_offset_date_pairs":len(checked),
                    "missing_offset_date_pairs":total_pairs-len(checked),
                    "planned_missing_requests":len(requests),"remaining_planned_requests":len(requests)-completed,
                    "batch_limit":min(len(requests),request_limit or len(requests)),
                    "batch_attempted":attempted,"batch_completed":completed,"new_receipts":downloaded,
                    "rejected_windows":len(rejected_requests),"existing_verified_receipts":reused,
                    "unreadable_receipts_encountered":rejected,
                    "empty_processed_receipts":empty,"empty_verified_receipts":statistics["empty_verified_receipts"],
                    "observed_session_dates":len({k[2] for k in observed}),
                    "active_receipts_per_minute":round(downloaded*60/elapsed,1) if elapsed>=10 and downloaded else None}
        def emit():
            if on_counts is not None:
                on_counts(counts())
        emit()
        if requests and fetcher is None and not (should_stop is not None and should_stop()):
            profile=dhan_auth.check_profile()
            if not profile.get("ok"):
                if profile.get("code")=="profile_unreachable":
                    raise exp.RollingConnectionError("Dhan profile connection unavailable; check local network")
                if profile.get("code")=="profile_rate_limited":
                    raise exp.RollingRateLimitError(profile.get("provider_retry_after_seconds",0))
                raise ValueError(profile.get("message") or "Verify Dhan historical-data access in Connections before downloading")
        begun=time.monotonic()
        # Production uses one-window lookahead outside live-priority passes.
        # Injected test transports remain sequential unless explicitly opted in.
        use_pipeline=(fetcher is None) if pipeline is None else bool(pipeline)
        batch=requests[:request_limit] if request_limit is not None else requests
        with _window_reader(fetcher,use_pipeline) as (read,prefetch):
            for i,body in enumerate(batch):
                if should_stop is not None and should_stop():
                    stopped_early=True
                    break
                if progress:
                    progress(min(95,5+90*attempted/max(1,len(requests))),
                             f"Option history {attempted}/{len(requests)}; {body['fromDate']}..{body['toDate']} {body['drvOptionType']} {body['strike']}")
                attempted+=1
                try:
                    payload,cached=read(body)
                except exp.RollingConnectionError:
                    emit()
                    raise
                except exp.RollingInputError:
                    consecutive+=1
                    rejected_requests.append({"from":body["fromDate"],"through":body["toDate"],
                                              "side":body["drvOptionType"],"strike":body["strike"],
                                              "code":"DH-905"})
                    emit()
                    if consecutive>=MAX_CONSECUTIVE_REJECTIONS or len(rejected_requests)>=MAX_REJECTIONS:
                        stopped_early=True
                        break
                    continue
                # Once a response is received, overlap the next network
                # request with local verification and atomic persistence.
                # The next window is never dispatched after a known error.
                if i+1<len(batch) and not (should_stop is not None and should_stop()):
                    prefetch(batch[i+1])
                rows=exp._normalize(payload,body)
                if cached:
                    exact_reused+=1
                else:
                    exp._save_cache(body,payload)
                    downloaded+=1
                known_minutes+=_record_observed(observed,rows,start,stop,count_days=known_days)
                consecutive=0
                completed+=1
                empty+=not bool(rows)
                usable+=sum(start_date<=r["session_ist"]<=end_date for r in rows)
                a,b=date.fromisoformat(body["fromDate"]),date.fromisoformat(body["toDate"])+timedelta(days=1)
                _add_checked(checked,(body["drvOptionType"],body["strike"]),max(a,start),min(b,stop),dates)
                emit()
        if attempted<len(requests):
            stopped_early=True
        if progress:
            progress(100,"Saved original receipts; some request windows remain" if rejected_requests or attempted<len(requests) else "Saved original receipts; inspect observed coverage")
        return {**preview(start_date,end_date,wings,today),**counts(),
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
