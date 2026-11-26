"""Matched incremental context research on the existing prospective ledger.

All comparison methods use the exact same eligible non-overlapping windows.
External archive availability is user-reviewed, not independently verified.
No prediction is exported into the live selector.
"""
from collections import Counter
from contextlib import closing
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import numpy as np

from . import constituent_alpha as a, market_context as m, context_events as events

SCOPES=("options","global","participants","events","combined","all")
GROUPS={"options":("options",),"global":("global",),"participants":("participants",),
        "events":("events",),"combined":("options","global","participants"),
        "all":("options","global","participants","events")}
VERSION="constituent_context_alpha_v2"
POLICY={"version":VERSION,"base_policy":a.POLICY_HASH,"context_version":m.VERSION,
        "groups":GROUPS,"option_features":m.OPTION_NAMES,"external_features":m.FEATURE_NAMES,
        "domestic_features":m.DOMESTIC_NAMES,"required_global_groups":m.GLOBAL_GROUPS,
        "event_version":events.VERSION,"event_features":events.FEATURE_NAMES,
        "participant_gate":"all four categories x three OI net position series with prior observation",
        "scope_matching":"base reserved windows are never replaced; drop missing required context; identical samples for every model",
        "fit":"fixed logistic and histogram boosting configurations from base study; calibration only on calibration sessions"}
POLICY_HASH=sha256(json.dumps(POLICY,sort_keys=True).encode()).hexdigest()

def policy_for(horizon):
    return POLICY_HASH if horizon in a.ORIGINAL_HORIZONS else sha256(json.dumps([POLICY_HASH,a.policy_for(horizon)],sort_keys=True).encode()).hexdigest()

def _attach(db,rows,timelines,scope):
    matched=[];counts=Counter();coverage=Counter()
    for r in rows:
        cutoff=a._stamp(r["cutoff_utc"])
        required=GROUPS[scope]
        counts["base_scored"]+=1
        vectors={};evidence={}
        if "options" in required:
            option=m.options_at(db,cutoff)
            if option:
                vectors["options"],evidence["options"]=option
                counts["options_available"]+=1
            else:
                counts["missing_options_context"]+=1
        if "global" in required or "participants" in required:
            vector,detail,global_ok=m.factor_at(timelines,cutoff)
            for k,v in detail.items():
                if v["state"]=="available":
                    coverage[k]+=1
            if "global" in required:
                if global_ok:
                    domestic,domestic_detail=m.domestic_at(db,cutoff,r["index"][2])
                    vectors["global"]=[v for i,(k,spec) in enumerate(m.FACTORS.items())
                        if spec[1]!="participants" for v in vector[i*4:i*4+4]]+domestic
                    evidence["global"]={k:v for k,v in detail.items()
                        if m.FACTORS[k][1]!="participants" and v["state"]=="available"}
                    evidence["domestic"]=domestic_detail
                    counts["global_available"]+=1
                    if domestic_detail is None:
                        counts["nifty50_missing"]+=1
                else:
                    counts["missing_global_context"]+=1
            if "participants" in required:
                keys=[c+"_"+v for c in ("FII","DII","CLIENT","PRO")
                    for v in ("INDEX_FUT_NET","INDEX_CALL_NET","INDEX_PUT_NET")]
                if all(detail[k]["state"]=="available" for k in keys):
                    vectors["participants"]=[v for i,(k,spec) in enumerate(m.FACTORS.items())
                        if spec[1]=="participants" for v in vector[i*4:i*4+4]]
                    evidence["participants"]={k:v for k,v in detail.items()
                        if m.FACTORS[k][1]=="participants" and v["state"]=="available"}
                    counts["participants_available"]+=1
                else:
                    counts["missing_participants_context"]+=1
        if "events" in required:
            item=events.features_at(db,cutoff)
            if item and item[1]["full_source_coverage"]:
                vectors["events"],evidence["events"]=item
                counts["events_available"]+=1
            else:
                counts["missing_events_context"]+=1
        if all(g in vectors for g in required):
            matched.append({**r,"context":vectors,"context_evidence":evidence})
            counts["context_matched"]+=1
    return matched,dict(counts),dict(coverage)

def _spec(scope):
    variants={"index_logistic":("index_logistic",()),
        "constituent_logistic":("constituent_logistic",()),
        "constituent_boosting":("constituent_boosting",())}
    for group in GROUPS[scope]:
        variants["constituent_"+group+"_logistic"]=("constituent_logistic",(group,))
    variants["constituent_"+scope+"_boosting"]=("constituent_boosting",GROUPS[scope])
    if len(GROUPS[scope])>1:
        variants["constituent_"+scope+"_logistic"]=("constituent_logistic",GROUPS[scope])
    return variants

def _view(rows,groups):
    return [{**r,"full":r["full"]+[x for g in groups for x in r["context"][g]]} for r in rows]

def _assess(train,cal,test,scope,progress=None):
    methods={"no_trade":a._directional_stats(test,[0]*len(test))}
    prior=np.asarray([(1+sum(r["class"]==c for r in train))/(len(train)+3) for c in a.CLASSES])
    probabilities={"training_class_prior":np.tile(prior,(len(test),1))}
    predictions={"no_trade":[0]*len(test)}
    variants=_spec(scope)
    for i,(name,(kind,groups)) in enumerate(variants.items()):
        if progress:
            progress(64+int(22*i/len(variants)),"Fitting matched "+name)
        fit=a._fit(kind,_view(train,groups))
        t=a._calibrate(a._predict(fit,_view(cal,groups)),cal)
        probabilities[name]=a._temperature(a._predict(fit,_view(test,groups)),t)
        methods[name]={"temperature":t}
    for name,probs in probabilities.items():
        predictions[name]=[a._call(v) for v in probs]
        methods.setdefault(name,{}).update(a._directional_stats(test,predictions[name],probs))
    base=methods["constituent_logistic"]["brier"]
    index=methods["index_logistic"]["brier"]
    prior_brier=methods["training_class_prior"]["brier"]
    for name,(kind,groups) in variants.items():
        item=methods[name]
        same_family=methods["constituent_boosting" if kind=="constituent_boosting" else "constituent_logistic"]["brier"]
        item["brier_skill_vs_prior"]=1-item["brier"]/prior_brier if prior_brier>0 else None
        item["brier_skill_vs_index_logistic"]=1-item["brier"]/index if index>0 else None
        item["brier_skill_vs_constituent_logistic"]=1-item["brier"]/base if base>0 else None
        item["brier_skill_vs_same_family_constituent"]=1-item["brier"]/same_family if same_family>0 else None
        item["descriptive_gate_passed"]=bool(item["brier"]<prior_brier and
            (name=="index_logistic" or item["brier"]<index) and
            (not groups or item["brier"]<same_family) and item["directional_calls"]>=20
            and item["call_sessions"]>=10 and item["mean_net_index_proxy_bps"] is not None
            and item["mean_net_index_proxy_bps"]>0)
    regimes={}
    for regime in ("trend_up","trend_down","compression","range"):
        idx=[i for i,r in enumerate(test) if r["regime"]==regime]
        regimes[regime]={"samples":len(idx),"methods":{}}
        if idx:
            for name in variants:
                regimes[regime]["methods"][name]=a._directional_stats(
                    [test[i] for i in idx],[predictions[name][i] for i in idx],probabilities[name][idx])
    q,quantiles=a._quantiles(_view(train,GROUPS[scope]),_view(test,GROUPS[scope]))
    records=[]
    for i,r in enumerate(test):
        evidence=json.dumps(r["context_evidence"],sort_keys=True,separators=(",",":"))
        for name,calls in predictions.items():
            call=calls[i];pr=probabilities[name][i] if name in probabilities else (None,None,None)
            records.append({"method":name,"session":r["session"],"cutoff_utc":r["cutoff_utc"],
                "decision_utc":r["decision_utc"],"target_utc":r["target_utc"],"regime":r["regime"],
                "actual_return_bps":r["return_bps"],"actual_class":r["class"],
                "call":call,"p_down":pr[0],"p_flat":pr[1],"p_up":pr[2],
                "net_index_proxy_bps":call*r["return_bps"]-a.COST_BPS if call else 0.,
                "q10_bps":None,"q50_bps":None,"q90_bps":None,"context_evidence_json":evidence if name=="no_trade" else ""})
        records.append({"method":"context_quantile","session":r["session"],"cutoff_utc":r["cutoff_utc"],
            "decision_utc":r["decision_utc"],"target_utc":r["target_utc"],"regime":r["regime"],
            "actual_return_bps":r["return_bps"],"actual_class":r["class"],"call":None,
            "p_down":None,"p_flat":None,"p_up":None,"net_index_proxy_bps":None,
            "q10_bps":q[i,0],"q50_bps":q[i,1],"q90_bps":q[i,2],"context_evidence_json":""})
    return methods,regimes,quantiles,records

def _walk(train,dates,scope,progress=None):
    out=[]
    for size,width in a.POLICY["development_walk_forward"]:
        early=[r for r in train if r["session"] in set(dates[:size])]
        later=[r for r in train if r["session"] in set(dates[size:size+width])]
        item={"train_dates":dates[:size],"test_dates":dates[size:size+width],
              "train_support":a.support(early),"test_support":a.support(later),
              "state":"insufficient_support","methods":{}}
        if a._supported(early,40,12,train=True) and a._supported(later,10,3):
            item["state"]="available"
            for name,(kind,groups) in _spec(scope).items():
                if progress:
                    progress(61,"Development context walk-forward: "+name)
                probs=a._predict(a._fit(kind,_view(early,groups)),_view(later,groups))
                item["methods"][name]=a._directional_stats(later,[a._call(x) for x in probs],probs)
        out.append(item)
    return out

def run(*,horizon=30,scope="combined",mode="receipt",cohort="original",progress=None,now=None):
    if scope not in SCOPES or mode not in ("receipt","archive"):
        raise ValueError("Unknown context scope or availability mode")
    if cohort not in ("original","registered"):
        raise ValueError("Unknown context cohort")
    registered=None
    if cohort=="registered":
        if mode!="receipt":
            raise ValueError("Forward cohorts require receipt mode")
        from . import context_cohort
        registered=context_cohort.get(scope,horizon)
        if not registered:
            raise ValueError("Register the forward cohort before running research")
    status=a.readiness(horizon,now=now,start_session=registered["start_session"]) if registered else a.readiness(horizon,now=now)
    status.update(cohort=cohort,cohort_registration=registered,version=VERSION,policy_sha256=policy_for(horizon),context_scope=scope,context_mode=mode)
    dates=status["training_dates"]+status["calibration_dates"]+status["holdout_dates"]
    samples=[];counts=Counter();audit=[];coverage=Counter();meta={"rows":0,"ambiguous_factors":[]}
    if dates:
        start=datetime.fromisoformat(dates[0]+"T00:00:00+00:00")
        stop=datetime.fromisoformat(dates[-1]+"T23:59:59+00:00")
        with closing(a._read()) as db:
            timelines,meta=m.load_timelines(db,start,stop,mode) if any(g in GROUPS[scope] for g in ("global","participants")) else ({},meta)
            for i,day in enumerate(dates):
                if progress:
                    progress(2+55*i/len(dates),"Auditing context at original decision cutoffs: "+day)
                base,base_counts=a.sample_day(a._rows(db,day,horizon))
                matched,context_counts,covered=_attach(db,base,timelines,scope)
                samples.extend(matched);counts.update(base_counts);counts.update(context_counts);coverage.update(covered)
                audit.append({"day":day,**base_counts,**context_counts})
    splits=[status[k] for k in ("training_dates","calibration_dates","holdout_dates")]
    train,cal,test=([r for r in samples if r["session"] in set(part)] for part in splits)
    status.update(evidence_counts=dict(counts),session_audit=audit,context_factor_coverage=dict(coverage),context_import_meta=meta,
        support={"training":a.support(train),"calibration":a.support(cal),"holdout":a.support(test)},
        methods={},regimes={},quantiles=None,walk_forward=[],run_id=None,
        broker_orders_enabled=False,live_model_promoted=False,
        warning="Context research on the same frozen, matched windows. Receipt mode requires actual import time; archive mode trusts reviewed availability timestamps, not independent prospective evidence. "
        "Participant reports are aggregate index derivatives, not BANKNIFTY-specific retail orders. Option OI is two-sided, not dealer gamma or trade direction. "
        "Official event counts and release dates use actual local receipts, not inferred sentiment or surprise values, including in archive mode. "
        "The fixed 5 bps index cost proxy is hypothetical. No model is promoted to live trading. Descriptive holdout gates are not significance or profit guarantees.")
    if len(dates)<status.get("required_sessions",a.REQUIRED):
        status["state"]="awaiting_recorded_sessions"
    elif not (a._supported(train,60,20,train=True) and a._supported(cal,20,7) and a._supported(test,40,12)):
        status["state"]="insufficient_matched_evidence"
    else:
        status["walk_forward"]=_walk(train,splits[0],scope,progress)
        methods,regimes,q,records=_assess(train,cal,test,scope,progress)
        status.update(state="holdout_assessment_available",methods=methods,regimes=regimes,quantiles=q,
                      run_id=a._save(records),prediction_rows=len(records))
    records=[{"day":"RUN_SUMMARY","state":status["state"],"context_scope":scope,"context_mode":mode,
        "counts_json":json.dumps(dict(counts),sort_keys=True),"factor_coverage_json":json.dumps({"coverage":dict(coverage),"cohort":registered},sort_keys=True),
        "support_json":json.dumps(status["support"],sort_keys=True),"policy_sha256":policy_for(horizon)}]
    for row in audit:
        records.append({"day":row["day"],"state":"recorded_session","context_scope":scope,"context_mode":mode,
            "counts_json":json.dumps({k:v for k,v in row.items() if k!="day"},sort_keys=True),
            "factor_coverage_json":"","support_json":"","policy_sha256":policy_for(horizon)})
    status["audit_id"]=a._save(records,audit=True)
    if progress:
        progress(100,"Matched context research report saved")
    return status
