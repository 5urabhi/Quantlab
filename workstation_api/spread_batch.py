"""Bounded batch exploration and frozen later-session research validation.

Only local result summaries and immutable plan manifests are written. The
shared market library stays read-only; real broker orders are never sent.
"""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import date, datetime, time
from hashlib import sha256
from pathlib import Path
from threading import Event
import csv
import json
import os
import re
import uuid

from . import depth_replay as replay, paper_execution as paper, service
from . import spread_batch_core as core, spread_speed as speed

VERSION="batch_depth_research_v1"
TOP_PER_COHORT=25
FAMILIES=("directional","spread")
COHORTS=("fixed","signal")
WARNING=("In-sample exploration; not a strategy profitability claim. Scored P&L is "
    "conditional on the first saved marketable books after assumed reaction delays. "
    "Missing paths are unscored, not zero returns. Fixed-clock windows may overlap; "
    "the random control has the same number of attempted source-valid anchors, not "
    "necessarily the same completed trades. Ranking uses a descriptive lower-block "
    "statistic, not a confidence bound or significance test. No actual fills, broker "
    "latency, margin, legging or passive queue fill probabilities are verified.")
CSV_METRICS=("attempted","scored","unscored","completion_pct","entry_complete",
    "profitable","losing","target_hits","mean_net","total_net","worst_net",
    "mean_fees","scored_blocks","lower_block_mean","robust_score","rankable","states")
CSV_FIELDS=("family","cohort","strategy","identities","legs","direction","lots",
    "latency_ms","hold_seconds","selection_coverage_pct",*CSV_METRICS,
    *("random_"+k for k in CSV_METRICS),"signal_minus_random_mean","random_overlap_attempts")


def _root():
    root=service.DATA/"research_workspace"/"speed_batch"
    root.mkdir(parents=True,exist_ok=True)
    return root


def _canonical(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()


def result_path(run_id):
    if not re.fullmatch(r"[a-f0-9]{32}",run_id):
        raise ValueError("Invalid batch result identifier")
    path=_root()/("run-"+run_id+".csv")
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError("Batch result not found")
    return path


def _plan_path(plan_id):
    if not re.fullmatch(r"[a-f0-9]{64}",plan_id):
        raise ValueError("Invalid frozen plan identifier")
    return _root()/("plan-"+plan_id+".json")


def load_plan(plan_id):
    path=_plan_path(plan_id)
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError("Frozen plan not found")
    raw=path.read_bytes()
    if sha256(raw).hexdigest()!=plan_id:
        raise ValueError("Frozen plan digest does not match")
    plan=json.loads(raw)
    if plan.get("version")!=VERSION:
        raise ValueError("Frozen plan requires its original research policy version")
    return plan


def _freeze(plan):
    raw=_canonical(plan)
    plan_id=sha256(raw).hexdigest()
    path=_plan_path(plan_id)
    if path.exists():
        load_plan(plan_id)
    else:
        temp=path.with_name(path.name+"."+uuid.uuid4().hex+".tmp")
        try:
            with temp.open("xb") as f:
                f.write(raw)
            # Atomic publish without replacing any existing frozen manifest.
            try:
                os.link(temp,path)
            except FileExistsError:
                load_plan(plan_id)
        finally:
            temp.unlink(missing_ok=True)
    return plan_id


def list_plans():
    rows=[]
    for path in sorted(_root().glob("plan-*.json"),key=lambda p:p.stat().st_mtime,reverse=True)[:30]:
        try:
            plan_id=path.stem.removeprefix("plan-")
            plan=load_plan(plan_id)
            rows.append({"plan_id":plan_id,"discovery_day":plan["discovery_day"],
                         "frozen_utc":plan["frozen_utc"],"configuration_count":len(plan["configurations"]),
                         "earliest_expiry":min(leg["expiry"] for pick in plan["configurations"]
                                               for leg in pick["legs"])})
        except (OSError,ValueError,KeyError,TypeError):
            continue
    return rows


def _settings(capital,max_lots,target_net,window_seconds,step_minutes,participation_pct,
              slippage_bps,broker_profile,expiry,side,search,include_spreads):
    for value,lo,hi,label in ((capital,1000,1e7,"capital"),(target_net,0,1e6,"target"),
        (participation_pct,1,100,"participation"),(slippage_bps,0,500,"slippage")):
        paper._check(value,lo,hi,label)
    if type(max_lots) is not int or not 1<=max_lots<=3:
        raise ValueError("Batch comparisons support one to three maximum lots")
    if type(window_seconds) is not int or not 1<=window_seconds<=30:
        raise ValueError("Choose a 1–30 second receipt window")
    if step_minutes not in (1,5,15):
        raise ValueError("Choose 1, 5 or 15 minute anchor spacing")
    if broker_profile not in replay.fees.BROKER_PROFILES:
        raise ValueError("Unknown broker fee profile")
    if side not in ("ALL","CE","PE") or len(search)>80:
        raise ValueError("Invalid option filter")
    if expiry and date.fromisoformat(expiry).isoformat()!=expiry:
        raise ValueError("Choose an ISO expiry")
    if type(include_spreads) is not bool:
        raise ValueError("Choose whether to include verticals")
    return dict(capital=capital,max_lots=max_lots,target_net=target_net,window_seconds=window_seconds,
        step_minutes=step_minutes,participation_pct=participation_pct,slippage_bps=slippage_bps,
        max_skew_seconds=2.,broker_profile=broker_profile,expiry=expiry,side=side,search=search,
        include_spreads=include_spreads)


def _csv_row(row):
    out={k:row.get(k) for k in CSV_FIELDS if not k.startswith("random_")}
    out["identities"]=" / ".join(row["identities"])
    out["legs"]=json.dumps(row["legs"],sort_keys=True,separators=(",",":"))
    out["states"]=json.dumps(row["states"],sort_keys=True,separators=(",",":"))
    out["random_overlap_attempts"]=row.get("random_overlap_attempts")
    control=row.get("random_control") or {}
    for k in CSV_METRICS:
        out["random_"+k]=json.dumps(control[k],sort_keys=True,separators=(",",":")) if k=="states" and k in control else control.get(k)
    return out


def _task_groups(tasks,cfg,day,anchors,directions,now,workers,progress,consume):
    """One bounded pool, no nested replay pools; keep only completed groups."""
    if not tasks:
        return
    stop=Event()
    pending={}
    next_index=0
    completed=0
    pool=ThreadPoolExecutor(max_workers=workers,thread_name_prefix="batch-depth")
    try:
        while next_index<len(tasks) or pending:
            while next_index<len(tasks) and len(pending)<workers:
                group,specs,cohorts=tasks[next_index]
                future=pool.submit(core.evaluate,group,specs,cfg,day,anchors,directions,now,stop,cohorts)
                pending[future]=next_index
                next_index+=1
            done,_=wait(tuple(pending),timeout=.4,return_when=FIRST_COMPLETED)
            for future in sorted(done,key=lambda f:pending[f]):
                pending.pop(future)
                consume(future.result())
                completed+=1
            if progress:
                progress(10+85*completed/len(tasks),
                    f"Batch replay: {completed}/{len(tasks)} structures complete; {workers} adaptive workers")
    finally:
        stop.set()
        pool.shutdown(wait=True,cancel_futures=True)


def _execute(tasks,cfg,day,now,progress,*,validation=False):
    if progress:
        progress(9,"Reconstructing causal index signals from original received ticks")
    anchors=speed._anchors(day,now,max(speed.LATENCIES_MS),cfg["window_seconds"],cfg["step_minutes"])
    directions,signal=core.signal_cohorts(day,anchors,now)
    workers=speed._worker_count(len(tasks)) if tasks else 0
    # No nested pools; original-book lookups are reused across sizes and holds.
    counts={family:{cohort:{"rows":0,"rankable":0,"positive_robust":0} for cohort in COHORTS} for family in FAMILIES}
    top={family:{cohort:[] for cohort in COHORTS} for family in FAMILIES}
    freeze={}
    validation_rows=[]
    run_id=uuid.uuid4().hex
    final=_root()/("run-"+run_id+".csv")
    temp=final.with_suffix(".tmp")
    rows_written=0
    try:
        with temp.open("x",newline="",encoding="utf-8") as f:
            writer=csv.DictWriter(f,fieldnames=CSV_FIELDS)
            writer.writeheader()
            def consume(rows):
                nonlocal rows_written
                local={}
                for row in rows:
                    writer.writerow(_csv_row(row));rows_written+=1
                    family,cohort=row["family"],row["cohort"]
                    bucket=counts[family][cohort]
                    bucket["rows"]+=1;bucket["rankable"]+=int(row["rankable"])
                    if row["rankable"] and row["robust_score"]>0:
                        bucket["positive_robust"]+=1
                    if validation:
                        validation_rows.append(row)
                        continue
                    local.setdefault((family,cohort),[]).append(row)
                    if core.can_freeze(row):
                        old=freeze.get((family,cohort))
                        if old is None or core.rank_key(row)<core.rank_key(old):
                            freeze[family,cohort]=row
                # Streaming top-k, not all paths/configurations in RAM.
                for (family,cohort),rows in local.items():
                    top[family][cohort]=sorted(top[family][cohort]+rows,key=core.rank_key)[:TOP_PER_COHORT]
            _task_groups(tasks,cfg,day,anchors,directions,now,workers,progress,consume)
        if progress:
            progress(96,"Finalizing batch summary CSV")
        os.replace(temp,final)
    finally:
        temp.unlink(missing_ok=True)
    result={"run_id":run_id,"day_ist":day.isoformat(),"cutoff_utc":paper._iso(now),
        "settings":cfg,"worker_count":workers,"anchor_count":len(anchors),"signal":signal,
        "structures":len(tasks),"configuration_count":sum(len(t[1]) for t in tasks),
        "attempted_paths":len(anchors)*sum(len(t[1]) for t in tasks),
        "summary_rows":rows_written,"counts":counts,"rankings":top,
        "thresholds":{"min_scored":core.MIN_SCORED,"min_completion_pct":100*core.MIN_COMPLETION,
                      "min_scored_blocks":core.MIN_BLOCKS,"block_minutes":core.BLOCK_MINUTES},
        "validation_rows":sorted(validation_rows,key=lambda r:(r["family"],r["cohort"],r["strategy"],r["identities"])),
        "actual_fills_observed":False,"broker_orders_enabled":False,"broker_margin_verified":False,
        "warning":WARNING}
    return result,freeze


def run(*,day,capital=17000.,max_lots=3,target_net=100.,window_seconds=1,
        step_minutes=5,participation_pct=25.,slippage_bps=5.,broker_profile="zerodha",
        expiry="",side="ALL",search="",include_spreads=True,progress=None,now=None):
    # Single cutoff is taken before screening. Later recordings are not
    # consumed by this study; source files must remain unchanged during it.
    cutoff=now or paper._now()
    chosen=date.fromisoformat(day)
    if chosen>cutoff.astimezone(paper.IST).date() or chosen.weekday()>=5:
        raise ValueError("Choose an observed weekday session")
    cfg=_settings(capital,max_lots,target_net,window_seconds,step_minutes,participation_pct,
                  slippage_bps,broker_profile,expiry,side,search,include_spreads)
    if progress:
        progress(0,"Screening the recorded option universe")
    groups,universe=core.universe(day,cfg,cutoff,progress)
    tasks=[(group,[(n,d,h) for n in group["lot_options"] for d in speed.LATENCIES_MS
                 for h in speed.HORIZONS],COHORTS) for group in groups]
    result,freeze=_execute(tasks,cfg,chosen,cutoff,progress)
    result.update(mode="exploration",universe=universe,plan_id=None,frozen_configurations=[])
    if freeze:
        # Freeze at actual completion, not the selected historical date or
        # research cutoff. Validation must be a strictly later IST session.
        frozen_at=now or paper._now()
        if progress:
            progress(98,"Freezing qualifying research configurations")
        picks=[{k:row[k] for k in ("family","cohort","strategy","identities","legs",
                "direction","selection_coverage_pct","lots","latency_ms","hold_seconds")}
               for _,row in sorted(freeze.items())]
        plan={"version":VERSION,"source_run_id":result["run_id"],"discovery_day":day,
              "frozen_utc":paper._iso(frozen_at),"settings":cfg,"configurations":picks}
        result.update(plan_id=_freeze(plan),frozen_configurations=picks,frozen_utc=plan["frozen_utc"])
    if progress:
        progress(100,"All eligible batch configurations evaluated")
    return result


def validate(*,plan_id,day,progress=None,now=None):
    cutoff=now or paper._now()
    plan=load_plan(plan_id)
    chosen=date.fromisoformat(day)
    frozen=replay.ao.timestamp(plan["frozen_utc"])
    if chosen<=max(date.fromisoformat(plan["discovery_day"]),frozen.astimezone(paper.IST).date()):
        raise ValueError("Validation must be a strictly later session than the frozen plan")
    close=datetime.combine(chosen,time(15,30),paper.IST)
    if chosen.weekday()>=5 or cutoff<close:
        raise ValueError("Choose a completed later weekday session")
    cfg=plan["settings"]
    tasks=[]
    for pick in plan["configurations"]:
        group={k:pick[k] for k in ("family","strategy","identities","legs","direction")}
        group["coverage_pct"]=pick["selection_coverage_pct"]
        specs=[(pick["lots"],pick["latency_ms"],pick["hold_seconds"])]
        tasks.append((group,specs,(pick["cohort"],)))
    result,_=_execute(tasks,cfg,chosen,cutoff,progress,validation=True)
    # No reselection, no re-ranking, no new plan, including expired contracts
    # and missing paths. Validation remains conditional paper evidence.
    result.update(mode="validation",plan_id=plan_id,frozen_configurations=plan["configurations"],
        frozen_utc=plan["frozen_utc"],discovery_day=plan["discovery_day"])
    if progress:
        progress(100,"Frozen later-session validation complete")
    return result
