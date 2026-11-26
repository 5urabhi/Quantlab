"""Development-calibrated entry ranking with matched context ablations.

All selection uses training/validation only. Candidate choice depends on
signal-time features and planned funding, never subsequent path availability.
"""
from collections import Counter, defaultdict
import numpy as np

from . import cpr_context_features as cx

TEMPERATURES=(.75,1.,1.5,2.,3.)
PRIOR_SHRINK=(0.,.25,.5,1.)
THRESHOLDS=(.10,.15,.20,.25,.35,.50)
MIN_VAL_TRADES=5
MIN_VAL_DAYS=3


class Calibrated:
    def __init__(self,model,temperature=1.,bias=None,threshold=1.1):
        self.model=model
        self.classes_=model.classes_
        self.temperature=temperature
        self.bias=np.zeros(len(self.classes_)) if bias is None else np.asarray(bias,dtype=float)
        self.target_threshold=threshold

    def predict_proba(self,X):
        raw=np.clip(self.model.predict_proba(X),1e-9,1.)
        logits=np.log(raw)/self.temperature+self.bias
        logits-=logits.max(axis=1,keepdims=True)
        exp=np.exp(logits)
        return exp/exp.sum(axis=1,keepdims=True)


def _priors(r,rows,classes):
    weights=r._anchor_weights(rows)
    counts=np.ones(len(classes))
    for (_,out),weight in zip(rows,weights):
        counts[list(classes).index(r._label(out))]+=weight
    return counts/counts.sum()


def calibrate(r,model,train,validation):
    tr=r._training_rows(train);va=r._training_rows(validation)
    X=[e["features"] for e,_ in va]
    truth=np.asarray([[float(r._label(out)==c) for c in model.classes_] for _,out in va])
    weights=np.asarray(r._anchor_weights(va))
    base_prior=_priors(r,tr,model.classes_)
    val_prior=_priors(r,va,model.classes_)
    shift=np.log(val_prior/base_prior)
    best=None
    # Identity transform is always in the search. Bias adjusts class-prior
    # shift with shrinkage; temperature controls confidence. This is development
    # tuning on the same validation set as model selection, not test calibration.
    for temp in TEMPERATURES:
        for shrink in PRIOR_SHRINK:
            wrapped=Calibrated(model,temp,shift*shrink)
            brier=float(np.average(np.sum((wrapped.predict_proba(X)-truth)**2,axis=1),weights=weights))
            rank=(brier,abs(temp-1),shrink)
            if best is None or rank<best[0]:
                best=(rank,wrapped,temp,shrink)
    raw=Calibrated(model)
    raw_brier=float(np.average(np.sum((raw.predict_proba(X)-truth)**2,axis=1),weights=weights))
    prior_brier=float(np.average(np.sum((base_prior-truth)**2,axis=1),weights=weights))
    return best[1],{"temperature":best[2],"prior_shift_shrinkage":best[3],
                   "validation_brier_raw":raw_brier,"validation_brier_calibrated":best[0][0],
                   "validation_brier_training_prior":prior_brier,
                   "training_prior":dict(zip(model.classes_,map(float,base_prior))),
                   "validation_prior":dict(zip(model.classes_,map(float,val_prior)))}


def key(ep):
    return (ep["session"],ep["minute"],ep["side"])


def _predict(r,model,means,ep):
    prob=dict(zip(model.classes_,map(float,model.predict_proba([ep["features"]])[0])))
    return sum(prob[c]*means[c] for c in r.CLASSES),prob["target"]


def rank(r,model,means,candidates,nearest):
    by_anchor=defaultdict(list)
    # Predict in batches for CPU efficiency. No state/outcome filters.
    valid=[ep for ep in candidates if "planned_funding" in ep]
    probs=model.predict_proba([ep["features"] for ep in valid]) if valid else []
    for ep,row in zip(valid,probs):
        pr=dict(zip(model.classes_,map(float,row)))
        ev=sum(pr[c]*means[c] for c in r.CLASSES);target=pr["target"]
        admissible=ev>0 and target>=model.target_threshold
        by_anchor[key(ep)].append((admissible,ev,target,-abs(ep["strike"]-ep["spot"]),
                                  -ep["strike"],ep))
    selected=[]
    for ep in nearest:
        ranked=by_anchor.get(key(ep))
        if not ranked:
            selected.append(ep)
            continue
        _,ev,target,_,_,choice=max(ranked,key=lambda v:v[:-1])
        selected.append({**choice,"entry_type":ep.get("entry_type"),
                         "observed_side_quotes":ep.get("observed_side_quotes"),
                         "qualified_contracts":ep.get("qualified_contracts"),
                         "minimum_funding_inr":ep.get("minimum_funding_inr"),
                         "ranked_expected_return":ev,"ranked_target_probability":target,
                         "ranked_candidate_count":len(ranked)})
    return selected


def _candidate_paths(r,signals,table,index,*,hold,lot_size,bps,risk_budget):
    # Only validation/test account pools. No price-path or result filters.
    rows=[]
    for s in signals:
        pool,_=r._candidate_pool(s,table,lot_size=lot_size,max_lots=1,bps=bps)
        for candidate in pool:
            if candidate[4]<=risk_budget:
                rows.append(r._episode(s,table,index[s["session"]],hold=hold,lot_size=lot_size,
                            max_lots=1,risk_budget=risk_budget,bps=bps,candidate=candidate))
    return rows


def _threshold(r,model,means,candidates,nearest,dates,capital,risk_budget):
    studies=[]
    best=None
    for threshold in THRESHOLDS:
        model.target_threshold=threshold
        ranked=rank(r,model,means,candidates,nearest)
        result,_=r._evaluate(ranked,method="ml_fixed",capital=capital,risk_budget=risk_budget,
                              model=model,means=means,dates=dates)
        n=result["scored_trades"];days=result["daily_coverage"]["days_with_scored_trade"]
        net=result["conditional_net_inr"]
        supported=bool(n>=MIN_VAL_TRADES and days>=MIN_VAL_DAYS and not result["unresolved_trades"]
                       and not result["exits_after_1520"] and (result["max_exit_delay_minutes"] or 0)<=2
                       and net is not None and net>0)
        studies.append({"threshold":threshold,"scored":n,"days":days,"conditional_net_inr":net,
                        "unresolved":result["unresolved_trades"],"max_exit_delay_minutes":result["max_exit_delay_minutes"],
                        "late_squareoffs":result["exits_after_1520"],"eligible":supported})
        if supported:
            score=(net,days,-threshold)
            if best is None or score>best[0]:
                best=(score,threshold)
    model.target_threshold=best[1] if best else 1.1
    return {"state":"validation_threshold_selected" if best else "no_supported_positive_validation_gate",
            "selected_threshold":best[1] if best else None,"development_trials":studies}


def _model(r,train,val,candidates,nearest,dates,capital,risk_budget):
    base,means,info=r._fit_ml(train,val)
    if base is None:
        return None,{},info
    model,cal=calibrate(r,base,train,val)
    selection=_threshold(r,model,means,candidates,nearest,dates,capital,risk_budget)
    info.update(calibration=cal,gate=selection)
    return model,means,info


def _matched(episodes,scope):
    return cx.view(episodes,scope)


def assess(r,*,signals,table,index,train,val,test,dates,hold,lot_size,bps,capital,risk_budget,
           context_audit,q=None,pattern_research=False,fixed_panel=False,context_q=False,progress=None):
    val_days,test_days=map(set,dates)
    val_signals=[s for s in signals if s["session"] in val_days]
    test_signals=[s for s in signals if s["session"] in test_days]
    pools=_candidate_paths(r,val_signals+test_signals,table,index,hold=hold,lot_size=lot_size,bps=bps,risk_budget=risk_budget)
    val_pool=[e for e in pools if e["session"] in val_days]
    test_pool=[e for e in pools if e["session"] in test_days]
    results={};journal=[]
    scopes=["technical"] if context_audit.get("state")=="disabled" else list(cx.SCOPES)
    if fixed_panel and context_audit.get("state")!="disabled":
        scopes.extend(cx.PANEL_SCOPES)
    if pattern_research:
        scopes.append("patterns")
        if context_audit.get("state")!="disabled":
            scopes.extend(("global_patterns","combined_patterns"))
            if fixed_panel:
                scopes.append("panel_global_patterns")
    # 'val' contains capital-independent learning trajectories; nearest actual
    # candidate episodes are built separately to match the trading account.
    nearest_val=[r._episode(s,table,index[s["session"]],hold=hold,lot_size=lot_size,
                max_lots=1,risk_budget=risk_budget,bps=bps) for s in val_signals]
    for scope in scopes:
        if progress:progress(75,"Calibrating ranked entry scope: "+scope)
        tr=_matched(train,scope);va=_matched(val,scope)
        vp=_matched(val_pool,scope);tp=_matched(test_pool,scope)
        nv=_matched(nearest_val,scope);nt=_matched(test,scope)
        # Compare matched technical features on exactly the same scope rows,
        # before expanding features. Recover original rows by anchor and strike.
        item={"state":"insufficient_matched_support","training_paths":len(tr),
              "validation_paths":len(va),"matched_test_signals":len(nt),
              "affordable_test_candidates":len(tp),"models":{},"methods":{}}
        results[scope]=item
        variants=("technical",) if scope=="technical" else ("matched_technical",scope)
        # Reconstruct the technical slice by fixed original feature length;
        # no test labels enter fitting/calibration.
        nbase=len(train[0]["features"]) if train else 0
        for variant in variants:
            technical=variant in ("technical","matched_technical")
            def original(rows):
                return [{**e,"features":e["features"][:nbase]} for e in rows] if technical else rows
            trv,vav,vpv,tpv,nvv,ntv=map(original,(tr,va,vp,tp,nv,nt))
            model,means,info=_model(r,trv,vav,vpv,nvv,dates[0],capital,risk_budget)
            item["models"][variant]=info
            if model is None:
                continue
            item["state"]="exploratory_assessment"
            info["matched_nearest_holdout"]=r._holdout_ml(model,ntv)
            scored=r._training_rows(ntv)
            if scored:
                prior=info["calibration"]["training_prior"]
                prior_brier=float(np.mean([sum((prior[c]-float(r._label(out)==c))**2
                                               for c in r.CLASSES) for _,out in scored]))
                score=info["matched_nearest_holdout"]["brier"]
                info["matched_nearest_holdout"].update(training_prior_brier=prior_brier,
                    brier_skill_vs_training_prior=1-score/prior_brier if prior_brier>0 else None)
            chosen=rank(r,model,means,tpv,ntv)
            for method in ("ml_fixed","ml_trailing_stop","ml_offline_q"):
                name=scope+":"+variant+":"+method
                if model.target_threshold>1:
                    item["methods"][name]={"state":"no_supported_positive_validation_gate"}
                    continue
                if method=="ml_offline_q" and not q:
                    item["methods"][name]={"state":"insufficient_q_training_support"}
                    continue
                metrics,rows=r._evaluate(chosen,method=method,capital=capital,risk_budget=risk_budget,
                                  model=model,means=means,q=q,dates=dates[1])
                item["methods"][name]=metrics
                journal.extend({**row,"method":name} for row in rows)
        if scope!="technical":
            # Same signal subset, same budget; this is a matched rule-based
            # comparator, not a comparison of differing market days.
            metrics,rows=r._evaluate(nt,method="fixed_stop",capital=capital,risk_budget=risk_budget,dates=dates[1])
            name=scope+":matched_fixed_stop"
            item["methods"][name]=metrics
            journal.extend({**row,"method":name} for row in rows)
            metrics,rows=r._evaluate(nt,method="fixed_stop",capital=capital,risk_budget=risk_budget,
                                    dates=dates[1],context_filter=lambda e:cx.rule_accept(e,scope))
            name=scope+":context_rule_fixed_stop"
            item["methods"][name]=metrics
            journal.extend({**row,"method":name} for row in rows)
            if context_q:
                # Train both Q variants on the same context-supported earlier
                # trajectories. Do not choose Q on the evaluated P&L.
                tq,ti=r._fit_q(tr)
                cq,ci=r._fit_q(tr,context_scope=scope)
                item["context_q"]={"matched_technical":ti,"contextual":ci}
                for label,method,policy,info in (("matched_technical_q","offline_q",tq,ti),
                                                  ("contextual_q","contextual_q",cq,ci)):
                    name=scope+":"+label
                    if not policy or not nt:
                        item["methods"][name]={"state":"insufficient_matched_q_support"}
                        continue
                    metrics,rows=r._evaluate(nt,method=method,capital=capital,risk_budget=risk_budget,
                            q=policy,context_scope=scope,dates=dates[1])
                    item["methods"][name]=metrics
                    journal.extend({**row,"method":name} for row in rows)
    return results,journal
