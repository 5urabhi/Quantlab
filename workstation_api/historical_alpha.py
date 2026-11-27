"""Read-only retrospective alpha research, separate from the prospective ledger.

Historical candles are latest retrieved observations, not proof of live
availability. Dated reconstructed memberships are pinned to a Dhan batch.
Unweighted bank statistics are never passed off as index contributions.
"""
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo
import csv
import io
import json
import math
import re

import numpy as np
from . import constituent_alpha as a, cockpit_sources, intraday_parquet as pq
from . import dhan_workspace as dw, banknifty_constituents as bank, service, nse_session_policy as sessions

VERSION="historical_minute_alpha_v3"
IST=ZoneInfo("Asia/Kolkata")
HORIZONS=(5,10,15,30,60,0)
MAX_DAYS=240
MAX_INSTRUMENTS=60
MAX_FILE=160*1024*1024
MAX_TOTAL=900*1024*1024
POLICY={"version":VERSION,"horizons":HORIZONS,"splits":[30,10,20],"session_close_splits":[60,20,40],
        "sampling":"first 60 observed completed index dates (120 for session-close); reserve predetermined windows before source or label gates; no substitutions",
        "weight_modes":["unweighted","verified_weights"],
        "target":"close of completed decision bar to close of future bar; 0 = fixed 15:29 index comparison bar, not official settlement",
        "source":"pinned Dhan batch membership and newest verified shared original index minute receipts",
        "features":"index returns 5/15/30m, realized volatility, EMA gap, RSI, time, EWMA volatility, rolling ADX-like proxy, causal CUSUM, opening range; constituent returns, breadth, dispersion and past-only relative volume",
        "advanced_models":"training-only 3-state GMM and diagonal Gaussian HMM; forward-only held-out filter; optional LightGBM/XGBoost; same matched chronological windows"}
POLICY_HASH=sha256(json.dumps(POLICY,sort_keys=True).encode()).hexdigest()


def _batch(batch_id, *, study_start=None, study_stop=None):
    raw=dw._load_batch(batch_id)
    if raw.get("selection")!="banknifty_pit" or raw.get("interval")!=1:
        raise ValueError("Select a BANKNIFTY dated-membership one-minute batch")
    start,stop=map(date.fromisoformat,(raw["from_date"],raw["to_date"]))
    local=datetime.now(IST)
    max_stop=local.date()+timedelta(days=int(local.hour>=16))
    if study_start is None and study_stop is None:
        if not 0<(stop-start).days<=MAX_DAYS or stop>max_stop:
            raise ValueError("Use a completed historical range up to 240 calendar days, end exclusive")
    else:
        if type(study_start) is not date or type(study_stop) is not date or not 0<(study_stop-study_start).days<=MAX_DAYS or study_stop>max_stop or start>=stop:
            raise ValueError("Invalid bounded historical study slice")
        start,stop=max(start,study_start),min(stop,study_stop)
        if start>=stop:
            raise ValueError("No overlap with requested study slice")
    info=raw.get("historical_index",{})
    intervals=info.get("intervals",[])
    payload=json.dumps(intervals,sort_keys=True,separators=(",",":")).encode()
    if not intervals or sha256(payload).hexdigest()!=info.get("intervals_sha256"):
        raise ValueError("Pinned historical membership missing or hash mismatch")
    items=raw.get("items",[])
    if study_start is not None:
        # The pinned membership hash above covers the entire original payload.
        # Restrict the actual study to relevant dated membership, not today's universe.
        needed={r["symbol"] for r in intervals if r["valid_from"]<stop.isoformat()
                and (not r["valid_to"] or r["valid_to"]>start.isoformat())}
        if not needed or len(needed)>MAX_INSTRUMENTS:
            raise ValueError("Study slice has missing or oversized membership")
        items=[x for x in items if x.get("pit_symbol") in needed]
    if not 1<=len(items)<=MAX_INSTRUMENTS:
        raise ValueError("Historical universe outside bounded study")
    resolved={}
    for x in items:
        symbol=x.get("pit_symbol");identity=x.get("id")
        if not isinstance(symbol,str) or not isinstance(identity,str) or not bank.IDENTITY.fullmatch(identity) or symbol in resolved or identity in resolved.values():
            raise ValueError("Ambiguous historical security mapping")
        resolved[symbol]=identity
    return raw,start,stop,intervals,resolved


def batches():
    return [b for b in dw.list_batches() if b.get("selection")=="banknifty_pit" and b.get("interval")==1]


def _member_set(intervals,day):
    active=[r["symbol"] for r in intervals if r["valid_from"]<=day and (not r["valid_to"] or day<r["valid_to"])]
    if not active or len(active)!=len(set(active)) or len(active)>MAX_INSTRUMENTS:
        return []
    return sorted(active)


def _read_file(path,digest,start,stop,budget,expected_rows=None):
    if not path.is_file() or path.is_symlink():
        raise ValueError("Original minute file unavailable")
    size=path.stat().st_size
    if not 0<size<=MAX_FILE or size>budget[0]:
        raise ValueError("Original minute source exceeds bounded read")
    with path.open("rb") as f:
        raw=f.read(MAX_FILE+1)
    budget[0]-=len(raw)
    if len(raw)!=size or sha256(raw).hexdigest()!=digest:
        raise ValueError("Original minute file checksum mismatch")
    data=defaultdict(dict)
    previous="";count=0
    reader=csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    for row in reader:
        stamp,day,o,h,l,c,v=pq._decode(row)
        if stamp<=previous:
            raise ValueError("Original minute timestamps not strictly ordered")
        previous=stamp;count+=1
        if count>pq.MAX_ROWS:
            raise ValueError("Original row cap exceeded")
        if not start<=date.fromisoformat(day)<stop:
            continue
        t=a._stamp(stamp)
        local=t.astimezone(IST)
        minute=local.hour*60+local.minute-555
        if local.second or local.microsecond or not 0<=minute<375:
            continue
        data[day][minute]=(o,h,l,c,v)
    if expected_rows is not None and count!=expected_rows:
        raise ValueError("Original index row count mismatch")
    return data


def shared_index_sources(start,stop,budget,*,identity="INDEX:BANKNIFTY"):
    """Union original verified spot receipts; newest verified minute wins.
    No extra market download or reconstructed index is required by a batch.
    """
    candidates=[]
    for path,_,meta in cockpit_sources._candidates(identity):
        try:
            if date.fromisoformat(meta["to_exclusive"])<=start or date.fromisoformat(meta["from_inclusive"])>=stop:
                continue
            received=a._stamp(meta["retrieved_utc"])
            candidates.append((path,meta,received))
        except (ValueError,KeyError,TypeError):
            continue
    candidates.sort(key=lambda x:(x[2],str(x[0])),reverse=True)
    if len(candidates)>512:
        raise ValueError("Too many original index receipts for bounded study")
    index=defaultdict(dict);digests={};failures={}
    for path,meta,received in candidates:
        try:
            rows=_read_file(path,meta["sha256"],start,stop,budget,meta["row_count"])
            # Match the source baseline's conservative completed-bar rule.
            latest=(received-timedelta(minutes=1)).astimezone(IST)
            used=False
            for day,minutes in rows.items():
                session=datetime.combine(date.fromisoformat(day),datetime.min.time(),IST)+timedelta(minutes=555)
                for minute,bar in minutes.items():
                    if session+timedelta(minutes=minute)<latest and minute not in index[day]:
                        index[day][minute]=bar;used=True
            if used:
                digests[identity+":"+path.parent.name]=meta["sha256"]
        except (ValueError,OSError,KeyError,TypeError,OverflowError,csv.Error) as exc:
            failures[identity+":"+path.parent.name]=str(exc)[:160]
    index={day:bars for day,bars in index.items() if bars}
    if not index:
        raise ValueError("No usable original "+identity.removeprefix("INDEX:")+" minute receipts in selected date range")
    return index,digests,failures


def _sources(batch_id,raw,start,stop,resolved,progress):
    budget=[MAX_TOTAL]
    index,sources,failures=shared_index_sources(start,stop,budget)
    stocks={}
    for i,(symbol,identity) in enumerate(sorted(resolved.items())):
        if progress:
            progress(5+35*i/max(1,len(resolved)),"Verifying original minute candles: "+symbol)
        try:
            sig=pq._source_signature(identity)
            if not sig:
                raise ValueError("Original one-minute cache missing")
            file,_=pq._raw(identity)
            original=_read_file(file,sig["source_sha256"],start,stop,budget)
            stocks[symbol]={day:{m:bar for m,bar in bars.items() if m<sessions.cash_bank_minutes(day,identity,symbol)} for day,bars in original.items()}
            sources[identity]=sig["source_sha256"]
        except (ValueError,OSError,KeyError,TypeError,OverflowError) as exc:
            failures[symbol]=str(exc)[:160]
    return index,stocks,sources,failures


def _ema(values,span):
    current=values[0]
    for value in values[1:]:
        current+=(value-current)*2/(span+1)
    return float(current)


def _indicators(rows):
    close=np.asarray([r[3] for r in rows],dtype=float)
    ret=10000*(close[1:]/close[:-1]-1)
    delta=np.diff(close)[-14:]
    gain=np.mean(np.maximum(delta,0));loss=np.mean(np.maximum(-delta,0))
    rsi=100*gain/(gain+loss) if gain+loss else 50.
    variance=float(ret[0]**2)
    for r in ret[1:]:
        variance=.94*variance+.06*r*r
    # Wilder-style directional movement with finite trailing-window smoothing;
    # ADX is the mean of the last 14 directional-index values.
    hi=np.asarray([r[1] for r in rows]);lo=np.asarray([r[2] for r in rows])
    tr=np.maximum(hi[1:]-lo[1:],np.maximum(abs(hi[1:]-close[:-1]),abs(lo[1:]-close[:-1])))
    up=np.diff(hi);down=-np.diff(lo)
    plus=np.where((up>down)&(up>0),up,0.);minus=np.where((down>up)&(down>0),down,0.)
    dx=[]
    for j in range(14,len(tr)+1):
        total=float(np.sum(plus[j-14:j])+np.sum(minus[j-14:j]))
        dx.append(100*abs(float(np.sum(plus[j-14:j])-np.sum(minus[j-14:j])))/total if total else 0.)
    adx=float(np.mean(dx[-14:])) if dx else 0.
    r5,r15,r30=[10000*(close[-1]/close[-1-k]-1) for k in (5,15,30)]
    rv=float(np.std(ret[-30:],ddof=1))
    ema_gap=10000*(_ema(close,9)/_ema(close,21)-1)
    # Standardized return-shift CUSUM; baseline uses earlier returns only.
    baseline=float(np.mean(ret[:15]))
    sigma=max(1.,float(np.std(ret[:15],ddof=1)))
    upper=lower=0.
    for z in (ret[15:]-baseline)/sigma:
        upper=max(0.,upper+float(z)-.5)
        lower=max(0.,lower-float(z)-.5)
    return [r5,r15,r30,rv,ema_gap,float(rsi),math.sqrt(variance),adx,upper,lower]


def _call(direction):
    return "UP" if direction>0 else "DOWN" if direction<0 else "ABSTAIN"


def _sample_day(day,index,stocks,members,weights,horizon,prior_days):
    counts=Counter();out=[]
    # Fixed decision grid, independent of missing observations or results.
    anchors=[30] if horizon==0 else range(30,375-horizon,horizon+1)
    for minute in anchors:
        counts["reserved_nonoverlap"]+=1
        target=374 if horizon==0 else minute+horizon
        if any(k not in index for k in range(minute-30,minute+1)):
            counts["missing_index_features"]+=1;continue
        window=[index[k] for k in range(minute-30,minute+1)]
        x=_indicators(window)
        price=index[minute][3]
        if not members or weights is None or any(s not in stocks or any(k not in stocks[s].get(day,{}) for k in range(minute-5,minute+1)) for s in members):
            counts["missing_constituent_features"]+=1;continue
        rets=[];vfeatures=[];w=[]
        for s in members:
            series=stocks[s][day];r=10000*(series[minute][3]/series[minute-5][3]-1)
            w.append(weights[s]);rets.append(r)
            base=[sum(stocks[s][d][k][4] for k in range(minute-4,minute+1))
                  for d in prior_days[-20:] if d in stocks[s] and all(k in stocks[s][d] for k in range(minute-4,minute+1))]
            volume=sum(series[k][4] for k in range(minute-4,minute+1))
            vfeatures.append(float(np.sign(r)*min(3.,volume/np.median(base))) if len(base)>=5 and np.median(base)>0 else None)
        w=np.asarray(w,dtype=float);w=w/w.sum();rets=np.asarray(rets)
        mean=float(np.dot(w,rets));breadth=float(np.dot(w,np.sign(rets))*100)
        disp=float(np.sqrt(np.dot(w,(rets-mean)**2)))
        observed=[i for i,v in enumerate(vfeatures) if v is not None]
        covered=float(sum(w[i] for i in observed))
        signed_volume=float(sum(w[i]*vfeatures[i] for i in observed)/covered) if covered>=.8 else 0.
        volume_missing=float(covered<.8)
        opening=all(k in index for k in range(15))
        opening_hi=max(index[k][1] for k in range(15)) if opening else price
        opening_lo=min(index[k][2] for k in range(15)) if opening else price
        range_position=(price-opening_lo)/(opening_hi-opening_lo) if opening and opening_hi>opening_lo else .5
        index_features=x[:6]+[float(minute),x[6],x[7],float(range_position),float(not opening),x[8],x[9]]
        bank_features=[mean,breadth,disp,signed_volume,volume_missing]
        counts["matched_features"]+=1
        if target not in index:
            counts["missing_label"]+=1;continue
        r=10000*(index[target][3]/price-1)
        scale=max(1.,x[3]*math.sqrt(30))
        regime="trend_up" if x[2]>=scale else "trend_down" if x[2]<=-scale else "compression" if x[3]<=3 else "range"
        stamp=datetime.combine(date.fromisoformat(day),datetime.min.time(),IST)+timedelta(minutes=555+minute+1)
        pressure=_call(mean if abs(breadth)>=50 and mean*breadth>0 else 0)
        ema=_call(1 if x[4]>0 and 50<x[5]<75 else -1 if x[4]<0 and 25<x[5]<50 else 0)
        breakout=_call(1 if opening and price>opening_hi else -1 if opening and price<opening_lo else 0)
        pullback=_call(1 if regime=="trend_up" and x[0]<0<x[1] else -1 if regime=="trend_down" and x[0]>0>x[1] else 0)
        reversion=_call(-1 if regime=="range" and x[5]>70 else 1 if regime=="range" and x[5]<30 else 0)
        out.append({"session":day,"decision_utc":stamp.astimezone(timezone.utc).isoformat(),
                    "target_utc":(stamp+timedelta(minutes=target-minute)).astimezone(timezone.utc).isoformat(),
                    "reference_price":price,"return_bps":r,"class":1 if r>a.DEADBAND_BPS else -1 if r<-a.DEADBAND_BPS else 0,
                    "index":index_features,"full":index_features+bank_features,"regime":regime,
                    "ema_rsi":ema,"pressure":pressure,"volume_pressure":pressure if not volume_missing and signed_volume*mean>0 else "UNAVAILABLE" if volume_missing else "ABSTAIN",
                    "opening_breakout":breakout,"trend_pullback":pullback,"range_reversion":reversion})
        counts["scored"]+=1
    return out,dict(counts)


def run(*,batch_id,horizon=30,weight_mode="unweighted",progress=None):
    if horizon not in HORIZONS or weight_mode not in ("unweighted","verified_weights"):
        raise ValueError("Invalid historical research parameters")
    raw,start,stop,intervals,resolved=_batch(batch_id)
    if progress:progress(1,"Inspecting pinned membership and original batch")
    index,stocks,sources,failures=_sources(batch_id,raw,start,stop,resolved,progress)
    # A session-close label has only one independent window per day.
    multiplier=2 if horizon==0 else 1
    required=a.REQUIRED*multiplier
    ntrain=a.TRAIN*multiplier;ncal=a.CALIBRATION*multiplier
    dates=sorted(index)[:required]
    split=[dates[:ntrain],dates[ntrain:ntrain+ncal],dates[ntrain+ncal:]]
    samples=[];audit=[];counts=Counter()
    for i,day in enumerate(dates):
        if progress:progress(42+17*i/max(1,len(dates)),"Auditing matched historical windows: "+day)
        members=_member_set(intervals,day)
        weights={s:1. for s in members} if members else None
        weight_digest=None
        if weight_mode=="verified_weights":
            cutoff=datetime.combine(date.fromisoformat(day),datetime.min.time(),IST)+timedelta(minutes=555)
            record=bank._weights_for(date.fromisoformat(day),cutoff,members)
            weights=record["weights_pct"] if record else None
            weight_digest=record.get("source_csv_sha256") if record else None
        rows,c=_sample_day(day,index[day],stocks,members,weights,horizon,dates[:i])
        samples.extend(rows);counts.update(c)
        audit.append({"day":day,"index_bars":len(index[day]),"members":len(members),
                      "member_files":sum(s in stocks and day in stocks[s] for s in members),
                      "weight_sha256":weight_digest,**c})
    train,cal,test=([r for r in samples if r["session"] in set(part)] for part in split)
    status={"version":VERSION,"policy_sha256":POLICY_HASH,"batch_id":batch_id,"weight_mode":weight_mode,
        "horizon_minutes":horizon,"recorded_sessions":len(dates),"required_sessions":required,
        "training_dates":split[0],"calibration_dates":split[1],"holdout_dates":split[2],
        "observed_index_dates":len(index),"source_hashes":sources,"source_failures":failures,
        "membership_sha256":raw["historical_index"]["intervals_sha256"],"evidence_counts":dict(counts),
        "session_audit":audit,"support":{"training":a.support(train),"calibration":a.support(cal),"holdout":a.support(test)},
        "methods":{},"regimes":{},"quantiles":None,"walk_forward":[],"run_id":None,
        "broker_orders_enabled":False,"live_model_promoted":False,
        "warning":"Retrospective latest-retrieved historical candles and reconstructed dated membership; not receipt-certified prospective predictions. "
        "Unweighted mode is a breadth/dispersion research feature, not official index weights or reconstructed index. Verified-weight mode requires dated weights actually recorded before the session. "
        "The split retains the first 60 observed index dates (120 for session-close research), not all exchange sessions. Missing windows are counted, not filled. "
        "Close-to-close returns and fixed 5 bps index cost are hypothetical prediction metrics, not executable index or option P&L."}
    if len(dates)<required:
        status["state"]="awaiting_recorded_sessions"
    elif not (a._supported(train,60,20,train=True) and a._supported(cal,20,7) and a._supported(test,40,12)):
        status["state"]="insufficient_matched_evidence"
    else:
        status["walk_forward"]=a._walk_forward(train,split[0],progress)
        methods,regimes,q,records=a._compare(train,cal,test,progress)
        from . import fitted_alpha
        extra,availability,extra_records=fitted_alpha.assess(train,cal,test,horizon,methods,progress)
        methods.update(extra);records.extend(extra_records)
        status.update(state="holdout_assessment_available",methods=methods,regimes=regimes,quantiles=q,
                      model_availability=availability,run_id=a._save(records),prediction_rows=len(records))
    records=[{"day":"RUN_SUMMARY","state":status["state"],"counts_json":json.dumps(dict(counts),sort_keys=True),
              "evidence_json":json.dumps({"batch_id":batch_id,"source_hashes":sources,"source_failures":failures,
                  "membership_sha256":status["membership_sha256"],"weight_mode":weight_mode,"horizon":horizon,"support":status["support"]},sort_keys=True),
              "policy_sha256":POLICY_HASH}]
    for row in audit:
        records.append({"day":row["day"],"state":"observed_index_session","counts_json":json.dumps(row,sort_keys=True),
                        "evidence_json":"","policy_sha256":POLICY_HASH})
    status["audit_id"]=a._save(records,audit=True)
    if progress:progress(100,"Historical evidence and model assessment saved")
    return status
