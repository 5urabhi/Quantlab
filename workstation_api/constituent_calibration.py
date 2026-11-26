"""Predeclared empirical probability validation for the frozen prospective ledger.

First 30 completed recorded sessions = development; next 20 = untouched
chronological assessment. No replacements, tuning, backfilled calls or ML.
The cohort is conditional on directional, verifiable outcomes and actual calls.
"""
from contextlib import closing
from datetime import datetime
import sqlite3
from . import constituent_prospective as p, live_market, market_inventory, shared_market_data

TRAIN_SESSIONS=30
HOLDOUT_SESSIONS=20
MIN_TRAIN=100
MIN_HOLDOUT=50
VERSION="paired-empirical-reliability-v1"


def evaluate(train,holdout):
    results={}
    for method in p.METHODS:
        rows=[r for r in train if r[method] in ("UP","DOWN") and r["outcome"] in ("UP","DOWN")]
        test=[r for r in holdout if r[method] in ("UP","DOWN") and r["outcome"] in ("UP","DOWN")]
        groups={}
        sufficient=True
        for direction in ("UP","DOWN"):
            a=[r for r in rows if r[method]==direction]
            b=[r for r in test if r[method]==direction]
            training_days=len({r["session_ist"] for r in a})
            test_days=len({r["session_ist"] for r in b})
            supported=len(a)>=MIN_TRAIN and len(b)>=MIN_HOLDOUT and training_days>=15 and test_days>=10
            sufficient=sufficient and supported
            groups[direction]={"training_calls":len(a),"holdout_calls":len(b),"training_sessions":training_days,
                              "holdout_sessions":test_days,"candidate_up_probability":None,"holdout_up_frequency":None,"absolute_error":None}
            if supported:
                candidate=(1+sum(r["outcome"]=="UP" for r in a))/(len(a)+2)
                observed=sum(r["outcome"]=="UP" for r in b)/len(b)
                groups[direction].update(candidate_up_probability=candidate,holdout_up_frequency=observed,absolute_error=abs(candidate-observed))
        out={"state":"insufficient_support","groups":groups,"brier":None,"base_brier":None,"brier_skill":None,
             "expected_calibration_error":None,"probability_by_call":None}
        if sufficient:
            base=(1+sum(r["outcome"]=="UP" for r in rows))/(len(rows)+2)
            loss=sum((groups[r[method]]["candidate_up_probability"]-int(r["outcome"]=="UP"))**2 for r in test)/len(test)
            base_loss=sum((base-int(r["outcome"]=="UP"))**2 for r in test)/len(test)
            error=sum(v["holdout_calls"]*v["absolute_error"] for v in groups.values())/len(test)
            passed=base_loss>0 and loss<base_loss and all(v["absolute_error"]<=.10 for v in groups.values())
            out.update(state="passes_predeclared_descriptive_gate" if passed else "fails_predeclared_gate",brier=loss,
                       base_brier=base_loss,brier_skill=1-loss/base_loss if base_loss>0 else None,expected_calibration_error=error,
                       probability_by_call={k:v["candidate_up_probability"] for k,v in groups.items()} if passed else None)
        results[method]=out
    return results


def report(horizon=5):
    if horizon not in p.HORIZONS:
        raise ValueError("Choose an approved horizon")
    response={"version":VERSION,"protocol_sha256":p.PROTOCOL_HASH,"horizon_minutes":horizon,
              "required_training_sessions":TRAIN_SESSIONS,"required_holdout_sessions":HOLDOUT_SESSIONS,
              "observed_sessions":0,"state":"awaiting_sessions","training_dates":[],"holdout_dates":[],"methods":{},
              "note":"Fixed first 30 completed recorded sessions followed by the next 20, without replacing unsupported days. Empirical probabilities are conditional on actual rule calls and non-flat verifiable index outcomes; they are not unconditional market forecasts. Minimum 100 training/50 holdout calls and 15/10 sessions per direction. Descriptive gate: better Brier score than the frozen training base rate and absolute error ≤10 percentage points in each call group. A pass is not a statistical guarantee, proof of alpha or authorization to trade."}
    if not market_inventory._safe_file(shared_market_data.database_path()):
        return response
    today=datetime.now(live_market.IST).date().isoformat()
    with closing(p._read()) as db:
        db.row_factory=sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(p.TABLE,)).fetchone():
            return response
        days=[r[0] for r in db.execute("""SELECT DISTINCT session_ist FROM banknifty_paired_signals
            WHERE protocol_hash=? AND horizon_minutes=? AND session_ist<?
            ORDER BY session_ist LIMIT 50""",(p.PROTOCOL_HASH,horizon,today))]
        response["observed_sessions"]=len(days)
        response["training_dates"]=days[:30]
        response["holdout_dates"]=days[30:]
        if len(days)<50:
            return response
        rows=[dict(r) for r in db.execute("""SELECT session_ist,pressure,volume_pressure,ema_rsi,outcome
            FROM banknifty_paired_signals WHERE protocol_hash=? AND horizon_minutes=? AND session_ist>=? AND session_ist<=?
            ORDER BY slot_utc LIMIT 20001""",(p.PROTOCOL_HASH,horizon,days[0],days[-1]))]
    if len(rows)>20000:
        response["state"]="bounded_read_exceeded"
        return response
    if any(r["outcome"]=="PENDING" for r in rows):
        response["state"]="awaiting_pending_labels"
        return response
    train=[r for r in rows if r["session_ist"] in set(days[:30])]
    test=[r for r in rows if r["session_ist"] in set(days[30:])]
    response.update(state="chronological_assessment_available",methods=evaluate(train,test))
    return response
