"""V4 fold-safe fitting and directional assessment; no trading actions."""
import json
import math

import numpy as np
from sklearn.linear_model import LogisticRegression,SGDClassifier
from threadpoolctl import threadpool_limits

from scripts import benchmark_market_dynamics as d
from scripts import market_dynamics_history as hist
from scripts import market_dynamics_v3 as v3

HORIZONS=(*d.HORIZONS,90,120,"EOD")
CANDIDATES=(("plain",128),("graph",128),("graph_moe",64),("graph_moe",128),("graph_moe",256))
SEEDS=(42,43,44)
CONFIDENCE=.60
COST_PROXY_BPS=5.


def folds(training,*,count=3,outer_days=40,inner_days=20):
    """Three nonoverlapping scoring blocks strictly inside original training."""
    dates=list(training)
    if dates!=sorted(set(dates)) or len(dates)<count*outer_days+inner_days+40:
        raise ValueError("Insufficient ordered sessions for V4 walk-forward folds")
    out=[]
    for i in range(count):
        start=len(dates)-(count-i)*outer_days
        out.append((dates[:start-inner_days],dates[start-inner_days:start],dates[start:start+outer_days]))
    return out


def rows_for(data,dates,stride=1):
    return np.flatnonzero(np.isin(data["days"],dates)&((data["minutes"]+1)%stride==0))


def material(data,rows,k):
    return data["mask"][rows,k]&(np.abs(data["y"][rows,k,0])>d.DEADBAND_BPS)


def prepare(data,split,*,stride,progress=None):
    train,validation,score=split
    if not (train and validation and score and max(train)<min(validation) and max(validation)<min(score)):
        raise ValueError("V4 split must be strictly chronological")
    tr=rows_for(data,train,stride);va=rows_for(data,validation);te=rows_for(data,score)
    train_all=rows_for(data,train)
    pre=rows_for(data,train,5)
    # Discover usable instruments strictly within this fold's fit dates.
    known=np.zeros(len(data["identities"]),bool)
    for i in np.unique(data["day_index"][pre]):
        known|=np.isfinite(data["pretrain_targets"][i]).all(axis=-1).any(axis=(0,2))
    if not known[0]:raise ValueError("No observed BANKNIFTY pretraining targets")
    tr=tr[(data["mask"][tr]&(np.abs(data["y"][tr,:,0])>d.DEADBAND_BPS)).any(axis=1)]
    if not len(tr) or not len(pre):raise ValueError("No V4 fit rows")
    for k in range(len(data["horizons"])):
        for part,minimum in ((tr,40),(va,15),(te,15)):
            # The scoring cohort is never used for training or model selection
            # except in explicitly designated inner historical screening folds.
            ix=part[material(data,part,k)]
            if len(set(data["days"][ix]))<minimum or len(np.unique(data["classes"][ix,k]))!=2:
                raise ValueError("Insufficient two-direction support for horizon "+str(data["horizons"][k]))
    fit=d.fit_aux(data,train_all)
    memory=v3.memory_grid(data,True,progress,known_assets=known)
    return {"tr":tr,"va":va,"te":te,"pre":pre,"known":known,"fit":fit,"memory":memory,
            "dates":[list(x) for x in split],"stride":stride}


def calibration(vp,y,days,ep):
    def logit(p):
        p=np.clip(p,1e-6,1-1e-6)
        return np.log(p/(1-p)).reshape(-1,1)
    if len(np.unique(y))!=2:raise ValueError("V4 calibration needs both signs")
    model=LogisticRegression(C=1.,max_iter=500,random_state=0)
    model.fit(logit(vp),y,sample_weight=d.m.day_weights(days))
    return model.predict_proba(logit(ep))[:,1],{"slope":float(model.coef_[0,0]),"intercept":float(model.intercept_[0])}


def calibrated(data,part,vp,ep):
    va=part["va"];out=np.zeros_like(ep,dtype=float);params=[]
    for k in range(len(data["horizons"])):
        take=material(data,va,k)
        out[:,k],fit=calibration(vp[take,k],data["classes"][va[take],k]==2,data["days"][va[take]],ep[:,k])
        params.append(fit)
    return out,params


def validation_rank(data,rows,p):
    values=[]
    for k in range(len(data["horizons"])):
        take=material(data,rows,k);ix=rows[take]
        if not len(ix):raise ValueError("No material validation observations")
        values.append(float(d.m._avg((p[take,k]-(data["classes"][ix,k]==2))**2,data["days"][ix])))
    return float(np.mean(values))


def lr_multiplier(step,total):
    warm=max(1,int(total*.05))
    if step<warm:return .1+.9*step/warm
    t=min(1.,(step-warm)/max(1,total-warm))
    return .05+.95*(1+math.cos(math.pi*t))/2


def fit_model(data,part,variant,width,seed,*,pre_epochs,epochs,batch,accumulate,patience,device,progress=None):
    torch,_=d.seq._torch()
    from workstation_api.market_direction_v4 import DirectionGraph,sign_loss
    from workstation_api.market_dynamics_v3 import factorized_loss
    torch.manual_seed(seed)
    if device.type=="cuda":torch.cuda.manual_seed_all(seed)
    if hasattr(torch.backends,"mha"):torch.backends.mha.set_fastpath_enabled(False)
    amp=device.type=="cuda" and torch.cuda.is_bf16_supported()
    if device.type=="cuda":
        torch.set_float32_matmul_precision("high");torch.cuda.reset_peak_memory_stats()
    rng=np.random.default_rng(seed);known=part["known"];tr,va,te,pre=(part[k] for k in ("tr","va","te","pre"))
    def inputs(rows):
        return v3.inputs(data,rows,True,part["fit"],part["memory"],known_assets=known)
    example=inputs(tr[:1])
    dims=(example[0].shape[2],example[0].shape[3],example[1].shape[2],example[2].shape[2])
    model=DirectionGraph(*dims,len(data["horizons"]),width=width,variant=variant).to(device)
    def tensor(value):return torch.from_numpy(np.asarray(value)).to(device)
    def forward(rows,pretrain=False):
        args=[tensor(x) for x in inputs(rows)]
        with torch.autocast(device_type=device.type,dtype=torch.bfloat16,enabled=amp):
            return model(*args,pretrain=pretrain)
    def pre_targets(rows):
        y,mask=v3.pretraining_targets(data,rows,True)
        return y[:,known],mask[:,known]
    counts=np.zeros((int(known.sum()),2),np.int64)
    for block in hist.batches(pre):
        _,mask=pre_targets(block);counts+=mask.sum(axis=0,dtype=np.int64)
    # Inspect learned routing in causal, overlapping regimes, not assigned expert names.
    ema_col=d.ASSET_FIELDS.index('ema9_minus_21_pct');vol_col=d.ASSET_FIELDS.index('vol_15m_pct')
    train_ema=data['grid'][data['day_index'][tr],data['minutes'][tr],0,ema_col]
    train_vol=data['grid'][data['day_index'][tr],data['minutes'][tr],0,vol_col]
    ema_threshold=float(np.quantile(np.abs(train_ema[np.isfinite(train_ema)]),.5)) if np.isfinite(train_ema).any() else None
    vol_threshold=float(np.quantile(train_vol[np.isfinite(train_vol)],.8)) if np.isfinite(train_vol).any() else None
    def predict(rows):
        model.eval();out=[];gate_sum=None;regime_sums={};regime_counts={}
        with torch.no_grad():
            for start in range(0,len(rows),batch):
                ix=rows[start:start+batch];logits,gates=forward(ix)
                out.append(logits.float().sigmoid().cpu().numpy())
                if gates is not None:
                    g=gates.detach().float().cpu().numpy();mass=g.sum(axis=0)
                    gate_sum=mass if gate_sum is None else gate_sum+mass
                    ema=data['grid'][data['day_index'][ix],data['minutes'][ix],0,ema_col]
                    vol=data['grid'][data['day_index'][ix],data['minutes'][ix],0,vol_col]
                    regimes={'first_30_minutes':data['minutes'][ix]<30}
                    if ema_threshold is not None:regimes.update(positive_ema_spread=ema>ema_threshold,negative_ema_spread=ema<-ema_threshold,small_ema_spread=np.abs(ema)<=ema_threshold)
                    if vol_threshold is not None:regimes['high_observed_volatility']=vol>=vol_threshold
                    for name,mask in regimes.items():
                        if mask.any():
                            regime_sums[name]=regime_sums.get(name,0)+g[mask].sum(axis=0)
                            regime_counts[name]=regime_counts.get(name,0)+int(mask.sum())
        routing=None if gate_sum is None else {'mean_mass':(gate_sum/len(rows)).tolist(),
            'regimes':{name:{'anchors':regime_counts[name],'mean_mass':(value/regime_counts[name]).tolist()} for name,value in regime_sums.items()},
            'train_ema_abs_median_pct':ema_threshold,'train_vol_80th_percentile_pct':vol_threshold}
        return np.concatenate(out),routing
    def setup(rows,maximum,lr):
        opt=torch.optim.AdamW(model.parameters(),lr=lr,weight_decay=.01)
        steps=math.ceil(math.ceil(len(rows)/batch)/accumulate)*maximum
        sch=torch.optim.lr_scheduler.LambdaLR(opt,lambda step:lr_multiplier(step,steps))
        weights=np.zeros(len(data["days"]),np.float32);weights[rows]=d.m.day_weights(data["days"][rows])
        return opt,sch,weights
    def epoch(rows,opt,sch,weights,e,maximum,pretrain):
        order=hist.shuffled_sessions(rows,data["day_index"],rng);model.train();total=0.;seen=0
        opt.zero_grad(set_to_none=True);batches=math.ceil(len(order)/batch)
        for step,start in enumerate(range(0,len(order),batch)):
            ix=order[start:start+batch];raw=forward(ix,pretrain)
            if pretrain:
                y,mask=pre_targets(ix);loss=factorized_loss(raw,tensor(y),tensor(mask),tensor(weights[ix]))
            else:
                logits,gate=raw
                loss=sign_loss(logits,tensor(data["y"][ix,:,0]),tensor(data["mask"][ix]),tensor(weights[ix]),gate)
            if not bool(torch.isfinite(loss)):raise ValueError("Nonfinite V4 loss")
            group=min(accumulate,batches-(step//accumulate)*accumulate)
            (loss/group).backward()
            if (step+1)%accumulate==0 or step+1==batches:
                torch.nn.utils.clip_grad_norm_(model.parameters(),1.,error_if_nonfinite=True)
                opt.step();sch.step();opt.zero_grad(set_to_none=True)
            total+=float(loss.detach().cpu())*len(ix);seen+=len(ix)
            if progress and (step+1)%200==0:
                progress(f"V4 {variant} {width} seed={seed} {'PRE' if pretrain else 'SIGN'} {e}/{maximum} {seen}/{len(order)}")
        return total/seen
    prehistory=[];opt,sch,w=setup(pre,pre_epochs,.0005)
    for e in range(1,pre_epochs+1):
        row={"epoch":e,"loss":epoch(pre,opt,sch,w,e,pre_epochs,True),"lr":sch.get_last_lr()[0]}
        prehistory.append(row)
        if progress:progress("V4_PRETRAIN "+json.dumps(row))
    # Sign-only fine tuning, independent from V3 movement/range heads.
    opt,sch,w=setup(tr,epochs,.0003);history=[];best=None;stale=0
    for e in range(1,epochs+1):
        loss=epoch(tr,opt,sch,w,e,epochs,False)
        vp,_=predict(va);rank=validation_rank(data,va,vp)
        row={"epoch":e,"sign_loss":loss,"validation_sign_brier":rank,"lr":sch.get_last_lr()[0]}
        history.append(row)
        if progress:progress("V4_VALIDATION "+json.dumps(row))
        if best is None or rank<best["rank"]-1e-6:
            best={"rank":rank,"epoch":e,"state":{k:v.detach().cpu().clone() for k,v in model.state_dict().items()}};stale=0
        else:
            stale+=1
            if stale>=patience:break
    model.load_state_dict(best["state"]);vp,vg=predict(va);ep,eg=predict(te)
    if not np.isfinite(vp).all() or not np.isfinite(ep).all():raise ValueError("Nonfinite V4 predictions")
    diagnostics={"variant":variant,"width":width,"seed":seed,"selected_epoch":best["epoch"],"validation_raw_sign_brier":best["rank"],
                 "pretraining_history":prehistory,"fine_tuning_history":history,"parameters":sum(p.numel() for p in model.parameters()),
                 "precision":"bf16_fp32_gru" if amp else "float32","input_dimensions":list(dims),
                 "known_assets":[name for name,ok in zip(data["identities"],known) if ok],
                 "pretraining_labels_per_asset":{name:row.tolist() for name,row in zip([n for n,ok in zip(data["identities"],known) if ok],counts)},
                 "pretraining_anchors":len(pre),"sign_training_anchors":len(tr),"validation_gate_mass":vg,"score_gate_mass":eg,
                 "peak_cuda_allocated_bytes":int(torch.cuda.max_memory_allocated()) if device.type=="cuda" else None}
    checkpoint={"research_only":True,"trade_qualified":False,"variant":variant,"width":width,"seed":seed,"state_dict":best["state"],
                "input_dimensions":list(dims),"known_assets":diagnostics["known_assets"],"horizons":list(data["horizons"]),
                "asset_fields":list(data.get("asset_fields",d.ASSET_FIELDS)),"aux_names":list(data["aux_names"]),
                "aux_fit":{k:v.tolist() for k,v in part["fit"].items()},"selected_epoch":best["epoch"],"dates":part["dates"]}
    return vp,ep,diagnostics,checkpoint


def reference_predictions(data,part):
    """Fixed fair conditional-sign baselines fit on the same fold fit rows."""
    tr,va,te=(part[k] for k in ("tr","va","te"));known=part["known"];days=data["days"]
    shape=(len(te),len(data["horizons"]))
    out={name:np.full(shape,.5,float) for name in ("coin","prior","clock","linear_raw","linear")}
    def get(rows):
        x=data["grid"][data["day_index"][rows],data["minutes"][rows]][:,known]
        return np.column_stack((v3.pooled(x,True),data["aux"][data["day_index"][rows],data["minutes"][rows]]))
    stats=hist.stats(get,tr)
    with threadpool_limits(limits=2):
        for k in range(shape[1]):
            ix=tr[material(data,tr,k)];y=(data["classes"][ix,k]==2).astype(int)
            prior=float(d.m._avg(y,days[ix]));out["prior"][:,k]=prior;out["clock"][:,k]=prior
            bins=data["minutes"]//30
            for clock in np.unique(bins[te]):
                keep=bins[ix]==clock
                if keep.sum()>=100 and len(set(days[ix[keep]]))>=10:
                    out["clock"][bins[te]==clock,k]=float(d.m._avg(y[keep],days[ix[keep]]))
            model=SGDClassifier(loss="log_loss",alpha=.0001,average=True,random_state=42,learning_rate="constant",eta0=.0001)
            weights=np.zeros(len(days),np.float32);weights[ix]=d.m.day_weights(days[ix])
            rng=np.random.default_rng(42)
            for _ in range(3):
                for p in hist.batches(hist.shuffled_sessions(ix,data["day_index"],rng)):
                    model.partial_fit(hist.scaled(get,p,stats),(data["classes"][p,k]==2).astype(int),
                                      classes=np.array([0,1]),sample_weight=weights[p])
            def predict(rows):
                return np.concatenate([model.predict_proba(hist.scaled(get,p,stats))[:,1] for p in hist.batches(rows)])
            vp=predict(va);ep=predict(te);take=material(data,va,k)
            out["linear_raw"][:,k]=ep
            out["linear"][:,k],_=calibration(vp[take],data["classes"][va[take],k]==2,days[va[take]],ep)
    return out


def assessment(data,rows,p,refs):
    """Conditional sign calibration + all-scheduled confidence/abstention audit."""
    days=data["days"][rows];result={};ranks=[]
    for k,horizon in enumerate(data["horizons"]):
        mask=material(data,rows,k);target=data["classes"][rows[mask],k]==2
        if not mask.any():raise ValueError("No material assessment outcomes")
        dy=days[mask];prob=p[mask,k]
        loss=(prob-target)**2;brier=float(d.m._avg(loss,dy));ranks.append(brier)
        scheduled=data["scheduled"][rows,k];resolved=data["mask"][rows,k]
        call=np.where(p[:,k]>=CONFIDENCE,1,np.where(p[:,k]<=1-CONFIDENCE,-1,0))
        called=scheduled&(call!=0);scored=called&resolved
        ret=data["y"][rows,k,0]
        record={"conditional_sign_brier":brier,"material_rows":int(mask.sum()),"material_sessions":len(set(dy)),
                "conditional_accuracy":float(d.m._avg((prob>=.5)==target,dy)),
                "balanced_conditional_accuracy":float(np.mean([d.m._avg(((prob>=.5)==target)[target==v],dy[target==v]) for v in (False,True)])),
                "references":{name:{"brier":float(d.m._avg((r[mask,k]-target)**2,dy)),
                   "paired_candidate_minus_reference":d.m.paired_day_interval(loss-(r[mask,k]-target)**2,dy)} for name,r in refs.items()},
                "research_sign_calls":{"scheduled":int(scheduled.sum()),"calls":int(called.sum()),"scored_calls":int(scored.sum()),
                    "unresolved_calls":int((called&~resolved).sum()),"abstentions":int((scheduled&~called).sum()),
                    "up_calls":int((called&(call==1)).sum()),"down_calls":int((called&(call==-1)).sum()),
                    "sessions":len(set(days[called])),
                    "mean_signed_index_move_minus_5bps_proxy":float(d.m._avg((call*ret-COST_PROXY_BPS)[scored],days[scored])) if scored.any() else None}}
        result[str(horizon)]=record
    return {"macro_sign_brier":float(np.mean(ranks)),"horizons":result}


def choose(records):
    """Choose architecture exclusively on designated earlier walk-forward scores."""
    grouped={}
    for row in records:grouped.setdefault((row["variant"],row["width"]),[]).append(row)
    if set(grouped)!=set(CANDIDATES) or any(len(v)!=3 or {r["fold"] for r in v}!={1,2,3} for v in grouped.values()):
        raise ValueError("Incomplete fixed V4 screening matrix")
    rank=[{"variant":variant,"width":width,"mean_fold_sign_brier":float(np.mean([r["assessment"]["macro_sign_brier"] for r in rs]))}
          for (variant,width),rs in grouped.items()]
    rank.sort(key=lambda x:(x["mean_fold_sign_brier"],x["width"],CANDIDATES.index((x["variant"],x["width"]))))
    return rank[0],rank
