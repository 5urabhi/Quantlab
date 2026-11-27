"""Read-only, exploratory BANKNIFTY post-open selective baseline.

One decision per date per clock/horizon cell. No pooled overlapping trades,
new data requests, parameter search, orders or live model changes.
"""
import argparse
from collections import Counter
from datetime import date, timedelta
import json
import math
import os
from pathlib import Path
import uuid

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from scripts import benchmark_global_open as pre
from workstation_api import historical_alpha as h, global_market_archive as g, service

CLOCKS=(5,15,45,105,225)  # 09:20, 09:30, 10:00, 11:00, 13:00 IST
HORIZONS=(15,30)
INITIAL=40
BLOCK=10
MIN_TRAIN=25
MIN_TEST=20
CONFIDENCE=.60
COSTS=(0.,5.,10.)
INDEX_NAMES=("since_open_bps","last5_bps","recent15_or_less_bps",
             "recent_realized_vol_bps","recent_range_position")
MEMBER_NAMES=("member_mean_5m_bps","member_breadth_pct","member_dispersion_bps",
              "member_signed_relative_volume","relative_volume_missing")
NOTE=("Exploratory latest-retrieved historical minute OHLC. Clock cells are evaluated "
      "separately, not a combined trading portfolio. Entry is a later index minute open "
      "after a full minute of delay; index is not a tradable instrument. Costs are "
      "illustrative 0/5/10 bps, not Zerodha option fees, spread, slippage or actual P&L. "
      "Confidence is an uncalibrated directional probability, not probability of "
      "profit after costs. No OI, IV, order-book data or live promotion in this study.")


def clock_name(offset):
    minute=555+offset
    return f"{minute//60:02d}:{minute%60:02d}"


def sample_index(bars,offset,horizon):
    """Only completed pre-decision bars enter features; no same-bar execution."""
    first=max(0,offset-15)
    if any(k not in bars for k in range(first,offset)) or 0 not in bars:
        return None,"missing_feature_bars"
    entry=offset+1
    exit_=entry+horizon
    if entry not in bars or exit_ not in bars:
        return None,"missing_later_entry_or_exit"
    recent=[bars[k] for k in range(first,offset)]
    last=recent[-1][3]
    high=max(x[1] for x in recent)
    low=min(x[2] for x in recent)
    prices=[recent[0][0]]+[x[3] for x in recent]
    rets=[pre.bps(b,a) for a,b in zip(prices,prices[1:])]
    x=[pre.bps(last,bars[0][0]),pre.bps(last,bars[offset-5][0]),
       pre.bps(last,recent[0][0]),float(np.sqrt(np.mean(np.square(rets)))),
       (last-low)/(high-low) if high>low else .5]
    y=pre.bps(bars[exit_][0],bars[entry][0])
    if not all(math.isfinite(v) for v in x+[y]):
        return None,"invalid_prices"
    return {"index":x,"return_bps":y,"entry_minute":entry,"exit_minute":exit_,
            "momentum":int(np.sign(x[1]))},None


def member_features(day,offset,stocks,members,prior_dates):
    """Require complete member price evidence. Use past-only same-clock volumes."""
    if not members:
        return None
    keys=list(range(offset-5,offset))
    rets=[];signed_volume=[]
    for symbol in members:
        series=stocks.get(symbol,{})
        today=series.get(day,{})
        if any(k not in today for k in keys):
            return None
        ret=pre.bps(today[keys[-1]][3],today[keys[0]][0])
        rets.append(ret)
        observed=sum(today[k][4] for k in keys)
        past=[]
        for d in prior_dates[-20:]:
            old=series.get(d,{})
            if all(k in old for k in keys):
                v=sum(old[k][4] for k in keys)
                if v>0:
                    past.append(v)
        if len(past)>=5 and observed>0:
            signed_volume.append(float(np.sign(ret)*min(3.,observed/np.median(past))))
    coverage=len(signed_volume)/len(members)
    x=[float(np.mean(rets)),float(np.mean(np.sign(rets))*100),
       float(np.std(rets)),float(np.mean(signed_volume)) if coverage>=.8 else 0.,
       float(coverage<.8)]
    return x if all(math.isfinite(v) for v in x) else None


def metrics(records, *, reserved):
    if not records:
        return {"scored":0,"reserved":reserved,"trades":0,"trade_coverage":0.,
                "direction_accuracy":None,"brier":None,"log_loss":None,
                "win_rate_after_5bps":None,"net_bps_per_trade":None,
                "net_bps_per_scored_opportunity":None}
    y=np.asarray([int(r["return_bps"]>0) for r in records],dtype=float)
    p=np.asarray([r["p_up"] for r in records],dtype=float)
    action=np.asarray([r["action"] for r in records])
    r=np.asarray([r["return_bps"] for r in records],dtype=float)
    active=action!=0
    n=int(np.sum(active))
    signed=action*r
    clip=np.clip(p,1e-8,1-1e-8)
    return {"scored":len(records),"reserved":reserved,"trades":n,
            "trade_coverage":n/len(records),"reserved_trade_coverage":n/reserved if reserved else None,
            "direction_accuracy":float(np.mean((p>=.5)==y)),
            "called_direction_accuracy":float(np.mean(action[active]*r[active]>0)) if n else None,
            "brier":float(np.mean((p-y)**2)),
            "log_loss":float(-np.mean(y*np.log(clip)+(1-y)*np.log(1-clip))),
            "win_rate_after_5bps":float(np.mean(signed[active]>5.)) if n else None,
            "net_bps_per_trade":{str(int(c)):float(np.mean(signed[active]-c)) if n else None for c in COSTS},
            "net_bps_per_scored_opportunity":{str(int(c)):float(np.mean(signed-c*active)) for c in COSTS}}


def evaluate(dates,rows,*,matched=False):
    """Training and test dates reserved chronologically before evidence gates.

    A matched constituent cohort retrains the index comparator on the exact
    same supported rows; it never compares that restricted cohort to the
    broader index-only sample as a causal lift estimate.
    """
    methods=("prior","momentum","index_always","index_selective")
    if matched:
        methods+=("members_always","members_selective")
    records={key:[] for key in methods}
    blocks=[]
    def usable(d):
        row=rows.get(d)
        return row is not None and (not matched or row.get("members") is not None)
    for at in range(INITIAL,len(dates),BLOCK):
        train=[rows[d] for d in dates[:at] if usable(d)]
        test=[rows[d] for d in dates[at:at+BLOCK] if usable(d)]
        y=np.asarray([int(r["return_bps"]>0) for r in train])
        counts=Counter(y.tolist())
        block={"train_reserved":at,"train_usable":len(train),
               "test_reserved":len(dates[at:at+BLOCK]),"test_usable":len(test),
               "first_test_date":dates[at],"last_test_date":dates[min(len(dates)-1,at+BLOCK-1)]}
        if len(train)<MIN_TRAIN or min(counts.get(0,0),counts.get(1,0))<5 or not test:
            blocks.append({**block,"state":"insufficient_evidence"})
            continue
        fitted={}
        for key in (("index","members") if matched else ("index",)):
            def vector(row):
                return row["index"]+row["members"] if key=="members" else row["index"]
            model=make_pipeline(StandardScaler(),LogisticRegression(C=.1,max_iter=1000,random_state=0))
            model.fit([vector(r) for r in train],y)
            fitted[key]=model.predict_proba([vector(r) for r in test])[:,1]
        for j,row in enumerate(test):
            def add(key,p,action):
                records[key].append({"date":row["date"],"p_up":float(p),"action":int(action),
                                     "return_bps":row["return_bps"]})
            prior=float(np.mean(y))
            add("prior",prior,1 if prior>=.5 else -1)
            # Momentum is a deterministic direction comparator; .5 for
            # neutral and 0/1 for directions, not calibrated probabilities.
            momentum=row["momentum"]
            add("momentum",(momentum+1)/2,momentum)
            for key,probs in fitted.items():
                p=float(probs[j])
                action=1 if p>=.5 else -1
                add(key+"_always",p,action)
                add(key+"_selective",p,action if max(p,1-p)>=CONFIDENCE else 0)
        blocks.append({**block,"state":"evaluated"})
    reserved=max(0,len(dates)-INITIAL)
    summary={key:metrics(value,reserved=reserved) for key,value in records.items()}
    # Hard 0/1 momentum outputs are directions, not probabilistic forecasts.
    summary["momentum"]["brier"]=None
    summary["momentum"]["log_loss"]=None
    summary["momentum"]["direction_accuracy"]=None
    state="exploratory_comparison" if len(records["index_always"])>=MIN_TEST else "insufficient_held_out_dates"
    return {"state":state,"metrics":summary,"blocks":blocks,"predictions":records}


def run(start,stop,*,batch_id=None,index_only=False,progress=None):
    today=g._now().astimezone(g.IST).date()
    if not 0<(stop-start).days<=200 or stop>today:
        raise ValueError("Use completed dates within a 200-calendar-day slice")
    warm=start-timedelta(days=35)
    budget=[h.MAX_TOTAL]
    if progress:progress("Verifying existing BANKNIFTY minute receipts")
    index,hashes,failures=h.shared_index_sources(warm,stop,budget)
    dates=sorted(d for d in index if start.isoformat()<=d<stop.isoformat())
    all_dates=sorted(index)
    if index_only:
        chosen,stocks,intervals,resolved,left,right,stock_hashes,stock_failures=(None,{},[],{},None,None,{},{"membership":"index-only requested"})
    else:
        if progress:progress("Verifying existing constituent candles and dated membership")
        chosen,stocks,intervals,resolved,left,right,stock_hashes,stock_failures=pre.read_constituents(warm,stop,budget,batch_id)
    # Reserve all observed index dates, including missing rows. The matched
    # cohort is limited to the documented membership span, before evidence gates.
    paired_dates=[d for d in dates if left is not None and left<=date.fromisoformat(d)<right]
    cells={}
    for offset in CLOCKS:
        if progress:progress("Evaluating "+clock_name(offset)+" IST")
        members_by_day={}
        for day in paired_dates:
            members=h._member_set(intervals,day)
            past=[d for d in all_dates if d<day][-20:]
            members_by_day[day]=member_features(day,offset,stocks,members,past)
        for horizon in HORIZONS:
            rows={};counts=Counter()
            for day in dates:
                row,error=sample_index(index[day],offset,horizon)
                if row is None:
                    counts[error]+=1
                    continue
                row.update(date=day,members=members_by_day.get(day))
                rows[day]=row
                counts["index_supported"]+=1
                if row["members"] is not None:
                    counts["member_supported"]+=1
                    if row["members"][-1]==0:
                        counts["relative_volume_supported"]+=1
            key=clock_name(offset)+"_"+str(horizon)+"m"
            cells[key]={"decision_ist":clock_name(offset),"entry_ist":clock_name(offset+1),
                        "exit_ist":clock_name(offset+1+horizon),"counts":dict(counts),
                        "index_full":evaluate(dates,rows),
                        "constituents_matched":evaluate(paired_dates,rows,matched=True)}
    return {"version":"intraday_selective_baseline_v1","state":"exploratory",
            "from_date":str(start),"to_date_exclusive":str(stop),"primary_cell":"09:30_15m",
            "reserved_observed_dates":dates,"membership_reserved_dates":paired_dates,
            "membership_span":[str(left),str(right)] if left else None,"batch_id":chosen,
            "source_hashes":{**hashes,**stock_hashes},"source_failures":{**failures,**stock_failures},
            "initial_training_dates":INITIAL,"block_dates":BLOCK,"confidence_threshold":CONFIDENCE,
            "index_features":INDEX_NAMES,"member_features":MEMBER_NAMES,"cells":cells,"warning":NOTE}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--from-date",type=date.fromisoformat,default=date(2026,6,1))
    p.add_argument("--to-date",type=date.fromisoformat,default=date(2026,11,27))
    p.add_argument("--shared-root",type=Path,default=service.ROOT)
    p.add_argument("--batch-id")
    p.add_argument("--index-only",action="store_true")
    args=p.parse_args()
    root=args.shared_root.resolve()
    if not (root/"data").is_dir():
        p.error("Original shared data directory missing")
    service.DATA=root/"data"
    import sys
    report=run(args.from_date,args.to_date,batch_id=args.batch_id,index_only=args.index_only,
               progress=lambda msg:print(msg,file=sys.stderr,flush=True))
    dest=root/"results"/("intraday_selective_"+str(args.from_date)+"_"+str(args.to_date)+".json")
    dest.parent.mkdir(parents=True,exist_ok=True)
    tmp=dest.with_name("."+dest.name+"."+uuid.uuid4().hex)
    try:
        tmp.write_text(json.dumps(report,indent=2,allow_nan=False),encoding="utf-8")
        os.replace(tmp,dest)
    finally:
        tmp.unlink(missing_ok=True)
    # Full paired predictions and chronological splits in the JSON report;
    # small console table retains only decision-relevant metrics.
    print("REPORT",dest)
    print("Observed dates",len(report["reserved_observed_dates"]),
          "| membership dates",len(report["membership_reserved_dates"]),
          "| membership span",report["membership_span"])
    print("Cell | Cohort | Method | Scored | Trades | Call accuracy | Net bps/trade (5bps cost) | Net bps/scored")
    def fmt(v):
        return "-" if v is None else f"{v:.3f}"
    for key,cell in report["cells"].items():
        for cohort in ("index_full","constituents_matched"):
            result=cell[cohort]
            print(key,cohort,result["state"],cell["counts"])
            for method,m in result["metrics"].items():
                net=m["net_bps_per_trade"] or {}
                opp=m["net_bps_per_scored_opportunity"] or {}
                print(" | ".join((key,cohort,method,str(m["scored"]),str(m["trades"]),
                    fmt(m.get("called_direction_accuracy")),fmt(net.get("5")),fmt(opp.get("5")))))
    print(NOTE)


if __name__=="__main__":
    main()
