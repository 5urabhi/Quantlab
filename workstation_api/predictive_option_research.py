"""Read-only, train-only empirical option response research.

Rolling option candles identify a same-session strike/side/monthly family,
not a verified exchange contract or lot size. Next-open results are
conditional OHLC proxies, not broker execution or historical bid/ask.
"""
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
import math
import re

import numpy as np

from . import historical_alpha as h, constituent_alpha as a
from . import expired_options_backtest as exp, options_history_sync as sync
from . import liquidity_spreads as fees, service

VERSION="predictive_rolling_options_v1"
HORIZONS=(5,10,15,30,60)
FAMILIES=("long_call","long_put","bull_call_debit","bear_put_debit")
MODELS=("index_logistic","constituent_logistic","constituent_boosting")
RULES=("ema_rsi","pressure","opening_breakout","trend_pullback","range_reversion")
MIN_ANALOGS=8
MIN_DAYS=5
MAX_ANALOGS=24
MAX_STRIKES=7
MAX_RECEIPT_BYTES=600*1024*1024
MAX_FEATURE_DISTANCE=3.
POLICY={"version":VERSION,"historical_policy":h.POLICY_HASH,"horizons":HORIZONS,
        "families":FAMILIES,"models":MODELS,"rules":RULES,"splits":[30,10,20],
        "analog_rule":"nearest same-family same-class joint historical option changes, one per training anchor",
        "analog_count":[MIN_ANALOGS,MAX_ANALOGS],"analog_days":MIN_DAYS,"max_distance":MAX_FEATURE_DISTANCE,
        "fill_proxy":"selection at signal close; entry open one whole minute after decision; target open; fixed same strike and side",
        "gate":"positive modeled net at both cost assumptions, modeled profit probability >= 0.55; full premium/gross buys plus fees within budget",
        "risk":"no naked or credit short; independent capital accounts; unresolved entry/exit censors session; realized loss allowance halts new positions"}
POLICY_HASH=sha256(json.dumps(POLICY,sort_keys=True).encode()).hexdigest()


def _clock(row):
    decision=a._stamp(row["decision_utc"])
    target=a._stamp(row["target_utc"])
    return decision-timedelta(minutes=1),decision+timedelta(minutes=1),target


def _load_options(rows,wings,progress=None):
    root=service.DATA/"dhan_expired_options"
    needed={t.isoformat() for row in rows for t in _clock(row)}
    if not rows or not root.exists():
        return {},{"verified_receipts":0,"rejected_receipts":0,"source_hashes":{},"conflicted_bars":0}
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Unsafe original option receipt directory")
    left=min(date.fromisoformat(r["session"]) for r in rows)
    right=max(date.fromisoformat(r["session"]) for r in rows)
    sample_body=exp._request_body(left,left+timedelta(days=1),"MONTH",0,"ATM","CALL")
    keys=[sync._key(exp._request_body(left,left+timedelta(days=1),"MONTH",0,offset,side))
          for side in ("CALL","PUT") for offset in exp._offsets(wings)]
    paths=[]
    for path in root.iterdir():
        if re.fullmatch(r"[a-f0-9]{64}\.json",path.name):
            paths.append(path)
            if len(paths)>sync.MAX_RECEIPTS:
                raise ValueError("Option receipt count exceeds bounded research scan")
    paths.sort()
    table={};conflicts=set();hashes={};rejected=0;budget=MAX_RECEIPT_BYTES
    for i,path in enumerate(paths):
        if progress and i%32==0:
            progress(35+15*i/max(1,len(paths)),"Verifying saved option receipts (no provider calls)")
        try:
            if path.is_symlink() or not path.is_file():
                raise ValueError("Unsafe original receipt")
            size=path.stat().st_size
            if size>exp.MAX_RESPONSE_BYTES+5000:
                raise ValueError("Oversized receipt")
            budget-=size
            if budget<0:
                raise RuntimeError("Bounded receipt read exceeded; reduce study range")
            envelope=json.loads(path.read_text(encoding="utf-8"))
            body=envelope["request"]
            if sync._key(body) not in keys:
                continue
            start,stop=map(date.fromisoformat,(body["fromDate"],body["toDate"]))
            if stop<left or start>right:
                continue
            if envelope.get("source")!=sync.SOURCE or path!=exp._cache_path(body):
                raise ValueError("Original receipt identity mismatch")
            payload=exp._get_cached(body)
            if payload is None:
                raise ValueError("Receipt disappeared")
            hashes[path.stem]=envelope["sha256"]
            for item in exp._normalize(payload,body):
                stamp=item["timestamp_utc"]
                if stamp not in needed:
                    continue
                key=(stamp,item["side"],item["strike"])
                if key in conflicts:
                    continue
                old=table.get(key)
                if old is not None:
                    if any(abs(old[k]-item[k])>.011 for k in ("open","high","low","close")) or old["volume"]!=item["volume"]:
                        conflicts.add(key);table.pop(key,None)
                    continue
                table[key]=item
        except (ValueError,OSError,KeyError,TypeError,OverflowError,AttributeError):
            rejected+=1
    by_stamp=defaultdict(dict)
    for (stamp,side,strike),item in table.items():
        by_stamp[stamp][(side,strike)]=item
    return by_stamp,{"verified_receipts":len(hashes),"rejected_receipts":rejected,
                     "source_hashes":hashes,"conflicted_bars":len(conflicts),"matched_original_bars":len(table)}


def _structures(quotes,spot):
    for side in ("CALL","PUT"):
        pool=sorted([v for (s,_),v in quotes.items() if s==side and v.get("volume",0) is not None
                     and v["volume"]>0 and v["close"]>=5 and abs(v["strike"]/spot-1)<=.03],
                    key=lambda r:(abs(r["strike"]-spot),r["strike"]))[:MAX_STRIKES]
        for first in pool:
            yield ("long_call" if side=="CALL" else "long_put",(first,))
        for first in pool:
            for second in pool:
                width=abs(second["strike"]-first["strike"])
                debit=first["close"]-second["close"]
                if not 0<debit<width:
                    continue
                if (side=="CALL" and first["strike"]<second["strike"]) or (side=="PUT" and first["strike"]>second["strike"]):
                    yield ("bull_call_debit" if side=="CALL" else "bear_put_debit",(first,second))


def _feature(legs,spot,minute):
    # Distances are in fixed, documented scale units, not test-fitted
    # standardization. Premium and moneyness jointly proxy option regime.
    x=[(v["strike"]/spot-1)*100 for v in legs]
    y=[v["close"]/spot*200 for v in legs]
    return np.asarray(x+y+[minute/375.],dtype=float)


def _observations(table,stamp,legs):
    quotes=table.get(stamp.isoformat(),{})
    out=[]
    for leg in legs:
        row=quotes.get((leg["side"],leg["strike"]))
        if row is None or row["session_ist"]!=leg["session_ist"] or row["expiry_flag"]!=leg["expiry_flag"] or row["expiry_code"]!=leg["expiry_code"]:
            return None
        # Positive minute volume is an observation-quality condition;
        # it does not certify a fill or the availability of its open.
        if row["volume"] is None or row["volume"]<=0:
            return None
        out.append(row["open"])
    return out


def _build_analogs(train,table,progress=None):
    pools=defaultdict(list)
    counts=Counter()
    for i,row in enumerate(train):
        if progress and i%20==0:
            progress(50+10*i/max(1,len(train)),"Learning earlier-session joint option responses")
        signal,entry,target=_clock(row)
        quotes=table.get(signal.isoformat(),{})
        for family,legs in _structures(quotes,row["reference_price"]):
            future=_observations(table,target,legs)
            initial=_observations(table,entry,legs)
            if future is None or initial is None:
                counts["missing_training_leg_bars"]+=1
                continue
            ratios=np.asarray(future)/np.asarray([v["close"] for v in legs])
            if not np.all(np.isfinite(ratios)) or np.any(ratios<=0):
                continue
            pools[(family,row["class"])].append((_feature(legs,row["reference_price"],row["index"][6]),
                ratios,i,row["session"]))
            counts["training_structure_observations"]+=1
    return {k:{"x":np.asarray([v[0] for v in values]),"ratios":np.asarray([v[1] for v in values]),
               "anchors":np.asarray([v[2] for v in values]),"days":[v[3] for v in values]}
            for k,values in pools.items()},dict(counts)


def _scenarios(family,legs,row,probabilities,pools):
    feature=_feature(legs,row["reference_price"],row["index"][6])
    prices=np.asarray([v["close"] for v in legs])
    moves=[];weights=[];support={}
    for cls,prob in zip(a.CLASSES,probabilities):
        if prob<=0:
            continue
        pool=pools.get((family,cls))
        if not pool:
            return None
        distance=np.sum((pool["x"]-feature)**2,axis=1)
        order=np.argsort(distance,kind="stable")
        seen=set();idx=[]
        for j in order:
            if distance[j]>MAX_FEATURE_DISTANCE**2:
                break
            anchor=int(pool["anchors"][j])
            if anchor in seen:
                continue
            seen.add(anchor);idx.append(int(j))
            if len(idx)>=MAX_ANALOGS:break
        days={pool["days"][j] for j in idx}
        if len(idx)<MIN_ANALOGS or len(days)<MIN_DAYS:
            return None
        # Paired-leg ratios come from one actual earlier forecast window.
        # Never combine independently sampled call/put leg returns.
        moves.extend(pool["ratios"][idx]*prices)
        weights.extend([float(prob)/len(idx)]*len(idx))
        support[str(cls)]={"anchors":len(idx),"sessions":len(days)}
    if not moves:
        return None
    return np.asarray(moves),np.asarray(weights)/sum(weights),support


def _cash(prices,units,bps,*,entry):
    # Long/debit spread only: buy the first leg, optionally sell second.
    # Explicit adverse premium penalty is a scenario, not observed spread.
    buy=float(prices[0] if entry else prices[1] if len(prices)>1 else 0.)*units*(1+bps/10000)
    sell=float(prices[1] if entry and len(prices)>1 else prices[0] if not entry else 0.)*units*(1-bps/10000)
    return buy,sell


def _funding(prices,units,bps,broker):
    buy,sell=_cash(prices,units,bps,entry=True)
    # The conservative gross-buy proxy includes entry and immediate
    # closing costs. No broker-certified spread margin is inferred.
    xb,xs=_cash(prices,units,bps,entry=False)
    f=fees.fee_schedule(buy+xb,sell+xs,executed_orders_per_side=len(prices),broker_profile=broker)["total_estimated"]
    return fees._money(buy+f)


def _net(entry,exit_,units,bps,broker):
    eb,es=_cash(entry,units,bps,entry=True)
    xb,xs=_cash(exit_,units,bps,entry=False)
    tariff=fees.fee_schedule(eb+xb,es+xs,executed_orders_per_side=len(entry),broker_profile=broker)
    return fees._money(es+xs-eb-xb-tariff["total_estimated"]),tariff["total_estimated"]


def _candidate(family,legs,row,probs,pools,budget,lot_size,max_lots,bps,broker,rejected):
    entry=[v["close"] for v in legs]
    stress=bps+10.
    affordable=[n for n in range(1,max_lots+1) if _funding(entry,n*lot_size,stress,broker)<=budget]
    if not affordable:
        rejected["capital_or_position_risk_proxy"]+=1
        return None
    scenarios=_scenarios(family,legs,row,probs,pools)
    if scenarios is None:
        rejected["insufficient_training_analogs"]+=1
        return None
    outcomes,weights,support=scenarios
    best=None
    for lots in affordable:
        units=lots*lot_size
        # The same paired scenarios and probabilities are used for both
        # cost assumptions; no favorable scenario is selected ex post.
        base=np.asarray([_net(entry,v,units,bps,broker)[0] for v in outcomes])
        adverse=np.asarray([_net(entry,v,units,stress,broker)[0] for v in outcomes])
        expected=float(np.dot(weights,base));worst=float(np.dot(weights,adverse))
        chance=float(weights[adverse>0].sum())
        if min(expected,worst)<=0 or chance<.55:
            rejected["modeled_net_or_profit_probability_gate"]+=1
            continue
        risk=_funding(entry,units,stress,broker)
        # Prefer greater stress-adjusted expected net, then lower funding.
        rank=(worst,expected,-risk)
        if best is None or rank>best[0]:
            best=(rank,{"family":family,"legs":legs,"lots":lots,"units":units,"expected_net_inr":expected,
                        "stress_expected_net_inr":worst,"scenario_profit_probability":chance,
                        "funding_proxy_inr":risk,"analog_support":support})
    return best[1] if best else None


def _select(row,table,probs,pools,budget,lot_size,max_lots,bps,broker,direction=None,family_filter=None):
    signal,_,_=_clock(row)
    rejected=Counter();best=None
    for family,legs in _structures(table.get(signal.isoformat(),{}),row["reference_price"]):
        if family_filter and family not in family_filter:continue
        if direction and ((direction==1)!=(family in ("long_call","bull_call_debit"))):continue
        c=_candidate(family,legs,row,probs,pools,budget,lot_size,max_lots,bps,broker,rejected)
        if c is not None:
            rank=(c["stress_expected_net_inr"],c["expected_net_inr"],-c["funding_proxy_inr"])
            if best is None or rank>best[0]:
                best=(rank,c)
    return (best[1] if best else None),dict(rejected)


def _rule_prior(train,rule,call):
    # Empirical class frequencies among earlier instances of the same
    # rule decision; Laplace smoothing, no holdout outcome information.
    observed=[r for r in train if a._rule(r[rule])==call]
    if len(observed)<20 or len({r["session"] for r in observed})<10:
        return None
    return np.asarray([(1+sum(r["class"]==c for r in observed))/(len(observed)+3) for c in a.CLASSES])


def _outcome(candidate,row,table,budget,bps,broker):
    _,entry_at,target=_clock(row);legs=candidate["legs"];units=candidate["units"]
    initial=_observations(table,entry_at,legs)
    if initial is None:
        return {"state":"entry_unobservable","net_pnl_inr":None}
    if _funding(initial,units,bps+10,broker)>budget:
        return {"state":"entry_budget_rejected","net_pnl_inr":None}
    if len(initial)==2 and not 0<initial[0]-initial[1]<abs(legs[0]["strike"]-legs[1]["strike"]):
        return {"state":"entry_structure_rejected","net_pnl_inr":None}
    final=_observations(table,target,legs)
    if final is None:
        return {"state":"exit_unobservable","net_pnl_inr":None,"entry_prices":initial}
    net,cost=_net(initial,final,units,bps,broker)
    stress,stress_fees=_net(initial,final,units,bps+10,broker)
    return {"state":"scored_conditional_ohlc","net_pnl_inr":net,"stress_net_pnl_inr":stress,
            "fees_inr":cost,"stress_fees_inr":stress_fees,"entry_prices":initial,"exit_prices":final}


def _evaluate(train,cal,test,table,pools,capital,max_loss,lot_size,max_lots,bps,broker,progress):
    configs={name:(name,None) for name in MODELS}
    configs.update({"constituent_directional":("constituent_logistic",("long_call","long_put")),
                    "constituent_debit_spreads":("constituent_logistic",("bull_call_debit","bear_put_debit"))})
    configs.update({name:(name,None) for name in RULES})
    probs={}
    for name in MODELS:
        fit=a._fit(name,train)
        probs[name]=a._temperature(a._predict(fit,test),a._calibrate(a._predict(fit,cal),cal))
    priors={(rule,call):_rule_prior(train,rule,call) for rule in RULES for call in (-1,1)}
    records=[];summary={}
    for j,(name,(model,families)) in enumerate(configs.items()):
        balance=capital;peak=capital;drawdown=0.;day=None;loss=0.;blocked=False;counts=Counter()
        scored=[];total_fees=0.;stress_total=0.;gaps=0
        for i,row in enumerate(test):
            if progress and i%12==0:
                progress(60+39*(j+i/max(1,len(test)))/len(configs),"Evaluating "+name+" on later sessions")
            if row["session"]!=day:
                day=row["session"];loss=0.;blocked=False
            budget=max(0.,min(balance,capital,max_loss-loss))
            record={"method":name,"session":day,"decision_utc":row["decision_utc"],"target_utc":row["target_utc"],
                    "state":"no_trade","family":"","lots":0,"units":0,"strikes_json":"","probabilities_json":"",
                    "expected_net_inr":None,"stress_expected_net_inr":None,"scenario_profit_probability":None,
                    "funding_proxy_inr":None,"analog_support_json":"","net_pnl_inr":None,"stress_net_pnl_inr":None,
                    "fees_inr":None,"entry_prices_json":"","exit_prices_json":"","conditional_balance_inr":balance,
                    "rejections_json":""}
            if blocked or budget<=0:
                record["state"]="session_halted"
            elif not table.get(_clock(row)[0].isoformat()):
                record["state"]="missing_signal_option_bars";gaps+=1
            else:
                direction=None
                if model in RULES:
                    direction=a._rule(row[model])
                    probabilities=priors.get((model,direction))
                else:
                    probabilities=probs[model][i]
                if probabilities is not None:
                    record["probabilities_json"]=json.dumps([float(v) for v in probabilities])
                    candidate,rejections=_select(row,table,probabilities,pools,budget,lot_size,max_lots,bps,broker,direction,families)
                    record["rejections_json"]=json.dumps(rejections,sort_keys=True)
                    if candidate:
                        record.update(family=candidate["family"],lots=candidate["lots"],units=candidate["units"],
                            strikes_json=json.dumps([v["strike"] for v in candidate["legs"]]),
                            expected_net_inr=candidate["expected_net_inr"],stress_expected_net_inr=candidate["stress_expected_net_inr"],
                            scenario_profit_probability=candidate["scenario_profit_probability"],funding_proxy_inr=candidate["funding_proxy_inr"],
                            analog_support_json=json.dumps(candidate["analog_support"],sort_keys=True))
                        outcome=_outcome(candidate,row,table,budget,bps,broker)
                        record.update(state=outcome["state"],net_pnl_inr=outcome["net_pnl_inr"],
                            stress_net_pnl_inr=outcome.get("stress_net_pnl_inr"),fees_inr=outcome.get("fees_inr"),
                            entry_prices_json=json.dumps(outcome.get("entry_prices",[])),exit_prices_json=json.dumps(outcome.get("exit_prices",[])))
                        if outcome["state"]=="scored_conditional_ohlc":
                            pnl=outcome["net_pnl_inr"];scored.append(pnl);balance+=pnl;loss+=max(0.,-pnl)
                            total_fees+=outcome["fees_inr"];stress_total+=outcome["stress_net_pnl_inr"]
                            peak=max(peak,balance);drawdown=max(drawdown,peak-balance)
                        elif outcome["state"] in ("entry_unobservable","exit_unobservable"):
                            blocked=True;gaps+=1
                elif model in RULES and direction not in (0,None):
                    record["state"]="insufficient_rule_training_support"
            record["conditional_balance_inr"]=fees._money(balance)
            counts[record["state"]]+=1;records.append(record)
        summary[name]={"states":dict(counts),"eligible_windows":len(test),"scored_trades":len(scored),
                       "positive_trades":sum(v>0 for v in scored),"negative_trades":sum(v<0 for v in scored),
                       "conditional_net_inr":fees._money(sum(scored)) if scored else None,
                       "conditional_stress_net_inr":fees._money(stress_total) if scored else None,
                       "conditional_fees_inr":fees._money(total_fees),"conditional_drawdown_inr":fees._money(drawdown),
                       "unobservable_windows":gaps,"conditional_end_balance_inr":fees._money(balance),
                       "full_account_pnl_certified":False}
    summary["no_trade"]={"states":{"no_trade":len(test)},"eligible_windows":len(test),"scored_trades":0,
                         "positive_trades":0,"negative_trades":0,"conditional_net_inr":0.,"conditional_stress_net_inr":0.,
                         "conditional_fees_inr":0.,"conditional_drawdown_inr":0.,"unobservable_windows":0,
                         "conditional_end_balance_inr":capital,"full_account_pnl_certified":False}
    return summary,records


def run(*,batch_id,horizon=15,capital=17000.,max_loss=4250.,lot_size=30,max_lots=3,wings=3,
        premium_penalty_bps=25.,broker_profile="zerodha",progress=None):
    if horizon not in HORIZONS or type(lot_size) is not int or not 1<=lot_size<=1000 or type(max_lots) is not int or not 1<=max_lots<=3 or type(wings) is not int or not 0<=wings<=3:
        raise ValueError("Select supported horizon, hypothetical historical lot size, max three lots and ATM wings 0–3")
    if not all(math.isfinite(v) for v in (capital,max_loss,premium_penalty_bps)) or not 1000<=capital<=1e7 or not 0<max_loss<=capital or not 0<=premium_penalty_bps<=200 or broker_profile not in fees.BROKER_PROFILES:
        raise ValueError("Invalid research capital, loss allowance, cost or brokerage assumption")
    raw,start,stop,intervals,resolved=h._batch(batch_id)
    if progress:progress(1,"Reading pinned historical membership and shared original candles")
    index,stocks,source_hashes,source_failures=h._sources(batch_id,raw,start,stop,resolved,None)
    dates=sorted(index)[:a.REQUIRED]
    splits=[dates[:a.TRAIN],dates[a.TRAIN:a.TRAIN+a.CALIBRATION],dates[a.TRAIN+a.CALIBRATION:]]
    samples=[];counts=Counter()
    for i,day in enumerate(dates):
        if progress:progress(5+29*i/max(1,len(dates)),"Auditing fixed historical prediction windows: "+day)
        members=h._member_set(intervals,day)
        rows,c=h._sample_day(day,index[day],stocks,members,{s:1. for s in members} if members else None,horizon,dates[:i])
        samples.extend(rows);counts.update(c)
    train,cal,test=([r for r in samples if r["session"] in set(part)] for part in splits)
    result={"version":VERSION,"policy_sha256":POLICY_HASH,"batch_id":batch_id,
            "horizon_minutes":horizon,"capital_inr":capital,"session_loss_allowance_inr":max_loss,
            "assumed_historical_lot_size":lot_size,"max_lots":max_lots,"premium_penalty_bps":premium_penalty_bps,
            "stress_penalty_bps":premium_penalty_bps+10,"broker_profile":broker_profile,"recorded_sessions":len(dates),
            "training_dates":splits[0],"calibration_dates":splits[1],"holdout_dates":splits[2],
            "support":{"training":a.support(train),"calibration":a.support(cal),"holdout":a.support(test)},
            "evidence_counts":dict(counts),"source_failures":source_failures,"methods":{},"run_id":None,
            "state":"insufficient_matched_evidence","broker_orders_enabled":False,"live_model_promoted":False,
            "warning":"Historical rolling near-monthly OHLC proxies only. Exact exchange expiry IDs, historical lot sizes, bid/ask, depth, margin and fills are not verified. "
            "Long options and debit verticals only; credit spreads are excluded until broker margin/terms can be verified. "
            "Joint earlier-session option responses incorporate observed price/volatility changes without inventing historical IV. "
            "The selected models are exploratory; incomplete windows and censored sessions mean conditional P&L is not a certified account result. "
            "Each method has its own capital; current tariff and explicit premium penalties are hypothetical historical costs."}
    option_meta={"source_hashes":{}}
    if len(dates)==a.REQUIRED and a._supported(train,60,20,train=True) and a._supported(cal,20,7) and a._supported(test,40,12):
        table,option_meta=_load_options(samples,wings,progress)
        pools,training_counts=_build_analogs(train,table,progress)
        result["evidence_counts"].update(training_counts)
        result["option_coverage"]={k:v for k,v in option_meta.items() if k!="source_hashes"}
        result["analog_pool_counts"]={family+":"+str(cls):len(v["anchors"]) for (family,cls),v in pools.items()}
        if pools:
            methods,records=_evaluate(train,cal,test,table,pools,capital,max_loss,lot_size,max_lots,premium_penalty_bps,broker_profile,progress)
            result.update(state="conditional_holdout_assessment_available",methods=methods,run_id=a._save(records))
        else:
            result["state"]="insufficient_training_option_observations"
    evidence={"result":result,"index_and_constituent_sources":source_hashes,"option_sources":option_meta["source_hashes"],
              "membership_sha256":raw["historical_index"]["intervals_sha256"]}
    result["audit_id"]=a._save([{"day":"RUN_SUMMARY","evidence_json":json.dumps(evidence,sort_keys=True,allow_nan=False)}],audit=True)
    if progress:progress(100,"Predictive option comparison and original source audit saved")
    return result
