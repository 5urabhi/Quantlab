"""Descriptive directional level-break/rejection audit on original EMA paths.

Freeze all levels at the completed crossover candle. Count one encounter per
level per crossover, not every repeated wick. Follow first failures to reclaim
or the end of the observed session. No hypothetical fills or ML promotion.
"""
import argparse
import csv
from collections import Counter
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import uuid

import numpy as np

from scripts import benchmark_ema_paths as p
from scripts import benchmark_direction_gate as b
from scripts.run_banknifty_candle_forecast import write_atomic
from workstation_api import banknifty_candle_forecast as m
from workstation_api import historical_alpha as h
from workstation_api import service
from workstation_api import cpr_hybrid_research as r

VERSION="ema_level_paths_v1"
LEVEL_NAMES=(
    "previous_open","previous_high","previous_low","previous_close",
    "cpr_bottom","cpr_pivot","cpr_top","r1","r2","s1","s2",
    "today_open","today_running_high","today_running_low",
    "today_developing_cpr_bottom","today_developing_pivot","today_developing_cpr_top",
    "opening_15m_high","opening_15m_low","opening_15m_close",
)
FOLLOWUP_MINUTES=(1,5,10,15,30,60)
INITIAL_REJECTION_FIELDS=("failure_minute","failure_close","failure_followup_state",
    "reclaim_minute","followup_end_minute","minutes_to_reclaim","observed_followup_minutes",
    "minutes_to_adverse_extreme","adverse_extreme_price","adverse_points_from_failure_close",
    "adverse_points_from_level","adverse_bps_from_failure_close","reclaim_after_opposite_cross"
    )+tuple(f"signed_close_change_{n}m_points" for n in FOLLOWUP_MINUTES)


def frozen_levels(bars,cross):
    """Only information known at signal close; no future session extrema."""
    hi,lo,close=(float(cross[k]) for k in ("previous_high","previous_low","previous_close"))
    pivot=float(cross["cpr_pivot"])
    today_hi,today_lo,spot=(float(cross[k]) for k in ("today_running_high","today_running_low","signal_close"))
    developing=(today_hi+today_lo+spot)/3
    mid=(today_hi+today_lo)/2
    bottom,top=sorted((mid,2*developing-mid))
    levels={k:float(cross[k]) for k in ("previous_open","previous_high","previous_low","previous_close",
                   "cpr_bottom","cpr_pivot","cpr_top","today_open","today_running_high","today_running_low")}
    levels.update(r1=2*pivot-lo,r2=pivot+hi-lo,s1=2*pivot-hi,s2=pivot-hi+lo,
                  today_developing_cpr_bottom=bottom,today_developing_pivot=developing,
                  today_developing_cpr_top=top,opening_15m_high=None,
                  opening_15m_low=None,opening_15m_close=None)
    if cross["minute"]>=14:
        opening=bars[:15,:4]
        if np.isfinite(opening).all():
            levels.update(opening_15m_high=float(opening[:,1].max()),
                          opening_15m_low=float(opening[:,2].min()),
                          opening_15m_close=float(opening[-1,3]))
    return levels


def first_index(mask,start):
    positions=np.flatnonzero(mask)
    return int(positions[0]+start) if len(positions) else None


def failure_followup(bars,level,direction,minute,prefix,leg_end):
    """After a known near-side close, observe adverse movement to reclaim.

    A reclaim is a strict completed close beyond the same frozen level.
    Subsequent OHLC extremes through that reclaim candle are descriptive:
    intrabar ordering is unknown. The failure candle's earlier extremes
    are excluded. Report adverse movement relative to both level and
    failure close, and close returns at fixed offsets before reclaim.
    """
    failure_close=float(bars[minute,3])
    start=minute+1
    reclaim=first_index(direction*(bars[start:prefix,3]-level)>0,start)
    end=reclaim if reclaim is not None else prefix-1
    observed=bars[start:end+1]
    extremes=np.r_[failure_close,observed[:,2 if direction==1 else 1]]
    adverse=-direction*(extremes-failure_close)
    extreme_offset=int(np.argmax(adverse))
    extreme=float(extremes[extreme_offset])
    result={"failure_minute":minute,"failure_close":failure_close,
            "failure_followup_state":"reclaimed" if reclaim is not None else
                ("censored_session_end" if prefix==p.MINUTES else "censored_gap"),
            "reclaim_minute":reclaim,"followup_end_minute":end,
            "minutes_to_reclaim":reclaim-minute if reclaim is not None else None,
            "observed_followup_minutes":end-minute,
            "minutes_to_adverse_extreme":extreme_offset,
            "adverse_extreme_price":extreme,
            "adverse_points_from_failure_close":float(adverse[extreme_offset]),
            "adverse_points_from_level":max(0.,-direction*(extreme-level)),
            "adverse_bps_from_failure_close":float(adverse[extreme_offset])*10000/failure_close,
            "reclaim_after_opposite_cross":bool(reclaim>leg_end) if reclaim is not None else None}
    for horizon in FOLLOWUP_MINUTES:
        target=minute+horizon
        # Do not silently treat a reclaimed path as continuing to fail.
        result[f"signed_close_change_{horizon}m_points"]=(direction*(float(bars[target,3])-failure_close)
                    if target<=end else None)
    return result


def level_row(day,bars,cross,next_cross,prefix,name,level):
    start=int(cross["minute"]);direction=int(cross["direction"])
    end=int(next_cross["minute"]) if next_cross is not None else prefix-1
    if not 0<=start<=end<prefix or direction not in (-1,1):
        raise ValueError("Invalid level path boundaries")
    price=float(cross["signal_close"])
    row={"session":day,"signal_minute":start,"signal_utc":r._stamp(day,start+1),
         "direction_name":"bullish" if direction==1 else "bearish",
         "direction":direction,"signal_close":price,"level_name":name,"level_price":level,
         "cpr_zone":cross["cpr_zone"],"leg_end_minute":end,
         "leg_state":"opposite_cross" if next_cross is not None else
                 ("censored_session_end" if prefix==p.MINUTES else "censored_gap"),
         "distance_points":None,"distance_bps":None,"state":"unavailable_level",
         "touch_minute":None,"minutes_to_touch":None,"first_touch_close":None,
         "first_touch_state":None,"breakout_minute":None,"minutes_to_breakout":None,
         "breakout_close":None,"minutes_touch_to_breakout":None,
         "failure_kind":None,"minutes_breakout_to_failure":None,
         "breakout_favorable_extension_points":None,"minutes_to_breakout_extreme":None,
         "failure_minute":None,"failure_close":None,"failure_followup_state":None,
         "reclaim_minute":None,"followup_end_minute":None,"minutes_to_reclaim":None,
         "observed_followup_minutes":None,"minutes_to_adverse_extreme":None,
         "adverse_extreme_price":None,"adverse_points_from_failure_close":None,
         "adverse_points_from_level":None,"adverse_bps_from_failure_close":None,
         "reclaim_after_opposite_cross":None,
         **{f"signed_close_change_{n}m_points":None for n in FOLLOWUP_MINUTES},
         **{"initial_rejection_"+key:None for key in INITIAL_REJECTION_FIELDS}}
    if level is None:return row
    distance=direction*(level-price)
    row.update(distance_points=distance,distance_bps=10000*distance/price)
    if distance<=0:
        row["state"]="at_level_at_signal" if distance==0 else "already_beyond_at_signal"
        return row
    future=bars[start+1:end+1]
    if not np.isfinite(future[:,:4]).all():raise ValueError("Unobserved candle inside level leg")
    near=next_cross is not None
    touch=first_index(direction*(future[:,1 if direction==1 else 2]-level)>=0,start+1)
    if touch is None:
        row["state"]="not_reached" if near else "unresolved_not_reached"
        return row
    touch_close=float(bars[touch,3])
    row.update(touch_minute=touch,minutes_to_touch=touch-start,first_touch_close=touch_close,
               first_touch_state="closed_beyond" if direction*(touch_close-level)>0 else
                       "rejected_close" if direction*(touch_close-level)<0 else "closed_at_level")
    breakout=first_index(direction*(bars[touch:end+1,3]-level)>0,touch)
    # First strict near-side close after touch and before any confirmed
    # breakout. Preserve its reversal even if a later breakout succeeds.
    initial_end=breakout if breakout is not None else end+1
    initial=first_index(direction*(bars[touch:initial_end,3]-level)<0,touch)
    if initial is not None:
        follow=failure_followup(bars,level,direction,initial,prefix,end)
        row.update({"initial_rejection_"+key:value for key,value in follow.items()})
    if breakout is None:
        row["state"]="touched_no_breakout" if near else "unresolved_touched_no_breakout"
        # A strict near-side close following a touch is a known rejection
        # even if the subsequent leg is censored. Never call equality a rejection.
        failure=first_index(direction*(bars[touch:end+1,3]-level)<0,touch)
        if failure is not None:
            row["failure_kind"]="touch_rejection_without_leg_breakout"
            row.update(failure_followup(bars,level,direction,failure,prefix,end))
        return row
    row.update(breakout_minute=breakout,minutes_to_breakout=breakout-start,
               breakout_close=float(bars[breakout,3]),minutes_touch_to_breakout=breakout-touch)
    failure=first_index(direction*(bars[breakout+1:end+1,3]-level)<0,breakout+1)
    # This extension begins at the confirmed breakout CLOSE. Do not use
    # the high/low of the breakout candle, which occurred before confirmation.
    extension_end=failure if failure is not None else end
    values=np.r_[float(bars[breakout,3]),bars[breakout+1:extension_end+1,1 if direction==1 else 2]]
    moves=direction*(values-level)
    best=int(np.argmax(moves))
    row.update(breakout_favorable_extension_points=float(moves[best]),minutes_to_breakout_extreme=best)
    if failure is None:
        row["state"]="breakout_no_failure_in_leg" if near else "unresolved_breakout_no_failure"
    else:
        row.update(state="failed_breakout_in_leg",failure_kind="closed_back_after_breakout",
                   minutes_breakout_to_failure=failure-breakout)
        row.update(failure_followup(bars,level,direction,failure,prefix,end))
    return row


def analyze(index,progress=None):
    rows=[];coverage={}
    dates=sorted(index)
    for i,day in enumerate(dates):
        if progress and (i%100==0 or i+1==len(dates)):
            progress(f"Auditing frozen EMA levels {i+1}/{len(dates)} {day}")
        bars=index[day]
        crosses,prefix,state=p.session_crosses(bars,index.get(b.prior_weekday(day)))
        coverage[day]={"state":state,"observed_prefix_minutes":prefix,"crossovers":len(crosses)}
        for k,cross in enumerate(crosses):
            nxt=crosses[k+1] if k+1<len(crosses) else None
            levels=frozen_levels(bars,cross)
            rows.extend(level_row(day,bars,cross,nxt,prefix,name,levels[name]) for name in LEVEL_NAMES)
    return rows,coverage


def fraction(n,d):return n/d if d else None


def summarize(rows):
    ahead=[x for x in rows if x["distance_points"] is not None and x["distance_points"]>0]
    completed=[x for x in ahead if x["leg_state"]=="opposite_cross"]
    touched=[x for x in ahead if x["touch_minute"] is not None]
    broken=[x for x in ahead if x["breakout_minute"] is not None]
    completed_touched=[x for x in completed if x["touch_minute"] is not None]
    completed_broken=[x for x in completed if x["breakout_minute"] is not None]
    failures=[x for x in ahead if x["failure_kind"] is not None]
    confirmed_failed=[x for x in completed_broken if x["state"]=="failed_breakout_in_leg"]
    def failure_stats(selected):
        reclaimed=[x for x in selected if x["failure_followup_state"]=="reclaimed"]
        censored=[x for x in selected if x["failure_followup_state"]!="reclaimed"]
        metrics=("observed_followup_minutes","minutes_to_adverse_extreme",
                 "adverse_points_from_failure_close","adverse_points_from_level",
                 "adverse_bps_from_failure_close")
        return {"failures":len(selected),"reclaimed":len(reclaimed),"censored":len(censored),
                "reclaimed_fraction_observed":fraction(len(reclaimed),len(selected)),
                "minutes_to_reclaim_completed_only":p.distribution(reclaimed,"minutes_to_reclaim"),
                "all_observed_followup_lower_bounds":{k:p.distribution(selected,k) for k in metrics},
                "reclaimed_followup":{k:p.distribution(reclaimed,k) for k in metrics},
                "censored_followup":{k:p.distribution(censored,k) for k in metrics},
                "close_change_before_or_at_reclaim":{str(n):p.distribution(selected,f"signed_close_change_{n}m_points")
                                                     for n in FOLLOWUP_MINUTES}}
    initial_rejections=[{key:x["initial_rejection_"+key] for key in INITIAL_REJECTION_FIELDS}
                        for x in ahead if x["initial_rejection_failure_minute"] is not None]
    return {"paths":len(rows),"sessions":len({x["session"] for x in rows}),
            "states":dict(Counter(x["state"] for x in rows)),
            "ahead":len(ahead),"completed_ahead":len(completed),
            "ahead_censored":len(ahead)-len(completed),
            "touched_all_observed":len(touched),"breakout_all_observed":len(broken),
            "first_touch_states":dict(Counter(x["first_touch_state"] for x in touched)),
            "completed_touch":len(completed_touched),"completed_breakout":len(completed_broken),
            "completed_touch_fraction_of_ahead":fraction(len(completed_touched),len(completed)),
            "completed_breakout_fraction_of_ahead":fraction(len(completed_broken),len(completed)),
            "completed_breakout_fraction_of_touched":fraction(len(completed_broken),len(completed_touched)),
            "completed_touch_rejection_fraction_of_touched":fraction(sum(x["first_touch_state"]=="rejected_close" for x in completed_touched),len(completed_touched)),
            "completed_failed_breakouts":len(confirmed_failed),
            "completed_failed_fraction_of_breakouts":fraction(len(confirmed_failed),len(completed_broken)),
            "distance_ahead_points":p.distribution(ahead,"distance_points"),
            "minutes_to_touch_completed":p.distribution(completed_touched,"minutes_to_touch"),
            "minutes_to_breakout_completed":p.distribution(completed_broken,"minutes_to_breakout"),
            "breakout_extension_completed":p.distribution(completed_broken,"breakout_favorable_extension_points"),
            "minutes_breakout_to_failure_completed":p.distribution(confirmed_failed,"minutes_breakout_to_failure"),
            "initial_rejection_followup":failure_stats(initial_rejections),
            "failure_followup":{kind:failure_stats([x for x in failures if x["failure_kind"]==kind])
                                for kind in ("touch_rejection_without_leg_breakout","closed_back_after_breakout")}}


def grouped(rows):
    # Distinct levels may coincide and one path can approach multiple levels.
    # Do not pool level rows as independent crossovers.
    buckets={}
    for row in rows:
        buckets.setdefault((row["direction_name"],row["level_name"]),[]).append(row)
    return {side:{name:summarize(buckets.get((side,name),[])) for name in LEVEL_NAMES}
            for side in ("bullish","bearish")}


def run(root,stop,days=1825,progress=print):
    if type(days) is not int or not 120<=days<=m.MAX_CORE_DAYS or stop>datetime.now(h.IST).date():
        raise ValueError("Use completed dates and 120-1827 calendar days")
    service.DATA=root/"data"
    if not service.DATA.is_dir():raise ValueError("Shared data directory missing")
    start=stop-timedelta(days=days)
    index,*_,meta=m.load_sources(start,stop,wings=None,index_only=True,progress=progress)
    dates=sorted(index);splits=m.split_days(dates)
    rows,coverage=analyze(index,progress)
    del index
    if not rows:raise ValueError("No supported EMA level opportunities")
    partition={day:name for name,part in zip(("training","validation","evaluation"),splits) for day in part}
    for row in rows:row["chronological_partition"]=partition[row["session"]]
    report={"version":VERSION,"from_inclusive":start.isoformat(),"to_exclusive":stop.isoformat(),
            "observed_sessions":len(dates),"observed_date_span":[dates[0],dates[-1]],
            "source_evidence":meta["index"],"session_coverage":coverage,
            "session_states":dict(Counter(x["state"] for x in coverage.values())),
            "unique_crossovers":sum(x["crossovers"] for x in coverage.values()),
            "level_rows":len(rows),"levels":list(LEVEL_NAMES),
            "training_dates":splits[0],"validation_dates":splits[1],"evaluation_dates":splits[2],
            "all_observed_dates":grouped(rows),
            "chronological_groups":{name:grouped([x for x in rows if x["chronological_partition"]==name])
                                     for name in ("training","validation","evaluation")},
            "warning":("Descriptive observed EMA crossover-to-opposite-cross level encounters; no fills or predictor. "
                       "All levels frozen at signal close. Today's close is the signal price, not a distinct ahead level. "
                       "Opening range unavailable before 15 completed candles. One-minute EMA and complete prior weekday "
                       "requirements match the original path audit; holidays and gaps may exclude sessions. "
                       "Only levels strictly ahead qualify; counts per level include at most one encounter per leg. "
                       "Touch uses high/low; breakout requires strict close beyond; failure requires subsequent strict "
                       "close back across within the leg. The first touch outcome is separate from eventual breakout. "
                       "A strict near-side close after touch but before any confirmed breakout has its own "
                       "follow-up, even if a later breakout succeeds. Rejections without a leg breakout are "
                       "a separate descriptive subset of those initial rejections. No-break and no-failure states "
                       "on incomplete legs are unresolved. Main rates condition on completed legs, not all signals; "
                       "all observed and censored counts are retained. Failures are followed through the first strict "
                       "reclaim close or session/gap censor, even after opposite EMA cross. No intrabar timing "
                       "or order inferred; extremes on the reclaim/failure endpoint candle are descriptive. "
                       "Adverse excursions and duration of censored follow-up are observed lower bounds. "
                       "Overlapping level/leg follow-ups are dependent; equal levels can duplicate events across names. "
                       "No cumulative P&L, exact exit, options costs, trading recommendation or prospective evidence.")}
    return report,rows


def _median(value):return value.get("p50")


def brief(name,s):
    failures=s["failure_followup"]["closed_back_after_breakout"]
    reject=s["initial_rejection_followup"]
    return {"level":name,"ahead":s["ahead"],"completed_ahead":s["completed_ahead"],
            "touch":s["completed_touch"],"breakout":s["completed_breakout"],"failed":s["completed_failed_breakouts"],
            "breakout_per_ahead":s["completed_breakout_fraction_of_ahead"],
            "breakout_per_touch":s["completed_breakout_fraction_of_touched"],
            "failed_per_breakout":s["completed_failed_fraction_of_breakouts"],
            "median_minutes_to_breakout":_median(s["minutes_to_breakout_completed"]),
            "median_breakout_extension_points":_median(s["breakout_extension_completed"]),
            "median_minutes_breakout_to_failure":_median(s["minutes_breakout_to_failure_completed"]),
            "failure_followups":failures["failures"],"failure_reclaimed":failures["reclaimed"],
            "failure_censored":failures["censored"],
            "median_minutes_to_reclaim_completed_only":_median(failures["minutes_to_reclaim_completed_only"]),
            "median_adverse_points_observed":_median(failures["all_observed_followup_lower_bounds"]["adverse_points_from_failure_close"]),
            "median_minutes_to_adverse_extreme_observed":_median(failures["all_observed_followup_lower_bounds"]["minutes_to_adverse_extreme"]),
            "rejection_followups":reject["failures"],"rejection_reclaimed":reject["reclaimed"],
            "median_rejection_adverse_points_observed":_median(reject["all_observed_followup_lower_bounds"]["adverse_points_from_failure_close"]),
            "median_rejection_minutes_to_reclaim_completed_only":_median(reject["minutes_to_reclaim_completed_only"])}


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
        stem="banknifty_ema_level_paths_"+uuid.uuid4().hex
        path=folder/(stem+".json");csv_path=folder/(stem+"_levels.csv")
        def writer(out):
            w=csv.DictWriter(out,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
        write_atomic(csv_path,writer)
        report["level_csv"]=csv_path.name
        write_atomic(path,lambda out:json.dump(report,out,sort_keys=True,indent=2,allow_nan=False))
        print("SESSIONS",report["observed_sessions"],json.dumps(report["session_states"]))
        print("CROSSOVERS",report["unique_crossovers"],"LEVEL_ROWS",report["level_rows"])
        for period,group in (("all",report["all_observed_dates"]),("evaluation",report["chronological_groups"]["evaluation"])):
            for side,levels in group.items():
                for name,summary in levels.items():
                    print("LEVEL",period,side,json.dumps(brief(name,summary),separators=(",",":")))
        print("REPORT",path)
        print("LEVEL_CSV",csv_path)
        print(report["warning"])
        return 0
    except (ValueError,OSError,RuntimeError) as exc:
        print("EMA level audit unavailable:",str(exc)[:240])
        return 2


if __name__=="__main__":
    raise SystemExit(main())
