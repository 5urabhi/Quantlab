"""Bounded, causal candidate selection on saved original BANKNIFTY evidence.

This is an unvalidated research rule. Scenario returns are assumptions, not
probabilities, expected returns, actual fills or advice to execute orders.
"""
from collections import Counter
from contextlib import closing
from datetime import date, datetime, time, timedelta
from hashlib import sha256
from math import sqrt, isfinite
import json
import sqlite3

from . import auto_option_depth as recorder, advanced_options as ao
from . import depth_replay as replay, paper_execution as paper, trading_cockpit as trend

VERSION = "prospective_ema_rsi_atr_bsm_v1"
MAX_BOOK_AGE = 8
MAX_CHAIN_AGE = 60
MAX_SKEW = 2
MAX_CONTRACTS = 200
MAX_PER_SIDE = 12
MIN_RECEIPTS = 3
PARTICIPATION = 25.
SLIPPAGE = 5.
LATENCY_MS = 1000
WINDOW_SECONDS = 5
RATE = .065
DIVIDEND = 0.


def latest_book(db, identity, now):
    raw = db.execute("""SELECT received_utc,book_json,packet_pair_sha256
        FROM live_depth_books WHERE identity=? AND received_utc>=? AND received_utc<=?
        ORDER BY received_utc DESC LIMIT 1""",
        (identity,paper._iso(now-timedelta(seconds=MAX_BOOK_AGE)),paper._iso(now))).fetchone()
    if not raw:
        return None
    stamp,body,digest=raw
    original=replay.spread_scanner._original_book(identity,stamp,body,digest)
    if not original:
        return None
    item=replay.studio._book_row(*original)
    if not item or not 0<=(now-item["stamp"]).total_seconds()<=MAX_BOOK_AGE:
        return None
    if not paper._regular(item["stamp"]) or item["stamp"]>=paper._close(item["stamp"],item["expiry"]):
        return None
    return {**item,"digest":digest}


def _activity(db, identity, now, lot_size):
    cutoff=paper._iso(now-timedelta(seconds=120)); stop=paper._iso(now)
    receipts=db.execute("""SELECT COUNT(*),COUNT(DISTINCT packet_pair_sha256)
        FROM live_depth_books WHERE identity=? AND received_utc>=? AND received_utc<=?""",
        (identity,cutoff,stop)).fetchone()
    if receipts[0]<MIN_RECEIPTS or receipts[1]<2:
        return None,"insufficient_recent_depth"
    try:
        # Bounded last 120 seconds for this exact indexed identity.
        trades=db.execute("""SELECT COUNT(DISTINCT exchange_trade_utc),
            MAX(volume)-MIN(volume) FROM dhan_option_live_events WHERE identity=? AND kind='quote'
            AND received_utc>=? AND received_utc<=? AND exchange_trade_utc>=? AND exchange_trade_utc<=?
            AND volume>=0""",(identity,cutoff,stop,cutoff,stop)).fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc):
            raise
        return None,"missing_original_trade_feed"
    if trades[0]<2 or (trades[1] or 0)<lot_size:
        return None,"insufficient_recent_trade_activity"
    return {"receipts_120s":receipts[0],"distinct_books_120s":receipts[1],
            "distinct_trade_times_120s":trades[0],"volume_range_120s":trades[1]},None


def _source(now, config):
    day=now.astimezone(paper.IST).date().isoformat()
    with recorder.LOCK:
        subscribed=[dict(row) for row in recorder.STATE.get("contracts",[])][:MAX_CONTRACTS]
    subscribed={row["identity"]:row for row in subscribed if replay.fees.ID.fullmatch(row.get("identity",""))}
    report={"source_cutoff_utc":paper._iso(now),"direction":"NO_TRADE","rejections":{},
            "subscribed_contracts":len(subscribed),"valid_contracts":0}
    if not paper._regular(now):
        return report,[],"outside_regular_session"
    if not subscribed:
        return report,[],"no_subscribed_depth_contracts"
    expiries=sorted({row["expiry"] for row in subscribed.values() if row.get("expiry","")>=day})
    if not expiries:
        return report,[],"no_current_expiry"
    expiry=expiries[0]
    try:
        with closing(ao._read_database()) as db:
            db.execute("BEGIN")
            cutoff=paper._iso(now.replace(second=0,microsecond=0))
            bars=db.execute("""SELECT minute_utc,session_ist,open,high,low,close
                FROM live_minute_bars WHERE identity='INDEX:BANKNIFTY' AND session_ist=?
                AND minute_utc<? AND last_received_utc<=? ORDER BY minute_utc DESC LIMIT 120""",
                (day,cutoff,paper._iso(now))).fetchall()
            if not bars:
                return report,[],"no_completed_index_bars"
            rows=[dict(zip(("timestamp_utc","session_ist","open","high","low","close"),row),volume=0)
                  for row in reversed(bars)]
            signal=trend.snapshot("INDEX:BANKNIFTY",rows,now=now,include_chart=False)
            report.update(direction=signal["direction"],bar_utc=signal["last_observed_utc"],
                source_age_seconds=signal["source_age_seconds"],ema9=signal["ema9"],ema21=signal["ema21"],
                rsi14=signal["rsi14"],atr14=signal["atr14"],contiguous_bars=signal["contiguous_session_bars"])
            if signal["quote_mode"]!="RECENT_LOCAL_CANDLE_NOT_VERIFIED_LIVE":
                report["direction"]="NO_TRADE"
                return report,[],"stale_completed_index_bar"
            if signal["direction"] not in ("UP","DOWN"):
                return report,[],"no_confirmed_ema_rsi_trend"
            stamp=db.execute("""SELECT captured_utc,normalized_json,snapshot_sha256 FROM option_chain_observations
                WHERE underlying='BANKNIFTY' AND expiry=? AND captured_utc>=? AND captured_utc<=?
                ORDER BY captured_utc DESC LIMIT 1""",
                (expiry,(now-timedelta(seconds=MAX_CHAIN_AGE)).isoformat(),now.isoformat())).fetchone()
            if not stamp:
                return report,[],"missing_fresh_chain"
            captured,raw,digest=stamp
            if sha256(raw.encode()).hexdigest()!=digest:
                return report,[],"chain_digest_mismatch"
            chain=json.loads(raw)
            if chain.get("received_utc")!=captured or chain.get("expiry")!=expiry:
                return report,[],"chain_terms_mismatch"
            chain_age=(now-ao.timestamp(captured)).total_seconds()
            spot=ao.positive(chain.get("underlying_spot"))
            if not spot or not 0<=chain_age<=MAX_CHAIN_AGE:
                return report,[],"stale_or_invalid_chain"
            years=(datetime.combine(date.fromisoformat(expiry),time(15,30),paper.IST)-now).total_seconds()/ao.YEAR_SECONDS
            move=ao.positive(signal["atr14"])
            if move is None or years<=config["hold_seconds"]/ao.YEAR_SECONDS:
                return report,[],"missing_atr_or_expiry_too_near"
            # ATR-scaled move is a declared stress scenario, never a prediction.
            move=move*sqrt(config["hold_seconds"]/60)
            report.update(spot=spot,chain_utc=captured,chain_sha256=digest,
                          expiry=expiry,scenario_move_points=round(move,3))
            rejected=Counter(); output=[]; seen=set()
            counts=Counter(c.get("identity") for c in chain.get("contracts",[]))
            for c in chain.get("contracts",[]):
                identity=c.get("identity")
                if identity not in subscribed or identity in seen:
                    continue
                seen.add(identity)
                if counts[identity]!=1 or not c.get("contract_master_verified") or not c.get("quote_valid"):
                    rejected["ambiguous_or_unverified_chain_contract"]+=1;continue
                if not ao.positive(c.get("oi")) or not ao.positive(c.get("volume")):
                    rejected["missing_oi_or_volume"]+=1;continue
                book=latest_book(db,identity,now)
                if not book:
                    rejected["missing_fresh_original_book"]+=1;continue
                if (book["expiry"],book["strike"],book["option_type"],book["lot_size"])!=(
                        c["expiry"],c["strike"],c["option_type"],c["lot_size"]):
                    rejected["depth_chain_terms_mismatch"]+=1;continue
                if book["bid"]<5 or book["spread_bps"]>250:
                    rejected["wide_spread_or_low_premium"]+=1;continue
                mid=(book["bid"]+book["ask"])/2
                sigma=ao.implied_iv(mid,spot,book["strike"],years,RATE,book["option_type"],DIVIDEND)
                if sigma is None or not .02<sigma<ao.MAX_IV-.02:
                    rejected["unusable_quote_implied_volatility"]+=1;continue
                greeks=ao.bsm(spot,book["strike"],years,RATE,sigma,book["option_type"],DIVIDEND)
                if not .05<=abs(greeks["delta"])<=.95:
                    rejected["delta_outside_research_band"]+=1;continue
                activity,reason=_activity(db,identity,now,book["lot_size"])
                if reason:
                    rejected[reason]+=1;continue
                output.append({**book,"sigma":sigma,"years":years,"greeks":greeks,
                               "oi":c["oi"],"volume":c["volume"],"activity":activity})
            report.update(rejections=dict(rejected),valid_contracts=len(output))
            return report,output,None
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc) or "unable to open database file" in str(exc):
            return report,[],"saved_market_source_unavailable"
        raise


def actions(strategy):
    return ("BUY",) if strategy=="LONG_OPTION" else replay.studio.STRATEGIES[strategy]["actions"]


def executions(books,strategy,lots,profile,reverse=False):
    units=lots*books[0]["lot_size"]
    sides=actions(strategy)
    if reverse:
        sides=tuple("SELL" if a=="BUY" else "BUY" for a in sides)
    rows=[replay._execute(b,a,units,PARTICIPATION,SLIPPAGE,profile) for b,a in zip(books,sides)]
    return rows if all(r["displayed_fill_units"]==units for r in rows) else None


def _scenario_exit(books,strategy,units,spot,move,iv_shock,hold_seconds,profile):
    cash=0.
    for book,action in zip(books,actions(strategy)):
        iv=book["sigma"]+iv_shock
        years=book["years"]-hold_seconds/ao.YEAR_SECONDS
        if not ao.MIN_IV<iv<ao.MAX_IV or years<=0 or spot+move<=0:
            return None
        mid=ao.bsm(spot+move,book["strike"],years,RATE,iv,book["option_type"],DIVIDEND)["price"]
        half=(book["ask"]-book["bid"])/2
        side="SELL" if action=="BUY" else "BUY"
        price=max(0.,mid-half)*(1-SLIPPAGE/10000) if side=="SELL" else (mid+half)*(1+SLIPPAGE/10000)
        gross=replay.fees._money(price*units)
        cash+=(gross if side=="SELL" else -gross)-paper._fees(side,gross,profile)
    return cash


def _candidate(strategy,books,config,report,rejections):
    if strategy!="LONG_OPTION":
        try:
            replay.studio._validate_structure(strategy,books)
        except ValueError:
            return None
    stamps=[b["stamp"] for b in books]
    if (max(stamps)-min(stamps)).total_seconds()>MAX_SKEW:
        rejections["unsynchronized_legs"]+=1;return None
    profile=config["broker_profile"]
    cap=min(config["capital"],config["max_loss"])
    direction=1 if report["direction"]=="UP" else -1
    best=None
    for lots in range(1,config["max_lots"]+1):
        entry=executions(books,strategy,lots,profile)
        exit_=executions(books,strategy,lots,profile,reverse=True)
        if entry is None or exit_ is None:
            rejections["insufficient_displayed_roundtrip_depth"]+=1;continue
        units=lots*books[0]["lot_size"]
        cash,max_loss,risk=replay._entry_risk(strategy,books,actions(strategy),entry,units)
        if (strategy.endswith("debit") and cash>=0) or (strategy.endswith("credit") and cash<=0):
            rejections["incorrect_modeled_spread_cashflow"]+=1;continue
        # Conservative sizing: include immediate modeled close fees in loss
        # ceiling; this does not certify real maximum loss or broker margin.
        risk=replay.fees._money(max(risk,max_loss+sum(x["fees"] for x in exit_)))
        if risk<=0 or risk>cap:
            rejections["risk_or_budget_ceiling"]+=1;continue
        outcomes={}
        for name,move,iv in (("favorable",direction*report["scenario_move_points"],0.),
                ("favorable_iv_down",direction*report["scenario_move_points"],-.02),
                ("favorable_iv_up",direction*report["scenario_move_points"],.02),
                ("flat",0.,0.),("adverse",-direction*report["scenario_move_points"],0.)):
            value=_scenario_exit(books,strategy,units,report["spot"],move,iv,config["hold_seconds"],profile)
            if value is None:
                break
            outcomes[name]=replay.fees._money(cash+value)
        if len(outcomes)!=5:
            rejections["invalid_model_scenario"]+=1;continue
        favorable=min(outcomes[k] for k in ("favorable","favorable_iv_down","favorable_iv_up"))
        if favorable<config["target_net"]:
            rejections["stress_target_not_met"]+=1;continue
        immediate=replay.fees._money(cash+sum(x["cashflow"] for x in exit_))
        # Rank by conservative favorable net relative to modeled adverse/flat
        # losses and crossing friction. This is not an expected-return model.
        score=favorable/(1.+max(0.,-outcomes["adverse"])+max(0.,-outcomes["flat"])+max(0.,-immediate))
        candidate={"strategy":strategy,"identities":[b["identity"] for b in books],"lots":lots,
            "units":units,"lot_size":books[0]["lot_size"],"modeled_risk_inr":risk,
            "entry_cashflow_inr":cash,"immediate_roundtrip_net_inr":immediate,
            "entry_fees_inr":sum(x["fees"] for x in entry),"immediate_exit_fees_inr":sum(x["fees"] for x in exit_),
            "stress_favorable_net_inr":favorable,"scenario_net_inr":outcomes,"score":round(score,6),
            "oldest_book_utc":paper._iso(min(stamps)),"newest_book_utc":paper._iso(max(stamps)),
            "legs":[{"identity":b["identity"],"strike":b["strike"],"side":b["option_type"],
                     "expiry":b["expiry"],"action":a,"bid":b["bid"],"ask":b["ask"],
                     "book_utc":b["received_utc"],"book_sha256":b["digest"],"iv_pct":b["sigma"]*100,
                     "greeks":b["greeks"],"oi":b["oi"],"volume":b["volume"],"activity":b["activity"]}
                     for b,a in zip(books,actions(strategy))]}
        if best is None or (candidate["score"],favorable,-risk)>(best["score"],best["stress_favorable_net_inr"],-best["modeled_risk_inr"]):
            best=candidate
    return best


def select(now,config):
    report,books,reason=_source(now,config)
    output={}
    for lane in ("directional","spread"):
        output[lane]={"action":"NO_TRADE","reason":reason or "no_candidate_passed", "candidates":[], "rejections":{}}
    if reason:
        return report,output
    direction=report["direction"]
    side="CE" if direction=="UP" else "PE"
    candidates=[]; rejects=Counter()
    for book in books:
        if book["option_type"]==side and .15<=abs(book["greeks"]["delta"])<=.85:
            c=_candidate("LONG_OPTION",[book],config,report,rejects)
            if c:candidates.append(c)
    _finish(output["directional"],candidates,rejects)
    # Compare bounded debit and defined-risk credit verticals on the same
    # observed trend. Passive bid/ask capture has no calibrated fill model.
    candidates=[]; rejects=Counter()
    pairs=[("bull_call_debit","CE",True),("bull_put_credit","PE",True)] if direction=="UP" else [
           ("bear_put_debit","PE",False),("bear_call_credit","CE",False)]
    for strategy,option_side,ascending in pairs:
        pool=sorted([b for b in books if b["option_type"]==option_side],
            key=lambda b:(b["spread_bps"],-b["activity"]["receipts_120s"],abs(b["strike"]-report["spot"]),b["identity"]))[:MAX_PER_SIDE]
        for first in pool:
            for second in pool:
                if first["lot_size"]!=second["lot_size"] or first["expiry"]!=second["expiry"]:
                    continue
                if not (first["strike"]<second["strike"] if ascending else first["strike"]>second["strike"]):
                    continue
                c=_candidate(strategy,[first,second],config,report,rejects)
                if c:candidates.append(c)
    _finish(output["spread"],candidates,rejects)
    return report,output


def _finish(output,candidates,rejects):
    candidates.sort(key=lambda c:(-c["score"],-c["stress_favorable_net_inr"],c["modeled_risk_inr"],c["identities"]))
    output.update(rejections=dict(rejects),candidates=candidates[:3],eligible_candidates=len(candidates))
    if candidates:
        output.update(action="PAPER_ENTRY",reason="modeled_scenario_and_source_gates_passed",selected=candidates[0])
