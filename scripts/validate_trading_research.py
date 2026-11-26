"""Bounded off-hours validation of locally saved BANKNIFTY research evidence.

This is NOT an execution test or a parameter optimization. It writes only
research outputs and reads existing original source receipts. Never launches
recorders, requests provider data, authenticates to a broker, or places orders.
"""
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
from math import isfinite
from pathlib import Path
from zoneinfo import ZoneInfo
import argparse
import json
import os
import re
import sqlite3
import uuid

from workstation_api import (
    advanced_options, alpha_model_registry, alpha_retraining, auto_paper_engine,
    constituent_alpha, dynamic_strategy_research, forecast_depth_research,
    replay_storage, shared_market_data, trading_acceptance, volatility_evidence,
)

IST = ZoneInfo("Asia/Kolkata")
MAX_REPLAY_DAYS = 3
MAX_MONITORS = 5
HORIZONS = (5, 15, 30, 60)
TIMINGS = ("decision_processing_ms", "conditional_entry_receipt_delay_ms",
           "conditional_exit_receipt_delay_ms")


def completed_days(now, count):
    """Choose calendar-ordered dates by original tick presence, not P&L."""
    if not shared_market_data.database_path().is_file():
        return []
    local = now.astimezone(IST)
    # Same-day replay is permitted only after market priority ends.
    stop = local.date() + timedelta(days=int(local.time() >= time(16)))
    first = stop - timedelta(days=30)
    lo = datetime.combine(first, time.min, IST).astimezone(timezone.utc)
    hi = datetime.combine(stop, time.min, IST).astimezone(timezone.utc)
    with closing(advanced_options._read_database()) as db:
        if not replay_storage.fetchone(db, "SELECT 1 FROM sqlite_master WHERE type='table' AND name='live_ticks'"):
            return []
        rows = replay_storage.fetchall(db, """SELECT DISTINCT substr(exchange_utc,1,10)
            FROM live_ticks WHERE identity='INDEX:BANKNIFTY' AND exchange_utc>=? AND exchange_utc<?
            ORDER BY 1 DESC LIMIT 30""", (lo.isoformat(), hi.isoformat()))
    # Indian regular hours always fall within the same UTC calendar date.
    days = [date.fromisoformat(r[0]) for r in rows]
    return sorted(d.isoformat() for d in days if first <= d < stop and d.weekday()<5)[-count:]


def _percentile(values, q):
    vals = sorted(values)
    position = (len(vals)-1)*q
    i = int(position)
    return vals[i] + (vals[min(i+1,len(vals)-1)]-vals[i])*(position-i)


def local_timing_evidence():
    """Summarize recorded paper processing/receipt delays, never broker fills."""
    path = auto_paper_engine._path()
    if not path.is_file() or path.is_symlink():
        return {"state":"no_paper_journal", "rows_examined":0, "metrics":{},
                "actual_broker_latency_verified":False}
    with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro", uri=True, timeout=3)) as db:
        db.execute("PRAGMA query_only=ON")
        if not replay_storage.fetchone(db, "SELECT 1 FROM sqlite_master WHERE type='table' AND name='decisions'"):
            return {"state":"no_paper_journal", "rows_examined":0, "metrics":{},
                    "actual_broker_latency_verified":False}
        records = replay_storage.fetchall(db, "SELECT state,body FROM decisions ORDER BY id DESC LIMIT 5001")
    metrics = {key:[] for key in TIMINGS}
    malformed = 0
    for state, raw in records[:5000]:
        try:
            row = json.loads(raw)
            if not isinstance(row, dict):
                raise ValueError("invalid row")
        except (ValueError,TypeError):
            malformed += 1
            continue
        for key in TIMINGS:
            if key != TIMINGS[0] and state == "no_trade":
                continue
            value = row.get(key)
            if type(value) in (int,float) and isfinite(value) and value >= 0:
                metrics[key].append(float(value))
    return {"state":"local_timing_available" if any(metrics.values()) else "awaiting_instrumented_paper_decisions",
            "rows_examined":min(len(records),5000), "sample_truncated":len(records)>5000,
            "malformed_rows":malformed, "metrics":{
                k:{"n":len(v),"p50_ms":_percentile(v,.5),"p95_ms":_percentile(v,.95),"max_ms":max(v)}
                if v else {"n":0,"p50_ms":None,"p95_ms":None,"max_ms":None}
                for k,v in metrics.items()},
            "actual_broker_latency_verified":False,
            "warning":"Recorded local processing and conditional receipt delay only. "
                      "The processing sample includes no-trade decisions. Missing or older timing fields are not zero. "
                      "No exchange order acknowledgement or broker fill was observed."}


def _report_path():
    root = Path("results")
    root.mkdir(exist_ok=True)
    return root/("trading_validation_"+datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                 +"_"+uuid.uuid4().hex[:8]+".json")


def _save(path, report):
    tmp = path.with_name("."+path.name+"."+uuid.uuid4().hex+".tmp")
    try:
        with tmp.open("x",encoding="utf-8") as f:
            json.dump(report,f,indent=2,sort_keys=True,allow_nan=False)
            f.write("\n")
        os.replace(tmp,path)
    finally:
        tmp.unlink(missing_ok=True)


def run(*, days=None, sessions=1, horizon=15, model_ids=None, iv_days=60,
        capital=17000., max_loss=4250., max_lots=3, hold_seconds=900,
        output=None, progress=None, now=None):
    fixed_clock = now is not None  # deterministic offline tests only
    now = now or datetime.now(timezone.utc)
    if not alpha_retraining.safe_window(now):
        raise ValueError("Run validation outside Indian market priority hours (08:30–16:00 IST on weekdays)")
    if type(sessions) is not int or not 1<=sessions<=MAX_REPLAY_DAYS:
        raise ValueError("Choose one to three recorded replay sessions")
    if horizon not in HORIZONS or type(iv_days) is not int or not 1<=iv_days<=120:
        raise ValueError("Unsupported horizon or IV window")
    if not all(type(v) in (int,float) and isfinite(v) for v in (capital,max_loss)) or not 1000<=capital<=1e7 or not 0<max_loss<=capital:
        raise ValueError("Invalid paper capital or session loss allowance")
    if type(max_lots) is not int or not 1<=max_lots<=3 or hold_seconds not in (60,120,300,600,900,1800):
        raise ValueError("Unsupported lot count or maximum hold")
    model_ids = list(model_ids or [])
    if len(model_ids)>MAX_MONITORS or len(model_ids)!=len(set(model_ids)) or any(not re.fullmatch(r"[a-f0-9]{64}",m) for m in model_ids):
        raise ValueError("Choose up to five unique frozen model IDs")
    if days is not None:
        days = sorted(set(days))
        local=now.astimezone(IST)
        last=local.date() if local.time()>=time(16) else local.date()-timedelta(days=1)
        if not 1<=len(days)<=MAX_REPLAY_DAYS or any(date.fromisoformat(d)>last or date.fromisoformat(d).weekday()>=5 for d in days):
            raise ValueError("Choose one to three completed weekday dates")
    path = Path(output) if output is not None else _report_path()
    report={"version":"local_trading_validation_v1","started_utc":now.isoformat(),
            "settings":{"horizon_minutes":horizon,"requested_replay_dates":days,
                        "recent_sessions":sessions,"iv_calendar_days":iv_days,"capital_inr":capital,
                        "session_loss_allowance_inr":max_loss,"max_lots":max_lots,"hold_seconds":hold_seconds},
            "stages":{},"broker_orders_enabled":False,"external_provider_requests_enabled":False,
            "actual_broker_margin_verified":False,"actual_broker_latency_verified":False,
            "prospective_profitability_certified":False,"rl_policy_independently_validated":False,
            "warning":"Local source-based research only; no results are live execution or prospective profitability certification."}
    _save(path,report)
    def emit(message):
        if progress:
            progress(message)
    def stage(name, fn):
        # Recheck wall-clock priority between tasks; current work is bounded
        # by each underlying engine's read limits.
        if not alpha_retraining.safe_window(now if fixed_clock else datetime.now(timezone.utc)):
            report["stages"][name]={"state":"paused_market_priority"}
            _save(path,report)
            return None
        emit(name+" ...")
        try:
            result=fn()
            report["stages"][name]={"state":"completed","result":result}
        except (ValueError,OSError,RuntimeError,sqlite3.Error,TypeError,KeyError,OverflowError) as exc:
            # Do not serialize arbitrary exception strings that could include
            # local file paths or credentials. A failed stage never passes.
            report["stages"][name]={"state":"error","error_type":type(exc).__name__}
            result=None
        _save(path,report)
        emit(name+": "+report["stages"][name]["state"])
        return result
    stage("stored_depth_integrity",trading_acceptance.inspect_saved_books)
    if days is None:
        days = stage("replay_date_inventory",lambda:completed_days(now,sessions))
    report["selected_replay_dates"]=days or []
    _save(path,report)
    for day in days or []:
        stage("reversal_replay_"+day,lambda day=day:dynamic_strategy_research.run(
            day=day,capital=capital,max_loss=max_loss,max_lots=max_lots,hold_seconds=hold_seconds,
            broker_profile="zerodha",include_spreads=True,compare_entry_profiles=False,now=now))
    if not days:
        report["stages"]["reversal_replay"]={"state":"not_run","reason":"no_selected_completed_dates"}
    status=stage("prospective_readiness",lambda:constituent_alpha.readiness(horizon,now=now))
    if status and status["recorded_sessions"]==status["required_sessions"]:
        stage("forecast_depth_replay",lambda:forecast_depth_research.run(
            horizon=horizon,capital=capital,max_loss=max_loss,max_lots=max_lots,include_credit=False))
    else:
        report["stages"]["forecast_depth_replay"]={"state":"not_run","reason":"insufficient_or_unavailable_recorded_sessions"}
    today=now.astimezone(IST).date()
    stage("chronological_iv_assessment",lambda:volatility_evidence.iv_run(
        from_date=(today-timedelta(days=iv_days)).isoformat(),to_date=today.isoformat(),horizon=horizon))
    if not model_ids:
        registry=stage("frozen_candidate_inventory",alpha_model_registry.list_candidates)
        eligible=[m["model_id"] for m in (registry or []) if m["source"]=="prospective"
                  and m["horizon_minutes"]==horizon and max(m["reference_holdout_dates"])<today.isoformat()]
        # Registry order is version recency, never holdout performance.
        model_ids=eligible[:MAX_MONITORS]
        report["eligible_candidates_in_bounded_registry"]=len(eligible)
        report["unmonitored_candidates_in_bounded_registry"]=max(0,len(eligible)-MAX_MONITORS)
    report["monitored_model_ids"]=model_ids
    for ident in model_ids:
        stage("frozen_monitor_"+ident,lambda ident=ident:alpha_model_registry.monitor(model_id=ident,now=now))
    if not model_ids:
        report["stages"]["frozen_monitor"]={"state":"not_run","reason":"no_eligible_frozen_candidates"}
    stage("paper_timing",local_timing_evidence)
    report["finished_utc"]=datetime.now(timezone.utc).isoformat()
    report["state"]="stage_errors" if any(v["state"]=="error" for v in report["stages"].values()) else "assessment_saved"
    if any(v["state"]=="paused_market_priority" for v in report["stages"].values()):
        report["state"]="paused_market_priority"
    _save(path,report)
    return path,report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day",action="append",help="Completed IST replay date; repeat up to three times")
    parser.add_argument("--sessions",type=int,default=1,help="Recent observed replay sessions if no --day")
    parser.add_argument("--horizon",type=int,choices=HORIZONS,default=15)
    parser.add_argument("--iv-days",type=int,default=60)
    parser.add_argument("--model-id",action="append",help="Monitor an explicitly chosen immutable candidate; repeat up to five times")
    parser.add_argument("--capital",type=float,default=17000.)
    parser.add_argument("--max-loss",type=float,default=4250.)
    parser.add_argument("--max-lots",type=int,default=3)
    parser.add_argument("--hold-seconds",type=int,default=900)
    args=parser.parse_args()
    try:
        path,report=run(days=args.day,sessions=args.sessions,horizon=args.horizon,
                        model_ids=args.model_id,iv_days=args.iv_days,capital=args.capital,
                        max_loss=args.max_loss,max_lots=args.max_lots,hold_seconds=args.hold_seconds,
                        progress=lambda s:print(s,flush=True))
    except (ValueError,OSError) as exc:
        print("Validation could not start: "+type(exc).__name__)
        return 2
    print("Verdict:",report["state"])
    print("Report:",path.resolve())
    print("Actual broker margin, latency, P&L and independently validated RL: NOT CERTIFIED")
    return 0 if report["state"]=="assessment_saved" else 2


if __name__=="__main__":
    raise SystemExit(main())
