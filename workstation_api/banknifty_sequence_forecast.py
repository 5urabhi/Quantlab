"""Chronological comparison of compact multi-asset candle sequence models."""
from datetime import date, datetime, timedelta
import json
import numpy as np
from . import banknifty_candle_forecast as base, banknifty_forecast_features as f
from . import banknifty_sequence_data as d, historical_alpha as h
from . import cpr_hybrid_research as r

VERSION="banknifty_sequence_forecast_v1"
CONFIGS=(("cnn",60),("gru",60),("transformer",60),("transformer",15),
         ("transformer",30),("transformer",120))
ALL_CONFIGS=tuple((kind,lookback) for kind in ("cnn","gru","transformer") for lookback in d.LOOKBACKS)
EVENT_NAMES=("close_up","close_up_20","close_up_30","close_up_50",
             "close_down_20","close_down_30","close_down_50")
SEED=42
BANK_DROPOUT=.25
OPTION_DROPOUT=.15
PATIENCE=2


def _torch():
    try:
        import torch
        from . import banknifty_sequence_models as net
    except ImportError as exc:
        raise RuntimeError("Optional PyTorch dependency missing. Install the CPU PyTorch extra before sequence research.") from exc
    return torch,net


def _mean(values,days):
    return base._avg(np.asarray(values),np.asarray(days))


def masks(data,splits):
    result={key:np.flatnonzero(np.isin(data["days"],part)) for key,part in zip(("train","validation","evaluation"),splits)}
    for key,minimum in (("train",base.MIN_TRAIN_DAYS),("validation",base.MIN_ASSESS_DAYS),("evaluation",base.MIN_ASSESS_DAYS)):
        if len(set(data["days"][result[key]].tolist()))<minimum:
            raise ValueError("Insufficient common 120-minute window support in "+key)
    return result


def _target(data,rows):
    return (data["y"][rows]/data["scale"][rows,None]).astype(np.float32)


def _decode(data,rows,norm):
    return base.decode(data["ref"][rows],norm*data["scale"][rows,None])


def _price_interval(data,rows,norm):
    return data["ref"][rows,None]*(1+data["scale"][rows,None]*norm/100)


def _interval_score(actual,interval,days):
    lo,hi=interval.T
    return {"nominal_level":.8,"coverage":float(_mean((actual>=lo)&(actual<=hi),days)),
            "mean_width_points":float(_mean(hi-lo,days)),
            "mean_pinball_points":float(_mean((np.maximum(.1*(actual-lo),-.9*(actual-lo))+
                                                np.maximum(.9*(actual-hi),-.1*(actual-hi)))/2,days))}


def score(data,rows,pred,prob,interval):
    days=data["days"][rows];actual=data["actual"][rows];ref=data["ref"][rows]
    out=base.metrics(actual,pred,ref,days)
    y=d.event_targets(data,rows)
    if prob.shape!=y.shape or not np.isfinite(prob).all() or np.any((prob<0)|(prob>1)):
        raise ValueError("Invalid probability forecast")
    errors=_mean((prob-y)**2,days)
    rates=_mean(y,days);forecast=_mean(prob,days)
    out["events"]={key:{"brier":float(errors[j]),"observed_rate":float(rates[j]),
                        "predicted_rate":float(forecast[j])} for j,key in enumerate(EVENT_NAMES)}
    out["tail_mean_brier"]=float(np.mean(errors[1:]))
    out["direction_brier"]=float(errors[0])
    out["direction_probability_accuracy"]=float(_mean((prob[:,0]>=.5)==y[:,0],days))
    out["close_interval"]=_interval_score(actual[:,3],interval,days)
    return out


def adaptive_fit(data,train):
    y=_target(data,train);clock=data["minutes"][train]//30
    # Training-only robust typical excursions scaled by *current past*
    # volatility, stronger than a fixed price-point range baseline.
    default=np.median(y[:,2:],axis=0)
    buckets={int(k):np.median(y[clock==k,2:],axis=0) for k in np.unique(clock)}
    q=np.quantile(y[:,1],[.1,.9])
    prior=_mean(d.event_targets(data,train),data["days"][train])
    return default,buckets,q,prior


def adaptive_predict(data,rows,fit):
    default,buckets,q,prior=fit
    norm=np.column_stack((np.zeros((len(rows),2)),np.stack([buckets.get(int(m//30),default) for m in data["minutes"][rows]])))
    return _decode(data,rows,norm),np.tile(prior,(len(rows),1)),_price_interval(data,rows,np.tile(q,(len(rows),1)))


def _rank(metrics,benchmark):
    # Fixed selection objective: close error dominates, then direction
    # calibration, full OHLC, and mean large-move probability error.
    ratios=(metrics["day_weighted_mae_pct"]["close"]/max(benchmark["day_weighted_mae_pct"]["close"],1e-12),
            metrics["direction_brier"]/max(benchmark["direction_brier"],1e-12),
            metrics["mean_ohlc_mae_pct"]/max(benchmark["mean_ohlc_mae_pct"],1e-12),
            metrics["tail_mean_brier"]/max(benchmark["tail_mean_brier"],1e-12))
    return float(np.dot(ratios,[.45,.25,.15,.15]))


def fit_tabular(data,train,val,test,progress=None):
    # Refit the fixed v1 combined tree comparator on identical common
    # windows, retaining its original nonoverlapping training stride.
    subset=train[(data["minutes"][train]+1)%base.TRAIN_STRIDE==0]
    allx=data["v1_tabular"]
    train_mask=np.zeros(len(allx),bool);train_mask[subset]=True
    keep=base.select_columns(allx,train_mask)
    if not keep.any():raise ValueError("No training features for fixed tabular comparator")
    x=allx[:,keep]
    weights=base.day_weights(data["days"][subset])
    if progress:progress(f"Refitting matched v1 histogram-gradient comparator: {len(subset)} rows, {int(keep.sum())} features")
    model=base.train_model("hist_gradient",x[subset],data["y"][subset],weights)
    actual_up=(data["y"][:,1]>0).astype(int)
    classifier=base.direction_model("hist_gradient",x[subset],actual_up[subset],weights)
    prior=_mean(actual_up[subset],data["days"][subset])
    # Use only train prior for large-move probability comparators; tree v1
    # never supplied tail-event heads or quantiles.
    tails=_mean(d.event_targets(data,subset),data["days"][subset])
    p={}
    for key,rows in (("validation",val),("evaluation",test)):
        pred=base.decode(data["ref"][rows],base.predict_model(model,x[rows]))
        prob=np.tile(tails,(len(rows),1))
        prob[:,0]=classifier.predict_proba(x[rows])[:,1] if classifier is not None else prior
        p[key]=(pred,prob)
    residual=(data["actual"][val,3]-p["validation"][0][:,3])/data["ref"][val]*100/data["scale"][val]
    q=np.quantile(residual,[.1,.9])
    results={}
    for key,rows in (("validation",val),("evaluation",test)):
        pred,prob=p[key]
        interval=pred[:,3,None]+data["ref"][rows,None]*data["scale"][rows,None]*q[None,:]/100
        results[key]=score(data,rows,pred,prob,interval)
    return {"training_rows":len(subset),"features":int(keep.sum()),**results,
            "tail_note":"Training-only empirical tails; v1 has no fitted tail-probability heads.",
            "interval_note":"Validation standardized residual interval; descriptive."}


def _predict(model,data,rows,lookback,fit,batch,device):
    torch,_=_torch();model.eval()
    outputs=[[],[],[]]
    with torch.inference_mode():
        for start in range(0,len(rows),batch):
            part=rows[start:start+batch]
            x=torch.from_numpy(d.raw_windows(data,part,lookback)).to(device)
            c=torch.from_numpy(d.context_windows(data,part,fit)).to(device)
            z=model(x,c)
            for out,value in zip(outputs,z):out.append(value.detach().cpu().numpy())
    candle,prob,quantile=(np.concatenate(x,axis=0) for x in outputs)
    return _decode(data,rows,candle),prob,_price_interval(data,rows,quantile)


def fit_one(data,train,val,fit,kind,lookback,benchmark,*,epochs,batch,device,progress=None):
    torch,net=_torch()
    torch.manual_seed(SEED)
    if device.type=="cuda":torch.cuda.manual_seed_all(SEED)
    rng=np.random.default_rng(SEED)
    model=net.MarketSequence(kind,len(data["identities"]),len(d.CHANNELS),int(fit["keep"].sum())*2).to(device)
    optimizer=torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.01)
    weights=np.zeros(len(data["days"]),np.float32);weights[train]=base.day_weights(data["days"][train])
    best=None;history=[];stale=0
    for epoch in range(1,epochs+1):
        model.train();order=rng.permutation(train);running=0.;seen=0
        for i in range(0,len(order),batch):
            rows=order[i:i+batch]
            # Train on every eligible minute, including overlapping windows
            # inside train only. Mask whole bank context sometimes to cope
            # with the recorded absence of dated later-session membership.
            drop_banks=rng.random(len(rows))<BANK_DROPOUT
            drop_options=rng.random(len(rows))<OPTION_DROPOUT
            x=torch.from_numpy(d.raw_windows(data,rows,lookback,drop_banks=drop_banks)).to(device)
            c=torch.from_numpy(d.context_windows(data,rows,fit,drop_banks=drop_banks,drop_options=drop_options)).to(device)
            y=torch.from_numpy(_target(data,rows)).to(device)
            ev=torch.from_numpy(d.event_targets(data,rows)).to(device)
            w=torch.from_numpy(weights[rows]).to(device)
            optimizer.zero_grad(set_to_none=True)
            loss=net.objective(model(x,c),y,ev,w)
            if not bool(torch.isfinite(loss)):raise ValueError("Nonfinite neural loss")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(),1.)
            optimizer.step()
            running+=float(loss.detach().cpu())*len(rows);seen+=len(rows)
            if progress and i and i%(batch*200)==0:
                progress(f"TRAIN {kind} {lookback}m epoch {epoch}/{epochs} {seen}/{len(order)} windows")
        pred,prob,interval=_predict(model,data,val,lookback,fit,batch,device)
        metrics=score(data,val,pred,prob,interval);rank=_rank(metrics,benchmark)
        history.append({"epoch":epoch,"training_loss":running/seen,"validation_objective":rank})
        if progress:progress("VALIDATION "+kind+" "+str(lookback)+"m "+json.dumps({
            "epoch":epoch,"training_loss":running/seen,"objective":rank,
            "close_mae_points":metrics["day_weighted_mae_points"]["close"],
            "range_mae_points":metrics["range_mae_points"],"direction_brier":metrics["direction_brier"]}))
        if best is None or rank<best["rank"]-1e-6:
            best={"rank":rank,"epoch":epoch,"state":{k:v.detach().cpu().clone() for k,v in model.state_dict().items()},
                  "metrics":metrics}
            stale=0
        else:
            stale+=1
            if stale>=PATIENCE:break
    return {**best,"kind":kind,"lookback":lookback,"history":history,
            "parameters":sum(x.numel() for x in model.parameters())}


def _skill(model,benchmark):
    return {"close_mae_skill":1-model["day_weighted_mae_pct"]["close"]/max(benchmark["day_weighted_mae_pct"]["close"],1e-12),
            "ohlc_mae_skill":1-model["mean_ohlc_mae_pct"]/max(benchmark["mean_ohlc_mae_pct"],1e-12),
            "range_mae_skill":1-model["range_mae_points"]/max(benchmark["range_mae_points"],1e-12),
            "direction_brier_skill":1-model["direction_brier"]/max(benchmark["direction_brier"],1e-12),
            "tail_brier_skill":1-model["tail_mean_brier"]/max(benchmark["tail_mean_brier"],1e-12)}


def run(*,days=365,to_date=None,wings=3,epochs=6,batch=96,device_name="cpu",full_grid=False,progress=None):
    torch,net=_torch()
    if not 120<=days<=400 or not 1<=epochs<=20 or not 16<=batch<=256 or (wings is not None and not 0<=wings<=10):
        raise ValueError("Invalid bounded research parameters")
    if device_name not in ("cpu","cuda"):raise ValueError("Use cpu or cuda")
    if device_name=="cuda" and not torch.cuda.is_available():raise ValueError("Requested CUDA unavailable")
    device=torch.device(device_name)
    torch.set_num_threads(1)
    today=datetime.now(h.IST).date();stop=date.fromisoformat(to_date) if to_date else today
    if stop>today:raise ValueError("Study end must exclude current incomplete session")
    start=stop-timedelta(days=days)
    # Original option loader prints a message per 32 receipts; throttle
    # identical messages, not numerical epoch updates.
    last=[None]
    def announce(msg):
        if progress and msg!=last[0]:progress(msg)
        last[0]=msg
    index,stocks,membership,weights,peers,table,sources=base.load_sources(start,stop,wings=wings,progress=announce)
    splits=base.split_days(sorted(index))
    data=d.build(index,stocks,membership,weights,peers,table,splits,progress=announce)
    del index,stocks,membership,weights,peers,table
    partitions=masks(data,splits);train,val,test=(partitions[x] for x in ("train","validation","evaluation"))
    fit=d.context_fit(data,train)
    baseline=adaptive_fit(data,train)
    baselines={key:score(data,rows,*adaptive_predict(data,rows,baseline)) for key,rows in (("validation",val),("evaluation",test))}
    # The fixed reference comparator is not a candidate in neural selection.
    tabular=fit_tabular(data,train,val,test,announce)
    del data["v1_tabular"]
    if progress:progress("MATCHED BASELINE "+json.dumps({"validation":baselines["validation"],"evaluation":baselines["evaluation"]}))
    configurations=ALL_CONFIGS if full_grid else CONFIGS
    best=None;validation=[]
    for kind,lookback in configurations:
        announce(f"Fitting {kind} {lookback}m, {len(train)} rolling training windows on {device_name}")
        result=fit_one(data,train,val,fit,kind,lookback,baselines["validation"],epochs=epochs,batch=batch,device=device,progress=announce)
        validation.append({k:v for k,v in result.items() if k!="state"})
        if best is None or result["rank"]<best["rank"]:best=result
    kind,lookback=best["kind"],best["lookback"]
    model=net.MarketSequence(kind,len(data["identities"]),len(d.CHANNELS),int(fit["keep"].sum())*2).to(device)
    model.load_state_dict(best["state"])
    vp,vpr,vi=_predict(model,data,val,lookback,fit,batch,device)
    pred,prob,raw_interval=_predict(model,data,test,lookback,fit,batch,device)
    # Adapt the predicted quantile interval using validation-only scaled
    # misses; the evaluation partition is never used to calibrate the band.
    vtruth=data["actual"][val,3]
    vscale=data["ref"][val]*data["scale"][val]/100
    miss=np.maximum(vi[:,0]-vtruth,vtruth-vi[:,1])/vscale
    expansion=max(0.,float(np.quantile(miss,.8)))
    ts=data["ref"][test]*data["scale"][test]/100
    adjusted=raw_interval+np.column_stack((-expansion*ts,expansion*ts))
    val_metrics=score(data,val,vp,vpr,vi)
    eval_metrics=score(data,test,pred,prob,adjusted)
    eval_metrics["uncalibrated_close_interval"]=_interval_score(data["actual"][test,3],raw_interval,data["days"][test])
    skill_val=_skill(val_metrics,baselines["validation"]);skill_test=_skill(eval_metrics,baselines["evaluation"])
    vs_tab=_skill(eval_metrics,tabular["evaluation"])
    # Direction and close are the main purpose. An improvement in range
    # alone cannot qualify the model; this still is retrospective evidence.
    primary=("close_mae_skill","direction_brier_skill","ohlc_mae_skill")
    improved=all(skill_val[k]>0 and skill_test[k]>0 for k in primary)
    improved=improved and vs_tab["close_mae_skill"]>0 and vs_tab["direction_brier_skill"]>0
    selected={"kind":kind,"lookback":lookback,"epoch":best["epoch"],"parameters":best["parameters"],
              "validation_objective":best["rank"]}
    report={"version":VERSION,"from_inclusive":start.isoformat(),"to_exclusive":stop.isoformat(),
            "training_dates":splits[0],"validation_dates":splits[1],"evaluation_dates":splits[2],
            "partition_windows":{k:len(v) for k,v in partitions.items()},"common_lookback":max(d.LOOKBACKS),
            "assets":data["identities"],"sequence_channels":list(d.CHANNELS),"context_features":data["context_names"],
            "retained_context_features":[n for n,k in zip(data["context_names"],fit["keep"]) if k],
            "sources":sources,"feature_coverage":data["feature_coverage"],"session_bank_coverage":data["session_audit"],
            "adaptive_baselines":baselines,"matched_v1_tabular":tabular,"validation_models":validation,
            "selected":selected,"selected_validation":val_metrics,"evaluation":eval_metrics,
            "validation_skill_vs_adaptive":skill_val,"evaluation_skill_vs_adaptive":skill_test,"evaluation_skill_vs_v1":vs_tab,
            "validation_interval_expansion_in_volatility_units":expansion,"seed":SEED,"epochs_max":epochs,"batch_size":batch,
            "device":device_name,"torch_version":str(torch.__version__),"training_stride":1,
            "state":"exploratory_primary_skill_positive" if improved else "no_confirmed_directional_improvement",
            "warning":"Retrospective research; previously examined evaluation dates are exploratory, not fresh confirmation. All lookbacks compared on identical complete 120-minute input windows, excluding earlier minutes; engineered indicators can use earlier past bars. Training windows overlap within training sessions only; session weighting does not establish independence. Dated bank membership/weights only, missing later memberships masked, never backfilled from today's list. No global news, exact historical order books, trade fills, option-profit or live approval. Rolling option observations and nominal expiry are proxies. Validation used for early stopping, architecture selection and descriptive interval expansion; one selected neural model evaluated, fixed reference baselines evaluated on same rows. No orders or data downloads."}
    predictions=[]
    for i,j in enumerate(test):
        day=str(data["days"][j]);m=int(data["minutes"][j]);actual=data["actual"][j]
        predictions.append({"session":day,"decision_utc":r._stamp(day,m+1),"target_end_utc":r._stamp(day,m+1+f.HORIZON),
                            "decision_close":float(data["ref"][j]),"past_volatility_pct":float(data["scale"][j]),
                            **{"actual_"+k:float(actual[n]) for n,k in enumerate(base.FIELDS)},
                            **{"predicted_"+k:float(pred[i,n]) for n,k in enumerate(base.FIELDS)},
                            **{k+"_probability":float(prob[i,n]) for n,k in enumerate(EVENT_NAMES)},
                            "close_interval_low":float(adjusted[i,0]),"close_interval_high":float(adjusted[i,1]),
                            **{k+"_available":bool(data["available"][k][j]) for k in ("banks","peers","options")}})
    checkpoint={"version":VERSION,"selected":selected,"state_dict":best["state"],"assets":data["identities"],
                "channels":list(d.CHANNELS),"context_names":data["context_names"],
                "context_fit":{k:v.tolist() for k,v in fit.items()},"width":net.WIDTH,
                "validation_interval_expansion":expansion,"training_dates":splits[0],
                "validation_dates":splits[1],"research_only":True,"qualification_state":report["state"]}
    return report,predictions,checkpoint
