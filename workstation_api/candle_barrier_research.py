"""Completed-candle sequence and index first-passage research.

No option prices, trades, future-feature joins, or live policy promotion.
Chronological date splits and matched context ablations. All barriers are
index POINTS, not option premium returns. Intra-minute ordering is unknown.
"""
from collections import Counter, defaultdict
from datetime import date,timedelta
from math import isfinite
import numpy as np
from sklearn.ensemble import RandomForestClassifier

from . import candle_pattern_research as p, cpr_context_features as cx
from .cpr_hybrid_research import _stamp, SESSION_SPLITS

VERSION="sequence_first_passage_v1"
HORIZONS=(5,15,30)
DISTANCES=(25,50,100,200)
WINDOWS=(3,5,10,20)
TOUCH_CLASSES=("lower_first","neither","upper_first","ambiguous")
CLOSE_CLASSES=("down_at_least","within_band","up_at_least")
TASKS=tuple((kind,d,classes) for kind,classes in (("first_touch",TOUCH_CLASSES),
                                                 ("terminal_move",CLOSE_CLASSES)) for d in DISTANCES)
BANK_TASKS=tuple((s,kind,p.CLASSES) for kind in ("direction","divergence") for s in cx.PANEL_SYMBOLS)
SEQUENCE_NAMES=tuple(f"lag_{j}_{name}" for j in range(1,21) for name in ("return_bps","missing"))+tuple(
    f"window_{n}_{name}" for n in WINDOWS for name in (
        "return_bps","up_fraction","path_efficiency","range_bps","close_location",
        "distance_prior_high_bps","distance_prior_low_bps","last_vs_earlier_range",
        "volatility_bps","last_return_minus_earlier_mean","missing"))


def sequence_features(bars,minute):
    """A trailing sequence of completed five-minute OHLC bars.

    Short histories have explicit missing masks. No padding with invented
    market prices, no centered indicators, no use of future highs or lows.
    """
    short=p.describe(bars,minute,5)
    if short is None:
        return None
    seq=[]
    for j in range(20):
        end=minute-5*j
        if end-5<0 or end-5 not in bars:
            break
        candle=p._aggregate(bars,end,5)
        if candle is None or bars[end-5][3]<=0:
            break
        change=10000*(candle[3]/bars[end-5][3]-1)
        if not isfinite(change):
            return None
        seq.append((candle,change))
    if len(seq)<3:
        return None
    values=[]
    for j in range(20):
        values.extend((seq[j][1],0.) if j<len(seq) else (0.,1.))
    price=bars[minute][3]
    for n in WINDOWS:
        if len(seq)<n:
            values.extend([0.]*10+[1.]);continue
        group=seq[:n];rows=[c for c,_ in group];moves=np.asarray([v for _,v in group])
        start=bars[minute-5*n][3]
        highest=max(c[1] for c in rows);lowest=min(c[2] for c in rows)
        prev_hi=max(c[1] for c in rows[1:]);prev_lo=min(c[2] for c in rows[1:])
        ranges=[c[1]-c[2] for c in rows]
        old_range=float(np.mean(ranges[1:]))
        total=float(np.sum(np.abs(moves)))
        values.extend((10000*(price/start-1),float(np.mean(moves>0)),
                       abs(float(np.sum(moves)))/total if total>0 else 0.,
                       10000*(highest-lowest)/price,
                       (price-lowest)/(highest-lowest) if highest>lowest else .5,
                       10000*(price-prev_hi)/price,10000*(price-prev_lo)/price,
                       min(20.,ranges[0]/max(old_range,price*1e-9)),
                       float(np.std(moves)),float(moves[0]-np.mean(moves[1:])),0.))
    return {"short":short["features"],"sequence":values,
            "pattern":short["pattern"],"index_return_5m_bps":seq[0][1]} if all(isfinite(v) for v in values) else None


def outcomes(bars,minute,horizon):
    """Complete minute OHLC path, barriers anchored at decision close.

    Open beyond a barrier establishes first touch at the observed open.
    When both barriers occur within a bar with open between them, ordering
    is ambiguous, NOT assumed favorable. A gap censors the entire outcome.
    """
    if minute not in bars or minute+horizon>=375:
        return None
    future=[]
    for k in range(minute+1,minute+horizon+1):
        row=bars.get(k)
        if row is None:
            return None
        o,h,l,c=map(float,row[:4])
        if not all(isfinite(v) and v>0 for v in (o,h,l,c)) or not l<=min(o,c)<=max(o,c)<=h:
            return None
        future.append((o,h,l,c))
    price=bars[minute][3]
    if not isfinite(price) or price<=0:
        return None
    upper=max(x[1] for x in future)-price
    lower=price-min(x[2] for x in future)
    move=future[-1][3]-price
    labels=[]
    for kind,d,classes in TASKS:
        if kind=="terminal_move":
            label="up_at_least" if move>=d else "down_at_least" if move<=-d else "within_band"
        else:
            label="neither"
            for o,h,l,_ in future:
                if o>=price+d:
                    label="upper_first";break
                if o<=price-d:
                    label="lower_first";break
                up=h>=price+d;down=l<=price-d
                if up and down:
                    label="ambiguous";break
                if up or down:
                    label="upper_first" if up else "lower_first";break
        labels.append(classes.index(label))
    return {"labels":labels,"terminal_points":move,
            "upper_excursion_points":upper,"lower_excursion_points":lower}


def _weights(rows):
    days=Counter(r["session"] for r in rows)
    return np.asarray([1./days[r["session"]] for r in rows],dtype=float)


def _score(rows,probs,y,classes):
    if not rows:
        return {"scored":0,"sessions":0,"brier":None}
    w=_weights(rows);truth=np.eye(len(classes))[y]
    losses=np.sum((probs-truth)**2,axis=1)
    daily=defaultdict(list)
    for r,v in zip(rows,losses):
        daily[r["session"]].append(float(v))
    return {"scored":len(rows),"sessions":len(daily),
            "brier":float(np.average(losses,weights=w)),
            "accuracy":float(np.average(np.argmax(probs,axis=1)==y,weights=w)),
            "predicted":dict(zip(classes,map(float,np.average(probs,axis=0,weights=w)))),
            "observed":dict(zip(classes,map(float,np.average(truth,axis=0,weights=w)))),
            "daily_brier":{day:float(np.mean(vals)) for day,vals in sorted(daily.items())}}


def _paired(candidate,base):
    days=sorted(set(candidate["daily_brier"])&set(base["daily_brier"]))
    if not days:
        return None
    diff=np.asarray([candidate["daily_brier"][d]-base["daily_brier"][d] for d in days])
    rng=np.random.default_rng(19)
    dist=np.mean(rng.choice(diff,size=(1000,len(diff)),replace=True),axis=1)
    return {"sessions":len(days),"brier_difference":float(np.mean(diff)),
            "day_bootstrap_95pct_exploratory":list(map(float,np.quantile(dist,[.025,.975])))}


def _features(row,model):
    x=list(row["short"])
    if model!="short":
        x+=row["sequence"]
    vectors=row.get("context_vectors",{})
    if model in ("sequence_panel","sequence_panel_global"):
        x+=vectors["panel_detail"]
    if model in ("sequence_global","sequence_panel_global"):
        # Change, age, missingness only; avoid memorizing absolute levels.
        g=vectors["global"]
        x+=[g[i] for i in range(len(g)) if i%4!=0]
    return x


def _fit(parts,model,tasks=TASKS):
    tr,va,te=parts
    info={"coverage":[len(x) for x in parts],"sessions":[len({r["session"] for r in x}) for x in parts],
          "state":"insufficient_matched_support","tasks":{}}
    if info["sessions"][0]<20 or info["sessions"][1]<5 or not te:
        return info
    train_y=np.asarray([r["labels"] for r in tr],dtype=int)
    w=_weights(tr)*len(tr)/info["sessions"][0]
    rf=RandomForestClassifier(n_estimators=80,max_depth=6,min_samples_leaf=15,random_state=29,n_jobs=1)
    rf.fit([_features(r,model) for r in tr],train_y,sample_weight=w)
    v=rf.predict_proba([_features(r,model) for r in va])
    t=rf.predict_proba([_features(r,model) for r in te])
    for i,(kind,d,classes) in enumerate(tasks):
        n=len(classes);prior=np.ones(n)
        for y,weight in zip(train_y[:,i],w):
            prior[y]+=weight
        prior/=prior.sum()
        def align(raw):
            result=np.zeros((len(raw),n))
            result[:,np.asarray(rf.classes_[i],dtype=int)]=raw
            return result
        vy=np.asarray([r["labels"][i] for r in va],dtype=int)
        ty=np.asarray([r["labels"][i] for r in te],dtype=int)
        vp=_score(va,np.tile(prior,(len(va),1)),vy,classes)
        vr=_score(va,align(v[i]),vy,classes)
        tp=_score(te,np.tile(prior,(len(te),1)),ty,classes)
        trf=_score(te,align(t[i]),ty,classes)
        selected="random_forest" if vr["brier"]<vp["brier"] else "training_prior"
        info["tasks"][f"{kind}_{d}"]={"selected_on_validation":selected,"training_prior":dict(zip(classes,map(float,prior))),
            "training_class_counts":dict(Counter(classes[y] for y in train_y[:,i])),
            "validation":{"training_prior":vp,"random_forest":vr},
            "holdout":{"training_prior":tp,"random_forest":trf},
            "rf_minus_prior":_paired(trf,tp)}
    info["state"]="exploratory_assessment"
    return info


def bank_outcomes(index,panel,day,minute,horizon):
    """Future individual bank directions and relative-to-index moves.

    One-basis-point bands are fixed before fitting. No bank target exists
    unless all five same-identity future bar paths are observed.
    """
    future=p._aggregate(index[day],minute+horizon,horizon)
    if future is None or minute not in index[day]:
        return None
    index_move=10000*(future[3]/index[day][minute][3]-1)
    moves={}
    for symbol in cx.PANEL_SYMBOLS:
        bars=panel.get(symbol,{}).get(day,{})
        end=p._aggregate(bars,minute+horizon,horizon)
        if end is None or minute not in bars or bars[minute][3]<=0:
            return None
        moves[symbol]=10000*(end[3]/bars[minute][3]-1)
    labels=[]
    for symbol,kind,classes in BANK_TASKS:
        change=moves[symbol]-(index_move if kind=="divergence" else 0.)
        label="up" if change>p.DEADBAND_BPS else "down" if change<-p.DEADBAND_BPS else "flat"
        labels.append(classes.index(label))
    return labels


def assess(index,splits,*,context_mode="off",fixed_panel=False,context_batch="auto",progress=None):
    if context_mode not in ("off","receipt","archive") or (fixed_panel and context_mode=="off"):
        raise ValueError("Fixed-panel features require explicit context mode")
    days=[d for part in splits for d in part]
    if not days or len(days)!=len(set(days)) or days!=sorted(days):
        raise ValueError("Require unique chronological session splits")
    anchors={}
    coverage=defaultdict(Counter)
    # Construct only completed feature rows first. Context availability
    # never depends on whether the future path is observed.
    for day in days:
        for minute in range(19,375-min(HORIZONS),5):
            d=sequence_features(index[day],minute)
            if d is not None:
                anchors[(day,minute)]={"session":day,"minute":minute,"side":"CALL",
                    "decision_utc":_stamp(day,minute+1),**d}
    if progress:progress(20,"Attaching as-of context to completed candle anchors")
    context=cx.attach(list(anchors.values()),mode=context_mode,batch_id=context_batch,
                      fixed_panel=fixed_panel,panel_detail=fixed_panel)
    report={"version":VERSION,"horizons":{},"context":{k:v for k,v in context.items() if k!="anchors"},
            "short_feature_names":p.FEATURE_NAMES,"sequence_feature_names":SEQUENCE_NAMES,
            "distances_points":DISTANCES,"horizon_minutes":HORIZONS,
            "training_dates":splits[0],"validation_dates":splits[1],"holdout_dates":splits[2],
            "warning":"Previously inspected dates remain exploratory. First-touch OHLC order can be ambiguous; "
                      "session-block intervals are descriptive, not multiplicity-adjusted certification. "
                      "Index points are not option-premium returns; no simulated or actual fills."}
    panel={}
    panel_meta=context.get("fixed_panel_sources",{})
    if fixed_panel and panel_meta.get("state")=="loaded":
        panel,_,target_meta=cx._load_fixed_panel(date.fromisoformat(days[0]),date.fromisoformat(days[-1])+timedelta(days=1),
                                 context.get("bank_sources",{}),enabled=True)
        if target_meta.get("source_hashes")!=panel_meta.get("source_hashes"):
            # Maintenance may have updated an original file during the run.
            panel={};report["bank_target_state"]="source_changed_during_research"
        else:
            report["bank_target_state"]="observed_fixed_panel" if panel else "unavailable"
    else:
        report["bank_target_state"]="unavailable" if fixed_panel else "disabled"
    report["bank_directions"]={}
    for horizon in HORIZONS:
        if progress:progress(40+HORIZONS.index(horizon)*15,"Estimating "+str(horizon)+"-minute movement and first passage")
        parts=[]
        for split,ds in zip(("train","validation","holdout"),splits):
            rows=[];counts=Counter()
            for day in ds:
                # A fixed clock ensures nonoverlapping outcome windows per horizon.
                for minute in range(19,375-horizon,horizon):
                    counts["reserved"]+=1
                    feature=anchors.get((day,minute))
                    if feature is None:
                        counts["missing_features"]+=1;continue
                    label=outcomes(index[day],minute,horizon)
                    if label is None:
                        counts["missing_outcomes"]+=1;continue
                    rows.append({**feature,**label});counts["scored"]+=1
            parts.append(rows);coverage[str(horizon)][split]=dict(counts)
        item={"coverage":dict(coverage[str(horizon)]),"scopes":{}}
        report["horizons"][str(horizon)]=item
        scopes={"sequence":((),"sequence")}
        if context_mode!="off":
            scopes["global"]=(("global",),"sequence_global")
            if fixed_panel:
                scopes.update(panel=(("panel_detail",),"sequence_panel"),
                              panel_global=(("panel_detail","global"),"sequence_panel_global"))
        for name,(required,augmented) in scopes.items():
            matched=[[r for r in rows if all(g in r.get("context_vectors",{}) for g in required)] for rows in parts]
            base_model="short" if name=="sequence" else "sequence"
            base=_fit(matched,base_model);aug=_fit(matched,augmented)
            comparison={}
            for task in base["tasks"].keys()&aug["tasks"].keys():
                a=aug["tasks"][task];b=base["tasks"][task]
                comparison[task]=_paired(a["holdout"][a["selected_on_validation"]],b["holdout"][b["selected_on_validation"]])
            item["scopes"][name]={"matched_coverage":dict(zip(("train","validation","holdout"),map(len,matched))),
                                 "baseline":base,"augmented":aug,"selected_model_comparison":comparison}
        if panel:
            bank_parts=[]
            for rows in parts:
                eligible=[]
                for row in rows:
                    if "panel_detail" not in row.get("context_vectors",{}):
                        continue
                    labels=bank_outcomes(index,panel,row["session"],row["minute"],horizon)
                    if labels is not None:
                        eligible.append({**row,"labels":labels})
                bank_parts.append(eligible)
            base=_fit(bank_parts,"sequence",BANK_TASKS);aug=_fit(bank_parts,"sequence_panel",BANK_TASKS)
            comparison={}
            for task in base["tasks"].keys()&aug["tasks"].keys():
                aa=aug["tasks"][task];bb=base["tasks"][task]
                comparison[task]=_paired(aa["holdout"][aa["selected_on_validation"]],bb["holdout"][bb["selected_on_validation"]])
            report["bank_directions"][str(horizon)]={"matched_coverage":dict(zip(("train","validation","holdout"),map(len,bank_parts))),
                "baseline":base,"augmented":aug,"selected_model_comparison":comparison,
                "warning":"Direction is the bank's return; divergence is its return minus BANKNIFTY return. Both use +/-1bp bands, not index weights."}
        if parts[2]:
            item["holdout_movement_distribution"]={key:{str(q):float(np.quantile([r[key] for r in parts[2]],q))
                for q in (.1,.25,.5,.75,.9)} for key in ("terminal_points","upper_excursion_points","lower_excursion_points")}
    if progress:progress(100,"Completed-candle barrier comparison finished")
    return report
