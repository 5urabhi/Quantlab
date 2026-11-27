"""Replicate frozen EMA level patterns across saved equity indices and banks.

Descriptive common-session comparisons, not a forecast or strategy. Reuse
the exact crossover and level definitions, with scheduled cash-session masks.
No new providers, downloads, orders, or pooled cross-asset trade counts.
"""
import argparse
from collections import Counter, defaultdict
import csv
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import uuid

import numpy as np

from scripts import benchmark_ema_paths as p
from scripts import benchmark_ema_levels as l
from scripts import benchmark_direction_gate as b
from scripts.run_banknifty_candle_forecast import write_atomic
from workstation_api import banknifty_candle_forecast as m
from workstation_api import historical_alpha as h
from workstation_api import service
from workstation_api import nse_session_policy as policy

VERSION="cross_market_ema_levels_v1"
PEERS=tuple(x for x in m.f.PEERS if x!="INDEX:INDIAVIX")
# Preserve every named level from the five-year study, not selected winners.
FIELDS=("distance_bps","breakout_extension_bps","minutes_to_breakout",
        "minutes_breakout_to_failure","adverse_bps_from_failure_close",
        "minutes_to_adverse_extreme","minutes_to_reclaim",
        "initial_rejection_adverse_bps","initial_rejection_minutes_to_reclaim")


def complete(array,minutes):
    if array is None or array.shape!=(p.MINUTES,5):return False
    a=array[:minutes,:4]
    return bool(np.isfinite(a).all() and np.all(a>0))


def common_dates(index,other,identity,dates,membership=None):
    """Match full regular prefixes, also matching previous-weekday seed.

    The dated bank universe is required only for bank lanes. Both instruments
    use the bank's supported scheduled comparison length on each date.
    """
    chosen=[];counts=Counter()
    for day in dates:
        if membership is not None and identity not in membership.get(day,{}).values():
            counts["not_dated_member_or_membership_unavailable"]+=1
            continue
        prev=b.prior_weekday(day)
        n=policy.cash_bank_minutes(day,identity) if membership is not None else p.MINUTES
        q=policy.cash_bank_minutes(prev,identity) if membership is not None else p.MINUTES
        if not complete(index.get(day),n) or not complete(index.get(prev),q):
            counts["index_or_prior_prefix_unavailable"]+=1
        elif not complete(other.get(day),n) or not complete(other.get(prev),q):
            counts["instrument_or_prior_prefix_unavailable"]+=1
        else:
            chosen.append((day,n,q))
            counts["matched_complete_sessions"]+=1
    return chosen,dict(counts)


def compact(row):
    # Preserve sufficient descriptive statistics without millions of copies
    # of the full level-path journal. Units normalize different price scales.
    return {"direction":row["direction_name"],"level":row["level_name"],
            "state":row["state"],"complete":row["leg_state"]=="opposite_cross",
            "distance_bps":row["distance_bps"],
            "touched":row["touch_minute"] is not None,
            "broken":row["breakout_minute"] is not None,
            "failed":row["state"]=="failed_breakout_in_leg",
            "breakout_extension_bps":(10000*row["breakout_favorable_extension_points"]/row["level_price"]
                    if row["breakout_favorable_extension_points"] is not None else None),
            "minutes_to_breakout":row["minutes_to_breakout"],
            "minutes_breakout_to_failure":row["minutes_breakout_to_failure"],
            "failure_observed":row["failure_kind"]=="closed_back_after_breakout",
            "failure_reclaimed":row["failure_followup_state"]=="reclaimed",
            "adverse_bps_from_failure_close":row["adverse_bps_from_failure_close"],
            "minutes_to_adverse_extreme":row["minutes_to_adverse_extreme"],
            "minutes_to_reclaim":row["minutes_to_reclaim"],
            "initial_rejection_observed":row["initial_rejection_failure_minute"] is not None,
            "initial_rejection_reclaimed":row["initial_rejection_followup_state"]=="reclaimed",
            "initial_rejection_adverse_bps":row["initial_rejection_adverse_bps_from_failure_close"],
            "initial_rejection_minutes_to_reclaim":row["initial_rejection_minutes_to_reclaim"]}


def session_rows(source,day,n,q):
    bars=source[day];previous=source[b.prior_weekday(day)]
    crosses,prefix,state=p.session_crosses(bars,previous,previous_minutes=q,session_minutes=n)
    if prefix!=n or state!="complete_regular_prefix":
        raise ValueError("Matched source changed or contains a gap")
    rows=[]
    for k,cross in enumerate(crosses):
        nxt=crosses[k+1] if k+1<len(crosses) else None
        levels=l.frozen_levels(bars,cross)
        for name in l.LEVEL_NAMES:
            row=l.level_row(day,bars,cross,nxt,prefix,name,levels[name],session_minutes=n)
            rows.append(compact(row))
    return rows,len(crosses)


def summarize(rows):
    ahead=[r for r in rows if r["distance_bps"] is not None and r["distance_bps"]>0]
    complete_rows=[r for r in ahead if r["complete"]]
    touched=[r for r in complete_rows if r["touched"]]
    broken=[r for r in complete_rows if r["broken"]]
    failed=[r for r in broken if r["failed"]]
    observed_failures=[r for r in ahead if r["failure_observed"]]
    rejected=[r for r in ahead if r["initial_rejection_observed"]]
    def dist(rs,key):
        return p.distribution(rs,key)
    return {"level_rows":len(rows),"states":dict(Counter(r["state"] for r in rows)),
            "ahead":len(ahead),"completed_ahead":len(complete_rows),
            "touch":len(touched),"breakout":len(broken),"failed":len(failed),
            "breakout_per_ahead":l.fraction(len(broken),len(complete_rows)),
            "breakout_per_touch":l.fraction(len(broken),len(touched)),
            "failed_per_breakout":l.fraction(len(failed),len(broken)),
            "distance_bps":dist(ahead,"distance_bps"),
            "breakout_extension_bps":dist(broken,"breakout_extension_bps"),
            "minutes_to_breakout":dist(broken,"minutes_to_breakout"),
            "minutes_breakout_to_failure":dist(failed,"minutes_breakout_to_failure"),
            "failure_followups":len(observed_failures),
            "failure_reclaimed":sum(r["failure_reclaimed"] for r in observed_failures),
            "adverse_bps_observed":dist(observed_failures,"adverse_bps_from_failure_close"),
            "minutes_to_adverse_extreme_observed":dist(observed_failures,"minutes_to_adverse_extreme"),
            "minutes_to_reclaim_completed_only":dist(observed_failures,"minutes_to_reclaim"),
            "initial_rejections":len(rejected),
            "initial_reclaimed":sum(r["initial_rejection_reclaimed"] for r in rejected),
            "initial_adverse_bps_observed":dist(rejected,"initial_rejection_adverse_bps"),
            "initial_minutes_to_reclaim_completed_only":dist(rejected,"initial_rejection_minutes_to_reclaim")}


def group(rows):
    bins=defaultdict(list)
    for row in rows:bins[(row["direction"],row["level"])].append(row)
    return {side:{name:summarize(bins[(side,name)]) for name in l.LEVEL_NAMES}
            for side in ("bullish","bearish")}


def compare(index,other,identity,dates,evaluation_dates,*,membership=None,baseline_cache=None):
    matched,coverage=common_dates(index,other,identity,dates,membership)
    if baseline_cache is None:baseline_cache={}
    left=[];right=[];le=[];re=[];cross_count=Counter()
    evaluation_dates=set(evaluation_dates)
    for day,n,q in matched:
        key=(day,n,q)
        if key not in baseline_cache:baseline_cache[key]=session_rows(index,day,n,q)
        a,na=baseline_cache[key]
        c,nc=session_rows(other,day,n,q)
        left.extend(a);right.extend(c)
        cross_count["banknifty"]+=na;cross_count["instrument"]+=nc
        if day in evaluation_dates:
            le.extend(a);re.extend(c)
            cross_count["evaluation_banknifty"]+=na
            cross_count["evaluation_instrument"]+=nc
    return {"state":"assessed_descriptive" if matched else "insufficient_matched_sessions",
            "coverage":coverage,"matched_dates":[day for day,_,_ in matched],
            "evaluation_dates":[day for day,_,_ in matched if day in evaluation_dates],
            "comparison_minutes":dict(Counter(str(n) for _,n,_ in matched)),
            "crossovers":dict(cross_count),
            "all":{"banknifty":group(left),"instrument":group(right)} if matched else {},
            "evaluation":{"banknifty":group(le),"instrument":group(re)} if le or re else {}}


def run(root,stop,days=365,progress=print):
    if type(days) is not int or not 120<=days<=400 or stop>datetime.now(h.IST).date():
        raise ValueError("Use completed dates and 120-400 calendar days")
    service.DATA=root/"data"
    if not service.DATA.is_dir():raise ValueError("Shared data directory missing")
    start=stop-timedelta(days=days)
    index,*_,meta=m.load_sources(start,stop,wings=None,index_only=True,progress=progress)
    dates=sorted(index);splits=m.split_days(dates);lanes={};sources={}
    cache={}
    for identity in PEERS:
        progress("Replicating levels on "+identity)
        try:
            raw,hashes,failures=h.shared_index_sources(start,stop,[h.MAX_TOTAL],identity=identity)
        except (OSError,ValueError,TypeError,KeyError) as exc:
            lanes[identity]={"state":"source_unavailable","reason":str(exc)[:180]}
            continue
        other={day:m.f.dense(bars) for day,bars in raw.items()}
        del raw
        sources[identity]={"source_hashes":hashes,"failures":failures,"observed_sessions":len(other)}
        lanes[identity]=compare(index,other,identity,dates,splits[2],baseline_cache=cache)
        del other
    stocks,membership,weights,bank_meta=m.f.load_membership(dates,start,stop,progress)
    del weights
    for identity in bank_meta["identities"]:
        progress("Replicating levels on dated constituent "+identity)
        if identity not in stocks:
            lanes[identity]={"state":"source_unavailable","reason":bank_meta["failures"].get(identity,"original source missing")}
            continue
        lanes[identity]=compare(index,stocks[identity],identity,dates,splits[2],
                                membership=membership,baseline_cache=cache)
    return {"version":VERSION,"from_inclusive":start.isoformat(),"to_exclusive":stop.isoformat(),
            "observed_index_sessions":len(dates),"evaluation_reserved_dates":splits[2],
            "index_sources":meta["index"],"peer_sources":sources,"bank_sources":bank_meta,
            "lanes":lanes,"levels":list(l.LEVEL_NAMES),
            "warning":("Descriptive cross-instrument replication on matched calendar dates and regular comparison "
                      "prefixes; crossovers are each instrument's own events, NOT synchronized BANKNIFTY predictions. "
                      "Each lane matches dates, current and prior weekday comparison lengths; reviewed shorter cash "
                      "sessions truncate both instruments and their prior seed to the scheduled common length. "
                      "Missing/unverified prior weekdays, gaps and unavailable dated membership exclude dates. "
                      "No India VIX equity lane, global/option replication, dated index weighting, or transfer fit. "
                      "Rates condition on completed legs; observed adverse follow-up can be censored. "
                      "Bps normalize price scales, not volatility or execution. Overlapping markets and levels are "
                      "dependent; no pooling as independent samples or selection of a profitable asset. "
                      "Previously examined dates are retrospective. No fill, cost, option P&L or live trade signal. "
                      "Next separate test: synchronize context at BANKNIFTY events and compare matched predictors.")}


def flatten(report):
    rows=[]
    for identity,lane in report["lanes"].items():
        if lane["state"]!="assessed_descriptive":continue
        for period in ("all","evaluation"):
            for instrument,groups in lane[period].items():
                for side,levels in groups.items():
                    for name,s in levels.items():
                        rows.append({"comparison_identity":identity,"period":period,"instrument":instrument,
                            "direction":side,"level":name,"matched_sessions":len(lane["matched_dates"] if period=="all" else lane["evaluation_dates"]),
                            **{key:s[key] for key in ("level_rows","ahead","completed_ahead","touch","breakout","failed",
                            "breakout_per_ahead","breakout_per_touch","failed_per_breakout","failure_followups","failure_reclaimed","initial_rejections","initial_reclaimed")},
                            **{"median_"+key:s[key].get("p50") for key in ("distance_bps","breakout_extension_bps","minutes_to_breakout",
                            "minutes_breakout_to_failure","adverse_bps_observed","minutes_to_adverse_extreme_observed",
                            "minutes_to_reclaim_completed_only","initial_adverse_bps_observed","initial_minutes_to_reclaim_completed_only")}})
    return rows


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--shared-root",type=Path,default=service.ROOT)
    ap.add_argument("--days",type=int,default=365)
    ap.add_argument("--to-date",default="2026-11-27",help="Exclusive IST end date")
    args=ap.parse_args()
    try:
        root=args.shared_root.resolve()
        report=run(root,date.fromisoformat(args.to_date),args.days,lambda s:print(s,flush=True))
        folder=root/"results";folder.mkdir(exist_ok=True)
        stem="banknifty_cross_market_levels_"+uuid.uuid4().hex
        path=folder/(stem+".json");csv_path=folder/(stem+"_summary.csv")
        rows=flatten(report)
        if rows:
            def writer(out):
                w=csv.DictWriter(out,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
            write_atomic(csv_path,writer)
        report["summary_csv"]=csv_path.name if rows else None
        write_atomic(path,lambda out:json.dump(report,out,sort_keys=True,indent=2,allow_nan=False))
        for identity,lane in report["lanes"].items():
            print("LANE",identity,json.dumps({"state":lane["state"],"coverage":lane.get("coverage"),
                  "matched_sessions":len(lane.get("matched_dates",[])),
                  "evaluation_sessions":len(lane.get("evaluation_dates",[])),
                  "crossovers":lane.get("crossovers"),"reason":lane.get("reason")}))
        for row in rows:
            if row["period"]=="evaluation" and row["level"] in ("previous_high","previous_low","cpr_top","cpr_bottom"):
                print("MATCHED_LEVEL",json.dumps(row,separators=(",",":")))
        print("REPORT",path)
        print("SUMMARY_CSV",csv_path if rows else "none")
        print(report["warning"])
        return 0
    except (ValueError,OSError,RuntimeError) as exc:
        print("Cross-market level audit unavailable:",str(exc)[:240])
        return 2


if __name__=="__main__":
    raise SystemExit(main())
