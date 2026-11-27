"""Fixed, read-only rolling monthly option premium response benchmark.

Compare observed premium outcomes, not a trading strategy or executable P&L.
Reuse the verified original index/option receipt loaders and baseline tools.
"""
import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
import csv
import json
from math import isfinite
from pathlib import Path
import uuid

import numpy as np

from workstation_api import banknifty_candle_forecast as m
from workstation_api import cpr_hybrid_research as r
from workstation_api import historical_alpha as h
from workstation_api import predictive_option_research as p
from workstation_api import service
from scripts.run_banknifty_candle_forecast import write_atomic

VERSION="rolling_option_response_v1"
HOLD=5
DELAY=1
WINGS=3
# m is the start minute of the just-completed index/option candle.
# Decision m+1, earliest modeled entry reference m+2, exit m+7.
MINUTES=tuple(range(59,375-HOLD-DELAY-1,HOLD))
MAX_PER_SIDE=3
MIN_PREMIUM=5.
MAX_MONEYNESS=.02
FEATURES=("is_call","signed_moneyness_pct","premium_pct_spot","log_volume","log_oi",
          "vendor_iv","same_strike_return_5m_pct","same_strike_oi_change_5m_fraction",
          "same_strike_iv_change_5m_vendor_units","clock_fraction")
INDEX_FEATURES=("return_1m_pct","return_5m_pct","return_15m_pct","return_30m_pct",
                "vol_5m_pct","vol_30m_pct","range_30m_pct")
MODES=("option_only","option_plus_index")


def _optional(row,name):
    if not row:return np.nan
    x=row.get(name)
    return float(x) if x is not None and isfinite(x) and x>=0 else np.nan


def _change(now,old,field):
    x=_optional(now,field);y=_optional(old,field)
    return x/y-1 if isfinite(x) and isfinite(y) and y>0 else np.nan


def _select(day,minute,spot,table):
    # Only the completed signal candle; no future outcome informs ranking.
    quotes=table.get(r._stamp(day,minute),{})
    for side in ("CALL","PUT"):
        candidates=[]
        for s,k in quotes:
            if s!=side or abs(k/spot-1)>MAX_MONEYNESS:continue
            q=r._observed(table,day,minute,s,k)
            if q is not None and q["close"]>=MIN_PREMIUM:
                candidates.append(q)
        yield from sorted(candidates,key=lambda q:(abs(q["strike"]-spot),q["strike"]))[:MAX_PER_SIDE]


def decision_rows(day,minute,a,table,index_values):
    """Return candidate observations, including unresolved outcome states."""
    if minute not in MINUTES or not np.isfinite(a[minute-59:minute+1,:4]).all():
        return []
    spot=float(a[minute,3])
    result=[]
    for q in _select(day,minute,spot,table):
        side=q["side"];strike=q["strike"];price=float(q["close"])
        prior=r._observed(table,day,minute-5,side,strike)
        sign=1 if side=="CALL" else -1
        signed=sign*100*(spot-strike)/spot
        raw=[float(side=="CALL"),signed,100*price/spot,np.log1p(q["volume"]),
             np.log1p(_optional(q,"oi")),_optional(q,"iv"),
             100*_change(q,prior,"close"),_change(q,prior,"oi"),
             _optional(q,"iv")-_optional(prior,"iv"),(minute+1)/375.]
        x=np.asarray(raw+list(index_values),dtype=np.float32)
        row={"session":day,"minute":minute,"side":side,"strike":strike,
             "expiry_family":"MONTH:1","signal_close":price,"index_close":spot,
             "x":x,"bucket":(side,int(np.floor(signed/.5)),minute//60),
             "decision_utc":r._stamp(day,minute+1),
             "entry_reference_utc":r._stamp(day,minute+1+DELAY),
             "exit_reference_utc":r._stamp(day,minute+1+DELAY+HOLD)}
        entry=r._observed(table,day,minute+1+DELAY,side,strike)
        if entry is None:
            row["state"]="entry_unobserved"
        else:
            row["entry_open"]=float(entry["open"])
            exit_=r._observed(table,day,minute+1+DELAY+HOLD,side,strike)
            if exit_ is None:
                row["state"]="exit_unobserved"
            else:
                end=float(exit_["open"])
                row.update(state="scored_conditional_ohlc",exit_open=end,
                           target=np.asarray([100*(end-price)/price,
                                              100*(end-row["entry_open"])/price],float))
        result.append(row)
    return result


def assemble(index,table,progress=None):
    rows=[];coverage={}
    for i,(day,a) in enumerate(sorted(index.items())):
        if progress and (i%25==0 or i+1==len(index)):
            progress(f"Building same-strike premium outcomes {i+1}/{len(index)} {day}")
        names,features=m.f.price_features(a,index=True)
        cols=[names.index(k) for k in INDEX_FEATURES]
        counts=Counter()
        for minute in MINUTES:
            counts["reserved_decisions"]+=1
            if not np.isfinite(a[minute-59:minute+1,:4]).all():
                counts["missing_index_history"]+=1
                continue
            candidates=decision_rows(day,minute,a,table,features[minute,cols])
            if not candidates:counts["no_signal_candidates"]+=1
            counts["signal_candidates"]+=len(candidates)
            for row in candidates:
                counts[row["state"]]+=1
                rows.append(row)
        coverage[day]=dict(counts)
    return rows,coverage


def _baseline_fit(rows):
    # Fixed simple conditional median and beta-smoothed probability.
    # Fit only on earlier scored rows, with fallback for sparse buckets.
    groups=defaultdict(list)
    for row in rows:
        groups[row["bucket"]].append(row)
    def summarize(values):
        y=np.asarray([v["target"] for v in values]);up=y[:,1]>0
        return np.median(y,axis=0),float((up.sum()+1)/(len(up)+2))
    default=summarize(rows)
    return default,{k:summarize(v) for k,v in groups.items()
                    if len(v)>=100 and len({r["session"] for r in v})>=10}


def _baseline_predict(rows,fit):
    default,groups=fit
    values=[groups.get(r["bucket"],default) for r in rows]
    return np.stack([x[0] for x in values]),np.asarray([x[1] for x in values])


def _arrays(rows):
    x=np.stack([r["x"] for r in rows])
    y=np.stack([r["target"] for r in rows])
    days=np.asarray([r["session"] for r in rows])
    return x,y,days


def _metrics(rows,pred,prob,prior):
    _,y,days=_arrays(rows)
    signal=np.asarray([r["signal_close"] for r in rows])
    exit_price=np.maximum(.01,signal*(1+pred[:,0]/100))
    actual_exit=np.asarray([r["exit_open"] for r in rows])
    return {"rows":len(rows),"sessions":len(set(days.tolist())),
            "exit_premium_mae_points":float(m._avg(np.abs(exit_price-actual_exit),days)),
            "delayed_change_mae_pct_of_signal":float(m._avg(np.abs(pred[:,1]-y[:,1]),days)),
            "probability":m.probability_metrics(prob,(y[:,1]>0).astype(int),days,prior)}


def assess(rows,splits,progress=None):
    reserved={label:set(dates) for label,dates in zip(("training","validation","evaluation"),splits)}
    parts={label:[r for r in rows if r["session"] in dates and r["state"]=="scored_conditional_ohlc"]
           for label,dates in reserved.items()}
    coverage={label:{"reserved_sessions":len(dates),
                     "states":dict(Counter(r["state"] for r in rows if r["session"] in dates)),
                     "scored_sessions":len({r["session"] for r in parts[label]})}
              for label,dates in reserved.items()}
    report={"coverage":coverage,"models":{}}
    if any(coverage[k]["scored_sessions"]<n for k,n in
           (("training",40),("validation",15),("evaluation",15))):
        report["state"]="insufficient_scored_sessions"
        return report,[]
    train,val,test=(parts[k] for k in ("training","validation","evaluation"))
    xt,yt,dt=_arrays(train);xv,yv,dv=_arrays(val);xe,ye,de=_arrays(test)
    labels=(yt[:,1]>0).astype(int)
    if len(np.unique(labels))<2:
        report["state"]="insufficient_training_classes"
        return report,[]
    weights=m.day_weights(dt)
    prior=float(m._avg(labels,dt))
    fixed=np.zeros((len(test),2))
    fixed_p=np.full(len(test),prior)
    bucket,bucket_p=_baseline_predict(test,_baseline_fit(train))
    report["training_prior_positive_gross_change"]=prior
    report["baselines"]={"no_change":_metrics(test,fixed,fixed_p,prior),
                         "historical_bucket":_metrics(test,bucket,bucket_p,prior)}
    outputs={}
    actual=(ye[:,1]>0).astype(int)
    for mode in MODES:
        if progress:progress("Fitting "+mode+" fixed ridge/logistic")
        width=len(FEATURES) if mode=="option_only" else len(FEATURES)+len(INDEX_FEATURES)
        keep=np.flatnonzero(np.isfinite(xt[:,:width]).mean(axis=0)>=.05)
        if not len(keep):raise ValueError("No supported training features")
        reg=m.train_model("ridge",xt[:,keep],yt,weights)
        cls=m.direction_model("ridge",xt[:,keep],labels,weights)
        vp=m.predict_model(reg,xv[:,keep]);ep=m.predict_model(reg,xe[:,keep])
        vprob=cls.predict_proba(xv[:,keep])[:,1]
        eprob=cls.predict_proba(xe[:,keep])[:,1]
        calibrated,state=m._calibrate_probability(vprob,(yv[:,1]>0).astype(int),dv,eprob)
        metrics=_metrics(test,ep,calibrated,prior)
        record={"features_retained":[(FEATURES+INDEX_FEATURES)[i] for i in keep],
                "calibration_state":state,"validation_raw":_metrics(val,vp,vprob,prior),
                "evaluation":metrics,"evaluation_raw_probability":m.probability_metrics(eprob,actual,de,prior)}
        def diff(other,other_prob):
            signal=np.asarray([r["signal_close"] for r in test])
            truth=np.asarray([r["exit_open"] for r in test])
            premium=lambda pred:np.maximum(.01,signal*(1+pred[:,0]/100))
            return {"exit_mae_points":m.paired_day_interval(np.abs(premium(ep)-truth)-np.abs(premium(other)-truth),de),
                    "delayed_change_mae_pct_of_signal":m.paired_day_interval(np.abs(ep[:,1]-ye[:,1])-np.abs(other[:,1]-ye[:,1]),de),
                    "brier":m.paired_day_interval((calibrated-actual)**2-(other_prob-actual)**2,de)}
        record["minus_no_change"]=diff(fixed,fixed_p)
        record["minus_historical_bucket"]=diff(bucket,bucket_p)
        if mode=="option_plus_index":
            record["minus_option_only"]=diff(outputs["option_only"][0],outputs["option_only"][2])
        report["models"][mode]=record
        outputs[mode]=(ep,eprob,calibrated)
        if progress:
            progress("OPTION_RESPONSE "+mode+" "+json.dumps({
                "exit_mae_points":metrics["exit_premium_mae_points"],
                "change_mae_pct":metrics["delayed_change_mae_pct_of_signal"],
                "raw_brier":record["evaluation_raw_probability"]["brier"],
                "calibrated_brier":metrics["probability"]["brier"],
                "minus_no_change":record["minus_no_change"],
                "minus_historical_bucket":record["minus_historical_bucket"],
                "minus_option_only":record.get("minus_option_only")}))
    journal=[];test_i=0
    # Preserve all evaluation candidates, not only those with later observations.
    for row in rows:
        if row["session"] not in reserved["evaluation"]:continue
        item={k:v for k,v in row.items() if k not in ("target","x","bucket","minute")}
        for mode in MODES:
            for key in ("predicted_exit_premium","predicted_change_pct_of_signal","raw_up_probability","calibrated_up_probability"):
                item[mode+"_"+key]=None
        if row["state"]=="scored_conditional_ohlc":
            # parts retain the same input order; missing outcomes are NOT
            # silently scored or treated as profitable fills.
            assert test[test_i] is row
            for mode,(pred,raw,cal) in outputs.items():
                item.update({mode+"_predicted_exit_premium":float(max(.01,row["signal_close"]*(1+pred[test_i,0]/100))),
                             mode+"_predicted_change_pct_of_signal":float(pred[test_i,1]),
                             mode+"_raw_up_probability":float(raw[test_i]),
                             mode+"_calibrated_up_probability":float(cal[test_i])})
            test_i+=1
        # Keep CSV schema stable across unresolved candidates.
        item.setdefault("entry_open",None);item.setdefault("exit_open",None)
        journal.append(item)
    if test_i!=len(test):raise RuntimeError("Evaluation candidate order changed")
    report["state"]="assessed_conditional_premium_only"
    return report,journal


def run(root,stop,days=365,progress=print):
    if type(days) is not int or not 120<=days<=400 or stop>datetime.now(h.IST).date():
        raise ValueError("Use completed dates and 120-400 calendar days")
    service.DATA=root/"data"
    if not service.DATA.is_dir():raise ValueError("Shared data directory missing")
    start=stop-timedelta(days=days)
    index,*_,meta=m.load_sources(start,stop,wings=None,index_only=True,progress=progress)
    dates=sorted(index)
    splits=m.split_days(dates)
    stamps={r._stamp(day,minute+offset) for day in dates for minute in MINUTES
            for offset in (-5,0,1+DELAY,1+DELAY+HOLD)}
    progress("Verifying original rolling option receipts; no provider calls")
    table,options=p._load_options([{"session":d} for d in dates],WINGS,needed_stamps=stamps)
    rows,coverage=assemble(index,table,progress)
    del table,index
    report,journal=assess(rows,splits,progress)
    report.update(version=VERSION,from_inclusive=start.isoformat(),to_exclusive=stop.isoformat(),
                  observed_sessions=len(dates),horizon_minutes=HOLD,decision_delay_minutes=DELAY,
                  strike_wings=WINGS,max_per_side=MAX_PER_SIDE,
                  training_dates=splits[0],validation_dates=splits[1],evaluation_dates=splits[2],
                  index_sources=meta["index"],option_sources=options,session_coverage=coverage,
                  features=list(FEATURES),index_features=list(INDEX_FEATURES),
                  warning=("Retrospective conditional rolling monthly family, not exact exchange contracts. "
                           "Completed signal bars, one-minute delay, then five-minute open-to-open premium "
                           "observations; positive gross change is NOT net profitability. "
                           "Later positive-volume bars establish observations, not fills; scored subset may be selective. "
                           "No exact expiry/lot, spread, fees, execution, IV-change forecast or trading policy. "
                           "Earlier examined dates are not prospective confirmation. No provider calls, orders or deployment."))
    return report,journal


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--shared-root",type=Path,default=service.ROOT)
    ap.add_argument("--days",type=int,default=365)
    ap.add_argument("--to-date",default="2026-11-27",help="Exclusive IST end date")
    args=ap.parse_args()
    try:
        root=args.shared_root.resolve()
        report,journal=run(root,date.fromisoformat(args.to_date),args.days,lambda s:print(s,flush=True))
        folder=root/"results";folder.mkdir(exist_ok=True)
        stem="banknifty_option_response_"+uuid.uuid4().hex
        path=folder/(stem+".json");csv_path=folder/(stem+"_predictions.csv")
        if journal:
            def writer(out):
                w=csv.DictWriter(out,fieldnames=list(journal[0]));w.writeheader();w.writerows(journal)
            write_atomic(csv_path,writer)
        report["prediction_csv"]=csv_path.name if journal else None
        write_atomic(path,lambda out:json.dump(report,out,sort_keys=True,indent=2,allow_nan=False))
        print("COVERAGE",json.dumps(report["coverage"]))
        print("BASELINES",json.dumps(report.get("baselines",{})))
        print("STATE",report["state"])
        print("REPORT",path)
        print("PREDICTIONS",csv_path if journal else "none")
        print(report["warning"])
        return 0
    except (ValueError,OSError,RuntimeError) as exc:
        print("Option response unavailable:",str(exc)[:240])
        return 2


if __name__=="__main__":
    raise SystemExit(main())
