"""Five-year descriptive EMA 9/21 crossover-to-opposite-cross path audit.

Measure observed favorable/adverse excursion, time to extreme and retracement.
The future extreme is a research label, NOT a signal or attainable exit.
No broker calls, orders, option price inference or model promotion.
"""
import argparse
import csv
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import uuid
from collections import Counter

import numpy as np

from scripts import benchmark_direction_gate as b
from scripts.run_banknifty_candle_forecast import write_atomic
from workstation_api import banknifty_candle_forecast as m
from workstation_api import historical_alpha as h
from workstation_api import service
from workstation_api import cpr_hybrid_research as r

VERSION="ema_cross_path_v1"
FAST=9
SLOW=21
DELAY=1
PROXY_COST_BPS=5.
MINUTES=375


def session_crosses(bars,previous,*,previous_minutes=MINUTES,session_minutes=MINUTES):
    """One-minute close EMA, seeded with verified complete prior weekday.

    Ignore equality touches: a new cross requires opposite nonzero signs.
    If prior EMAs are exactly equal, first nonzero sign establishes state.
    Process only the contiguous observed current-session prefix.
    """
    if bars.shape!=(MINUTES,5):
        raise ValueError("Expected regular 375-minute index research array")
    if not (type(previous_minutes) is int and type(session_minutes) is int and
            1<=previous_minutes<=MINUTES and 1<=session_minutes<=MINUTES):
        raise ValueError("Invalid scheduled comparison window")
    if previous is None or previous.shape!=(MINUTES,5):
        return [],0,"prior_complete_weekday_unavailable"
    prior=previous[:previous_minutes,:4]
    if not np.isfinite(prior).all() or np.any(prior<=0):
        return [],0,"prior_complete_weekday_unavailable"
    prev=(prior[0,0],prior[:,1].max(),prior[:,2].min(),prior[-1,3])
    current=bars[:session_minutes,:4]
    valid=np.isfinite(current).all(axis=1)&(current>0).all(axis=1)
    missing=np.flatnonzero(~valid)
    prefix=int(missing[0]) if len(missing) else session_minutes
    if not prefix:return [],0,"current_prefix_unavailable"
    op,high,low,close=map(float,prev)
    pivot=(high+low+close)/3
    bc=(high+low)/2
    bottom,top=sorted((bc,2*pivot-bc))
    fast=h._ema(prior[:,3],FAST);slow=h._ema(prior[:,3],SLOW)
    state=int(np.sign(fast-slow))
    crosses=[];today_high=-np.inf;today_low=np.inf
    for minute in range(prefix):
        _,hi,lo,price=map(float,bars[minute,:4])
        today_high=max(today_high,hi);today_low=min(today_low,lo)
        fast+=(price-fast)*2/(FAST+1)
        slow+=(price-slow)*2/(SLOW+1)
        direction=int(np.sign(fast-slow))
        if direction and state and direction!=state:
            zone="above" if price>top else "below" if price<bottom else "inside"
            crosses.append({"minute":minute,"direction":direction,"signal_close":price,
                            "ema9":fast,"ema21":slow,"previous_open":op,
                            "previous_high":high,"previous_low":low,"previous_close":close,
                            "cpr_bottom":bottom,"cpr_pivot":pivot,"cpr_top":top,"cpr_zone":zone,
                            "today_open":float(bars[0,0]),"today_running_high":today_high,
                            "today_running_low":today_low})
        if direction:state=direction
    return crosses,prefix,"complete_regular_prefix" if prefix==session_minutes else "current_gap"


def path_row(day,bars,cross,next_cross,prefix):
    """A completed signal is the starting mark, not a known execution price.

    Intrabar extrema use only subsequent candles (through opposite signal
    candle inclusive). With OHLC data the exact intrabar order/time is unknown.
    Mark unfinished paths separately; never assume a missing reversal.
    """
    start=int(cross["minute"]);direction=int(cross["direction"])
    end=int(next_cross["minute"]) if next_cross is not None else prefix-1
    if not 0<=start<=end<prefix or direction not in (-1,1):
        raise ValueError("Invalid path boundaries")
    if next_cross is not None and int(next_cross["direction"])!=-direction:
        raise ValueError("End must be the opposite crossover")
    price=float(cross["signal_close"])
    subsequent=bars[start+1:end+1]
    if not np.isfinite(subsequent[:,:4]).all():
        raise ValueError("Path contains a gap")
    favorable=np.r_[price,subsequent[:,1 if direction==1 else 2]]
    adverse=np.r_[price,subsequent[:,2 if direction==1 else 1]]
    best_index=int(np.argmax(direction*(favorable-price)))
    worst_index=int(np.argmax(-direction*(adverse-price)))
    peak=float(favorable[best_index]);worst=float(adverse[worst_index])
    mfe=max(0.,direction*(peak-price));mae=max(0.,-direction*(worst-price))
    endpoint=float(bars[end,3])
    signed=direction*(endpoint-price)
    giveback=max(0.,mfe-signed)
    completed=next_cross is not None
    row={**{k:v for k,v in cross.items() if k!="minute"},
         "session":day,"prior_weekday":b.prior_weekday(day),
         "direction_name":"bullish" if direction==1 else "bearish",
         "signal_minute":start,"signal_utc":r._stamp(day,start+1),
         "state":"opposite_cross" if completed else ("censored_session_end" if prefix==MINUTES else "censored_missing_bar"),
         "end_minute":end,"end_mark_utc":r._stamp(day,end+1),"end_close":endpoint,
         "opposite_cross_utc":r._stamp(day,end+1) if completed else None,
         "duration_minutes":end-start,"favorable_extreme_price":peak,
         "adverse_extreme_price":worst,
         "favorable_extreme_bar_close_utc":r._stamp(day,start+best_index+1),
         "adverse_extreme_bar_close_utc":r._stamp(day,start+worst_index+1),
         "minutes_to_favorable_extreme":best_index,"minutes_to_adverse_extreme":worst_index,
         "minutes_from_favorable_extreme_to_end":end-start-best_index,
         "mfe_points":mfe,"mae_points":mae,"signed_end_move_points":signed,
         "giveback_points":giveback,
         "mfe_bps":10000*mfe/price,"mae_bps":10000*mae/price,
         "signed_end_move_bps":10000*signed/price,"giveback_bps":10000*giveback/price,
         "capture_fraction":signed/mfe if mfe>0 else None,
         "giveback_fraction":giveback/mfe if mfe>0 else None,
         "delayed_reference_state":"not_scored_censored",
         "entry_reference_utc":None,"exit_reference_utc":None,
         "entry_reference_open":None,"exit_reference_open":None,
         "delayed_signed_move_points":None,"delayed_gross_proxy_bps":None,
         "delayed_net_proxy_bps":None}
    if not completed:return row
    entry=start+1+DELAY;exit_=end+1+DELAY
    # If the reverse signal is known by the earliest entry reference,
    # cancel rather than assume a trade from a stale signal.
    if end+1<=entry:
        row["delayed_reference_state"]="opposite_signal_before_or_at_entry"
    elif entry>=prefix or exit_>=prefix:
        row["delayed_reference_state"]="reference_unobserved"
    else:
        entry_price=float(bars[entry,0]);exit_price=float(bars[exit_,0])
        move=direction*(exit_price-entry_price)
        gross=10000*move/entry_price
        row.update(delayed_reference_state="scored_index_open_proxy",
                   entry_reference_utc=r._stamp(day,entry),
                   exit_reference_utc=r._stamp(day,exit_),
                   entry_reference_open=entry_price,exit_reference_open=exit_price,
                   delayed_signed_move_points=move,delayed_gross_proxy_bps=gross,
                   delayed_net_proxy_bps=gross-PROXY_COST_BPS)
    return row


def analyze(index,progress=None):
    rows=[];coverage={}
    dates=sorted(index)
    for i,day in enumerate(dates):
        if progress and (i%100==0 or i+1==len(dates)):
            progress(f"Measuring EMA paths {i+1}/{len(dates)} {day}")
        bars=index[day]
        crosses,prefix,state=session_crosses(bars,index.get(b.prior_weekday(day)))
        paths=[path_row(day,bars,c,crosses[k+1] if k+1<len(crosses) else None,prefix)
               for k,c in enumerate(crosses)]
        rows.extend(paths)
        coverage[day]={"state":state,"observed_prefix_minutes":prefix,
                       "crossovers":len(crosses),
                       "path_states":dict(Counter(x["state"] for x in paths)),
                       "delayed_reference_states":dict(Counter(x["delayed_reference_state"] for x in paths))}
    return rows,coverage


def distribution(rows,key):
    values=np.asarray([x[key] for x in rows if x[key] is not None],dtype=float)
    if not len(values):return {"count":0}
    if not np.isfinite(values).all():raise ValueError("Nonfinite path statistic")
    return {"count":len(values),"mean":float(values.mean()),"min":float(values.min()),
            **{f"p{q}":float(np.percentile(values,q)) for q in (10,25,50,75,90,95)},
            "max":float(values.max())}


METRICS=("duration_minutes","minutes_to_favorable_extreme",
         "minutes_from_favorable_extreme_to_end",
         "mfe_points","mae_points","signed_end_move_points","giveback_points",
         "mfe_bps","mae_bps","signed_end_move_bps","giveback_bps",
         "capture_fraction","giveback_fraction","delayed_signed_move_points",
         "delayed_gross_proxy_bps","delayed_net_proxy_bps")


def summarize(rows):
    complete=[x for x in rows if x["state"]=="opposite_cross"]
    censored=[x for x in rows if x["state"]!="opposite_cross"]
    delayed=[x for x in complete if x["delayed_reference_state"]=="scored_index_open_proxy"]
    return {"paths":len(rows),"sessions":len({x["session"] for x in rows}),
            "path_states":dict(Counter(x["state"] for x in rows)),
            "complete_paths":len(complete),
            "complete_sessions":len({x["session"] for x in complete}),
            "censored_paths":len(censored),
            "delayed_reference_states":dict(Counter(x["delayed_reference_state"] for x in rows)),
            "complete_distribution":{k:distribution(complete,k) for k in METRICS},
            "censored_observed_lower_bound_distribution":{
                k:distribution(censored,k) for k in ("duration_minutes","mfe_points","mae_points","mfe_bps","mae_bps")},
            "positive_completed_end_move_fraction":float(np.mean([x["signed_end_move_points"]>0 for x in complete])) if complete else None,
            "positive_delayed_net_proxy_fraction":float(np.mean([x["delayed_net_proxy_bps"]>0 for x in delayed])) if delayed else None}


def groups(rows):
    return {"all":summarize(rows),
            **{name:summarize([x for x in rows if x["direction_name"]==name]) for name in ("bullish","bearish")},
            "by_direction_and_cpr_zone":{
                direction+"_"+zone:summarize([x for x in rows if x["direction_name"]==direction and x["cpr_zone"]==zone])
                for direction in ("bullish","bearish") for zone in ("above","inside","below")}}


def run(root,stop,days=1825,progress=print):
    if type(days) is not int or not 120<=days<=m.MAX_CORE_DAYS or stop>datetime.now(h.IST).date():
        raise ValueError("Use completed dates and 120-1827 calendar days")
    service.DATA=root/"data"
    if not service.DATA.is_dir():raise ValueError("Shared data directory missing")
    start=stop-timedelta(days=days)
    index,*_,meta=m.load_sources(start,stop,wings=None,index_only=True,progress=progress)
    dates=sorted(index);splits=m.split_days(dates)
    rows,coverage=analyze(index,progress)
    if not rows:raise ValueError("No supported fresh EMA crossovers")
    partition={day:name for name,part in zip(("training","validation","evaluation"),splits) for day in part}
    for row in rows:row["chronological_partition"]=partition[row["session"]]
    report={"version":VERSION,"from_inclusive":start.isoformat(),"to_exclusive":stop.isoformat(),
            "observed_sessions":len(dates),"observed_date_span":[dates[0],dates[-1]],
            "training_dates":splits[0],"validation_dates":splits[1],"evaluation_dates":splits[2],
            "source_evidence":meta["index"],"session_coverage":coverage,
            "session_states":dict(Counter(x["state"] for x in coverage.values())),
            "ema_periods":[FAST,SLOW],"candle_minutes":1,"delayed_reference_minutes":DELAY,
            "assumed_index_roundtrip_proxy_bps":PROXY_COST_BPS,
            "all_observed_dates":groups(rows),
            "chronological_groups":{name:groups([x for x in rows if x["chronological_partition"]==name])
                                     for name in ("training","validation","evaluation")},
            "warning":("Descriptive crossover paths, not a trained predictor or achievable peak/trough exit. "
                       "One-minute close EMA seeded by the complete preceding weekday; missing/unverified "
                       "weekdays (including unverified holidays) excluded. Equal EMA touches do not create "
                       "repeated same-direction crosses. No cross-session position. Missing bars or end of "
                       "regular session censor the last open path. Future extrema use subsequent OHLC "
                       "bars through the opposite-cross candle, whose intrabar order is unknown. "
                       "Censored excursions are observed lower bounds, not complete-path outcomes. "
                       "Complete-path and delayed-open subsets are conditional on available observations. "
                       "Delayed open prices are index references, not executable fills; 5bps is an "
                       "illustrative index proxy, not option costs. No option P&L, cumulative account "
                       "return, prospective qualification or live orders. Previously examined dates remain exploratory.")}
    return report,rows


def _brief(summary):
    d=summary["complete_distribution"]
    return {"paths":summary["paths"],"complete":summary["complete_paths"],
            "censored":summary["censored_paths"],
            "delayed_reference_states":summary["delayed_reference_states"],
            **{key:{q:d[key].get(q) for q in ("p25","p50","p75","p90","max")}
               for key in ("duration_minutes","minutes_to_favorable_extreme","mfe_points","mae_points",
                           "signed_end_move_points","giveback_points","capture_fraction",
                           "giveback_fraction","delayed_signed_move_points","delayed_net_proxy_bps")},
            "positive_completed_end_move_fraction":summary["positive_completed_end_move_fraction"],
            "positive_delayed_net_proxy_fraction":summary["positive_delayed_net_proxy_fraction"]}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--shared-root",type=Path,default=service.ROOT)
    ap.add_argument("--days",type=int,default=1825)
    ap.add_argument("--to-date",default="2026-11-27",help="Exclusive IST end date")
    args=ap.parse_args()
    try:
        root=args.shared_root.resolve()
        report,rows=run(root,date.fromisoformat(args.to_date),args.days,lambda s:print(s,flush=True))
        folder=root/"results";folder.mkdir(exist_ok=True)
        stem="banknifty_ema_cross_paths_"+uuid.uuid4().hex
        path=folder/(stem+".json");csv_path=folder/(stem+"_paths.csv")
        def writer(out):
            w=csv.DictWriter(out,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
        write_atomic(csv_path,writer)
        report["path_csv"]=csv_path.name
        write_atomic(path,lambda out:json.dump(report,out,sort_keys=True,indent=2,allow_nan=False))
        print("SESSIONS",report["observed_sessions"],json.dumps(report["session_states"]))
        for period,summary in (("all_observed_dates",report["all_observed_dates"]),
                                ("evaluation",report["chronological_groups"]["evaluation"])):
            for side in ("all","bullish","bearish"):
                print("PATHS",period,side,json.dumps(_brief(summary[side])))
            print("CPR_ZONES",period,json.dumps({key:_brief(value) for key,value in summary["by_direction_and_cpr_zone"].items()}))
        print("REPORT",path)
        print("PATH_CSV",csv_path)
        print(report["warning"])
        return 0
    except (ValueError,OSError,RuntimeError) as exc:
        print("EMA path audit unavailable:",str(exc)[:240])
        return 2


if __name__=="__main__":
    raise SystemExit(main())
