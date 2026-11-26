"""Read-only, fixed-clock diagnostic on original Dhan depth.

Neither exchange fills nor passive queue priority are observed. Compare
identical decision anchors across fixed horizons, never choose best future
quotes or treat censored paths as zero P&L.
"""
from collections import Counter
from contextlib import closing
import sqlite3
from datetime import date,datetime,time,timedelta,timezone
from math import ceil,isfinite
from statistics import mean,median

from . import depth_replay as replay, liquidity_spreads as fees, paper_execution as paper

HORIZONS=(1,2,5,15,30,60,120,300)
MAX_COVERAGE_ROWS=50000
STEP_MINUTES=5


def _stats(values):
    if not values:
        return {"median":None,"p90":None,"mean":None}
    ordered=sorted(values)
    return {"median":round(median(ordered),3),"p90":round(ordered[ceil(.9*len(ordered))-1],3),
            "mean":round(mean(ordered),3)}


def _delta(a,b):
    return (datetime.fromisoformat(b)-datetime.fromisoformat(a)).total_seconds()


def _anchors(day,now,latency_ms,window_seconds,step_minutes=STEP_MINUTES):
    start=datetime.combine(day,time(9,20),paper.IST).astimezone(timezone.utc)
    close=datetime.combine(day,time(15,30),paper.IST).astimezone(timezone.utc)
    # Same eligible decisions for every horizon. Reserve both latency and
    # full receipt windows even if the first quote happens to arrive early.
    reserve=timedelta(seconds=max(HORIZONS)+2*window_seconds+2*latency_ms/1000+.01)
    if day.weekday()>=5:
        return []
    out=[]
    while start+reserve<close and start+reserve<=now:
        out.append(start)
        start+=timedelta(minutes=step_minutes)
    return out


def _coverage(day, identities, now):
    """Timestamp inventory, not a validation of every original book.

    Every elapsed regular-session second is in the denominator. Unsubscribed,
    quiet, dropped or missing seconds remain absent; no forward filling.
    Replay itself independently verifies the selected original book pair.
    """
    start=datetime.combine(day,time(9,15),paper.IST).astimezone(timezone.utc)
    end=min(now,datetime.combine(day,time(15,30),paper.IST).astimezone(timezone.utc))
    total=max(0,int((end-start).total_seconds()))
    output=[]
    sets=[]
    for identity in identities:
        bins=set()
        stamps=[]
        count=0
        limited=False
        state="available"
        try:
            if total:
                with closing(replay.ao._read_database()) as db:
                    cursor=db.execute("""SELECT received_utc FROM live_depth_books
                        WHERE identity=? AND received_utc>=? AND received_utc<?
                        ORDER BY received_utc LIMIT ?""",
                        (identity,paper._iso(start),paper._iso(start+timedelta(seconds=total)),MAX_COVERAGE_ROWS+1))
                    for (stamp,) in cursor:
                        count+=1
                        if count>MAX_COVERAGE_ROWS:
                            limited=True
                            break
                        t=(datetime.fromisoformat(stamp)-start).total_seconds()
                        if 0<=t<total:
                            bins.add(int(t))
                            stamps.append(t)
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc) and "unable to open database file" not in str(exc):
                raise
            state="source_unavailable"
        gaps=[b-a for a,b in zip(stamps,stamps[1:])]
        sets.append(bins)
        output.append({"identity":identity,"saved_receipts":len(stamps),"seconds_observed":len(bins),
                       "elapsed_seconds":total,"coverage_pct":round(100*len(bins)/total,2) if total else None,
                       "median_gap_seconds":_stats(gaps)["median"],"p90_gap_seconds":_stats(gaps)["p90"],
                       "largest_internal_gap_seconds":round(max(gaps),3) if gaps else None,
                       "scan_limited":limited,"state":state})
    overlap=len(set.intersection(*sets)) if sets else 0
    return {"contracts":output,"common_observed_seconds":overlap,"elapsed_seconds":total,
            "common_coverage_pct":round(100*overlap/total,2) if total else None,
            "note":"Saved timestamp inventory only; includes every elapsed session second, not just subscribed time. Same-second receipts are not simultaneous executions. No gaps are filled."}


def run(*,day,strategy,identities,lots=3,capital=17000.,target_net=100.,
        latency_ms=1000,window_seconds=1,max_skew_seconds=2.,
        participation_pct=25.,slippage_bps=5.,broker_profile="zerodha",
        progress=None,now=None,step_minutes=STEP_MINUTES):
    now=now or paper._now()
    chosen=date.fromisoformat(day)
    if chosen>now.astimezone(paper.IST).date():
        raise ValueError("Choose an observed date, not a future session")
    if strategy not in replay.STRATEGIES or broker_profile not in fees.BROKER_PROFILES:
        raise ValueError("Unsupported spread strategy or broker profile")
    actions=("BUY",) if strategy=="LONG_OPTION" else replay.studio.STRATEGIES[strategy]["actions"]
    if len(identities)!=len(actions) or len(set(identities))!=len(identities) or any(not fees.ID.fullmatch(x) for x in identities):
        raise ValueError("Select distinct exact option identities in the required leg order")
    if type(lots) is not int or not 1<=lots<=10:
        raise ValueError("Choose 1–10 lots")
    for value,lo,hi,label in ((capital,1000,1e7,"capital"),(target_net,0,1e6,"target net"),
        (latency_ms,0,60000,"reaction delay"),(window_seconds,1,30,"receipt window"),
        (max_skew_seconds,0,30,"leg skew"),(participation_pct,1,100,"participation"),
        (slippage_bps,0,500,"slippage")):
        paper._check(value,lo,hi,label)
    if step_minutes not in (1,5,15):
        raise ValueError("Choose 1, 5 or 15 minute decision spacing")
    coverage=_coverage(chosen,identities,now)
    anchors=_anchors(chosen,now,latency_ms,window_seconds,step_minutes)
    by_horizon={h:[] for h in HORIZONS}
    # All horizons use the same immutable first-book lookup for a decision.
    cache={}
    def lookup(identity,eligible,end,cutoff):
        key=(identity,eligible,end,cutoff)
        if key not in cache:
            cache[key]=replay._first(identity,eligible,end,cutoff)
        return cache[key]
    for i,decision in enumerate(anchors):
        cache.clear()
        for h in HORIZONS:
            if progress:
                progress(95*(i*len(HORIZONS)+HORIZONS.index(h))/max(1,len(anchors)*len(HORIZONS)),
                         f"Saved depth: decision {i+1}/{len(anchors)}, hold {h}s")
            result=replay.replay(strategy=strategy,identities=identities,decision_utc=paper._iso(decision),
                lots=lots,capital=capital,hold_seconds=h,latency_ms=latency_ms,
                window_seconds=window_seconds,max_skew_seconds=max_skew_seconds,
                participation_pct=participation_pct,slippage_bps=slippage_bps,
                broker_profile=broker_profile,now=now,first_book=lookup)
            item={"decision_utc":paper._iso(decision),"state":result["state"],
                  "net_pnl_inr":result["net_pnl_inr"],"fees_inr":result.get("total_fees_inr"),
                  "entry_delay_seconds":None,"exit_delay_seconds":None,"elapsed_seconds":None,
                  "passive_bid_entry_markout_inr":None}
            if result["entry_complete"]:
                item["entry_delay_seconds"]=_delta(item["decision_utc"],result["entry_received_utc"])
            if result["exit_complete"]:
                item["exit_delay_seconds"]=_delta(result["exit_decision_utc"],result["exit_received_utc"])
                item["elapsed_seconds"]=_delta(item["decision_utc"],result["exit_received_utc"])
                if strategy=="LONG_OPTION":
                    # Counterfactual only: assume all units entered at the
                    # observed bid at exactly the same receipt. Exit still
                    # crosses displayed depth. Never infer a passive fill.
                    entry=result["entries"][0]
                    turnover=entry["requested_units"]*entry["original_best_bid"]
                    charge=paper._fees("BUY",turnover,broker_profile)
                    item["passive_bid_entry_markout_inr"]=fees._money(
                        result["net_pnl_inr"]-entry["cashflow"]-turnover-charge)
            by_horizon[h].append(item)
    matched=set.intersection(*[
        {r["decision_utc"] for r in rows if r["net_pnl_inr"] is not None}
        for rows in by_horizon.values()]) if anchors else set()
    summaries=[]
    for h,rows in by_horizon.items():
        scored=[r for r in rows if r["net_pnl_inr"] is not None]
        net=[r["net_pnl_inr"] for r in scored]
        passive=[r["passive_bid_entry_markout_inr"] for r in scored if r["passive_bid_entry_markout_inr"] is not None]
        comparable=[r["net_pnl_inr"] for r in scored if r["decision_utc"] in matched]
        summaries.append({"hold_seconds":h,"attempted":len(rows),"scored":len(scored),
            "unscored":len(rows)-len(scored),"positive":sum(v>0 for v in net),
            "target_hits":sum(v>=target_net for v in net),"negative":sum(v<0 for v in net),
            "net":_stats(net),"matched_net":_stats(comparable),"worst_net":min(net) if net else None,
            "fees":_stats([r["fees_inr"] for r in scored]),
            "entry_delay":_stats([r["entry_delay_seconds"] for r in rows if r["entry_delay_seconds"] is not None]),
            "exit_delay":_stats([r["exit_delay_seconds"] for r in scored]),
            "roundtrip":_stats([r["elapsed_seconds"] for r in scored]),
            "passive_bid_entry_markout":_stats(passive),
            "passive_target_hits":sum(v>=target_net for v in passive) if passive else None,
            "states":dict(Counter(r["state"] for r in rows)),"observations":rows})
    if progress:
        progress(100,"Original-depth speed diagnostics complete")
    return {"day_ist":day,"strategy":strategy,"identities":identities,"lots":lots,"capital":capital,
            "target_net":target_net,"latency_ms":latency_ms,"window_seconds":window_seconds,
            "participation_pct":participation_pct,"slippage_bps":slippage_bps,
            "max_skew_seconds":max_skew_seconds,"broker_profile":broker_profile,
            "decision_count":len(anchors),"matched_decisions":len(matched),"rows":summaries,
            "coverage":coverage,"step_minutes":step_minutes,
            "actual_fills_observed":False,"broker_margin_verified":False,
            "warning":"Fixed clock diagnostic for selected exact contracts, not an entry strategy or unbiased backtest. "
            "First received original books after assumed reaction delay; observed quote delays are not broker execution times. "
            "Marketable depth and fees are modeled, passive bid entry is a conditional counterfactual. "
            "Partial or missing baskets are unscored, not zero losses. Broker margin, order queue, legging and actual fill latency are unverified."}
