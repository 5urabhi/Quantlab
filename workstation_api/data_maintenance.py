"""Opt-in automatic read-only market-library maintenance.

All acquisition passes are submitted to the existing serialized research
queue. No new market-price store, order API, or synthetic candles.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone, time as clock
from pathlib import Path
from threading import Event, RLock, Thread
from zoneinfo import ZoneInfo
import json
import os
import uuid

from . import (service, market_patterns as mp, cockpit_sources, dhan_workspace as dw,
               pit_index, dhan_auth, historical_alpha as ha, intraday_parquet as pq,
               options_history_sync as options, recorder_storage, job_safety)

IST=ZoneInfo("Asia/Kolkata")
DEFAULT={"enabled":False,"index":True,"constituents":True,"options":True,
         "index_days":365,"constituent_days":240,"option_days":365,"wings":3}
VERSION="automatic_market_library_v1"
INDEX_IDENTITIES=("INDEX:BANKNIFTY","INDEX:NIFTY50")
MAX_INDEX_WINDOWS=5
MAX_OPTION_REQUESTS=112
MAX_EQUITY_REPAIRS=2
REPAIR_COOLDOWN=timedelta(days=7)
RETRY=timedelta(hours=4)
LOCK=RLock()
STOP=Event()
WAKE=Event()
THREAD=None

def _now():
    return datetime.now(timezone.utc)

def _path(name):
    return service.DATA/"research_workspace"/("market_maintenance_"+name+".json")

def _read(name,default):
    path=_path(name)
    if not path.exists():
        return default
    if path.is_symlink() or path.stat().st_size>2_000_000:
        raise ValueError("Unsafe maintenance state file")
    value=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value,dict):
        raise ValueError("Invalid maintenance state")
    return value

def _write(name,value):
    path=_path(name);path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Unsafe maintenance state path")
    temp=path.with_name("."+path.name+"."+uuid.uuid4().hex+".tmp")
    try:
        with temp.open("x",encoding="utf-8") as f:
            json.dump(value,f,sort_keys=True,allow_nan=False)
        os.replace(temp,path)
    finally:
        temp.unlink(missing_ok=True)

def validate(cfg):
    if not isinstance(cfg,dict) or set(cfg)!=set(DEFAULT):
        raise ValueError("Invalid automatic maintenance settings")
    for k in ("enabled","index","constituents","options"):
        if type(cfg[k]) is not bool:
            raise ValueError("Maintenance switches must be boolean")
    for k,lo,hi in (("index_days",30,365),("constituent_days",30,240),("option_days",30,365),("wings",0,5)):
        if type(cfg[k]) is not int or not lo<=cfg[k]<=hi:
            raise ValueError("Maintenance scope outside supported bound: "+k)
    if cfg["enabled"] and not any(cfg[k] for k in ("index","constituents","options")):
        raise ValueError("Enable at least one source scope")
    if cfg["enabled"] and cfg["constituents"] and not cfg["index"]:
        raise ValueError("Constituent coverage repair requires the index history scope")
    return dict(cfg)

def config():
    with LOCK:
        return validate(_read("config",dict(DEFAULT)))

def enabled():
    try:
        return config()["enabled"]
    except (OSError,ValueError,TypeError):
        return False

def _state():
    return _read("state",{})

def _save_state(state):
    with LOCK:
        _write("state",state)

def configure(cfg,confirm):
    cfg=validate(cfg)
    if cfg["enabled"] and confirm is not True:
        raise ValueError("Authorize recurring read-only historical requests for the selected scope")
    with LOCK:
        old=config()
        _write("config",cfg)
        state=_state()
        if old!=cfg:
            state["next_due_utc"]=None
            state["target"]=None
            _write("state",state)
    # Transfer the old index-only policy to this one master control.
    if cfg["enabled"]:
        mp.configure_sync(False)
    WAKE.set()
    return status()

def _local(now):
    return now.astimezone(IST)

def safe_window(now):
    local=_local(now)
    # Quiet period; does not claim a weekday is an exchange session.
    return local.weekday()>=5 or local.time().replace(tzinfo=None)<clock(8,30) or local.time().replace(tzinfo=None)>=clock(16)

def target_dates(now):
    local=_local(now);day=local.date()
    candidate=day if local.time().replace(tzinfo=None)>=clock(16) else day-timedelta(days=1)
    while candidate.weekday()>=5:
        candidate-=timedelta(days=1)
    stop=candidate+timedelta(days=1)
    option_end=min(candidate,day-timedelta(days=1))
    return stop,option_end

def _target(now):
    stop,option_end=target_dates(now)
    return {"end_exclusive":stop.isoformat(),"option_through":option_end.isoformat()}

def _due(cfg,state,now):
    if not cfg["enabled"] or not safe_window(now):
        return False
    if state.get("target")!=_target(now):
        return True
    try:
        return not state.get("next_due_utc") or datetime.fromisoformat(state["next_due_utc"])<=now
    except (ValueError,TypeError):
        return True

def status():
    try:
        with LOCK:
            cfg=config();state=_state()
        error=None
    except (OSError,ValueError,TypeError):
        cfg=dict(DEFAULT);state={};error="Maintenance configuration or checkpoint unreadable"
    now=_now()
    return {"version":VERSION,"config":cfg,"last_run":state.get("last_run"),"target":_target(now),
            "next_due_utc":state.get("next_due_utc"),"batch_id":state.get("batch_id"),
            "safe_window":safe_window(now),"worker_running":bool(THREAD and THREAD.is_alive()),
            "due":_due(cfg,state,now),"error":error,
            "limits":{"option_requests_per_pass":MAX_OPTION_REQUESTS,"equity_repairs_per_instrument":MAX_EQUITY_REPAIRS},
            "note":"Runs while the backend is open, outside the Indian market recording window. Verified request coverage is not proof of every minute. Global feeds, approved report deliveries and live capture retain their own source permissions. Historical missed ticks/books, unknown membership, unavailable provider history and missing dated weights cannot be fabricated."}

def request_check():
    if not enabled():
        raise ValueError("Enable and authorize automatic maintenance first")
    with LOCK:
        state=_state()
        state["next_due_utc"]=None
        _write("state",state)
    WAKE.set()
    return status()

def _attempt_allowed(attempts,key,now):
    try:
        return datetime.fromisoformat(attempts[key])+REPAIR_COOLDOWN<=now
    except (KeyError,ValueError,TypeError):
        return True

def _mark(state,key,now):
    state.setdefault("repairs",{})[key]=now.isoformat()
    # Preserve a bounded cooldown ledger; remove only old retry metadata.
    state["repairs"]={k:v for k,v in state["repairs"].items()
                       if not _attempt_allowed({k:v},k,now)}
    _save_state(state)

def _index_plan(source,other,start,stop,identity,state,now):
    gaps=mp.missing_windows(start,stop,source["coverage"])
    gaps=[(a,b) for a,b in gaps if any((a+timedelta(days=i)).weekday()<5 for i in range((b-a).days))]
    expected={d for d,bars in source["days"].items() if 0<len(bars)<mp.MINUTES}
    # Other observed complete index sessions establish market activity;
    # never infer an exchange holiday or missing session from a weekday.
    expected.update(d for d in other.get("complete",{}) if not source["days"].get(d))
    missing=sorted(d for d in expected if start.isoformat()<=d<stop.isoformat())
    selected=[]
    for day in missing:
        d=date.fromisoformat(day)
        if any(a<=d<b for a,b in gaps):
            continue
        key=identity+"|"+day
        if _attempt_allowed(state.get("repairs",{}),key,now):
            selected.append((d,d+timedelta(days=1),key))
    return [(a,b,None) for a,b in gaps[:MAX_INDEX_WINDOWS]]+selected[:max(0,MAX_INDEX_WINDOWS-len(gaps))],missing

def _index_pass(cfg,state,now,stop,progress,should_stop):
    today=_local(now).date()
    start=today-timedelta(days=cfg["index_days"])
    sources={k:mp._history(k,today) for k in INDEX_IDENTITIES}
    result={}
    for i,identity in enumerate(INDEX_IDENTITIES):
        source=sources[identity];other=sources[INDEX_IDENTITIES[1-i]]
        plan,missing=_index_plan(source,other,start,stop,identity,state,now)
        errors=0;downloaded=0
        for a,b,key in plan:
            if should_stop():break
            if key:_mark(state,key,_now())
            if progress:progress(5+i*10,"Updating original "+identity+" history "+a.isoformat())
            try:
                cockpit_sources.download_spot(identity,a.isoformat(),b.isoformat())
                downloaded+=1
            except (ValueError,OSError,RuntimeError):
                errors+=1
            with mp.LOCK:
                mp.CACHE.pop(identity,None)
        final=mp._history(identity,today)
        # Include the current day's closed receipt in observed completeness;
        # the historical baseline deliberately excludes today.
        complete=sum(len(bars)==mp.MINUTES for d,bars in final["days"].items() if start.isoformat()<=d<stop.isoformat())
        partial=sum(0<len(bars)<mp.MINUTES for d,bars in final["days"].items() if start.isoformat()<=d<stop.isoformat())
        uncovered=mp.missing_windows(start,stop,final["coverage"])
        uncovered=[(a,b) for a,b in uncovered if any((a+timedelta(days=i)).weekday()<5 for i in range((b-a).days))]
        missing_observed=sum(not final["days"].get(d) for d in missing)
        result[identity]={"state":"partial" if errors or uncovered or partial or missing_observed or final["rejected_receipts"] or final["omitted_receipts"] else "checked",
                          "complete_observed_sessions":complete,"partial_observed_sessions":partial,
                          "uncovered_request_windows":len(uncovered),"missing_other_index_observed_sessions":missing_observed,
                          "rejected_receipts":final["rejected_receipts"],"omitted_receipts":final["omitted_receipts"],
                          "downloaded_windows":downloaded,"failed_windows":errors}
    return result

def _batch_for(state,start,stop,plan):
    desired=[start.isoformat(),stop.isoformat(),plan["source_sha256"],
             sorted((r["pit_symbol"],r["id"]) for r in plan["resolved"])]
    # JSON normalizes tuple/list representations before persisted comparison.
    desired=json.loads(json.dumps(desired))
    if state.get("batch_scope")==desired and state.get("batch_id"):
        try:
            raw=dw._load_batch(state["batch_id"])
            if raw.get("maintenance_owned") and raw["from_date"]==desired[0] and raw["to_date"]==desired[1]:
                return raw
        except (OSError,ValueError,KeyError):
            pass
    summary=dw.create_batch(selection="banknifty_pit",ids=[],tickers=[],from_date=desired[0],to_date=desired[1],
                            interval=1,acknowledged_bulk=False,acknowledged_gaps=True,include_index_spot=False)
    raw=dw._load_batch(summary["id"])
    raw["maintenance_owned"]=True
    dw._save_batch(raw)
    state.update(batch_id=raw["id"],batch_scope=desired)
    _save_state(state)
    return raw

def _equity_audit(raw,start,stop,index_days,state,now,*,choose_repairs):
    intervals=raw["historical_index"]["intervals"]
    budget=[ha.MAX_TOTAL]
    complete_dates=sorted(d for d,b in index_days.items()
                          if start.isoformat()<=d<stop.isoformat() and len(b)==mp.MINUTES)
    result={};repairs={}
    for item in raw["items"]:
        symbol=item["pit_symbol"];identity=item["id"]
        days=[d for d in complete_dates if symbol in ha._member_set(intervals,d)]
        gaps=[]
        try:
            sig=pq._source_signature(identity)
            if not sig:
                raise ValueError("Original minute file absent")
            path,_=pq._raw(identity)
            candles=ha._read_file(path,sig["source_sha256"],start,stop,budget)
            gaps=[d for d in days if len(candles.get(d,{}))<mp.MINUTES]
            result[symbol]={"expected_observed_index_sessions":len(days),"complete_sessions":len(days)-len(gaps),
                            "missing_or_partial_sessions":len(gaps),"example_dates":gaps[:8]}
            if choose_repairs:
                eligible=[d for d in gaps if _attempt_allowed(state.get("repairs",{}),identity+"|"+d,now)]
                if eligible:
                    repairs[identity]=eligible[:MAX_EQUITY_REPAIRS]
        except (OSError,ValueError,TypeError,KeyError,OverflowError):
            result[symbol]={"expected_observed_index_sessions":len(days),"complete_sessions":None,
                            "missing_or_partial_sessions":None,"state":"original_source_unavailable"}
    return result,repairs

class _Stop:
    def __init__(self,check,progress):
        self.check=check;self.progress=progress;self.cancelled=False
    def is_set(self):
        if self.cancelled or self.check():return True
        if self.progress:
            try:self.progress(45,"Updating dated BANKNIFTY constituent history")
            except Exception:
                self.cancelled=True
                return True
        return False

def _equity_pass(cfg,state,now,stop,progress,should_stop):
    start=_local(now).date()-timedelta(days=cfg["constituent_days"])
    info=pit_index.status()
    # Refresh the existing independently licensed reconstruction, not an NSE
    # website scraper. Never extend an undocumented membership interval.
    if not info.get("available") or date.fromisoformat(info["covered_through"])<stop-timedelta(days=1):
        try:
            last=state.get("membership_refresh_utc")
            if not last or datetime.fromisoformat(last)+timedelta(hours=24)<=now:
                state["membership_refresh_utc"]=now.isoformat();_save_state(state)
                info=pit_index.sync()
        except (ValueError,OSError,RuntimeError):
            info=pit_index.status()
    if not info.get("available"):
        return {"state":"blocked","reason":"Dated membership unavailable"}
    eligible_stop=min(stop,date.fromisoformat(info["covered_through"])+timedelta(days=1))
    start=max(start,date.fromisoformat(info["first_date"]))
    if eligible_stop<=start:
        return {"state":"blocked","reason":"No documented membership in authorized lookback"}
    if (eligible_stop-start).days>ha.MAX_DAYS:
        start=eligible_stop-timedelta(days=ha.MAX_DAYS)
    plan=pit_index.query("banknifty_pit",start.isoformat(),eligible_stop.isoformat(),dw.catalog())
    if not 1<=len(plan["resolved"])<=ha.MAX_INSTRUMENTS:
        return {"state":"blocked","reason":"No bounded unambiguous Dhan constituent universe","unresolved":plan["unresolved"]}
    raw=_batch_for(state,start,eligible_stop,plan)
    index=mp._history("INDEX:BANKNIFTY",_local(now).date())["days"]
    _,repairs=_equity_audit(raw,start,eligible_stop,index,state,now,choose_repairs=True)
    # Do not retry entire previously checked windows on every pass. Repair
    # only gaps identified on actual complete index-session dates.
    for identity,days in repairs.items():
        for day in days:_mark(state,identity+"|"+day,_now())
    stop_event=_Stop(should_stop,progress)
    if should_stop():
        return {"state":"paused","batch_id":raw["id"]}
    outcome=dw.run_batch(raw["id"],cancel_event=stop_event,repair_dates_by_identity=repairs)
    if stop_event.cancelled and progress:
        progress(45,"Cancelling automatic maintenance")
    observed,_=_equity_audit(raw,start,eligible_stop,index,state,now,choose_repairs=False)
    gaps=sum(x["missing_or_partial_sessions"] or 0 for x in observed.values())
    unavailable=sum(x["complete_sessions"] is None for x in observed.values())
    return {"state":"partial" if gaps or unavailable or plan["unresolved"] or eligible_stop<stop or outcome["status"]!="completed" or outcome["errors"] or not observed else "checked",
            "batch_id":raw["id"],"documented_through":info["covered_through"],"requested_end_exclusive":stop.isoformat(),
            "actual_end_exclusive":eligible_stop.isoformat(),"unresolved":plan["unresolved"],"batch_status":outcome["status"],
            "batch_counts":outcome["counts"],"observed_member_session_gaps":gaps,"unavailable_sources":unavailable,
            "members":observed,"repair_dates_attempted":sum(map(len,repairs.values()))}

def run(*,progress=None,now=None):
    now=now or _now();cfg=config()
    if not cfg["enabled"] or not safe_window(now):
        return {"state":"paused","reason":"Disabled or live-session priority"}
    with LOCK:
        state=_state()
    stop,option_end=target_dates(now)
    report={"started_utc":now.isoformat(),"state":"running","sources":{}}
    state.update(target=_target(now),next_due_utc=(now+RETRY).isoformat(),last_run=report)
    _save_state(state)
    def should_stop():
        return STOP.is_set() or config()!=cfg or not safe_window(_now()) or not recorder_storage.allow("market_maintenance")
    try:
        if progress:progress(1,"Checking Dhan connection and shared storage")
        if should_stop():
            report.update(state="paused",reason="Disabled, market session, or storage reserve")
            return report
        if not dhan_auth.check_profile().get("ok"):
            report.update(state="blocked",reason="Dhan token or historical data permission requires attention")
            return report
        if cfg["index"]:
            # Legacy spot sync uses the same guard and yields while the
            # master policy is enabled.
            with mp.HISTORY_WRITE_LOCK:
                report["sources"]["index"]=_index_pass(cfg,state,now,stop,progress,should_stop)
            _save_state(state)
        if cfg["constituents"] and not should_stop():
            if progress:progress(30,"Checking dated banking constituents")
            try:
                report["sources"]["constituents"]=_equity_pass(cfg,state,now,stop,progress,should_stop)
            except (ValueError,OSError,RuntimeError,KeyError,TypeError) as exc:
                if progress:progress(49,"Constituent history remains partially unavailable")
                report["sources"]["constituents"]={"state":"blocked","reason":job_safety.scrub(exc)[:200]}
            _save_state(state)
        if cfg["options"] and not should_stop():
            if progress:progress(55,"Checking saved expired-option request windows")
            try:
                opt=options.run(start_date=(_local(now).date()-timedelta(days=cfg["option_days"])).isoformat(),
                    end_date=option_end.isoformat(),wings=cfg["wings"],request_limit=MAX_OPTION_REQUESTS,
                    should_stop=should_stop,progress=(lambda pct,msg:progress(55+.44*pct,msg)) if progress else None)
                report["sources"]["options"]={k:opt[k] for k in ("state","existing_verified_receipts","new_receipts",
                    "planned_missing_requests","unattempted_requests","empty_processed_receipts","usable_rows_in_processed_receipts",
                    "unreadable_receipts_encountered","excluded_active_calendar_days","continuous_coverage_certified",
                    "empty_verified_receipts","observed_rolling_minute_slots","observed_offset_session_pairs","observed_session_dates")}
                report["sources"]["options"]["rejected_windows"]=len(opt["rejected_requests"])
                report["sources"]["options"]["state"]="partial" if opt["state"]=="partial_requests" or opt["unreadable_receipts_encountered"] else "checked"
            except (ValueError,OSError,RuntimeError,KeyError,TypeError) as exc:
                if progress:progress(99,"Option history remains partially unavailable")
                report["sources"]["options"]={"state":"blocked","reason":job_safety.scrub(exc)[:200]}
        states=[v["state"] for k,v in report["sources"].items() if k!="index"]
        states.extend(v["state"] for v in report["sources"].get("index",{}).values())
        report["state"]="paused" if should_stop() else "partial" if not states or any(x!="checked" for x in states) else "checked"
        if report["state"]=="checked":
            state["next_due_utc"]=(now+timedelta(hours=24)).isoformat()
        if progress:progress(100,"Automatic maintenance pass saved")
        return report
    finally:
        if report["state"]=="running":report["state"]="interrupted"
        report["finished_utc"]=_now().isoformat()
        with LOCK:
            # Preserve a concurrently saved request to disable/reconfigure;
            # its new settings take effect at the next safe boundary.
            if config()!=cfg:
                state["target"]=None;state["next_due_utc"]=None
            state["last_run"]=report
            _save_state(state)

def _worker(submit):
    while not STOP.is_set():
        try:
            with LOCK:
                cfg=config();state=_state()
            if _due(cfg,state,_now()):
                submit()
        except (OSError,ValueError,TypeError,RuntimeError):
            pass
        WAKE.wait(30);WAKE.clear()

def start(submit):
    global THREAD
    with LOCK:
        if THREAD and THREAD.is_alive():return
        STOP.clear()
        THREAD=Thread(target=_worker,args=(submit,),daemon=True,name="market-library-maintenance")
        THREAD.start()

def shutdown():
    STOP.set();WAKE.set()
