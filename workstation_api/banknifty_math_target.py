"""BANKNIFTY long-option mathematical target research; no ML or orders.

Past same-clock index paths, volatility rescaling and constant-IV European
repricing are an explicit physical-path heuristic, not a calibrated option
forecast. Nominal monthly expiry is a proxy; actual OHLC replay is separate.
"""
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from math import isfinite, sqrt
import numpy as np
from scipy.special import ndtr
from . import cpr_hybrid_research as r, historical_alpha as h
from . import predictive_option_research as p, expired_options_backtest as exp
from . import liquidity_spreads as fee, cpr_execution_evidence as evidence

VERSION="banknifty_math_target_v1"
HOLDS=(5,10,15,30,60)
COSTS=(35.,75.)
MIN_PATHS=12
MIN_TRAIN_SESSIONS=20
MIN_VALID_TRADES=10
MIN_VALID_DAYS=5
PROB_FLOOR=.35
TARGET=.10
STOP=-.05


def price(spot,strike,tau,iv,side):
    """Zero-carry, European spot proxy; calendar time in years."""
    spot=np.asarray(spot,dtype=float)
    tau=np.maximum(np.asarray(tau,dtype=float),1e-12)
    root=iv*np.sqrt(tau)
    d1=(np.log(spot/strike)+.5*root**2)/root
    d2=d1-root
    if side=="CALL":
        return np.maximum(0.,spot*ndtr(d1)-strike*ndtr(d2))
    return np.maximum(0.,strike*ndtr(-d2)-spot*ndtr(-d1))


def implied_vol(spot,strike,tau,premium,side):
    if min(spot,strike,tau,premium)<=0:
        return None
    lo,hi=.0001,5.
    if not float(price(spot,strike,tau,lo,side))<premium<float(price(spot,strike,tau,hi,side)):
        return None
    for _ in range(32):
        mid=(lo+hi)/2
        if price(spot,strike,tau,mid,side)<premium:lo=mid
        else:hi=mid
    return (lo+hi)/2


def _state(bars,m):
    if m<30 or any(k not in bars for k in range(m-30,m+1)):
        return None
    c=np.asarray([bars[k][3] for k in range(m-30,m+1)],dtype=float)
    if not np.isfinite(c).all() or min(c)<=0:return None
    sigma=float(np.sqrt(np.mean(np.diff(np.log(c))**2)))
    if sigma<1e-7:return None
    # Direction is conditional momentum, not an ML classification.
    drift=float(np.log(c[-1]/c[-16]))
    return c[-1],sigma,1 if drift>=0 else -1


def paths(index,train_dates,day,m,hold):
    """Only fixed earlier training sessions; same decision clock and direction.
    Fallback to all past training clocks if conditional support is inadequate.
    Each historical day is a single scenario, not independent minute samples.
    """
    state=_state(index[day],m)
    if state is None:return None
    spot,sigma,sign=state
    prior=[]
    for old in train_dates:
        if old>=day:continue
        bars=index[old];s=_state(bars,m)
        if s is None or any(k not in bars for k in range(m+1,m+hold+3)):continue
        base,vol,direction=s
        scale=float(np.clip(sigma/vol,.5,2.))
        op=np.asarray([bars[k][0] for k in range(m+1,m+hold+3)],dtype=float)
        cl=np.asarray([bars[k][3] for k in range(m+1,m+hold+3)],dtype=float)
        if min(op)<=0 or min(cl)<=0 or not np.isfinite(op).all() or not np.isfinite(cl).all():continue
        prior.append((old,direction,spot*np.exp(np.log(op/base)*scale),spot*np.exp(np.log(cl/base)*scale)))
    conditioned=[x for x in prior if x[1]==sign]
    chosen=conditioned if len(conditioned)>=MIN_PATHS else prior
    if len(chosen)<MIN_PATHS:return None
    return {"spot":float(spot),"opens":np.asarray([x[2] for x in chosen]),
            "closes":np.asarray([x[3] for x in chosen]),"days":[x[0] for x in chosen],
            "conditional":len(conditioned)>=MIN_PATHS,
            "up_probability":float(np.mean([x[3][hold] > spot for x in chosen])),
            "expected_terminal_move_points":float(np.mean([x[3][hold]-spot for x in chosen]))}


def _net_array(entry,exit_,units,bps):
    """Unrounded screen only; exact existing fee schedule used in replay."""
    buy=entry*units*(1+bps/10000)
    sell=exit_*units*(1-bps/10000)
    brokerage=2*fee.BROKER_PROFILES["zerodha"]["brokerage"]
    charges=(brokerage+(buy+sell)*(fee.NSE_OPTION_EXCHANGE_RATE+fee.SEBI_RATE))*(1+fee.GST_RATE)+sell*fee.STT_SELL_RATE+buy*fee.STAMP_BUY_RATE
    return (sell-buy-charges)/np.maximum(buy,1e-9)


def _forecast_returns(op,cl,hold,units,bps):
    # Scenario entry at m+2 open; completed-bar target/stop requests execute
    # at m+j+2 open, matching the historical engine. No intrabar high/low fill.
    entry=op[:,1]
    if np.any(entry<.05):return None
    marks=_net_array(entry[:,None],cl[:,1:hold],units,bps)
    hit=(marks>=TARGET)|(marks<=STOP)
    found=hit.any(axis=1)
    first=hit.argmax(axis=1)
    ix=np.arange(len(entry))
    # j=m+2+first, requested exit j+2. Timeout at m+2+hold.
    exits=np.where(found,first+3,hold+1)
    ret=_net_array(entry,op[ix,exits],units,bps)
    return {"expected_net_return":float(ret.mean()),
            "target_probability":float(np.mean(found & (marks[ix,first]>=TARGET))),
            "stop_probability":float(np.mean(found & (marks[ix,first]<=STOP))),
            "realized_target_probability":float(np.mean(ret>=TARGET)),
            "negative_probability":float(np.mean(ret<0))}


def required_move(spot,strike,tau,iv,side,premium,units,bps,elapsed=5):
    """Approximate favorable spot move for +10% net at fixed IV and time."""
    t=max(1e-12,tau-elapsed/(365*1440))
    direction=1 if side=="CALL" else -1
    lo,hi=0.,spot*.2
    def mark(move):
        return float(_net_array(premium,price(spot+direction*move,strike,t,iv,side),units,bps))
    if mark(hi)<TARGET:return None
    for _ in range(35):
        mid=(lo+hi)/2
        if mark(mid)>=TARGET:hi=mid
        else:lo=mid
    return hi*direction


def select(index,train,table,day,m,hold,*,lot_size,max_lots,budget):
    if m+hold+2>r.SQUAREOFF_MINUTE:return None,"too_late"
    scenario=paths(index,train,day,m,hold)
    if scenario is None:return None,"insufficient_past_paths"
    session=date.fromisoformat(day)
    expiry=exp._nominal_selected_expiry(session,0)
    # On nominal expiry day, rolling near-monthly identity and expiry timing
    # are particularly ambiguous. Exclude rather than invent a duration.
    if expiry<=session:return None,"nominal_expiry_day_excluded"
    tau=((expiry-session).days*1440+375-(m+1))/(365*1440)
    times=tau-np.arange(1,hold+3)/(365*1440)
    spot=scenario["spot"]
    candidates=[];observed=0;affordable=0;priced=0
    for (side,strike),row in table.get(r._stamp(day,m),{}).items():
        if side not in ("CALL","PUT") or not r._observed(table,day,m,side,strike):continue
        if abs(strike/spot-1)>.015 or row["close"]<5:continue
        observed+=1
        premium=row["close"]
        affordable_lots=[n for n in range(1,max_lots+1) if r._fund(premium,n*lot_size,COSTS[1])<=budget]
        if not affordable_lots:continue
        affordable+=1
        iv=implied_vol(spot,strike,tau,premium,side)
        if iv is None:continue
        priced+=1
        op=price(scenario["opens"],strike,times,iv,side)
        cl=price(scenario["closes"],strike,times,iv,side)
        for lots in affordable_lots:
            units=lots*lot_size
            forecasts=[_forecast_returns(op,cl,hold,units,cost) for cost in COSTS]
            if any(f is None for f in forecasts):continue
            if any(f["expected_net_return"]<=0 or f["target_probability"]<PROB_FLOOR for f in forecasts):continue
            worst=min(f["expected_net_return"] for f in forecasts)
            planned=r._fund(premium,units,COSTS[0])
            candidates.append((worst,forecasts[0]["target_probability"],-abs(strike-spot),-lots,
                {"side":side,"strike":float(strike),"lots":lots,"units":units,"premium":premium,
                 "iv_proxy":iv,"nominal_expiry":expiry.isoformat(),"tau":tau,"forecasts":forecasts,
                 "planned_funding":planned}))
    if not candidates:
        return None,("no_observed_contract" if not observed else "no_affordable_contract" if not affordable else "no_priceable_contract" if not priced else "no_positive_math_candidate")
    chosen=max(candidates,key=lambda x:x[:4])[-1]
    chosen.update(required_spot_move_points=required_move(spot,chosen["strike"],tau,chosen["iv_proxy"],
                    chosen["side"],chosen["premium"],chosen["units"],COSTS[0],hold),
                  up_probability=scenario["up_probability"],expected_terminal_move_points=scenario["expected_terminal_move_points"],
                  scenario_days=scenario["days"],conditional_paths=scenario["conditional"],
                  candidate_count=len(candidates),spot=spot)
    return chosen,"selected"


def replay(index,train,table,dates,hold,*,capital,budget,lot_size,max_lots,progress=None):
    """Rank once at each decision; reuse the same choices in both cost lanes.
    Each lane obeys its own position/risk constraint, without future reselection.
    """
    episodes={cost:[] for cost in COSTS}
    counts=Counter();journal=[]
    for i,day in enumerate(dates):
        if progress:progress(i,len(dates),day)
        for m in range(34,r.SQUAREOFF_MINUTE-hold-1,5):
            candidate,state=select(index,train,table,day,m,hold,lot_size=lot_size,max_lots=max_lots,budget=budget)
            counts[state]+=1
            if candidate is None:continue
            signal={"session":day,"minute":m,"side":candidate["side"],"spot":candidate["spot"],"features":[],
                    "decision_utc":r._stamp(day,m+1),"entry_utc":r._stamp(day,m+2),
                    "entry_type":"math_target","ranked_expected_return":candidate["forecasts"][0]["expected_net_return"],
                    "ranked_target_probability":candidate["forecasts"][0]["target_probability"]}
            journal.append({"session":day,"minute":m,**candidate})
            for cost in COSTS:
                planned=r._fund(candidate["premium"],candidate["units"],cost)
                pick=(abs(candidate["strike"]-candidate["spot"]),candidate["lots"],candidate["strike"],candidate["units"],planned,candidate["premium"])
                ep=r._episode(signal,table,index[day],hold=hold,lot_size=lot_size,max_lots=max_lots,risk_budget=budget,bps=cost,candidate=pick)
                episodes[cost].append(ep)
    lanes={}
    for cost in COSTS:
        metrics,trades=r._evaluate(episodes[cost],method="fixed_stop",capital=capital,risk_budget=budget,dates=dates,strict_execution=True)
        lanes[str(int(cost))]={"metrics":metrics,"journal":trades}
    return {"hold_minutes":hold,"candidate_states":dict(counts),"candidate_journal":journal,"lanes":lanes}


def _qualified(row):
    for lane in row["lanes"].values():
        m=lane["metrics"]
        if (m["scored_trades"]<MIN_VALID_TRADES or m["daily_coverage"]["days_with_scored_trade"]<MIN_VALID_DAYS
                or (m["conditional_net_inr"] or 0)<=0 or m["stress_utility_inr"]<=0):return False
    return True


def run(*,sessions=90,to_date=None,capital=17000.,budget=12000.,lot_size=30,max_lots=3,wings=5,progress=None):
    today=datetime.now(timezone.utc).astimezone(h.IST).date()
    stop=date.fromisoformat(to_date) if to_date else today
    if sessions not in r.SESSION_SPLITS or stop>today or not 0<budget<=capital<=1e7 or capital<1000 or not 1<=lot_size<=1000 or not 1<=max_lots<=3 or not 0<=wings<=10:
        raise ValueError("Invalid completed-session, capital or lot/wing assumptions")
    start=stop-timedelta(days={60:100,90:150,120:200}[sessions])
    index,hashes,failures=h.shared_index_sources(start,stop,[h.MAX_TOTAL])
    dates=[d for d in sorted(index) if date.fromisoformat(d).weekday()<5][-sessions:]
    if len(dates)!=sessions:raise ValueError("Insufficient observed sessions; no silent smaller study")
    ntrain,nval,_=r.SESSION_SPLITS[sessions]
    train,val,test=dates[:ntrain],dates[ntrain:ntrain+nval],dates[ntrain+nval:]
    if len(train)<MIN_TRAIN_SESSIONS:raise ValueError("Insufficient development history")
    clocks={r._stamp(d,m) for d in val+test for m in range(375)}
    coverage={}
    table,meta=p._load_options([{"session":d} for d in val+test],wings,progress,
                               needed_stamps=clocks,evidence=coverage,evidence_days=val+test)
    if not table:raise ValueError("No usable saved BANKNIFTY rolling option candles")
    report={"version":VERSION,"capital_inr":capital,"premium_and_daily_loss_budget_inr":budget,
            "assumed_lot_size":lot_size,"max_lots":max_lots,"target_net_on_paid_premium":TARGET,"stop_net_on_paid_premium":STOP,
            "training_dates":train,"validation_dates":val,"evaluation_dates":test,
            "index_sources":hashes,"index_failures":failures,"option_sources":meta,
            "option_window_states":dict(Counter(evidence.window_status(coverage,d,side,today)["state"] for d in val+test for side in ("CALL","PUT"))),
            "validation":{},"evaluation":None,"selected_hold":None,
            "warning":"Exploratory only. Fixed earlier training paths are rescaled by decision-time volatility; European zero-carry constant-IV proxy uses nominal monthly expiry, not a verified exact contract. Forecasts use approximate unrounded charges; replay uses current illustrative Zerodha charges and 35/75 bps adverse premium adjustment per side. No actual historical bid/ask, lot-size or fills. Stops/targets trigger on completed closes, then delayed observed opens; target not guaranteed and losses can exceed 5%. Missing/late evidence penalized in separate stress utility. Daily accounts reset, not compounded. Previously reviewed dates are not fresh confirmation. No ML/RL, orders, or provider requests."}
    for hold in HOLDS:
        if progress:progress(50,"Validation "+str(hold)+"-minute holding policy")
        result=replay(index,train,table,val,hold,capital=capital,budget=budget,lot_size=lot_size,max_lots=max_lots,
                      progress=(lambda i,n,d:progress(50,f"Validation {hold}m: {i+1}/{n} {d}")) if progress else None)
        result["qualified"]=_qualified(result)
        report["validation"][str(hold)]=result
    qualified=[x for x in report["validation"].values() if x["qualified"]]
    if qualified:
        best=max(qualified,key=lambda x:(min(v["metrics"]["stress_utility_inr"] for v in x["lanes"].values()),-x["hold_minutes"]))
        hold=best["hold_minutes"];report["selected_hold"]=hold
        report["evaluation"]=replay(index,train,table,test,hold,capital=capital,budget=budget,lot_size=lot_size,max_lots=max_lots,
                                    progress=(lambda i,n,d:progress(85,f"Evaluation {hold}m: {i+1}/{n} {d}")) if progress else None)
    report["state"]="exploratory_evaluation_complete" if qualified else "no_validation_policy_qualified"
    if progress:progress(100,report["state"])
    return report
