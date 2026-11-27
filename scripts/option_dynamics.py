"""Separate GPU premium/IV response benchmark utilities.

Only historical rolling near-month observations; no order routing, no claim
of exact contracts or tradable quotes.
"""
import json
import numpy as np

from scripts import benchmark_option_response as b
from scripts import market_dynamics_history as hist
from workstation_api import banknifty_sequence_forecast as seq


def near_month_table(archive,day):
    # Re-key by observed strike, not the moving ATM label. Mask conflicts.
    needed={minute+offset for minute in b.MINUTES for offset in (-5,0,1+b.DELAY,1+b.DELAY+b.HOLD)}
    table={};conflicts=set()
    for key,days in sorted(archive.groups.items()):
        if key[:2]!=("MONTH",1) or day not in days:continue
        raw,_=days[day];side=key[2]
        for minute in needed:
            values=raw[minute]
            if not np.isfinite(values[:5]).all() or not np.isfinite(values[5]) or values[5]<=0:continue
            strike=float(values[0]);pair=(side,strike);stamp=b.r._stamp(day,minute)
            if (stamp,pair) in conflicts:continue
            row={name:float(value) if np.isfinite(value) else None for name,value in zip(hist.OPTION_RAW,values)}
            row.update(session_ist=day,side=side,expiry_flag="MONTH",expiry_code=1)
            cell=table.setdefault(stamp,{})
            previous=cell.get(pair)
            if previous is not None:
                if any(abs(previous[k]-row[k])>.011 for k in ("open","high","low","close")) or previous["volume"]!=row["volume"]:
                    cell.pop(pair);conflicts.add((stamp,pair));continue
                for k in ("iv","oi"):
                    if previous[k]!=row[k]:previous[k]=None
            else:cell[pair]=row
    return table


def fit(train,val,evaluation,width,*,device_name="cuda",epochs=12,progress=None):
    torch,_=seq._torch()
    from torch import nn
    from torch.nn import functional as F
    if not 1<=epochs<=30:raise ValueError("OptionDynamics epochs outside 1-30")
    if device_name=="cuda" and not torch.cuda.is_available():raise ValueError("CUDA unavailable")
    device=torch.device(device_name);torch.manual_seed(42)
    if device.type=="cuda":torch.cuda.manual_seed_all(42)
    rng=np.random.default_rng(42)
    x,y,days=b._arrays(train);vx,vy,vd=b._arrays(val)
    ex=np.stack([r["x"] for r in evaluation])
    x=x[:,:width];vx=vx[:,:width];ex=ex[:,:width]
    stats=hist.stats(lambda rows:x[rows],np.arange(len(x)))
    def features(z):return hist.scaled(lambda rows:z[rows],np.arange(len(z)),stats)
    x=features(x);vx=features(vx);ex=features(ex)
    def iv_values(rows):
        raw=np.asarray([r.get("iv_target") if r.get("iv_target") is not None else np.nan for r in rows],np.float32)
        return np.where(np.isfinite(raw),raw,0.),np.isfinite(raw)
    iv,iv_ok=iv_values(train);viv,viv_ok=iv_values(val)
    iv_supported=bool(iv_ok.sum()>=100 and len(set(days[iv_ok]))>=10)
    iv_scale=max(1.,float(np.median(np.abs(iv[iv_ok])))) if iv_supported else 1.
    model=nn.Sequential(nn.Linear(x.shape[1],128),nn.LayerNorm(128),nn.GELU(),nn.Dropout(.15),
                        nn.Linear(128,128),nn.LayerNorm(128),nn.GELU(),nn.Dropout(.15),nn.Linear(128,4)).to(device)
    optimizer=torch.optim.AdamW(model.parameters(),lr=.0005,weight_decay=.01)
    weights=b.m.day_weights(days).astype(np.float32)
    def tensor(value):return torch.from_numpy(np.asarray(value,np.float32)).to(device)
    def predict(features):
        model.eval();out=[]
        with torch.no_grad():
            for part in hist.batches(np.arange(len(features)),512):
                raw=model(tensor(features[part]))
                reg=torch.cat((raw[:,:1].clamp_min(-10.),raw[:,1:2]),dim=1)*10.
                out.append(torch.column_stack((reg,torch.sigmoid(raw[:,2]),raw[:,3]*iv_scale)).cpu().numpy())
        values=np.concatenate(out)
        return values[:,:2],values[:,2],values[:,3]
    prior=float(b.m._avg((y[:,1]>0).astype(int),days))
    history=[];best=None;stale=0
    for e in range(1,epochs+1):
        model.train();order=rng.permutation(len(x));total=0.
        for part in hist.batches(order,512):
            raw=model(tensor(x[part]));target=tensor(y[part]/10.)
            w=tensor(weights[part]);label=tensor((y[part,1]>0).astype(np.float32))
            reg=F.smooth_l1_loss(raw[:,:2],target,reduction="none").mean(dim=1)
            classification=F.binary_cross_entropy_with_logits(raw[:,2],label,reduction="none")
            loss=((reg+classification)*w).mean()
            if iv_supported:
                mask=tensor(iv_ok[part].astype(np.float32))*w
                loss+=.25*(F.smooth_l1_loss(raw[:,3],tensor(iv[part]/iv_scale),reduction="none")*mask).sum()/mask.sum().clamp_min(1)
            if not bool(torch.isfinite(loss)):raise ValueError("Nonfinite OptionDynamics loss")
            optimizer.zero_grad(set_to_none=True);loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(),1.,error_if_nonfinite=True);optimizer.step()
            total+=float(loss.detach().cpu())*len(part)
        pred,p,viv_pred=predict(vx)
        # Fixed validation rank across probability and premium change.
        score=float(b.m._avg((p-(vy[:,1]>0))**2,vd)+b.m._avg(np.abs(pred[:,1]-vy[:,1]),vd)/100.)
        row={"epoch":e,"training_loss":total/len(x),"validation_rank":score};history.append(row)
        if progress:progress("OPTION_DYNAMICS_VALIDATION "+json.dumps(row))
        if best is None or score<best["score"]-1e-6:
            best={"score":score,"epoch":e,"state":{k:v.detach().cpu().clone() for k,v in model.state_dict().items()}}
            stale=0
        else:
            stale+=1
            if stale>=3:break
    model.load_state_dict(best["state"])
    _,vp,_=predict(vx);ep,p,iv_pred=predict(ex)
    calibrated,state=b.m._calibrate_probability(vp,(vy[:,1]>0).astype(int),vd,p)
    if not iv_supported:iv_pred[:]=np.nan
    return {"predictions":(ep,p,calibrated,iv_pred),
            "diagnostics":{"selected_epoch":best["epoch"],"training_history":history,"parameters":sum(p.numel() for p in model.parameters()),
                           "calibration_state":state,"iv_training_rows":int(iv_ok.sum()),"iv_validation_rows":int(viv_ok.sum()),
                           "iv_head_supported":iv_supported,"retained_input_columns":np.flatnonzero(stats["keep"]).tolist()},
            "checkpoint":{"state_dict":best["state"],"selected_epoch":best["epoch"],"width":width,
                          "input_channels":x.shape[1],"feature_fit":{k:v.tolist() for k,v in stats.items()},
                          "iv_scale":iv_scale,"iv_head_supported":iv_supported,"calibration_state":state}}
