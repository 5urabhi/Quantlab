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
PANEL_SYMBOLS=("AXISBANK","HDFCBANK","ICICIBANK","KOTAKBANK","SBIN")
PANEL_SCOPES=("bank_panel","panel_global")
PATTERN_SCOPES=("patterns","global_patterns","panel_global_patterns","combined_patterns")
SCOPE_GROUPS={"technical":(),"constituents":("constituents",),"global":("global",),
              "combined":("constituents","global"),"bank_panel":("bank_panel",),
              "panel_global":("bank_panel","global"),"patterns":("patterns",),
              "global_patterns":("global","patterns"),
              "panel_global_patterns":("bank_panel","global","patterns"),
              "combined_patterns":("constituents","global","patterns")}
FACTORS=tuple(k for k,spec in m.FACTORS.items() if spec[1]!="participants")
PARTICIPANTS=("FII_CASH_NET_CR","DII_CASH_NET_CR","FII_INDEX_FUT_NET","CLIENT_INDEX_FUT_NET")
FACTORS+=PARTICIPANTS
BANK_NAMES=("breadth_5m","mean_5m","dispersion_5m","mean_15m","signed_relative_volume",
            "volume_coverage","weighted_5m","weighted_breadth_5m","verified_weights_missing",
            "hdfcbank_5m","hdfcbank_missing","icicibank_5m","icicibank_missing","sbin_5m","sbin_missing")
GLOBAL_NAMES=tuple(v for k in FACTORS for v in (k+"_level",k+"_change",k+"_age",k+"_missing"))


def _batch_candidates(start,stop):
    items=[]
    for b in h.batches():
        try:
            left,right=map(date.fromisoformat,(b["from_date"],b["to_date"]))
            overlap=(min(stop,right)-max(start,left)).days
            if overlap>0:
                items.append((overlap,int(b["status"]=="complete"),b["id"]))
        except (TypeError,ValueError,KeyError):
            continue
    return [x[2] for x in sorted(items,reverse=True)]


def _load_banks(start,stop,batch_id):
    meta={"batch_id":None,"source_hashes":{},"failures":{},"membership_sha256":None,
          "rejected_batches":{}}
    candidates=_batch_candidates(start,stop) if batch_id=="auto" else [batch_id]
    if not candidates:
        meta["state"]="no_dated_membership_batch"
        return {},[],None,None,meta
    # First valid candidate in date-overlap order; never select on model outcomes.
    for candidate in candidates:
        try:
            raw,left,right,intervals,resolved=h._batch(candidate,
                study_start=start-timedelta(days=35),study_stop=stop)
            through=date.fromisoformat(raw["historical_index"]["covered_through"])
            right=min(right,through+timedelta(days=1))
            if max(left,start)>=min(right,stop):
                raise ValueError("Pinned membership does not cover requested signals")
        except (ValueError,KeyError,TypeError,OSError,OverflowError) as exc:
            # Only local validation errors; never expose raw provider responses.
            known=("Select a BANKNIFTY","Invalid bounded historical","No overlap",
                   "Pinned historical membership","Study slice has missing",
                   "Historical universe outside","Ambiguous historical security",
                   "Pinned membership does not cover")
            detail=str(exc) if isinstance(exc,ValueError) and str(exc).startswith(known) else type(exc).__name__
            meta["rejected_batches"][candidate]=detail
            continue
        meta["batch_id"]=candidate
        break
    else:
        meta["state"]="invalid_dated_membership_batch"
        meta["failures"]["batch"]="No candidate passed manifest validation"
        return {},[],None,None,meta
    meta["membership_sha256"]=raw["historical_index"]["intervals_sha256"]
    meta["state"]="loaded"
    meta["study_from"]=left.isoformat()
    meta["study_to_exclusive"]=right.isoformat()
    meta["mapped_members"]=sorted(resolved)
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
            known=("missing original receipt","Original minute","One-minute","Unsafe original")
            meta["failures"][symbol]=str(exc) if isinstance(exc,ValueError) and str(exc).startswith(known) else type(exc).__name__
    return stocks,intervals,left,right,meta


def _load_fixed_panel(start,stop,batch_meta,*,enabled):
    """Fixed major-bank watchlist, NOT historical index membership.
    Resolve using the pinned earlier batch rather than today's index list.
    Read the same canonical Dhan files beyond that batch's membership window.
    """
    meta={"state":"disabled","symbols":PANEL_SYMBOLS,"source_hashes":{},"failures":{}}
    if not enabled:
        return {},[],meta
    if not batch_meta.get("batch_id"):
        meta["state"]="no_pinned_security_mapping"
        return {},[],meta
    try:
        raw=h.dw._load_batch(batch_meta["batch_id"])
        left=date.fromisoformat(raw["from_date"])
        covered=date.fromisoformat(raw["historical_index"]["covered_through"])
        if not left<=start<=covered or not set(PANEL_SYMBOLS)<=set(h._member_set(raw["historical_index"]["intervals"],start.isoformat())):
            raise ValueError("Fixed panel must be documented before the study starts")
        # _load_banks already validates this pinned membership and its hash;
        # validate exact mapping here too, independently of later outcomes.
        mapping={s:[v["id"] for v in raw["items"] if v.get("pit_symbol")==s] for s in PANEL_SYMBOLS}
        if any(len(v)!=1 or not bank.IDENTITY.fullmatch(v[0]) for v in mapping.values()) or len({v[0] for v in mapping.values()})!=len(PANEL_SYMBOLS):
            raise ValueError("Invalid fixed panel identity mapping")
    except (OSError,ValueError,KeyError,TypeError):
        meta["state"]="no_validated_panel_mapping";return {},[],meta
    meta.update(state="loaded",mapping_batch=batch_meta["batch_id"],selection_as_of=start.isoformat(),
                identities={s:v[0] for s,v in mapping.items()})
    stocks={};budget=[h.MAX_TOTAL]
    for s,ids in mapping.items():
        try:
            sig=h.pq._source_signature(ids[0])
            if not sig:
                raise ValueError("Missing original panel minute receipt")
            file,_=h.pq._raw(ids[0])
            stocks[s]=h._read_file(file,sig["source_sha256"],start-timedelta(days=35),stop,budget)
            meta["source_hashes"][s]=sig["source_sha256"]
        except (ValueError,OSError,KeyError,TypeError,OverflowError,csv.Error) as exc:
            meta["failures"][s]=type(exc).__name__
    # These intervals are the fixed panel research definition, NOT NSE data.
    intervals=[{"symbol":s,"valid_from":start.isoformat(),"valid_to":None} for s in PANEL_SYMBOLS]
    meta["observed_sessions_by_symbol"]={s:len(v) for s,v in stocks.items()}
    return stocks,intervals,meta


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
    detail={"state":"missing_constituent_bars","members":len(members),"matched":len(returns),
            "missing_members":sorted(set(members)-set(returns))}
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


def attach(signals,*,mode="receipt",batch_id="auto",fixed_panel=False):
    if mode not in ("receipt","archive","off"):
        raise ValueError("Invalid CPR context availability mode")
    if mode=="off" or not signals:
        return {"state":"disabled" if mode=="off" else "no_signals","mode":mode,"anchors":{}}
    unique={(s["session"],s["minute"],s["side"]):s for s in signals}
    dates=sorted({s["session"] for s in unique.values()})
    start=date.fromisoformat(dates[0]);stop=date.fromisoformat(dates[-1])+timedelta(days=1)
    stocks,intervals,left,right,bank_meta=_load_banks(start,stop,batch_id)
    panel,panel_intervals,panel_meta=_load_fixed_panel(start,stop,bank_meta,enabled=fixed_panel)
    panel_dates=sorted({d for series in panel.values() for d in series})
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
    bank_meta["observed_sessions_by_symbol"]={s:len(v) for s,v in stocks.items()}
    bank_meta["observed_session_count"]=len(stock_dates)
    weights={};audit={};coverage=Counter();factor_coverage=Counter();factor_hashes=set()
    bank_states=Counter();global_states=Counter();missing_members=Counter()
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
        bank_states[bdetail["state"]]+=1;global_states[gdetail["state"]]+=1
        missing_members.update(bdetail.get("missing_members",[]))
        vectors={}
        if bvec is not None:
            vectors["constituents"]=bvec
            coverage["constituents"]+=1
        if fixed_panel and panel_intervals:
            pv,pdetail=_bank_vector(s,panel,panel_intervals,[d for d in panel_dates if d<day],None)
            if pv is not None:
                vectors["bank_panel"]=pv
                coverage["bank_panel"]+=1
                if gvec is not None:
                    coverage["panel_global"]+=1
        else:
            pdetail={"state":"disabled_or_missing_panel"}
        if gvec is not None:
            vectors["global"]=gvec
            coverage["global"]+=1
        if bvec is not None and gvec is not None:
            coverage["combined"]+=1
        for k,v in gdetail["factors"].items():
            factor_coverage[k]+=1
            factor_hashes.update((v["receipt_sha256"],v["prior_receipt_sha256"]))
        record={"vectors":vectors,"constituents":bdetail,"global":gdetail,"bank_panel":pdetail}
        audit["|".join(map(str,key))]=record
    # Update all signal copies, not just the deduplicated objects.
    for s in signals:
        key="|".join(map(str,(s["session"],s["minute"],s["side"])))
        s["context_vectors"]=audit[key]["vectors"]
    return {"state":"audited","mode":mode,"unique_anchors":len(unique),"coverage":dict(coverage),
            "factor_coverage":dict(factor_coverage),"factor_receipt_sha256":sorted(factor_hashes),
            "bank_sources":bank_meta,"fixed_panel_sources":panel_meta,"global_sources":global_meta,"anchors":audit,
            "constituent_state_counts":dict(bank_states),"global_state_counts":dict(global_states),
            "missing_constituent_anchor_counts":dict(missing_members),
            "bank_feature_names":BANK_NAMES,"global_feature_names":GLOBAL_NAMES,
            "warning":"Unweighted breadth is not index attribution. Verified weights require an earlier dated receipt. "
                      "Archive mode trusts reviewed availability; absent groups are not filled. No causal market influence is established."}


def view(episodes,scope):
    groups=SCOPE_GROUPS[scope]
    out=[]
    for e in episodes:
        vectors=e.get("context_vectors",{})
        if any(g not in vectors for g in groups):
            continue
        out.append({**e,"features":e["features"]+[x for g in groups for x in vectors[g]]}
                   if "features" in e else e)
    return out


def rule_accept(episode,scope):
    """Fixed direction-confirmation hypotheses, never a fitted causal claim."""
    vectors=episode.get("context_vectors",{})
    groups=SCOPE_GROUPS[scope]
    if "constituents" in groups or "bank_panel" in groups:
        b=vectors.get("constituents" if "constituents" in groups else "bank_panel")
        if b is None or b[0]<1/3 or b[1]<=0 or b[3]<=0 or (not b[8] and b[6]<=0):
            return False
    if "global" in groups:
        g=vectors.get("global")
        if g is None:
            return False
        direction=1 if episode["side"]=="CALL" else -1
        for group in ("global_equity","asia"):
            changes=[direction*g[4*i+1] for i,k in enumerate(FACTORS)
                     if m.FACTORS[k][1]==group and m.FACTORS[k][0].endswith("return")
                     and not g[4*i+3]]
            if not changes or sum(changes)<=0:
                return False
    if "patterns" in groups:
        from . import candle_pattern_research as patterns
        if not patterns.accepts(episode):
            return False
    return True
