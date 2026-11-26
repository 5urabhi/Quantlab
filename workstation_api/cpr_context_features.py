"""Causal optional constituent/global inputs for historical CPR research.

Retrospective minute receipts are not prospective packet evidence. External
archive mode trusts reviewed availability; receipt mode enforces import time.
Neither path calls a provider or synthesizes missing factors.
"""
from collections import Counter
from contextlib import closing
from datetime import date, datetime, timedelta
import csv
import math
import sqlite3

from . import historical_alpha as h, banknifty_constituents as bank
from . import market_context as m, constituent_alpha as a, shared_market_data

SCOPES=("technical","constituents","global","combined")
FACTORS=tuple(k for k,spec in m.FACTORS.items() if spec[1]!="participants")
PARTICIPANTS=("FII_CASH_NET_CR","DII_CASH_NET_CR","FII_INDEX_FUT_NET","CLIENT_INDEX_FUT_NET")
FACTORS+=PARTICIPANTS
BANK_NAMES=("breadth_5m","mean_5m","dispersion_5m","mean_15m","signed_relative_volume",
            "volume_coverage","weighted_5m","weighted_breadth_5m","verified_weights_missing",
            "hdfcbank_5m","hdfcbank_missing","icicibank_5m","icicibank_missing","sbin_5m","sbin_missing")
GLOBAL_NAMES=tuple(v for k in FACTORS for v in (k+"_level",k+"_change",k+"_age",k+"_missing"))


def _auto_batch(start,stop):
    # Choose only from manifest date coverage, never model outcomes.
    items=[]
    for b in h.batches():
        try:
            left,right=map(date.fromisoformat,(b["from_date"],b["to_date"]))
            overlap=(min(stop,right)-max(start,left)).days
            if overlap>0:
                items.append((overlap,int(b["status"]=="complete"),b["id"]))
        except (TypeError,ValueError,KeyError):
            continue
    return max(items)[2] if items else None


def _load_banks(start,stop,batch_id):
    meta={"batch_id":None,"source_hashes":{},"failures":{},"membership_sha256":None}
    if batch_id=="auto":
        batch_id=_auto_batch(start,stop)
    if not batch_id:
        meta["state"]="no_dated_membership_batch"
        return {},[],None,None,meta
    meta["batch_id"]=batch_id
    try:
        raw,left,right,intervals,resolved=h._batch(batch_id)
    except (ValueError,KeyError,TypeError,OSError) as exc:
        meta["state"]="invalid_dated_membership_batch"
        meta["failures"]["batch"]=type(exc).__name__
        return {},[],None,None,meta
    meta["membership_sha256"]=raw["historical_index"]["intervals_sha256"]
    meta["state"]="loaded"
    # Respect the manifest range and its pinned membership coverage boundary.
    through=raw["historical_index"].get("covered_through")
    if isinstance(through,str):
        right=min(right,date.fromisoformat(through)+timedelta(days=1))
    stocks={};budget=[h.MAX_TOTAL]
    for symbol,identity in sorted(resolved.items()):
        try:
            sig=h.pq._source_signature(identity)
            if not sig:
                raise ValueError("missing original receipt")
            file,_=h.pq._raw(identity)
            digest=sig["source_sha256"]
            stocks[symbol]=h._read_file(file,digest,max(left,start-timedelta(days=35)),
                                        min(stop,right),budget)
            meta["source_hashes"][symbol]=digest
        except (ValueError,OSError,TypeError,KeyError,OverflowError,csv.Error) as exc:
            meta["failures"][symbol]=type(exc).__name__
    return stocks,intervals,left,right,meta


def _bank_vector(signal,stocks,intervals,prior_dates,weights):
    day=signal["session"];minute=signal["minute"]
    members=h._member_set(intervals,day)
    if not members or minute<15:
        return None,{"state":"missing_membership_or_warmup"}
    direction=1 if signal["side"]=="CALL" else -1
    returns={};longer={};vols={}
    for symbol in members:
        series=stocks.get(symbol,{}).get(day,{})
        if any(k not in series for k in range(minute-15,minute+1)):
            continue
        current=series[minute][3]
        if min(current,series[minute-5][3],series[minute-15][3])<=0:
            continue
        returns[symbol]=direction*10000*(current/series[minute-5][3]-1)
        longer[symbol]=direction*10000*(current/series[minute-15][3]-1)
        past=stocks[symbol]
        base=[sum(past[d][k][4] for k in range(minute-4,minute+1))
              for d in prior_dates[-20:] if d in past and all(k in past[d] for k in range(minute-4,minute+1))]
        if len(base)>=5:
            from statistics import median
            denom=median(base)
            if denom>0:
                relative=min(5.,sum(series[k][4] for k in range(minute-4,minute+1))/denom)
                vols[symbol]=relative*(1 if returns[symbol]>0 else -1 if returns[symbol]<0 else 0)
    detail={"state":"missing_constituent_bars","members":len(members),"matched":len(returns)}
    if set(returns)!=set(members):
        return None,detail
    n=len(members);mean=sum(returns.values())/n
    breadth=sum(1 if v>0 else -1 if v<0 else 0 for v in returns.values())/n
    dispersion=math.sqrt(sum((v-mean)**2 for v in returns.values())/n)
    weight_map=weights.get("weights_pct") if weights else None
    weighted_ok=bool(weight_map and set(weight_map)==set(members))
    weighted=sum(weight_map[s]*returns[s] for s in members)/sum(weight_map.values()) if weighted_ok else 0.
    weighted_breadth=sum(weight_map[s]*(1 if returns[s]>0 else -1 if returns[s]<0 else 0) for s in members)/sum(weight_map.values()) if weighted_ok else 0.
    values=[breadth,mean,dispersion,sum(longer.values())/n,
            sum(vols.values())/len(vols) if vols else 0.,len(vols)/n,
            weighted,weighted_breadth,float(not weighted_ok)]
    for s in ("HDFCBANK","ICICIBANK","SBIN"):
        values.extend((returns.get(s,0.),float(s not in returns)))
    detail.update(state="available",relative_volume_members=len(vols),weight_mode="verified" if weighted_ok else "unweighted",
                  weight_sha256=weights.get("source_csv_sha256") if weighted_ok else None,
                  member_symbols=members)
    return values,detail


def _global_vector(timelines,signal):
    cutoff=m._stamp(signal["decision_utc"])
    vector,details,ok=m.factor_at(timelines,cutoff)
    offsets={k:i*4 for i,k in enumerate(m.FACTORS)}
    values=[v for k in FACTORS for v in vector[offsets[k]:offsets[k]+4]]
    # Explicit missing indicator per factor; no fabricated prices. Require
    # at least one fresh factor from each of global equity, Asia and macro.
    available={k:details[k] for k in FACTORS if details[k]["state"]=="available"}
    return (values if ok else None),{"state":"available" if ok else "missing_global_groups",
                                    "factors":available}


def attach(signals,*,mode="receipt",batch_id="auto"):
    if mode not in ("receipt","archive","off"):
        raise ValueError("Invalid CPR context availability mode")
    if mode=="off" or not signals:
        return {"state":"disabled" if mode=="off" else "no_signals","mode":mode,"anchors":{}}
    unique={(s["session"],s["minute"],s["side"]):s for s in signals}
    dates=sorted({s["session"] for s in unique.values()})
    start=date.fromisoformat(dates[0]);stop=date.fromisoformat(dates[-1])+timedelta(days=1)
    stocks,intervals,left,right,bank_meta=_load_banks(start,stop,batch_id)
    timelines={};global_meta={"rows":0,"ambiguous_factors":[],"state":"no_context_database"}
    if shared_market_data.database_path().is_file():
        try:
            with closing(a._read()) as db:
                timelines,global_meta=m.load_timelines(db,m._stamp(dates[0]+"T00:00:00+00:00"),
                             m._stamp(dates[-1]+"T23:59:59+00:00"),mode)
                global_meta["state"]="loaded"
        except (OSError,ValueError,sqlite3.Error) as exc:
            global_meta["state"]="context_source_unavailable"
            global_meta["error"]=type(exc).__name__
    stock_dates=sorted({d for series in stocks.values() for d in series})
    weights={};audit={};coverage=Counter();factor_coverage=Counter();factor_hashes=set()
    for key,s in sorted(unique.items()):
        day,minute,side=key
        bvec=None;bdetail={"state":"outside_membership_batch"}
        if left is not None and left<=date.fromisoformat(day)<right:
            if day not in weights:
                members=h._member_set(intervals,day)
                cutoff=datetime.combine(date.fromisoformat(day),datetime.min.time(),h.IST)+timedelta(minutes=555)
                weights[day]=bank._weights_for(date.fromisoformat(day),cutoff,members) if members else None
            bvec,bdetail=_bank_vector(s,stocks,intervals,[d for d in stock_dates if d<day],weights[day])
        gvec,gdetail=_global_vector(timelines,s)
        vectors={}
        if bvec is not None:
            vectors["constituents"]=bvec
            coverage["constituents"]+=1
        if gvec is not None:
            vectors["global"]=gvec
            coverage["global"]+=1
        if bvec is not None and gvec is not None:
            coverage["combined"]+=1
        for k,v in gdetail["factors"].items():
            factor_coverage[k]+=1
            factor_hashes.update((v["receipt_sha256"],v["prior_receipt_sha256"]))
        record={"vectors":vectors,"constituents":bdetail,"global":gdetail}
        audit["|".join(map(str,key))]=record
    # Update all signal copies, not just the deduplicated objects.
    for s in signals:
        key="|".join(map(str,(s["session"],s["minute"],s["side"])))
        s["context_vectors"]=audit[key]["vectors"]
    return {"state":"audited","mode":mode,"unique_anchors":len(unique),"coverage":dict(coverage),
            "factor_coverage":dict(factor_coverage),"factor_receipt_sha256":sorted(factor_hashes),
            "bank_sources":bank_meta,"global_sources":global_meta,"anchors":audit,
            "bank_feature_names":BANK_NAMES,"global_feature_names":GLOBAL_NAMES,
            "warning":"Unweighted breadth is not index attribution. Verified weights require an earlier dated receipt. "
                      "Archive mode trusts reviewed availability; absent groups are not filled. No causal market influence is established."}


def view(episodes,scope):
    groups={"technical":(),"constituents":("constituents",),"global":("global",),
            "combined":("constituents","global")}[scope]
    out=[]
    for e in episodes:
        vectors=e.get("context_vectors",{})
        if any(g not in vectors for g in groups):
            continue
        out.append({**e,"features":e["features"]+[x for g in groups for x in vectors[g]]}
                   if "features" in e else e)
    return out
