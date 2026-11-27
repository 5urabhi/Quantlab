"""Non-ML BANKNIFTY momentum/reversal, with matched sector confirmation.

All entry rules use completed bars. The comparison trades only long BANKNIFTY
options with actual historical rolling OHLC proxies and modeled fees.
"""
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from math import isfinite, log, sqrt
import numpy as np
from . import cpr_hybrid_research as r, historical_alpha as h
from . import predictive_option_research as p, expired_options_backtest as exp
from . import cpr_execution_evidence as evidence

VERSION="banknifty_sector_momentum_v1"
PEERS=("INDEX:FINNIFTY","INDEX:NIFTYPRIVATEBANK","INDEX:NIFTYPSUBANK")
RULES=("momentum","mean_reversion","confirmed_momentum","confirmed_reversion")
HOLDS=(5,10,15,30,60)
COSTS=(35,75)
Z_MIN=1.
FRICTION_MAX=.025
LOT_LIMIT=1


def signal_z(bars,m):
    if m<30 or any(k not in bars for k in range(m-30,m+1)):
        return None
    close=np.array([bars[k][3] for k in range(m-30,m+1)],dtype=float)
    if not np.isfinite(close).all() or np.min(close)<=0:return None
    sigma=float(np.sqrt(np.mean(np.diff(np.log(close))**2)))
    if sigma<1e-7:return None
    return float(log(close[-1]/close[-16])/(sigma*sqrt(15)))


def peer_votes(peers,day,m):
    signs=[]
    for key in PEERS:
        bars=peers.get(key,{}).get(day,{})
        if m<5 or any(i not in bars for i in range(m-5,m+1)):
            return None
        first,last=bars[m-5][3],bars[m][3]
        if not all(isfinite(v) and v>0 for v in (first,last)):return None
        signs.append(1 if last>first else -1 if last<first else 0)
    return signs


def side_for(rule,z,votes):
    if not isfinite(z) or abs(z)<Z_MIN:return None
    if rule not in RULES:raise ValueError("Unknown mathematical rule")
    direction=(1 if z>0 else -1)*(1 if rule in ("momentum","confirmed_momentum") else -1)
    if rule.startswith("confirmed") and (votes is None or sum(v==direction for v in votes)<2):return None
    return "CALL" if direction>0 else "PUT"


def choose(table,day,m,spot,lot,budget):
    """Same selection and conservative friction screen for all rules."""
    chosen={};counts=Counter()
    for (side,strike),q in table.get(r._stamp(day,m),{}).items():
        if side not in ("CALL","PUT") or not r._observed(table,day,m,side,strike):continue
        premium=q["close"]
        if premium<5:continue
        counts["observed"]+=1
        funding=r._fund(premium,lot,COSTS[-1])
        if funding>budget:continue
        counts["affordable"]+=1
        loss,_=r._net(premium,premium,lot,COSTS[-1])
        friction=-loss/(premium*lot*(1+COSTS[-1]/10000))
        if friction>FRICTION_MAX:continue
        counts["low_friction"]+=1
        rank=(abs(strike-spot),friction,float(strike),float(premium))
        if side not in chosen or rank<chosen[side]:chosen[side]=rank
    return chosen,counts


def opportunities(index,peers,table,days,lot,budget):
    rows=[];counts=Counter()
    for day in days:
        session=date.fromisoformat(day)
        if exp._nominal_selected_expiry(session,0)<=session:
            counts["nominal_expiry_days_excluded"]+=1
            continue
        bars=index.get(day,{})
        # Identical anchor reservation across horizons.
        for m in range(34,r.SQUAREOFF_MINUTE-max(HOLDS)-1,5):
            counts["reserved_anchors"]+=1
            z=signal_z(bars,m)
            if z is None:
                counts["incomplete_index"]+=1;continue
            votes=peer_votes(peers,day,m)
            if votes is None:
                counts["incomplete_sector_context"]+=1;continue
            counts["matched_anchors"]+=1
            if abs(z)<Z_MIN:
                counts["weak_move"]+=1;continue
            spot=bars[m][3]
            candidates,detail=choose(table,day,m,spot,lot,budget)
            counts.update({"contract_"+k:v for k,v in detail.items()})
            if not candidates:
                counts["no_affordable_low_friction_side"]+=1
            else:
                counts["candidate_anchors"]+=1
            rows.append({"day":day,"minute":m,"spot":spot,"z":z,"votes":votes,"candidates":candidates})
    return rows,dict(counts)


def _lane(index,table,rows,days,rule,hold,cost,capital,budget,lot,cache):
    episodes=[];stats=Counter();moves=[]
    for row in rows:
        day,m=row["day"],row["minute"]
        side=side_for(rule,row["z"],row["votes"])
        if side is None:
            stats["rule_abstain"]+=1;continue
        stats["direction_signals"]+=1
        # Underlying forecast diagnostic: fixed delayed entry to scheduled
        # end open. Future prices affect reporting only, not candidate choice.
        bars=index[day]
        first,last=bars.get(m+2),bars.get(m+hold+2)
        if first and last and first[0]>0 and last[0]>0:
            move=(1 if side=="CALL" else -1)*10000*log(last[0]/first[0])
            moves.append(move)
        if side not in row["candidates"]:
            stats["no_eligible_side_contract"]+=1;continue
        distance,friction,strike,premium=row["candidates"][side]
        key=(day,m,side,hold,cost)
        if key not in cache:
            funding=r._fund(premium,lot,cost)
            signal={"session":day,"minute":m,"side":side,"spot":row["spot"],"features":[row["z"]],
                    "decision_utc":r._stamp(day,m+1),"entry_utc":r._stamp(day,m+2)}
            cache[key]=r._episode(signal,table,index[day],hold=hold,lot_size=lot,max_lots=LOT_LIMIT,
                    risk_budget=budget,bps=cost,candidate=(distance,1,strike,lot,funding,premium))
        episodes.append({**cache[key],"entry_type":rule})
    metrics,journal=r._evaluate(episodes,method="fixed_stop",capital=capital,risk_budget=budget,
                                dates=days,strict_execution=True)
    metrics["rule_coverage"]=dict(stats)
    metrics["spot_forecast"]={"scored":len(moves),"mean_signed_bps":float(np.mean(moves)) if moves else None,
                              "direction_accuracy":float(np.mean(np.asarray(moves)>0)) if moves else None}
    return metrics,journal


def qualified(lanes,*,minimum_trades,minimum_days):
    return all(m["scored_trades"]>=minimum_trades
               and m["daily_coverage"]["days_with_scored_trade"]>=minimum_days
               and (m["conditional_net_inr"] or 0)>0
               and m["stress_utility_inr"]>0 for m in lanes.values())


def _phase(index,table,rows,dates,policies,*,capital,budget,lot,minimum_trades,minimum_days,progress,label,keep_journal=False):
    results=[]
    # Reuse the same causal contract paths across matched policy comparisons.
    # Bound cached paths to one horizon to avoid retaining the full grid.
    for hold in HOLDS:
        cache={}
        for rule in RULES:
            if (rule,hold) not in policies:continue
            lanes={};journals={}
            for cost in COSTS:
                metrics,journal=_lane(index,table,rows,dates,rule,hold,cost,capital,budget,lot,cache)
                lanes[str(cost)]=metrics
                if keep_journal:journals[str(cost)]=journal
            item={"rule":rule,"hold":hold,"lanes":lanes,"qualified":qualified(lanes,minimum_trades=minimum_trades,minimum_days=minimum_days)}
            if keep_journal:item["journals"]=journals
            results.append(item)
            if progress:progress(label,rule,hold,lanes,item["qualified"])
    return results


def run(*,sessions=90,to_date=None,capital=17000.,budget=12000.,lot_size=30,wings=10,progress=None,log=None):
    today=datetime.now(timezone.utc).astimezone(h.IST).date()
    stop=date.fromisoformat(to_date) if to_date else today
    if sessions not in r.SESSION_SPLITS or stop>today or not 0<budget<=capital<=1e7 or capital<1000 or not 1<=lot_size<=1000 or not 0<=wings<=10:
        raise ValueError("Invalid historical date, capital, lot or wings assumption")
    start=stop-timedelta(days={60:100,90:150,120:200}[sessions])
    if log:log("Verifying saved BANKNIFTY spot receipts")
    index,hashes,failures=h.shared_index_sources(start,stop,[h.MAX_TOTAL])
    dates=[d for d in sorted(index) if start.isoformat()<=d<stop.isoformat() and date.fromisoformat(d).weekday()<5][-sessions:]
    if len(dates)!=sessions:raise ValueError("Insufficient completed BANKNIFTY sessions; no silent smaller study")
    ntrain,nval,_=r.SESSION_SPLITS[sessions]
    train,val,test=dates[:ntrain],dates[ntrain:ntrain+nval],dates[ntrain+nval:]
    peers={};peer_sources={};peer_failures={}
    for key in PEERS:
        if log:log("Verifying saved "+key+" receipts")
        peers[key],peer_sources[key],peer_failures[key]=h.shared_index_sources(start,stop,[h.MAX_TOTAL],identity=key)
    clocks={r._stamp(d,m) for d in dates for m in range(375)}
    cov={}
    if log:log("Verifying original saved rolling option receipts (no downloads)")
    table,meta=p._load_options([{"session":d} for d in dates],wings,needed_stamps=clocks,evidence=cov,evidence_days=dates)
    if not table:raise ValueError("No usable saved BANKNIFTY rolling option candles")
    report={"version":VERSION,"capital_inr":capital,"funding_and_daily_realized_loss_budget_inr":budget,
            "assumed_lot_size":lot_size,"lots":LOT_LIMIT,"wings":wings,"target_net_on_paid_premium":r.TARGET,
            "stop_net_on_paid_premium":r.STOP,"max_roundtrip_friction_fraction":FRICTION_MAX,"z_min":Z_MIN,
            "training_dates":train,"validation_dates":val,"evaluation_dates":test,
            "index_sources":hashes,"index_failures":failures,"peer_sources":peer_sources,"peer_failures":peer_failures,
            "option_sources":meta,"option_window_states":dict(Counter(evidence.window_status(cov,d,s,today)["state"] for d in dates for s in ("CALL","PUT"))),
            "coverage":{},"training":[],"validation":None,"evaluation":None,"selected":None,
            "warning":"Exploratory only; no ML/RL or order routing. Same-clock sector context is not independent evidence. Other indices are inputs only. One assumed historical lot; near-month rolling strike/side, nominal expiry-day exclusion, no verified exact contract, bid/ask or fills. Fixed target/stop on modeled net paid-premium marks, then delayed observed opens; losses may exceed stop. 35/75 bps adverse premium adjustment per side and current illustrative Zerodha fees; immediate unchanged-price friction capped at 2.5% at signal, not a live spread guarantee. Independent daily accounts and cumulative realized-loss/funding cap, not compounded account P&L. Previously examined validation/evaluation dates are not untouched confirmation."}
    rows,coverage=opportunities(index,peers,table,train,lot_size,budget)
    report["coverage"]["training"]=coverage
    if coverage.get("matched_anchors",0)<.8*coverage.get("reserved_anchors",1):
        raise ValueError("Insufficient matched sector context in development; cannot compare fairly")
    policies=[(rule,hold) for rule in RULES for hold in HOLDS]
    opts=dict(capital=capital,budget=budget,lot=lot_size,progress=progress)
    report["training"]=_phase(index,table,rows,train,policies,minimum_trades=20,minimum_days=10,label="TRAINING",**opts)
    eligible=[x for x in report["training"] if x["qualified"]]
    if not eligible:
        report["state"]="no_training_policy_qualified";return report
    # Select a single policy on development only, with deterministic tie-break.
    best=max(eligible,key=lambda x:(min(m["stress_utility_inr"] for m in x["lanes"].values()),-x["hold"],-RULES.index(x["rule"])))
    pair=(best["rule"],best["hold"])
    report["selected"]={"rule":pair[0],"hold":pair[1]}
    rows,coverage=opportunities(index,peers,table,val,lot_size,budget)
    report["coverage"]["validation"]=coverage
    if coverage.get("matched_anchors",0)<.8*coverage.get("reserved_anchors",1):
        report["state"]="insufficient_validation_context";return report
    report["validation"]=_phase(index,table,rows,val,[pair],minimum_trades=10,minimum_days=5,label="VALIDATION",keep_journal=True,**opts)[0]
    if not report["validation"]["qualified"]:
        report["state"]="selected_policy_failed_validation";return report
    rows,coverage=opportunities(index,peers,table,test,lot_size,budget)
    report["coverage"]["evaluation"]=coverage
    if coverage.get("matched_anchors",0)<.8*coverage.get("reserved_anchors",1):
        report["state"]="insufficient_evaluation_context";return report
    report["evaluation"]=_phase(index,table,rows,test,[pair],minimum_trades=10,minimum_days=5,label="EXPLORATORY_EVALUATION",keep_journal=True,**opts)[0]
    report["state"]="exploratory_evaluation_complete"
    return report
