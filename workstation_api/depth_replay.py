"""Original-depth historical replay shared by manual and rule-based research.

Deterministic first-receipt windows, no selection of best later quotes.
Basket results are conditional synchronized all-leg observations, not a
simulation of sequential short-leg execution or verified broker margin.
"""
from __future__ import annotations
from contextlib import closing
from datetime import datetime, date, time, timedelta, timezone
from statistics import mean, pstdev
import sqlite3
from . import advanced_options as ao, liquidity_spreads as fees
from . import option_spread_studio as studio, paper_execution as paper
from . import spread_scanner, strategy_lab

STRATEGIES=("LONG_OPTION",*studio.STRATEGIES.keys())


def _first(identity,eligible,end,now):
    try:
        with closing(ao._read_database()) as db:
            raw=db.execute("""SELECT received_utc,book_json,packet_pair_sha256
                FROM live_depth_books WHERE identity=? AND received_utc>=?
                AND received_utc<=? ORDER BY received_utc LIMIT 1""",
                (identity,paper._iso(eligible),paper._iso(min(end,now)))).fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc) or "unable to open database file" in str(exc):
            return None,"source_table_unavailable"
        raise
    if raw is None:
        return None,"no_book_in_fixed_window"
    stamp,body,digest=raw
    verified=spread_scanner._original_book(identity,stamp,body,digest)
    if not verified:
        return None,"first_book_failed_original_validation"
    book,stats,features=verified
    item=studio._book_row(book,stats,features)
    if not item or not eligible<=item["stamp"]<=min(end,now):
        return None,"invalid_first_book_time_or_terms"
    if not paper._regular(item["stamp"]) or item["stamp"]>=paper._close(item["stamp"],item["expiry"]):
        return None,"book_outside_regular_session_or_expired"
    return {**item,"digest":digest},None


def _execute(row,action,units,participation_pct,slippage_bps,profile):
    result=paper.marketable_walk(row["book"],action,units,row["lot_size"],
         1e9 if action=="BUY" else 0.,participation_pct/100,slippage_bps)
    cost=paper._fees(action,result["turnover"],profile)
    return {"identity":row["identity"],"option_type":row["option_type"],"strike":row["strike"],
       "expiry":row["expiry"],"action":action,"lot_size":row["lot_size"],
       "received_utc":row["received_utc"],"book_pair_sha256":row["digest"],
       "requested_units":units,"displayed_fill_units":result["units"],
       "vwap":result["vwap"],"turnover":result["turnover"],"fees":cost,
       "cashflow":fees._money((1 if action=="SELL" else -1)*result["turnover"]-cost)}


def replay(*,strategy,identities,decision_utc,lots=1,capital=50000.,hold_minutes=5,
           latency_ms=1000,window_seconds=60,max_skew_seconds=2.,
           participation_pct=25.,slippage_bps=5.,broker_profile="zerodha",
           now=None,exit_decision=None):
    now=now or paper._now()
    if strategy not in STRATEGIES or broker_profile not in fees.BROKER_PROFILES:
        raise ValueError("Unsupported replay strategy or brokerage profile")
    actions=("BUY",) if strategy=="LONG_OPTION" else studio.STRATEGIES[strategy]["actions"]
    if len(identities)!=len(actions) or len(set(identities))!=len(identities) or any(not fees.ID.fullmatch(i) for i in identities):
        raise ValueError("Choose distinct exact recorded NSE_FNO identities in the strategy leg order")
    if not isinstance(lots,int) or isinstance(lots,bool) or not 1<=lots<=50:
        raise ValueError("Select 1–50 lots")
    for v,lo,hi,label in ((capital,1000,1e7,"capital"),(hold_minutes,1,1440,"holding minutes"),
                         (latency_ms,0,60000,"latency"),(window_seconds,1,180,"observation window"),
                         (max_skew_seconds,0,30,"leg receipt skew"),(participation_pct,1,100,"participation"),
                         (slippage_bps,0,500,"slippage")):
        paper._check(v,lo,hi,label)
    decision=ao.timestamp(decision_utc)
    if decision>now or not paper._regular(decision):
        raise ValueError("Choose an observed historical regular-session decision time with timezone")
    ready=decision+timedelta(microseconds=max(1,round(latency_ms*1000)))
    close=datetime.combine(decision.astimezone(paper.IST).date(),time(15,30),paper.IST).astimezone(timezone.utc)
    end=min(ready+timedelta(seconds=window_seconds),close-timedelta(microseconds=1))
    if exit_decision is not None:
        end=min(end,exit_decision-timedelta(microseconds=1))
    result={"strategy":strategy,"decision_utc":paper._iso(decision),"ready_utc":paper._iso(ready),
        "state":"entry_unobservable","entries":[],"exits":[],"missing":[],"net_pnl_inr":None,
        "entry_complete":False,"exit_complete":False,"entry_risk_proxy":None,
        "broker_margin_verified":False,"broker_orders_enabled":False,
        "warning":"Conditional quote-depth replay, not actual orders. Multi-leg results require all "
          "displayed legs within the specified receipt skew; legging risk, actual passive queue fills, "
          "expiry settlement and broker margin are not modeled. Partial baskets are censored, not zero losses."}
    if end<ready:
        result["state"]="entry_window_cancelled"
        return result
    if now<end:
        result["state"]="future_entry_window_not_complete"
        return result
    entry=[]
    for identity in identities:
        row,error=_first(identity,ready,end,now)
        if error:
            result["missing"].append({"identity":identity,"stage":"entry","reason":error})
        else:
            entry.append(row)
    if len(entry)!=len(identities):
        return result
    if strategy!="LONG_OPTION":
        studio._validate_structure(strategy,entry)
    units=lots*entry[0]["lot_size"]
    stamps=[r["stamp"] for r in entry]
    skew=(max(stamps)-min(stamps)).total_seconds()
    result["entry_skew_seconds"]=skew
    result["entry_received_utc"]=paper._iso(max(stamps))
    result["entries"]=[_execute(row,action,units,participation_pct,slippage_bps,broker_profile)
                       for row,action in zip(entry,actions)]
    if skew>max_skew_seconds:
        result["state"]="entry_leg_skew_exceeded"
        return result
    if any(r["displayed_fill_units"]!=units for r in result["entries"]):
        result["state"]="entry_partial_or_insufficient_depth"
        return result
    entry_cash=fees._money(sum(r["cashflow"] for r in result["entries"]))
    gross_buys=sum(-r["cashflow"] for r in result["entries"] if r["action"]=="BUY")
    if strategy=="LONG_OPTION":
        max_loss=-entry_cash
    else:
        legs=[{**r,"action":a} for r,a in zip(entry,actions)]
        gross=sum((1 if r["action"]=="SELL" else -1)*r["turnover"] for r in result["entries"])
        max_loss=studio._terminal_payoff(legs,gross,sum(r["fees"] for r in result["entries"]),units)["max_loss_before_expiry_settlement_inr"]
    risk=fees._money(max(max_loss,gross_buys))
    result["entry_risk_proxy"]=risk
    result["entry_cashflow"]=entry_cash
    result["theoretical_max_loss_before_settlement"]=max_loss
    if risk>capital:
        result["state"]="insufficient_hypothetical_risk_budget"
        return result
    result["entry_complete"]=True
    due=exit_decision if exit_decision is not None else max(stamps)+timedelta(minutes=hold_minutes)
    exit_ready=due+timedelta(microseconds=max(1,round(latency_ms*1000)))
    exit_end=min(exit_ready+timedelta(seconds=window_seconds),close-timedelta(microseconds=1))
    result["exit_decision_utc"]=paper._iso(due)
    result["exit_ready_utc"]=paper._iso(exit_ready)
    result["exit_window_end_utc"]=paper._iso(exit_end)
    if exit_end<exit_ready or due<=max(stamps):
        result["state"]="exit_window_unavailable_before_close"
        return result
    if now<exit_end:
        result["state"]="future_exit_window_not_complete"
        return result
    exit_rows=[]
    for prior in entry:
        row,error=_first(prior["identity"],exit_ready,exit_end,now)
        if not error and (row["expiry"],row["strike"],row["option_type"],row["lot_size"])!=(
            prior["expiry"],prior["strike"],prior["option_type"],prior["lot_size"]):
            error="exit_contract_terms_changed"
        if error:
            result["missing"].append({"identity":prior["identity"],"stage":"exit","reason":error})
        else:
            exit_rows.append(row)
    if len(exit_rows)!=len(entry):
        result["state"]="exit_unobservable"
        return result
    exit_stamps=[r["stamp"] for r in exit_rows]
    result["exit_skew_seconds"]=(max(exit_stamps)-min(exit_stamps)).total_seconds()
    result["exit_received_utc"]=paper._iso(max(exit_stamps))
    result["exits"]=[_execute(row,"SELL" if a=="BUY" else "BUY",units,
                               participation_pct,slippage_bps,broker_profile) for row,a in zip(exit_rows,actions)]
    if result["exit_skew_seconds"]>max_skew_seconds:
        result["state"]="exit_leg_skew_exceeded"
        return result
    if any(r["displayed_fill_units"]!=units for r in result["exits"]):
        result["state"]="exit_partial_or_insufficient_depth"
        return result
    result["exit_complete"]=True
    result["state"]="complete_conditional_quote_replay"
    result["net_pnl_inr"]=fees._money(entry_cash+sum(r["cashflow"] for r in result["exits"]))
    result["total_fees_inr"]=fees._money(sum(r["fees"] for r in result["entries"]+result["exits"]))
    return result


def _bars(day,now):
    if date.fromisoformat(day).isoformat()!=day:
        raise ValueError("Choose an exact IST date")
    with closing(ao._read_database()) as db:
        records=db.execute("""SELECT minute_utc,close,last_received_utc FROM live_minute_bars
            WHERE identity='INDEX:BANKNIFTY' AND session_ist=? ORDER BY minute_utc LIMIT 376""",
            (day,)).fetchall()
    out=[]
    for minute,price,received in records:
        t=ao.timestamp(minute)
        decision=max(t+timedelta(minutes=1),ao.timestamp(received))
        if (paper._regular(t) and decision<=now and paper._regular(decision)
                and ao.positive(price) is not None):
            out.append({"timestamp_utc":minute,"close":price,"session_ist":day,"decision":decision})
    return out


from . import range_research


def rule_signals(rows,rule,fast,slow,lookback,threshold):
    if rule=="EMA_CROSSOVER":
        return strategy_lab.crossover_events(rows,fast,slow)[0]
    if rule not in ("MOMENTUM","MEAN_REVERSION","RANGE_REVERSION") or not isinstance(lookback,int) or not 2<=lookback<=150:
        raise ValueError("Choose supported rule and lookback 2–150")
    paper._check(threshold,.001,.49 if rule=="RANGE_REVERSION" else 100,"rule threshold")
    if rule=="RANGE_REVERSION":
        lookback=range_research.LOOKBACK+1
    signals=["HOLD"]*len(rows)
    segment=[]
    last="HOLD"
    for i,r in enumerate(rows):
        if i and not strategy_lab._contiguous(rows[i-1],r):
            segment=[]
            last="HOLD"
        value=r["close"]
        if len(segment)>=lookback:
            recent=segment[-lookback:]
            if rule=="RANGE_REVERSION":
                state=range_research.reversion_signal(recent,value,threshold)
            elif rule=="MOMENTUM":
                metric=100*(value/recent[0]-1)
                state="UP" if metric>=threshold else "DOWN" if metric<=-threshold else "HOLD"
            else:
                sigma=pstdev(recent)
                metric=(value-mean(recent))/sigma if sigma>0 else 0.
                state="DOWN" if metric>=threshold else "UP" if metric<=-threshold else "HOLD"
            if state!="HOLD" and state!=last:
                signals[i]=state
            last=state
        segment.append(value)
    return signals


def rule_replay(*,day,call_identity,put_identity,rule="EMA_CROSSOVER",fast=9,slow=21,
                lookback=10,threshold=.1,hold_rule="FIXED",hold_minutes=5,lots=1,
                capital=50000.,latency_ms=1000,window_seconds=60,
                participation_pct=25.,slippage_bps=5.,broker_profile="zerodha",
                now=None):
    now=now or paper._now()
    if call_identity==put_identity or not all(fees.ID.fullmatch(i) for i in (call_identity,put_identity)):
        raise ValueError("Choose distinct exact historical CE and PE identities")
    if hold_rule not in ("FIXED","FLIP"):
        raise ValueError("Choose fixed hold or hold until opposite signal")
    paper._check(capital,1000,1e7,"initial capital")
    rows=_bars(day,now)
    if len(rows)<3:
        return {"state":"insufficient_observed_index_bars","bars":len(rows),"signals":0,"trades":[],
                "completed":0,"net_pnl_inr":None,"broker_orders_enabled":False}
    signals=rule_signals(rows,rule,fast,slow,lookback,threshold)
    entries=[(r["decision"],sig) for r,sig in zip(rows,signals) if sig in ("UP","DOWN")]
    # Receipt-based decisions must remain chronological. Never reorder
    # late-arriving bars into a different signal series.
    if any(b[0]<=a[0] for a,b in zip(entries,entries[1:])):
        raise ValueError("Nonchronological source receipts; cannot establish causal signal decisions")
    cash=capital
    trades=[]
    available_after=datetime.min.replace(tzinfo=timezone.utc)
    unresolved=False
    flip_pending=None
    close=datetime.combine(date.fromisoformat(day),time(15,30),paper.IST).astimezone(timezone.utc)
    for i,(signal_time,direction) in enumerate(entries):
        if len(trades)>=50:
            break
        decision=signal_time
        if signal_time<=available_after:
            if hold_rule!="FLIP" or flip_pending!=signal_time:
                continue
            decision=available_after+timedelta(microseconds=1)
            if i+1<len(entries) and entries[i+1][0]<=decision:
                continue  # An intervening signal supersedes the pending flip.
        exit_at=None
        if hold_rule=="FLIP":
            exit_at=next((stamp for stamp,other in entries[i+1:] if other!=direction),None)
            if exit_at is None:
                exit_at=close-timedelta(seconds=window_seconds+latency_ms/1000+1)
            if exit_at<=decision:
                continue
        item=replay(strategy="LONG_OPTION",identities=[call_identity if direction=="UP" else put_identity],
                    decision_utc=paper._iso(decision),lots=lots,capital=cash,hold_minutes=hold_minutes,
                    latency_ms=latency_ms,window_seconds=window_seconds,participation_pct=participation_pct,
                    slippage_bps=slippage_bps,broker_profile=broker_profile,now=now,exit_decision=exit_at)
        item["signal"]=direction
        item["signal_decision_utc"]=paper._iso(signal_time)
        trades.append(item)
        if item["entries"] and item["entries"][0]["option_type"]!=("CE" if direction=="UP" else "PE"):
            raise ValueError("Selected historical identity does not match the signal option side")
        if item["net_pnl_inr"] is not None:
            cash=fees._money(cash+item["net_pnl_inr"])
            item["cash_after_completed_trade"]=cash
            available_after=ao.timestamp(item["exit_received_utc"])
            flip_pending=exit_at if hold_rule=="FLIP" else None
            if cash<1000:
                break
        elif item["entry_complete"] or item["state"] in ("entry_partial_or_insufficient_depth","future_entry_window_not_complete"):
            unresolved=True
            break  # Never reuse capital after an ambiguous possible fill.
        else:
            available_after=decision+timedelta(milliseconds=latency_ms,seconds=window_seconds)
    completed=[t for t in trades if t["net_pnl_inr"] is not None]
    return {"state":"unresolved_execution" if unresolved else "conditional_replay_complete",
       "day":day,"rule":rule,"hold_rule":hold_rule,"bars":len(rows),"signals":len(entries),
       "trades":trades,"completed":len(completed),"unresolved":unresolved,
       "completed_subset_net_pnl_inr":fees._money(sum(t["net_pnl_inr"] for t in completed)) if completed else None,
       "net_pnl_inr":fees._money(cash-capital) if completed and not unresolved else None,
       "positive":sum(t["net_pnl_inr"]>0 for t in completed),
       "negative":sum(t["net_pnl_inr"]<0 for t in completed),
       "broker_orders_enabled":False,
       "warning":"Fixed preselected historical identities, completed observed index bars, no overlapping positions. "
         "Flip re-entry waits for the prior close and rejects superseded signals. "
         "Censored trades stop reuse of possibly committed capital. At most 50 attempts. "
         "This is conditional observed-depth replay, not an out-of-sample profitability certificate."}
