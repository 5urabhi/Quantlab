"""Fixed full-history V3 fitting, using V2 source grid and scoring protocol."""
import json
import numpy as np

from scripts import benchmark_market_dynamics as d
from scripts import market_dynamics_history as hist
from workstation_api import nse_session_policy as sessions


def pooled(x,joint):
    """Token = target features + cross-sectional observed mean/std/coverage."""
    index=x[...,0,:]
    if not joint:return index
    peers=x[...,1:,:]
    valid=np.isfinite(peers);count=valid.sum(axis=-2)
    clean=np.where(valid,peers,0.)
    mean=np.divide(clean.sum(axis=-2),count,out=np.full(count.shape,np.nan,dtype=np.float32),where=count>0)
    sd=np.sqrt(np.divide(np.where(valid,(clean-mean[...,None,:])**2,0.).sum(axis=-2),
                         count,out=np.full(count.shape,np.nan,dtype=np.float32),where=count>0))
    return np.concatenate((index,mean,sd,count/max(1,peers.shape[-2])),axis=-1).astype(np.float32)


def memory_grid(data,joint,progress=None,*,known_assets=None):
    """Every completed 15m block and complete observed day, never future.

    Daily snapshots represent last completed source session, including its
    running day OHLC/CPR and current technical state; no session is fabricated.
    """
    grid=data["grid"];dates=data["dates"];assets=len(data["identities"])
    fields=data.get('asset_fields',d.ASSET_FIELDS)
    channels=len(fields)*(4 if joint else 1)
    known=np.ones(assets,bool) if known_assets is None else np.asarray(known_assets,bool)
    if known.shape!=(assets,) or not known[0]:raise ValueError('Invalid fold-known assets')
    session=np.full((len(dates),25,channels),np.nan,np.float32)
    daily=np.full((len(dates),channels),np.nan,np.float32)
    complete=d.ASSET_FIELDS.index("session_prefix_complete")
    block=d.ASSET_FIELDS.index("completed_15m_close_distance_pct")
    eq=set(data["equity_identities"])
    for i,day in enumerate(dates):
        if progress and (i%200==0 or i+1==len(dates)):progress(f"V3 memory {'joint' if joint else 'index'} {i+1}/{len(dates)}")
        x=np.array(grid[i,14::15],copy=True)
        x[~(np.isfinite(x[:,:,block])&(x[:,:,0]>0))]=np.nan
        session[i]=pooled(x[:,known],joint)
        end=np.array([(sessions.cash_bank_minutes(day,identity) if identity in eq else d.MINUTES)-1
                      for identity in data["identities"]],dtype=int)
        y=np.array(grid[i,end,np.arange(assets)],copy=True)
        y[~((y[:,complete]==1)&(y[:,0]>0))]=np.nan
        daily[i]=pooled(y[None,known],joint)[0]
    return session,daily


def pack(x,allowed,*,joint,asset_features=len(d.ASSET_FIELDS)):
    # Token validity requires at least one actual observed instrument, not a
    # numeric zero coverage marker or padded token.
    observed=x[...,0]>0
    if joint:observed|=x[...,asset_features]>0
    valid=observed&allowed
    ok=np.isfinite(x)&valid[...,None]
    return np.concatenate((np.where(ok,np.clip(x,-10,10),0.),ok.astype(np.float32)),axis=-1).astype(np.float32),valid


def inputs(data,rows,joint,fit,memory,*,known_assets=None):
    x,aux=d.windows(data,rows,joint,fit)
    if joint and known_assets is not None:x=x[:,:,np.asarray(known_assets,bool)]
    features=len(data.get('asset_fields',d.ASSET_FIELDS))
    days=data["day_index"][rows];minutes=data["minutes"][rows]
    session,daily=memory
    s,sv=pack(session[days],np.arange(25)[None,:]<(minutes[:,None]+1)//15,joint=joint,asset_features=features)
    prior=days[:,None]-np.arange(60,0,-1)[None,:]
    p,pv=pack(daily[np.maximum(prior,0)],prior>=0,joint=joint,asset_features=features)
    return x,aux,s,p,sv,pv


def pretraining_targets(data,rows,joint):
    day=data["day_index"][rows];minute=data["minutes"][rows]
    if np.any((minute+1)%5):raise ValueError("Pretraining requires completed five-minute anchors")
    y=data["pretrain_targets"][day,minute//5]
    if not joint:y=y[:,:1]
    mask=np.isfinite(y).all(axis=-1)
    return np.where(mask[...,None],y/10.,0.).astype(np.float32),mask.astype(np.float32)


def validation_rank(data,rows,p):
    # Model selection explicitly values material direction, not just quiet
    # market recognition. Every horizon contributes equally.
    values=[]
    for k in range(len(d.HORIZONS)):
        mask=data["mask"][rows,k];ix=rows[mask];y=data["classes"][ix,k]
        prob=p[mask,k];days=data["days"][ix];material=y!=1
        move=float(d.m._avg((1-prob[:,1]-material)**2,days))
        if not material.any():raise ValueError("Validation lacks material moves")
        sign=prob[material,2]/np.maximum(prob[material,0]+prob[material,2],1e-12)
        conditional=float(d.m._avg((sign-(y[material]==2))**2,days[material]))
        values.append((move+conditional)/2)
    return float(np.mean(values))


def fit(data,tr,va,te,aux_fit,*,joint,epochs,batch,device,progress,pretrain_epochs=2,accumulate=4,width=128):
    torch,_=d.seq._torch()
    from workstation_api.market_dynamics_v3 import MarketDynamicsV3,distribution,factorized_loss
    torch.manual_seed(d.SEED)
    if device.type=="cuda":torch.cuda.manual_seed_all(d.SEED)
    # Avoid mixed-precision attention inference fastpath dtype mismatch.
    if hasattr(torch.backends,"mha"):torch.backends.mha.set_fastpath_enabled(False)
    amp=device.type=="cuda" and torch.cuda.is_bf16_supported()
    if device.type=="cuda":torch.set_float32_matmul_precision("high")
    rng=np.random.default_rng(d.SEED)
    memory=memory_grid(data,joint,progress)
    example=inputs(data,tr[:1],joint,aux_fit,memory)
    model=MarketDynamicsV3(example[0].shape[2],example[0].shape[3],example[1].shape[2],
                          example[2].shape[2],len(d.HORIZONS),width).to(device)
    mode="joint" if joint else "index_only"
    weights=np.zeros(len(data["days"]),np.float32)
    weights[tr]=d.m.day_weights(data["days"][tr])
    def tensor(x):return torch.from_numpy(x).to(device)
    def forward(rows,pre=False):
        args=[tensor(x) for x in inputs(data,rows,joint,aux_fit,memory)]
        with torch.autocast(device_type=device.type,dtype=torch.bfloat16,enabled=amp):
            return model(*args,pretrain=pre)
    def predict(rows):
        probs=[];reg=[];model.eval()
        with torch.no_grad():
            for start in range(0,len(rows),batch):
                raw=forward(rows[start:start+batch]);lp,y=distribution(raw)
                probs.append(lp.exp().cpu().numpy());reg.append(y.cpu().numpy()*10)
        return np.concatenate(probs),np.concatenate(reg)
    def epoch(rows,optimizer,number,total_epochs,pre=False):
        order=hist.shuffled_sessions(rows,data["day_index"],rng)
        model.train();losses=0.;seen=0;optimizer.zero_grad(set_to_none=True)
        num_batches=(len(order)+batch-1)//batch
        for step,start in enumerate(range(0,len(order),batch)):
            part=order[start:start+batch]
            if pre:y,mask=pretraining_targets(data,part,joint)
            else:y=data["y"][part]/10.;mask=data["mask"][part].astype(np.float32)
            raw=forward(part,pre)
            loss=factorized_loss(raw,tensor(y),tensor(mask),tensor(weights[part]))
            if not bool(torch.isfinite(loss)):raise ValueError("Nonfinite V3 training loss")
            group_size=min(accumulate,num_batches-(step//accumulate)*accumulate)
            (loss/group_size).backward()
            if (step+1)%accumulate==0 or step+1==num_batches:
                torch.nn.utils.clip_grad_norm_(model.parameters(),1.,error_if_nonfinite=True)
                optimizer.step();optimizer.zero_grad(set_to_none=True)
            losses+=float(loss.detach().cpu())*len(part);seen+=len(part)
            if progress and (step+1)%200==0:progress(f"V3 {'PRETRAIN' if pre else 'TRAIN'} {mode} {number}/{total_epochs} {seen}/{len(order)}")
        return losses/seen
    pre=tr[(data["minutes"][tr]+1)%5==0]
    if not len(pre):raise ValueError("No pretraining anchors")
    optimizer=torch.optim.AdamW(model.parameters(),lr=.0005,weight_decay=.01)
    used=np.zeros((example[0].shape[2],2),np.int64)
    for part in hist.batches(pre):
        _,mask=pretraining_targets(data,part,joint);used+=mask.sum(axis=0,dtype=np.int64)
    prehistory=[]
    for e in range(1,pretrain_epochs+1):
        loss=epoch(pre,optimizer,e,pretrain_epochs,True)
        record={"epoch":e,"loss":loss,"decision_anchors":len(pre)}
        prehistory.append(record)
        if progress:progress("V3_PRETRAIN "+mode+" "+json.dumps(record))
    # No evaluation-driven architecture search; fresh optimizer for fine tune.
    optimizer=torch.optim.AdamW(model.parameters(),lr=.0003,weight_decay=.01)
    best=None;history=[];stale=0
    for e in range(1,epochs+1):
        loss=epoch(tr,optimizer,e,epochs)
        vp,_=predict(va);rank=validation_rank(data,va,vp)
        record={"epoch":e,"training_loss":loss,"validation_movement_and_sign_brier":rank,
                "validation_multiclass_brier":d.val_rank(data,va,vp)}
        history.append(record)
        if progress:progress("V3_VALIDATION "+mode+" "+json.dumps(record))
        if best is None or rank<best["rank"]-1e-6:
            best={"rank":rank,"epoch":e,"state":{k:v.detach().cpu().clone() for k,v in model.state_dict().items()}}
            stale=0
        else:
            stale+=1
            if stale>=3:break
    model.load_state_dict(best["state"])
    vp,vr=predict(va);ep,er=predict(te)
    return {"validation":(vp,vr),"evaluation":(ep,er),"state":best["state"],"selected_epoch":best["epoch"],
            "history":history,"pretraining":prehistory,"used_pretraining_labels":{identity:row.tolist() for identity,row in zip(data["identities"],used)},"precision":"bf16_projections_fp32_gru" if amp else "float32",
            "parameters":sum(p.numel() for p in model.parameters()),
            "input_dimensions":[example[0].shape[2],example[0].shape[3],example[1].shape[2]],
            "memory_dimensions":example[2].shape[2]}
