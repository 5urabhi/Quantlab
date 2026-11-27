"""Read-only multi-asset sequence inputs for the BANKNIFTY forecasting study.

Keep one compact per-session grid, not a huge duplicate window tensor.
An instrument is a dated member or missing. Never forward-fill absent prices,
infer past membership from today's list, or use a future close to normalize.
"""
from collections import Counter
from datetime import date
import numpy as np
from . import banknifty_forecast_features as f, banknifty_candle_forecast as base

LOOKBACKS=(15,30,60,120)
CHANNELS=("open_rel","high_rel","low_rel","close_rel","log_volume",
          "relative_log_volume","price_observed","volume_observed")
THRESHOLDS=(20.,30.,50.)
SCALE_FLOOR_PCT=.01
SCALE_CEILING_PCT=.5


def build(index,stocks,membership,weights,peers,table,splits,*,progress=None):
    """Reuse v1 feature and target clocks; all lookbacks share 120-bar support.

    Select asset IDs only from dated training membership. Unknown future
    constituents do not acquire learned identities from the evaluation set.
    """
    data=base.assemble(index,stocks,membership,weights,peers,table,progress=progress)
    dates=sorted(index)
    training=set(splits[0])
    bank_ids=sorted({identity for day,mp in membership.items() if day in training for identity in mp.values()})
    identities=["INDEX:BANKNIFTY",*bank_ids,*f.PEERS]
    bank_slice=slice(1,1+len(bank_ids))
    grid=np.full((len(dates),f.MINUTES,len(identities),5),np.nan,np.float32)
    day_lookup={d:i for i,d in enumerate(dates)}
    audit={}
    for i,day in enumerate(dates):
        grid[i,:,0,:4]=index[day][:,:4] # spot has no traded volume
        active=set(membership.get(day,{}).values())
        present=0
        for j,identity in enumerate(bank_ids,1):
            if identity in active and day in stocks.get(identity,{}):
                grid[i,:,j]=stocks[identity][day]
                present+=1
        for j,identity in enumerate(f.PEERS,1+len(bank_ids)):
            if day in peers.get(identity,{}):
                grid[i,:,j,:4]=peers[identity][day][:,:4]
        audit[day]={"dated_membership":day in membership,"active_members":len(active),
                    "training_known_members":len(active&set(bank_ids)),
                    "member_sources_present":present,"verified_weights":day in weights}
    di=np.asarray([day_lookup[d] for d in data["days"]],np.int32)
    minute=data["minutes"]
    # 120 complete index observations plus 5 complete target bars are required
    # across every model/lookback. v1 already verified the 60-bar/target path.
    index_ok=np.isfinite(grid[:,:,0,:4]).all(axis=-1)
    prefix=np.column_stack((np.zeros(len(dates),np.int32),np.cumsum(index_ok,axis=1)))
    common=(minute>=max(LOOKBACKS)-1)
    j=np.flatnonzero(common)
    common[j]=(prefix[di[j],minute[j]+1]-prefix[di[j],minute[j]+1-max(LOOKBACKS)])==max(LOOKBACKS)
    # Past-only scale is expected five-minute return volatility from the most
    # recent 30 completed one-minute returns. Units are percentage points.
    scale=np.full(len(minute),np.nan)
    for i in range(len(dates)):
        close=grid[i,:,0,3].astype(float)
        ret=np.full(f.MINUTES,np.nan)
        good=np.isfinite(close[1:])&np.isfinite(close[:-1])&(close[1:]>0)&(close[:-1]>0)
        ret[1:][good]=100*np.log(close[1:][good]/close[:-1][good])
        win=np.lib.stride_tricks.sliding_window_view(ret,30)
        vol=np.full(f.MINUTES,np.nan)
        vol[29:]=np.sqrt(5*np.mean(win**2,axis=1))
        rows=np.flatnonzero(di==i)
        scale[rows]=np.clip(vol[minute[rows]],SCALE_FLOOR_PCT,SCALE_CEILING_PCT)
    common&=np.isfinite(scale)
    if not common.any():raise ValueError("No common complete 120-minute input windows")
    rows=np.flatnonzero(common)
    # Keep indicators and small contextual summaries, not the v1 flattened
    # 60-bar sequence (which would confound the raw-sequence lookback study).
    blocks=[];context_names=[];bank_columns=[];option_columns=[]
    for group in ("index","banks","peers","options"):
        names=data["names"][group]
        if group=="index":keep=[j for j,n in enumerate(names) if not n.startswith("lag_")]
        elif group=="banks":keep=[j for j,n in enumerate(names) if n.startswith("bank_")]
        else:keep=list(range(len(names)))
        offset=len(context_names)
        if group=="banks":bank_columns.extend(range(offset,offset+len(keep)))
        if group=="options":option_columns.extend(range(offset,offset+len(keep)))
        context_names.extend(group+":"+names[j] for j in keep)
        blocks.append(data["blocks"][group][rows][:,keep])
    context=np.column_stack((*blocks,scale[rows])).astype(np.float32)
    context_names.append("index:past_30m_five_minute_volatility_pct")
    selected={k:data[k][rows] for k in ("days","minutes","ref","y","actual")}
    selected["available"]={k:v[rows] for k,v in data["available"].items()}
    selected.update(grid=grid,day_index=di[rows],scale=scale[rows].astype(np.float32),
                    context=context,context_names=context_names,bank_columns=bank_columns,
                    option_columns=option_columns,identities=identities,bank_count=len(bank_ids),
                    bank_slice=bank_slice,session_audit=audit,
                    feature_coverage=base._coverage(data,{"train":np.isin(data["days"],splits[0])&common,
                        "validation":np.isin(data["days"],splits[1])&common,"evaluation":np.isin(data["days"],splits[2])&common}),
                    v1_tabular=base.scope_matrix(data,("index","banks","peers","options"))[rows])
    return selected


def raw_windows(data,rows,lookback,*,drop_banks=None,drop_options=None):
    """Return B x T x A x 8 from known bars only; missing masks are explicit.

    Price is relative to that asset's close at the completed decision minute.
    If the decision close is missing, the asset is unavailable for that window.
    No extrapolation of stale close or volume. Each 5-minute patch later receives
    the actual within-patch 1-minute order.
    """
    rows=np.asarray(rows,dtype=int)
    if lookback not in LOOKBACKS:raise ValueError("Unsupported lookback")
    minute=data["minutes"][rows]
    if np.any(minute<lookback-1):raise ValueError("Window would cross session boundary")
    clocks=minute[:,None]-np.arange(lookback-1,-1,-1)[None,:]
    raw=data["grid"][data["day_index"][rows,None],clocks].copy()
    ref=raw[:,-1,:,3]
    present=np.isfinite(raw[...,:4]).all(axis=-1)&np.isfinite(ref[:,None,:])&(ref[:,None,:]>0)
    px=np.divide(raw[...,:4],ref[:,None,:,None],out=np.ones_like(raw[...,:4]),where=present[...,None])
    px=np.clip(1000*(px-1),-30,30) # 0.1 percent units; robust numeric bound
    volume=raw[...,4]
    vok=np.isfinite(volume)&(volume>=0)&present
    lv=np.log1p(np.where(vok,volume,0))
    count=vok.sum(axis=1,keepdims=True)
    mean=np.divide(lv.sum(axis=1,keepdims=True),count,out=np.zeros_like(lv[:,:1]),where=count>0)
    result=np.concatenate((np.where(present[...,None],px,0),
                           np.where(vok,lv/10,0)[...,None],
                           np.where(vok,np.clip(lv-mean,-8,8),0)[...,None],
                           present[...,None],vok[...,None]),axis=-1).astype(np.float32)
    if drop_banks is not None and len(rows) and data["bank_count"]:
        result[np.asarray(drop_banks,dtype=bool),:,data["bank_slice"],:]=0
    return result


def context_fit(data,train):
    x=data["context"][train].astype(float)
    valid=np.isfinite(x)
    n=valid.sum(axis=0);keep=n>=max(1,int(.05*len(x)))
    clean=np.where(valid,x,0.)
    mean=np.divide(clean.sum(axis=0),n,out=np.zeros(x.shape[1]),where=n>0)
    centered=np.where(valid,clean-mean,0.)
    std=np.sqrt(np.divide((centered**2).sum(axis=0),n,out=np.ones(x.shape[1]),where=n>0))
    std=np.maximum(std,1e-6)
    return {"keep":keep,"mean":mean.astype(np.float32),"std":std.astype(np.float32)}


def context_windows(data,rows,fit,*,drop_banks=None,drop_options=None):
    x=data["context"][rows].copy()
    for mask,cols in ((drop_banks,data["bank_columns"]),(drop_options,data["option_columns"])):
        if mask is not None and cols:
            x[np.ix_(np.flatnonzero(mask),cols)]=np.nan
    x=x[:,fit["keep"]];valid=np.isfinite(x)
    x=np.where(valid,np.clip((x-fit["mean"][fit["keep"]])/fit["std"][fit["keep"]],-10,10),0.)
    return np.column_stack((x,valid.astype(np.float32))).astype(np.float32)


def event_targets(data,rows):
    change=data["actual"][rows,3]-data["ref"][rows]
    return np.column_stack((change>0,*(change>=t for t in THRESHOLDS),
                            *(change<=-t for t in THRESHOLDS))).astype(np.float32)
