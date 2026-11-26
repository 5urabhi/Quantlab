"""Causal next-candle direction and morphology study on original index OHLC.

Forecast labels are close-to-close moves, distinct from future candle color.
Each horizon has a fixed nonoverlapping within-session grid. All selection
uses training and development dates; no option P&L is used to fit this layer.
"""
from collections import Counter, defaultdict
from math import isfinite
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

VERSION="completed_candle_patterns_v1"
HORIZONS=(1,5,15,30)
CLASSES=("down","flat","up")
DEADBAND_BPS=1.
MIN_SUPPORT=30
MIN_DAYS=5
SHRINK=20.
FEATURE_NAMES=("body_signed_fraction","upper_wick_fraction","lower_wick_fraction",
               "range_bps","close_location","previous_body_signed_fraction",
               "older_body_signed_fraction","range_ratio","three_candle_return_bps",
               "last_15m_return_bps","last_15m_range_bps","last_15m_vol_bps",
               "day_range_location","from_open_bps","session_fraction",
               "bull_engulf","bear_engulf","lower_rejection","upper_rejection",
               "inside","outside","three_up","three_down","bull_breakout","bear_breakout")


def _aggregate(bars,end,width):
    if end-width+1<0 or any(k not in bars for k in range(end-width+1,end+1)):
        return None
    rows=[bars[k] for k in range(end-width+1,end+1)]
    o,h,l,c=rows[0][0],max(r[1] for r in rows),min(r[2] for r in rows),rows[-1][3]
    if not all(isfinite(v) and v>0 for v in (o,h,l,c)) or not l<=min(o,c)<=max(o,c)<=h:
        return None
    return o,h,l,c


def _color(c):
    return "G" if c[3]>c[0] else "R" if c[3]<c[0] else "D"


def _body(c):
    return (c[3]-c[0])/max(c[1]-c[2],c[0]*1e-9)


def describe(bars,minute,frame):
    # Trailing candles are anchored at the completed decision minute,
    # never centered or interpolated. Session prefix must be contiguous.
    if minute<max(15,3*frame-1) or any(k not in bars for k in range(minute+1)):
        return None
    older,prev,cur=(_aggregate(bars,minute-i*frame,frame) for i in (2,1,0))
    if any(c is None for c in (older,prev,cur)):
        return None
    o,h,l,c=cur;r=max(h-l,o*1e-9)
    body=_body(cur);upper=(h-max(o,c))/r;lower=(min(o,c)-l)/r
    colors="".join(map(_color,(older,prev,cur)))
    bull=prev[3]<prev[0] and c>o and o<=prev[3] and c>=prev[0]
    bear=prev[3]>prev[0] and c<o and o>=prev[3] and c<=prev[0]
    low_reject=lower>=.55 and upper<=.25 and abs(body)<=.40
    high_reject=upper>=.55 and lower<=.25 and abs(body)<=.40
    inside=h<=prev[1] and l>=prev[2] and (h<prev[1] or l>prev[2])
    outside=h>prev[1] and l<prev[2]
    up=colors=="GGG";down=colors=="RRR"
    bu=c>max(older[1],prev[1]);bd=c<min(older[2],prev[2])
    flags=(bull,bear,low_reject,high_reject,inside,outside,up,down,bu,bd)
    labels=("bull_engulf","bear_engulf","lower_rejection","upper_rejection",
            "inside","outside","three_up","three_down","bull_breakout","bear_breakout")
    name=next((name for name,v in zip(labels,flags) if v),"other")
    last=[bars[k] for k in range(minute-15,minute+1)]
    closes=np.asarray([v[3] for v in last],dtype=float)
    if not np.all(np.isfinite(closes)) or min(closes)<=0:
        return None
    changes=10000*(closes[1:]/closes[:-1]-1)
    dh=max(bars[k][1] for k in range(minute+1));dl=min(bars[k][2] for k in range(minute+1))
    prior_range=max((older[1]-older[2]+prev[1]-prev[2])/2,o*1e-9)
    features=[body,upper,lower,10000*(h-l)/o,(c-l)/r,_body(prev),_body(older),
              min(20.,(h-l)/prior_range),10000*(c/older[0]-1),
              10000*(c/closes[0]-1),10000*(max(v[1] for v in last)-min(v[2] for v in last))/c,
              float(np.std(changes)),(c-dl)/(dh-dl) if dh>dl else .5,
              10000*(c/bars[0][0]-1),minute/375.]+[float(v) for v in flags]
    if not all(isfinite(x) for x in features):
        return None
    return {"features":features,"pattern":name,"colors":colors,
            "active_patterns":[name for name,v in zip(labels,flags) if v]}


def outcome(bars,minute,width):
    future=_aggregate(bars,minute+width,width)
    if future is None or minute not in bars or minute+width>=375:
        return None
    price=bars[minute][3]
    move=10000*(future[3]/price-1)
    label="up" if move>DEADBAND_BPS else "down" if move<-DEADBAND_BPS else "flat"
    next_colors=[]
    for i in (1,2,3):
        v=_aggregate(bars,minute+i*width,width) if minute+i*width<375 else None
        if v is None:
            break
        next_colors.append(_color(v))
    return {"label":label,"return_bps":move,"next_color":_color(future),
            "next_three_colors":"".join(next_colors) if len(next_colors)==3 else None,
            "up_excursion_bps":10000*(future[1]/price-1),
            "down_excursion_bps":10000*(future[2]/price-1)}


def _samples(index,days,width):
    rows=[];counts=Counter()
    for day in days:
        bars=index[day]
        # Aligned nonoverlapping targets, with at least 15m observed context.
        for minute in range(max(3,(16+width-1)//width)*width-1,375-width,width):
            counts["reserved"]+=1
            desc=describe(bars,minute,width)
            if desc is None:
                counts["missing_features"]+=1;continue
            future=outcome(bars,minute,width)
            if future is None:
                counts["missing_outcome"]+=1;continue
            rows.append({"session":day,"minute":minute,**desc,**future})
            counts["scored"]+=1
    return rows,dict(counts)


def _weights(rows):
    counts=Counter(r["session"] for r in rows)
    return np.asarray([1./counts[r["session"]] for r in rows])


def _prior(rows):
    counts=np.ones(3)
    weights=_weights(rows)*len(rows)/max(1,len({r["session"] for r in rows}))
    for r,w in zip(rows,weights):
        counts[CLASSES.index(r["label"])]+=w
    return counts/counts.sum()


class PatternLookup:
    def __init__(self,train,prior):
        self.prior=prior;self.groups=defaultdict(list)
        for r in train:
            self.groups[(r["pattern"],r["colors"])].append(r)
    def predict(self,rows):
        out=[]
        for r in rows:
            group=self.groups.get((r["pattern"],r["colors"]),[])
            if len(group)<MIN_SUPPORT or len({x["session"] for x in group})<MIN_DAYS:
                out.append(self.prior);continue
            # Balance the observed sessions, then shrink toward the training prior.
            w=_weights(group)*len(group)/len({x["session"] for x in group})
            counts=SHRINK*self.prior.copy()
            for x,v in zip(group,w):
                counts[CLASSES.index(x["label"])]+=v
            out.append(counts/counts.sum())
        return np.asarray(out)


def _predict(model,rows,prior):
    if not rows:
        return np.empty((0,3))
    if model is None:
        return np.tile(prior,(len(rows),1))
    if isinstance(model,PatternLookup):
        return model.predict(rows)
    raw=model.predict_proba([r["features"] for r in rows])
    return raw[:,[list(model.classes_).index(c) for c in CLASSES]]


def _metrics(rows,probs):
    if not rows:
        return {"scored":0,"sessions":0,"brier":None}
    truth=np.asarray([[float(r["label"]==c) for c in CLASSES] for r in rows])
    w=_weights(rows)
    confident=(np.max(probs[:,[0,2]],axis=1)>=.55)&(np.abs(probs[:,2]-probs[:,0])>=.10)
    pred=np.where(probs[:,2]>probs[:,0],2,0)
    return {"scored":len(rows),"sessions":len({r["session"] for r in rows}),
            "brier":float(np.average(np.sum((probs-truth)**2,axis=1),weights=w)),
            "accuracy":float(np.average(np.argmax(probs,axis=1)==np.argmax(truth,axis=1),weights=w)),
            "directional_calls":int(confident.sum()),
            "directional_accuracy":float(np.average((pred==np.argmax(truth,axis=1))[confident],
                                                     weights=w[confident])) if confident.any() else None,
            "mean_probability":dict(zip(CLASSES,map(float,np.average(probs,axis=0,weights=w)))),
            "observed_fraction":dict(zip(CLASSES,map(float,np.average(truth,axis=0,weights=w))))}


def _pattern_table(rows):
    groups=defaultdict(list)
    for r in rows:
        groups[r["pattern"]].append(r)
    out={}
    for name,g in sorted(groups.items()):
        if len(g)<MIN_SUPPORT or len({r["session"] for r in g})<MIN_DAYS:
            continue
        w=_weights(g)
        color=Counter(r["next_color"] for r in g)
        sequence=Counter(r["next_three_colors"] for r in g if r["next_three_colors"] is not None)
        out[name]={"anchors":len(g),"sessions":len({r["session"] for r in g}),
                   "direction_fraction":{c:float(np.average([r["label"]==c for r in g],weights=w)) for c in CLASSES},
                   "next_candle_color_counts":dict(color),"next_three_color_counts":dict(sequence),
                   "mean_return_bps":float(np.average([r["return_bps"] for r in g],weights=w)),
                   "mean_up_excursion_bps":float(np.average([r["up_excursion_bps"] for r in g],weights=w)),
                   "mean_down_excursion_bps":float(np.average([r["down_excursion_bps"] for r in g],weights=w))}
    return out


def assess(index,splits,signals=(),progress=None):
    """Fit only earlier index sessions. Attach raw features and frozen
    direction probabilities to later CPR opportunities, not training labels.
    """
    report={"version":VERSION,"deadband_bps":DEADBAND_BPS,"horizons":{},
            "feature_names":FEATURE_NAMES,"direction_rule_probability":.55,
            "warning":"Index direction and future candle color are distinct. "
                      "Overlapping three-candle outcomes are descriptive. "
                      "No option fills, profitability or independent confirmation implied."}
    models={};later=set(splits[1])|set(splits[2])
    for width in HORIZONS:
        if progress:progress(25,"Studying next "+str(width)+"-minute candle patterns")
        parts=[_samples(index,days,width) for days in splits]
        tr,va,te=[x[0] for x in parts]
        item={"coverage":dict(zip(("train","validation","holdout"),[x[1] for x in parts])),
              "pattern_library":{name:_pattern_table(rows) for name,rows in zip(("train","validation","holdout"),(tr,va,te))},
              "state":"insufficient_support"}
        report["horizons"][str(width)]=item
        if len({r["session"] for r in tr})<20 or len({r["session"] for r in va})<5 or min(Counter(r["label"] for r in tr).get(c,0) for c in CLASSES)<10:
            continue
        prior=_prior(tr);models_to_try={"prior":None,"pattern_lookup":PatternLookup(tr,prior)}
        X=[r["features"] for r in tr];y=[r["label"] for r in tr];w=_weights(tr)*len(tr)/len(set(r["session"] for r in tr))
        lr=make_pipeline(StandardScaler(),LogisticRegression(max_iter=500,C=.3))
        lr.fit(X,y,logisticregression__sample_weight=w)
        rf=RandomForestClassifier(n_estimators=100,max_depth=5,min_samples_leaf=20,random_state=23,n_jobs=1)
        rf.fit(X,y,sample_weight=w)
        models_to_try.update(logistic=lr,random_forest=rf)
        metrics={name:_metrics(va,_predict(model,va,prior)) for name,model in models_to_try.items()}
        chosen=min(models_to_try,key=lambda name:metrics[name]["brier"])
        model=models_to_try[chosen]
        evaluation={name:_metrics(te,_predict(obj,te,prior)) for name,obj in models_to_try.items()}
        item.update(state="exploratory_assessment",selected=chosen,validation=metrics,holdout=evaluation,
                    training_prior=dict(zip(CLASSES,map(float,prior))))
        models[width]=(model,prior,chosen)
    coverage=Counter()
    for s in signals:
        bars=index[s["session"]];minute=s["minute"]
        d=[describe(bars,minute,w) for w in (1,5,15)]
        if d[0] is None or d[1] is None:
            continue
        values=d[0]["features"]+d[1]["features"]+(d[2]["features"] if d[2] else [0.]*len(FEATURE_NAMES))+[float(d[2] is None)]
        s.setdefault("context_vectors",{})["patterns"]=values
        s["candle_pattern_types"]={str(w):x["pattern"] for w,x in zip((1,5,15),d) if x}
        coverage["pattern_features"]+=1
        if s["session"] in later and 5 in models:
            model,prior,chosen=models[5]
            probs=_predict(model,[d[1]],prior)[0]
            s["candle_direction_5m"]={**dict(zip(CLASSES,map(float,probs))),"selected":chosen}
            coverage["later_5m_forecast"]+=1
    report["signal_feature_coverage"]=dict(coverage)
    return report


def accepts(ep):
    p=ep.get("candle_direction_5m")
    if not p or p["selected"]=="prior":
        return False
    yes,no=("up","down") if ep["side"]=="CALL" else ("down","up")
    return p[yes]>=.55 and p[yes]-p[no]>=.10
