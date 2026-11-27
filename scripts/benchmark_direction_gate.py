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
EMA_CPR_VERSION="direction_ema_cpr_v1"
LEVELS=("previous_high","previous_low","cpr_bottom","cpr_top","opening_15m_high","opening_15m_low")
EVENTS=("fresh_ema_cross","level_breakout","level_rejection","failed_breakout")
CONTEXT_FEATURES=("ema9_distance_bps","ema21_distance_bps","ema9_minus_21_bps",
                  "ema_cross","last_cross_direction","minutes_since_cross",
                  "previous_open_distance_bps","previous_close_distance_bps",
                  "previous_pivot_distance_bps","previous_cpr_width_bps","previous_r1_distance_bps",
                  "previous_s1_distance_bps","opening_gap_bps","today_open_distance_bps",
                  "today_running_high_distance_bps","today_running_low_distance_bps",
                  "today_running_range_bps","developing_pivot_distance_bps",
                  "developing_cpr_bottom_distance_bps","developing_cpr_top_distance_bps","cpr_zone",
                  "breakout_ema_alignment","rejection_ema_alignment","failed_breakout_ema_alignment"
                  )+tuple(level+"_"+field for level in LEVELS
                          for field in ("distance_bps","cross","rejection","failed_breakout"))


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


def prior_weekday(day):
    previous=date.fromisoformat(day)-timedelta(days=1)
    while previous.weekday()>=5:
        previous-=timedelta(days=1)
    return previous.isoformat()


def ema_cpr_features(bars,previous):
    """Causal 1m EMA and level events, seeded from complete prior weekday.

    Today's standard daily CPR comes from previous H/L/C. Developing
    CPR is a distinct provisional feature using only completed bars.
    Stop at a current-session gap rather than silently skipping it.
    """
    context=np.full((len(bars),len(CONTEXT_FEATURES)),np.nan,dtype=np.float32)
    rules=np.zeros((len(bars),2),dtype=int)
    events=np.zeros((len(bars),len(EVENTS)),dtype=bool)
    if previous is None or previous.shape!=(375,5):
        return context,rules,events
    prev_ohlc=m.f.daily_ohlc(previous)
    if prev_ohlc is None or np.any(previous[:,:4]<=0):
        return context,rules,events
    op,hi,lo,close=prev_ohlc
    p=(hi+lo+close)/3;bc=(hi+lo)/2;tc=2*p-bc
    bottom,top=sorted((bc,tc))
    fast=h._ema(previous[:,3],9);slow=h._ema(previous[:,3],21)
    today_open=float(bars[0,0]);running_hi=-np.inf;running_lo=np.inf
    opening_hi=opening_lo=None
    last_cross=0;cross_minute=-1;last_price=None
    previous_crosses=np.zeros(len(LEVELS),dtype=int)
    for minute,bar in enumerate(bars):
        o,high,low,price=bar[:4]
        if not np.isfinite(bar[:4]).all() or np.any(bar[:4]<=0):break
        old_gap=fast-slow
        fast+=(price-fast)*2/10
        slow+=(price-slow)*2/22
        gap=fast-slow
        cross=1 if old_gap<=0<gap else -1 if old_gap>=0>gap else 0
        if cross:
            last_cross=cross;cross_minute=minute
        running_hi=max(running_hi,high);running_lo=min(running_lo,low)
        if minute==14:opening_hi,opening_lo=running_hi,running_lo
        # Opening-range levels do not exist until the first 15 bars close.
        levels=(hi,lo,bottom,top,opening_hi,opening_lo)
        crosses=[];rejections=[];failures=[]
        for j,level in enumerate(levels):
            c=q=0
            if level is not None and last_price is not None and (j<4 or minute>14):
                c=1 if last_price<=level<price else -1 if last_price>=level>price else 0
                # Same-side touch/rejection (support retest or resistance rejection).
                q=1 if last_price>level and low<=level<price else -1 if last_price<level and high>=level>price else 0
            failed=c if c and previous_crosses[j]==-c else 0
            crosses.append(c);rejections.append(q);failures.append(failed)
        previous_crosses=np.asarray(crosses)
        last_price=price
        if opening_hi is None:continue
        running_p=(running_hi+running_lo+price)/3
        running_bc=(running_hi+running_lo)/2
        running_bottom,running_top=sorted((running_bc,2*running_p-running_bc))
        scale=10000/price
        distances=lambda values:[(price-v)*scale for v in values]
        zone=1 if price>top else -1 if price<bottom else 0
        direction=int(np.sign(gap))
        context[minute]=[
            *distances((fast,slow)),gap*scale,float(cross),float(last_cross),
            float(minute-cross_minute if cross_minute>=0 else minute+1),
            *distances((op,close,p)),(top-bottom)*scale,
            *distances((2*p-lo,2*p-hi)),10000*(today_open/close-1),
            *distances((today_open,running_hi,running_lo)),(running_hi-running_lo)*scale,
            *distances((running_p,running_bottom,running_top)),float(zone),
            direction*sum(crosses),direction*sum(rejections),direction*sum(failures),
            *[v for j,level in enumerate(levels) for v in
              ((price-level)*scale,crosses[j],rejections[j],failures[j])]]
        # Fixed comparators, not position/fill simulators. A conflicting
        # level-event set abstains; no future bars determine the call.
        rules[minute,0]=cross if cross==zone else 0
        directions={v for v in crosses+rejections+failures if v}
        rules[minute,1]=next(iter(directions)) if len(directions)==1 else 0
        events[minute]=[bool(cross),any(crosses),any(rejections),any(failures)]
    return context,rules,events


def assemble(index,progress=None,*,ema_cpr=False):
    rows=[];coverage={};rule_rows=[];event_rows=[]
    for i,(day,bars) in enumerate(sorted(index.items())):
        counts={"reserved":0,"missing_history":0,"missing_outcome":0,"scored":0}
        if ema_cpr:
            previous=index.get(prior_weekday(day))
            context,rules,events=ema_cpr_features(bars,previous)
            counts["missing_ema_cpr_context"]=0
        if progress and (i%100==0 or i+1==len(index)):
            progress(f"Building material-direction labels {i+1}/{len(index)} {day}")
        for minute in range(LOOKBACK-1,len(bars)-1-DELAY-HORIZON):
            counts["reserved"]+=1
            result=sample(bars,minute)
            if result is None:
                counts["missing_history"]+=1
                continue
            features,outcome=result
            if ema_cpr and not np.isfinite(context[minute]).all():
                counts["missing_ema_cpr_context"]+=1
                continue
            if outcome is None:
                counts["missing_outcome"]+=1
                continue
            entry,exit_,move,label=outcome
            if ema_cpr:
                features=np.concatenate((features,context[minute]))
                rule_rows.append(rules[minute]);event_rows.append(events[minute])
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
            "label":np.array([r[6] for r in rows]),
            **({"level_rules":np.stack(rule_rows),"level_events":np.stack(event_rows)} if ema_cpr else {})},coverage


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


def assess_ema_cpr(data,splits,progress=None):
    """Fixed paired information comparison: same labels, dates, rows, model."""
    core={**data,"x":data["x"][:,:len(FEATURES)]}
    if progress:progress("Matched intraday-only comparator")
    base,base_journal=assess(core,splits,progress)
    if progress:progress("Matched EMA 9/21 + previous OHLC/CPR + developing levels")
    report,journal=assess(data,splits,progress)
    if len(journal)!=len(base_journal):
        raise RuntimeError("Matched evaluation lengths differ")
    test=np.isin(data["days"],splits[2])
    days=data["days"][test];labels=data["label"][test];move=data["move"][test]
    columns=["model_calibrated_"+k for k in ("down","flat","up")]
    p=np.asarray([[row[k] for k in columns] for row in journal])
    q=np.asarray([[row[k] for k in columns] for row in base_journal])
    calls=np.asarray([row["model_call"] for row in journal])
    base_calls=np.asarray([row["model_call"] for row in base_journal])
    if any(x["decision_utc"]!=y["decision_utc"] or x["actual_class"]!=y["actual_class"]
           for x,y in zip(journal,base_journal)):
        raise RuntimeError("Matched evaluation anchors differ")
    one=np.eye(3)[labels+1]
    inc={"multiclass_brier":m.paired_day_interval(np.sum((p-one)**2-(q-one)**2,axis=1),days)}
    # Conditional sign discrimination diagnostic on actual material moves.
    # This is NOT a decision-time filter or a claim that we know a move will occur.
    material=labels!=0
    if material.any():
        y=(labels[material]==1).astype(float)
        pp=p[material,2]/np.maximum(p[material,0]+p[material,2],1e-12)
        qq=q[material,2]/np.maximum(q[material,0]+q[material,2],1e-12)
        inc["conditional_material_direction_brier"]=m.paired_day_interval((pp-y)**2-(qq-y)**2,days[material])
        inc["conditional_material_direction_rows"]=int(material.sum())
        inc["conditional_material_direction_model_brier"]=float(m._avg((pp-y)**2,days[material]))
        inc["conditional_material_direction_core_brier"]=float(m._avg((qq-y)**2,days[material]))
    else:
        inc["conditional_material_direction_brier"]={"interval_95":None}
    model_net=_action_metrics(calls,labels,move,days)[1]
    core_net=_action_metrics(base_calls,labels,move,days)[1]
    inc["net_proxy_per_eligible_opportunity"]=m.paired_day_interval(model_net-core_net,days)
    rules=data["level_rules"][test];events=data["level_events"][test]
    report["fixed_level_rules"]={name:_action_metrics(rules[:,k],labels,move,days)[0]
                                 for k,name in enumerate(("ema_cpr_cross","unambiguous_level_event"))}
    report["event_diagnostics"]={}
    for k,name in enumerate(EVENTS):
        mask=events[:,k]
        report["event_diagnostics"][name]={"rows":int(mask.sum()),"sessions":len(set(days[mask].tolist())),
             "model":_action_metrics(calls[mask],labels[mask],move[mask],days[mask])[0] if mask.any() else None,
             "core":_action_metrics(base_calls[mask],labels[mask],move[mask],days[mask])[0] if mask.any() else None}
    report["matched_intraday_only"]=base
    report["incremental_comparison"]=inc
    for name in ("multiclass_brier","conditional_material_direction_brier"):
        interval=inc[name]["interval_95"]
        report["retrospective_gate"]["incremental_"+name]=interval is not None and interval[1]<0
    report["state"]="retrospective_screen_pass_only" if all(report["retrospective_gate"].values()) else "direction_not_qualified"
    for i,row in enumerate(journal):
        row["intraday_only_call"]=int(base_calls[i])
        for k,name in enumerate(("down","flat","up")):
            row["intraday_only_calibrated_"+name]=float(q[i,k])
        row["ema_cpr_cross_rule"]=int(rules[i,0])
        row["level_event_rule"]=int(rules[i,1])
        for k,name in enumerate(EVENTS):row[name]=bool(events[i,k])
    return report,journal


def run(root,stop,days=1825,progress=print,*,ema_cpr=False):
    if type(days) is not int or not 120<=days<=m.MAX_CORE_DAYS or stop>datetime.now(h.IST).date():
        raise ValueError("Use completed dates and bounded core history")
    service.DATA=root/"data"
    if not service.DATA.is_dir():raise ValueError("Shared data directory missing")
    start=stop-timedelta(days=days)
    index,*_,meta=m.load_sources(start,stop,wings=None,index_only=True,progress=progress)
    splits=m.split_days(sorted(index))
    data,coverage=assemble(index,progress,ema_cpr=ema_cpr)
    del index
    report,journal=(assess_ema_cpr(data,splits,progress) if ema_cpr else assess(data,splits,progress))
    report.update(version=EMA_CPR_VERSION if ema_cpr else VERSION,from_inclusive=start.isoformat(),to_exclusive=stop.isoformat(),
                  observed_sessions=sum(map(len,splits)),training_dates=splits[0],validation_dates=splits[1],
                  evaluation_dates=splits[2],sources=meta["index"],session_coverage=coverage,
                  horizon_minutes=HORIZON,delay_minutes=DELAY,lookback_minutes=LOOKBACK,
                  deadband_bps=DEADBAND_BPS,confidence=CONFIDENCE,proxy_cost_bps=PROXY_COST_BPS,
                  features=list(FEATURES+(CONTEXT_FEATURES if ema_cpr else ())),warning=("Retrospective exploratory direction only. Previously examined dates are "
                    "not untouched. The first 16 completed bars are required; all eligible minute decisions are "
                    "assessed, targets overlap, and proxy losses are per opportunity, never account P&L. "
                    "Open references are not fills; 5 bps is an assumed index proxy, not option costs. "
                    "No live promotion, broker orders, options pricing or guarantee. A fresh prospective "
                    "receipt-time shadow test and realistic options execution validation remain mandatory."))
    if ema_cpr:
        report["warning"]+=" EMA/CPR context requires a complete prior weekday and gap-free current prefix; unverified holidays and missing weekdays exclude dates rather than reuse stale levels. Opening range uses first 15 completed minutes. One-minute EMA 9/21 is seeded by prior session. Developing CPR is not the end-of-day CPR. Event categories can overlap. Matched comparator shares the context-qualified dates and anchors; material-direction diagnostic conditions on realized nonflat outcomes only for scoring, not calls."
    return report,journal


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--shared-root",type=Path,default=service.ROOT)
    ap.add_argument("--days",type=int,default=1825)
    ap.add_argument("--ema-cpr",action="store_true",help="Fixed matched EMA 9/21 + previous-day and current developing level context")
    ap.add_argument("--to-date",default="2026-11-27",help="Exclusive IST end date")
    args=ap.parse_args()
    try:
        root=args.shared_root.resolve()
        report,journal=run(root,date.fromisoformat(args.to_date),args.days,lambda s:print(s,flush=True),ema_cpr=args.ema_cpr)
        folder=root/"results";folder.mkdir(exist_ok=True)
        stem=("banknifty_direction_ema_cpr_" if args.ema_cpr else "banknifty_direction_gate_")+uuid.uuid4().hex
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
        if args.ema_cpr:
            print("MATCHED CORE",json.dumps(report["matched_intraday_only"]["evaluation"]["model_calibrated"]))
            print("INCREMENTAL",json.dumps(report["incremental_comparison"]))
            print("LEVEL RULES",json.dumps(report["fixed_level_rules"]))
            print("EVENT DIAGNOSTICS",json.dumps(report["event_diagnostics"]))
            print("MISSING CONTEXT",sum(v["missing_ema_cpr_context"] for v in report["session_coverage"].values()))
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
