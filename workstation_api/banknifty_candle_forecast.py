"""Single BANKNIFTY next-five-minute OHLC research system.

Walk forward by entire trading sessions. Fit on nonoverlapping anchors, assess
on every eligible minute, and select only on validation. Outputs are index
forecasts, not orders, option P&L, or live-trading approval.
"""
from collections import Counter
from datetime import date, datetime, timedelta
import json
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor, HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge, LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from . import historical_alpha as h, banknifty_forecast_features as f
from . import cpr_hybrid_research as r, predictive_option_research as p
from . import expired_options_backtest as exp

VERSION="banknifty_ohlc_forecast_v3"
MAX_CORE_DAYS=1827
MAX_CONTEXT_DAYS=400
TRAIN_STRIDE=5
MIN_TRAIN_DAYS=40
MIN_ASSESS_DAYS=15
MIN_CONTEXT_TRAIN_DAYS=10
SCOPES={"index":("index",),"index_banks":("index","banks"),
        "index_peers":("index","peers"),"index_options":("index","options"),
        "combined":("index","banks","peers","options")}
ALGORITHMS=("ridge","hist_gradient")
FIELDS=("open","high","low","close")


def split_days(dates):
    if len(dates)<75:
        raise ValueError("Need at least 75 observed index sessions for chronological support")
    n=len(dates);a=int(.6*n);b=int(.8*n)
    if a<MIN_TRAIN_DAYS or b-a<MIN_ASSESS_DAYS or n-b<MIN_ASSESS_DAYS:
        raise ValueError("Chronological split has insufficient session support")
    return dates[:a],dates[a:b],dates[b:]


def load_sources(start,stop,*,wings,index_only=False,progress=None):
    if progress:progress("Verifying original BANKNIFTY index receipts")
    index,hashes,failures=h.shared_index_sources(start,stop,[h.MAX_TOTAL])
    index={d:f.dense(bars) for d,bars in sorted(index.items()) if start.isoformat()<=d<stop.isoformat() and date.fromisoformat(d).weekday()<5}
    dates=sorted(index)
    split_days(dates)
    index_meta={"source_hashes":hashes,"failures":failures,"sessions":len(index),
                "complete_regular_sessions":sum(f.daily_ohlc(a) is not None for a in index.values()),
                "observed_minutes":sum(int(np.isfinite(a[:,3]).sum()) for a in index.values())}
    if index_only:
        # Preserve the same verified index loader and research clock. Do not
        # open shorter constituent, peer or expired-option history at all.
        return index,{},{},{},{},{},{"index":index_meta,
            "banks":{"state":"disabled_index_only","membership_days":0,"source_hashes":{},"weighted_days":0},
            "peers":{},"options":{"state":"disabled_index_only"}}
    stocks,membership,weights,banks=f.load_membership(dates,start,stop,progress)
    peers={};peer_meta={}
    for identity in f.PEERS:
        if progress:progress("Verifying peer "+identity)
        try:
            x,hs,fs=h.shared_index_sources(start,stop,[h.MAX_TOTAL],identity=identity)
            peers[identity]={d:f.dense(bars) for d,bars in x.items() if d in index}
            peer_meta[identity]={"state":"loaded","source_hashes":hs,"failures":fs,"sessions":len(peers[identity]),
                                 "observed_minutes":sum(int(np.isfinite(a[:,3]).sum()) for a in peers[identity].values())}
        except (OSError,ValueError,TypeError,KeyError) as exc:
            peer_meta[identity]={"state":"unavailable","reason":str(exc)[:180]}
    table={};option_meta={"state":"disabled"}
    if wings is not None:
        try:
            if progress:progress("Verifying saved option-chain receipts")
            stamps={r._stamp(d,m) for d in dates for m in range(f.LOOKBACK-6,f.MINUTES-f.HORIZON)}
            table,meta=p._load_options([{"session":d} for d in dates],wings,needed_stamps=stamps,
                                       progress=(lambda _,msg:progress(msg)) if progress else None)
            option_meta={**meta,"state":"loaded" if table else "unavailable","wings":wings}
        except (OSError,ValueError,RuntimeError,TypeError,KeyError) as exc:
            option_meta={"state":"unavailable","reason":str(exc)[:180],"wings":wings}
    return index,stocks,membership,weights,peers,table,{"index":index_meta,
               "banks":banks,"peers":peer_meta,"options":option_meta}


def assemble(index,stocks,membership,weights,peers,table,*,index_only=False,horizon=f.HORIZON,progress=None):
    if type(horizon) is not int or horizon not in f.HORIZONS:raise ValueError("Unsupported forecast horizon")
    if horizon!=f.HORIZON and not index_only:raise ValueError("Nondefault horizons require explicit index-only mode")
    dates=sorted(index);ids=sorted({v for x in membership.values() for v in x.values()})
    buffers={key:[] for key in ("index","banks","peers","options")}
    names={};availability={key:[] for key in ("banks","peers","options")}
    all_days=[];all_minutes=[];all_ref=[];all_y=[];all_real=[]
    prior_daily=[];coverage={};bank_scheduled=[];bank_closed=[]
    # The long-history lane retains the existing core feature schema without
    # accumulating hundreds of per-day matrices and then duplicating them
    # with vstack. No bank/peer/option matrix is allocated in this lane.
    index_matrix=None;index_count=0
    max_rows=len(dates)*(f.MINUTES-horizon-f.LOOKBACK+1)
    for i,day in enumerate(dates):
        if progress and (i==0 or (i+1)%20==0 or i+1==len(dates)):
            progress(f"Building causal feature windows {i+1}/{len(dates)} {day}")
        a=index[day];minutes,y,real=f.anchors(a,horizon)
        coverage[day]={"eligible_index_windows":len(minutes),"complete_regular_index":f.daily_ohlc(a) is not None}
        prior=prior_daily[-1] if prior_daily else None
        if len(minutes):
            ns,features=f.price_features(a,index=True,prior=prior,earlier_days=prior_daily)
            seq=f.sequence(a,minutes).reshape(len(minutes),-1)
            ns+=tuple(f"lag_{f.LOOKBACK-1-j}m_{field}_relative_pct" for j in range(f.LOOKBACK) for field in FIELDS)
            # Sequence order in source is O,H,L,C. Keep same column names.
            extra=np.column_stack((np.full(len(minutes),date.fromisoformat(day).weekday()),
                                   np.full(len(minutes),(exp._nominal_selected_expiry(date.fromisoformat(day),0)-date.fromisoformat(day)).days)))
            ns+=("weekday","days_to_nominal_monthly_expiry")
            blocks={"index":(ns,np.column_stack((features[minutes],seq,extra)).astype(np.float32))}
            if index_only:
                scheduled=np.zeros(len(minutes),dtype=int)
                members=set()
                bok=pok=ook=np.zeros(len(minutes),dtype=bool)
                # Zero-width placeholders retain reporting compatibility,
                # not invented observations or missing context features.
                for key in ("banks","peers","options"):
                    blocks[key]=((),np.empty((len(minutes),0),dtype=np.float32))
            else:
                members=set(membership.get(day,{}).values())
                scheduled=f.scheduled_bank_counts(day,minutes,members)
                bn,bv,bok=f.banks_at(day,minutes,ids,stocks,members,weights.get(day),dates[:i],a[:,3])
                pn,pv,pok=f.peers_at(day,minutes,peers,a[:,3])
                ov=np.stack([f.option_at(table,day,int(m),a[m,3]) for m in minutes]).astype(np.float32)
                ook=np.isfinite(ov[:,1])
                blocks.update(banks=(bn,bv),peers=(pn,pv),options=(f.OPTION_NAMES,ov))
            bank_scheduled.extend((scheduled>0).tolist())
            bank_closed.extend(((scheduled==0)&bool(members)).tolist())
            coverage[day]["bank_scheduled_open_windows"]=int((scheduled>0).sum())
            coverage[day]["bank_scheduled_closed_windows"]=int(((scheduled==0)&bool(members)).sum())
            for key,(columns,values) in blocks.items():
                if key in names and names[key]!=columns:raise ValueError("Feature schema changed across sessions")
                names[key]=columns
                values=np.asarray(values,dtype=np.float32);values[~np.isfinite(values)]=np.nan
                if index_only:
                    if key=="index":
                        if index_matrix is None:
                            index_matrix=np.empty((max_rows,len(columns)),dtype=np.float32)
                        end=index_count+len(minutes)
                        if end>max_rows:raise ValueError("Index feature row bound exceeded")
                        index_matrix[index_count:end]=values;index_count=end
                else:
                    buffers[key].append(values)
            for key,ok in (("banks",bok),("peers",pok),("options",ook)):
                availability[key].append(ok);coverage[day][key+"_available_windows"]=int(ok.sum())
            all_days.extend([day]*len(minutes));all_minutes.extend(minutes.tolist())
            all_ref.extend(a[minutes,3].tolist());all_y.append(y);all_real.append(real)
        prior_daily.append(f.daily_ohlc(a))
    if not all_days:raise ValueError("No complete 60-minute input and requested-horizon target windows")
    matrix=({"index":index_matrix[:index_count],
             **{k:np.empty((index_count,0),dtype=np.float32) for k in ("banks","peers","options")}}
            if index_only else {k:np.vstack(v) for k,v in buffers.items()})
    return {"days":np.asarray(all_days),"minutes":np.asarray(all_minutes,dtype=int),"ref":np.asarray(all_ref),
            "y":np.vstack(all_y),"actual":np.vstack(all_real),
            "blocks":matrix,"names":names,
            "available":{k:np.concatenate(v) for k,v in availability.items()},"coverage":coverage,
            "bank_scheduled":np.asarray(bank_scheduled,dtype=bool),"bank_closed":np.asarray(bank_closed,dtype=bool)}


def decode(ref,encoded):
    ref=np.asarray(ref,float)
    y=np.asarray(encoded,float)
    if y.shape!=(len(ref),4) or not np.isfinite(y).all() or not np.isfinite(ref).all() or np.any(ref<=0):
        raise ValueError("Invalid OHLC forecast")
    op=np.maximum(.01,ref*(1+y[:,0]/100))
    cl=np.maximum(.01,ref*(1+y[:,1]/100))
    hi=np.maximum(op,cl)+ref*np.maximum(y[:,2],0)/100
    lo=np.maximum(.01,np.minimum(op,cl)-ref*np.maximum(y[:,3],0)/100)
    return np.column_stack((op,hi,lo,cl))


def day_weights(days):
    count=Counter(days.tolist())
    w=np.asarray([1/count[d] for d in days],dtype=float)
    return w/w.mean()


def _avg(x,days):
    return np.average(x,axis=0,weights=day_weights(days))


def metrics(actual,pred,ref,days):
    if not len(ref):return {"rows":0,"days":0}
    err=np.abs(actual-pred);rel=100*err/ref[:,None]
    direction=(actual[:,3]>ref).astype(int);guess=(pred[:,3]>ref).astype(int)
    classes=[float(_avg((guess[direction==k]==k).astype(float),days[direction==k])) for k in (0,1) if (direction==k).any()]
    return {"rows":len(ref),"days":len(set(days.tolist())),
            "day_weighted_mae_points":{k:float(x) for k,x in zip(FIELDS,_avg(err,days))},
            "day_weighted_mae_pct":{k:float(x) for k,x in zip(FIELDS,_avg(rel,days))},
            "mean_ohlc_mae_pct":float(_avg(rel.mean(axis=1),days)),
            "range_mae_points":float(_avg(np.abs((actual[:,1]-actual[:,2])-(pred[:,1]-pred[:,2])),days)),
            "direction_accuracy":float(_avg((direction==guess).astype(float),days)),
            "balanced_direction_accuracy":float(np.mean(classes)) if len(classes)==2 else None,
            "actual_up_rate":float(_avg(direction,days)),
            "predicted_up_rate":float(_avg(guess,days)),
            "mean_close_bias_points":float(_avg(pred[:,3]-actual[:,3],days))}


def baseline_fit(y,minutes):
    # Training-only time-of-day typical excursions, with flat O/C.
    default=np.median(y[:,2:],axis=0)
    buckets={int(k):np.median(y[minutes//30==k,2:],axis=0) for k in np.unique(minutes//30)}
    return default,buckets


def baseline_predict(minutes,fit):
    default,buckets=fit
    return np.column_stack((np.zeros((len(minutes),2)),np.stack([buckets.get(int(m//30),default) for m in minutes])))


def select_columns(x,train):
    # Drop features unavailable in the training partition only. No validation/
    # evaluation statistics enter feature selection, imputation or scaling.
    fraction=np.isfinite(x[train]).mean(axis=0)
    return fraction>=.05


def train_model(name,x,y,weights):
    if name=="ridge":
        model=make_pipeline(SimpleImputer(strategy="median",add_indicator=True,keep_empty_features=True),
                            StandardScaler(),Ridge(alpha=50.))
        model.fit(x,y,ridge__sample_weight=weights)
        return model
    if name=="hist_gradient":
        out=[]
        for k in range(4):
            model=HistGradientBoostingRegressor(max_iter=60,max_leaf_nodes=15,min_samples_leaf=80,
                                                 learning_rate=.06,l2_regularization=2.,max_bins=63,
                                                 early_stopping=False,random_state=0)
            model.fit(x,y[:,k],sample_weight=weights);out.append(model)
        return out
    raise ValueError("Unknown forecast algorithm")


def predict_model(model,x):
    if isinstance(model,list):return np.column_stack([m.predict(x) for m in model])
    return model.predict(x)


def direction_model(name,x,y,weights):
    if len(np.unique(y))<2:return None
    if name=="ridge":
        model=make_pipeline(SimpleImputer(strategy="median",add_indicator=True,keep_empty_features=True),
                            StandardScaler(),LogisticRegression(C=.1,max_iter=500,random_state=0))
        model.fit(x,y,logisticregression__sample_weight=weights)
    else:
        model=HistGradientBoostingClassifier(max_iter=60,max_leaf_nodes=15,min_samples_leaf=80,
                                            learning_rate=.06,l2_regularization=2.,max_bins=63,
                                            early_stopping=False,random_state=0)
        model.fit(x,y,sample_weight=weights)
    return model


def scope_matrix(data,groups):
    if len(groups)==1:return data["blocks"][groups[0]]
    return np.column_stack([data["blocks"][g] for g in groups]).astype(np.float32,copy=False)


def _metrics(data,mask,pred):
    return metrics(data["actual"][mask],pred,data["ref"][mask],data["days"][mask])


def _coverage(data,masks):
    out={}
    for key,ok in data["available"].items():
        out[key]={}
        for part,mask in masks.items():
            chosen=ok&mask
            out[key][part]={"available_windows":int(chosen.sum()),"total_windows":int(mask.sum()),
                            "days":len(set(data["days"][chosen].tolist()))}
            if key=="banks" and "bank_scheduled" in data:
                out[key][part].update(scheduled_open_windows=int((data["bank_scheduled"]&mask).sum()),
                                      scheduled_closed_windows=int((data["bank_closed"]&mask).sum()),
                                      undocumented_membership_windows=int((~data["bank_scheduled"]&~data["bank_closed"]&mask).sum()))
    return out


def adaptive_scale(vol,horizon):
    """Past 30-minute RMS log-return volatility in percentage units.
    Fixed 0.5 bp one-minute floor, scaled to the requested horizon.
    """
    vol=np.asarray(vol,float)
    if not np.isfinite(vol).all() or np.any(vol<0):
        raise ValueError("Adaptive baseline requires finite nonnegative past volatility")
    return np.maximum(vol,.005)*np.sqrt(horizon)


def adaptive_fit(actual,ref,minutes,vol,horizon):
    # Targets are training-only excursions from the decision close, not the
    # encoded wick labels beyond future O/C. Negative excursions clip to 0
    # because this comparator deliberately predicts O=C=last close.
    scale=adaptive_scale(vol,horizon)
    excursions=np.maximum(0.,100*np.column_stack((actual[:,1]-ref,ref-actual[:,2]))/ref[:,None])
    ratios=excursions/scale[:,None]
    default=np.median(ratios,axis=0)
    buckets={int(k):np.median(ratios[minutes//30==k],axis=0) for k in np.unique(minutes//30)}
    return default,buckets


def adaptive_predict(minutes,vol,horizon,fit):
    default,buckets=fit
    ratios=np.stack([buckets.get(int(k//30),default) for k in minutes])
    return np.column_stack((np.zeros((len(minutes),2)),ratios*adaptive_scale(vol,horizon)[:,None]))


def paired_day_interval(delta,days,*,block=5,draws=1000):
    """Exploratory circular moving-block bootstrap of daily mean differences.
    Negative loss difference favors the candidate; overlapping minute rows
    within a session are never treated as independent bootstrap draws.
    """
    unique,inverse=np.unique(days,return_inverse=True)
    n=len(unique)
    values=np.bincount(inverse,weights=delta)/np.bincount(inverse)
    if n<2*block:
        return {"days":n,"mean_difference":float(values.mean()),"interval_95":None}
    rng=np.random.default_rng(42)
    starts=rng.integers(0,n,size=(draws,(n+block-1)//block))
    idx=((starts[:,:,None]+np.arange(block))%n).reshape(draws,-1)[:,:n]
    samples=values[idx].mean(axis=1)
    return {"days":n,"mean_difference":float(values.mean()),
            "interval_95":[float(v) for v in np.quantile(samples,[.025,.975])],
            "block_observed_sessions":block,"draws":draws}


def probability_metrics(prob,y,days,prior):
    p=np.asarray(prob,float);y=np.asarray(y,float)
    weights=day_weights(days)
    base=np.full(len(p),prior)
    def loss(q):
        q=np.clip(q,1e-8,1-1e-8)
        return -(y*np.log(q)+(1-y)*np.log1p(-q))
    bins=[]
    bucket=np.minimum((p*10).astype(int),9)
    for k in range(10):
        chosen=bucket==k
        if chosen.any():
            w=weights[chosen]
            bins.append({"bin":k,"rows":int(chosen.sum()),
                         "sessions":len(set(days[chosen].tolist())),
                         "weight_fraction":float(w.sum()/weights.sum()),
                         "mean_probability":float(np.average(p[chosen],weights=w)),
                         "observed_up_rate":float(np.average(y[chosen],weights=w))})
    return {"brier":float(_avg((p-y)**2,days)),
            "training_base_rate_brier":float(_avg((base-y)**2,days)),
            "log_loss":float(_avg(loss(p),days)),
            "training_base_rate_log_loss":float(_avg(loss(base),days)),
            "training_up_rate":prior,"mean_predicted_up_probability":float(_avg(p,days)),
            "classifier_direction_accuracy":float(_avg((p>=.5)==y,days)),
            "reliability_bins":bins,
            "brier_difference_day_blocks":paired_day_interval((p-y)**2-(base-y)**2,days)}


def assess(data,splits,*,algorithms=ALGORITHMS,horizon=f.HORIZON,progress=None):
    if type(horizon) is not int or horizon not in f.HORIZONS:raise ValueError("Unsupported forecast horizon")
    tr,va,te=splits;days=data["days"];minutes=data["minutes"];y=data["y"];ref=data["ref"]
    masks={"train":np.isin(days,tr),"validation":np.isin(days,va),"evaluation":np.isin(days,te)}
    # Nonoverlapping horizon-sized target windows for fitting. Every minute
    # is scored out of sample; day weighting handles unequal session counts.
    train=masks["train"]&((minutes+1)%horizon==0)
    val=masks["validation"];test=masks["evaluation"]
    for label,mask,minimum in (("train",train,MIN_TRAIN_DAYS),("validation",val,MIN_ASSESS_DAYS),("evaluation",test,MIN_ASSESS_DAYS)):
        if len(set(days[mask].tolist()))<minimum:raise ValueError("Insufficient eligible index days in "+label)
    weights=day_weights(days[train])
    base=baseline_fit(y[train],minutes[train])
    naive={label:decode(ref[mask],baseline_predict(minutes[mask],base)) for label,mask in (("validation",val),("evaluation",test))}
    flat={label:decode(ref[mask],np.zeros((int(mask.sum()),4))) for label,mask in (("validation",val),("evaluation",test))}
    baseline={label:{"last_close":_metrics(data,mask,flat[label]),"last_close_typical_range":_metrics(data,mask,naive[label])}
              for label,mask in (("validation",val),("evaluation",test))}
    adaptive={}
    # Older synthetic unit-test matrices may not carry the feature schema.
    # Every original-source assembly has this completed-history feature.
    names=data.get("names",{}).get("index",())
    if "vol_30m_pct" in names:
        vol=data["blocks"]["index"][:,names.index("vol_30m_pct")]
        fit=adaptive_fit(data["actual"][train],ref[train],minutes[train],vol[train],horizon)
        for label,mask in (("validation",val),("evaluation",test)):
            adaptive[label]=decode(ref[mask],adaptive_predict(minutes[mask],vol[mask],horizon,fit))
            baseline[label]["last_close_adaptive_range"]=_metrics(data,mask,adaptive[label])
    coverage=_coverage(data,{"train_fit":train,"validation":val,"evaluation":test})
    result={"training_rows":int(train.sum()),"training_days":len(set(days[train].tolist())),
            "feature_coverage":coverage,"baselines":baseline,"validation":{},"selected":None}
    best=None;index_validation={}
    for scope,groups in SCOPES.items():
        # Scope eligibility is determined exclusively on the training part.
        available_groups=tuple(g for g in groups if g=="index" or coverage[g]["train_fit"]["days"]>=MIN_CONTEXT_TRAIN_DAYS)
        if scope!="combined" and available_groups!=groups or scope=="combined" and available_groups==("index",):
            result["validation"][scope]={"state":"insufficient_training_context","available_groups":list(available_groups)}
            continue
        if scope=="combined" and available_groups in tuple(SCOPES[k] for k in SCOPES if k!="combined"):
            result["validation"][scope]={"state":"duplicate_available_scope","available_groups":list(available_groups)}
            continue
        x=scope_matrix(data,available_groups);keep=select_columns(x,train)
        if not keep.any():continue
        if not keep.all():x=x[:,keep]
        scope_record={"state":"assessed","groups":list(available_groups),"features_retained":int(keep.sum()),"models":{}}
        for algorithm in algorithms:
            if progress:progress(f"Fitting {scope} / {algorithm}, {int(train.sum())} nonoverlapping windows, {int(keep.sum())} features")
            fitted=train_model(algorithm,x[train],y[train],weights)
            forecast=decode(ref[val],predict_model(fitted,x[val]))
            score=_metrics(data,val,forecast)
            # Compare identical validation windows and explicitly report
            # matched availability for each contextual scope.
            matched=val.copy()
            for g in available_groups:
                if g!="index":matched&=data["available"][g]
            match_inside=matched[val]
            score["matched_context"]=_metrics(data,matched,forecast[match_inside])
            score["matched_naive"]=_metrics(data,matched,naive["validation"][match_inside])
            if scope=="index":index_validation[algorithm]=forecast.copy()
            else:score["matched_index_only"]=_metrics(data,matched,index_validation[algorithm][match_inside])
            scope_record["models"][algorithm]=score
            if progress:progress(f"VALIDATION {scope} {algorithm} "+json.dumps({k:score[k] for k in ("rows","days","mean_ohlc_mae_pct","day_weighted_mae_points","balanced_direction_accuracy")}))
            rank=(score["mean_ohlc_mae_pct"],score["day_weighted_mae_pct"]["close"],list(SCOPES).index(scope),ALGORITHMS.index(algorithm))
            if best is None or rank<best[0]:
                best=(rank,scope,algorithm,available_groups,keep.copy(),fitted,forecast)
        result["validation"][scope]=scope_record
        del x
    if best is None:raise ValueError("No supported supervised forecast model")
    _,scope,algorithm,groups,keep,fitted,vpred=best
    x=scope_matrix(data,groups)
    if not keep.all():x=x[:,keep]
    tpred=decode(ref[test],predict_model(fitted,x[test]))
    val_score=_metrics(data,val,vpred);test_score=_metrics(data,test,tpred)
    matched=test.copy()
    for g in groups:
        if g!="index":matched&=data["available"][g]
    test_score["matched_context"]=_metrics(data,matched,tpred[matched[test]])
    test_score["matched_naive"]=_metrics(data,matched,naive["evaluation"][matched[test]])
    # Fixed validation residual quantiles; descriptive intervals, not formal
    # coverage guarantees under overlapping windows or shifting markets.
    residual=100*(data["actual"][val,3]-vpred[:,3])/ref[val]
    qlo,qhi=np.quantile(residual,[.1,.9])
    lower=tpred[:,3]+ref[test]*qlo/100;upper=tpred[:,3]+ref[test]*qhi/100
    truth=data["actual"][test,3]
    interval={"validation_residual_quantiles_pct":[float(qlo),float(qhi)],
              "nominal_interval_level":.8,"evaluation_day_weighted_coverage":float(_avg(((truth>=lower)&(truth<=upper)).astype(float),days[test])),
              "evaluation_mean_width_points":float(_avg(upper-lower,days[test]))}
    actual_up=(y[:,1]>0).astype(int)
    prior=float(np.average(actual_up[train],weights=weights))
    cls=direction_model(algorithm,x[train],actual_up[train],weights)
    prob=cls.predict_proba(x[test])[:,1] if cls is not None else np.full(int(test.sum()),prior)
    val_prob=cls.predict_proba(x[val])[:,1] if cls is not None else np.full(int(val.sum()),prior)
    probability={}
    for label,mask,pr in (("validation",val,val_prob),("evaluation",test,prob)):
        probability[label]=probability_metrics(pr,actual_up[mask],days[mask],prior)
    def skill(score,base):
        b=base["last_close_typical_range"]
        return {"ohlc_mae_skill":1-score["mean_ohlc_mae_pct"]/max(b["mean_ohlc_mae_pct"],1e-12),
                "close_mae_skill":1-score["day_weighted_mae_pct"]["close"]/max(b["day_weighted_mae_pct"]["close"],1e-12)}
    vskill=skill(val_score,baseline["validation"]);tskill=skill(test_score,baseline["evaluation"])
    result.update(selected={"scope":scope,"algorithm":algorithm,"groups":list(groups),"features_retained":int(keep.sum())},
                  selected_validation=val_score,evaluation=test_score,validation_skill=vskill,evaluation_skill=tskill,
                  close_interval=interval,direction_probability=probability,
                  state="exploratory_forecast_improved" if all(v>0 for v in (*vskill.values(),*tskill.values())) else "no_confirmed_ohlc_improvement")
    if adaptive:
        result["adaptive_comparison"]={}
        for label,mask,pred in (("validation",val,vpred),("evaluation",test,tpred)):
            actual=data["actual"][mask]
            base=adaptive[label]
            # Full OHLC relative error and high/low mean absolute point error
            # against the matched stronger comparator. Negative favors model.
            rel=100*(np.abs(actual-pred)-np.abs(actual-base))/ref[mask,None]
            extremes=(np.abs(actual[:,1:3]-pred[:,1:3])-np.abs(actual[:,1:3]-base[:,1:3])).mean(axis=1)
            result["adaptive_comparison"][label]={
                "ohlc_mae_pct_difference":paired_day_interval(rel.mean(axis=1),days[mask]),
                "high_low_mae_points_difference":paired_day_interval(extremes,days[mask]),
                "close_mae_points_difference":paired_day_interval(np.abs(actual[:,3]-pred[:,3])-np.abs(actual[:,3]-base[:,3]),days[mask])}
    else:
        result["adaptive_comparison"]={"state":"unavailable_feature_schema"}
    # Only selected model evaluated; every eligible test anchor is preserved.
    predictions=[]
    for i,j in enumerate(np.flatnonzero(test)):
        day=str(days[j]);m=int(minutes[j]);actual=data["actual"][j]
        predictions.append({"session":day,"decision_utc":r._stamp(day,m+1),"target_end_utc":r._stamp(day,m+1+horizon),
                            "decision_close":float(ref[j]),**{"actual_"+k:float(actual[n]) for n,k in enumerate(FIELDS)},
                            **{"predicted_"+k:float(tpred[i,n]) for n,k in enumerate(FIELDS)},
                            "up_probability":float(prob[i]),"close_interval_low":float(lower[i]),"close_interval_high":float(upper[i]),
                            **{g+"_context_available":bool(data["available"][g][j]) for g in ("banks","peers","options")}})
    return result,predictions


def run(*,days=365,to_date=None,wings=3,index_only=False,horizon=f.HORIZON,algorithms=ALGORITHMS,progress=None):
    if type(horizon) is not int or horizon not in f.HORIZONS:raise ValueError("Unsupported forecast horizon")
    if horizon!=f.HORIZON and not index_only:raise ValueError("Nondefault horizons require explicit index-only mode")
    today=datetime.now(h.IST).date();stop=date.fromisoformat(to_date) if to_date else today
    maximum=MAX_CORE_DAYS if index_only else MAX_CONTEXT_DAYS
    if type(days) is not int or not 120<=days<=maximum or stop>today or (wings is not None and not 0<=wings<=10):
        raise ValueError(f"Use 120-{maximum} calendar days, completed dates, and 0-10 option wings; longer studies require --index-only")
    if not algorithms or len(set(algorithms))!=len(algorithms) or any(x not in ALGORITHMS for x in algorithms):raise ValueError("Invalid algorithms")
    start=stop-timedelta(days=days)
    index,stocks,membership,weights,peers,table,meta=load_sources(start,stop,wings=wings,index_only=index_only,progress=progress)
    dates=sorted(index);splits=split_days(dates)
    data=assemble(index,stocks,membership,weights,peers,table,index_only=index_only,horizon=horizon,progress=progress)
    del index,stocks,membership,weights,peers,table
    result,predictions=assess(data,splits,algorithms=algorithms,horizon=horizon,progress=progress)
    report={"version":VERSION,"from_inclusive":start.isoformat(),"to_exclusive":stop.isoformat(),
            "requested_calendar_days":days,"mode":"index_only" if index_only else "context_comparison",
            "observed_date_span":[dates[0],dates[-1]],"core_feature_matrix_bytes":int(data["blocks"]["index"].nbytes),
            "lookback_minutes":f.LOOKBACK,"horizon_minutes":horizon,"training_stride_minutes":horizon,
            "training_dates":splits[0],"validation_dates":splits[1],"evaluation_dates":splits[2],
            "sources":meta,"feature_schema":{k:list(v) for k,v in data["names"].items()},"session_coverage":data["coverage"],
            **result,"warning":"Retrospective index forecasts only; no trades or option P&L. Dates previously used in research are not fresh confirmation. Whole-day chronological split; train on nonoverlapping horizon-sized targets, evaluate rolling forecasts every minute, day-weighted summaries do not imply independent observations. Missing source features remain missing, training-only imputation and feature retention. Dated historical memberships and recorded prior weights only, no present-day backfill. Rolling monthly option features are not exact contract-ID or historical bid/ask evidence; nominal expiry proxy. External global feeds are not included. Binary direction is future close above decision close versus not above; separate flat/first-passage labels and first-hour forecasting remain future work. The adaptive range baseline and observed-session block intervals are exploratory diagnostics, not selection on evaluation or proof of predictive edge. The validation-selected residual interval is descriptive, not a guarantee. No provider requests, data mutation, recorder restart or live deployment."}
    return report,predictions
