"""Authorized, bounded repair of the exact rolling history study scope.

Uses the canonical Dhan receipt cache. Wider offsets are tested on one
observed expired session before bulk acquisition, never assumed available.
"""
from datetime import date, datetime, timedelta, timezone
from collections import Counter
import time

from . import (alpha_retraining, cpr_execution_evidence as evidence,
               cpr_hybrid_research as r, data_maintenance as dm,
               dhan_auth, expired_options_backtest as exp, historical_alpha as h,
               options_history_sync as sync, recorder_storage)

CORE_WINGS=5
CORE_LIMIT=440
WIDE_LIMIT=112


def _safe():
    return (dm.safe_window(datetime.now(timezone.utc)) and
            alpha_retraining.safe_window(datetime.now(timezone.utc)) and
            recorder_storage.allow("market_maintenance"))


def probe_wings(day,today,*,fetcher=None,should_stop=None,progress=None):
    """Require positive observed rows on the same expired date for all
    four side/offset combinations at every additional width. This is
    evidence for this date only, not a guarantee of other dates.
    """
    selected=date.fromisoformat(day)
    previous=selected-timedelta(days=1)
    if not all(exp._expired_eligible(d,expiry_flag="MONTH",expiry_code=0,today=today)
               for d in (previous,selected)):
        raise ValueError("Probe requires two safely expired calendar dates")
    verified=CORE_WINGS;checks=[]
    with sync.acquisition_lock():
        for n in range(CORE_WINGS+1,sync.MAX_NEAR_WINGS+1):
            passed=True
            for side in ("CALL","PUT"):
                for offset in (f"ATM+{n}",f"ATM-{n}"):
                    if should_stop and should_stop():
                        return {"state":"paused","probe_date":day,"verified_wings":verified,"checks":checks}
                    body=exp._request_body(previous,selected,"MONTH",0,offset,side)
                    if progress:progress(50,f"Checking original {side} {offset} receipt for {day}")
                    try:
                        payload=exp._get_cached(body)
                        if payload is None:
                            if fetcher is None:
                                time.sleep(.45)
                                payload=exp._original_response_once(body)
                            else:
                                payload=fetcher(body)
                            if not isinstance(payload,dict) or not isinstance(payload.get("data"),dict):
                                raise ValueError("Invalid original response")
                            rows=exp._normalize(payload,body)
                            exp._save_cache(body,payload)
                        else:
                            rows=exp._normalize(payload,body)
                    except exp.RollingInputError:
                        checks.append({"side":side,"offset":offset,"state":"request_rejected"})
                        return {"state":"probe_limited","probe_date":day,"verified_wings":verified,"checks":checks}
                    except (ValueError,OSError,RuntimeError,TypeError,KeyError) as exc:
                        checks.append({"side":side,"offset":offset,"state":"source_unavailable","error_type":type(exc).__name__})
                        return {"state":"source_unavailable","probe_date":day,"verified_wings":verified,"checks":checks}
                    positive=sum(x["session_ist"]==day and (x.get("volume") or 0)>0 for x in rows)
                    checks.append({"side":side,"offset":offset,"positive_volume_rows":positive,
                                   "state":"observed" if positive else "no_positive_observation"})
                    passed=passed and positive>0
            if not passed:
                return {"state":"probe_limited","probe_date":day,"verified_wings":verified,"checks":checks}
            verified=n
    return {"state":"observed_on_probe_date","probe_date":day,"verified_wings":verified,"checks":checks}


def run(*,sessions=90,progress=None):
    if sessions not in r.SESSION_SPLITS:
        raise ValueError("Use 60, 90 or 120 observed sessions")
    cfg=dm.config()
    if not cfg["enabled"] or not cfg["options"]:
        raise ValueError("Existing automatic read-only option acquisition must be enabled")
    if not _safe():
        raise ValueError("Repair requires off-market priority hours and storage reserve")
    today=exp._ist_today()
    start=today-timedelta(days={60:100,90:150,120:200}[sessions])
    index,_,_=h.shared_index_sources(start-timedelta(days=7),today,[h.MAX_TOTAL])
    days=[d for d in sorted(index) if start.isoformat()<=d<today.isoformat() and date.fromisoformat(d).weekday()<5][-sessions:]
    if len(days)!=sessions:
        raise ValueError(f"Need {sessions} observed sessions; have {len(days)}")
    def stop():
        current=dm.config()
        return not (current["enabled"] and current["options"] and _safe())
    if not dhan_auth.check_profile().get("ok"):
        raise ValueError("Dhan authentication or historical data permission requires attention")
    scope=dict(start_date=days[0],end_date=days[-1],priority_sessions=days,today=today,
               should_stop=stop,progress=progress)
    report={"study_start":days[0],"study_end":days[-1],"core":None,"wide_probe":None,"wide":None,
            "warning":"Only expired near-month rolling receipts are repaired. Verified empty windows remain empty; absent contract bars are not fabricated. Wider support is date-specific. No orders or fills."}
    try:
        report["core"]=sync.run(**scope,wings=CORE_WINGS,request_limit=CORE_LIMIT)
    except (ValueError,OSError,RuntimeError,KeyError,TypeError) as exc:
        report.update(state="core_repair_blocked",error_type=type(exc).__name__)
        return report
    if stop():
        report["state"]="paused"
        return report
    if report["core"]["rejected_requests"]:
        report["state"]="core_requests_rejected"
        return report
    probe_dates=[d for d in days if len(index[d])==375 and all(
        exp._expired_eligible(v,expiry_flag="MONTH",expiry_code=0,today=today)
        for v in (date.fromisoformat(d),date.fromisoformat(d)-timedelta(days=1)))]
    if probe_dates:
        try:
            report["wide_probe"]=probe_wings(probe_dates[-1],today,should_stop=stop,progress=progress)
            wings=report["wide_probe"]["verified_wings"]
            if wings>CORE_WINGS and not stop() and report["wide_probe"]["state"]!="source_unavailable":
                report["wide"]=sync.run(**scope,wings=wings,request_limit=WIDE_LIMIT)
        except (ValueError,OSError,RuntimeError,KeyError,TypeError) as exc:
            report["wide_error_type"]=type(exc).__name__
    report["state"]="paused" if stop() else "bounded_pass_finished"
    return report
