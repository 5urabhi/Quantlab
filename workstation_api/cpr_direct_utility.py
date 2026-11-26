"""Direct cost-adjusted return and execution-risk research.

Long-option, fixed-target/stop historical proxies only. Fit on earlier
trajectories; predict using decision-time inputs, never future fill status.
Stress utility charges full reserved funding for an unresolved or delayed
attempt; it is a deliberately adverse scenario, not an actual P&L bound.
"""
from collections import Counter,defaultdict
from math import isfinite,log1p
import numpy as np
from sklearn.ensemble import RandomForestRegressor,RandomForestClassifier

VERSION="direct_stress_utility_v1"
LOOKBACK=10
MAX_DELAY=2
MIN_VAL_TRADES=10
MIN_VAL_DAYS=5
THRESHOLDS=(0.,.005,.01)
MAX_BAD_PROBABILITY=.10
TRIGGERS=("target_first","stop_first","other_exit","unverified_or_delayed")
FEATURE_NAMES=("observed_10m_fraction","observed_last_3","log_median_volume","premium_move_5m_fraction","premium_move_missing")


def execution_features(r,signal,table,strike):
    day,m,side=signal["session"],signal["minute"],signal["side"]
    history=[r._observed(table,day,k,side,strike) if k>=0 else None for k in range(m-LOOKBACK+1,m+1)]
    if history[-1] is None:
        return None
    volume=[x["volume"] for x in history if x is not None and isfinite(x["volume"])]
    old=history[-6]
    current=history[-1]
    move=current["close"]/old["close"]-1 if old else 0.
    values=[sum(x is not None for x in history)/LOOKBACK,float(all(x is not None for x in history[-3:])),
            log1p(float(np.median(volume))) if volume else 0.,move,float(old is None)]
    return values if all(isfinite(x) for x in values) else None


def _timely(result):
    return (result["state"]=="complete" and result.get("exit_delay_minutes",0)<=MAX_DELAY
            and not result.get("exit_after_squareoff",False) and result.get("reason")!="monitoring_gap_exit")


def target(r,ep):
    # All signal-time candidate paths are counted, including missing entry.
    # No hindsight rejection or zero-P&L substitution for missing outcomes.
    result=r._exit(ep,"fixed_stop")
    good=_timely(result)
    observed=result.get("net") if result["state"]=="complete" else None
    funding=ep["planned_funding"]
    if not isfinite(funding) or funding<=0:
        raise ValueError("Invalid planned funding")
    realized=observed/funding if observed is not None else None
    # Delayed observations are retained for conditional reporting but penalized
    # at full planned funding in this separate adverse scenario.
    stress=realized if good else min(-1.,realized) if realized is not None else -1.
    reason=result.get("reason")
    failure_reason=(None if good else result["state"] if result["state"]!="complete" else
                    "late_squareoff" if result.get("exit_after_squareoff") else
                    "monitoring_gap" if reason=="monitoring_gap_exit" else "delayed_exit")
    trigger="unverified_or_delayed" if not good else "target_first" if reason=="target" else "stop_first" if reason=="stop" else "other_exit"
    return {"timely":good,"bad":int(not good),"trigger":trigger,"failure_reason":failure_reason,"observed_net_per_planned_funding":realized,
            "timely_net_per_planned_funding":realized if good else None,"stress_utility":stress}


def _available(ep):
    v=ep.get("context_vectors",{})
    return ("planned_funding" in ep and "execution" in v and "regime" in v and "features" in ep)


def _design(ep,regime):
    v=ep["context_vectors"]
    return ep["features"]+v["execution"]+(v["regime"] if regime else [])


def _predict(bundle,rows):
    if bundle.get("frozen"):
        from .cpr_forward_utility import predict
        return predict(bundle,rows)
    if not rows:
        return []
    x=[_design(ep,bundle["regime"]) for ep in rows]
    expected=bundle["stress"].predict(x)
    # Tree estimates are correlated; this is a disagreement heuristic, not
    # a calibrated prediction interval or a mathematical confidence bound.
    members=np.asarray([tree.predict(x) for tree in bundle["stress"].estimators_])
    q=np.quantile(members,.2,axis=0)
    conditional=bundle["conditional"].predict(x)
    risk=bundle["failure"]
    prob=risk.predict_proba(x)[:,list(risk.classes_).index(1)] if 1 in risk.classes_ else np.zeros(len(x))
    trigger=bundle["trigger"]
    raw=trigger.predict_proba(x)
    ordered=np.zeros((len(x),len(TRIGGERS)))
    ordered[:,[TRIGGERS.index(c) for c in trigger.classes_]]=raw
    return [{"expected_stress_utility":float(ev),"tree_disagreement_p20":float(lo),
             "expected_timely_net_return":float(c),"predicted_execution_failure":float(p),
             "trigger_probabilities":dict(zip(TRIGGERS,map(float,t)))}
            for ev,lo,c,p,t in zip(expected,q,conditional,prob,ordered)]


def _fit(r,episodes,regime):
    rows=[(ep,target(r,ep)) for ep in episodes if _available(ep)]
    timely=[(ep,y) for ep,y in rows if y["timely"]]
    days={ep["session"] for ep,_ in rows}
    info={"paths":len(rows),"sessions":len(days),"timely_paths":len(timely),
          "timely_days":len({ep["session"] for ep,_ in timely}),
          "execution_failure_paths":len(rows)-len(timely),
          "execution_failure_reasons":dict(Counter(y["failure_reason"] for _,y in rows if not y["timely"]))}
    if len(days)<20 or info["timely_days"]<15 or len(timely)<40 or len(rows)<100:
        return None,info
    X=[_design(ep,regime) for ep,_ in rows]
    weights=r._anchor_weights(rows)
    common=dict(n_estimators=80,max_depth=4,min_samples_leaf=15,random_state=72,n_jobs=1)
    stress=RandomForestRegressor(**common).fit(X,[y["stress_utility"] for _,y in rows],sample_weight=weights)
    failure=RandomForestClassifier(**common).fit(X,[y["bad"] for _,y in rows],sample_weight=weights)
    trigger=RandomForestClassifier(**common).fit(X,[y["trigger"] for _,y in rows],sample_weight=weights)
    conditional=RandomForestRegressor(**common).fit([_design(ep,regime) for ep,_ in timely],
                    [y["timely_net_per_planned_funding"] for _,y in timely],sample_weight=r._anchor_weights(timely))
    info.update(stress_prior=float(np.average([y["stress_utility"] for _,y in rows],weights=weights)),
                failure_prior=float(np.average([y["bad"] for _,y in rows],weights=weights)),
                conditional_prior=float(np.average([y["timely_net_per_planned_funding"] for _,y in timely],weights=r._anchor_weights(timely))))
    info["trigger_prior"]={k:float(np.average([y["trigger"]==k for _,y in rows],weights=weights)) for k in TRIGGERS}
    return {"stress":stress,"failure":failure,"conditional":conditional,"trigger":trigger,"regime":regime},info


def _metrics(r,bundle,info,episodes):
    rows=[(ep,target(r,ep)) for ep in episodes if _available(ep)]
    if not rows:
        return {"scored_paths":0}
    pred=_predict(bundle,[ep for ep,_ in rows])
    w=r._anchor_weights(rows)
    y=np.asarray([v["stress_utility"] for _,v in rows])
    bad=np.asarray([v["bad"] for _,v in rows])
    ev=np.asarray([v["expected_stress_utility"] for v in pred])
    fail=np.asarray([v["predicted_execution_failure"] for v in pred])
    timely=[i for i,(_,v) in enumerate(rows) if v["timely"]]
    out={"scored_paths":len(rows),"sessions":len({ep["session"] for ep,_ in rows}),
         "timely_paths":len(timely),"execution_failure_reasons":dict(Counter(v["failure_reason"] for _,v in rows if not v["timely"])),
         "stress_rmse":float(np.sqrt(np.average((ev-y)**2,weights=w))),
         "stress_prior_rmse":float(np.sqrt(np.average((info["stress_prior"]-y)**2,weights=w))),
         "stress_mean_forecast":float(np.average(ev,weights=w)),"stress_mean_observed":float(np.average(y,weights=w)),
         "failure_brier":float(np.average((fail-bad)**2,weights=w)),
         "failure_prior_brier":float(np.average((info["failure_prior"]-bad)**2,weights=w)),
         "mean_failure_forecast":float(np.average(fail,weights=w)),"observed_failure_fraction":float(np.average(bad,weights=w))}
    truth=np.asarray([[float(y["trigger"]==k) for k in TRIGGERS] for _,y in rows])
    trig=np.asarray([[p["trigger_probabilities"][k] for k in TRIGGERS] for p in pred])
    prior=np.asarray([info["trigger_prior"][k] for k in TRIGGERS])
    out.update(trigger_brier=float(np.average(np.sum((trig-truth)**2,axis=1),weights=w)),
        trigger_prior_brier=float(np.average(np.sum((prior-truth)**2,axis=1),weights=w)),
        trigger_mean_forecast=dict(zip(TRIGGERS,map(float,np.average(trig,axis=0,weights=w)))),
        trigger_observed=dict(zip(TRIGGERS,map(float,np.average(truth,axis=0,weights=w)))))
    if timely:
        ret=np.asarray([rows[i][1]["timely_net_per_planned_funding"] for i in timely])
        f=np.asarray([pred[i]["expected_timely_net_return"] for i in timely])
        ww=r._anchor_weights([rows[i] for i in timely])
        out.update(conditional_return_rmse=float(np.sqrt(np.average((f-ret)**2,weights=ww))),
                   conditional_prior_rmse=float(np.sqrt(np.average((info["conditional_prior"]-ret)**2,weights=ww))),
                   conditional_mean_forecast=float(np.average(f,weights=ww)),conditional_mean_observed=float(np.average(ret,weights=ww)))
    return out


def _admissible(ep,pred,threshold):
    x=ep["context_vectors"]["execution"]
    return (x[0]>=.8 and x[1]==1. and pred["predicted_execution_failure"]<=MAX_BAD_PROBABILITY
            and pred["expected_timely_net_return"]>0 and pred["expected_stress_utility"]>threshold
            and pred["tree_disagreement_p20"]>0)


def _rank(bundle,candidates,nearest,threshold):
    from .cpr_ranked_entries import key
    available=[ep for ep in candidates if _available(ep)]
    by_anchor=defaultdict(list)
    for ep,pred in zip(available,_predict(bundle,available)):
        if _admissible(ep,pred,threshold):
            by_anchor[key(ep)].append((pred["expected_stress_utility"],pred["tree_disagreement_p20"],
                -ep["planned_funding"],-abs(ep["strike"]-ep["spot"]),-ep["strike"],ep,pred))
    out=[]
    for ep in nearest:
        options=by_anchor.get(key(ep))
        if not options:
            out.append({**ep,"utility_accepted":False})
            continue
        *_,choice,pred=max(options,key=lambda v:v[:-2])
        out.append({**choice,"utility_accepted":True,"utility_forecast":pred,
                    "minimum_funding_inr":ep.get("minimum_funding_inr"),"entry_type":ep.get("entry_type")})
    return out


def _strict(r,rows,dates,capital,budget,*,filtered=False):
    return r._evaluate(rows,method="fixed_stop",capital=capital,risk_budget=budget,dates=dates,
                       strict_execution=True,context_filter=(lambda e:e.get("utility_accepted",False)) if filtered else None)


def _gate(metrics):
    return (metrics["scored_trades"]>=MIN_VAL_TRADES
            and metrics["daily_coverage"]["days_with_scored_trade"]>=MIN_VAL_DAYS
            and not metrics["unresolved_trades"] and not metrics["exits_after_1520"] and not metrics["stress_failed_attempts"]
            and (metrics["max_exit_delay_minutes"] or 0)<=MAX_DELAY
            and metrics["stress_utility_inr"]>0)


def assess(r,*,train,val,pools,nearest,dates,capital,budget,freeze_policy=False):
    va_pool,te_pool=pools;va_near,te_near=nearest
    # Same candidates for both models. Keep absent contexts as abstentions
    # in account evaluation rather than excluding their sessions.
    tr=[ep for ep in train if _available(ep)]
    vv=[ep for ep in val if _available(ep)]
    report={"version":VERSION,"models":{},"methods":{},"live_model_promoted":False,
            "warning":"Full-funding stress is a scenario, not a certified loss bound. "
                      "Observed OHLC and minute volume are not bid/ask or fill proof. "
                      "Tree disagreement is not a calibrated lower confidence bound."}
    journal=[]
    baseline,rows=_strict(r,te_near,dates[1],capital,budget)
    report["methods"]["strict_fixed_stop"]=baseline
    journal.extend({**row,"method":"strict_fixed_stop"} for row in rows)
    for name,regime in (("technical_execution",False),("regime_execution",True)):
        model,info=_fit(r,tr,regime)
        item={"training":info,"state":"insufficient_support"};report["models"][name]=item
        if model is None:
            continue
        item.update(state="exploratory_assessment",validation=_metrics(r,model,info,vv),holdout=_metrics(r,model,info,te_pool))
        best=None;trials=[]
        for threshold in THRESHOLDS:
            selected=_rank(model,va_pool,va_near,threshold)
            metrics,_=_strict(r,selected,dates[0],capital,budget,filtered=True)
            eligible=_gate(metrics)
            trials.append({"threshold":threshold,"eligible":eligible,"scored":metrics["scored_trades"],
                "days":metrics["daily_coverage"]["days_with_scored_trade"],"conditional_net_inr":metrics["conditional_net_inr"],
                "stress_utility_inr":metrics["stress_utility_inr"],"unresolved":metrics["unresolved_trades"],
                "stress_failed_attempts":metrics["stress_failed_attempts"],
                "max_exit_delay_minutes":metrics["max_exit_delay_minutes"]})
            if eligible:
                score=(metrics["stress_utility_inr"],threshold)
                if best is None or score>best[0]:
                    best=(score,threshold)
        chosen=best[1] if best else None
        item["gate"]={"trials":trials,"selected_threshold":chosen,
                      "state":"validation_selected" if best else "abstain_no_supported_validation_gate"}
        if chosen is None:
            report["methods"][name]={"state":"abstain_no_supported_validation_gate","scored_trades":0}
            continue
        if freeze_policy and name=="regime_execution":
            from .cpr_forward_utility import export_bundle
            report["frozen_candidate"]={"threshold":chosen,"bundle":export_bundle(model)}
        selected=_rank(model,te_pool,te_near,chosen)
        metrics,rows=_strict(r,selected,dates[1],capital,budget,filtered=True)
        report["methods"][name]=metrics
        journal.extend({**row,"method":name} for row in rows)
    return report,journal
