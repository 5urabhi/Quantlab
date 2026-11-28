"""Bounded, original-receipt-backed full-history context for MarketDynamics.

Derived scratch arrays never replace raw history. Include saved equity sources
as individual context, not inferred index members. Options are rolling
family/offset observations, not a verified historical contract master.
"""
from collections import Counter
from contextlib import closing
from datetime import date,datetime,time,timedelta
from hashlib import sha256
import csv
import json
from pathlib import Path
import re
import shutil
import sqlite3

import numpy as np
from sklearn.linear_model import SGDClassifier
from threadpoolctl import threadpool_limits

from workstation_api import banknifty_candle_forecast as m, historical_alpha as h
from workstation_api import cockpit_sources, dhan_checkpoint, intraday_parquet as pq
from workstation_api import expired_options_backtest as exp, options_history_sync as sync
from workstation_api import market_context, alpaca_overnight, shared_market_data, service
from workstation_api import cpr_hybrid_research as r

MINUTES=375
MAX_HISTORY_DAYS=3660
MAX_EQUITIES=120
MAX_GRID_BYTES=16*1024**3
MAX_OPTION_INPUT_BYTES=12*1024**3
MAX_OPTION_RAW_BYTES=2*1024**3
OPTION_RAW=("strike","open","high","low","close","volume","oi","iv")
OPTION_FIELDS=("strike_distance_pct","open_pct","high_pct","low_pct","close_pct",
               "log_volume","log_oi","iv","same_strike_5m_return_pct","same_strike_5m_oi_change_pct")
GLOBAL_NAMES=tuple(key+":"+name for key in market_context.FACTORS
                   for name in ("normalized_level","change","age_hours"))
OVERNIGHT_NAMES=tuple("BOATS:"+key+":"+name for key in alpaca_overnight.SYMBOLS
                      for name in ("session_return_bps","trailing_30m_bps","coverage_ratio","age_minutes"))


def archive_start(stop):
    starts=[]
    for _,_,meta in cockpit_sources._candidates("INDEX:BANKNIFTY"):
        try:
            left=date.fromisoformat(meta["from_inclusive"])
            if left<stop:starts.append(left)
        except (KeyError,TypeError,ValueError):
            continue
    if not starts:raise ValueError("No dated BANKNIFTY original receipts")
    start=min(starts)
    if not 120<=(stop-start).days<=MAX_HISTORY_DAYS:
        raise ValueError("Full original receipt span outside 120-3660 day safety bound")
    return start


def full_splits(dates):
    """All earlier dates train; latest 365 calendar days reserve 60/20/20."""
    dates=sorted(dates)
    if not dates:raise ValueError("No observed index sessions")
    cutoff=(date.fromisoformat(dates[-1])-timedelta(days=364)).isoformat()
    old=[d for d in dates if d<cutoff]
    train,val,test=m.split_days([d for d in dates if d>=cutoff])
    return old+train,val,test


def allocate(shape,scratch,name):
    size=int(np.prod(shape,dtype=np.int64))*4
    if scratch is None:return np.full(shape,np.nan,np.float32)
    if size==0:return np.full(shape,np.nan,np.float32)
    used=sum(p.stat().st_size for p in Path(scratch).glob("*.bin"))
    if used+size>MAX_GRID_BYTES or shutil.disk_usage(scratch).free<used+size+512*1024**2:
        raise ValueError(f"Insufficient bounded feature scratch space for {name}: {size} bytes")
    return np.memmap(Path(scratch)/(name+".bin"),mode="w+",dtype=np.float32,shape=shape)


def load_equities(start,stop,dates,stocks,progress=None):
    """Discover original 1m equity caches, including nonmember PSU/equities."""
    root=service.DATA/"dhan"/"history";identities=set(stocks)
    if root.is_symlink():raise ValueError("Unsafe original equity history root")
    for segment in ("NSE_EQ","BSE_EQ"):
        folder=root/segment
        if not folder.is_dir() or folder.is_symlink():continue
        for child in folder.iterdir():
            if child.is_dir() and not child.is_symlink() and re.fullmatch(r"[0-9]{1,12}",child.name):
                if (child/"1m.csv").exists() or (child/"1m.json").exists():
                    identities.add(segment+":"+child.name)
    if len(identities)>MAX_EQUITIES:
        raise ValueError(f"{len(identities)} original equity identities exceed explicit {MAX_EQUITIES} research bound")
    wanted=set(dates);evidence={};failures={}
    for i,identity in enumerate(sorted(identities)):
        if progress:progress(f"Verifying saved equity {i+1}/{len(identities)} {identity}")
        try:
            if identity in stocks and stocks[identity]:
                evidence[identity]={"state":"reused_membership_source","sessions":len(stocks[identity])}
                continue
            path,sidecar=pq._raw(identity)
            receipt=dhan_checkpoint._read_receipt(sidecar,identity=identity,interval=1)
            raw=h._read_file(path,receipt["sha256"],start,stop,[h.MAX_TOTAL],receipt["rows"])
            values={day:m.f.dense(bars) for day,bars in raw.items() if day in wanted}
            if not values:raise ValueError("No overlap with observed BANKNIFTY dates")
            stocks[identity]=values
            evidence[identity]={"state":"verified","source_sha256":receipt["sha256"],"sessions":len(values),
                                "first_session":min(values),"last_session":max(values)}
        except (ValueError,OSError,TypeError,KeyError,OverflowError,csv.Error) as exc:
            failures[identity]=str(exc)[:180]
    return stocks,{"discovered_identities":sorted(identities),"sources":evidence,"failures":failures,
                   "membership_note":"Individual equity streams do not imply dated index membership."}


def group_name(group):return ":".join(map(str,group))


class RollingArchive:
    def __init__(self,groups,training,evidence):
        self.groups=groups;self.evidence=evidence
        self.keys=tuple(sorted(key for key,days in groups.items() if any(
            day in training and np.isfinite(values[:,0]).any() for day,(values,_) in days.items())))
        self.names=tuple(m.f.OPTION_NAMES)+tuple(
            "rolling:"+group_name(key)+":"+field for key in self.keys for field in OPTION_FIELDS)
        evidence["observed_groups"]={group_name(key):{"sessions":int(sum(bool(np.isfinite(v[:,0]).any()) for v,_ in days.values())),
             "observed_minutes":sum(int(np.isfinite(v[:,0]).sum()) for v,_ in days.values()),
             "training_supported":key in self.keys}
             for key,days in sorted(groups.items())}

    def features(self,day,spot):
        block=np.full((MINUTES,len(self.names)),np.nan,np.float32)
        observed=np.zeros(MINUTES,bool)
        table={};conflicts=set();stamps=[r._stamp(day,j) for j in range(MINUTES)]
        for i,key in enumerate(self.keys):
            item=self.groups[key].get(day)
            if item is None:continue
            raw,_=item;valid=np.isfinite(raw[:,:5]).all(axis=1)&np.isfinite(spot)&(spot>0)
            observed|=valid
            col=len(m.f.OPTION_NAMES)+i*len(OPTION_FIELDS)
            x=np.full((MINUTES,len(OPTION_FIELDS)),np.nan,np.float32)
            x[valid,0]=100*(raw[valid,0]/spot[valid]-1)
            x[valid,1:5]=100*raw[valid,1:5]/spot[valid,None]
            for j,k in ((5,5),(6,6)):
                good=valid&np.isfinite(raw[:,k])&(raw[:,k]>=0)
                x[good,j]=np.log1p(raw[good,k])/10
            x[valid,7]=raw[valid,7]
            same=valid[5:]&valid[:-5]&(raw[5:,0]==raw[:-5,0])
            at=np.flatnonzero(same)+5
            x[at,8]=100*(raw[at,4]/raw[at-5,4]-1)
            good=at[np.isfinite(raw[at,6])&np.isfinite(raw[at-5,6])&(raw[at-5,6]>0)]
            x[good,9]=100*(raw[good,6]/raw[good-5,6]-1)
            block[:,col:col+len(OPTION_FIELDS)]=x
            # Preserve the earlier near-month aggregate features too.
            # Separate rolling slots remain distinct; conflicting same-strike
            # observations are not used for pooled near-month aggregates.
            if key[:2]!=("MONTH",1):continue
            for j in np.flatnonzero(valid):
                strike=float(raw[j,0]);side=key[2];pair=(side,strike);stamp=stamps[j]
                id_=(j,pair)
                if id_ in conflicts:continue
                values={name:float(raw[j,k]) if np.isfinite(raw[j,k]) else None
                        for k,name in enumerate(OPTION_RAW)}
                row={**values,"side":side,"session_ist":day,"expiry_flag":"MONTH","expiry_code":1}
                now=table.setdefault(stamp,{})
                old=now.get(pair)
                if old is not None:
                    if any(abs(old[k]-row[k])>.011 for k in ("open","high","low","close")) or old["volume"]!=row["volume"]:
                        now.pop(pair,None);conflicts.add(id_);continue
                    for k in ("oi","iv"):
                        if old[k]!=row[k]:old[k]=None
                else:now[pair]=row
        for j in np.flatnonzero(observed):
            block[j,:len(m.f.OPTION_NAMES)]=m.f.option_at(table,day,int(j),float(spot[j]))
        return block,observed


def load_options(index,training,progress=None):
    """Read each saved rolling receipt once; all canonical family/offset groups.

    Do not impose the prior 100k-stamp or ATM +/-3 benchmark restriction.
    Conflict within a family/offset/minute masks the observation.
    """
    root=service.DATA/"dhan_expired_options"
    evidence={"source_hashes":{},"rejected":{},"ignored":Counter(),"verified_receipts":0,
              "conflicted_slot_minutes":0,"raw_bytes":0,"input_bytes":0}
    groups={}
    if not root.exists():return RollingArchive(groups,set(training),evidence)
    if root.is_symlink() or not root.is_dir():raise ValueError("Unsafe rolling option archive")
    files=sorted(p for p in root.iterdir() if re.fullmatch(r"[a-f0-9]{64}\.json",p.name))
    if len(files)>sync.MAX_RECEIPTS:raise ValueError("Rolling option receipt count exceeds bound")
    for i,path in enumerate(files):
        if progress and (i%200==0 or i+1==len(files)):progress(f"Verifying all rolling receipts {i+1}/{len(files)}")
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size>exp.MAX_RESPONSE_BYTES+5000:
                raise ValueError("Unsafe or oversized original receipt")
            evidence["input_bytes"]+=path.stat().st_size
            if evidence["input_bytes"]>MAX_OPTION_INPUT_BYTES:raise RuntimeError("Rolling option input exceeds 12 GiB audit bound")
            envelope=json.loads(path.read_text(encoding="utf-8"));body=envelope["request"]
            if envelope.get("source")!=sync.SOURCE:
                evidence["ignored"]["nonrolling_source"]+=1;continue
            flag=body["expiryFlag"];code=body["expiryCode"];side=body["drvOptionType"];offset=body["strike"]
            if flag not in ("MONTH","WEEK") or type(code) is not int or code not in (1,2,3) or side not in ("CALL","PUT") or offset not in exp._offsets(sync.MAX_NEAR_WINGS):
                evidence["ignored"]["unsupported_rolling_family"]+=1;continue
            left=date.fromisoformat(body["fromDate"]);right=date.fromisoformat(body["toDate"])
            if body!=exp._request_body(left,right,flag,code-1,offset,side) or path!=exp._cache_path(body):
                raise ValueError("Noncanonical rolling receipt identity")
            payload=envelope["payload"]
            digest=sha256(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).hexdigest()
            if digest!=envelope["sha256"]:raise ValueError("Rolling receipt checksum mismatch")
            evidence["source_hashes"][path.stem]=digest;evidence["verified_receipts"]+=1
            key=(flag,code,side,offset);group=groups.setdefault(key,{})
            for row in exp._normalize(payload,body):
                day=row["session_ist"]
                if day not in index:continue
                clock=datetime.fromisoformat(row["timestamp_utc"]).astimezone(h.IST)
                minute=clock.hour*60+clock.minute-555
                if not 0<=minute<MINUTES or clock.second or clock.microsecond:continue
                if day not in group:
                    raw=np.full((MINUTES,len(OPTION_RAW)),np.nan);conflict=np.zeros(MINUTES,bool)
                    evidence["raw_bytes"]+=raw.nbytes+conflict.nbytes
                    if evidence["raw_bytes"]>MAX_OPTION_RAW_BYTES:raise RuntimeError("Rolling slot grid exceeds 2 GiB audit bound")
                    group[day]=(raw,conflict)
                raw,conflict=group[day]
                if conflict[minute]:continue
                value=np.asarray([row.get(k,np.nan) if row.get(k) is not None else np.nan for k in OPTION_RAW],float)
                old=raw[minute]
                if np.isfinite(old[0]):
                    if old[0]!=value[0] or np.any(np.abs(old[1:5]-value[1:5])>.011) or (
                            np.isfinite(old[5]) and np.isfinite(value[5]) and old[5]!=value[5]):
                        raw[minute]=np.nan;conflict[minute]=True;evidence["conflicted_slot_minutes"]+=1;continue
                    for j in (5,6,7):
                        if not (np.isfinite(old[j]) and np.isfinite(value[j]) and old[j]==value[j]):old[j]=np.nan
                else:raw[minute]=value
        except (ValueError,OSError,KeyError,TypeError,OverflowError,AttributeError) as exc:
            evidence["rejected"][path.stem]=str(exc)[:160]
    evidence["ignored"]=dict(evidence["ignored"])
    return RollingArchive(groups,set(training),evidence)


class GlobalArchive:
    def __init__(self,timelines,overnight,evidence):
        self.timelines=timelines;self.overnight=overnight;self.evidence=evidence
        self.names=GLOBAL_NAMES;self.overnight_names=OVERNIGHT_NAMES
        self.receipts=set()

    def features(self,day,minutes):
        block=np.full((MINUTES,len(self.names)),np.nan,np.float32)
        known=np.zeros(MINUTES,bool)
        start=datetime.combine(date.fromisoformat(day),time(9,15),h.IST)
        if self.timelines:
            for minute in minutes:
                cutoff=start+timedelta(minutes=int(minute)+1)
                values,details,_=market_context.factor_at(self.timelines,cutoff)
                v=np.asarray(values,float).reshape(-1,4)
                supported=v[:,3]==0
                x=v[:,:3].copy()
                x[~supported]=np.nan
                block[minute]=x.ravel();known[minute]=supported.any()
                for detail in details.values():
                    if detail.get("state")=="available":
                        self.receipts.update((detail["receipt_sha256"],detail["prior_receipt_sha256"]))
        nv=self.overnight.get(day,np.full(len(self.overnight_names),np.nan))
        return block,known,nv,bool(np.isfinite(nv[::4]).any() or np.isfinite(nv[1::4]).any())


def load_global(start,stop,dates,progress=None):
    path=shared_market_data.database_path()
    evidence={"state":"database_missing","overnight_asof":{}}
    if not path.is_file():return GlobalArchive({}, {},evidence)
    with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=3)) as db:
        db.execute("PRAGMA query_only=ON")
        timelines,meta=market_context.load_timelines(db,datetime.combine(start,time.min,h.IST),
                         datetime.combine(stop,time.min,h.IST),"archive")
        evidence.update(state="archive_asof_completed_minute",daily_and_intraday=meta,
                        timeline_factors=sorted(timelines))
        overnight={}
        for i,day in enumerate(dates):
            if progress and (i%200==0 or i+1==len(dates)):progress(f"Loading preopen ETF context {i+1}/{len(dates)}")
            cutoff=datetime.combine(date.fromisoformat(day),time(9,10),h.IST)
            rows=alpaca_overnight.features(db,date.fromisoformat(day),cutoff,mode="archive")
            nv=[]
            for key in alpaca_overnight.SYMBOLS:
                row=rows[key];present=row["state"]=="observed_proxy"
                nv.extend([row.get(k) if present and row.get(k) is not None else np.nan
                           for k in ("session_return_bps","trailing_30m_bps","coverage_ratio","age_minutes")])
            overnight[day]=np.asarray(nv,np.float32)
            evidence["overnight_asof"][day]=rows
    return GlobalArchive(timelines,overnight,evidence)


def batches(rows,n=2048):
    for i in range(0,len(rows),n):yield rows[i:i+n]


def stats(get,rows):
    """Streaming train-only per-column scaling; retain short-history columns."""
    total=counts=squares=None
    for part in batches(rows):
        x=get(part).astype(float);valid=np.isfinite(x);clean=np.where(valid,x,0.)
        if total is None:
            total=np.zeros(x.shape[1]);counts=np.zeros(x.shape[1],dtype=np.int64);squares=np.zeros(x.shape[1])
        total+=clean.sum(axis=0);counts+=valid.sum(axis=0);squares+=(clean*clean).sum(axis=0)
    if counts is None:raise ValueError("Empty training rows")
    mean=np.divide(total,counts,out=np.zeros_like(total),where=counts>0)
    var=np.maximum(np.divide(squares,counts,out=np.zeros_like(total),where=counts>0)-mean*mean,0)
    return {"keep":counts>0,"mean":mean.astype(np.float32),"std":np.maximum(np.sqrt(var),1e-6).astype(np.float32)}


def scaled(get,rows,fit):
    x=get(rows)[:,fit["keep"]]
    ok=np.isfinite(x)
    value=np.where(ok,np.clip((x-fit["mean"][fit["keep"]])/fit["std"][fit["keep"]],-10,10),0.)
    return np.column_stack((value,ok.astype(np.float32))).astype(np.float32)


def shuffled_sessions(rows,day_index,rng):
    """All rows once, randomized sessions but disk-local access within each."""
    days=day_index[rows]
    unique,first=np.unique(days,return_index=True)
    if np.any(np.diff(days)<0):raise ValueError("Training rows must be chronological before shuffling")
    groups=np.split(rows,first[1:])
    return np.concatenate([groups[i] for i in rng.permutation(len(unique))])


def streaming_snapshot(get,tr,va,te,y,days,day_index,fit,*,seed=42,stable=False):
    """Fixed regularized logistic SGD baseline, bounded memory, every row."""
    model=SGDClassifier(loss="log_loss",alpha=.0001,average=True,random_state=seed,
                        **({"learning_rate":"constant","eta0":.0001} if stable else {}))
    rng=np.random.default_rng(seed)
    weights=np.zeros(len(days),np.float32);weights[tr]=m.day_weights(days[tr])
    with threadpool_limits(limits=2):
        for _ in range(3):
            order=shuffled_sessions(tr,day_index,rng)
            for part in batches(order):
                model.partial_fit(scaled(get,part,fit),y[part],classes=np.arange(3),sample_weight=weights[part])
        def predict(rows):
            return np.concatenate([model.predict_proba(scaled(get,p,fit)) for p in batches(rows)])
        return predict(va),predict(te)
