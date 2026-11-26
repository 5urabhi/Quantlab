"""Research on the frozen prospective constituent ledger; never places orders.

The first 60 completed *recorded* sessions are locked by the existing
protocol, not replaced by better-covered days. This is an assessment of
a previously recorded feature ledger, not an externally preregistered
live model or a substitute for historical OHLC acquisition.
"""
from collections import Counter
from contextlib import closing
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import csv
import json
import math
import os
import re
import uuid

import numpy as np

from . import constituent_prospective as p, shared_market_data, service
from . import advanced_options as ao, replay_storage

VERSION="constituent_alpha_v1"
HORIZONS=(5,10,30,60)
TRAIN=30
CALIBRATION=10
HOLDOUT=20
REQUIRED=TRAIN+CALIBRATION+HOLDOUT
DEADBAND_BPS=5.
COST_BPS=5.
CALL_PROB=.60
CLASSES=(-1,0,1)
INDEX_FEATURES=("index_5m_bps","index_15m_bps","index_30m_bps","index_rv_1m_bps","ema_gap_bps","rsi14","minute_of_session")
BANK_FEATURES=("weighted_return_bps","breadth_pct","weighted_dispersion_bps",
               "signed_rvol","rvol_missing","weighted_atp_deviation_bps","atp_missing",
               "weighted_displayed_imbalance","imbalance_missing")
MODELS=("index_logistic","constituent_logistic","constituent_boosting")
POLICY={"version":VERSION,"source_protocol_hash":p.PROTOCOL_HASH,"horizons":HORIZONS,
        "split_sessions":[TRAIN,CALIBRATION,HOLDOUT],"deadband_bps":DEADBAND_BPS,
        "roundtrip_index_cost_proxy_bps":COST_BPS,"call_probability":CALL_PROB,
        "index_features":INDEX_FEATURES,"bank_features":BANK_FEATURES,
        "minimum_samples":[60,20,40],"minimum_supported_sessions":[20,7,12],
        "sampling":"greedy nonoverlapping decision windows including 30s label allowance; reserve missing-label slots",
        "model_settings":"standardized L2 logistic C=1; histogram gradient boosting max_iter=100 max_leaf_nodes=7 min_samples_leaf=20 L2=1; temperature grid fixed; three quantile regressors",
        "development_walk_forward":[[20,5],[25,5]]}
POLICY_HASH=sha256(json.dumps(POLICY,sort_keys=True).encode()).hexdigest()


def _stamp(value):
    t=datetime.fromisoformat(value)
    if t.tzinfo is None:
        raise ValueError("Naive timestamp")
    return t.astimezone(timezone.utc)


def _num(value):
    if type(value) not in (float,int) or not math.isfinite(value):
        raise ValueError("Missing or invalid numeric evidence")
    return float(value)


def _hash(value):
    if not p._valid_hash(value):
        raise ValueError("Missing source digest")
    return value


def _read():
    return ao._read_database()


def _horizon(h):
    if h not in HORIZONS:
        raise ValueError("Use 5, 10, 30 or 60 minutes recorded by the existing protocol")


def _days(db,horizon,today):
    if not replay_storage.fetchone(db,"SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(p.TABLE,)):
        return []
    return [r[0] for r in replay_storage.fetchall(db,"""SELECT DISTINCT session_ist FROM banknifty_paired_signals
        WHERE protocol_hash=? AND horizon_minutes=? AND session_ist<? ORDER BY session_ist LIMIT ?""",
        (p.PROTOCOL_HASH,horizon,today,REQUIRED))]


def readiness(horizon=30,*,now=None):
    _horizon(horizon)
    now=now or p._now()
    today=p._session(now).date().isoformat()
    days=[]
    if shared_market_data.database_path().is_file():
        with closing(_read()) as db:
            days=_days(db,horizon,today)
    return {"version":VERSION,"policy_sha256":POLICY_HASH,"source_protocol_sha256":p.PROTOCOL_HASH,
            "horizon_minutes":horizon,"supported_horizons":list(HORIZONS),
            "required_sessions":REQUIRED,"recorded_sessions":len(days),"training_dates":days[:TRAIN],
            "calibration_dates":days[TRAIN:TRAIN+CALIBRATION],"holdout_dates":days[TRAIN+CALIBRATION:],
            "state":"ready_for_evidence_audit" if len(days)==REQUIRED else "awaiting_recorded_sessions",
            "prospective_enabled":p.enabled(),"constituent_capture_enabled":p.bank.enabled(),
            "note":"Counts are completed recorded sessions, not proof of usable data. The first 60 are retained even if coverage is poor. The existing ledger has 5/10/30/60 minute labels, not 15 minutes. No fabricated historical weights or signals."}


def _reference(row,e):
    cutoff,decided,target=(_stamp(row[k]) for k in ("cutoff_utc","decided_utc","target_utc"))
    if not 0<=(decided-cutoff).total_seconds()<=5 or target!=decided+timedelta(minutes=row["horizon_minutes"]):
        raise ValueError("Decision clock mismatch")
    if p._session(cutoff).date().isoformat()!=row["session_ist"]:
        raise ValueError("Session mismatch")
    ref=e["reference"]
    price=_num(row["reference_price"])
    received,event=_stamp(ref["received_utc"]),_stamp(ref["exchange_utc"])
    if price<=0 or price!=_num(ref["price"]) or _hash(ref["sha256"])!=_hash(row["reference_sha256"]):
        raise ValueError("Reference price mismatch")
    if not cutoff-timedelta(seconds=15)<=event<=cutoff or not cutoff-timedelta(seconds=15)<=received<=cutoff or not -2<=(received-event).total_seconds()<=15:
        raise ValueError("Reference unavailable at cutoff")
    return cutoff,decided,target,price


def _bank_features(e,cutoff):
    members=e["expected_members"]
    rows=e["constituent_receipts"]
    if not p._valid_hash(e.get("membership_sha256")):
        raise ValueError("Missing dated membership")
    if not p._valid_hash(e.get("weights_sha256")) or not e.get("weights_recorded_utc"):
        raise ValueError("Missing dated weights")
    membership=_hash(e["membership_sha256"])
    _hash(e["weights_sha256"])
    if _stamp(e["weights_recorded_utc"])>cutoff or not 1<=members<=50 or e["members"]!=members or len(rows)!=members:
        raise ValueError("Incomplete dated constituent evidence")
    if abs(_num(e["observed_weight_pct"])-100)>.10001:
        raise ValueError("Incomplete weighted coverage")
    items=[]; symbols=set()
    for r in rows:
        symbol=r["symbol"]
        if symbol in symbols:
            raise ValueError("Duplicate constituent")
        symbols.add(symbol)
        w=_num(r["weight_pct"])
        if not 0<w<=100:
            raise ValueError("Invalid weight")
        c,a=r["current"],r["anchor"]
        if c["identity"]!=a["identity"]:
            raise ValueError("Identity mismatch")
        for quote,limit in ((c,cutoff),(a,cutoff-timedelta(minutes=5))):
            _hash(quote["packet_sha256"])
            if quote["membership_sha256"]!=membership:
                raise ValueError("Membership receipt mismatch")
            receipt,trade=_stamp(quote["received_utc"]),_stamp(quote["exchange_trade_utc"])
            if not limit-timedelta(seconds=30)<=receipt<=limit or not limit-timedelta(seconds=30)<=trade<=limit:
                raise ValueError("Quote unavailable at cutoff")
        cp,ap=_num(c["price"]),_num(a["price"])
        if min(cp,ap)<=0:
            raise ValueError("Nonpositive constituent price")
        ret=10000*(cp/ap-1)
        rvol=r.get("relative_volume")
        rv=(math.copysign(min(float(rvol),3),ret) if ret else 0.) if type(rvol) in (int,float) and math.isfinite(rvol) and rvol>=0 and r.get("baseline_sessions",0)>=5 else None
        atp=c.get("atp")
        atp_dev=10000*(cp/atp-1) if type(atp) in (int,float) and math.isfinite(atp) and atp>0 else None
        buy,sell=c.get("buy_quantity"),c.get("sell_quantity")
        imb=(buy-sell)/(buy+sell) if all(type(x) in (int,float) and math.isfinite(x) and x>=0 for x in (buy,sell)) and buy+sell>0 else None
        items.append((w,ret,rv,atp_dev,imb))
    total=sum(x[0] for x in items)
    if abs(total-100)>.10001:
        raise ValueError("Weight sum mismatch")
    avg=sum(w*r for w,r,*_ in items)/total
    breadth=sum(w*(1 if r>0 else -1 if r<0 else 0) for w,r,*_ in items)
    dispersion=math.sqrt(sum(w*(r-avg)**2 for w,r,*_ in items)/total)
    def optional(index):
        covered=sum(x[0] for x in items if x[index] is not None)
        if covered<.8*total:
            # Numeric placeholder is paired with an explicit missingness
            # flag, not an imputed market move or zero-filled constituent.
            return 0.,1.
        return sum(x[0]*x[index] for x in items if x[index] is not None)/covered,0.
    return [avg,breadth,dispersion,*optional(2),*optional(3),*optional(4)]


def _label(row,price,target):
    try:
        observed=_num(row["observed_price"])
        exchange,receipt=_stamp(row["observed_exchange_utc"]),_stamp(row["observed_received_utc"])
        _hash(row["observed_sha256"])
        if observed<=0 or not target<=exchange<=target+timedelta(seconds=30) or not target<=receipt<=target+timedelta(seconds=30) or not -2<=(receipt-exchange).total_seconds()<=15:
            return None
        outcome="UP" if observed>price else "DOWN" if observed<price else "FLAT"
        if row["outcome"]!=outcome:
            return None
        return 10000*(observed/price-1)
    except (KeyError,TypeError,ValueError,OverflowError):
        return None


def sample_day(rows):
    """One horizon, one session, chronological frozen observations.

    Features never inspect the target/outcome. Reserve a nonoverlapping
    window on feature eligibility *before* attempting to score its label.
    """
    refs={}
    samples=[]
    counts=Counter()
    next_eligible=None
    for row in rows:
        counts["ledger_rows"]+=1
        try:
            e=json.loads(row["evidence_json"])
            cutoff,decided,target,price=_reference(row,e)
            slot=_stamp(row["slot_utc"])
            if slot!=cutoff.replace(second=0,microsecond=0):
                raise ValueError("Slot mismatch")
            refs[slot]=price
        except (ValueError,TypeError,KeyError,OverflowError):
            counts["invalid_reference"]+=1
            continue
        try:
            past=[refs[slot-timedelta(minutes=m)] for m in (5,15,30)]
            one_minute=[]
            for m in range(30):
                a,b=slot-timedelta(minutes=m+1),slot-timedelta(minutes=m)
                if a in refs and b in refs:
                    one_minute.append(10000*(refs[b]/refs[a]-1))
            if len(one_minute)<20:
                raise ValueError("Insufficient one-minute returns")
            ema=e["ema"]
            if ema["quote_mode"]!="RECENT_LOCAL_CANDLE_NOT_VERIFIED_LIVE" or ema["contiguous_session_bars"]<30:
                raise ValueError("Missing completed EMA")
            if not 60<=(cutoff-_stamp(ema["last_observed_utc"])).total_seconds()<=90:
                raise ValueError("Stale EMA")
            fast,slow,rsi=(_num(ema[k]) for k in ("ema9","ema21","rsi14"))
            if slow<=0 or not 0<=rsi<=100:
                raise ValueError("Invalid EMA/RSI")
            r5,r15,r30=(10000*(price/x-1) for x in past)
            rv=float(np.std(one_minute,ddof=1))
            local=p._session(cutoff)
            index=[r5,r15,r30,rv,10000*(fast/slow-1),rsi,float(local.hour*60+local.minute-555)]
        except (ValueError,TypeError,KeyError,OverflowError):
            counts["missing_index_features"]+=1
            continue
        try:
            bank=_bank_features(e,cutoff)
            if row["pressure"] not in ("UP","DOWN","ABSTAIN"):
                raise ValueError("Unavailable weighted rule evidence")
            if not all(math.isfinite(v) for v in index+bank):
                raise ValueError("Nonfinite feature")
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            counts["missing_constituent_features"]+=1
            reason=str(exc)
            key={"Missing dated membership":"bank_missing_membership",
                 "Missing dated weights":"bank_missing_weights",
                 "Incomplete dated constituent evidence":"bank_incomplete_dated_evidence",
                 "Incomplete weighted coverage":"bank_incomplete_weight_coverage",
                 "Quote unavailable at cutoff":"bank_stale_or_future_quote",
                 "Unavailable weighted rule evidence":"bank_unavailable_weighted_rule"}.get(reason,"bank_other_invalid_evidence")
            counts[key]+=1
            continue
        counts["matched_features"]+=1
        if next_eligible is not None and decided<=next_eligible:
            counts["overlap_skipped"]+=1
            continue
        next_eligible=target+timedelta(seconds=30)
        counts["reserved_nonoverlap"]+=1
        label=_label(row,price,target)
        if label is None:
            counts["missing_label"]+=1
            continue
        counts["scored"]+=1
        scale=max(1.,rv*math.sqrt(30))
        regime="trend_up" if r30>=scale else "trend_down" if r30<=-scale else "compression" if rv<=3. else "range"
        samples.append({"session":row["session_ist"],"decision_utc":row["decided_utc"],"cutoff_utc":row["cutoff_utc"],"target_utc":row["target_utc"],
            "reference_price":price,"return_bps":label,"class":1 if label>DEADBAND_BPS else -1 if label<-DEADBAND_BPS else 0,
            "index":index,"full":index+bank,"regime":regime,
            "ema_rsi":row["ema_rsi"],"pressure":row["pressure"],"volume_pressure":row["volume_pressure"]})
    return samples,dict(counts)


def _rows(db,day,horizon):
    # The existing primary protocol has at most 375 minute slots per session.
    # Cap reads, refuse a corrupt/duplicated ledger rather than truncating.
    db.row_factory=None
    start=day+"T03:45:00"
    stop=day+"T10:01:00"
    columns=("slot_utc","session_ist","cutoff_utc","decided_utc","target_utc","horizon_minutes",
             "reference_price","reference_sha256","pressure","volume_pressure","ema_rsi","evidence_json",
             "outcome","observed_price","observed_exchange_utc","observed_received_utc","observed_sha256")
    data=replay_storage.fetchall(db,"SELECT "+",".join(columns)+""" FROM banknifty_paired_signals
        WHERE protocol_hash=? AND horizon_minutes=? AND slot_utc>=? AND slot_utc<? AND session_ist=?
        ORDER BY slot_utc LIMIT 401""",(p.PROTOCOL_HASH,horizon,start,stop,day))
    if len(data)>400:
        raise ValueError("Recorded session exceeds bounded minute ledger")
    return [dict(zip(columns,row)) for row in data]


def _root():
    path=service.DATA/"research_workspace"/"constituent_alpha"
    path.mkdir(parents=True,exist_ok=True)
    return path


def result_path(run_id,*,audit=False):
    if not re.fullmatch(r"[a-f0-9]{32}",run_id):
        raise ValueError("Invalid alpha result identifier")
    path=_root()/("run-"+run_id+("-audit" if audit else "")+".csv")
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError("Alpha result unavailable")
    return path


def support(samples):
    classes=Counter(x["class"] for x in samples)
    return {"samples":len(samples),"sessions":len({x["session"] for x in samples}),
            "classes":{str(c):classes[c] for c in CLASSES}}


def _supported(samples,n,days,*,train=False):
    s=support(samples)
    return s["samples"]>=n and s["sessions"]>=days and (not train or min(s["classes"].values())>=10)


def _fit(model, rows):
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from threadpoolctl import threadpool_limits
    key="index" if model=="index_logistic" else "full"
    estimator=(HistGradientBoostingClassifier(max_iter=100,max_leaf_nodes=7,
        min_samples_leaf=20,l2_regularization=1.,random_state=419,early_stopping=False)
        if model=="constituent_boosting" else
        make_pipeline(StandardScaler(),LogisticRegression(C=1.,max_iter=1000,random_state=419)))
    with threadpool_limits(limits=1):
        estimator.fit(np.asarray([r[key] for r in rows]),np.asarray([r["class"] for r in rows]))
    if tuple(estimator.classes_)!=CLASSES:
        raise ValueError("Model requires all three direction classes")
    return key,estimator


def _predict(fitted, rows):
    from threadpoolctl import threadpool_limits
    key,estimator=fitted
    with threadpool_limits(limits=1):
        return estimator.predict_proba(np.asarray([r[key] for r in rows]))


def _temperature(probs,t):
    log=np.log(np.clip(probs,1e-12,1.))/t
    exp=np.exp(log-np.max(log,axis=1,keepdims=True))
    return exp/exp.sum(axis=1,keepdims=True)


def _targets(rows):
    return np.asarray([r["class"]+1 for r in rows],dtype=int)


def _calibrate(probs,rows):
    labels=_targets(rows)
    one=np.eye(3)[labels]
    grid=(.5,.75,1.,1.25,1.5,2.,3.)
    return min(grid,key=lambda t:(float(np.mean(np.sum((_temperature(probs,t)-one)**2,axis=1))),abs(t-1)))


def _call(probs):
    # A flat class or a tie is abstention. Predeclared threshold never tuned
    # on the holdout or adjusted until a favorable result is obtained.
    top=int(np.argmax(probs))
    if top==1 or probs[top]<CALL_PROB or sum(v==probs[top] for v in probs)>1:
        return 0
    return CLASSES[top]


def _rule(value):
    return 1 if value=="UP" else -1 if value=="DOWN" else None if value=="UNAVAILABLE" else 0


def _directional_stats(rows,calls,probs=None):
    target=_targets(rows)
    verified=[(r,c) for r,c in zip(rows,calls) if c is not None]
    traded=[(r,c) for r,c in verified if c!=0]
    pnl=[c*r["return_bps"]-COST_BPS for r,c in traded]
    day_pnl={}
    for r,c in traded:
        day_pnl[r["session"]]=day_pnl.get(r["session"],0.)+c*r["return_bps"]-COST_BPS
    n=len(rows)
    result={"eligible_samples":n,"available_calls":len(verified),"unavailable":n-len(verified),
        "directional_calls":len(traded),"abstentions":len(verified)-len(traded),
        "call_rate_pct":100*len(traded)/n if n else None,
        "directional_hit_pct":100*sum(c==r["class"] for r,c in traded)/len(traded) if traded else None,
        "mean_signed_index_return_bps":float(np.mean([c*r["return_bps"] for r,c in traded])) if traded else None,
        "mean_net_index_proxy_bps":float(np.mean(pnl)) if pnl else None,
        "sum_net_index_proxy_bps":float(sum(pnl)),
        "worst_net_index_proxy_bps":float(min(pnl)) if pnl else None,
        "positive_proxy_calls":sum(v>0 for v in pnl),"call_sessions":len(day_pnl),
        "positive_proxy_sessions":sum(v>0 for v in day_pnl.values()),
        "accuracy_pct":None,"brier":None,"log_loss":None,"reliability":[]}
    if probs is not None:
        one=np.eye(3)[target]
        result["accuracy_pct"]=100*float(np.mean(np.argmax(probs,axis=1)==target))
        result["brier"]=float(np.mean(np.sum((probs-one)**2,axis=1)))
        result["log_loss"]=-float(np.mean(np.log(np.clip(probs[np.arange(n),target],1e-12,1.))))
        # Top-label reliability is descriptive; not a calibrated guarantee.
        conf=np.max(probs,axis=1)
        correct=np.argmax(probs,axis=1)==target
        for low,high in ((0.,.4),(.4,.6),(.6,.8),(.8,1.000001)):
            mask=(conf>=low)&(conf<high)
            if np.any(mask):
                result["reliability"].append({"low":low,"high":min(high,1.),"count":int(mask.sum()),
                    "mean_confidence":float(conf[mask].mean()),"observed_accuracy":float(correct[mask].mean())})
    return result


def _quantiles(train,test):
    from sklearn.ensemble import GradientBoostingRegressor
    from threadpoolctl import threadpool_limits
    x=np.asarray([r["full"] for r in train]);y=np.asarray([r["return_bps"] for r in train])
    xt=np.asarray([r["full"] for r in test]);yt=np.asarray([r["return_bps"] for r in test])
    q=(.1,.5,.9)
    preds=[]
    with threadpool_limits(limits=1):
        for level in q:
            model=GradientBoostingRegressor(loss="quantile",alpha=level,n_estimators=100,
                max_depth=2,min_samples_leaf=20,random_state=419)
            model.fit(x,y);preds.append(model.predict(xt))
    values=np.column_stack(preds)
    empirical=np.tile(np.quantile(y,q),(len(test),1))
    def pinball(v):
        err=yt[:,None]-v
        return [float(x) for x in np.mean(np.maximum(np.asarray(q)*err,(np.asarray(q)-1)*err),axis=0)]
    crossed=(values[:,0]>values[:,1])|(values[:,1]>values[:,2])
    valid=~crossed
    coverage=float(np.mean((yt[valid]>=values[valid,0])&(yt[valid]<=values[valid,2]))) if np.any(valid) else None
    return values,{"quantiles":list(q),"pinball_loss_bps":pinball(values),
        "historical_unconditional_pinball_loss_bps":pinball(empirical),
        "crossed_rows":int(crossed.sum()),"valid_interval_rows":int(valid.sum()),
        "observed_interval_coverage":coverage,"nominal_interval_coverage":.8,
        "note":"Quantile forecasts are scored as fitted; crossed intervals are flagged, not silently repaired."}


def _compare(train,cal,test,progress=None):
    records=[];methods={}
    # Empirical class frequency is frozen from development training only.
    base=np.asarray([(1+sum(r["class"]==c for r in train))/(len(train)+3) for c in CLASSES])
    probabilities={"training_class_prior":np.tile(base,(len(test),1))}
    calls={"no_trade":[0]*len(test),
           "index_momentum":[1 if r["index"][2]>DEADBAND_BPS else -1 if r["index"][2]<-DEADBAND_BPS else 0 for r in test],
           "regime_momentum":[1 if r["regime"]=="trend_up" else -1 if r["regime"]=="trend_down" else 0 for r in test]}
    for rule in ("ema_rsi","pressure","volume_pressure"):
        calls[rule]=[_rule(r[rule]) for r in test]
    for rule in ("opening_breakout","trend_pullback","range_reversion"):
        if all(rule in r for r in test):
            calls[rule]=[_rule(r[rule]) for r in test]
    for i,model in enumerate(MODELS):
        if progress:
            progress(65+5*i,"Training frozen "+model)
        fitted=_fit(model,train)
        temp=_calibrate(_predict(fitted,cal),cal)
        probabilities[model]=_temperature(_predict(fitted,test),temp)
        methods[model]={"temperature":temp}
    for model,probs in probabilities.items():
        calls[model]=[_call(v) for v in probs]
    for model,pred in calls.items():
        probs=probabilities.get(model)
        result=_directional_stats(test,pred,probs)
        methods.setdefault(model,{}).update(result)
        for i,(r,call) in enumerate(zip(test,pred)):
            v=probs[i] if probs is not None else (None,None,None)
            records.append({"method":model,"session":r["session"],"decision_utc":r["decision_utc"],
                "target_utc":r["target_utc"],"regime":r["regime"],"reference_price":r["reference_price"],
                "actual_return_bps":r["return_bps"],"actual_class":r["class"],
                "call":call,"p_down":v[0],"p_flat":v[1],"p_up":v[2],
                "net_index_proxy_bps":call*r["return_bps"]-COST_BPS if call else 0. if call==0 else None,
                "q10_bps":None,"q50_bps":None,"q90_bps":None})
    prior=methods["training_class_prior"]["brier"]
    index=methods["index_logistic"]["brier"]
    for model in MODELS:
        item=methods[model]
        item["brier_skill_vs_prior"]=1-item["brier"]/prior if prior>0 else None
        item["brier_skill_vs_index_logistic"]=1-item["brier"]/index if index>0 else None
        item["descriptive_gate_passed"]=bool(item["brier"]<prior and
            (model=="index_logistic" or item["brier"]<index) and item["directional_calls"]>=20
            and item["call_sessions"]>=10 and item["mean_net_index_proxy_bps"] is not None
            and item["mean_net_index_proxy_bps"]>0)
    regimes={}
    for regime in ("trend_up","trend_down","compression","range"):
        idx=[i for i,r in enumerate(test) if r["regime"]==regime]
        regimes[regime]={"samples":len(idx),"methods":{}}
        if idx:
            for model in MODELS:
                regimes[regime]["methods"][model]=_directional_stats(
                    [test[i] for i in idx],[calls[model][i] for i in idx],probabilities[model][idx])
    if progress:
        progress(82,"Estimating conditional return quantiles")
    quantile_values,quantile_report=_quantiles(train,test)
    for r,v in zip(test,quantile_values):
        records.append({"method":"constituent_quantile","session":r["session"],"decision_utc":r["decision_utc"],
            "target_utc":r["target_utc"],"regime":r["regime"],"reference_price":r["reference_price"],
            "actual_return_bps":r["return_bps"],"actual_class":r["class"],
            "call":None,"p_down":None,"p_flat":None,"p_up":None,"net_index_proxy_bps":None,
            "q10_bps":v[0],"q50_bps":v[1],"q90_bps":v[2]})
    return methods,regimes,quantile_report,records


def _walk_forward(train,dates,progress=None):
    output=[]
    for size,width in POLICY["development_walk_forward"]:
        a=[r for r in train if r["session"] in set(dates[:size])]
        b=[r for r in train if r["session"] in set(dates[size:size+width])]
        item={"train_dates":dates[:size],"test_dates":dates[size:size+width],
              "train_support":support(a),"test_support":support(b),"methods":{},"state":"insufficient_support"}
        if _supported(a,40,12,train=True) and _supported(b,10,3):
            item["state"]="available"
            for model in MODELS:
                if progress:
                    progress(61,"Development walk-forward: "+model)
                probs=_predict(_fit(model,a),b)
                item["methods"][model]=_directional_stats(b,[_call(v) for v in probs],probs)
        output.append(item)
    return output


def _save(records,*,audit=False):
    run_id=uuid.uuid4().hex
    path=_root()/("run-"+run_id+("-audit" if audit else "")+".csv")
    tmp=path.with_suffix(".tmp")
    try:
        with tmp.open("x",newline="",encoding="utf-8") as f:
            writer=csv.DictWriter(f,fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(records)
        os.replace(tmp,path)
    finally:
        tmp.unlink(missing_ok=True)
    return run_id


def run(*,horizon=30,progress=None,now=None):
    now=now or p._now()
    status=readiness(horizon,now=now)
    dates=status["training_dates"]+status["calibration_dates"]+status["holdout_dates"]
    samples=[];audit=[];counts=Counter()
    if progress:
        progress(1,"Auditing the existing constituent observation ledger")
    if dates:
        with closing(_read()) as db:
            for i,day in enumerate(dates):
                if progress:
                    progress(2+55*i/len(dates),"Auditing recorded session "+day)
                day_samples,day_counts=sample_day(_rows(db,day,horizon))
                samples.extend(day_samples)
                counts.update(day_counts)
                audit.append({"day":day,**day_counts})
    split=[status[k] for k in ("training_dates","calibration_dates","holdout_dates")]
    train,cal,test=([r for r in samples if r["session"] in set(part)] for part in split)
    status.update(evidence_counts=dict(counts),session_audit=audit,
        support={"training":support(train),"calibration":support(cal),"holdout":support(test)},
        methods={},regimes={},quantiles=None,walk_forward=[],run_id=None,
        broker_orders_enabled=False,live_model_promoted=False,
        warning="Frozen chronological research on the first 60 recorded sessions, not external preregistration. "
        "The 5 bps round-trip underlying index cost is a fixed hypothetical proxy, not option P&L, broker charges, or a tradable BANKNIFTY spot fill. "
        "All methods share matched constituent and index evidence; missing observations remain excluded and counted. "
        "No overlapping selected forecast windows; within-day returns may still be dependent. "
        "A descriptive gate is not a significance test, proof of alpha, or permission to trade. "
        "No model is connected to the paper order selector.")
    if len(dates)<REQUIRED:
        status["state"]="awaiting_recorded_sessions"
    elif not (_supported(train,60,20,train=True) and _supported(cal,20,7) and _supported(test,40,12)):
        status["state"]="insufficient_matched_evidence"
    else:
        status["walk_forward"]=_walk_forward(train,split[0],progress)
        methods,regimes,quantiles,records=_compare(train,cal,test,progress)
        status.update(state="holdout_assessment_available",methods=methods,regimes=regimes,quantiles=quantiles,
                      run_id=_save(records),prediction_rows=len(records))
    # The coverage artifact is useful even when model fitting is blocked.
    audit_records=[{"day":"RUN_SUMMARY","state":status["state"],"counts_json":json.dumps(dict(counts),sort_keys=True),
                    "support_json":json.dumps(status["support"],sort_keys=True),
                    "policy_sha256":POLICY_HASH}]
    for item in audit:
        audit_records.append({"day":item["day"],"state":"recorded_session",
            "counts_json":json.dumps({k:v for k,v in item.items() if k!="day"},sort_keys=True),
            "support_json":"","policy_sha256":POLICY_HASH})
    status["audit_id"]=_save(audit_records,audit=True)
    if progress:
        progress(100,"Constituent alpha research report saved")
    return status
