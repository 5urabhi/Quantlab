"""Read-only BANKNIFTY option analysis and conditional contract comparisons.

No order endpoints, no directional forecast, no fill/profit probability.
One Dhan chain receipt supplies spot, strikes, bid/ask, provider IV and OI.
Independent BSM quote-IV inversion, explicit units and scenario repricing.
Historical analytics only use bounded, already persisted original receipts.
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from math import erfc, exp, isfinite, log, pi, sqrt
from statistics import mean, stdev
import json
import sqlite3

from . import option_chain_live, shared_market_data, liquidity_spreads as fees
from . import spread_scanner

IST = option_chain_live.IST
YEAR_SECONDS = 365.25 * 86400
MIN_IV, MAX_IV = 0.00001, 5.0
MAX_RECEIPT_AGE = 30
DEPTH_WINDOW = 120
MIN_IV_SESSIONS = 20
MIN_REALIZED_RETURNS = 30


def number(v):
    return float(v) if isinstance(v, (float, int)) and not isinstance(v, bool) and isfinite(v) else None


def positive(v):
    n = number(v)
    return n if n is not None and n > 0 else None


def timestamp(v):
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        raise ValueError("Source timestamp must include timezone")
    return dt.astimezone(timezone.utc)


def _cdf(x):
    return erfc(-x / sqrt(2.0)) / 2


def bsm(spot, strike, years, rate, sigma, side, dividend):
    """Same continuous-yield BSM convention as index_research.math_models.
    Fast scalar kernel for whole-chain pricing; Greeks use explicit units.
    """
    root = sqrt(years)
    d1 = (log(spot / strike) + (rate - dividend + sigma*sigma/2)*years)/(sigma*root)
    d2 = d1 - sigma*root
    dq, dr = exp(-dividend*years), exp(-rate*years)
    density = exp(-d1*d1/2)/sqrt(2*pi)
    common_theta = -spot*dq*density*sigma/(2*root)
    if side == "CE":
        price = spot*dq*_cdf(d1) - strike*dr*_cdf(d2)
        delta = dq*_cdf(d1)
        theta = common_theta + dividend*spot*dq*_cdf(d1) - rate*strike*dr*_cdf(d2)
        rho = strike*years*dr*_cdf(d2)
    else:
        price = strike*dr*_cdf(-d2) - spot*dq*_cdf(-d1)
        delta = -dq*_cdf(-d1)
        theta = common_theta - dividend*spot*dq*_cdf(-d1) + rate*strike*dr*_cdf(-d2)
        rho = -strike*years*dr*_cdf(-d2)
    return {
        "price": max(0., price), "delta": delta,
        "gamma": dq*density/(spot*sigma*root),
        "theta_day": theta/365.25,
        "vega_iv_point": spot*dq*density*root/100,
        "rho_rate_point": rho/100,
    }


def implied_iv(price, spot, strike, years, rate, side, dividend):
    if positive(price) is None or years <= 0:
        return None
    discounted_s = spot*exp(-dividend*years)
    discounted_k = strike*exp(-rate*years)
    lower = max(0., discounted_s-discounted_k if side=="CE" else discounted_k-discounted_s)
    upper = discounted_s if side=="CE" else discounted_k
    if not lower < price < upper:
        return None
    lo, hi = MIN_IV, MAX_IV
    if not bsm(spot,strike,years,rate,lo,side,dividend)["price"] < price < bsm(
            spot,strike,years,rate,hi,side,dividend)["price"]:
        return None
    for _ in range(44):
        mid = (lo+hi)/2
        if bsm(spot,strike,years,rate,mid,side,dividend)["price"] < price:
            lo = mid
        else:
            hi = mid
    return (lo+hi)/2


def _read_database():
    path = shared_market_data.database_path().resolve()
    return sqlite3.connect(path.as_uri()+"?mode=ro", uri=True, timeout=2)


def _read_json(raw):
    value = json.loads(raw)
    return value if isinstance(value, dict) else {}


def _atm_iv(snapshot):
    """Provider IV %, equal-weight CE/PE at the nearest paired strike."""
    spot = positive(snapshot.get("underlying_spot"))
    if spot is None:
        return None
    pairs = defaultdict(dict)
    for c in snapshot.get("contracts", []):
        k, iv = positive(c.get("strike")), positive(c.get("iv"))
        if k is not None and iv is not None and c.get("quote_valid") and c.get("option_type") in ("CE","PE"):
            pairs[k][c["option_type"]] = iv
    eligible = [(abs(k-spot), k, (v["CE"]+v["PE"])/2)
                for k,v in pairs.items() if "CE" in v and "PE" in v]
    if not eligible:
        return None
    _, strike, iv = min(eligible)
    return {"strike":strike, "iv_pct":iv, "spot":spot}


@lru_cache(maxsize=24)
def _daily_history(path, expiry, day, bucket):
    """One last saved snapshot per UTC date during the regular IST session.
    Bounded to 60 observed days; cache the older receipts for five minutes.
    """
    if not shared_market_data.database_path().is_file():
        return []
    cutoff = datetime.combine(date.fromisoformat(day),time.min,IST).astimezone(timezone.utc).isoformat()
    floor = (timestamp(cutoff)-timedelta(days=90)).isoformat()
    try:
        with closing(_read_database()) as db:
            records = db.execute("""SELECT captured_utc, normalized_json
                FROM option_chain_observations
                WHERE underlying='BANKNIFTY' AND expiry=? AND captured_utc IN (
                    SELECT MAX(captured_utc) FROM option_chain_observations
                    WHERE underlying='BANKNIFTY' AND expiry=? AND captured_utc>=?
                      AND captured_utc<? GROUP BY substr(captured_utc,1,10)
                    ORDER BY MAX(captured_utc) DESC LIMIT 60)
                ORDER BY captured_utc""",(expiry,expiry,floor,cutoff)).fetchall()
        out=[]
        for stamp, raw in records:
            atm = _atm_iv(_read_json(raw))
            if atm:
                out.append({"day":timestamp(stamp).astimezone(IST).date().isoformat(),
                            "captured_utc":stamp, **atm})
        return out
    except (sqlite3.Error, ValueError, OSError):
        return []


def _history(chain, now):
    captured = timestamp(chain["received_utc"])
    day = captured.astimezone(IST).date().isoformat()
    start = datetime.combine(date.fromisoformat(day),time.min,IST).astimezone(timezone.utc).isoformat()
    stamp = chain["received_utc"]
    result = {"previous":{}, "previous_utc":None, "term":[], "realized":None,
              "realized_returns":0,"realized_last_utc":None,"recent_trades":{},
              "historical_error":None}
    try:
        with closing(_read_database()) as db:
            try:
                prior = db.execute("""SELECT captured_utc, normalized_json
                   FROM option_chain_observations WHERE underlying='BANKNIFTY'
                   AND expiry=? AND captured_utc>=? AND captured_utc<?
                   ORDER BY captured_utc DESC LIMIT 1""",(chain["expiry"],start,stamp)).fetchone()
                if prior:
                    result["previous_utc"] = prior[0]
                    result["previous"] = {c["identity"]:c for c in _read_json(prior[1]).get("contracts",[])
                                          if c.get("identity")}
                # One latest receipt per expiry on the same IST date, with each own timestamp.
                term = db.execute("""SELECT o.expiry,o.captured_utc,o.normalized_json
                   FROM option_chain_observations o JOIN (
                      SELECT expiry,MAX(captured_utc) AS newest FROM option_chain_observations
                      WHERE underlying='BANKNIFTY' AND expiry>=? AND captured_utc>=? AND captured_utc<=?
                      GROUP BY expiry ORDER BY expiry LIMIT 12
                   ) x ON o.expiry=x.expiry AND o.captured_utc=x.newest
                   WHERE o.underlying='BANKNIFTY' ORDER BY o.expiry""",(day,start,stamp)).fetchall()
                for expiry, receipt, raw in term:
                    atm = _atm_iv(_read_json(raw))
                    if atm:
                        result["term"].append({"expiry":expiry,"captured_utc":receipt,**atm})
            except sqlite3.Error:
                result["historical_error"]="Saved chain history unavailable"
            try:
                bars=db.execute("""SELECT minute_utc, close FROM live_minute_bars
                   WHERE identity='INDEX:BANKNIFTY' AND session_ist=? AND minute_utc<?
                   ORDER BY minute_utc DESC LIMIT 121""",
                   (day,captured.replace(second=0,microsecond=0).isoformat())).fetchall()
                # Most recent contiguous one-minute closes; never bridge missing bars.
                prices=[]
                prev=None
                for stamp_, price in bars:
                    t=timestamp(stamp_)
                    if positive(price) is None or (prev is not None and (prev-t).total_seconds()!=60):
                        break
                    prices.append(price)
                    prev=t
                returns=[log(a/b) for a,b in zip(prices,prices[1:])]
                result["realized_returns"]=len(returns)
                if bars:
                    result["realized_last_utc"]=bars[0][0]
                if len(returns)>=MIN_REALIZED_RETURNS:
                    result["realized"]=stdev(returns)*sqrt(252*375)*100
            except sqlite3.Error:
                pass
            try:
                # Index on received_utc keeps this bounded to the last two minutes.
                cutoff=(captured-timedelta(seconds=120)).isoformat()
                rows=db.execute("""SELECT identity,COUNT(DISTINCT exchange_trade_utc),
                   MAX(volume)-MIN(volume),MAX(exchange_trade_utc)
                   FROM dhan_option_live_events
                   WHERE kind='quote' AND received_utc>=? AND received_utc<=?
                     AND exchange_trade_utc>=? AND exchange_trade_utc<=?
                     AND volume IS NOT NULL AND volume>=0
                   GROUP BY identity""",(cutoff,stamp,cutoff,stamp)).fetchall()
                result["recent_trades"]={i:{"trade_times":count,"volume_delta":vol,
                     "last_exchange_trade_utc":latest} for i,count,vol,latest in rows}
            except sqlite3.Error:
                pass
    except (sqlite3.Error,OSError,ValueError):
        result["historical_error"]="Saved market library unavailable"
    current_atm=_atm_iv(chain)
    history=_daily_history(str(shared_market_data.database_path()),chain["expiry"],day,
                          int(now.timestamp()//300))
    if current_atm:
        history=[*history,{"day":day,"captured_utc":chain["received_utc"],**current_atm}]
        result["term"]=[r for r in result["term"] if r["expiry"]!=chain["expiry"]]
        result["term"].append({"expiry":chain["expiry"],"captured_utc":chain["received_utc"],**current_atm})
        result["term"].sort(key=lambda r:r["expiry"])
    past=[x["iv_pct"] for x in history if x["day"]!=day]
    rank=percentile=None
    if current_atm and len(past)>=MIN_IV_SESSIONS:
        value=current_atm["iv_pct"]
        lo,hi=min(past+[value]),max(past+[value])
        rank=100*(value-lo)/(hi-lo) if hi>lo else None
        percentile=100*sum(v<value for v in past)/len(past)
    result.update({"atm_iv_pct":current_atm["iv_pct"] if current_atm else None,
                   "iv_history":history,"iv_sessions":len(past),
                   "iv_rank":rank,"iv_percentile":percentile})
    return result


def _entry_cost(ask, size, lots, profile):
    return fees.fee_schedule(ask*size*lots,0.,broker_profile=profile)["buy_leg"]["cash_debit"]


def _affordable(ask,size,budget,profile):
    low,high=0,min(1000,int(budget/(ask*size)))
    while low<high:
        mid=(low+high+1)//2
        if _entry_cost(ask,size,mid,profile)<=budget:
            low=mid
        else:
            high=mid-1
    return low


def _scenario(spot,strike,years,rate,sigma,side,dividend,move,iv_points,horizon,
              ask,half_spread,units,profile,slippage_bps):
    next_t=years-horizon*60/YEAR_SECONDS
    next_iv=sigma+iv_points/100
    if next_t<=0 or next_iv<=MIN_IV or next_iv>MAX_IV or spot+move<=0:
        return None
    modeled=bsm(spot+move,strike,next_t,rate,next_iv,side,dividend)["price"]
    exit_bid=max(0.,modeled-half_spread)*(1-slippage_bps/10000)
    buy,sell=ask*units,exit_bid*units
    charges=fees.fee_schedule(buy,sell,broker_profile=profile)
    return {"move_points":move,"iv_change_points":iv_points,"minutes":horizon,
            "model_mid":round(modeled,4),"assumed_exit_bid":round(exit_bid,4),
            "charges_inr":charges["total_estimated"],
            "net_pnl_inr":fees._money(sell-buy-charges["total_estimated"]),
            "exit_bid_is_forecast":False}


def _break_even(ask,units,profile):
    """Minimum future SELL premium to recover actual modeled entry/exit costs."""
    lo,hi=ask,ask+max(100,ask*.25)
    def net(sell):
        return (sell-ask)*units-fees.fee_schedule(
            ask*units,sell*units,broker_profile=profile)["total_estimated"]
    while net(hi)<0 and hi<1e7:
        hi*=2
    for _ in range(32):
        mid=(lo+hi)/2
        if net(mid)>=0:
            hi=mid
        else:
            lo=mid
    # NSE tick sizes can change; this is unrounded theoretical premium.
    return round(hi,4)


def _depth_for_shortlist(rows, captured, now, selected):
    """Validate at most 60 leading candidate books plus selected identity.
    Indexed per-ID query; never scans the entire historical depth table.
    """
    picked=[r for r in rows if r["score"] is not None]
    picked.sort(key=lambda r:(r["trade_activity_state"]!="recent_trade_evidence",-r["score"]))
    ids={r["identity"] for r in picked[:60]}
    if selected:
        ids.add(selected)
    by_id={r["identity"]:r for r in rows if r["identity"] in ids}
    cutoff=(captured-timedelta(seconds=DEPTH_WINDOW)).isoformat()
    try:
        with closing(_read_database()) as db:
            for identity,r in by_id.items():
                r["depth_state"]="no_recent_original_book"
                values=db.execute("""SELECT received_utc,book_json,packet_pair_sha256
                    FROM live_depth_books WHERE identity=? AND received_utc>=?
                    AND received_utc<=? ORDER BY received_utc DESC LIMIT 4""",
                    (identity,cutoff,captured.isoformat())).fetchall()
                for stamp,raw,digest in values:
                    verified=spread_scanner._original_book(identity,stamp,raw,digest)
                    if not verified:
                        continue
                    _,stats,feature=verified
                    if (feature.get("expiry")!=r["expiry"] or feature.get("strike")!=r["strike"] or
                        feature.get("side")!=r["option_type"] or stats["lot_size"]!=r["lot_size"]):
                        continue
                    age=(now-timestamp(stamp)).total_seconds()
                    r["depth"]={"received_utc":stamp,"age_seconds":round(age,2),
                               **{k:stats[k] for k in ("bid","ask","spread_bps","imbalance_20",
                                 "bid_quantity_20","ask_quantity_20","top_bid_quantity","top_ask_quantity")}}
                    r["depth_state"]="recent_original_book" if 0<=age<=8 else "delayed_original_book"
                    break
    except (sqlite3.Error,OSError,ValueError):
        for r in by_id.values():
            if r["depth_state"]=="not_checked":
                r["depth_state"]="original_book_unavailable"


def analyze(chain, *, capital=50000., max_lots=3, direction="BOTH", move_points=100.,
            horizon_minutes=5, iv_change_points=0., rate_pct=6.5, dividend_pct=0.,
            max_spread_bps=250., risk_pct=100., target_premium=300.,
            slippage_bps=10., broker_profile="zerodha", selected="", now=None):
    """One snapshot, descriptive market analytics and assumption-dependent ranking."""
    if direction not in ("BOTH","UP","DOWN") or broker_profile not in fees.BROKER_PROFILES:
        raise ValueError("Invalid direction or broker profile")
    checks=((capital,1000,1e8),(max_lots,1,50),(move_points,1,10000),
        (horizon_minutes,1,1440),(iv_change_points,-50,50),(rate_pct,-5,25),
        (dividend_pct,0,25),(max_spread_bps,10,5000),(risk_pct,1,100),
        (target_premium,1,100000),(slippage_bps,0,500))
    if any(number(x) is None or not lo<=x<=hi for x,lo,hi in checks):
        raise ValueError("Invalid analytics assumptions")
    if not isinstance(max_lots,int) or not isinstance(horizon_minutes,int):
        raise ValueError("Lots and horizon must be integers")
    now=now or datetime.now(timezone.utc)
    captured=timestamp(chain["received_utc"])
    spot=positive(chain["underlying_spot"])
    if spot is None:
        raise ValueError("No observed BANKNIFTY spot")
    expiry_at=datetime.combine(date.fromisoformat(chain["expiry"]),time(15,30),IST)
    years=(expiry_at-captured).total_seconds()/YEAR_SECONDS
    rate,dividend=rate_pct/100,dividend_pct/100
    age=(now-captured).total_seconds()
    local=now.astimezone(IST)
    recent=0<=age<=MAX_RECEIPT_AGE and local.weekday()<5 and time(9,15)<=local.time()<time(15,30)
    h=_history(chain,now)
    rows=[]
    for c in chain["contracts"]:
        k=positive(c.get("strike"));side=c.get("option_type")
        if k is None or side not in ("CE","PE"):
            continue
        identity=c.get("identity")
        bid,ask=positive(c.get("bid")),positive(c.get("ask"))
        valid=bool(c.get("quote_valid") and bid is not None and ask is not None and bid<=ask)
        mid=(bid+ask)/2 if valid else None
        intrinsic=max(spot-k,0.) if side=="CE" else max(k-spot,0.)
        spread_bps=(ask-bid)/mid*10000 if mid else None
        sigma=implied_iv(mid,spot,k,years,rate,side,dividend) if mid and years>0 else None
        model=bsm(spot,k,years,rate,sigma,side,dividend) if sigma else None
        iv_bid=implied_iv(bid,spot,k,years,rate,side,dividend) if valid and years>0 else None
        iv_ask=implied_iv(ask,spot,k,years,rate,side,dividend) if valid and years>0 else None
        prior=h["previous"].get(identity,{}) if identity else {}
        def change(field):
            a,b=number(c.get(field)),number(prior.get(field))
            return a-b if a is not None and b is not None else None
        volume_delta=change("volume")
        trade=h["recent_trades"].get(identity)
        size=c.get("lot_size")
        verified=bool(identity and c.get("contract_master_verified") and
                      isinstance(size,int) and not isinstance(size,bool) and 1<=size<=1000)
        recent_trade=bool(verified and trade and trade["trade_times"]>=2 and
                          (trade["volume_delta"] or 0)>=size)
        top_bid,top_ask=number(c.get("top_bid_quantity")),number(c.get("top_ask_quantity"))
        top_lots=int(min(top_bid,top_ask)//size) if verified and top_bid is not None and top_ask is not None else None
        affordable=_affordable(ask,size,capital,broker_profile) if valid and verified else None
        risk_lots=_affordable(ask,size,capital*risk_pct/100,broker_profile) if valid and verified else None
        lots=min(max_lots,risk_lots,top_lots) if risk_lots is not None and top_lots is not None else 0
        reasons=[]
        if not recent: reasons.append("Snapshot not current regular-session receipt")
        if not verified: reasons.append("Unverified contract / lot")
        if not valid: reasons.append("Missing or crossed bid/ask")
        if valid and (bid<20 or spread_bps>max_spread_bps): reasons.append("Low premium or wide relative spread")
        if not model: reasons.append("No valid midpoint IV solution")
        elif not .15<=abs(model["delta"])<=.85: reasons.append("Delta outside 0.15–0.85 comparison band")
        if not lots or lots<1: reasons.append("Insufficient budget, risk allocation or top-level quantity")
        if not positive(c.get("oi")) or not positive(c.get("volume")): reasons.append("No reported OI / volume")
        if direction!="BOTH" and side!=("CE" if direction=="UP" else "PE"): reasons.append("Other scenario direction")
        if years<=horizon_minutes*60/YEAR_SECONDS: reasons.append("Horizon reaches assumed expiry close")
        scenarios={};cost=roundtrip=break_even=None
        score=None
        if model and lots>0 and years>horizon_minutes*60/YEAR_SECONDS:
            units=lots*size
            cost=_entry_cost(ask,size,lots,broker_profile)
            roundtrip=fees.fee_schedule(ask*units,bid*units,broker_profile=broker_profile)
            break_even=_break_even(ask,units,broker_profile)
            move=move_points if side=="CE" else -move_points
            for label,m,iv in (("favorable",move,iv_change_points),("flat",0,iv_change_points),
                  ("adverse",-move,iv_change_points),("iv_crush",move,iv_change_points-2),
                  ("iv_expansion",move,iv_change_points+2),("double_favorable",2*move,iv_change_points),
                  ("double_adverse",-2*move,iv_change_points)):
                scenarios[label]=_scenario(spot,k,years,rate,sigma,side,dividend,m,iv,
                    horizon_minutes,ask,(ask-bid)/2,units,broker_profile,slippage_bps)
            fav,adverse,flat=(scenarios.get(x) for x in ("favorable","adverse","flat"))
            if not fav or not adverse or not flat:
                reasons.append("Scenario outside valid model assumptions")
            elif fav["net_pnl_inr"]<=0:
                reasons.append("Favorable scenario is not net positive")
            elif not reasons:
                # Transparent heuristic: reward / adverse-loss, preferred premium
                # proximity, costs and recent activity. Not a calibrated probability.
                reward=fav["net_pnl_inr"]/cost
                loss=max(0.,-adverse["net_pnl_inr"])/cost
                decay=max(0.,-flat["net_pnl_inr"])/cost
                ratio=reward/(.05+loss+decay)
                premium_fit=1/(1+abs(mid-target_premium)/target_premium)
                score=round(50*min(1.,ratio/2)+20*(1-min(1.,spread_bps/max_spread_bps))
                            +15*premium_fit+15*min(1.,reward/.15),2)
        else:
            units=0
        gex=(model["gamma"]*positive(c.get("oi"))*spot*spot*.01
             if model and positive(c.get("oi")) is not None else None)
        # OI units are provider-reported; no dealer-long/short sign inferred.
        rows.append({**c,"mid":mid,"intrinsic":intrinsic,
            "extrinsic":mid-intrinsic if mid is not None else None,
            "moneyness":"ATM vicinity" if abs(spot-k)<100 else ("ITM" if intrinsic>0 else "OTM"),
            "spread_bps":spread_bps,"iv_mid_pct":sigma*100 if sigma else None,
            "iv_bid_pct":iv_bid*100 if iv_bid else None,"iv_ask_pct":iv_ask*100 if iv_ask else None,
            "model_greeks":model,"iv_change_pct_points":change("iv"),"oi_change":change("oi"),
            "volume_change":volume_delta if volume_delta is not None and volume_delta>=0 else None,
            "trade_activity":trade,"trade_activity_state":"recent_trade_evidence" if recent_trade else
              ("insufficient_recent_trades" if trade else "missing_trade_evidence"),
            "top_level_lots":top_lots,"affordable_lots":affordable,"scenario_lots":max(0,lots),
            "units":units,"entry_debit_inr":cost,"max_premium_loss_inr":cost,
            "break_even_exit_premium":break_even,"roundtrip_fees":roundtrip,
            "same_quote_roundtrip_net_inr":fees._money((bid-ask)*units-roundtrip["total_estimated"]) if roundtrip else None,
            "scenarios":scenarios,"score":score,"reasons":reasons,
            "depth":None,"depth_state":"not_checked",
            "unsigned_gamma_oi_proxy":gex})
    _depth_for_shortlist(rows,captured,now,selected)
    def quality(r):
        if r["depth_state"]=="recent_original_book" and r["trade_activity_state"]=="recent_trade_evidence":
            d=r["depth"]
            if min(d["top_bid_quantity"],d["top_ask_quantity"])>=r["units"] and d["spread_bps"]<=max_spread_bps:
                return 0
        return 1 if r["trade_activity_state"]=="recent_trade_evidence" else 2
    ranked=[r for r in rows if r["score"] is not None]
    ranked.sort(key=lambda r:(quality(r),-r["score"],r["strike"],r["option_type"]))
    for i,r in enumerate(ranked,1):
        r["rank"]=i
        r["rank_quality"]=("recent_depth_and_trades","recent_trades_snapshot_only","indicative_snapshot_only")[quality(r)]
    # OI descriptive metrics from the complete returned chain; missing OI is not zero.
    totals={s:sum(number(c.get("oi")) or 0 for c in rows if c["option_type"]==s) for s in ("CE","PE")}
    known={s:sum(number(c.get("oi")) is not None for c in rows if c["option_type"]==s) for s in ("CE","PE")}
    counts={s:sum(c["option_type"]==s for c in rows) for s in ("CE","PE")}
    complete=all(known[s]==counts[s] and counts[s]>0 for s in ("CE","PE"))
    pcr=totals["PE"]/totals["CE"] if complete and totals["CE"]>0 else None
    max_pain=None
    if complete and totals["CE"]+totals["PE"]>0:
        strikes=sorted({r["strike"] for r in rows})
        # O(n log n) prefix/suffix payout over candidate settlement strikes.
        ce=defaultdict(float);pe=defaultdict(float)
        for r in rows:
            (ce if r["option_type"]=="CE" else pe)[r["strike"]]+=r["oi"]
        call_n=call_weight=0.;put_n=sum(pe.values());put_weight=sum(k*v for k,v in pe.items())
        losses=[]
        for k in strikes:
            put_n-=pe[k];put_weight-=k*pe[k]
            losses.append((max(0.,k*call_n-call_weight+put_weight-k*put_n),k))
            call_n+=ce[k];call_weight+=k*ce[k]
        max_pain=min(losses)[1]
    current=h["atm_iv_pct"]
    expected_move=(spot*current/100*sqrt(horizon_minutes*60/YEAR_SECONDS)
                   if current is not None else None)
    return {"chain":chain,"rows":rows,"ranked_identities":[r["identity"] for r in ranked],
        "ranked_count":len(ranked),"confirmed_depth_count":sum(quality(r)==0 for r in ranked),
        "recent_trade_count":sum(quality(r)<=1 for r in ranked),
        "as_of_utc":captured.isoformat(),"generated_utc":now.isoformat(),
        "snapshot_age_seconds":round(age,2),"recent_receipt":recent,
        "assumed_expiry_utc":expiry_at.astimezone(timezone.utc).isoformat(),
        "years_to_expiry":max(0.,years),
        "assumptions":{"capital":capital,"max_lots":max_lots,"direction":direction,
          "move_points":move_points,"horizon_minutes":horizon_minutes,"iv_change_points":iv_change_points,
          "rate_pct":rate_pct,"dividend_pct":dividend_pct,"max_spread_bps":max_spread_bps,
          "risk_pct":risk_pct,"target_premium":target_premium,"slippage_bps":slippage_bps,
          "broker_profile":broker_profile},
        "volatility":{"atm_provider_iv_pct":current,"realized_intraday_pct":h["realized"],
          "realized_returns":h["realized_returns"],"realized_last_utc":h["realized_last_utc"],
          "expected_move_points_model":expected_move,"iv_rank":h["iv_rank"],"iv_percentile":h["iv_percentile"],
          "iv_prior_sessions":h["iv_sessions"],"iv_min_prior_sessions":MIN_IV_SESSIONS,
          "iv_history":h["iv_history"],"term_structure":h["term"],"india_vix":None},
        "oi":{"call_oi":totals["CE"] if known["CE"] else None,
          "put_oi":totals["PE"] if known["PE"] else None,"known_counts":known,"contract_counts":counts,
          "complete":complete,"pcr":pcr,"max_pain_strike":max_pain,
          "previous_snapshot_utc":h["previous_utc"],"dealer_gamma_exposure":None},
        "historical_error":h["historical_error"],"read_only":True,
        "profit_probability":None,"expected_profit_inr":None,"orders_enabled":False,
        "warnings":[
          "Rank is a conditional long-option comparison, NOT a buy signal, forecast or win probability. UP means a user-assumed rise, DOWN a user-assumed fall; BOTH compares each side under its own favorable move.",
          "Chain receipt time is local, not exchange quote time. Original 20-level books and trade timestamps are checked separately; even recent depth is not an order fill. Only up to 60 leading candidates and selected ID receive indexed depth checks.",
          "Expiry at 15:30 IST, 365.25-day year, assumed rate/dividend and constant IV shock. Special sessions and exchange holidays are not certified.",
          "Scenario exit = theoretical midpoint less current half-spread and slippage. Future spreads, fills and IV are unknown. Fees are indicative existing Zerodha/Dhan schedule; settlement/exercise and other levies excluded.",
          "IV history uses same-expiry nearest paired strike provider IV, not a constant-tenor index. Realized vol uses at least 30 contiguous observed BANKNIFTY one-minute log returns, annualized sqrt(252 x 375); gaps not bridged.",
          "Gamma × reported OI × spot² × 1% is unsigned, per reported OI unit; dealer inventory sign and OI contract/quantity convention are not established. Max pain and PCR are descriptive, not directional forecasts.",
          "Full premium debit can be lost. Risk allocation is a user-entered ceiling, not a recommended allocation."],
    }


def current(expiry, **kwargs):
    return analyze(option_chain_live.chain(expiry), **kwargs)
