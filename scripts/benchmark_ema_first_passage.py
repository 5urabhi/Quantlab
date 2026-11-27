"""Fixed causal EMA first-passage benchmark with synchronized market context.

One candidate per fresh BANKNIFTY crossover. No option fills or trade P&L.
Retain unresolved paths and score only observed, unambiguous outcomes.
"""
import argparse
from collections import Counter
from contextlib import closing
import csv
from datetime import date, datetime, time, timedelta
import json
from pathlib import Path
import sqlite3
import uuid

import numpy as np
from threadpoolctl import threadpool_limits

from scripts import benchmark_ema_paths as paths, benchmark_ema_levels as levels
from scripts import benchmark_direction_gate as direction, benchmark_global_open as global_open
from scripts.run_banknifty_candle_forecast import write_atomic
from workstation_api import banknifty_candle_forecast as m
from workstation_api import historical_alpha as h, cpr_hybrid_research as r
from workstation_api import predictive_option_research as opt
from workstation_api import market_context, alpaca_overnight, shared_market_data, service

VERSION="ema_first_passage_v1"
FAVORABLE_BPS=10.
ADVERSE_BPS=5.
DELAY=1
CONFIDENCE=.60
LANES=("banks","peers","options","global_daily","overnight")
RESOLVED={"favorable_first":1,"adverse_first":0,"opposite_cross_without_barrier":0}
CORE_FIELDS=("direction","clock_fraction","weekday","signed_ema_gap_bps",
             "signed_price_minus_ema9_bps","signed_open_gap_bps","cpr_width_bps",
             "signed_previous_session_return_bps","nearest_ahead_bps","nearest_behind_bps"
             )+tuple("signed_distance_to_"+name+"_bps" for name in levels.LEVEL_NAMES)
CORE_TECH=("return_1m_pct","return_5m_pct","return_15m_pct","return_30m_pct","return_60m_pct",
           "vol_5m_pct","vol_15m_pct","vol_30m_pct","range_5m_pct","range_15m_pct",
           "body_pct","upper_wick_pct","lower_wick_pct")
BANK_FIELDS=("return_1m_pct","return_5m_pct","return_15m_pct","relative_volume_5m",
             "vol_15m_pct","member","observed","scheduled_open")


def outcome(bars,cross,nxt,prefix):
    """First observed touch from delayed reference open, before/on reversal.

    Dual-barrier candles are ambiguous even if the close looks favorable.
    Opposite signal known at entry cancels; no synthetic prices after gaps.
    """
    minute=int(cross["minute"]);sign=int(cross["direction"])
    entry=minute+1+DELAY
    end=int(nxt["minute"]) if nxt is not None else prefix-1
    row={"entry_minute":entry,"entry_reference_open":None,"outcome_minute":None,
         "outcome_state":"entry_unobserved","success":None}
    if nxt is not None and end+1<=entry:
        row["outcome_state"]="canceled_before_or_at_entry"
        return row
    if entry>=prefix:return row
    ref=float(bars[entry,0])
    if not np.isfinite(ref) or ref<=0:raise ValueError("Invalid observed entry reference")
    row["entry_reference_open"]=ref
    favorable=ref*(1+sign*FAVORABLE_BPS/10000)
    adverse=ref*(1-sign*ADVERSE_BPS/10000)
    for j in range(entry,end+1):
        high,low=bars[j,1:3]
        if not np.isfinite((high,low)).all():raise ValueError("Unobserved outcome inside prefix")
        good=high>=favorable if sign==1 else low<=favorable
        bad=low<=adverse if sign==1 else high>=adverse
        if good or bad:
            state="ambiguous_dual_touch" if good and bad else ("favorable_first" if good else "adverse_first")
            row.update(outcome_minute=j,outcome_state=state,success=RESOLVED.get(state))
            return row
    state=("opposite_cross_without_barrier" if nxt is not None else
           ("censored_session_end" if prefix==paths.MINUTES else "censored_gap"))
    row.update(outcome_minute=end,outcome_state=state,success=RESOLVED.get(state))
    return row


def core_vector(day,bars,cross,tech,names):
    j=int(cross["minute"]);sign=int(cross["direction"]);price=float(cross["signal_close"])
    frozen=levels.frozen_levels(bars,cross)
    distances=[sign*10000*(v-price)/price if v is not None else np.nan for v in frozen.values()]
    # Use explicit named order rather than relying on dictionary construction.
    distances=[sign*10000*(frozen[k]-price)/price if frozen[k] is not None else np.nan
               for k in levels.LEVEL_NAMES]
    ahead=[v for v in distances if np.isfinite(v) and v>0]
    behind=[-v for v in distances if np.isfinite(v) and v<0]
    values=[sign,(j+1)/375,date.fromisoformat(day).weekday(),
            sign*10000*(cross["ema9"]-cross["ema21"])/price,
            sign*10000*(price-cross["ema9"])/price,
            sign*10000*(cross["today_open"]/cross["previous_close"]-1),
            10000*(cross["cpr_top"]-cross["cpr_bottom"])/price,
            sign*10000*(cross["previous_close"]/cross["previous_open"]-1),
            min(ahead,default=np.nan),min(behind,default=np.nan),*distances]
    return np.asarray(values+[float(tech[j,names.index(k)]) for k in CORE_TECH],dtype=np.float32)


def collect(index,progress=None):
    events={};coverage={}
    for i,day in enumerate(sorted(index)):
        if progress and (i%100==0 or i+1==len(index)):progress(f"Index crossover outcomes {i+1}/{len(index)}")
        bars=index[day]
        crosses,prefix,state=paths.session_crosses(bars,index.get(direction.prior_weekday(day)))
        coverage[day]={"state":state,"prefix_minutes":prefix,"crossovers":len(crosses)}
        if not crosses:continue
        names,tech=m.f.price_features(bars,index=True)
        rows=[]
        for k,c in enumerate(crosses):
            nxt=crosses[k+1] if k+1<len(crosses) else None
            result=outcome(bars,c,nxt,prefix)
            rows.append({"session":day,"signal_minute":int(c["minute"]),
                         "signal_utc":r._stamp(day,int(c["minute"])+1),
                         "direction":int(c["direction"]),"signal_close":float(c["signal_close"]),
                         "core":core_vector(day,bars,c,tech,names),**result})
        events[day]=rows
        coverage[day]["outcomes"]=dict(Counter(x["outcome_state"] for x in rows))
    return events,coverage


def global_features(start,stop,dates):
    daily_names=tuple(global_open.DAILY)
    overnight_names=tuple("BOATS_"+s for s in global_open.OVERNIGHT)
    daily={};overnight={};evidence={}
    path=shared_market_data.database_path()
    if not path.is_file():
        return daily,overnight,{"state":"database_missing"},daily_names,overnight_names
    with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=3)) as db:
        db.execute("PRAGMA query_only=ON")
        try:
            timelines,meta=market_context.load_timelines(db,datetime.combine(start,time.min,h.IST),
                                                         datetime.combine(stop,time.min,h.IST),"archive")
            evidence["daily"]=meta
            evidence["daily_receipt_hashes"]=set()
            for day in dates:
                cutoff=datetime.combine(date.fromisoformat(day),time(9,10),h.IST)
                _,details,_=market_context.factor_at(timelines,cutoff)
                row=np.full(len(daily_names),np.nan)
                for k,name in enumerate(daily_names):
                    detail=details.get(name,{})
                    if detail.get("state")=="available":
                        row[k]=float(detail["change_feature"])
                        evidence["daily_receipt_hashes"].update((detail["receipt_sha256"],detail["prior_receipt_sha256"]))
                daily[day]=row
            evidence["daily_receipt_hashes"]=sorted(evidence["daily_receipt_hashes"])
        except (ValueError,OSError,sqlite3.Error,KeyError,TypeError) as exc:
            daily={};evidence.pop("daily_receipt_hashes",None);evidence["daily_error"]=str(exc)[:180]
        try:
            audit={}
            for day in dates:
                cutoff=datetime.combine(date.fromisoformat(day),time(9,10),h.IST)
                rows=alpaca_overnight.features(db,date.fromisoformat(day),cutoff,mode="archive")
                value=np.full(len(overnight_names),np.nan)
                for k,name in enumerate(global_open.OVERNIGHT):
                    record=rows.get(name,{})
                    if record.get("state")=="observed_proxy" and record.get("session_return_bps") is not None:
                        value[k]=float(record["session_return_bps"])
                overnight[day]=value
                audit[day]={s:rows[s] for s in global_open.OVERNIGHT if s in rows}
            evidence["overnight_asof"]=audit
        except (ValueError,OSError,sqlite3.Error,KeyError,TypeError) as exc:
            overnight={};evidence["overnight_error"]=str(exc)[:180]
    evidence["state"]="archive_asof_0910"
    return daily,overnight,evidence,daily_names,overnight_names


def aligned_levels(day,minutes,source,identity,*,bank=False):
    """Exact EMA9/21 and prior levels at the BANKNIFTY clock, not own-event clocks."""
    from workstation_api import nse_session_policy as policy
    a=source.get(day);prevday=direction.prior_weekday(day);previous=source.get(prevday)
    out=np.full((len(minutes),5),np.nan)
    if a is None or previous is None:return out
    q=policy.cash_bank_minutes(prevday,identity) if bank else paths.MINUTES
    n=policy.cash_bank_minutes(day,identity) if bank else paths.MINUTES
    prior=previous[:q,:4]
    if not np.isfinite(prior).all() or np.any(prior<=0):return out
    hi=float(prior[:,1].max());lo=float(prior[:,2].min());close=float(prior[-1,3])
    pivot=(hi+lo+close)/3;mid=(hi+lo)/2;bottom,top=sorted((mid,2*pivot-mid))
    fast=h._ema(prior[:,3],9);slow=h._ema(prior[:,3],21)
    slots={int(j):i for i,j in enumerate(minutes)}
    for j in range(min(n,int(minutes[-1])+1)):
        bar=a[j,:4]
        if not np.isfinite(bar).all() or np.any(bar<=0):break
        price=float(bar[3]);fast+=(price-fast)*2/10;slow+=(price-slow)*2/22
        if j in slots:
            out[slots[j]]=[10000*(fast-slow)/price,*[10000*(price-v)/price for v in (hi,lo,bottom,top)]]
    return out


ALIGN_FIELDS=("ema9_minus_21_bps","previous_high_distance_bps","previous_low_distance_bps",
              "cpr_bottom_distance_bps","cpr_top_distance_bps")


def context_blocks(index,events,stocks,membership,weights,peers,table,daily,overnight,
                   daily_names,overnight_names,progress=None):
    ids=sorted({identity for value in membership.values() for identity in value.values()})
    names={};blocks={k:[] for k in LANES};available={k:[] for k in LANES}
    dates=sorted(index);prior=[];i=0
    for day in dates:
        rows=events.get(day,[])
        if not rows:prior.append(day);continue
        i+=1
        if progress and (i%25==0 or i==len(events)):progress(f"Synchronizing event context {i}/{len(events)}")
        minutes=np.asarray([row["signal_minute"] for row in rows],dtype=int)
        a=index[day];members=set(membership.get(day,{}).values())
        bn,bv,bok=m.f.banks_at(day,minutes,ids,stocks,members,weights.get(day),prior,a[:,3])
        keep=[i for i,n in enumerate(bn) if n.startswith("bank_") or
              any(n.endswith("_"+field) for field in BANK_FIELDS)]
        bank_names=tuple(bn[i] for i in keep)
        bank_values=[bv[:,keep]]
        for identity in ids:
            bank_names+=tuple(identity+"_"+f for f in ALIGN_FIELDS)
            bank_values.append(aligned_levels(day,minutes,stocks.get(identity,{}),identity,bank=True)
                               if identity in members else np.full((len(minutes),len(ALIGN_FIELDS)),np.nan))
        pn,pv,pok=m.f.peers_at(day,minutes,peers,a[:,3])
        peer_names=tuple(pn);peer_values=[pv]
        for identity in m.f.PEERS:
            if identity=="INDEX:INDIAVIX":continue
            peer_names+=tuple(identity+"_"+f for f in ALIGN_FIELDS)
            peer_values.append(aligned_levels(day,minutes,peers.get(identity,{}),identity))
        ov=np.stack([m.f.option_at(table,day,int(j),a[j,3]) if j>=5 else
                     np.full(len(m.f.OPTION_NAMES),np.nan) for j in minutes])
        dv=daily.get(day,np.full(len(daily_names),np.nan))
        nv=overnight.get(day,np.full(len(overnight_names),np.nan))
        day_blocks={"banks":(bank_names,np.column_stack(bank_values),bok),
                    "peers":(peer_names,np.column_stack(peer_values),pok),
                    "options":(m.f.OPTION_NAMES,ov,np.isfinite(ov[:,1])),
                    "global_daily":(daily_names,np.tile(dv,(len(rows),1)),np.full(len(rows),np.isfinite(dv).sum()>=4)),
                    "overnight":(overnight_names,np.tile(nv,(len(rows),1)),np.full(len(rows),np.isfinite(nv).any()))}
        for key,(ns,x,ok) in day_blocks.items():
            if key in names and names[key]!=ns:raise ValueError("Context schema changed")
            names[key]=tuple(ns)
            blocks[key].append(np.asarray(x,dtype=np.float32))
            available[key].append(np.asarray(ok,dtype=bool))
        prior.append(day)
    return {k:np.vstack(v) for k,v in blocks.items()},names,{k:np.concatenate(v) for k,v in available.items()}


def model_predict(x,train,val,evaluate,y,days):
    keep=np.isfinite(x[train]).mean(axis=0)>=.05
    if not keep.any():raise ValueError("No supported model features")
    with threadpool_limits(limits=1):
        model=m.direction_model("ridge",x[train][:,keep],y[train],m.day_weights(days[train]))
        vp=model.predict_proba(x[val][:,keep])[:,1]
        ep=model.predict_proba(x[evaluate][:,keep])[:,1]
        calibrated,state=m._calibrate_probability(vp,y[val],days[val],ep)
    return ep,calibrated,state,keep


def prior_predict(train,val,evaluate,y,days,minutes,signs):
    prior=float(m._avg(y[train],days[train]))
    bucket={}
    for sign in (-1,1):
        for clock in range(13):
            mask=train&(signs==sign)&(minutes//30==clock)
            if mask.sum()>=30 and len(set(days[mask]))>=10:bucket[(sign,clock)]=float(m._avg(y[mask],days[mask]))
    def clock(mask):return np.asarray([bucket.get((int(s),int(j)//30),prior) for s,j in zip(signs[mask],minutes[mask])])
    vp=clock(val);ep=clock(evaluate)
    fixed=np.full(int(evaluate.sum()),prior)
    calibrated,state=m._calibrate_probability(vp,y[val],days[val],ep)
    const,_=m._calibrate_probability(np.full(int(val.sum()),prior),y[val],days[val],fixed)
    return prior,{"constant_prior":(fixed,const),"direction_clock_prior":(ep,calibrated)},state


def metrics(prob,y,days,prior):
    result=m.probability_metrics(prob,y,days,prior)
    rename={"training_up_rate":"training_success_rate","mean_predicted_up_probability":"mean_predicted_success_probability",
            "classifier_direction_accuracy":"binary_outcome_accuracy"}
    result={rename.get(k,k):v for k,v in result.items()}
    for item in result["reliability_bins"]:item["observed_success_rate"]=item.pop("observed_up_rate")
    return result


def call_metrics(prob,y,days,signs,states):
    calls=prob>=CONFIDENCE;resolved=calls&(y>=0);positive=resolved&(y==1)
    unknown=calls&(y<0)&(states!="canceled_before_or_at_entry")
    n=int(calls.sum());scored=int(resolved.sum());hits=int(positive.sum())
    return {"calls":n,"call_sessions":len(set(days[calls])),"bullish_calls":int((calls&(signs==1)).sum()),
            "bearish_calls":int((calls&(signs==-1)).sum()),"coverage":n/len(prob),
            "called_outcome_states":dict(Counter(states[calls].tolist())),"resolved_calls":scored,
            "known_favorable_calls":hits,"conditional_favorable_rate":hits/scored if scored else None,
            "known_favorable_fraction_of_calls":hits/n if n else None,
            "possible_favorable_upper_fraction_of_calls":(hits+int(unknown.sum()))/n if n else None}


def assess_lane(core,extra,rows,available,feature_names,extra_names=()):
    days=np.asarray([x["session"] for x in rows]);minutes=np.asarray([x["signal_minute"] for x in rows])
    signs=np.asarray([x["direction"] for x in rows]);states=np.asarray([x["outcome_state"] for x in rows])
    y=np.asarray([x["success"] if x["success"] is not None else -1 for x in rows],dtype=int)
    available=np.asarray(available,dtype=bool)
    dates=sorted(set(days[available]))
    result={"supported_events":int(available.sum()),"supported_sessions":len(dates),
            "supported_outcomes":dict(Counter(states[available].tolist()))}
    if len(dates)<75:return {**result,"state":"insufficient_context_sessions"},{}
    tr,va,te=m.split_days(dates)
    train=available&np.isin(days,tr)&(y>=0);val=available&np.isin(days,va)&(y>=0)
    evaluate=available&np.isin(days,te);scored=evaluate&(y>=0)
    result.update(training_dates=tr,validation_dates=va,evaluation_dates=te,
                  rows={"train_resolved":int(train.sum()),"validation_resolved":int(val.sum()),
                        "evaluation_all":int(evaluate.sum()),"evaluation_resolved":int(scored.sum())},
                  evaluation_outcomes=dict(Counter(states[evaluate].tolist())))
    if any(len(set(days[mask]))<n or len(np.unique(y[mask]))<2
           for mask,n in ((train,40),(val,15),(scored,15))):
        return {**result,"state":"insufficient_resolved_sessions_or_classes"},{}
    prior,methods,prior_state=prior_predict(train,val,evaluate,y,days,minutes,signs)
    raw,cal,state,keep=model_predict(core,train,val,evaluate,y,days)
    methods["index_only"]=(raw,cal)
    retained={"index_only":[name for name,ok in zip(feature_names,keep) if ok]}
    calibration={"index_only":state,"direction_clock_prior":prior_state}
    if extra is not None:
        raw,cal,state,keep=model_predict(np.column_stack((core,extra)),train,val,evaluate,y,days)
        retained["context"]=[name for name,ok in zip(feature_names+tuple(extra_names),keep) if ok]
        if not keep[core.shape[1]:].any():return {**result,"state":"no_supported_extra_features"},{}
        methods["context"]=(raw,cal);calibration["context"]=state
    candidate="context" if extra is not None else "index_only"
    ey=y[evaluate];ed=days[evaluate];es=signs[evaluate];st=states[evaluate];ok=ey>=0
    result.update(state="assessed_conditional_first_passage",retained_features=retained,calibration=calibration,
                  methods={k:{"raw":metrics(v[0][ok],ey[ok],ed[ok],prior),
                              "calibrated":metrics(v[1][ok],ey[ok],ed[ok],prior),
                              "calls":call_metrics(v[1],ey,ed,es,st)} for k,v in methods.items()})
    refs=["constant_prior","direction_clock_prior"]+(["index_only"] if extra is not None else [])
    loss=(methods[candidate][1][ok]-ey[ok])**2
    result["paired_brier_differences"]={k:m.paired_day_interval(loss-(methods[k][1][ok]-ey[ok])**2,ed[ok]) for k in refs}
    c=result["methods"][candidate]["calls"]
    checks={"brier_beats_all_matched_references":all(v["interval_95"] is not None and v["interval_95"][1]<0
                                                   for v in result["paired_brier_differences"].values()),
            "minimum_call_support":c["calls"]>=100 and c["call_sessions"]>=30,
            "both_directions":c["bullish_calls"]>0 and c["bearish_calls"]>0}
    result["exploratory_evidence_checks"]=checks
    result["trade_qualified"]=False
    predictions={}
    for j,k in enumerate(np.flatnonzero(evaluate)):
        predictions[int(k)]={f"{name}_{kind}":float(v[i][j]) for name,v in methods.items()
                             for i,kind in enumerate(("raw_probability","calibrated_probability"))}
    return result,predictions


def run(root,stop,days=365,index_only=False,progress=print):
    maximum=m.MAX_CORE_DAYS if index_only else m.MAX_CONTEXT_DAYS
    if type(days) is not int or not 120<=days<=maximum or stop>datetime.now(h.IST).date():
        raise ValueError("Use completed dates and bounded history")
    service.DATA=root/"data"
    if not service.DATA.is_dir():raise ValueError("Shared data directory missing")
    start=stop-timedelta(days=days)
    index,stocks,membership,weights,peers,_,meta=m.load_sources(start,stop,wings=None,index_only=index_only,progress=progress)
    events,coverage=collect(index,progress)
    rows=[row for day in sorted(events) for row in events[day]]
    if not rows:raise ValueError("No supported crossover events")
    core=np.stack([row["core"] for row in rows]);core_names=CORE_FIELDS+CORE_TECH
    blocks={};names={};availability={}
    if not index_only:
        stamps={r._stamp(day,row["signal_minute"]+offset) for day,rr in events.items()
                for row in rr for offset in (0,-5) if row["signal_minute"]+offset>=0}
        try:
            progress("Verifying rolling option receipts at event clocks")
            table,options=opt._load_options([{"session":d} for d in sorted(events)],3,needed_stamps=stamps)
            meta["options"]={**options,"state":"loaded" if table else "unavailable","wings":3}
        except (ValueError,OSError,RuntimeError,TypeError,KeyError) as exc:
            table={};meta["options"]={"state":"unavailable","reason":str(exc)[:180]}
        try:
            daily,overnight,gmeta,dn,on=global_features(start,stop,sorted(events))
        except (ValueError,OSError,sqlite3.Error) as exc:
            daily={};overnight={};gmeta={"state":"unavailable","reason":str(exc)[:180]}
            dn=tuple(global_open.DAILY);on=tuple("BOATS_"+s for s in global_open.OVERNIGHT)
        meta["global"]=gmeta
        blocks,names,availability=context_blocks(index,events,stocks,membership,weights,peers,table,daily,overnight,dn,on,progress)
    del index,stocks,peers
    journal=[{k:v for k,v in row.items() if k!="core"} for row in rows]
    results={}
    for lane in ("core",) if index_only else ("core",*LANES):
        progress("Fitting matched first-passage lane "+lane)
        avail=np.ones(len(rows),dtype=bool) if lane=="core" else availability[lane]
        extra=None if lane=="core" else blocks[lane]
        result,pred=assess_lane(core,extra,rows,avail,core_names,names.get(lane,()))
        results[lane]=result
        method_names=("constant_prior","direction_clock_prior","index_only")+(("context",) if lane!="core" else ())
        fields=[name+"_"+kind for name in method_names for kind in ("raw_probability","calibrated_probability")]
        for i,row in enumerate(journal):
            row[lane+"_available"]=bool(avail[i])
            row[lane+"_evaluation"]=i in pred
            row.update({lane+"_"+key:pred.get(i,{}).get(key) for key in fields})
    return {"version":VERSION,"from_inclusive":start.isoformat(),"to_exclusive":stop.isoformat(),
            "observed_index_sessions":len(coverage),"crossovers":len(rows),"session_coverage":coverage,
            "outcome_counts":dict(Counter(row["outcome_state"] for row in rows)),"source_evidence":meta,
            "favorable_bps":FAVORABLE_BPS,"adverse_bps":ADVERSE_BPS,"delay_minutes":DELAY,
            "confidence":CONFIDENCE,"core_features":list(core_names),"lanes":results,
            "warning":("Retrospective same-session first-passage observation, not executable price, option P&L "
                       "or a direction-qualified trading system. Fixed +10/-5 bps barriers from delayed index open, "
                       "no known peak exit. Dual touches unresolved; reverse without barrier is a nonsuccess. "
                       "Canceled, missing and censored outcomes retained; metrics conditional on resolved outcomes, "
                       "predictions include supported unresolved evaluation candidates. Historical receipts and "
                       "archive-known 09:10 global factors are not proof of live availability. Per-lane chronological "
                       "cohorts chosen from signal-time support before outcome filtering, matched within each lane. "
                       "Bank/peer returns and EMA/level states as of BANKNIFTY clock, no invented weights; "
                       "rolling monthly option context is not exact contracts. Overnight ETF proxies not cash markets. "
                       "All inspected dates exploratory. No model selection, thresholds tuned, actual fills, "
                       "net returns, broker orders, or live promotion.")},journal


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--shared-root",type=Path,default=service.ROOT)
    ap.add_argument("--days",type=int,default=365)
    ap.add_argument("--to-date",default="2026-11-27")
    ap.add_argument("--index-only",action="store_true")
    args=ap.parse_args()
    try:
        root=args.shared_root.resolve()
        report,journal=run(root,date.fromisoformat(args.to_date),args.days,args.index_only,lambda s:print(s,flush=True))
        folder=root/"results";folder.mkdir(exist_ok=True)
        stem="banknifty_ema_first_passage_"+uuid.uuid4().hex
        path=folder/(stem+".json");csv_path=folder/(stem+"_events.csv")
        def writer(out):
            w=csv.DictWriter(out,fieldnames=list(journal[0]));w.writeheader();w.writerows(journal)
        write_atomic(csv_path,writer)
        report["events_csv"]=csv_path.name
        write_atomic(path,lambda out:json.dump(report,out,sort_keys=True,indent=2,allow_nan=False))
        print("CROSSOVERS",report["crossovers"],"OUTCOMES",json.dumps(report["outcome_counts"]))
        for key,lane in report["lanes"].items():
            summary={k:v for k,v in lane.items() if k not in ("training_dates","validation_dates","evaluation_dates","retained_features","methods")}
            if "methods" in lane:
                summary["methods"]={k:{"brier_raw":v["raw"]["brier"],"brier_calibrated":v["calibrated"]["brier"],
                                       "calls":v["calls"]} for k,v in lane["methods"].items()}
            print("FIRST_PASSAGE",key,json.dumps(summary))
        print("REPORT",path)
        print("EVENTS_CSV",csv_path)
        print(report["warning"])
        return 0
    except (ValueError,OSError,RuntimeError) as exc:
        print("First-passage benchmark unavailable:",str(exc)[:240])
        return 2


if __name__=="__main__":
    raise SystemExit(main())
