"""Regime-conditioned volatility and normalized first-passage research.

Fixed rule definitions, training-only probability tables, later validation
selection and day-clustered assessment. No live trading or causal claims.
"""
from collections import Counter, defaultdict
from math import isfinite,sqrt
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import Ridge

from . import candle_barrier_research as b, candle_pattern_research as p
from . import cpr_context_features as cx
from .stable_scaler import StableWeightedScaler

VERSION="regime_volatility_v1"
HORIZONS=(5,15,30)
MULTIPLIERS=(.75,1.5,3.)
VOL_CLASSES=("contraction","stable","expansion")
REGIMES=("trend_up","trend_down","reversal_up","reversal_down","range")
TASKS=(("future_volatility",VOL_CLASSES),)+tuple((f"first_touch_{x:g}sigma",b.TOUCH_CLASSES) for x in MULTIPLIERS)
NAMES=("rms_5m_bps","rms_30m_bps","rms_ratio_5m_30m","rms_vs_prior_same_clock",
       "seasonality_missing","move_5m_bps","move_30m_bps","path_efficiency",
       "last_5m_range_to_30m_rms","session_fraction")+tuple("is_"+r for r in REGIMES)
MIN_GROUP_DAYS=5
SHRINK=30.


def _returns(bars,minute,width):
    if minute<width or any(k not in bars for k in range(minute-width,minute+1)):
        return None
    closes=np.asarray([bars[k][3] for k in range(minute-width,minute+1)],dtype=float)
    if not np.isfinite(closes).all() or np.min(closes)<=0:
        return None
    return 10000*(closes[1:]/closes[:-1]-1.)


def _rms(values):
    return float(np.sqrt(np.mean(np.square(values))))


def describe(index,day,minute,prior_dates):
    bars=index[day]
    r=_returns(bars,minute,30)
    pattern=p.describe(bars,minute,5)
    if r is None or pattern is None:
        return None
    short=r[-5:]
    vol30=_rms(r);vol5=_rms(short)
    prior=[]
    for old in prior_dates[-20:]:
        if old>=day:
            raise ValueError("Regime baseline must use prior sessions")
        returns=_returns(index[old],minute,30)
        if returns is not None:
            prior.append(_rms(returns))
    seasonal=float(np.median(prior)) if len(prior)>=5 else 0.
    spot=bars[minute][3]
    move30=10000*(spot/bars[minute-30][3]-1.)
    move5=10000*(spot/bars[minute-5][3]-1.)
    older=10000*(bars[minute-5][3]/bars[minute-30][3]-1.)
    efficiency=abs(float(np.sum(r)))/max(1e-9,float(np.sum(np.abs(r))))
    # A reversal here is an observed opposing short move, not a claim
    # that a future reversal will occur.
    if older>max(1.,vol30*sqrt(25)) and move5<-max(1.,vol30*sqrt(5)*.5):
        regime="reversal_down"
    elif older<-max(1.,vol30*sqrt(25)) and move5>max(1.,vol30*sqrt(5)*.5):
        regime="reversal_up"
    elif efficiency>=.55 and abs(move30)>=max(1.,vol30*sqrt(30)):
        regime="trend_up" if move30>0 else "trend_down"
    else:
        regime="range"
    seasonal_ratio=min(20.,vol30/max(seasonal,.05)) if seasonal>0 else 0.
    vol_state="expanded" if vol5>1.25*max(vol30,.05) else "compressed" if vol5<.8*max(vol30,.05) else "normal"
    last=p._aggregate(bars,minute,5)
    if last is None:
        return None
    vector=[vol5,vol30,min(20.,vol5/max(vol30,.05)),seasonal_ratio,float(seasonal<=0),
            move5,move30,efficiency,min(30.,10000*(last[1]-last[2])/spot/max(vol30,.05)),minute/375.]
    vector.extend(float(regime==r) for r in REGIMES)
    if not all(isfinite(x) for x in vector):
        return None
    return {"regime":regime,"vol_state":vol_state,"pattern":pattern["pattern"],
            "rms_bps":vol30,"spot":spot,"regime_features":vector,"short":pattern["features"],
            "index_return_5m_bps":move5}


def outcome(bars,minute,horizon,desc):
    returns=_returns(bars,minute+horizon,horizon)
    if returns is None or minute+horizon>=375:
        return None
    future=[]
    for k in range(minute+1,minute+horizon+1):
        o,h,l,c=map(float,bars[k][:4])
        if not all(isfinite(x) and x>0 for x in (o,h,l,c)) or not l<=min(o,c)<=max(o,c)<=h:
            return None
        future.append((o,h,l,c))
    baseline=max(.05,desc["rms_bps"])
    future_rms=_rms(returns)
    ratio=future_rms/baseline
    labels=[VOL_CLASSES.index("expansion" if ratio>1.25 else "contraction" if ratio<.8 else "stable")]
    price=desc["spot"]
    scale=max(1.,price*baseline/10000*sqrt(horizon))
    for multiple in MULTIPLIERS:
        d=scale*multiple
        label="neither"
        for o,h,l,c in future:
            if o>=price+d:
                label="upper_first";break
            if o<=price-d:
                label="lower_first";break
            up=h>=price+d;down=l<=price-d
            if up and down:
                label="ambiguous";break
            if up or down:
                label="upper_first" if up else "lower_first";break
        labels.append(b.TOUCH_CLASSES.index(label))
    return {"labels":labels,"scale_points":scale,"future_rms_bps":future_rms,
            "volatility_ratio":ratio,"future_return_bps":float(10000*(future[-1][3]/price-1.))}


def _key(row,with_pattern):
    k=(row["regime"],row["vol_state"])
    return k+(row["pattern"],) if with_pattern else k


def _lookup(train,task,classes,weights,prior,with_pattern):
    groups=defaultdict(list)
    for row,w in zip(train,weights):
        groups[_key(row,with_pattern)].append((row,w))
    out={}
    for key,rows in groups.items():
        if len(rows)<30 or len({r["session"] for r,_ in rows})<MIN_GROUP_DAYS:
            continue
        counts=SHRINK*prior.copy()
        for r,w in rows:
            counts[r["labels"][task]]+=w
        out[key]=counts/counts.sum()
    return out


def _fit(parts,*,panel=False):
    tr,va,te=parts
    counts=[len({r["session"] for r in x}) for x in parts]
    result={"state":"insufficient_support","coverage":[len(x) for x in parts],"sessions":counts,"tasks":{}}
    if counts[0]<20 or counts[1]<5 or not te:
        return result
    w=b._weights(tr)*len(tr)/counts[0]
    def x(row):
        return row["regime_features"]+row["short"]+(row["context_vectors"]["panel_detail"] if panel else [])
    y=np.asarray([r["labels"] for r in tr],dtype=int)
    forest=RandomForestClassifier(n_estimators=100,max_depth=4,min_samples_leaf=20,random_state=91,n_jobs=1)
    forest.fit([x(r) for r in tr],y,sample_weight=w)
    vf=forest.predict_proba([x(r) for r in va]);tf=forest.predict_proba([x(r) for r in te])
    for i,(task,classes) in enumerate(TASKS):
        prior=np.ones(len(classes))
        for row,weight in zip(tr,w):
            prior[row["labels"][i]]+=weight
        prior/=prior.sum()
        lookup={name:_lookup(tr,i,classes,w,prior,pattern) for name,pattern in (("regime_lookup",False),("pattern_lookup",True))}
        def predicts(rows,raw):
            rf=np.zeros((len(rows),len(classes)))
            rf[:,np.asarray(forest.classes_[i],dtype=int)]=raw
            return {"prior":np.tile(prior,(len(rows),1)),
                    "regime_lookup":np.asarray([lookup["regime_lookup"].get(_key(row,False),prior) for row in rows]),
                    "pattern_lookup":np.asarray([lookup["pattern_lookup"].get(_key(row,True),lookup["regime_lookup"].get(_key(row,False),prior)) for row in rows]),
                    "random_forest":rf}
        val={name:b._score(va,prob,np.asarray([r["labels"][i] for r in va]),classes) for name,prob in predicts(va,vf[i]).items()}
        test={name:b._score(te,prob,np.asarray([r["labels"][i] for r in te]),classes) for name,prob in predicts(te,tf[i]).items()}
        chosen=min(val,key=lambda name:(val[name]["brier"],name!="prior",name))
        result["tasks"][task]={"selected_on_validation":chosen,"validation":val,"holdout":test,
                               "selected_minus_prior":b._paired(test[chosen],test["prior"])}
    result["state"]="exploratory_assessment"
    return result


def _lead_lag(parts):
    """Lagged bank returns vs future index return; matched index-only Ridge.
    No causal attribution or contemporaneous/future stock return inputs.
    """
    tr,va,te=parts
    if len({r["session"] for r in tr})<20 or len({r["session"] for r in va})<5 or not te:
        return {"state":"insufficient_support"}
    def design(row,bank):
        x=row["regime_features"]
        if bank:
            vector=row["context_vectors"]["panel_detail"]
            for symbol in ("HDFCBANK","ICICIBANK"):
                i=cx.PANEL_DETAIL_NAMES.index(symbol+"_return_5m_bps")
                x=x+vector[i:i+3]
        return x
    def metrics(rows,pred):
        actual=np.asarray([r["future_return_bps"] for r in rows])
        sq=(actual-pred)**2
        daily=defaultdict(list)
        for row,e in zip(rows,sq):
            daily[row["session"]].append(float(e))
        return {"rmse_bps":float(np.sqrt(np.average(sq,weights=b._weights(rows)))),
                "mean_error_bps":float(np.average(pred-actual,weights=b._weights(rows))),
                "daily_mse":{day:float(np.mean(v)) for day,v in daily.items()}}
    out={"state":"exploratory_assessment","coverage":[len(x) for x in parts],"models":{}}
    w=b._weights(tr)*len(tr)/len({r["session"] for r in tr})
    y=np.asarray([r["future_return_bps"] for r in tr])
    for name,bank in (("index_only",False),("index_hdfc_icici",True)):
        scaler=StableWeightedScaler().fit([design(r,bank) for r in tr],sample_weight=w)
        X=scaler.transform([design(r,bank) for r in tr])
        V=scaler.transform([design(r,bank) for r in va]);T=scaler.transform([design(r,bank) for r in te])
        options=[]
        for alpha in (1.,10.,100.):
            model=Ridge(alpha=alpha).fit(X,y,sample_weight=w)
            mv=metrics(va,model.predict(V))
            options.append((mv["rmse_bps"],alpha,model,mv))
        _,alpha,model,mv=min(options,key=lambda a:(a[0],a[1]))
        out["models"][name]={"alpha":alpha,"validation":mv,"holdout":metrics(te,model.predict(T))}
    a=out["models"]["index_hdfc_icici"]["holdout"]["daily_mse"]
    c=out["models"]["index_only"]["holdout"]["daily_mse"]
    diff=np.asarray([a[d]-c[d] for d in sorted(a)])
    rng=np.random.default_rng(83)
    out["bank_minus_index_mse"]={"difference":float(np.mean(diff)),
        "day_bootstrap_95pct_exploratory":list(map(float,np.quantile(np.mean(rng.choice(diff,size=(1000,len(diff)),replace=True),axis=1),[.025,.975])))}
    return out


def _regime_table(rows):
    groups=defaultdict(list)
    for r in rows:
        groups[_key(r,True)].append(r)
    out={}
    for key,g in sorted(groups.items()):
        if len(g)<30 or len({r["session"] for r in g})<5:
            continue
        w=b._weights(g)
        out["|".join(key)]={"anchors":len(g),"sessions":len({r["session"] for r in g}),
            "future_volatility":{c:float(np.average([r["labels"][0]==i for r in g],weights=w)) for i,c in enumerate(VOL_CLASSES)},
            "first_touch_1.5sigma":{c:float(np.average([r["labels"][2]==i for r in g],weights=w)) for i,c in enumerate(b.TOUCH_CLASSES)}}
    return out


def assess(index,splits,*,context_mode="off",fixed_panel=False,context_batch="auto",progress=None):
    days=[day for part in splits for day in part]
    if not days or days!=sorted(set(days)):
        raise ValueError("Unique chronological splits required")
    if fixed_panel and context_mode=="off":
        raise ValueError("Panel requires reviewed context mode")
    from .cpr_hybrid_research import _stamp
    anchors={}
    history=sorted(index)
    for day in days:
        prior=[d for d in history if d<day][-20:]
        for minute in range(34,375-min(HORIZONS),5):
            desc=describe(index,day,minute,prior)
            if desc is not None:
                anchors[(day,minute)]={"session":day,"minute":minute,"side":"CALL","decision_utc":_stamp(day,minute+1),**desc}
    if progress:progress(20,"Attaching completed bank features to regime anchors")
    audit=cx.attach(list(anchors.values()),mode=context_mode,batch_id=context_batch,fixed_panel=fixed_panel,panel_detail=fixed_panel)
    report={"version":VERSION,"horizons":{},"regime_feature_names":NAMES,
            "barrier_multipliers":MULTIPLIERS,"context":{k:v for k,v in audit.items() if k!="anchors"},
            "warning":"Exploratory historical assessment, not a live signal or verified execution. "
                      "Regime labels are observed heuristics. Volatility-normalized barriers use only the decision-time scale. "
                      "Prior session RMS seasonality uses only earlier dates; day bootstrap is not independent confirmation."}
    for h in HORIZONS:
        if progress:progress(40+HORIZONS.index(h)*20,"Assessing volatility regime and normalized "+str(h)+"-minute barriers")
        parts=[];coverage={}
        for name,ds in zip(("train","validation","holdout"),splits):
            rows=[];counts=Counter()
            for day in ds:
                for minute in range(34,375-h,h):
                    counts["reserved"]+=1
                    a=anchors.get((day,minute))
                    if a is None:
                        counts["missing_features"]+=1;continue
                    target=outcome(index[day],minute,h,a)
                    if target is None:
                        counts["missing_outcomes"]+=1;continue
                    rows.append({**a,**target});counts["scored"]+=1
            parts.append(rows);coverage[name]=dict(counts)
        item={"coverage":coverage,"index_only":_fit(parts),
              "conditional_pattern_library":{name:_regime_table(rows) for name,rows in zip(("train","validation","holdout"),parts)}}
        report["horizons"][str(h)]=item
        if parts[2]:
            item["holdout_volatility_ratio_quantiles"]={str(q):float(np.quantile([r["volatility_ratio"] for r in parts[2]],q)) for q in (.1,.5,.9)}
            item["holdout_scale_points_quantiles"]={str(q):float(np.quantile([r["scale_points"] for r in parts[2]],q)) for q in (.1,.5,.9)}
        if fixed_panel:
            matched=[[r for r in rows if "panel_detail" in r.get("context_vectors",{})] for rows in parts]
            base=_fit(matched);panel=_fit(matched,panel=True)
            comparisons={}
            for task in base["tasks"].keys()&panel["tasks"].keys():
                aa=panel["tasks"][task];bb=base["tasks"][task]
                comparisons[task]=b._paired(aa["holdout"][aa["selected_on_validation"]],bb["holdout"][bb["selected_on_validation"]])
            item["matched_panel"]={"baseline":base,"augmented":panel,"comparisons":comparisons}
            item["hdfc_icici_lead_lag"]=_lead_lag(matched)
    if progress:progress(100,"Regime research complete")
    return report
