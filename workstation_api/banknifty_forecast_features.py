"""Causal BANKNIFTY minute features and coherent five-minute OHLC targets.

Historical candles are retrospective observations, not packet-arrival evidence.
All feature functions receive a session array, but use only bars through the
decision minute. A gap is NaN, not a synthesized candle.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from math import isfinite
import warnings
import numpy as np
import pandas as pd
from . import historical_alpha as h, cpr_hybrid_research as r
from . import index_spot, dhan_checkpoint, banknifty_constituents as bank
from . import predictive_option_research as options
from . import banknifty_membership_fallback as membership_fallback
from . import nse_session_policy as sessions

MINUTES=375
LOOKBACK=60
HORIZON=5
PEERS=("INDEX:NIFTY50",*sorted(index_spot.RESEARCH_INDEXES))
LAGS=(1,3,5,10,15,30,60)
EMA_SPANS=(5,9,13,20,50,100,200)
EMA_PAIRS=((5,9),(9,20),(20,50),(50,200))
BANK_WINDOWS=(5,15,30,60)
OPTION_NAMES=("paired_strikes","atm_straddle_pct","same_strike_straddle_change_5m_pct",
              "put_call_oi_log_ratio","put_call_volume_log_ratio","atm_call_iv","atm_put_iv",
              "put_minus_call_iv","oi_pair_fraction","iv_pair_fraction",
              "same_strike_put_minus_call_oi_change_5m","atm_strike_distance_pct")


def dense(bars):
    out=np.full((MINUTES,5),np.nan,dtype=float)
    for minute,bar in bars.items():
        if type(minute) is int and 0<=minute<MINUTES:
            a=np.asarray(bar,dtype=float)
            if a.shape==(5,) and np.isfinite(a[:4]).all() and min(a[:4])>0 and a[1]>=max(a[0],a[2],a[3]) and a[2]<=min(a[0],a[1],a[3]):
                out[minute,:4]=a[:4]
                if isfinite(a[4]) and a[4]>=0:out[minute,4]=a[4]
    return out


def continuous_stock(day,identity,array):
    """Keep the fixed index comparison grid, masking scheduled cash closure."""
    n=sessions.cash_bank_minutes(day,identity)
    if n==MINUTES:return array
    out=array.copy()
    out[n:]=np.nan
    return out


def scheduled_bank_counts(day,minutes,members):
    counts=np.zeros(len(minutes),dtype=int)
    for identity in members:
        counts+=(minutes<sessions.cash_bank_minutes(day,identity))
    return counts


def _series(x):return pd.Series(x,dtype=float)


def _roll(x,n,method):
    return getattr(_series(x).rolling(n,min_periods=n),method)().to_numpy()


def _lag(x,n):
    return _series(x).shift(n).to_numpy()


def _ret(c,n):
    out=100*(c/_lag(c,n)-1)
    return np.where(_roll(np.isfinite(c).astype(float),n+1,"sum")==n+1,out,np.nan)


def _vol(c,n):
    return np.sqrt(_roll(np.square(np.log(c/_lag(c,1))),n,"mean"))*100


def _ema(c,n):
    # Reset at every gap. Long EMA is deliberately unavailable until its
    # within-session warmup; never carry a missing minute or future close.
    out=np.full(len(c),np.nan)
    present=np.flatnonzero(np.isfinite(c))
    for block in np.split(present,np.where(np.diff(present)!=1)[0]+1):
        if len(block):out[block]=_series(c[block]).ewm(span=n,adjust=False,min_periods=n).mean().to_numpy()
    return out


def _distance(c,x):return 100*(c-x)/c


def daily_ohlc(a):
    if a is None or a.shape!=(MINUTES,5) or not np.isfinite(a[:,:4]).all():return None
    return np.array([a[0,0],a[:,1].max(),a[:,2].min(),a[-1,3]])


def _pack(parts):
    return tuple(parts),np.column_stack(list(parts.values())).astype(np.float32)


def price_features(a,*,index=False,prior=None,earlier_days=()):
    o,hi,lo,c,v=a.T
    result={}
    for n in LAGS:result[f"return_{n}m_pct"]=_ret(c,n)
    for n in BANK_WINDOWS:
        result[f"vol_{n}m_pct"]=_vol(c,n)
        result[f"range_{n}m_pct"]=100*(_roll(hi,n,"max")-_roll(lo,n,"min"))/c
    result.update(body_pct=100*(c-o)/c,upper_wick_pct=100*(hi-np.maximum(c,o))/c,
                  lower_wick_pct=100*(np.minimum(c,o)-lo)/c,
                  open_gap_1m_pct=100*(o/_lag(c,1)-1))
    spans=EMA_SPANS if index else (5,9,20,50)
    ema={n:_ema(c,n) for n in spans}
    for n,x in ema.items():
        result[f"ema{n}_distance_pct"]=_distance(c,x)
        result[f"ema{n}_slope_5m_pct"]=100*(x/_lag(x,5)-1)
    pairs=EMA_PAIRS if index else ((5,9),(9,20))
    for left,right in pairs:
        gap=(ema[left]-ema[right])/c*100
        last=_lag(gap,1)
        cross=np.where(np.isfinite(gap)&np.isfinite(last),np.where((last<=0)&(gap>0),1.,np.where((last>=0)&(gap<0),-1.,0.)),np.nan)
        age=np.full(MINUTES,np.nan);last_cross=None
        for m,g in enumerate(gap):
            if not isfinite(g):last_cross=None;continue
            if isfinite(cross[m]) and cross[m]!=0:last_cross=m
            if last_cross is not None:age[m]=m-last_cross
        result[f"ema{left}_{right}_gap_pct"]=gap
        result[f"ema{left}_{right}_cross"]=cross
        result[f"ema{left}_{right}_cross_age"]=age
    if not index:
        result["log_volume_1m"]=np.log1p(v)
        result["log_volume_5m"]=np.log1p(_roll(v,5,"sum"))
        return _pack(result)
    # Current session running levels must not hide an earlier missing bar.
    observed=np.cumprod(np.isfinite(a[:,:4]).all(axis=1)).astype(bool)
    session_high=np.where(observed,np.maximum.accumulate(np.nan_to_num(hi,nan=-np.inf)),np.nan)
    session_low=np.where(observed,np.minimum.accumulate(np.nan_to_num(lo,nan=np.inf)),np.nan)
    result["session_open_distance_pct"]=_distance(c,o[0])
    result["session_high_distance_pct"]=_distance(c,session_high)
    result["session_low_distance_pct"]=_distance(c,session_low)
    result["minute_fraction"]=np.arange(MINUTES)/(MINUTES-1)
    for n in (5,15):
        # Most recent fully completed exchange-clock aggregate, never the
        # partially formed current 5/15-minute candle.
        ag=np.full((MINUTES,4),np.nan)
        for end in range(n-1,MINUTES,n):
            block=a[end-n+1:end+1,:4]
            if np.isfinite(block).all():
                ag[end:min(end+n,MINUTES)]=[block[0,0],block[:,1].max(),block[:,2].min(),block[-1,3]]
        for j,key in enumerate(("open","high","low","close")):
            result[f"completed_{n}m_{key}_distance_pct"]=_distance(c,ag[:,j])
    tr=np.maximum(hi-lo,np.maximum(np.abs(hi-_lag(c,1)),np.abs(lo-_lag(c,1))))
    for n in (5,14,30):result[f"atr{n}_pct"]=100*_roll(tr,n,"mean")/c
    change=c-_lag(c,1)
    for n in (7,14):
        gain=_roll(np.maximum(change,0),n,"mean");loss=_roll(np.maximum(-change,0),n,"mean")
        result[f"rsi{n}"]=np.divide(100*gain,gain+loss,out=np.full(MINUTES,np.nan),where=(gain+loss)>0)
    mid=_roll(c,20,"mean");sd=_roll(c,20,"std")
    result["bollinger_width_pct"]=400*sd/c
    result["bollinger_z"]=np.divide(c-mid,sd,out=np.full(MINUTES,np.nan),where=sd>0)
    macd=_ema(c,12)-_ema(c,26)
    signal=_ema(macd,9)
    result["macd_pct"]=100*macd/c;result["macd_hist_pct"]=100*(macd-signal)/c
    # Complete previous-session OHLC and CPR. If it is missing, do not
    # substitute an older day. Wider daily history uses only earlier dates.
    for j,key in enumerate(("open","high","low","close")):
        result["prev_"+key+"_distance_pct"]=_distance(c,prior[j] if prior is not None else np.nan)
    levels={}
    if prior is not None:
        _,ph,pl,pc=prior;p=(ph+pl+pc)/3;bc=(ph+pl)/2;tc=2*p-bc
        levels={"pivot":p,"cpr_bottom":min(bc,tc),"cpr_top":max(bc,tc),
                "r1":2*p-pl,"s1":2*p-ph,"r2":p+ph-pl,"s2":p-ph+pl,
                "r3":ph+2*(p-pl),"s3":pl-2*(ph-p)}
        result["opening_gap_pct"]=np.full(MINUTES,100*(o[0]/pc-1))
        result["cpr_width_pct"]=100*abs(tc-bc)/c
    else:
        result["opening_gap_pct"]=np.full(MINUTES,np.nan);result["cpr_width_pct"]=np.full(MINUTES,np.nan)
    for key in ("pivot","cpr_bottom","cpr_top","r1","s1","r2","s2","r3","s3"):
        result[key+"_distance_pct"]=_distance(c,levels.get(key,np.nan))
    for i in range(1,6):
        d=earlier_days[-i] if len(earlier_days)>=i else None
        for j,key in enumerate(("open","high","low","close")):
            result[f"day_{i}_{key}_distance_pct"]=_distance(c,d[j] if d is not None else np.nan)
    return _pack(result)


def anchors(a):
    """Each row is the immediately NEXT five minutes, not a partial candle.
    Encode O/C relative to known close and nonnegative upper/lower excursions.
    """
    idx=[];targets=[];real=[]
    for m in range(LOOKBACK-1,MINUTES-HORIZON):
        past=a[m-LOOKBACK+1:m+1,:4];future=a[m+1:m+1+HORIZON,:4]
        if not np.isfinite(past).all() or not np.isfinite(future).all():continue
        ref=a[m,3];op,cl=future[0,0],future[-1,3]
        high,low=future[:,1].max(),future[:,2].min()
        y=100*np.array([op-ref,cl-ref,high-max(op,cl),min(op,cl)-low])/ref
        idx.append(m);targets.append(y);real.append((op,high,low,cl))
    return np.asarray(idx,dtype=int),np.asarray(targets,dtype=float).reshape(-1,4),np.asarray(real,dtype=float).reshape(-1,4)


def sequence(a,minutes):
    # 60 completed one-minute OHLC candles, relative to the decision close.
    seq=np.stack([a[m-LOOKBACK+1:m+1,:4] for m in minutes]) if len(minutes) else np.empty((0,LOOKBACK,4))
    return (100*(seq/a[minutes,3,None,None]-1)).astype(np.float32)


def load_membership(dates,start,stop,progress=None):
    """Resolve dated BANKNIFTY constituents in bounded source slices.
    Multiple overlapping manifests must agree on active identity mappings.
    """
    candidates=h.batches();mappings=defaultdict(list);audit={};rejected={}
    for item in candidates:
        bid=item["id"]
        try:
            raw=h.dw._load_batch(bid)
            left=max(start,date.fromisoformat(raw["from_date"]))
            right=min(stop,date.fromisoformat(raw["to_date"]),date.fromisoformat(raw["historical_index"]["covered_through"])+timedelta(days=1))
            if left>=right:continue
            staged={}
            cursor=left
            while cursor<right:
                end=min(right,cursor+timedelta(days=180))
                _,lo,hi,intervals,resolved=h._batch(bid,study_start=cursor,study_stop=end)
                for day in dates:
                    if lo.isoformat()<=day<hi.isoformat():
                        members=h._member_set(intervals,day)
                        if members and all(s in resolved for s in members):
                            staged[day]={s:resolved[s] for s in members}
                cursor=end
            for day,values in staged.items():mappings[day].append(values)
            audit[bid]={"membership_sha256":raw["historical_index"]["intervals_sha256"],"covered_dates":len(staged)}
        except (ValueError,OSError,TypeError,KeyError,OverflowError) as exc:
            rejected[bid]=str(exc)[:180]
    membership={};conflicts=[]
    for day,versions in mappings.items():
        if all(x==versions[0] for x in versions):membership[day]=versions[0]
        else:conflicts.append(day)
    membership,fallback_audit=membership_fallback.supplement(dates,membership,conflicts)
    ids=sorted({identity for values in membership.values() for identity in values.values()})
    if len(ids)>h.MAX_INSTRUMENTS:raise ValueError("Constituent history exceeds bounded universe")
    stocks={};hashes={};failures={};budget=[h.MAX_TOTAL]
    for i,identity in enumerate(ids):
        if progress:progress(f"Verifying historical bank constituent {i+1}/{len(ids)} {identity}")
        try:
            sig=h.pq._source_signature(identity)
            if not sig:raise ValueError("Missing original one-minute cache")
            path,sidecar=h.pq._raw(identity)
            receipt=dhan_checkpoint._read_receipt(sidecar,identity=identity,interval=1)
            if sig["source_sha256"]!=receipt["sha256"]:raise ValueError("Source changed during verification")
            original=h._read_file(path,receipt["sha256"],start,stop,budget,receipt["rows"])
            stocks[identity]={d:continuous_stock(d,identity,dense(bars)) for d,bars in original.items()}
            hashes[identity]=receipt["sha256"]
        except (ValueError,OSError,TypeError,KeyError,OverflowError) as exc:
            failures[identity]=str(exc)[:180]
    weights={};weight_hashes={}
    for day,values in membership.items():
        asof=datetime.combine(date.fromisoformat(day),datetime.min.time(),h.IST)
        snap=bank._weights_for(date.fromisoformat(day),asof,list(values))
        if snap:
            weights[day]={values[s]:w for s,w in snap["weights_pct"].items()}
            weight_hashes[day]=snap["source_csv_sha256"]
    return stocks,membership,weights,{"batches":audit,"rejected_batches":rejected,"conflicting_membership_dates":conflicts,
           "membership_fallback":fallback_audit,
           "membership_days":len(membership),"identities":ids,"source_hashes":hashes,"failures":failures,
           "weighted_days":len(weights),"weight_hashes":weight_hashes,
           "observed_sessions_by_identity":{k:len(v) for k,v in stocks.items()}}


def banks_at(day,minutes,ids,stocks,members,weights,prior_days,index_close):
    empty=dense({})
    names0,_=price_features(empty)
    fields=names0+("relative_volume_5m","member","observed","scheduled_open")
    out=[];names=[];returns=[];observed_ids=[]
    for identity in ids:
        member=identity in members
        array=stocks.get(identity,{}).get(day) if member else None
        if array is None:array=empty
        else:array=continuous_stock(day,identity,array)
        scheduled=(minutes<sessions.cash_bank_minutes(day,identity))&member
        _,values=price_features(array)
        previous=stocks.get(identity,{})
        refs=[_roll(continuous_stock(d,identity,previous[d])[:,4],5,"sum") for d in prior_days[-20:] if d in previous] if member else []
        rel=np.full(MINUTES,np.nan)
        if len(refs)>=5:
            mat=np.asarray(refs);support=np.isfinite(mat).sum(axis=0)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore",RuntimeWarning);base=np.nanmedian(mat,axis=0)
            rel=np.divide(_roll(array[:,4],5,"sum"),base,out=rel,where=(base>0)&(support>=5))
        obs=np.isfinite(array[minutes,:4]).all(axis=1)
        out.append(np.column_stack((values[minutes],rel[minutes],np.full(len(minutes),float(member)),obs.astype(float),scheduled.astype(float))))
        names.extend(identity+"_"+v for v in fields)
        if member:returns.append(_ret(array[:,3],5)[minutes]);observed_ids.append(identity)
    agg=np.full((len(minutes),8),np.nan)
    scheduled=scheduled_bank_counts(day,minutes,members)
    agg[:,0]=len(members);agg[:,1]=0;agg[:,7]=scheduled
    if returns:
        mat=np.column_stack(returns);count=np.isfinite(mat).sum(axis=1)
        agg[:,1]=np.divide(count,scheduled,out=np.zeros(len(minutes)),where=scheduled>0)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore",RuntimeWarning)
            agg[:,2]=np.where(count>=3,np.nanmean(mat,axis=1),np.nan)
            agg[:,3]=np.where(count>=3,np.nanstd(mat,axis=1),np.nan)
        agg[:,4]=np.divide((mat>0).sum(axis=1),count,out=np.full(len(minutes),np.nan),where=count>=3)
        if weights and set(observed_ids)==set(weights):
            w=np.asarray([weights[k] for k in observed_ids]);w/=w.sum()
            agg[:,5]=np.where(scheduled==len(members),mat@w,np.nan)
            agg[:,6]=agg[:,5]-_ret(index_close,5)[minutes]
    names.extend(("bank_member_count","bank_observed_fraction","bank_mean_5m_pct","bank_dispersion_5m_pct","bank_up_fraction","bank_weighted_5m_pct","bank_weighted_minus_index_5m_pct","bank_scheduled_open_count"))
    out.append(agg)
    return tuple(names),np.column_stack(out).astype(np.float32),agg[:,1]>=.8


def peers_at(day,minutes,peers,index_close):
    names=[];out=[];observed=[]
    for identity in PEERS:
        a=peers.get(identity,{}).get(day)
        c=a[:,3] if a is not None else np.full(MINUTES,np.nan)
        moves=[_ret(c,n)[minutes] for n in (1,5,15,30,60)]
        fields=("return_1m_pct","return_5m_pct","return_15m_pct","return_30m_pct","return_60m_pct","vol_15m_pct","relative_5m_pct","observed")
        vals=[*moves,_vol(c,15)[minutes],moves[1]-_ret(index_close,5)[minutes],np.isfinite(c[minutes]).astype(float)]
        if identity=="INDEX:INDIAVIX":fields+=("level",);vals.append(c[minutes])
        names.extend(identity+"_"+v for v in fields);out.extend(vals)
        observed.append(np.isfinite(moves[1]))
    return tuple(names),np.column_stack(out).astype(np.float32),np.mean(np.column_stack(observed),axis=1)>=.8


def option_at(table,day,m,spot):
    result=np.full(len(OPTION_NAMES),np.nan)
    if not table:return result
    now=table.get(r._stamp(day,m),{})
    old=table.get(r._stamp(day,m-5),{})
    def valid(q):
        return q is not None and q.get("session_ist")==day and q.get("expiry_flag")=="MONTH" and q.get("expiry_code")==1 and q.get("volume") is not None and q["volume"]>0 and q.get("close",0)>0
    strikes=sorted(k for s,k in now if s=="CALL" and abs(k/spot-1)<=.02 and valid(now.get(("CALL",k))) and valid(now.get(("PUT",k))))
    result[0]=len(strikes)
    if not strikes:return result
    k=min(strikes,key=lambda k:(abs(k-spot),k))
    c,p=now["CALL",k],now["PUT",k];oc,op=old.get(("CALL",k)),old.get(("PUT",k))
    result[1]=100*(c["close"]+p["close"])/spot
    if valid(oc) and valid(op):result[2]=100*((c["close"]+p["close"])/(oc["close"]+op["close"])-1)
    def usable(q,key):return q.get(key) is not None and isfinite(q[key]) and q[key]>=0
    oi=[k for k in strikes if all(usable(now[s,k],"oi") for s in ("CALL","PUT"))]
    iv=[k for k in strikes if all(usable(now[s,k],"iv") for s in ("CALL","PUT"))]
    result[8]=len(oi)/len(strikes);result[9]=len(iv)/len(strikes)
    if oi:
        result[3]=np.log((1+sum(now["PUT",k]["oi"] for k in oi))/(1+sum(now["CALL",k]["oi"] for k in oi)))
    result[4]=np.log((1+sum(now["PUT",k]["volume"] for k in strikes))/(1+sum(now["CALL",k]["volume"] for k in strikes)))
    if k in iv:
        result[5]=c["iv"];result[6]=p["iv"];result[7]=p["iv"]-c["iv"]
    if valid(oc) and valid(op) and all(usable(q,"oi") for q in (c,p,oc,op)) and min(oc["oi"],op["oi"])>0:
        result[10]=(p["oi"]/op["oi"]-1)-(c["oi"]/oc["oi"]-1)
    result[11]=100*(k/spot-1)
    return result
