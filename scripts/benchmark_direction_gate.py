"""Fixed five-year material-direction benchmark; no order or option P&L.

Reuse the verified index receipt loader, existing three-class direction
protocol and day-block diagnostics. This is a retrospective qualification
attempt, NOT a live trade recommendation.
"""
import argparse
import csv
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import uuid

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from workstation_api import banknifty_candle_forecast as m
from workstation_api import constituent_alpha as a
from workstation_api import cpr_hybrid_research as r
from workstation_api import historical_alpha as h
from workstation_api import service
from scripts.run_banknifty_candle_forecast import write_atomic

VERSION="direction_gate_v1"
HORIZON=5
DELAY=1
LOOKBACK=16
DEADBAND_BPS=5.
CONFIDENCE=.60
PROXY_COST_BPS=5.
MIN_CALLS=100
MIN_CALL_DAYS=30
TEMPERATURES=(.5,.75,1.,1.25,1.5,2.,3.)
FEATURES=("return_1m_bps","return_5m_bps","return_15m_bps",
          "rms_1m_5_bps","rms_1m_15_bps","range_5m_bps","range_15m_bps",
          "body_1m_bps","position_in_15m_range","clock_fraction")
CLASSES=(-1,0,1)


def sample(bars,minute):
    """All features end with the completed decision candle.

    Decision at m+1; delayed entry reference open m+2; exit reference
    open m+7. Labels, eligibility and observed outcome are separate
    from signal-time features; no prediction may look at future prices.
    """
    if minute<LOOKBACK-1 or minute+1+DELAY+HORIZON>=len(bars):
        return None
    past=bars[minute-LOOKBACK+1:minute+1,:4]
    if not np.isfinite(past).all() or np.any(past<=0):
        return None
    op,hi,lo,close=past.T
    returns=10000*np.diff(np.log(close))
    reference=close[-1]
    width=hi.max()-lo.min()
    features=np.array([10000*(reference/close[-n-1]-1) for n in (1,5,15)]+[
        np.sqrt(np.mean(returns[-5:]**2)),np.sqrt(np.mean(returns**2)),
        10000*(hi[-5:].max()-lo[-5:].min())/reference,
        10000*width/reference,10000*(reference-op[-1])/reference,
        (reference-lo.min())/width if width>0 else .5,(minute+1)/375.],
        dtype=np.float32)
    # Require the observed same-session path, including the one-minute
    # delay; never invent a label through a missing candle.
    future=bars[minute+1:minute+2+DELAY+HORIZON,:4]
    if not np.isfinite(future).all() or np.any(future<=0):
        return features,None
    entry=float(bars[minute+1+DELAY,0])
    exit_=float(bars[minute+1+DELAY+HORIZON,0])
    move=10000*(exit_/entry-1)
    label=1 if move>DEADBAND_BPS else -1 if move<-DEADBAND_BPS else 0
    return features,(entry,exit_,move,label)


def assemble(index,progress=None):
    rows=[];coverage={}
    for i,(day,bars) in enumerate(sorted(index.items())):
        counts={"reserved":0,"missing_history":0,"missing_outcome":0,"scored":0}
        if progress and (i%100==0 or i+1==len(index)):
            progress(f"Building material-direction labels {i+1}/{len(index)} {day}")
        for minute in range(LOOKBACK-1,len(bars)-1-DELAY-HORIZON):
            counts["reserved"]+=1
            result=sample(bars,minute)
            if result is None:
                counts["missing_history"]+=1
                continue
            features,outcome=result
            if outcome is None:
                counts["missing_outcome"]+=1
                continue
            entry,exit_,move,label=outcome
            rows.append((day,minute,features,entry,exit_,move,label))
            counts["scored"]+=1
        coverage[day]=counts
    if not rows:raise ValueError("No supported causal direction observations")
    return {"days":np.array([r[0] for r in rows]),
            "minutes":np.array([r[1] for r in rows]),
            "x":np.stack([r[2] for r in rows]),
            "entry":np.array([r[3] for r in rows]),
            "exit":np.array([r[4] for r in rows]),
            "move":np.array([r[5] for r in rows]),
            "label":np.array([r[6] for r in rows])},coverage


def _prob_metrics(prob,labels,days):
    targets=labels+1
    one=np.eye(3)[targets]
    losses=np.sum((prob-one)**2,axis=1)
    guess=np.argmax(prob,axis=1)-1
    recalls=[float(m._avg(guess[labels==k]==k,days[labels==k])) for k in CLASSES if np.any(labels==k)]
    conf=np.max(prob,axis=1)
    bins=[]
    for lo,hi in ((0.,.4),(.4,.6),(.6,.8),(.8,1.00001)):
        ok=(conf>=lo)&(conf<hi)
        if ok.any():
            bins.append({"low":lo,"high":min(hi,1.),"rows":int(ok.sum()),
                         "sessions":len(set(days[ok].tolist())),
                         "mean_confidence":float(m._avg(conf[ok],days[ok])),
                         "observed_accuracy":float(m._avg((guess[ok]==labels[ok]).astype(float),days[ok]))})
    return {"brier":float(m._avg(losses,days)),
            "log_loss":float(m._avg(-np.log(np.clip(prob[np.arange(len(prob)),targets],1e-12,1.)),days)),
            "accuracy":float(m._avg(guess==labels,days)),
            "balanced_accuracy":float(np.mean(recalls)) if len(recalls)==3 else None,
            "reliability":bins},losses


def _calibrate(prob,labels,days):
    one=np.eye(3)[labels+1]
    return min(TEMPERATURES,key=lambda t:(float(m._avg(np.sum((a._temperature(prob,t)-one)**2,axis=1),days)),abs(t-1)))


def _calls(prob):
    return np.array([a._call(v) for v in prob],dtype=int)


def _action_metrics(calls,labels,move,days):
    active=calls!=0
    net=np.where(active,calls*move-PROXY_COST_BPS,0.)
    selected_days=days[active]
    result={"eligible":len(calls),"calls":int(active.sum()),"call_sessions":len(set(selected_days.tolist())),
            "coverage":float(m._avg(active.astype(float),days)),
            "material_hit_rate":float(m._avg((calls[active]==labels[active]).astype(float),selected_days)) if active.any() else None,
            "opposite_material_rate":float(m._avg((calls[active]==-labels[active]).astype(float),selected_days)) if active.any() else None,
            "flat_rate":float(m._avg((labels[active]==0).astype(float),selected_days)) if active.any() else None,
            "up_calls":int((calls==1).sum()),"down_calls":int((calls==-1).sum()),
            "mean_net_index_proxy_bps_per_called_opportunity":float(m._avg(net[active],selected_days)) if active.any() else None,
            "positive_net_proxy_call_rate":float(m._avg((net[active]>0).astype(float),selected_days)) if active.any() else None,
            "net_proxy_per_eligible_opportunity":m.paired_day_interval(net,days)}
    return result,net


def assess(data,splits,progress=None):
    days=data["days"];minutes=data["minutes"];x=data["x"];y=data["label"]
    train=np.isin(days,splits[0])&((minutes+1)%HORIZON==0)
    val=np.isin(days,splits[1]);test=np.isin(days,splits[2])
    if any(len(set(days[mask].tolist()))<n for mask,n in ((train,40),(val,15),(test,15))):
        raise ValueError("Insufficient supported chronological sessions")
    if tuple(np.unique(y[train]))!=CLASSES:
        raise ValueError("All three training classes required")
    weights=m.day_weights(days[train])
    prior=np.average(np.eye(3)[y[train]+1],axis=0,weights=weights)
    # Simple training-only clock prior, fixed 30-minute buckets.
    buckets={}
    for k in np.unique(minutes[train]//30):
        chosen=train&(minutes//30==k)
        buckets[int(k)]=np.average(np.eye(3)[y[chosen]+1],axis=0,weights=m.day_weights(days[chosen]))
    def clock(mask):
        return np.stack([buckets.get(int(k),prior) for k in minutes[mask]//30])
    if progress:progress("Fitting fixed regularized three-class logistic direction model")
    model=make_pipeline(StandardScaler(),LogisticRegression(C=.1,max_iter=500,random_state=0))
    with threadpool_limits(limits=1):
        model.fit(x[train],y[train],logisticregression__sample_weight=weights)
        raw_v=model.predict_proba(x[val]);raw_t=model.predict_proba(x[test])
    t=_calibrate(raw_v,y[val],days[val])
    pc=_calibrate(clock(val),y[val],days[val])
    pp=_calibrate(np.tile(prior,(int(val.sum()),1)),y[val],days[val])
    probs={"model_raw":raw_t,"model_calibrated":a._temperature(raw_t,t),
           "training_prior_calibrated":a._temperature(np.tile(prior,(int(test.sum()),1)),pp),
           "clock_prior_calibrated":a._temperature(clock(test),pc)}
    labels=y[test];d=days[test];move=data["move"][test]
    report={"training_rows":int(train.sum()),"validation_rows":int(val.sum()),"evaluation_rows":int(test.sum()),
            "temperature":{"model":t,"clock_prior":pc,"training_prior":pp},
            "training_class_prior":prior.tolist(),"evaluation":{},"paired_brier":{}}
    losses={};actions={};net={}
    for key,prob in probs.items():
        metrics,losses[key]=_prob_metrics(prob,labels,d)
        calls=_calls(prob)
        stats,net[key]=_action_metrics(calls,labels,move,d)
        report["evaluation"][key]={"probability":metrics,"action":stats}
        actions[key]=calls
    momentum=np.where(x[test,1]>DEADBAND_BPS,1,np.where(x[test,1]<-DEADBAND_BPS,-1,0))
    for key,calls in (("momentum_5m",momentum),("no_trade",np.zeros(len(d),int))):
        report["evaluation"][key]={"action":_action_metrics(calls,labels,move,d)[0]}
    for key in ("training_prior_calibrated","clock_prior_calibrated"):
        report["paired_brier"]["model_minus_"+key]=m.paired_day_interval(losses["model_calibrated"]-losses[key],d)
    # Gate is a deliberately demanding retrospective screening criterion,
    # not a promise of returns, formal significance test or production pass.
    stats=report["evaluation"]["model_calibrated"]["action"]
    called=actions["model_calibrated"]!=0
    # Compare on exactly the model-called observations, not on different coverage.
    report["called_subset_comparison"]={}
    if called.any():
        for name,other in (("clock_prior",np.argmax(probs["clock_prior_calibrated"],axis=1)-1),
                           ("momentum",momentum)):
            hit=((actions["model_calibrated"][called]==labels[called]).astype(float)-
                 (other[called]==labels[called]).astype(float))
            report["called_subset_comparison"]["material_hit_minus_"+name]=m.paired_day_interval(hit,d[called])
    def upper_negative(z):return z["interval_95"] is not None and z["interval_95"][1]<0
    proxy=stats["net_proxy_per_eligible_opportunity"]["interval_95"]
    gate={"paired_brier_beats_both_priors":all(upper_negative(z) for z in report["paired_brier"].values()),
          "minimum_calls_and_sessions":stats["calls"]>=MIN_CALLS and stats["call_sessions"]>=MIN_CALL_DAYS,
          "both_direction_calls":stats["up_calls"]>0 and stats["down_calls"]>0,
          "positive_proxy_lower_interval":proxy is not None and proxy[0]>0}
    report["retrospective_gate"]=gate
    report["state"]="retrospective_screen_pass_only" if all(gate.values()) else "direction_not_qualified"
    journal=[]
    for i,j in enumerate(np.flatnonzero(test)):
        minute=int(minutes[j]);day=str(days[j])
        item={"session":day,"decision_utc":r._stamp(day,minute+1),
              "entry_reference_utc":r._stamp(day,minute+1+DELAY),
              "exit_reference_utc":r._stamp(day,minute+1+DELAY+HORIZON),
              "entry_reference_open":float(data["entry"][j]),"exit_reference_open":float(data["exit"][j]),
              "actual_return_bps":float(move[i]),"actual_class":int(labels[i]),
              "model_call":int(actions["model_calibrated"][i])}
        for name,p in probs.items():
            for k,label in enumerate(("down","flat","up")):item[name+"_"+label]=float(p[i,k])
        journal.append(item)
    return report,journal


def run(root,stop,days=1825,progress=print):
    if type(days) is not int or not 120<=days<=m.MAX_CORE_DAYS or stop>datetime.now(h.IST).date():
        raise ValueError("Use completed dates and bounded core history")
    service.DATA=root/"data"
    if not service.DATA.is_dir():raise ValueError("Shared data directory missing")
    start=stop-timedelta(days=days)
    index,*_,meta=m.load_sources(start,stop,wings=None,index_only=True,progress=progress)
    splits=m.split_days(sorted(index))
    data,coverage=assemble(index,progress)
    del index
    report,journal=assess(data,splits,progress)
    report.update(version=VERSION,from_inclusive=start.isoformat(),to_exclusive=stop.isoformat(),
                  observed_sessions=sum(map(len,splits)),training_dates=splits[0],validation_dates=splits[1],
                  evaluation_dates=splits[2],sources=meta["index"],session_coverage=coverage,
                  horizon_minutes=HORIZON,delay_minutes=DELAY,lookback_minutes=LOOKBACK,
                  deadband_bps=DEADBAND_BPS,confidence=CONFIDENCE,proxy_cost_bps=PROXY_COST_BPS,
                  features=list(FEATURES),warning=("Retrospective exploratory direction only. Previously examined dates are "
                    "not untouched. The first 16 completed bars are required; all eligible minute decisions are "
                    "assessed, targets overlap, and proxy losses are per opportunity, never account P&L. "
                    "Open references are not fills; 5 bps is an assumed index proxy, not option costs. "
                    "No live promotion, broker orders, options pricing or guarantee. A fresh prospective "
                    "receipt-time shadow test and realistic options execution validation remain mandatory."))
    return report,journal


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--shared-root",type=Path,default=service.ROOT)
    ap.add_argument("--days",type=int,default=1825)
    ap.add_argument("--to-date",default="2026-11-27",help="Exclusive IST end date")
    args=ap.parse_args()
    try:
        root=args.shared_root.resolve()
        report,journal=run(root,date.fromisoformat(args.to_date),args.days,lambda s:print(s,flush=True))
        folder=root/"results";folder.mkdir(exist_ok=True)
        stem="banknifty_direction_gate_"+uuid.uuid4().hex
        path=folder/(stem+".json");csv_path=folder/(stem+"_predictions.csv")
        def writer(out):
            w=csv.DictWriter(out,fieldnames=list(journal[0]));w.writeheader();w.writerows(journal)
        write_atomic(csv_path,writer)
        report["prediction_csv"]=csv_path.name
        write_atomic(path,lambda out:json.dump(report,out,sort_keys=True,indent=2,allow_nan=False))
        print("SESSIONS",report["observed_sessions"])
        print("ROWS",report["training_rows"],report["validation_rows"],report["evaluation_rows"])
        print("EVALUATION",json.dumps(report["evaluation"]))
        print("PAIRED BRIER",json.dumps(report["paired_brier"]))
        print("GATE",json.dumps(report["retrospective_gate"]))
        print("STATE",report["state"])
        print("REPORT",path)
        print("PREDICTIONS",csv_path)
        print(report["warning"])
        return 0
    except (ValueError,OSError,RuntimeError) as exc:
        print("Directional benchmark unavailable:",str(exc)[:240])
        return 2


if __name__=="__main__":
    raise SystemExit(main())
