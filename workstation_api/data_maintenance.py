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
DEFAULT={"enabled":False,"index":True,"constituents":True,"options":True,"bank_panel":False,
         "index_days":365,"constituent_days":240,"option_days":365,"wings":3}
VERSION="automatic_market_library_v8"
SCHEDULE_VERSION=8
INDEX_IDENTITIES=("INDEX:BANKNIFTY","INDEX:NIFTY50")
MAX_INDEX_WINDOWS=5
MAX_OPTION_REQUESTS=440
MAX_EQUITY_REPAIRS=2
LIVE_INDEX_WINDOWS=1
LIVE_OPTION_REQUESTS=64
LIVE_EQUITY_REPAIRS=1
LIVE_RECORDER_DROP_COOLDOWN=timedelta(minutes=2)
LIVE_QUOTE_QUEUE_FRACTION=.10
REPAIR_COOLDOWN=timedelta(days=7)
RETRY=timedelta(minutes=5)
RATE_LIMIT_RETRY=timedelta(minutes=15)
PRODUCTIVE_RETRY=timedelta(seconds=30)
PRESSURE_RETRY=timedelta(minutes=2)
CONNECTION_RETRY_MINUTES=(2,4,8,16,30)
CHECKED_RETRY=timedelta(hours=24)
LOCK=RLock()
STOP=Event()
WAKE=Event()
THREAD=None
OPTION_PROGRESS=None

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
    if isinstance(cfg,dict) and set(cfg)==set(DEFAULT)-{"bank_panel"}:
        cfg={**cfg,"bank_panel":False}
    if not isinstance(cfg,dict) or set(cfg)!=set(DEFAULT):
        raise ValueError("Invalid automatic maintenance settings")
    for k in ("enabled","index","constituents","options","bank_panel"):
        if type(cfg[k]) is not bool:
            raise ValueError("Maintenance switches must be boolean")
    for k,lo,hi in (("index_days",30,365),("constituent_days",30,240),("option_days",30,365),("wings",0,options.MAX_NEAR_WINGS)):
        if type(cfg[k]) is not int or not lo<=cfg[k]<=hi:
            raise ValueError("Maintenance scope outside supported bound: "+k)
    if cfg["enabled"] and not any(cfg[k] for k in ("index","constituents","options","bank_panel")):
        raise ValueError("Enable at least one source scope")
    if cfg["enabled"] and (cfg["constituents"] or cfg["bank_panel"]) and not cfg["index"]:
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
            due,reason=_effective_schedule(state)
            if reason=="provider_rate_limit" and due and datetime.fromisoformat(due)>_now():
                state["next_due_utc"]=due
                state["next_due_reason"]=reason
                state["schedule_version"]=SCHEDULE_VERSION
            else:
                state["next_due_utc"]=None
                state["next_due_reason"]="configuration_changed"
            state["target"]=None
            state.pop("coverage_sources",None)
            state.pop("coverage_config",None)
            state.pop("connection_failure_count",None)
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
    # Quiet period for intensive work, NOT a prohibition on historical
    # acquisition. Does not claim a weekday is an exchange session.
    return local.weekday()>=5 or local.time().replace(tzinfo=None)<clock(8,30) or local.time().replace(tzinfo=None)>=clock(16)

def _recent_pressure(stamp,now):
    if not stamp:
        return False
    try:
        age=now-datetime.fromisoformat(stamp)
        return timedelta(0)<=age<LIVE_RECORDER_DROP_COOLDOWN
    except (TypeError,ValueError):
        return False


def live_pressure(now):
    """Cheap process-local storage/queue pressure check, not a fill or
    latency guarantee. Historical work yields at request boundaries.
    No historical scan of quote events and no provider calls.
    """
    if safe_window(now):
        return None
    from . import full_option_feed as feed
    if feed.WRITES.qsize()>=max(1,int(feed.MAX_QUEUE*LIVE_QUOTE_QUEUE_FRACTION)):
        return "live_quote_queue_backlog"
    with feed.LOCK:
        recent=any(_recent_pressure(feed.STATUS.get(k),now) for k in ("storage_last_drop_utc","storage_gap_started_utc"))
    if recent:
        return "recent_live_quote_storage_gap"
    for stream in ("quote_oi_queue","option_chain","auto_depth","individual_depth","live_ticks"):
        health=recorder_storage.status(stream)
        if any(_recent_pressure(health.get(k),now) for k in ("last_drop_utc","gap_started_utc")):
            return "recent_live_recorder_storage_gap:"+stream
    return None


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

def _rate_limit_message(value):
    text=str(value or "").lower()
    return ("rate-limit" in text or "rate limit" in text or "http 429" in text
            or "(429)" in text or "dh-904" in text or "too many requests" in text
            or text.strip() in ("429","805"))


def _effective_schedule(state):
    """Apply the shorter policy to old saved checkpoints on startup.
    Migrate v7 cross-source backoff only when a productive lane can resume.
    Do not shorten an explicit provider cooldown already recorded by v7.
    """
    due=state.get("next_due_utc")
    reason=state.get("next_due_reason")
    last=state.get("last_run") or {}
    version=state.get("schedule_version")
    if not due or version==SCHEDULE_VERSION or reason=="provider_rate_limit":
        return due,reason
    if version==7 and reason not in ("source_error_backoff","source_blocked_or_paused"):
        return due,reason
    finished=last.get("finished_utc")
    if not finished:
        if reason=="pass_running" and last.get("started_utc"):
            return min(datetime.fromisoformat(due),datetime.fromisoformat(last["started_utc"])+RETRY).isoformat(),reason
        return due,reason
    old_option=last.get("sources",{}).get("options",{})
    if old_option.get("reason")=="Dhan expired-options data connection unavailable; check local network":
        last={**last,"transient_connection_failure":True}
    if last.get("state") not in ("partial","blocked","paused","interrupted","checked"):
        return due,reason
    delay,new_reason=_next_schedule(last)
    if version==7 and delay!=PRODUCTIVE_RETRY:
        return due,reason
    revised=datetime.fromisoformat(finished)+delay
    original=datetime.fromisoformat(due)
    return (revised.isoformat(),new_reason) if revised<original else (due,reason)


def _due(cfg,state,now):
    if not cfg["enabled"]:
        return False
    try:
        due,reason=_effective_schedule(state)
        if reason=="provider_rate_limit" and due and datetime.fromisoformat(due)>now:
            return False
        if state.get("target")!=_target(now):
            return True
        return not due or datetime.fromisoformat(due)<=now
    except (ValueError,TypeError):
        return True

def _connection_delay(failures):
    return timedelta(minutes=CONNECTION_RETRY_MINUTES[min(len(CONNECTION_RETRY_MINUTES)-1,max(0,failures-1))])


def _next_schedule(report):
    """Only accelerate bounded batches that made progress and have more work.
    Independent productive lanes must not inherit unrelated source errors.
    Shared throttling, connection failures and market/storage guards take
    precedence. Failed lanes retain their existing bounded repair policies.
    """
    state=report["state"]
    sources=report.get("sources",{})
    lanes=[*sources.get("index",{}).values(),*(v for k,v in sources.items() if k!="index")]
    if report.get("provider_rate_limited") or any(v.get("provider_rate_limited") or _rate_limit_message(v.get("reason")) for v in lanes) or _rate_limit_message(report.get("reason")):
        seconds=max(RATE_LIMIT_RETRY.total_seconds(),report.get("provider_retry_after_seconds",0) or 0)
        return timedelta(seconds=seconds),"provider_rate_limit"
    if state=="checked":
        return CHECKED_RETRY,"all_authorized_scopes_checked"
    if state=="paused" and report.get("pause_reason","").startswith(("live_","recent_live_","market_priority_transition")):
        return PRESSURE_RETRY,"live_recording_priority"
    if state=="blocked" and report.get("transient_connection_failure"):
        return _connection_delay(report.get("connection_failure_count",1)),"connection_retry"
    if state!="partial":
        return RETRY,"normal_backoff"
    sources=report.get("sources",{})
    index=list(sources.get("index",{}).values())
    equity=[sources[k] for k in ("constituents","bank_panel") if k in sources]
    option=sources.get("options",{})
    if report.get("transient_connection_failure") and not (
        any(v.get("state") in ("blocked","paused") or v.get("failed_windows",0) or v.get("rejected_receipts",0) or v.get("omitted_receipts",0) for v in index)
        or any(v.get("state") in ("blocked","paused") or v.get("batch_errors") or v.get("unavailable_sources",0) or v.get("unresolved") or v.get("batch_status") not in (None,"completed") for v in equity)
        or option.get("rejected_windows",0) or option.get("unreadable_receipts_encountered",0)):
        return _connection_delay(report.get("connection_failure_count",1)),"connection_retry"
    def blocked(v):
        return v.get("state") in ("blocked","paused")
    def index_error(v):
        return blocked(v) or any(v.get(k,0) for k in ("failed_windows","rejected_receipts","omitted_receipts"))
    def equity_error(v):
        return blocked(v) or v.get("batch_errors") or v.get("unavailable_sources",0) or v.get("unresolved") or v.get("batch_status") not in (None,"completed")
    # A verified full batch can keep filling missing windows even if the
    # local scan found a separate unreadable historical receipt. Never
    # accelerate a rejected, interrupted or stale provider batch.
    full_option_batch=(option.get("batch_limit",0)>0
                       and option.get("batch_attempted")==option.get("batch_limit")
                       and option.get("batch_completed")==option.get("batch_limit"))
    option_error=(blocked(option) or option.get("progress_stale")
                  or option.get("rejected_windows",0)
                  or (option.get("unreadable_receipts_encountered",0) and not full_option_batch))
    if not report.get("transient_connection_failure"):
        if not option_error and option.get("new_receipts",0)>0 and option.get("unattempted_requests",0)>0:
            return PRODUCTIVE_RETRY,"more_option_requests"
        if any(not equity_error(v) and v.get("repair_dates_attempted",0)>0 and v.get("retryable_member_session_gaps",0)>0 for v in equity):
            return PRODUCTIVE_RETRY,"more_unattempted_equity_repairs"
        if any(not index_error(v) and v.get("downloaded_windows",0)>0 and v.get("uncovered_request_windows",0)>0 for v in index):
            return PRODUCTIVE_RETRY,"more_index_windows"
    if any(blocked(v) for v in [*index,*equity,option]):
        return RETRY,"source_blocked_or_paused"
    if any(index_error(v) for v in index) or any(equity_error(v) for v in equity) or option_error or option.get("unreadable_receipts_encountered",0):
        return RETRY,"source_error_backoff"
    return RETRY,"no_more_immediately_actionable_work"


def status():
    try:
        with LOCK:
            cfg=config();state=_state()
            active_counts=dict(OPTION_PROGRESS) if OPTION_PROGRESS is not None else None
        error=None
    except (OSError,ValueError,TypeError):
        cfg=dict(DEFAULT);state={};active_counts=None;error="Maintenance configuration or checkpoint unreadable"
    now=_now()
    last=state.get("last_run") or {}
    same_scope=state.get("coverage_config")==cfg
    coverage=state.get("coverage_sources",{}) if same_scope else {}
    # Retain last verified source audit while another pass is in progress.
    sources={**coverage,**last.get("sources",{})} if same_scope or not state.get("coverage_config") else {}
    try:
        due_at,due_reason=_effective_schedule(state)
    except (ValueError,TypeError):
        due_at,due_reason=state.get("next_due_utc"),state.get("next_due_reason")
    return {"version":VERSION,"coverage_sources":sources,"option_progress":active_counts if cfg["enabled"] and last.get("state")=="running" else None,"config":cfg,"last_run":state.get("last_run"),"target":_target(now),
            "next_due_utc":due_at,"next_due_reason":due_reason,
            "connection_failure_count":state.get("connection_failure_count",0),"batch_id":state.get("batch_id"),
            "safe_window":safe_window(now),"backfill_mode":"standard" if safe_window(now) else "live_priority",
            "live_pressure":live_pressure(now) if cfg["enabled"] else None,
            "worker_running":bool(THREAD and THREAD.is_alive()),
            "due":_due(cfg,state,now),"error":error,
            "limits":{"option_requests_per_pass":MAX_OPTION_REQUESTS,"equity_repairs_per_instrument":MAX_EQUITY_REPAIRS,
                      "live_option_requests_per_pass":LIVE_OPTION_REQUESTS,"live_equity_repairs_per_instrument":LIVE_EQUITY_REPAIRS,
                      "live_index_windows_per_instrument":LIVE_INDEX_WINDOWS,
                      "productive_retry_seconds":int(PRODUCTIVE_RETRY.total_seconds()),"live_pressure_retry_seconds":int(PRESSURE_RETRY.total_seconds()),"normal_retry_seconds":int(RETRY.total_seconds()),"rate_limit_retry_seconds":int(RATE_LIMIT_RETRY.total_seconds())},
            "note":"Runs while the backend is open, including during Indian market hours with smaller batches and live-recorder pressure checks. In-flight requests may finish before a pause. Verified request coverage is not proof of every minute. Global feeds, approved report deliveries and live capture retain their own source permissions. Historical missed ticks/books, unknown membership, unavailable provider history and missing dated weights cannot be fabricated."}

def request_check():
    if not enabled():
        raise ValueError("Enable and authorize automatic maintenance first")
    with LOCK:
        state=_state()
        due,reason=_effective_schedule(state)
        if reason=="provider_rate_limit" and due and datetime.fromisoformat(due)>_now():
            return status()
        state["next_due_utc"]=None
        state["next_due_reason"]="manual_check_requested"
        _write("state",state)
    WAKE.set()
    return status()

def credentials_verified():
    """Wake an already authorized pass after a successful Dhan profile check.

    Do not restart active or completed work, or clear provider, storage or
    live-recorder guards. This event contains no credentials.
    """
    with LOCK:
        cfg=config()
        if not cfg["enabled"]:
            return False
        state=_state()
        last=state.get("last_run") or {}
        due,reason=_effective_schedule(state)
        if reason=="provider_rate_limit" and due and datetime.fromisoformat(due)>_now():
            return False
        if last.get("state") not in ("blocked","partial"):
            return False
        # Older checkpoints used only a generic top-level auth blocker.
        profile_code=last.get("profile_code")
        auth_or_connection=(bool(profile_code) or
            last.get("reason")=="Dhan token or historical data permission requires attention" or
            reason=="connection_retry")
        if not auth_or_connection or reason in ("provider_rate_limit","live_recording_priority"):
            return False
        state["next_due_utc"]=None
        state["next_due_reason"]="credentials_verified"
        state["connection_failure_count"]=0
        state["schedule_version"]=SCHEDULE_VERSION
        _write("state",state)
    WAKE.set()
    return True


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

def _index_plan(source,other,start,stop,identity,state,now,*,limit=MAX_INDEX_WINDOWS):
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
    return [(a,b,None) for a,b in gaps[:limit]]+selected[:max(0,limit-len(gaps))],missing

def _index_pass(cfg,state,now,stop,progress,should_stop):
    today=_local(now).date()
    start=today-timedelta(days=cfg["index_days"])
    sources={k:mp._history(k,today) for k in INDEX_IDENTITIES}
    result={}
    provider_rate_limited=False
    for i,identity in enumerate(INDEX_IDENTITIES):
        source=sources[identity];other=sources[INDEX_IDENTITIES[1-i]]
        plan,missing=_index_plan(source,other,start,stop,identity,state,now,
                                 limit=MAX_INDEX_WINDOWS if safe_window(now) else LIVE_INDEX_WINDOWS)
        errors=0;downloaded=0
        for a,b,key in plan:
            if provider_rate_limited or should_stop():break
            if progress:progress(5+i*10,"Updating original "+identity+" history "+a.isoformat())
            try:
                cockpit_sources.download_spot(identity,a.isoformat(),b.isoformat())
                downloaded+=1
            except (ValueError,OSError,RuntimeError) as exc:
                errors+=1
                if _rate_limit_message(exc):
                    provider_rate_limited=True
                    break
            if key:_mark(state,key,_now())
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
        result[identity]={"state":"partial" if provider_rate_limited or errors or uncovered or partial or missing_observed or final["rejected_receipts"] or final["omitted_receipts"] else "checked",
                          "complete_observed_sessions":complete,"partial_observed_sessions":partial,
                          "uncovered_request_windows":len(uncovered),"missing_other_index_observed_sessions":missing_observed,
                          "rejected_receipts":final["rejected_receipts"],"omitted_receipts":final["omitted_receipts"],
                          "downloaded_windows":downloaded,"failed_windows":errors,
                          "provider_rate_limited":provider_rate_limited}
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
            eligible=[d for d in gaps if _attempt_allowed(state.get("repairs",{}),identity+"|"+d,now)]
            # Count missing minutes on audited index dates, rather than
            # describing a 374-bar session and an absent day identically.
            histogram=defaultdict(int)
            for day in gaps:
                histogram[str(len(candles.get(day,{})))]+=1
            result[symbol]={"expected_observed_index_sessions":len(days),"complete_sessions":len(days)-len(gaps),
                            "missing_or_partial_sessions":len(gaps),"retryable_sessions":len(eligible),"example_dates":gaps[:8],
                            "incomplete_session_minute_counts":dict(histogram),
                            "example_gap_minutes":{d:len(candles.get(d,{})) for d in gaps[:8]}}
            if choose_repairs:
                if eligible:
                    repairs[identity]=eligible[:MAX_EQUITY_REPAIRS if safe_window(now) else LIVE_EQUITY_REPAIRS]
        except (OSError,ValueError,TypeError,KeyError,OverflowError):
            result[symbol]={"expected_observed_index_sessions":len(days),"complete_sessions":None,
                            "missing_or_partial_sessions":None,"state":"original_source_unavailable"}
    return result,repairs

def _repair_request_callback(state,repairs):
    """A cancelled or not-yet-attempted date must not receive a seven-day
    cooldown just because it was included in the planned batch."""
    attempted=set()
    def on_request(identity,first,last):
        for day in repairs.get(identity,()):
            key=identity+"|"+day
            if first<=date.fromisoformat(day)<last and key not in attempted:
                _mark(state,key,_now())
                attempted.add(key)
    return on_request,attempted


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
    on_request,attempted=_repair_request_callback(state,repairs)
    stop_event=_Stop(should_stop,progress)
    if should_stop():
        return {"state":"paused","batch_id":raw["id"]}
    outcome=dw.run_batch(raw["id"],cancel_event=stop_event,repair_dates_by_identity=repairs,on_request=on_request)
    if stop_event.cancelled and progress:
        progress(45,"Cancelling automatic maintenance")
    observed,_=_equity_audit(raw,start,eligible_stop,index,state,now,choose_repairs=False)
    gaps=sum(x["missing_or_partial_sessions"] or 0 for x in observed.values())
    unavailable=sum(x["complete_sessions"] is None for x in observed.values())
    return {"state":"partial" if gaps or unavailable or plan["unresolved"] or eligible_stop<stop or outcome["status"]!="completed" or outcome["errors"] or not observed else "checked",
            "batch_id":raw["id"],"documented_through":info["covered_through"],"requested_end_exclusive":stop.isoformat(),
            "actual_end_exclusive":eligible_stop.isoformat(),"unresolved":plan["unresolved"],"batch_status":outcome["status"],
            "batch_counts":outcome["counts"],"observed_member_session_gaps":gaps,"unavailable_sources":unavailable,
            "members":observed,"repair_dates_attempted":len(attempted),
            "retryable_member_session_gaps":sum(x.get("retryable_sessions",0) for x in observed.values()),
            "batch_errors":bool(outcome["errors"]),
            "provider_rate_limited":any(_rate_limit_message(x.get("code")) or _rate_limit_message(x.get("summary")) for x in outcome.get("failure_examples",[]))}

def _panel_pass(cfg,state,now,stop,progress,should_stop):
    """Optional, independently labeled five-bank watchlist.
    Same canonical original-price files and serialized acquisition lane.
    No fabricated dated-index membership and no new provider credentials.
    """
    from .cpr_context_features import PANEL_SYMBOLS
    start=_local(now).date()-timedelta(days=cfg["constituent_days"])
    rows=dw._choose("watchlist",[],list(PANEL_SYMBOLS))
    identities=sorted((r["symbol"],r["id"]) for r in rows)
    if set(s for s,_ in identities)!=set(PANEL_SYMBOLS):
        return {"state":"blocked","reason":"Exact fixed-panel security identities not resolved"}
    desired=[start.isoformat(),stop.isoformat(),[list(x) for x in identities]]
    raw=None
    if state.get("panel_batch_scope")==desired and state.get("panel_batch_id"):
        try:
            candidate=dw._load_batch(state["panel_batch_id"])
            if (candidate.get("maintenance_panel_owned") and
                candidate["from_date"]==desired[0] and candidate["to_date"]==desired[1] and
                sorted((r["symbol"],r["id"]) for r in candidate["items"])==identities):
                raw=candidate
        except (OSError,ValueError,KeyError):
            pass
    if raw is None:
        summary=dw.create_batch(selection="selected",ids=[key for _,key in identities],tickers=[],
             from_date=desired[0],to_date=desired[1],interval=1,acknowledged_bulk=False,
             include_index_spot=False)
        raw=dw._load_batch(summary["id"])
        raw["maintenance_owned"]=True
        raw["maintenance_panel_owned"]=True
        dw._save_batch(raw)
        state.update(panel_batch_id=raw["id"],panel_batch_scope=desired);_save_state(state)
    # Reuse the minute-coverage audit with the fixed research definition
    # in memory only. The persisted manifest remains a selected watchlist.
    audit={**raw,"historical_index":{"intervals":[{"symbol":s,"valid_from":desired[0],"valid_to":None}
               for s,_ in identities]},"items":[{**r,"pit_symbol":r["symbol"]} for r in raw["items"]]}
    index=mp._history("INDEX:BANKNIFTY",_local(now).date())["days"]
    _,repairs=_equity_audit(audit,start,stop,index,state,now,choose_repairs=True)
    on_request,attempted=_repair_request_callback(state,repairs)
    if should_stop():
        return {"state":"paused","batch_id":raw["id"]}
    outcome=dw.run_batch(raw["id"],cancel_event=_Stop(should_stop,progress),repair_dates_by_identity=repairs,on_request=on_request)
    observed,_=_equity_audit(audit,start,stop,index,state,now,choose_repairs=False)
    gaps=sum(x["missing_or_partial_sessions"] or 0 for x in observed.values())
    unavailable=sum(x["complete_sessions"] is None for x in observed.values())
    return {"state":"partial" if gaps or unavailable or outcome["status"]!="completed" or outcome["errors"] or not observed else "checked",
            "batch_id":raw["id"],"symbols":list(PANEL_SYMBOLS),"requested_end_exclusive":desired[1],
            "actual_end_exclusive":desired[1],"observed_member_session_gaps":gaps,"unavailable_sources":unavailable,
            "members":observed,"repair_dates_attempted":len(attempted),
            "retryable_member_session_gaps":sum(x.get("retryable_sessions",0) for x in observed.values()),
            "batch_status":outcome["status"],"batch_errors":bool(outcome["errors"]),
            "provider_rate_limited":any(_rate_limit_message(x.get("code")) or _rate_limit_message(x.get("summary")) for x in outcome.get("failure_examples",[])),
            "warning":"Fixed research watchlist, not verified BANKNIFTY membership or index attribution."}


def run(*,progress=None,now=None):
    global OPTION_PROGRESS
    now=now or _now();cfg=config()
    if not cfg["enabled"]:
        return {"state":"paused","reason":"Automatic maintenance disabled"}
    during_priority=not safe_window(now)
    with LOCK:
        state=_state()
        OPTION_PROGRESS=None
        if state.get("coverage_config")!=cfg:
            state["coverage_sources"]={} if state.get("coverage_config") else (state.get("last_run") or {}).get("sources",{})
            state["coverage_config"]=cfg
    stop,option_end=target_dates(now)
    report={"started_utc":now.isoformat(),"state":"running","sources":{},
            "backfill_mode":"live_priority" if during_priority else "standard"}
    state.update(target=_target(now),next_due_utc=(now+RETRY).isoformat(),next_due_reason="pass_running",last_run=report,schedule_version=SCHEDULE_VERSION)
    _save_state(state)
    def provider_limited():
        sources=report["sources"]
        lanes=[*sources.get("index",{}).values(),*(v for k,v in sources.items() if k!="index")]
        return any(v.get("provider_rate_limited") or _rate_limit_message(v.get("reason")) for v in lanes)
    def should_stop():
        # Once paused, do not re-enter the same pass if pressure briefly
        # clears. The next scheduled pass rechecks current resources.
        if report.get("pause_reason"):
            return True
        current=_now()
        reason=None
        if STOP.is_set() or config()!=cfg:
            reason="disabled_or_reconfigured"
        elif not recorder_storage.allow("market_maintenance"):
            reason="storage_reserve"
        elif not safe_window(current):
            if not during_priority:
                reason="market_priority_transition"
            else:
                reason=live_pressure(current)
        if reason:
            report["pause_reason"]=reason
        return reason is not None
    try:
        if progress:progress(1,"Checking Dhan connection and shared storage")
        if should_stop():
            report.update(state="paused",reason=report["pause_reason"])
            return report
        profile=dhan_auth.check_profile()
        if not profile.get("ok"):
            report["profile_code"]=profile.get("code") or "profile_unverified"
            if profile.get("code")=="profile_unreachable":
                report.update(state="blocked",reason="Dhan profile connection unavailable; check local network",transient_connection_failure=True)
            elif profile.get("code")=="profile_rate_limited" or (profile.get("code")=="profile_http_error" and _rate_limit_message(profile.get("message"))):
                report.update(state="blocked",reason="Dhan profile rate limit",provider_rate_limited=True,
                              provider_retry_after_seconds=profile.get("provider_retry_after_seconds",0))
            else:
                report.update(state="blocked",reason=job_safety.scrub(
                    profile.get("message") or "Dhan token or historical data permission requires attention",limit=200))
            return report
        if cfg["index"]:
            # Legacy spot sync uses the same guard and yields while the
            # master policy is enabled.
            with mp.HISTORY_WRITE_LOCK:
                report["sources"]["index"]=_index_pass(cfg,state,now,stop,progress,should_stop)
            _save_state(state)
        if cfg["constituents"] and not provider_limited() and not should_stop():
            if progress:progress(30,"Checking dated banking constituents")
            try:
                report["sources"]["constituents"]=_equity_pass(cfg,state,now,stop,progress,should_stop)
            except (ValueError,OSError,RuntimeError,KeyError,TypeError) as exc:
                if progress:progress(49,"Constituent history remains partially unavailable")
                report["sources"]["constituents"]={"state":"blocked","reason":job_safety.scrub(exc)[:200]}
            _save_state(state)
        if cfg["bank_panel"] and not provider_limited() and not should_stop():
            if progress:progress(49,"Checking fixed major-bank research panel")
            try:
                report["sources"]["bank_panel"]=_panel_pass(cfg,state,now,stop,progress,should_stop)
            except (ValueError,OSError,RuntimeError,KeyError,TypeError) as exc:
                report["sources"]["bank_panel"]={"state":"blocked","reason":job_safety.scrub(exc)[:200]}
            _save_state(state)
        if cfg["options"] and not provider_limited() and not should_stop():
            if progress:progress(55,"Checking saved expired-option request windows")
            try:
                option_start=_local(now).date()-timedelta(days=cfg["option_days"])
                # Original observed dates establish download priority, not
                # a complete holiday calendar. Unknown dates remain in scope.
                priority=[]
                try:
                    ix=mp._history("INDEX:BANKNIFTY",_local(now).date())
                    priority=sorted(d for d,bars in ix["days"].items()
                                    if bars and option_start.isoformat()<=d<=option_end.isoformat())
                except (ValueError,OSError,RuntimeError,KeyError,TypeError):
                    pass
                def on_counts(counts):
                    global OPTION_PROGRESS
                    with LOCK:
                        OPTION_PROGRESS=dict(counts)
                opt=options.run(start_date=option_start.isoformat(),
                    end_date=option_end.isoformat(),wings=cfg["wings"],request_limit=LIVE_OPTION_REQUESTS if during_priority else MAX_OPTION_REQUESTS,
                    priority_sessions=priority,on_counts=on_counts,pipeline=not during_priority,
                    should_stop=should_stop,progress=(lambda pct,msg:progress(55+.44*pct,msg)) if progress else None)
                report["sources"]["options"]={k:opt[k] for k in ("state","existing_verified_receipts","new_receipts",
                    "planned_missing_requests","unattempted_requests","empty_processed_receipts","usable_rows_in_processed_receipts",
                    "unreadable_receipts_encountered","excluded_active_calendar_days","continuous_coverage_certified",
                    "empty_verified_receipts","observed_rolling_minute_slots","observed_offset_session_pairs","observed_session_dates")}
                report["sources"]["options"].update({k:opt[k] for k in ("eligible_offset_date_pairs","checked_offset_date_pairs",
                    "missing_offset_date_pairs","remaining_planned_requests","batch_limit","batch_attempted","batch_completed",
                    "scope_start","scope_end","scope_wings","known_observed_minute_slots","known_expected_minute_slots","known_market_dates",
                    "active_receipts_per_minute") if k in opt})
                report["sources"]["options"]["coverage_as_of"]=_now().isoformat()
                report["sources"]["options"]["rejected_windows"]=len(opt["rejected_requests"])
                report["sources"]["options"]["state"]="partial" if opt["state"]=="partial_requests" or opt["unreadable_receipts_encountered"] else "checked"
            except (ValueError,OSError,RuntimeError,KeyError,TypeError) as exc:
                if progress:progress(99,"Option history remains partially unavailable")
                if isinstance(exc,options.exp.RollingConnectionError):
                    report["transient_connection_failure"]=True
                if isinstance(exc,options.exp.RollingRateLimitError):
                    report["provider_rate_limited"]=True
                    report["provider_retry_after_seconds"]=exc.retry_after_seconds
                prior=state.get("coverage_sources",{}).get("options",{})
                if OPTION_PROGRESS is not None:
                    evidence={**OPTION_PROGRESS,"coverage_as_of":_now().isoformat()}
                elif prior.get("scope_start")==option_start.isoformat() and prior.get("scope_end")==option_end.isoformat() and prior.get("scope_wings")==cfg["wings"]:
                    evidence={**prior,"progress_stale":True,"active_receipts_per_minute":None}
                else:
                    evidence={}
                report["sources"]["options"]={**evidence,"state":"blocked","reason":job_safety.scrub(exc)[:200]}
        states=[v["state"] for k,v in report["sources"].items() if k!="index"]
        states.extend(v["state"] for v in report["sources"].get("index",{}).values())
        report["state"]="paused" if should_stop() else "partial" if not states or any(x!="checked" for x in states) else "checked"
        if report["state"]=="paused":
            report["reason"]=report.get("pause_reason","maintenance_paused")
        if progress:progress(100,"Automatic maintenance pass saved")
        return report
    finally:
        if report["state"]=="running":report["state"]="interrupted"
        finished=_now()
        report["finished_utc"]=finished.isoformat()
        if report.get("transient_connection_failure"):
            # A successful receipt followed by a disconnect is new progress,
            # not another consecutive zero-progress failure.
            prior_count=state.get("connection_failure_count",0)
            progress_made=report.get("sources",{}).get("options",{}).get("new_receipts",0)
            if report.get("sources",{}).get("options",{}).get("progress_stale"):
                progress_made=0
            count=1 if progress_made else min(len(CONNECTION_RETRY_MINUTES),prior_count+1)
            report["connection_failure_count"]=count
            state["connection_failure_count"]=count
        elif report.get("sources",{}).get("options",{}).get("state") in ("checked","partial") or report["state"]=="checked":
            state["connection_failure_count"]=0
        delay,reason=_next_schedule(report)
        state["next_due_utc"]=(finished+delay).isoformat()
        state["next_due_reason"]=reason
        state["schedule_version"]=SCHEDULE_VERSION
        with LOCK:
            # Preserve a concurrently saved request to disable/reconfigure;
            # its new settings take effect at the next safe boundary.
            OPTION_PROGRESS=None
            if config()!=cfg:
                state["target"]=None
                if reason!="provider_rate_limit":
                    state["next_due_utc"]=None;state["next_due_reason"]="configuration_changed"
                state.pop("coverage_sources",None);state.pop("coverage_config",None)
                state.pop("connection_failure_count",None)
            else:
                state["coverage_sources"]={**state.get("coverage_sources",{}),**report["sources"]}
                state["coverage_config"]=cfg
            state["last_run"]=report
            _save_state(state)

def _worker(submit):
    while not STOP.is_set():
        # Clear before reading the checkpoint so a wake arriving during a
        # scheduling check cannot be lost at the end of the iteration.
        WAKE.clear()
        try:
            with LOCK:
                cfg=config();state=_state()
            if _due(cfg,state,_now()):
                submit()
        except (OSError,ValueError,TypeError,RuntimeError):
            pass
        WAKE.wait(30)

def start(submit):
    global THREAD
    with LOCK:
        if THREAD and THREAD.is_alive():return
        STOP.clear()
        THREAD=Thread(target=_worker,args=(submit,),daemon=True,name="market-library-maintenance")
        THREAD.start()

def shutdown():
    STOP.set();WAKE.set()
