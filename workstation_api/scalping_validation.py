"""Matched historical original-depth scalping comparison.

Fixed daily contract selection from a hash-verified prior chain receipt;
three frozen rules; first later original book; strict censoring; no orders,
network, retrospective choice by returns, or fabricated depth.
"""
from __future__ import annotations
from collections import Counter
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from statistics import mean
import json
import os
import re
import sqlite3
import uuid

from . import advanced_options as ao, depth_replay as replay, liquidity_spreads as fees
from . import manual_options_workflow as mw, paper_execution as paper, service

VERSION = "matched-depth-scalping-v1"
RULES = ("RANGE_REVERSION", "MEAN_REVERSION", "EMA_CROSSOVER")
ID = re.compile(r"scalp_[0-9a-f]{20}")
MAX_DAYS = 60
# No actual trade quota. An explicit resource guard censors unusually long days.
MAX_ATTEMPTS = 100


def _day(value):
    d = date.fromisoformat(value)
    if d.isoformat() != value:
        raise ValueError("Choose exact ISO session dates")
    return d


def _select(snapshot, day, *, capital, lots, target_premium, tolerance, max_spread_bps, fee_floor_per_side):
    if not snapshot or snapshot.get("market_master_fresh") is not True:
        return None
    expiry = snapshot.get("expiry")
    if not isinstance(expiry,str) or _day(expiry) < day:
        return None
    chosen = {}
    for side in ("CE","PE"):
        candidates = []
        for r in snapshot["contracts"]:
            if (r.get("option_type") != side or r.get("expiry") != expiry
                or r.get("contract_master_verified") is not True
                or not fees.ID.fullmatch(str(r.get("identity","")))
                or not ao.positive(r.get("strike"))
                or type(r.get("lot_size")) is not int or r["lot_size"] <= 0):
                continue
            units=lots*r["lot_size"]
            bid,ask=mw._quote(r,"bid",units),mw._quote(r,"ask",units)
            if bid is None or ask is None or abs(ask-target_premium)>tolerance:
                continue
            spread=10000*(ask-bid)/((ask+bid)/2)
            # Broker fee estimate is checked again at actual simulated entry.
            if spread>max_spread_bps or ask*units+fee_floor_per_side>capital:
                continue
            candidates.append((abs(ask-target_premium),spread,abs(r["strike"]-snapshot["underlying_spot"]),
                               r["identity"],r))
        if not candidates:
            return None
        r=min(candidates,key=lambda c:c[:4])[-1]
        chosen[side]={k:r[k] for k in ("identity","option_type","expiry","strike","lot_size","bid","ask")}
    if chosen["CE"]["identity"]==chosen["PE"]["identity"]:
        return None
    return chosen


def _chain_at(day, cutoff):
    """Nearest observed expiry, latest prior receipt within 120 seconds.
    No fallback to a different receipt based on subsequent profitability.
    """
    try:
        with closing(ao._read_database()) as db:
            db.execute("PRAGMA query_only=ON")
            raw=db.execute("""SELECT captured_utc,snapshot_sha256,normalized_json
                FROM option_chain_observations WHERE underlying='BANKNIFTY'
                AND expiry>=? AND captured_utc>=? AND captured_utc<=?
                ORDER BY expiry ASC,captured_utc DESC LIMIT 1""",
                (day.isoformat(),mw._iso(cutoff-timedelta(seconds=120)),mw._iso(cutoff))).fetchone()
        return (mw._snapshot(raw),raw[1]) if raw else (None,None)
    except (sqlite3.OperationalError,OSError):
        return None,None


def _index(day, now):
    try:
        rows=replay._bars(day.isoformat(),now)
    except (sqlite3.OperationalError,OSError):
        return [],"index_source_unavailable"
    # The depth replay source only emits decisions before 15:30, so the
    # 15:29 candle is not needed. Insufficient early receipt data is blocked.
    expected=[datetime.combine(day,time(9,15),paper.IST)+timedelta(minutes=i) for i in range(374)]
    if len(rows)!=len(expected) or any(ao.timestamp(r["timestamp_utc"])!=t for r,t in zip(rows,expected)):
        return rows,"partial_or_missing_index_minutes"
    if any(b["decision"]<=a["decision"] for a,b in zip(rows,rows[1:])):
        return rows,"nonchronological_index_receipts"
    return rows,None


def _replay_day(rows, selection, *, rule, start, close, now, capital, lots, hold_minutes,
                latency_ms, window_seconds, participation_pct, slippage_bps, broker_profile,
                fee_floor_per_side, daily_loss_limit_pct):
    threshold=.2 if rule=="RANGE_REVERSION" else 1.5
    signals=replay.rule_signals(rows,rule,9,21,30,threshold)
    # Reserve worst allowed entry and exit receipt windows before session end.
    last_decision=close-timedelta(minutes=hold_minutes,
                 seconds=2*(latency_ms/1000+window_seconds)+1)
    candidates=[(r["decision"],sig) for r,sig in zip(rows,signals)
                if sig in ("UP","DOWN") and start<=r["decision"]<=last_decision]
    cash=capital
    available=start
    trades=[]
    attempts=0
    rejected=0
    suppressed=0
    terminal="complete"
    reasons=Counter()
    peak=capital
    max_drawdown=0.
    for stamp,side in candidates:
        if stamp<=available:
            suppressed+=1
            continue
        if cash<1000 or cash-capital<=-capital*daily_loss_limit_pct/100:
            terminal="loss_budget_stop"
            break
        if attempts>=MAX_ATTEMPTS:
            terminal="attempt_resource_limit_censored"
            break
        leg=selection["CE" if side=="UP" else "PE"]
        attempts+=1
        item=replay.replay(strategy="LONG_OPTION",identities=[leg["identity"]],
             decision_utc=paper._iso(stamp),lots=lots,capital=cash,hold_minutes=hold_minutes,
             latency_ms=latency_ms,window_seconds=window_seconds,participation_pct=participation_pct,
             slippage_bps=slippage_bps,broker_profile=broker_profile,now=now,
             fee_floor_per_side=fee_floor_per_side)
        state=item["state"]
        if any((r.get("identity"),r.get("option_type"),r.get("expiry"),r.get("strike"),r.get("lot_size"))!=
               (leg["identity"],leg["option_type"],leg["expiry"],leg["strike"],leg["lot_size"])
               for r in item["entries"]+item["exits"]):
            terminal="contract_terms_mismatch_censored"
            reasons[terminal]+=1
            break
        if state=="insufficient_hypothetical_risk_budget":
            rejected+=1
            reasons[state]+=1
            available=ao.timestamp(item["entry_received_utc"])
            continue
        if item["net_pnl_inr"] is None:
            # Even missing entry evidence is not a confirmed no-fill.
            terminal="unresolved_execution_censored"
            reasons[state]+=1
            reasons.update(m["reason"] for m in item.get("missing",[]))
            break
        pnl=item["net_pnl_inr"]
        cash=fees._money(cash+pnl)
        peak=max(peak,cash)
        max_drawdown=max(max_drawdown,peak-cash)
        trades.append({"signal":side,"decision_utc":item["decision_utc"],
                       "identity":leg["identity"],"entry_utc":item["entry_received_utc"],
                       "exit_utc":item["exit_received_utc"],"net_pnl_inr":pnl,
                       "fees_inr":item["total_fees_inr"],
                       "entry_book_sha256":item["entries"][0]["book_pair_sha256"],
                       "exit_book_sha256":item["exits"][0]["book_pair_sha256"]})
        available=ao.timestamp(item["exit_received_utc"])
    complete=terminal in ("complete","loss_budget_stop")
    return {"rule":rule,"state":terminal,"complete":complete,"signals":len(candidates),
            "attempts":attempts,"suppressed_overlaps":suppressed,"known_budget_rejections":rejected,
            "completed":len(trades),"resolved_subset_net_inr":fees._money(cash-capital) if trades else None,
            "session_net_inr":fees._money(cash-capital) if complete else None,
            "max_closed_trade_drawdown_inr":max_drawdown,"reasons":dict(reasons),"trades":trades}


def _aggregate(days):
    # Matched evaluation uses only dates where all three strategies have
    # complete observations. This subset is conditional and may be biased.
    matched=[d for d in days if d.get("matched_complete")]
    result=[]
    for rule in RULES:
        reports=[next(r for r in d["rules"] if r["rule"]==rule) for d in matched]
        trades=[t for r in reports for t in r["trades"]]
        pnls=[t["net_pnl_inr"] for t in trades]
        gains=sum(x for x in pnls if x>0)
        losses=-sum(x for x in pnls if x<0)
        daily=[r["session_net_inr"] for r in reports]
        fees_paid=sum(t["fees_inr"] for t in trades)
        gross=[t["net_pnl_inr"]+t["fees_inr"] for t in trades]
        # Stress adds another fixed 25 or 50 INR per completed round trip.
        result.append({"rule":rule,"matched_sessions":len(reports),"trades":len(trades),
                       "wins":sum(x>0 for x in pnls),"losses":sum(x<0 for x in pnls),
                       "flat":sum(x==0 for x in pnls),
                       "win_rate_pct":100*sum(x>0 for x in pnls)/len(pnls) if pnls else None,
                       "net_pnl_inr":fees._money(sum(daily)) if daily else None,
                       "average_net_inr":mean(pnls) if pnls else None,
                       "gross_before_fees_inr":fees._money(sum(gross)) if pnls else None,
                       "fees_inr":fees._money(fees_paid) if pnls else None,
                       "profit_factor":gains/losses if losses>0 else None,
                       "positive_sessions":sum(x>0 for x in daily),
                       "negative_sessions":sum(x<0 for x in daily),
                       "stress_extra_25_inr":fees._money(sum(daily)-25*len(pnls)) if daily else None,
                       "stress_extra_50_inr":fees._money(sum(daily)-50*len(pnls)) if daily else None,
                       "worst_session_inr":min(daily) if daily else None,
                       "max_intraday_closed_drawdown_inr":max((r["max_closed_trade_drawdown_inr"] for r in reports),default=None)})
    return result


def run(*,start_date,end_date,capital=17000.,lots=3,target_premium=180.,tolerance=60.,
        max_spread_bps=150.,hold_minutes=5,latency_ms=1000,window_seconds=30,
        participation_pct=25.,slippage_bps=5.,broker_profile="zerodha",fee_floor_per_side=0.,
        daily_loss_limit_pct=10.,progress=None,now=None,save=True):
    now=now or paper._now()
    first,last=_day(start_date),_day(end_date)
    if not first<=last<now.astimezone(paper.IST).date() or (last-first).days>=MAX_DAYS:
        raise ValueError("Choose at most 60 calendar days, ending before today's IST date")
    for v,lo,hi,label in ((capital,1000,1e7,"capital"),(target_premium,10,20000,"premium"),
         (tolerance,0,5000,"tolerance"),(max_spread_bps,1,10000,"spread"),
         (latency_ms,0,60000,"latency"),(window_seconds,1,180,"window"),
         (participation_pct,1,100,"participation"),(slippage_bps,0,500,"slippage"),
         (fee_floor_per_side,0,1000,"minimum per-side fee"),(daily_loss_limit_pct,1,100,"daily loss budget")):
        paper._check(v,lo,hi,label)
    if type(lots) is not int or not 1<=lots<=50 or hold_minutes not in (1,3,5,10,15):
        raise ValueError("Choose whole lots and a fixed 1/3/5/10/15 minute hold")
    if broker_profile not in fees.BROKER_PROFILES:
        raise ValueError("Unsupported fee profile")
    days=[first+timedelta(days=i) for i in range((last-first).days+1)
          if (first+timedelta(days=i)).weekday()<5]
    cut=int(.7*len(days))
    records=[]
    for i,day in enumerate(days):
        if progress:
            progress(5+90*i/max(1,len(days)),"Comparing fixed rules on saved source receipts")
        start=datetime.combine(day,time(9,45),paper.IST)
        close=datetime.combine(day,time(15,30),paper.IST)
        rows,reason=_index(day,now)
        record={"date":day.isoformat(),"cohort":"development" if i<cut else "evaluation",
                "index_minutes":len(rows),"state":reason or "checking_selection",
                "matched_complete":False,"rules":[]}
        records.append(record)
        if reason:
            continue
        chain,digest=_chain_at(day,start)
        selection=_select(chain,day,capital=capital,lots=lots,target_premium=target_premium,
                          tolerance=tolerance,max_spread_bps=max_spread_bps,
                          fee_floor_per_side=fee_floor_per_side)
        if not selection:
            record["state"]="prior_chain_or_contract_selection_unavailable"
            continue
        record.update(selection=selection,selection_receipt_utc=chain["received_utc"],
                      selection_sha256=digest,state="replayed")
        record["rules"]=[_replay_day(rows,selection,rule=rule,start=start,close=close,now=now,
                 capital=capital,lots=lots,hold_minutes=hold_minutes,latency_ms=latency_ms,
                 window_seconds=window_seconds,participation_pct=participation_pct,
                 slippage_bps=slippage_bps,broker_profile=broker_profile,
                 fee_floor_per_side=fee_floor_per_side,daily_loss_limit_pct=daily_loss_limit_pct)
                 for rule in RULES]
        record["matched_complete"]=all(r["complete"] for r in record["rules"])
        if not record["matched_complete"]:
            record["state"]="unresolved_execution"
    development=[d for d in records if d["cohort"]=="development"]
    evaluation=[d for d in records if d["cohort"]=="evaluation"]
    matched_eval=sum(d["matched_complete"] for d in evaluation)
    # Never declare a profitable strategy: this is one historical conditional
    # comparison; a new, preregistered prospective sample is still required.
    report={"version":VERSION,"generated_utc":paper._iso(now),"start_date":start_date,
            "end_date":end_date,"state":"conditional_comparison" if matched_eval else "insufficient_evaluation_evidence",
            "requested_weekdays":len(records),"matched_days":sum(d["matched_complete"] for d in records),
            "development":_aggregate(development),"evaluation":_aggregate(evaluation),
            "evaluation_requested_weekdays":len(evaluation),"evaluation_matched_days":matched_eval,
            "day_states":dict(Counter(d["state"] for d in records)),
            "settings":{"capital":capital,"lots":lots,"target_premium":target_premium,"tolerance":tolerance,
              "max_spread_bps":max_spread_bps,"hold_minutes":hold_minutes,"latency_ms":latency_ms,
              "window_seconds":window_seconds,"participation_pct":participation_pct,"slippage_bps":slippage_bps,
              "broker_profile":broker_profile,"fee_floor_per_side":fee_floor_per_side,
              "daily_loss_limit_pct":daily_loss_limit_pct},
            "days":records,"orders_enabled":False,
            "warning":"Requested weekdays are not an official exchange calendar. Missing days, contracts and unresolved attempts remain censored; matched complete subsets may be selection-biased. Each rule/day starts with independent research capital; totals are not a compounded account. Fixed 09:45 IST prior receipt selection, 70/30 chronological weekday split, no parameter optimization. Original displayed depth with fee floor and latency is conditional replay, not real fills or a proven trading edge. A loss-budget stop can be exceeded by a gap."}
    if save:
        study_id="scalp_"+uuid.uuid4().hex[:20]
        report["study_id"]=study_id
        root=_root()
        root.mkdir(parents=True,exist_ok=True)
        temp=root/(study_id+".tmp")
        try:
            temp.write_text(json.dumps(report,allow_nan=False,separators=(",",":")),encoding="utf-8")
            os.replace(temp,root/(study_id+".json"))
        finally:
            temp.unlink(missing_ok=True)
    return report


def _root():
    return Path(service.DATA)/"trading_cockpit"/"scalping_studies"


def saved(study_id):
    if not ID.fullmatch(study_id):
        raise ValueError("Invalid scalping study ID")
    path=_root()/(study_id+".json")
    if path.is_symlink() or not path.is_file() or path.stat().st_size>20_000_000:
        raise ValueError("Saved scalping study unavailable")
    value=json.loads(path.read_text(encoding="utf-8"))
    if value.get("study_id")!=study_id or value.get("version")!=VERSION:
        raise ValueError("Saved study identity mismatch")
    return value


def latest():
    root=_root()
    if not root.is_dir() or root.is_symlink():
        return {"study":None}
    paths=[p for p in root.glob("scalp_*.json") if ID.fullmatch(p.stem) and p.is_file() and not p.is_symlink()]
    return {"study":saved(max(paths,key=lambda p:p.stat().st_mtime_ns).stem) if paths else None}
