"""Small, read-only pre-open BANKNIFTY baseline benchmark.

No new provider requests, trading integration, database writes or RL.
One observation per Indian market date. All decisions are at 09:10 IST.
Compare three fixed regularized logistic regressions on identical
chronological dates. Retrospective source availability is assumed.
"""
import argparse
from collections import Counter
from contextlib import closing
from datetime import date, datetime, time, timedelta
import json
import math
from pathlib import Path
import sqlite3

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from workstation_api import historical_alpha as h, market_context as m
from workstation_api import alpaca_overnight as boats, global_market_archive as g
from workstation_api import service, shared_market_data, intraday_parquet as pq
from workstation_api import nse_session_policy as sessions

DAILY=("US_SPY_ETF_CLOSE","US_QQQ_ETF_CLOSE","US_KBE_ETF_CLOSE",
       "JAPAN_EWJ_ETF_CLOSE","CHINA_FXI_ETF_CLOSE","US_VIX_CLOSE",
       "USDINR_CLOSE","BRENT_CLOSE")
OVERNIGHT=("SPY","QQQ","EWY")
TARGETS=("gap","first15","first30")
COST_BPS=5.0
TRAIN_DATES=30
BLOCK=10
MIN_TRAIN=20
MIN_TEST=10
WARNING=("Exploratory, retrospective latest-retrieved Dhan candles and archive availability "
         "assumptions, not a live trading test. ETF proxies are not local cash markets. "
         "Observed index dates are not a certified exchange calendar. "
         "Hypothetical 5 bps index cost is not option execution P&L. No orders or promotion.")


def bps(price,anchor):
    if price<=0 or anchor<=0:
        raise ValueError("Invalid price")
    return 10000*(price/anchor-1)


def index_sample(previous,current):
    # Do not substitute adjacent bars for the required clock anchors.
    if not all(k in previous for k in (0,344,374)) or not all(k in current for k in range(30)):
        return None
    p=previous[374][3]
    opening=current[0][0]
    x=[bps(p,previous[0][0]),bps(p,previous[344][3])]
    y={"gap":bps(opening,p),"first15":bps(current[14][3],opening),
       "first30":bps(current[29][3],opening)}
    if not all(math.isfinite(v) for v in x+list(y.values())):
        return None
    return x,y


def constituent_sample(previous,stocks,members,resolved):
    """Prior-session unweighted breadth and mean return, never assumed weights."""
    values=[]
    for symbol in members:
        identity=resolved.get(symbol)
        if identity is None:
            continue
        end=sessions.cash_bank_minutes(previous,identity,symbol)-1
        series=stocks.get(symbol,{}).get(previous,{})
        if 0 in series and end in series:
            values.append(bps(series[end][3],series[0][0]))
    if not members or len(values)!=len(members):
        return None
    return [float(np.mean(values)),float(np.mean(np.sign(values))*100)]


def read_constituents(start,stop,budget,batch_id=None):
    """Use one best-overlap pinned batch; never extrapolate its membership."""
    candidates=h.batches()
    if batch_id:
        candidates=[x for x in candidates if x["id"]==batch_id]
    candidates=[x for x in candidates if x.get("from_date") and x.get("to_date") and
                x.get("membership_covered_through")]
    def overlap(x):
        left=max(start,date.fromisoformat(x["from_date"]))
        right=min(stop,date.fromisoformat(x["to_date"]),
                  date.fromisoformat(x["membership_covered_through"])+timedelta(days=1))
        return max(0,(right-left).days)
    candidates.sort(key=overlap,reverse=True)
    if not candidates or not overlap(candidates[0]):
        return None,{},[],{},None,None,{},{"membership":"no overlapping dated batch"}
    chosen=candidates[0]["id"]
    try:
        raw,left,right,intervals,resolved=h._batch(chosen,study_start=start,study_stop=stop)
        right=min(right,date.fromisoformat(raw["historical_index"]["covered_through"])+timedelta(days=1))
        if left>=right:
            raise ValueError("No documented membership overlap")
    except (ValueError,KeyError,OSError,TypeError) as exc:
        return chosen,{},[],{},None,None,{},{"membership":str(exc)[:160]}
    stocks={};hashes={};failures={}
    for symbol,identity in sorted(resolved.items()):
        try:
            sig=pq._source_signature(identity)
            if not sig:
                raise ValueError("No original minute receipt")
            path,_=pq._raw(identity)
            stocks[symbol]=h._read_file(path,sig["source_sha256"],left,right,budget)
            hashes[identity]=sig["source_sha256"]
        except (ValueError,OSError,KeyError,TypeError,OverflowError) as exc:
            failures[symbol]=str(exc)[:160]
    return chosen,stocks,intervals,resolved,left,right,hashes,failures


def features(db,timelines,day):
    cutoff=datetime.combine(date.fromisoformat(day),time(9,10),g.IST).astimezone(g.UTC)
    _,details,_=m.factor_at(timelines,cutoff)
    x=[];available=[]
    for factor in DAILY:
        d=details.get(factor,{})
        present=d.get("state")=="available"
        x.extend([float(d["change_feature"]) if present else 0.,float(not present)])
        if present:
            available.append(factor)
    overnight=boats.features(db,date.fromisoformat(day),cutoff,mode="archive")
    for symbol in OVERNIGHT:
        record=overnight[symbol]
        value=record["session_return_bps"]
        present=value is not None and record["state"]=="observed_proxy"
        x.extend([float(value) if present else 0.,float(not present)])
        if present:
            available.append("BOATS_"+symbol)
    return x,available


def summarize(predictions,target):
    if not predictions:
        return None
    y=np.asarray([r["actual_up"] for r in predictions],dtype=float)
    p=np.asarray([r["probability_up"] for r in predictions],dtype=float)
    r=np.asarray([r["return_bps"] for r in predictions],dtype=float)
    call=p>=.5
    clipped=np.clip(p,1e-8,1-1e-8)
    result={"n":len(y),"accuracy":float(np.mean(call==y)),
            "brier":float(np.mean((p-y)**2)),
            "log_loss":float(-np.mean(y*np.log(clipped)+(1-y)*np.log(1-clipped))),
            "actual_up_rate":float(np.mean(y)),"mean_predicted_up":float(np.mean(p)),
            "flat_returns":int(np.sum(r==0))}
    if target!="gap":
        signed=np.where(call,1.,-1.)*r
        result["hypothetical_index_gross_bps_per_trade"]=float(np.mean(signed))
        result["hypothetical_index_net_bps_per_trade_at_5bps"]=float(np.mean(signed-COST_BPS))
    return result


def evaluate(dates,rows,target):
    """Fixed expanding windows; reserve dates before checking observations.

    No random splitting, tuning, test-set threshold selection or reuse of
    same-day labels. Missing global values are zero plus explicit masks.
    Use the same eligible test dates across all four methods.
    """
    predictions={k:[] for k in ("prior_up_rate","domestic","global","combined")}
    blocks=[]
    for offset in range(TRAIN_DATES,len(dates),BLOCK):
        train=[rows[d] for d in dates[:offset] if d in rows]
        test=[rows[d] for d in dates[offset:offset+BLOCK] if d in rows]
        y=np.asarray([int(r["returns"][target]>0) for r in train])
        counts=Counter(y.tolist())
        record={"train_reserved":offset,"train_usable":len(train),
                "test_reserved":min(BLOCK,len(dates)-offset),"test_usable":len(test),
                "first_test_date":dates[offset],"last_test_date":dates[min(len(dates)-1,offset+BLOCK-1)]}
        if len(train)<MIN_TRAIN or min(counts.get(0,0),counts.get(1,0))<5 or not test:
            blocks.append({**record,"state":"insufficient_training_or_test"});continue
        probs={"prior_up_rate":np.full(len(test),float(np.mean(y)))}
        for key in ("domestic","global","combined"):
            # Fixed strong regularization; scalers fit on train only.
            model=make_pipeline(StandardScaler(),LogisticRegression(C=.1,max_iter=1000,random_state=0))
            model.fit([r[key] for r in train],y)
            probs[key]=model.predict_proba([r[key] for r in test])[:,1]
        for key,values in probs.items():
            for row,p in zip(test,values):
                actual=row["returns"][target]
                predictions[key].append({"date":row["date"],"actual_up":int(actual>0),
                    "return_bps":actual,"probability_up":float(p)})
        blocks.append({**record,"state":"evaluated"})
    metrics={k:summarize(v,target) for k,v in predictions.items()}
    enough=len(predictions["domestic"])>=MIN_TEST
    delta=None
    if enough:
        d,c=metrics["domestic"],metrics["combined"]
        delta={"accuracy":c["accuracy"]-d["accuracy"],"brier":c["brier"]-d["brier"],
               "log_loss":c["log_loss"]-d["log_loss"]}
    return {"state":"exploratory_comparison" if enough else "insufficient_held_out_dates",
            "metrics":metrics,"combined_minus_domestic":delta,"blocks":blocks,
            "predictions":predictions}


def run(start,stop,batch_id=None,*,index_only=False,progress=None):
    today=g._now().astimezone(g.IST).date()
    if not 0<(stop-start).days<=220 or stop>today:
        raise ValueError("Choose completed dates within a 220-calendar-day range")
    warm=start-timedelta(days=10)
    budget=[h.MAX_TOTAL]
    if progress:progress("Verifying existing BANKNIFTY minute receipts")
    index,hashes,failures=h.shared_index_sources(warm,stop,budget)
    if index_only:
        chosen,stocks,intervals,resolved,left,right,stock_hashes,stock_failures=(None,{},[],{},None,None,{},{"membership":"index-only requested"})
    else:
        if progress:progress("Verifying overlapping dated BANKNIFTY constituent receipts")
        chosen,stocks,intervals,resolved,left,right,stock_hashes,stock_failures=read_constituents(warm,stop,budget,batch_id)
    dates=sorted(d for d in index if start.isoformat()<=d<stop.isoformat())
    all_dates=sorted(index)
    rows={};counts=Counter();availability=Counter()
    path=shared_market_data.database_path()
    if not path.is_file():
        raise ValueError("Canonical shared database missing")
    if progress:progress("Building one 09:10 IST information set per observed date")
    with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=3)) as db:
        db.execute("PRAGMA query_only=ON")
        timelines,evidence=m.load_timelines(db,
             datetime.combine(start,time.min,g.IST),datetime.combine(stop,time.min,g.IST),"archive")
        for day in dates:
            i=all_dates.index(day)
            if not i:
                counts["missing_previous_observed_session"]+=1;continue
            prev=all_dates[i-1]
            if (date.fromisoformat(day)-date.fromisoformat(prev)).days>7:
                counts["previous_observation_too_old"]+=1;continue
            result=index_sample(index[prev],index[day])
            if result is None:
                counts["missing_exact_index_anchors"]+=1;continue
            domestic,returns=result
            bank=None
            if left is not None and left<=date.fromisoformat(prev)<right:
                members=h._member_set(intervals,prev)
                bank=constituent_sample(prev,stocks,members,resolved)
            counts["constituent_supported" if bank is not None else "constituent_missing"]+=1
            domestic=domestic+(bank+[0.] if bank is not None else [0.,0.,1.])
            glob,available=features(db,timelines,day)
            availability.update(available)
            # Require at least one overnight ETF to answer the specific
            # overnight hypothesis, with identical dates for all models.
            if not any("BOATS_"+s in available for s in OVERNIGHT):
                counts["no_fresh_overnight_session_return"]+=1;continue
            counts["paired_dates"]+=1
            rows[day]={"date":day,"domestic":domestic,"global":glob,
                       "combined":domestic+glob,"returns":returns}
    if progress:progress("Expanding chronological baseline fits")
    return {"version":"global_open_baseline_v1","state":"exploratory",
        "from_date":str(start),"to_date_exclusive":str(stop),"cutoff_ist":"09:10",
        "reserved_observed_dates":dates,"counts":dict(counts),
        "feature_availability_before_pair_gate":dict(availability),
        "domestic_features":["prior_banknifty_session_bps","prior_banknifty_last30_bps",
            "prior_member_mean_bps","prior_member_breadth_pct","member_missing"],
        "daily_factors":DAILY,"overnight_symbols":OVERNIGHT,"batch_id":chosen,
        "membership_span":[str(left),str(right)] if left else None,
        "source_hashes":{**hashes,**stock_hashes},"source_failures":{**failures,**stock_failures},
        "context_evidence":evidence,"train_reserved_dates":TRAIN_DATES,"block_dates":BLOCK,
        "results":{target:evaluate(dates,rows,target) for target in TARGETS},
        "warning":WARNING}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--from-date",type=date.fromisoformat,default=date(2026,8,29))
    p.add_argument("--to-date",type=date.fromisoformat,default=date(2026,11,27))
    p.add_argument("--shared-root",type=Path,default=service.ROOT)
    p.add_argument("--batch-id")
    p.add_argument("--index-only",action="store_true")
    args=p.parse_args()
    root=args.shared_root.resolve()
    if not (root/"data").is_dir():
        p.error("Original QuantLab data directory is missing")
    service.DATA=root/"data"
    import sys
    report=run(args.from_date,args.to_date,args.batch_id,index_only=args.index_only,
               progress=lambda message:print(message,file=sys.stderr,flush=True))
    dest=root/"results"/("global_open_baseline_"+args.from_date.isoformat()+"_"+args.to_date.isoformat()+".json")
    dest.parent.mkdir(parents=True,exist_ok=True)
    # No database writes; output is a small reproducible research report.
    import os,uuid
    tmp=dest.with_name("."+dest.name+"."+uuid.uuid4().hex)
    try:
        tmp.write_text(json.dumps(report,indent=2,allow_nan=False),encoding="utf-8")
        os.replace(tmp,dest)
    finally:
        tmp.unlink(missing_ok=True)
    print(json.dumps({"report":str(dest),"reserved_dates":len(report["reserved_observed_dates"]),
        "counts":report["counts"],"feature_availability":report["feature_availability_before_pair_gate"],
        "membership_span":report["membership_span"],
        "results":{k:{x:v for x,v in r.items() if x!="predictions" and x!="blocks"} for k,r in report["results"].items()},
        "warning":WARNING},indent=2,allow_nan=False))


if __name__=="__main__":
    main()
