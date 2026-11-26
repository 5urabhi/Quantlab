"""Explicit, local JSON freeze and reserved forward replay of a direct utility policy.

This is preregistered later-date historical OHLC replay, not receipt-timed
paper orders or live execution. Never deserialize executable objects.
"""
from datetime import date,datetime,timedelta,timezone
from hashlib import sha256
from pathlib import Path
import json
import numpy as np

VERSION="utility_forward_v1"
WINDOW_DAYS=45
MAX_BYTES=8*1024*1024
MAX_TREES=100
MAX_NODES=127
MODELS=("stress","failure","conditional","trigger")
CODE_FILES=("cpr_hybrid_research.py","cpr_direct_utility.py","cpr_regime_research.py",
            "candle_pattern_research.py","cpr_ranked_entries.py","predictive_option_research.py",
            "expired_options_backtest.py","liquidity_spreads.py","historical_alpha.py","cpr_forward_utility.py")


def _digest(data):
    return sha256(json.dumps(data,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()


def _code_hashes():
    root=Path(__file__).resolve().parent
    return {name:sha256((root/name).read_bytes()).hexdigest() for name in CODE_FILES}


def _tree(model):
    t=model.tree_
    values=t.value[:,0,:].astype(float)
    return {"left":t.children_left.tolist(),"right":t.children_right.tolist(),
            "feature":t.feature.tolist(),"threshold":t.threshold.tolist(),"values":values.tolist()}


def export_bundle(bundle):
    out={"regime":bool(bundle["regime"]),"forests":{}}
    for name in MODELS:
        model=bundle[name]
        out["forests"][name]={"classes":model.classes_.tolist() if hasattr(model,"classes_") else None,
            "n_features":int(model.n_features_in_),"trees":[_tree(t) for t in model.estimators_]}
    return out


def _forest_predict(forest,X,classification):
    if not isinstance(forest,dict) or type(forest.get("n_features")) is not int or forest["n_features"]!=X.shape[1]:
        raise ValueError("Frozen feature dimension mismatch")
    trees=forest["trees"]
    if not isinstance(trees,list) or not 1<=len(trees)<=MAX_TREES:
        raise ValueError("Invalid frozen forest")
    predictions=[]
    for t in trees:
        left,right,feat=(np.asarray(t[name],dtype=int) for name in ("left","right","feature"))
        threshold=np.asarray(t["threshold"],dtype=float);values=np.asarray(t["values"],dtype=float)
        n=len(left)
        expected=len(forest["classes"]) if classification else 1
        if not 1<=n<=MAX_NODES or any(v.shape!=(n,) for v in (left,right,feat,threshold)) or values.shape!=(n,expected):
            raise ValueError("Invalid frozen tree dimensions")
        if not np.isfinite(threshold).all() or not np.isfinite(values).all():
            raise ValueError("Invalid frozen tree values")
        for i,(l,rr,f) in enumerate(zip(left,right,feat)):
            if l==rr==-1:
                continue
            if not i<l<n or not i<rr<n or not 0<=f<X.shape[1]:
                raise ValueError("Invalid frozen tree topology")
        nodes=np.zeros(len(X),dtype=int)
        for _ in range(n):
            mask=left[nodes]!=-1
            if not mask.any():
                break
            active=nodes[mask]
            col=feat[active]
            nodes[mask]=np.where(X[mask,col]<=threshold[active],left[active],right[active])
        if (left[nodes]!=-1).any():
            raise ValueError("Unfinished frozen tree traversal")
        pred=values[nodes]
        if classification:
            totals=pred.sum(axis=1,keepdims=True)
            if np.any(pred<0) or np.any(totals<=0):
                raise ValueError("Invalid frozen class values")
            pred=pred/totals
        predictions.append(pred)
    return np.asarray(predictions)


def predict(bundle,rows):
    from . import cpr_direct_utility as u
    if not rows:
        return []
    # sklearn tree prediction converts inputs to float32 before threshold tests.
    X=np.asarray([u._design(ep,bundle["regime"]) for ep in rows],dtype=np.float32)
    if X.ndim!=2 or not np.isfinite(X).all():
        raise ValueError("Invalid frozen feature matrix")
    f=bundle["forests"]
    stress=_forest_predict(f["stress"],X,False)[:,:,0]
    conditional=_forest_predict(f["conditional"],X,False)[:,:,0].mean(axis=0)
    failure=_forest_predict(f["failure"],X,True).mean(axis=0)
    if any(c not in (0,1) for c in f["failure"]["classes"]):
        raise ValueError("Invalid frozen failure classes")
    bad=failure[:,f["failure"]["classes"].index(1)] if 1 in f["failure"]["classes"] else np.zeros(len(X))
    trigger=_forest_predict(f["trigger"],X,True).mean(axis=0)
    if any(c not in u.TRIGGERS for c in f["trigger"]["classes"]):
        raise ValueError("Invalid frozen trigger classes")
    aligned=np.zeros((len(X),len(u.TRIGGERS)))
    aligned[:,[u.TRIGGERS.index(c) for c in f["trigger"]["classes"]]]=trigger
    return [{"expected_stress_utility":float(ev),"tree_disagreement_p20":float(lo),
             "expected_timely_net_return":float(c),"predicted_execution_failure":float(p),
             "trigger_probabilities":dict(zip(u.TRIGGERS,map(float,t)))}
            for ev,lo,c,p,t in zip(stress.mean(axis=0),np.quantile(stress,.2,axis=0),conditional,bad,aligned)]


def freeze(report,root,*,now=None):
    from . import cpr_direct_utility as u, historical_alpha as h
    utility=report.get("utility_research",{})
    candidate=utility.get("frozen_candidate")
    gate=utility.get("models",{}).get("regime_execution",{}).get("gate",{})
    if candidate is None or gate.get("state")!="validation_selected":
        return {"state":"blocked_no_eligible_regime_utility_policy"}
    threshold=gate["selected_threshold"]
    if threshold not in u.THRESHOLDS or candidate["threshold"]!=threshold or not candidate["bundle"]["regime"]:
        raise ValueError("Frozen policy does not match preselected development gate")
    now=now or datetime.now(timezone.utc)
    last=max(date.fromisoformat(d) for d in report["training_dates"]+report["validation_dates"]+report["holdout_dates"])
    left=max(last,now.astimezone(h.IST).date())+timedelta(days=1)
    settings=report["settings"]
    policy={"version":VERSION,"frozen_utc":now.isoformat(),"start_inclusive":left.isoformat(),
            "end_exclusive":(left+timedelta(days=WINDOW_DAYS)).isoformat(),
            "prior_study_last_session":last.isoformat(),"source_sha256":report["source_sha256"],
            "code_hashes":_code_hashes(),"model":"regime_execution","threshold":threshold,
            "settings":{k:settings[k] for k in ("entry_mode","timeframe","hold_minutes","capital_inr",
                "full_premium_and_fee_budget_inr","historical_lot_size_assumed","max_lots","strike_wings",
                "primary_adverse_penalty_bps_per_side")},
            "bundle":candidate["bundle"],"validation_gate":gate,
            "warning":"Fixed future-date replay only. No certified fills, live signal or profitability approval. Local hash is not a third-party timestamp."}
    digest=_digest(policy)
    dest=Path(root)/("utility_forward_"+digest+".json")
    with dest.open("x",encoding="utf-8") as f:
        json.dump({"sha256":digest,"policy":policy},f,separators=(",",":"),allow_nan=False)
    return {"state":"frozen_for_later_replay","file":str(dest.resolve()),"sha256":digest,
            "start_inclusive":policy["start_inclusive"],"end_exclusive":policy["end_exclusive"]}


def load(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>MAX_BYTES:
        raise ValueError("Invalid frozen policy file")
    raw=json.loads(path.read_text(encoding="utf-8"))
    policy=raw["policy"]
    if raw["sha256"]!=_digest(policy) or policy.get("version")!=VERSION:
        raise ValueError("Frozen policy integrity mismatch")
    if policy["code_hashes"]!=_code_hashes():
        raise ValueError("Frozen policy code changed; use the original verified research version")
    from . import cpr_direct_utility as u
    if policy["model"]!="regime_execution" or not policy["bundle"]["regime"] or policy["threshold"] not in u.THRESHOLDS:
        raise ValueError("Unsupported frozen policy")
    left,stop=map(date.fromisoformat,(policy["start_inclusive"],policy["end_exclusive"]))
    from .historical_alpha import IST
    stamp=datetime.fromisoformat(policy["frozen_utc"])
    if stamp.tzinfo is None or left<=max(stamp.astimezone(IST).date(),date.fromisoformat(policy["prior_study_last_session"])) or (stop-left).days!=WINDOW_DAYS:
        raise ValueError("Invalid forward reservation")
    return policy,raw["sha256"]


def replay(path,*,progress=None,now=None):
    from . import cpr_hybrid_research as r, cpr_regime_research as g, cpr_direct_utility as u
    from . import cpr_ranked_entries as rank, historical_alpha as h, alpha_retraining, predictive_option_research as p
    policy,digest=load(path)
    now=now or datetime.now(timezone.utc)
    left,stop=map(date.fromisoformat,(policy["start_inclusive"],policy["end_exclusive"]))
    if now.astimezone(h.IST).date()<stop:
        raise ValueError("Reserved forward window is not finished; no early stopping or date selection")
    if not alpha_retraining.safe_window(now):
        raise ValueError("Run forward replay outside Indian market priority hours")
    if progress:progress(1,"Verifying reserved later-session index receipts")
    index,hashes,failures=h.shared_index_sources(left-timedelta(days=40),stop,[h.MAX_TOTAL])
    ordered=sorted(index)
    # Keep every weekday in the reservation visible; observed sessions
    # alone are not evidence of a complete exchange calendar.
    reserved=[(left+timedelta(days=i)).isoformat() for i in range((stop-left).days)
              if (left+timedelta(days=i)).weekday()<5]
    dates=[d for d in reserved if d in index]
    missing=[d for d in reserved if d not in index]
    settings=policy["settings"]
    hold=settings["hold_minutes"] or 0;lot=settings["historical_lot_size_assumed"];bps=settings["primary_adverse_penalty_bps_per_side"]
    capital=settings["capital_inr"];budget=settings["full_premium_and_fee_budget_inr"]
    signals=[];day_states={}
    for d in dates:
        prior=[x for x in ordered if x<d]
        if not prior:
            day_states[d]="prior_unavailable";continue
        ss,state=r._signals(d,index[d],prior[-1],index[prior[-1]],frame=settings["timeframe"],hold=hold,
                            max_signals=375 if settings["entry_mode"]!="crossover" else 3,entry_mode=settings["entry_mode"])
        day_states[d]=state
        for s in ss:
            desc=g.describe(index,d,s["minute"],prior[-20:])
            if desc is not None:
                s["context_vectors"]={"regime":desc["regime_features"]}
                s["regime"]=desc["regime"]
            s["utility_research"]=True
        signals.extend(ss)
    earliest={}
    for s in signals:
        d=s["session"];earliest[d]=min(earliest.get(d,375),max(0,s["minute"]-9))
    needed={r._stamp(d,m) for d,start in earliest.items() for m in range(start,r.LAST_SESSION_MINUTE+1)}
    table,meta=p._load_options(signals,settings["strike_wings"],progress,needed_stamps=needed)
    near=[r._episode(s,table,index[s["session"]],hold=hold,lot_size=lot,max_lots=settings["max_lots"],
                    risk_budget=budget,bps=bps) for s in signals]
    pool=rank._candidate_paths(r,signals,table,index,hold=hold,lot_size=lot,bps=bps,risk_budget=budget)
    bundle={**policy["bundle"],"frozen":True}
    selected=u._rank(bundle,pool,near,policy["threshold"])
    base,_=u._strict(r,near,reserved,capital,budget)
    candidate,journal=u._strict(r,selected,reserved,capital,budget,filtered=True)
    return {"state":"fixed_later_date_replay","policy_sha256":digest,"reserved_weekdays":reserved,
            "observed_sessions":dates,"unobserved_weekdays_unverified_holidays":missing,
            "day_states":day_states,"index_sources":hashes,"index_failures":failures,"option_sources":meta,
            "strict_fixed_stop":base,"frozen_candidate":candidate,"journal":journal,
            "refit_performed":False,"live_model_promoted":False,
            "warning":"Reserved later dates and frozen parameters; missing weekdays may be holidays or absent data. "
                      "Not prospective receipt-time trading, exact contract fills or independent P&L certification."}
