"""Unified causal multi-asset market dynamics research (not a trading engine).

Uses existing receipt-backed data and one fixed cross-asset/temporal neural
architecture. Fit on earlier sessions; assess all eligible completed minutes.
"""
import argparse
from collections import Counter
from datetime import date,datetime,timedelta
import csv
import json
import os
import tempfile
from pathlib import Path
import sqlite3
import uuid

import numpy as np
from threadpoolctl import threadpool_limits

from scripts import benchmark_direction_gate as direction
from scripts import benchmark_ema_first_passage as passage
from scripts import benchmark_ema_levels as levels
from scripts import market_dynamics_history as histdata
from scripts.run_banknifty_candle_forecast import write_atomic
from workstation_api import banknifty_candle_forecast as m, historical_alpha as h
from workstation_api import banknifty_sequence_forecast as seq
from workstation_api import cpr_hybrid_research as r, predictive_option_research as opt
from workstation_api import nse_session_policy as sessions, service

VERSION="market_dynamics_v1_1"
FULL_VERSION="market_dynamics_full_history_v2"
HORIZONS=(1,5,10,15,30,60)
LOOKBACK=30
MIN_HISTORY=15
DELAY=1
DEADBAND_BPS=5.
CONFIDENCE=.60
SEED=42
MINUTES=375
EMA=(9,21,50,200)
LAGS=(1,5,15,30,60)
VOL=(5,15,30)
DAILY=(5,20,60)
ASSET_FIELDS=("observed","open_pct","high_pct","low_pct","close_pct","log_volume",
              "relative_log_volume_20m","prior_complete","clock_fraction",
              "log_open","log_high","log_low","log_close","session_prefix_complete","dated_bank_member","weekday_scaled","prior_observed_gap_days"
              )+tuple(f"return_{n}m_pct" for n in LAGS)+tuple(f"vol_{n}m_pct" for n in VOL)+tuple(
              f"ema{n}_distance_pct" for n in EMA)+("ema9_minus_21_pct","ema_cross","ema9_slope_5m_pct","ema21_slope_5m_pct",
              "ema_last_cross","ema_cross_age_scaled",
              "opening_gap_pct","cpr_width_pct")+tuple(name+"_distance_pct" for name in levels.LEVEL_NAMES)+tuple(
              f"prior_{n}d_{kind}" for n in DAILY for kind in ("return_scaled","rms_pct"))+tuple(
              "last_observed_"+key+"_distance_pct" for key in ("open","high","low","close"))+tuple(
              f"completed_{n}m_{key}_distance_pct" for n in (5,15,30,60) for key in ("open","high","low","close"))
BANK_AUX=("dated_membership","scheduled_count","observed_fraction","mean_5m_pct",
          "dispersion_5m_pct","up_fraction","verified_weighted_5m_pct")
AVAILABILITY=("banks","peers","options","global_daily","overnight")


def prefix(a,n=MINUTES):
    if a is None:return 0
    if a.shape!=(MINUTES,5):raise ValueError("Expected regular 375-minute source grid")
    ok=np.isfinite(a[:n,:4]).all(axis=1)&(a[:n,:4]>0).all(axis=1)
    bad=np.flatnonzero(~ok)
    return int(bad[0]) if len(bad) else n


def daily_close(a,n):
    return float(a[n-1,3]) if prefix(a,n)==n else np.nan


def rolling(x,n,kind):
    out=np.full(len(x),np.nan)
    if len(x)>=n:
        win=np.lib.stride_tricks.sliding_window_view(x,n)
        out[n-1:]=np.mean(win,axis=1) if kind=="mean" else np.sqrt(np.mean(win**2,axis=1))
    return out


def asset_features(a,previous,history,*,n=MINUTES,q=MINUTES,seed_prior=True):
    """All channels describe completed bars and earlier observed sessions.

    Use prior weekday only when its scheduled prefix is complete. If
    unavailable, explicitly mark prior levels missing and seed EMA locally.
    Missing current bars terminate the supported prefix (no gap filling).
    """
    out=np.full((MINUTES,len(ASSET_FIELDS)),np.nan,dtype=np.float32)
    count=prefix(a,n)
    if not count:return out
    a=a[:count];o,hi,lo,c,v=a.T
    prior=previous[:q] if prefix(previous,q)==q else None
    anchor=np.r_[prior[-1,3] if prior is not None and seed_prior else o[0],c[:-1]]
    values={"observed":np.ones(count),"prior_complete":np.full(count,float(prior is not None)),
            "clock_fraction":(np.arange(count)+1)/MINUTES,
            "session_prefix_complete":np.ones(count),"dated_bank_member":np.full(count,np.nan),
            "weekday_scaled":np.full(count,np.nan),"prior_observed_gap_days":np.full(count,np.nan)}
    for name,x in zip(("open","high","low","close"),(o,hi,lo,c)):
        values[name+"_pct"]=100*(x/anchor-1)
        values["log_"+name]=np.log(x)/10
    logv=np.log1p(np.where(np.isfinite(v)&(v>=0),v,np.nan))
    values["log_volume"]=logv/10
    values["relative_log_volume_20m"]=logv-np.r_[np.nan,rolling(logv,20,"mean")[:-1]]
    for lag in LAGS:
        value=np.full(count,np.nan)
        if count>lag:value[lag:]=100*(c[lag:]/c[:-lag]-1)
        values[f"return_{lag}m_pct"]=value
    ret=np.r_[np.nan,100*np.diff(np.log(c))]
    for k in VOL:values[f"vol_{k}m_pct"]=rolling(ret,k,"rms")
    seeds=np.array([h._ema(prior[:,3],k) if prior is not None and seed_prior else c[0] for k in EMA])
    ema=seeds.copy();alpha=2/(np.asarray(EMA)+1)
    em=np.empty((count,len(EMA)));cross=np.zeros(count);sign=int(np.sign(ema[0]-ema[1]))
    for j,price in enumerate(c):
        ema+=(price-ema)*alpha;em[j]=ema
        current=int(np.sign(ema[0]-ema[1]))
        if current and sign and current!=sign:cross[j]=current
        if current:sign=current
    for k,j in zip(EMA,range(len(EMA))):values[f"ema{k}_distance_pct"]=100*(c-em[:,j])/c
    values["ema9_minus_21_pct"]=100*(em[:,0]-em[:,1])/c
    values["ema_cross"]=cross
    last=0;when=-1;lasts=[];ages=[]
    for j,event in enumerate(cross):
        if event:last=int(event);when=j
        lasts.append(last);ages.append((j-when)/60 if when>=0 else np.nan)
    values["ema_last_cross"]=np.asarray(lasts);values["ema_cross_age_scaled"]=np.asarray(ages)
    for k,j in ((9,0),(21,1)):
        slope=np.full(count,np.nan)
        if count>5:slope[5:]=100*(em[5:,j]/em[:-5,j]-1)
        values[f"ema{k}_slope_5m_pct"]=slope
    frozen={}
    if prior is not None:
        po,ph,pl,pc=prior[0,0],prior[:,1].max(),prior[:,2].min(),prior[-1,3]
        pivot=(ph+pl+pc)/3;bc=(ph+pl)/2;bottom,top=sorted((bc,2*pivot-bc))
        frozen.update(previous_open=po,previous_high=ph,previous_low=pl,previous_close=pc,
                      cpr_bottom=bottom,cpr_pivot=pivot,cpr_top=top,r1=2*pivot-pl,
                      r2=pivot+ph-pl,s1=2*pivot-ph,s2=pivot-ph+pl)
        values["opening_gap_pct"]=np.full(count,100*(o[0]/pc-1))
        values["cpr_width_pct"]=100*(top-bottom)/c
    else:
        values["opening_gap_pct"]=np.full(count,np.nan);values["cpr_width_pct"]=np.full(count,np.nan)
    th=np.maximum.accumulate(hi);tl=np.minimum.accumulate(lo)
    dp=(th+tl+c)/3;mid=(th+tl)/2
    frozen.update(today_open=o[0],today_running_high=th,today_running_low=tl,
                  today_developing_cpr_bottom=np.minimum(mid,2*dp-mid),
                  today_developing_pivot=dp,today_developing_cpr_top=np.maximum(mid,2*dp-mid))
    if count>=15:
        for name,value in (("opening_15m_high",hi[:15].max()),("opening_15m_low",lo[:15].min()),("opening_15m_close",c[14])):
            z=np.full(count,np.nan);z[14:]=value;frozen[name]=z
    for name in levels.LEVEL_NAMES:values[name+"_distance_pct"]=100*(c-frozen.get(name,np.nan))/c
    for k in DAILY:
        past=np.asarray(history[-(k+1):],float)
        supported=len(past)==k+1 and np.isfinite(past).all() and np.all(past>0)
        values[f"prior_{k}d_return_scaled"]=np.full(count,10*(past[-1]/past[0]-1) if supported else np.nan)
        values[f"prior_{k}d_rms_pct"]=np.full(count,100*np.sqrt(np.mean(np.diff(np.log(past))**2)) if supported else np.nan)
    out[:count]=np.column_stack([np.broadcast_to(values.get(name,np.nan),(count,)) for name in ASSET_FIELDS]).astype(np.float32)
    return out


def full_asset_features(a,previous,earlier,*,n=MINUTES,q=MINUTES):
    """Use all observed contiguous runs; explicitly reset after a gap.

    Prior-day levels remain known independently of a current gap. Do not
    present post-gap observed extrema as complete current-session OHLC.
    """
    out=np.full((MINUTES,len(ASSET_FIELDS)),np.nan,np.float32)
    if a is None:return out
    valid=np.isfinite(a[:n,:4]).all(axis=1)&(a[:n,:4]>0).all(axis=1)
    indices=np.flatnonzero(valid)
    if not len(indices):return out
    runs=np.split(indices,np.flatnonzero(np.diff(indices)>1)+1)
    col={name:i for i,name in enumerate(ASSET_FIELDS)}
    for run in runs:
        start=int(run[0]);length=len(run)
        padded=np.full((MINUTES,5),np.nan)
        padded[:length]=a[run]
        values=asset_features(padded,previous,earlier,n=length,q=q,seed_prior=start==0)[:length]
        values[:,col["clock_fraction"]]=(run+1)/MINUTES
        if start:
            values[:,col["session_prefix_complete"]]=0
            for name in ("today_running_high","today_running_low","today_developing_cpr_bottom",
                         "today_developing_pivot","today_developing_cpr_top",
                         "opening_15m_high","opening_15m_low","opening_15m_close","today_open"):
                values[:,col[name+"_distance_pct"]]=np.nan
            values[:,col["opening_gap_pct"]]=np.nan
            if valid[0]:
                values[:,col["today_open_distance_pct"]]=100*(a[run,3]-a[0,0])/a[run,3]
                if prefix(previous,q)==q:
                    values[:,col["opening_gap_pct"]]=100*(a[0,0]/previous[q-1,3]-1)
            if len(valid)>=15 and valid[:15].all():
                known=run>=14
                for name,price in (("opening_15m_high",a[:15,1].max()),("opening_15m_low",a[:15,2].min()),
                                   ("opening_15m_close",a[14,3])):
                    values[known,col[name+"_distance_pct"]]=100*(a[run[known],3]-price)/a[run[known],3]
        out[run]=values
    return out


def add_clock_context(features,a,day,last_complete,n):
    """Exact completed exchange-clock aggregates and separately aged last
    observed complete-session levels. No incomplete block or future OHLC.
    """
    if a is None:return
    col={name:i for i,name in enumerate(ASSET_FIELDS)}
    present=features[:,0]>0
    features[present,col["weekday_scaled"]]=date.fromisoformat(day).weekday()/4
    if last_complete is not None:
        previous_day,ohlc=last_complete
        features[present,col["prior_observed_gap_days"]]=(date.fromisoformat(day)-date.fromisoformat(previous_day)).days
        for key,value in zip(("open","high","low","close"),ohlc):
            features[present,col["last_observed_"+key+"_distance_pct"]]=100*(a[present,3]-value)/a[present,3]
    for duration in (5,15,30,60):
        for end in range(duration-1,n,duration):
            raw=a[end-duration+1:end+1,:4]
            if not np.isfinite(raw).all() or np.any(raw<=0):continue
            ohlc=(raw[0,0],raw[:,1].max(),raw[:,2].min(),raw[-1,3])
            at=np.arange(end,min(end+duration,n));at=at[present[at]]
            for key,value in zip(("open","high","low","close"),ohlc):
                features[at,col[f"completed_{duration}m_{key}_distance_pct"]]=100*(a[at,3]-value)/a[at,3]


def labels_for_session(a,*,all_minutes=False):
    """Delayed open-to-open target and observed high/low excursions.

    A label requires all bars through the exit reference; excursions use
    entry..exit-1 highs/lows plus the exit OPEN, never its future high/low.
    Scheduled but missing outcomes remain separate from signal eligibility.
    """
    n=MINUTES if all_minutes else prefix(a)
    present=np.isfinite(a[:n,:4]).all(axis=1)&(a[:n,:4]>0).all(axis=1)
    missing=np.r_[0,np.cumsum(~present)]
    if all_minutes:
        minutes=np.flatnonzero(present& (np.arange(n)<MINUTES-DELAY-2))
    else:minutes=np.arange(MIN_HISTORY-1,min(n,MINUTES-DELAY-2),dtype=int)
    entry=minutes+1+DELAY
    y=np.zeros((len(minutes),len(HORIZONS),3),np.float32)
    mask=np.zeros(y.shape[:2],bool);scheduled=np.zeros_like(mask)
    for k,duration in enumerate(HORIZONS):
        end=entry+duration;scheduled[:,k]=end<MINUTES
        valid=end<n
        if all_minutes:
            rows=np.flatnonzero(valid)
            valid[rows]&=(missing[end[rows]+1]-missing[minutes[rows]])==0
        mask[:,k]=valid
        if not valid.any():continue
        left=entry[valid];right=end[valid]
        ref=a[left,0];exit_=a[right,0]
        high=np.lib.stride_tricks.sliding_window_view(a[:n,1],duration)[left].max(axis=1)
        low=np.lib.stride_tricks.sliding_window_view(a[:n,2],duration)[left].min(axis=1)
        y[valid,k]=np.column_stack((10000*(exit_/ref-1),
                   10000*np.maximum(np.maximum(high,exit_)/ref-1,0),
                   10000*np.maximum(1-np.minimum(low,exit_)/ref,0)))
    classes=np.where(y[:,:,0]>DEADBAND_BPS,2,np.where(y[:,:,0]<-DEADBAND_BPS,0,1)).astype(np.int64)
    return minutes,y,classes,mask,scheduled


def build(index,stocks,membership,weights,peers,table,daily,overnight,dn,on,splits,*,index_only=False,progress=None,
          all_history=False,scratch=None,option_archive=None,global_archive=None,
          include_options=True,pretraining=False):
    dates=sorted(index);training=set(splits[0])
    bank_ids=[] if index_only else sorted({v for day,mp in membership.items() if day in training for v in mp.values()})
    if all_history and not index_only:
        bank_ids=sorted({identity for identity,source in stocks.items() if any(
            day in training and np.isfinite(values[:,3]).any() for day,values in source.items())})
    identities=["INDEX:BANKNIFTY",*bank_ids,*(() if index_only else m.f.PEERS)]
    sources=[index,*[stocks.get(x,{}) for x in bank_ids],*[peers.get(x,{}) for x in identities[1+len(bank_ids):]]]
    channels=len(ASSET_FIELDS)
    size=len(dates)*MINUTES*len(identities)*channels*4
    if not all_history and size>900_000_000:raise ValueError("Feature grid exceeds 900MB research bound")
    if all_history and scratch is None:raise ValueError("Full-history mode requires bounded disk-backed scratch")
    grid=histdata.allocate((len(dates),MINUTES,len(identities),channels),scratch,"assets")
    option_names=(option_archive.names if option_archive is not None else m.f.OPTION_NAMES) if include_options else ()
    if global_archive is not None:dn,on=global_archive.names,global_archive.overnight_names
    aux_names=() if index_only else tuple(BANK_AUX)+tuple(option_names)+tuple(dn)+tuple(on)
    aux=histdata.allocate((len(dates),MINUTES,len(aux_names)),scratch,"auxiliary")
    pretrain_targets=(histdata.allocate((len(dates),MINUTES//5,len(identities),2,3),scratch,"pretrain_targets")
                       if pretraining else None)
    pretrain_counts=np.zeros((len(identities),2),dtype=np.int64)
    avail=np.zeros((len(dates),MINUTES,len(AVAILABILITY)),bool)
    histories=[[] for _ in identities];last_complete=[None for _ in identities];audit={}
    availability_names=(*AVAILABILITY[:3],"global_context",AVAILABILITY[4]) if all_history else AVAILABILITY
    di=[];minutes=[];targets=[];classes=[];masks=[];scheduled=[]
    retcol=ASSET_FIELDS.index("return_5m_pct")
    for i,day in enumerate(dates):
        if progress and (i%25==0 or i+1==len(dates)):progress(f"Building unified minute grid {i+1}/{len(dates)} {day}")
        active=set(membership.get(day,{}).values());prev=direction.prior_weekday(day)
        grid[i]=np.nan;aux[i]=np.nan
        if pretrain_targets is not None:pretrain_targets[i]=np.nan
        for j,(identity,source) in enumerate(zip(identities,sources)):
            bank=1<=j<=len(bank_ids)
            n=sessions.cash_bank_minutes(day,identity) if bank else MINUTES
            q=sessions.cash_bank_minutes(prev,identity) if bank else MINUTES
            a=source.get(day)
            if all_history or not bank or identity in active:
                function=full_asset_features if all_history else asset_features
                grid[i,:,j]=function(a,source.get(prev),histories[j],n=n,q=q)
                add_clock_context(grid[i,:,j],a,day,last_complete[j],n)
                if bank and day in membership:
                    observed=grid[i,:,j,0]>0
                    grid[i,observed,j,ASSET_FIELDS.index("dated_bank_member")]=float(identity in active)
            if pretrain_targets is not None and day in training and a is not None:
                # Source-native labels, before feature normalization. Enforce
                # the reviewed cash-session boundary independently of index hours.
                raw=a.copy();raw[n:]=np.nan
                pm,py,_,pok,_=labels_for_session(raw,all_minutes=True)
                for k,horizon in enumerate((5,30)):
                    col=HORIZONS.index(horizon);take=((pm+1)%5==0)&pok[:,col]
                    pretrain_targets[i,pm[take]//5,j,k]=py[take,col]
                    pretrain_counts[j,k]+=int(take.sum())
            histories[j].append(daily_close(a,n))
            if prefix(a,n)==n:
                last_complete[j]=(day,(float(a[0,0]),float(a[:n,1].max()),float(a[:n,2].min()),float(a[n-1,3])))
        a=index[day]
        if not index_only:
            nbank=len(bank_ids);mat=grid[i,:,1:1+nbank,retcol].copy()
            if all_history:mat[:,[k for k,identity in enumerate(bank_ids) if identity not in active]]=np.nan
            nobs=np.isfinite(mat).sum(axis=1)
            scheduled_bank=m.f.scheduled_bank_counts(day,np.arange(MINUTES),active)
            frac=np.divide(nobs,scheduled_bank,out=np.zeros(MINUTES),where=scheduled_bank>0)
            mean=np.divide(np.nansum(mat,axis=1),nobs,out=np.full(MINUTES,np.nan),where=nobs>=3)
            dispersion=np.sqrt(np.divide(np.nansum((mat-mean[:,None])**2,axis=1),nobs,
                                        out=np.full(MINUTES,np.nan),where=nobs>=3))
            up=np.divide((mat>0).sum(axis=1),nobs,out=np.full(MINUTES,np.nan),where=nobs>=3)
            weighted=np.full(MINUTES,np.nan)
            dated=weights.get(day)
            if active and dated and set(dated)==active and active<=set(bank_ids):
                columns=[bank_ids.index(x) for x in sorted(active)]
                w=np.array([dated[x] for x in sorted(active)],float)
                if np.isfinite(w).all() and (w>=0).all() and w.sum()>0:
                    weighted=mat[:,columns]@(w/w.sum())
            aux[i,:,:len(BANK_AUX)]=np.column_stack((np.full(MINUTES,float(day in membership)),
                                     scheduled_bank,frac,mean,dispersion,up,weighted))
            avail[i,:,0]=(frac>=.8)&(nobs>=3)
            pm=grid[i,:,1+nbank:,retcol]
            avail[i,:,1]=np.isfinite(pm).mean(axis=1)>=.8
            off=len(BANK_AUX);end=off+len(option_names)
            if not include_options:
                pass
            elif option_archive is not None:
                aux[i,:,off:end],avail[i,:,2]=option_archive.features(day,a[:,3])
            else:
                for j in range(5,prefix(a)):
                    aux[i,j,off:end]=m.f.option_at(table,day,j,float(a[j,3]))
                avail[i,:,2]=np.isfinite(aux[i,:,off+1])
            if global_archive is not None:
                dv,known,nv,overnight_known=global_archive.features(day,np.flatnonzero(np.isfinite(a[:,3])))
                aux[i,:,end:end+len(dn)]=dv;aux[i,:,end+len(dn):]=nv
                avail[i,:,3]=known;avail[i,:,4]=overnight_known
            else:
                dv=daily.get(day,np.full(len(dn),np.nan));nv=overnight.get(day,np.full(len(on),np.nan))
                aux[i,:,end:end+len(dn)]=dv;aux[i,:,end+len(dn):]=nv
                avail[i,:,3]=np.isfinite(dv).sum()>=4;avail[i,:,4]=np.isfinite(nv).any()
        ms,y,c,ok,sc=labels_for_session(a,all_minutes=all_history)
        di.extend([i]*len(ms));minutes.extend(ms.tolist())
        targets.append(y);classes.append(c);masks.append(ok);scheduled.append(sc)
        audit[day]={"eligible_minutes":len(ms),"observed_index_prefix":prefix(a),
                    "observed_index_minutes":int(np.isfinite(a[:,3]).sum()),
                    "observed_equity_streams":sum(bool(np.isfinite(grid[i,:,j,0]).any()) for j in range(1,1+len(bank_ids))),
                    "dated_membership":day in membership,"active_members":len(active),
                    "training_known_members":len(active&set(bank_ids)),"verified_weights":day in weights,
                    "available_minutes":{name:int(avail[i,ms,k].sum()) for k,name in enumerate(availability_names)}}
    if not minutes:raise ValueError("No supported completed decision minutes")
    di=np.asarray(di,dtype=int)
    if isinstance(grid,np.memmap):grid.flush()
    if isinstance(aux,np.memmap):aux.flush()
    if isinstance(pretrain_targets,np.memmap):pretrain_targets.flush()
    return {"grid":grid,"aux":aux,"aux_names":aux_names,"identities":identities,"days":np.asarray(dates)[di],
            "all_history":all_history,"equity_identities":bank_ids,"availability_names":availability_names,
            "pretrain_targets":pretrain_targets,"pretrain_counts":pretrain_counts.tolist(),"dates":dates,
            "day_index":di,"minutes":np.asarray(minutes,dtype=int),"y":np.concatenate(targets),
            "classes":np.concatenate(classes),"mask":np.concatenate(masks),"scheduled":np.concatenate(scheduled),
            "available":avail,"audit":audit}


def fit_aux(data,train):
    if data.get("all_history"):
        return histdata.stats(lambda rows:data["aux"][data["day_index"][rows],data["minutes"][rows]],train)
    x=data["aux"][data["day_index"][train],data["minutes"][train]].astype(float)
    valid=np.isfinite(x);n=valid.sum(axis=0);clean=np.where(valid,x,0.)
    mean=np.divide(clean.sum(axis=0),n,out=np.zeros(x.shape[1]),where=n>0)
    sd=np.sqrt(np.divide((np.where(valid,clean-mean,0.)**2).sum(axis=0),n,
                         out=np.ones(x.shape[1]),where=n>0))
    return {"keep":n>=max(1,int(.05*len(train))),"mean":mean.astype(np.float32),
            "std":np.maximum(sd,1e-6).astype(np.float32)}


def windows(data,rows,joint,fit):
    """Only completed candles, padded earlier session slots and explicit masks."""
    rows=np.asarray(rows,dtype=int);days=data["day_index"][rows];minute=data["minutes"][rows]
    clocks=minute[:,None]-np.arange(LOOKBACK-1,-1,-1)[None,:]
    present=clocks>=0;clocks=np.maximum(clocks,0)
    grid=data["grid"] if joint else data["grid"][:,:,:1]
    x=grid[days[:,None],clocks]
    valid=np.isfinite(x)&present[:,:,None,None]
    values=np.where(valid,np.clip(x,-10,10),0.)
    raw=np.concatenate((values,valid.astype(np.float32)),axis=-1).astype(np.float32)
    if joint and fit["keep"].any():
        z=data["aux"][days[:,None],clocks][:,:,fit["keep"]]
        ok=np.isfinite(z)&present[:,:,None]
        scaled=np.where(ok,np.clip((z-fit["mean"][fit["keep"]])/fit["std"][fit["keep"]],-10,10),0.)
        aux=np.concatenate((scaled,ok.astype(np.float32)),axis=-1).astype(np.float32)
    else:aux=np.zeros((len(rows),LOOKBACK,1),np.float32)
    return raw,aux


def partitions(data,splits):
    days=data["days"]
    stride=np.ones(len(days),bool) if data.get("all_history") else ((data["minutes"]+1)%5==0)
    tr=np.flatnonzero(np.isin(days,splits[0])&stride&data["mask"].any(axis=1))
    va=np.flatnonzero(np.isin(days,splits[1]));te=np.flatnonzero(np.isin(days,splits[2]))
    for k in range(len(HORIZONS)):
        for rows,minimum in ((tr,40),(va,15),(te,15)):
            scored=rows[data["mask"][rows,k]]
            if len(set(days[scored]))<minimum:raise ValueError("Insufficient horizon/session support")
        if len(np.unique(data["classes"][tr[data["mask"][tr,k]],k]))!=3:
            raise ValueError("All three classes required for every training horizon")
    return tr,va,te


def predict(torch,model,data,rows,joint,fit,batch,device):
    probs=[];reg=[];model.eval()
    with torch.no_grad():
        for i in range(0,len(rows),batch):
            x,z=windows(data,rows[i:i+batch],joint,fit)
            logits,y=model(torch.from_numpy(x).to(device),torch.from_numpy(z).to(device))
            probs.append(torch.softmax(logits,dim=-1).cpu().numpy());reg.append(y.cpu().numpy()*10)
    return np.concatenate(probs),np.concatenate(reg)


def val_rank(data,rows,p):
    scores=[]
    for k in range(len(HORIZONS)):
        ok=data["mask"][rows,k];ix=rows[ok]
        err=np.sum((p[ok,k]-np.eye(3)[data["classes"][ix,k]])**2,axis=1)
        scores.append(float(m._avg(err,data["days"][ix])))
    return float(np.mean(scores))


def fit_neural(data,tr,va,te,fit,*,joint,epochs,batch,device,progress):
    torch,net=seq._torch();torch.manual_seed(SEED)
    if device.type=="cuda":torch.cuda.manual_seed_all(SEED)
    rng=np.random.default_rng(SEED)
    x,z=windows(data,tr[:1],joint,fit)
    model=net.MarketDynamics(x.shape[2],x.shape[3],z.shape[2],len(HORIZONS)).to(device)
    optimizer=torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.01)
    weights=np.zeros(len(data["days"]),np.float32);weights[tr]=m.day_weights(data["days"][tr])
    best=None;history=[];stale=0
    mode="joint" if joint else "index_only"
    for epoch in range(1,epochs+1):
        model.train();order=(histdata.shuffled_sessions(tr,data["day_index"],rng) if data.get("all_history")
                              else rng.permutation(tr));total=0.;seen=0
        for i in range(0,len(order),batch):
            rows=order[i:i+batch];x,z=windows(data,rows,joint,fit)
            out=model(torch.from_numpy(x).to(device),torch.from_numpy(z).to(device))
            loss=net.dynamics_objective(out,torch.from_numpy(data["classes"][rows]).to(device),
                    torch.from_numpy(data["y"][rows]/10).to(device),
                    torch.from_numpy(data["mask"][rows].astype(np.float32)).to(device),
                    torch.from_numpy(weights[rows]).to(device))
            if not bool(torch.isfinite(loss)):raise ValueError("Nonfinite dynamics training loss")
            optimizer.zero_grad(set_to_none=True);loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(),1.);optimizer.step()
            seen+=len(rows);total+=float(loss.detach().cpu())*len(rows)
            if progress and i and i%(batch*100)==0:progress(f"TRAIN {mode} epoch {epoch}/{epochs} {seen}/{len(order)}")
        p,_=predict(torch,model,data,va,joint,fit,batch,device)
        rank=val_rank(data,va,p)
        history.append({"epoch":epoch,"training_loss":total/seen,"validation_mean_brier":rank})
        if progress:progress("DYNAMICS_VALIDATION "+mode+" "+json.dumps(history[-1]))
        if best is None or rank<best["rank"]-1e-6:
            best={"rank":rank,"epoch":epoch,"state":{k:v.detach().cpu().clone() for k,v in model.state_dict().items()}}
            stale=0
        else:
            stale+=1
            if stale>=3:break
    model.load_state_dict(best["state"])
    vp,vr=predict(torch,model,data,va,joint,fit,batch,device)
    ep,er=predict(torch,model,data,te,joint,fit,batch,device)
    return {"validation":(vp,vr),"evaluation":(ep,er),"state":best["state"],
            "selected_epoch":best["epoch"],"history":history,
            "parameters":sum(p.numel() for p in model.parameters()),
            "input_dimensions":[x.shape[2],x.shape[3],z.shape[2]]}


def snapshot(data,rows,joint):
    grid=data["grid"] if joint else data["grid"][:,:,:1]
    x=grid[data["day_index"][rows],data["minutes"][rows]].reshape(len(rows),-1)
    if joint:x=np.column_stack((x,data["aux"][data["day_index"][rows],data["minutes"][rows]]))
    return x


def calibration(vp,ep,labels,days):
    t=direction._calibrate(vp,labels-1,days)
    return direction.a._temperature(ep,t),t


def calibrated_metrics(raw,cal,labels,days):
    metrics,_=direction._prob_metrics(cal,labels-1,days)
    raw_metrics,_=direction._prob_metrics(raw,labels-1,days)
    metrics["raw_brier"]=raw_metrics["brier"]
    nonflat=labels!=1
    if nonflat.any():
        signed=cal[nonflat,2]/np.maximum(cal[nonflat,0]+cal[nonflat,2],1e-12)
        metrics["conditional_nonflat_sign_brier"]=float(m._avg((signed-(labels[nonflat]==2))**2,days[nonflat]))
    else:metrics["conditional_nonflat_sign_brier"]=None
    return metrics


def score_all(data,tr,va,te,models,joint,progress,*,v3=False):
    # One fixed latest-snapshot logistic comparator on the same data scope;
    # no architecture/horizon/threshold search on the evaluated dates.
    full=data.get("all_history",False)
    if full:
        getter=lambda rows:snapshot(data,rows,joint)
        stream_fit=histdata.stats(getter,tr)
    else:tx=snapshot(data,tr,joint);vx=snapshot(data,va,joint);ex=snapshot(data,te,joint)
    reports={};predictions={name:np.zeros((len(te),len(HORIZONS),3),float)
                           for name in ("constant_prior","clock_prior","snapshot",*models)}
    for k,horizon in enumerate(HORIZONS):
        if progress:progress(f"Scoring matched {horizon}m direction and excursion outcomes")
        mt=data["mask"][tr,k];mv=data["mask"][va,k];me=data["mask"][te,k]
        yt=data["classes"][tr[mt],k];yv=data["classes"][va[mv],k];ye=data["classes"][te[me],k]
        dt=data["days"][tr[mt]];dv=data["days"][va[mv]];de=data["days"][te[me]]
        prior=m._avg(np.eye(3)[yt],dt)
        bucket={}
        for clock in range(13):
            choose=data["minutes"][tr[mt]]//30==clock
            if choose.sum()>=30 and len(set(dt[choose]))>=10:bucket[clock]=m._avg(np.eye(3)[yt[choose]],dt[choose])
        def clock(rows):return np.stack([bucket.get(int(j)//30,prior) for j in data["minutes"][rows]])
        if full:
            vl,el=histdata.streaming_snapshot(getter,tr[mt],va,te,data["classes"][:,k],data["days"],
                                               data["day_index"],stream_fit,seed=SEED,stable=v3)
        else:
            keep=np.isfinite(tx[mt]).mean(axis=0)>=.05
            with threadpool_limits(limits=2):
                linear=m.direction_model("ridge",tx[mt][:,keep],yt,m.day_weights(dt))
                vl=linear.predict_proba(vx[:,keep]);el=linear.predict_proba(ex[:,keep])
        methods={"constant_prior":(np.tile(prior,(len(va),1)),np.tile(prior,(len(te),1))),
                 "clock_prior":(clock(va),clock(te)),"snapshot":(vl,el)}
        for name,model in models.items():methods[name]=(model["validation"][0][:,k],model["evaluation"][0][:,k])
        target=data["y"][te[me],k];truth=np.eye(3)[ye]
        # Training-only adaptive excursion reference, scaled by recent
        # one-minute RMS volatility and the requested horizon.
        col=ASSET_FIELDS.index("vol_15m_pct")
        def scale(rows):
            z=data["grid"][data["day_index"][rows],data["minutes"][rows],0,col].astype(float)*100
            return np.maximum(np.where(np.isfinite(z),z,.5),.5)*np.sqrt(horizon)
        ratio=data["y"][tr[mt],k,1:]/scale(tr[mt])[:,None]
        typical=np.median(ratio,axis=0)
        reference=np.column_stack((np.zeros(len(ye)),scale(te[me])[:,None]*typical))
        record={"train_rows":len(yt),"validation_rows":len(yv),"evaluation_rows":len(ye),
                "scheduled_evaluation_rows":int(data["scheduled"][te,k].sum()),
                "unresolved_evaluation_rows":int((data["scheduled"][te,k]&~me).sum()),
                "training_class_prior":prior.tolist(),"methods":{},
                "adaptive_mae_bps":m._avg(np.abs(reference-target),de).tolist()}
        losses={};sign_losses={};nonflat=ye!=1;regressions={};movement_losses={};raw_losses={};raw_sign_losses={}
        for name,(vp,ep) in methods.items():
            cal,t=calibration(vp[mv],ep,yv,dv);predictions[name][:,k]=cal
            prob=cal[me];metric=calibrated_metrics(ep[me],prob,ye,de);metric["temperature"]=t
            all_calls=np.where((cal.max(axis=1)>=CONFIDENCE)&(cal.argmax(axis=1)!=1),cal.argmax(axis=1)-1,0)
            metric["actions"]=direction._action_metrics(all_calls[me],ye-1,target[:,0],de)[0]
            metric["unresolved_scheduled_calls"]=int(((all_calls!=0)&data["scheduled"][te,k]&~me).sum())
            losses[name]=np.sum((prob-truth)**2,axis=1)
            raw_losses[name]=np.sum((ep[me]-truth)**2,axis=1)
            movement_losses[name]=(1-prob[:,1]-nonflat)**2
            metric["movement_brier"]=float(m._avg(movement_losses[name],de))
            if nonflat.any():
                pp=prob[nonflat,2]/np.maximum(prob[nonflat,0]+prob[nonflat,2],1e-12)
                sign_losses[name]=(pp-(ye[nonflat]==2))**2
                raw=ep[me][nonflat];rp=raw[:,2]/np.maximum(raw[:,0]+raw[:,2],1e-12)
                raw_sign_losses[name]=(rp-(ye[nonflat]==2))**2
            if name in models:
                reg=models[name]["evaluation"][1][me,k];regressions[name]=np.abs(reg-target)
                metric["return_up_down_mae_bps"]=m._avg(regressions[name],de).tolist()
                metric["return_mae_minus_zero"]=m.paired_day_interval(regressions[name][:,0]-np.abs(target[:,0]),de)
                metric["excursion_mae_minus_adaptive"]=m.paired_day_interval(
                    regressions[name][:,1:].mean(axis=1)-np.abs(reference[:,1:]-target[:,1:]).mean(axis=1),de)
            record["methods"][name]=metric
        main="joint" if joint else "index_only"
        refs=("constant_prior","clock_prior","snapshot")+(("index_only",) if joint else ())
        record["paired_brier"]={key:m.paired_day_interval(losses[main]-losses[key],de) for key in refs}
        record["paired_conditional_sign_brier"]={key:m.paired_day_interval(sign_losses[main]-sign_losses[key],de[nonflat])
             for key in refs} if nonflat.any() else {}
        if v3:
            record["paired_movement_brier"]={key:m.paired_day_interval(movement_losses[main]-movement_losses[key],de) for key in refs}
            record["paired_brier_vs_raw_references"]={key:m.paired_day_interval(losses[main]-raw_losses[key],de) for key in refs}
            record["paired_sign_vs_raw_references"]={key:m.paired_day_interval(sign_losses[main]-raw_sign_losses[key],de[nonflat]) for key in refs} if nonflat.any() else {}
        if joint:
            record["paired_return_mae_joint_minus_core"]=m.paired_day_interval(
                regressions["joint"][:,0]-regressions["index_only"][:,0],de)
        act=record["methods"][main]["actions"]
        proxy=act["net_proxy_per_eligible_opportunity"]["interval_95"]
        def favorable(v):return v["interval_95"] is not None and v["interval_95"][1]<0
        record["exploratory_checks"]={
            "brier_beats_all_references":all(favorable(v) for v in record["paired_brier"].values()),
            "nonflat_sign_beats_all_references":bool(record["paired_conditional_sign_brier"]) and
                all(favorable(v) for v in record["paired_conditional_sign_brier"].values()),
            "minimum_call_support":act["calls"]>=100 and act["call_sessions"]>=30,
            "both_directions":act["up_calls"]>0 and act["down_calls"]>0,
            "positive_index_proxy_lower_interval":proxy is not None and proxy[0]>0}
        record["trade_qualified"]=False
        reports[str(horizon)]=record
    return reports,predictions


def journal_rows(data,te,models,probs):
    for i,j in enumerate(te):
        day=str(data["days"][j]);minute=int(data["minutes"][j]);entry=minute+1+DELAY
        for k,horizon in enumerate(HORIZONS):
            if not data["scheduled"][j,k]:continue
            observed=bool(data["mask"][j,k])
            row={"session":day,"decision_utc":r._stamp(day,minute+1),
                 "entry_reference_utc":r._stamp(day,entry),"exit_reference_utc":r._stamp(day,entry+horizon),
                 "horizon_minutes":horizon,"outcome_observed":observed,
                 "actual_class":int(data["classes"][j,k]-1) if observed else None,
                 **{key:float(data["y"][j,k,n]) if observed else None
                    for n,key in enumerate(("actual_return_bps","actual_up_excursion_bps","actual_down_excursion_bps"))}}
            for name,p in probs.items():
                for n,key in enumerate(("down","flat","up")):row[name+"_"+key+"_probability"]=float(p[i,k,n])
            for name,model in models.items():
                for n,key in enumerate(("return","up_excursion","down_excursion")):
                    row[name+"_predicted_"+key+"_bps"]=float(model["evaluation"][1][i,k,n])
            for n,name in enumerate(data.get("availability_names",AVAILABILITY)):
                row[name+"_available"]=bool(data["available"][data["day_index"][j],minute,n])
            yield row


def run(root,stop,days=365,*,index_only=False,epochs=8,batch=128,device_name="cpu",progress=print,all_history=False,
        v3=False,include_options=False,pretrain_epochs=2,accumulate=4,width=128):
    if v3 and not all_history:raise ValueError("V3 requires --all-history")
    if include_options and (not v3 or index_only):raise ValueError("--include-options is the optional V3 ablation; V2 already includes options")
    if all_history:
        root=Path(root).resolve();folder=root/"results";folder.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="market_dynamics_scratch_",dir=folder) as scratch:
            return _run(root,stop,days,index_only=index_only,epochs=epochs,batch=batch,
                        device_name=device_name,progress=progress,all_history=True,scratch=Path(scratch),v3=v3,
                        include_options=include_options,pretrain_epochs=pretrain_epochs,accumulate=accumulate,width=width)
    return _run(root,stop,days,index_only=index_only,epochs=epochs,batch=batch,device_name=device_name,progress=progress)


def _run(root,stop,days=365,*,index_only=False,epochs=8,batch=128,device_name="cpu",progress=print,all_history=False,scratch=None,
         v3=False,include_options=False,pretrain_epochs=2,accumulate=4,width=128):
    maximum=m.MAX_CORE_DAYS if index_only else m.MAX_CONTEXT_DAYS
    if type(days) is not int or (not all_history and not 120<=days<=maximum) or stop>datetime.now(h.IST).date():
        raise ValueError("Use completed dates and bounded source history")
    if not 1<=epochs<=30 or not 16<=batch<=256:raise ValueError("Bound epochs to 1-30 and batch to 16-256")
    if v3 and (width not in (64,128,256) or not 1<=pretrain_epochs<=4 or not 1<=accumulate<=16):
        raise ValueError("Invalid V3 width, pretraining epochs or accumulation")
    torch,_=seq._torch()
    torch.set_num_threads(min(4,os.cpu_count() or 1))
    if device_name=="cuda" and not torch.cuda.is_available():raise ValueError("CUDA unavailable")
    device=torch.device(device_name)
    service.DATA=root/"data"
    if not service.DATA.is_dir():raise ValueError("Shared data directory missing")
    start=histdata.archive_start(stop) if all_history else stop-timedelta(days=days)
    index,stocks,membership,weights,peers,_,meta=m.load_sources(start,stop,wings=None,index_only=index_only,progress=progress)
    dates=sorted(index);splits=histdata.full_splits(dates) if all_history else m.split_days(dates)
    table={};daily={};overnight={};dn=();on=();option_archive=None;global_archive=None
    if all_history and not index_only:
        stocks,meta["all_equities"]=histdata.load_equities(start,stop,dates,stocks,progress)
        if not v3 or include_options:
            option_archive=histdata.load_options(index,splits[0],progress)
            meta["all_rolling_options"]=option_archive.evidence
        else:meta["all_rolling_options"]={"state":"excluded_from_underlying_model"}
        global_archive=histdata.load_global(start,stop,dates,progress)
        meta["all_global"]=global_archive.evidence
    elif not index_only:
        try:
            progress("Verifying rolling option context on the minute clock")
            stamps={r._stamp(day,j) for day in dates for j in range(MINUTES)}
            table,om=opt._load_options([{"session":day} for day in dates],3,needed_stamps=stamps)
            meta["options"]={**om,"state":"loaded" if table else "unavailable","wings":3}
        except (ValueError,OSError,RuntimeError,TypeError,KeyError) as exc:
            meta["options"]={"state":"unavailable","reason":str(exc)[:180]}
        try:
            daily,overnight,gm,dn,on=passage.global_features(start,stop,dates);meta["global"]=gm
        except (ValueError,OSError,sqlite3.Error) as exc:
            meta["global"]={"state":"unavailable","reason":str(exc)[:180]}
            dn=tuple(passage.global_open.DAILY);on=tuple("BOATS_"+s for s in passage.global_open.OVERNIGHT)
    data=build(index,stocks,membership,weights,peers,table,daily,overnight,dn,on,splits,
               index_only=index_only,progress=progress,all_history=all_history,scratch=scratch,
               option_archive=option_archive,global_archive=global_archive,
               include_options=(not v3 or include_options),pretraining=v3)
    if global_archive is not None:meta["all_global"]["factor_receipt_hashes"]=sorted(global_archive.receipts)
    if all_history:
        meta["all_equities_excluded_from_embedding"]=sorted(set(stocks)-set(data["equity_identities"]))
    del index,stocks,peers,table,option_archive,global_archive
    tr,va,te=partitions(data,splits);fit=fit_aux(data,tr)
    progress(f"GRID {data['grid'].shape} bytes={data['grid'].nbytes} TRAIN {len(tr)} VALIDATION {len(va)} EVALUATION {len(te)}")
    models={}
    for name,joint in (("index_only",False),) if index_only else (("index_only",False),("joint",True)):
        progress("Fitting fixed custom market dynamics "+name)
        if v3:
            from scripts import market_dynamics_v3 as advanced
            models[name]=advanced.fit(data,tr,va,te,fit,joint=joint,epochs=epochs,batch=batch,device=device,
                                      progress=progress,pretrain_epochs=pretrain_epochs,accumulate=accumulate,width=width)
        else:models[name]=fit_neural(data,tr,va,te,fit,joint=joint,epochs=epochs,batch=batch,device=device,progress=progress)
    metrics,probs=score_all(data,tr,va,te,models,not index_only,progress,v3=v3)
    version=("market_dynamics_v3_with_options" if include_options else "market_dynamics_v3_underlying") if v3 else (FULL_VERSION if all_history else VERSION)
    report={"version":version,"from_inclusive":start.isoformat(),"to_exclusive":stop.isoformat(),
            "full_history":all_history,"observed_date_span":[dates[0],dates[-1]],
            "split_policy":"all_earlier_train_plus_latest_365d_60_20_20" if all_history else "60_20_20",
            "grid_storage":"temporary_memmap" if all_history else "in_memory",
            "snapshot_policy":"streaming_logistic_sgd_3passes" if all_history else "regularized_logistic",
            "equity_identities":data["equity_identities"],
            "training_dates":splits[0],"validation_dates":splits[1],"evaluation_dates":splits[2],
            "observed_index_sessions":len(dates),"assets":data["identities"],"asset_fields":list(ASSET_FIELDS),
            "auxiliary_fields":list(data["aux_names"]),"retained_auxiliary_fields":[n for n,k in zip(data["aux_names"],fit["keep"]) if k],
            "grid_bytes":int(data["grid"].nbytes),"aux_bytes":int(data["aux"].nbytes),"session_audit":data["audit"],
            "partition_rows":{"training":len(tr),"validation":len(va),"evaluation":len(te)},
            "availability":{name:{key:int(data["available"][data["day_index"][rows],data["minutes"][rows],k].sum())
                           for key,rows in (("training",tr),("validation",va),("evaluation",te))}
                           for k,name in enumerate(data.get("availability_names",AVAILABILITY))},
            "horizons":list(HORIZONS),"delay_minutes":DELAY,"lookback_minutes":LOOKBACK,"minimum_history":1 if all_history else MIN_HISTORY,
            "training_stride":1 if all_history else 5,"deadband_bps":DEADBAND_BPS,"confidence":CONFIDENCE,"seed":SEED,
            "models":{name:{key:result[key] for key in ("selected_epoch","history","parameters","input_dimensions")}
                      for name,result in models.items()},"evaluation":metrics,"sources":meta,
            "device":device_name,"torch_version":str(torch.__version__),"trade_qualified":False,
            "warning":("Exploratory custom supervised market dynamics, not a validated trading system. All eligible completed "
                       "minutes, 30-minute context padded before 30 bars (minimum 15), prior-weekday EMA/levels when complete, "
                       "and 5/20/60 earlier observed-session daily summaries (not certified exchange calendar or full overnight sequence). "
                       "Current gaps terminate supported prefix; missing context remains masked. Joint model uses training-known dated bank IDs, "
                       "actual membership and weights only, observed equity/VIX histories, rolling monthly options and archive-as-of 09:10 "
                       "global ETF/daily proxies. Historical timestamps do not prove live receipt availability. "
                       "Targets are delayed index opens and observed excursions, not option fills. Fit stride five overlaps longer targets within "
                       "training sessions; whole-session partitions separate outcomes. Validation-only epoch choice and temperature calibration; "
                       "all horizons reported, no post-hoc selection. Conditional scored metrics exclude unresolved outcomes, whose scheduled "
                       "predictions remain in the journal. Proxy 5bps is illustrative, overlapping opportunities not account P&L. "
                       "No RL, exact-contract selection, live inference/promotion, orders or new data downloads. Previously inspected dates are "
                       "exploratory; prospective shadow confirmation and separate option execution tests remain mandatory.")}
    if all_history:
        report["warning"]=("Full-history exploratory MarketDynamics v2: all observed BANKNIFTY date receipts within bounded "
            "original target span; all eligible observed decision minutes, including after gaps, and every earlier resolved "
            "training minute. Recent 365 calendar days reserve chronological 60/20/20 dates; earlier sessions train. "
            "30-minute raw sequence with masks, 5/20/60 earlier observed-session summaries, not an uninterrupted multiyear "
            "minute sequence. Complete prior weekday levels only; EMA reset after missing bars; incomplete current-session "
            "running OHLC/CPR masked. Individual verified equity histories with training-known embeddings regardless of "
            "membership; only dated active members contribute to bank breadth/weights. All verified rolling family/offset "
            "streams with training support, not exact exchange contracts. Global factors as-of completed minute and all "
            "BOATS proxies frozen at 09:10; archive timestamps not proof of live availability. Missing original sources and "
            "evaluation-only identities reported. No tick/order-book histories, exact historical fills, Greeks inferred from "
            "unknown expiry, future data or invented membership. Scratch feature grids removed after fitting. "
            "Validation-only epoch/calibration, all horizons, overlapping index proxy not account P&L; no live qualification, "
            "RL or orders. Previously examined dates exploratory; future prospective evidence required.")
    if v3:
        report["architecture"]={"width":width,"heads":8,"cross_layers":2,"gru_layers":2,"transformer_layers":2,
                                "local_minutes":30,"intraday_block_minutes":15,"prior_sessions":60,
                                "pretrain_horizons":[5,30],"pretrain_stride":5,"pretrain_epochs":pretrain_epochs,
                                "gradient_accumulation":accumulate,"batch_size":batch,"options_included":include_options}
        report["snapshot_policy"]="streaming_logistic_sgd_constant_lr_3passes"
        report["available_pretraining_labels_per_asset"]={asset:counts for asset,counts in zip(data["identities"],data["pretrain_counts"])}
        for name,result in models.items():
            report["models"][name].update(pretraining=result["pretraining"],precision=result["precision"],
                                          used_pretraining_labels=result["used_pretraining_labels"],
                                          memory_dimensions=result["memory_dimensions"])
        report["warning"]=(report["warning"].replace("MarketDynamics v2","MarketDynamics v3").replace("All verified rolling family/offset streams with training support, not exact exchange contracts.","All verified rolling family/offset streams with training support, not exact exchange contracts." if include_options else "Underlying-only primary model: all rolling option inputs explicitly excluded."))+" V3 uses a 30-minute raw local window, completed 15-minute session blocks and 60 prior observed-session tokens; long memory tokens contain index features and cross-sectional mean/dispersion/coverage, not all instruments raw at all times. Pretraining uses 5/30m instrument-specific observed labels on earlier five-minute anchors; fine-tuning uses every eligible resolved minute. Movement and conditional direction have separate supervised losses; validation rank averages their Brier scores. Optional options lane is a separate fixed ablation, not a trading decision. Previously inspected evaluation dates remain exploratory. Raw and calibrated probability comparisons are both reported."
    checkpoint={"version":version,"full_history":all_history,"research_only":True,"trade_qualified":False,"assets":data["identities"],
                "asset_fields":list(ASSET_FIELDS),"auxiliary_fields":list(data["aux_names"]),
                "aux_fit":{k:v.tolist() for k,v in fit.items()},"horizons":list(HORIZONS),
                "models":{name:{"state_dict":result["state"],"input_dimensions":result["input_dimensions"],
                                "selected_epoch":result["selected_epoch"],
                                "temperatures":[metrics[str(h)]["methods"][name]["temperature"] for h in HORIZONS]}
                          for name,result in models.items()},"training_dates":splits[0],"validation_dates":splits[1]}
    # The journal needs only labels, clocks, availability and predictions.
    # Release scratch mappings before the outer TemporaryDirectory exits.
    if v3:checkpoint["architecture"]=report["architecture"]
    if all_history:del data["grid"],data["aux"],data["pretrain_targets"]
    return report,journal_rows(data,te,models,probs),checkpoint


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--shared-root",type=Path,default=service.ROOT)
    ap.add_argument("--days",type=int,default=365)
    ap.add_argument("--to-date",default="2026-11-27")
    ap.add_argument("--index-only",action="store_true")
    ap.add_argument("--all-history",action="store_true",help="Use earliest target receipt, all saved verified context, every observed training minute")
    ap.add_argument("--v3",action="store_true",help="Larger multiscale underlying model with all-instrument pretraining")
    ap.add_argument("--include-options",action="store_true",help="Separate V3 rolling-option context ablation")
    ap.add_argument("--pretrain-epochs",type=int,default=2)
    ap.add_argument("--accumulate",type=int,default=4)
    ap.add_argument("--width",type=int,choices=(64,128,256),default=128)
    ap.add_argument("--epochs",type=int,default=8)
    ap.add_argument("--batch",type=int,default=128)
    ap.add_argument("--device",choices=("cpu","cuda"),default=None)
    args=ap.parse_args()
    try:
        root=args.shared_root.resolve()
        report,rows,checkpoint=run(root,date.fromisoformat(args.to_date),args.days,index_only=args.index_only,
             epochs=args.epochs,batch=args.batch,device_name=args.device or ("cuda" if args.all_history else "cpu"),
             progress=lambda s:print(s,flush=True),all_history=args.all_history,v3=args.v3,
             include_options=args.include_options,pretrain_epochs=args.pretrain_epochs,accumulate=args.accumulate,width=args.width)
        folder=root/"results";folder.mkdir(exist_ok=True)
        stem="banknifty_market_dynamics_"+uuid.uuid4().hex
        path=folder/(stem+".json");csv_path=folder/(stem+"_predictions.csv");weights=folder/(stem+"_research_only.pt")
        torch,_=seq._torch()
        tmp=weights.with_suffix(".tmp")
        try:torch.save(checkpoint,tmp);os.replace(tmp,weights)
        finally:tmp.unlink(missing_ok=True)
        def writer(out):
            first=next(rows);w=csv.DictWriter(out,fieldnames=list(first));w.writeheader();w.writerow(first);w.writerows(rows)
        write_atomic(csv_path,writer)
        report.update(prediction_csv=csv_path.name,research_checkpoint=weights.name)
        write_atomic(path,lambda out:json.dump(report,out,sort_keys=True,indent=2,allow_nan=False))
        print("HISTORY",report["version"],report["observed_date_span"],"observed sessions",report["observed_index_sessions"],
              "training stride",report["training_stride"],"grid storage",report["grid_storage"],"device",report["device"])
        print("ASSETS",json.dumps(report["assets"]))
        print("PARTITIONS",json.dumps(report["partition_rows"]))
        print("AVAILABILITY",json.dumps(report["availability"]))
        if args.v3:
            print("ARCHITECTURE",json.dumps(report["architecture"]))
            print("PRETRAIN_LABELS",json.dumps(report["available_pretraining_labels_per_asset"]))
            print("MODELS",json.dumps(report["models"]))
        for horizon,s in report["evaluation"].items():
            summary={key:s[key] for key in ("evaluation_rows","unresolved_evaluation_rows","adaptive_mae_bps",
                     "paired_brier","paired_conditional_sign_brier","exploratory_checks")}
            summary["methods"]={name:{key:v.get(key) for key in ("brier","raw_brier","balanced_accuracy",
                "conditional_nonflat_sign_brier","movement_brier","return_up_down_mae_bps","actions")} for name,v in s["methods"].items()}
            if args.v3:
                summary.update({key:s[key] for key in ("paired_movement_brier","paired_brier_vs_raw_references","paired_sign_vs_raw_references")})
            print("DYNAMICS",horizon,json.dumps(summary))
        print("REPORT",path);print("PREDICTIONS",csv_path);print("RESEARCH_CHECKPOINT",weights)
        print(report["warning"])
        return 0
    except (ValueError,OSError,RuntimeError) as exc:
        print("Market dynamics unavailable:",str(exc)[:300])
        return 2


if __name__=="__main__":
    raise SystemExit(main())
