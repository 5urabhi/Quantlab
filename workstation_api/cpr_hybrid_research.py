"""CPR + previous OHLC + EMA 9/21: bounded offline options research.

No provider calls, orders, live policy promotion, or forward-filled quotes.
An observed rolling monthly option family is not an exact listed contract.
All actions use completed bars and delayed next-open price proxies.
"""
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from math import isfinite
import json

from . import historical_alpha as h, predictive_option_research as p
from . import alpha_retraining, liquidity_spreads as fees

VERSION = "cpr_ml_offline_q_v1"
SPLITS = (30, 10, 20)
TARGET = .10
STOP = -.05
CLASSES = ("target", "stop", "other")
METHODS = ("no_stop", "fixed_stop", "ml_fixed", "offline_q", "ml_offline_q", "no_trade")
FRAMES = (1, 3, 5, 15)
HOLDS = (15, 30, 60, 120)
MIN_STATE_EPISODES = 5
MIN_STATE_DAYS = 3
WARNING = (
    "Historical conditional OHLC proxies only: same-session rolling near-monthly "
    "strike/side, assumed lot size, no verified exact contract, bid/ask or fills. "
    "Prior OHLC uses the preceding observed complete index session, not an official "
    "exchange-calendar guarantee. Positive minute volume is an observation-quality "
    "condition, not execution proof. Decisions use completed bars, then delay "
    "one full minute before modeled entry/exit at an observed open. Stops and targets "
    "are net marks, not guaranteed realized prices. Missing paths are censored, not "
    "zero P&L. Current tariff and adverse premium penalties are cost assumptions. "
    "Independent daily accounts reset to starting capital; the aggregate is not a compounded account path. "
    "No-stop is a paper comparator only; full premium may be lost. No live approval."
)


def _stamp(day, minute):
    return (datetime.combine(date.fromisoformat(day), datetime.min.time(), h.IST)
            + timedelta(minutes=555+minute)).astimezone(timezone.utc).isoformat()


def _cpr(previous):
    if set(previous) != set(range(375)):
        return None
    op = previous[0][0]
    hi = max(x[1] for x in previous.values())
    lo = min(x[2] for x in previous.values())
    close = previous[374][3]
    pivot = (hi+lo+close)/3
    bc = (hi+lo)/2
    tc = 2*pivot-bc
    return (op, hi, lo, close, pivot, min(bc,tc), max(bc,tc))


def _bar_closes(bars, frame):
    return [bars[m][3] for m in range(frame-1,375,frame)]


def _signals(day, bars, prev_day, previous, *, frame, hold, max_signals):
    levels = _cpr(previous)
    # Exclude unusually stale previous observed sessions; holidays are not inferred.
    if levels is None or not 0 < (date.fromisoformat(day)-date.fromisoformat(prev_day)).days <= 4:
        return [], "prior_complete_session_unavailable"
    op,hi,lo,close,pivot,bottom,top=levels
    seed=_bar_closes(previous,frame)
    if len(seed)<21:
        return [], "ema_warmup_unavailable"
    fast,slow=h._ema(seed,9),h._ema(seed,21)
    rows=[]
    last=-hold-10
    for m in range(frame-1,375,frame):
        if any(k not in bars for k in range(m-frame+1,m+1)):
            # A later EMA would silently skip a missing interval. Stop this session.
            return rows,"index_gap"
        price=bars[m][3]
        old=fast-slow
        fast+=(price-fast)*2/10
        slow+=(price-slow)*2/22
        gap=fast-slow
        # Decision at m+1; entry m+2. Terminal exit open <=374.
        if m+2+hold>374 or m<=last+hold+2 or len(rows)>=max_signals:
            continue
        side="CALL" if old<=0<gap and price>top else "PUT" if old>=0>gap and price<bottom else None
        if side is None:
            continue
        # Continuous EMA warmup uses only prior completed bars. The crossover
        # plus CPR side is one explicit hypothesis, not a claim about manual rules.
        scale=10000/price
        direction=1 if side=="CALL" else -1
        x=[direction*(price-z)*scale for z in (op,hi,lo,close,pivot,bottom,top)]
        x += [(top-bottom)*scale, direction*gap*scale, m/375.]
        rows.append({"session":day,"prior_session":prev_day,"minute":m,
                     "side":side,"spot":price,"features":x,
                     "decision_utc":_stamp(day,m+1),"entry_utc":_stamp(day,m+2),
                     "target_utc":_stamp(day,m+2+hold)})
        last=m
    return rows,"complete_clock"


def _observed(table, day, minute, side, strike):
    row=table.get(_stamp(day,minute),{}).get((side,strike))
    if not row or row.get("session_ist")!=day or row.get("expiry_flag")!="MONTH" or row.get("expiry_code")!=1:
        return None
    if row.get("volume") is None or row["volume"]<=0:
        return None
    if any(type(row.get(k)) not in (int,float) or not isfinite(row[k]) or row[k]<=0 for k in ("open","close")):
        return None
    return row


def _fund(price,units,bps):
    # Conservative reserve: entry premium plus estimated round-trip charges
    # at unchanged premium. This does not certify any broker fill.
    return p._funding([price],units,bps,"zerodha")


def _net(entry,exit_,units,bps):
    return p._net([entry],[exit_],units,bps,"zerodha")


def _episode(signal,table,index,*,hold,lot_size,max_lots,risk_budget,bps):
    day,m,side,spot=(signal[k] for k in ("session","minute","side","spot"))
    quotes=table.get(_stamp(day,m),{})
    candidates=[]
    for (s,k),row in quotes.items():
        if s!=side or abs(k/spot-1)>.015 or row.get("close",0)<5:
            continue
        if not _observed(table,day,m,s,k):
            continue
        # Select from information available at signal close, never from future path.
        for lots in range(1,max_lots+1):
            units=lots*lot_size
            funding=_fund(row["close"],units,bps)
            if funding<=risk_budget:
                candidates.append((abs(k-spot),lots,k,units,funding,row["close"]))
    if not candidates:
        return {**signal,"state":"no_affordable_observed_contract"}
    _,lots,strike,units,planned,signal_premium=min(candidates)
    ep={**signal,"strike":strike,"lots":lots,"units":units,"planned_funding":planned,
        "features":signal["features"]+[(strike/spot-1)*10000,signal_premium/spot*10000,planned/risk_budget],
        "state":"missing_entry","path":[]}
    first=m+2
    entry=_observed(table,day,first,side,strike)
    if entry is None:
        return ep
    funding=_fund(entry["open"],units,bps)
    if funding>risk_budget:
        return {**ep,"state":"entry_limit_exceeded","observed_funding":funding}
    debit=entry["open"]*units*(1+bps/10000)
    ep.update(state="entered",entry=entry["open"],funding=funding,debit=debit)
    peak=None
    # A mark at close j can cause an exit at open j+2. Last such exit is
    # the deadline. Missing marks or fills terminate the observed trajectory.
    for j in range(first,first+hold-1):
        bar=_observed(table,day,j,side,strike)
        future=_observed(table,day,j+2,side,strike)
        spot_bar=index.get(j)
        if bar is None or future is None or spot_bar is None:
            ep["path_gap_minute"]=j
            break
        mark,_=_net(ep["entry"],bar["close"],units,bps)
        net,charges=_net(ep["entry"],future["open"],units,bps)
        r=mark/debit
        peak=r if peak is None else max(peak,r)
        trend=(1 if side=="CALL" else -1)*(spot_bar[3]/spot-1)
        ep["path"].append({"minute":j,"elapsed":j-first+1,"mark_return":r,
                           "drawdown":peak-r,"trend":trend,
                           "exit_net":net,"exit_fees":charges,
                           "exit_utc":_stamp(day,j+2),"terminal":j==first+hold-2})
    return ep


def _key(step):
    r=step["mark_return"]
    pnl=sum(r>=b for b in (-.05,-.02,0.,.03,.06,.10))
    elapsed=sum(step["elapsed"]>=b for b in (5,15,30,60))
    return (pnl,elapsed,int(step["trend"]>=0),int(step["drawdown"]>=.03))


def _forced(step, *, stop):
    if step["mark_return"]>=TARGET:
        return "target"
    if stop and step["mark_return"]<=STOP:
        return "stop"
    if step["terminal"]:
        return "timeout"
    return None


def _exit(ep, policy, q=None):
    if ep["state"]!="entered":
        return {"state":ep["state"]}
    for step in ep["path"]:
        reason=_forced(step,stop=policy!="no_stop")
        if reason is None and policy=="offline_q":
            values=(q or {}).get(_key(step))
            # Unknown or tied states use the fixed target/stop baseline.
            if values is not None and values[0]>values[1]:
                reason="learned_exit"
        if reason:
            return {"state":"complete","reason":reason,"net":step["exit_net"],
                    "fees":step["exit_fees"],"exit_utc":step["exit_utc"],
                    "net_return":step["exit_net"]/ep["debit"],
                    "target_realized":step["exit_net"]/ep["debit"]>=TARGET}
    return {"state":"exit_censored"}


def _label(result):
    # Label the delayed realized net outcome, not a target/stop mark.
    return "target" if result["net_return"]>=TARGET else "stop" if result["net_return"]<=STOP else "other"


def _training_rows(episodes):
    out=[]
    for ep in episodes:
        if ep["state"]!="entered":
            continue
        result=_exit(ep,"fixed_stop")
        if result["state"]=="complete":
            out.append((ep,result))
    return out


def _fit_q(episodes, *, sweeps=20):
    """Batch fitted tabular Q iteration on earlier, fully observed paths.

    Reward is terminal net return. Hold reward is zero. Finite horizon and
    compulsory exits are outside the learned action set. Each observed path
    supplies counterfactual hold/exit marks under the same price proxy.
    """
    transitions=defaultdict(list)
    for ep in episodes:
        if ep["state"]!="entered" or not ep["path"] or not ep["path"][-1]["terminal"]:
            continue
        for i,step in enumerate(ep["path"][:-1]):
            if _forced(step,stop=True):
                break
            nxt=ep["path"][i+1]
            transitions[_key(step)].append((ep["session"],ep["minute"],
                step["exit_net"]/ep["debit"],_key(nxt),
                nxt["exit_net"]/ep["debit"],bool(_forced(nxt,stop=True))))
    supported={k:v for k,v in transitions.items()
               if len({(x[0],x[1]) for x in v})>=MIN_STATE_EPISODES
               and len({x[0] for x in v})>=MIN_STATE_DAYS}
    q={k:(sum(x[2] for x in v)/len(v),0.) for k,v in supported.items()}
    for _ in range(sweeps):
        new={}
        for k,rows in supported.items():
            # Average within each episode first, so long paths cannot dominate.
            per_episode=defaultdict(list)
            for day,minute,exit_r,nk,next_r,terminal in rows:
                continuation=next_r if terminal or nk not in q else max(q[nk])
                per_episode[(day,minute)].append((exit_r,continuation))
            averages=[(sum(x[0] for x in v)/len(v),sum(x[1] for x in v)/len(v))
                      for v in per_episode.values()]
            new[k]=(sum(x[0] for x in averages)/len(averages),
                    sum(x[1] for x in averages)/len(averages))
        q=new
    return q,{"supported_states":len(q),"observed_states":len(transitions),
              "training_transitions":sum(len(v) for v in transitions.values()),
              "sweeps":sweeps}


def _fit_ml(train,validation):
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    import numpy as np
    tr=_training_rows(train);va=_training_rows(validation)
    counts=Counter(_label(r) for _,r in tr)
    info={"training_labels":dict(counts),"validation_labels":dict(Counter(_label(r) for _,r in va)),
          "training_episodes":len(tr),"validation_episodes":len(va),"validation_brier":{}}
    if (len(tr)<40 or len({e["session"] for e,_ in tr})<15
            or min(counts.get(c,0) for c in CLASSES)<5
            or len(va)<10 or len({e["session"] for e,_ in va})<5):
        return None,{},info
    X=[e["features"] for e,_ in tr];y=[_label(r) for _,r in tr]
    V=[e["features"] for e,_ in va]
    truth=np.asarray([[float(_label(r)==c) for c in CLASSES] for _,r in va])
    models={"logistic":make_pipeline(StandardScaler(),LogisticRegression(max_iter=500,random_state=42)),
            "random_forest":RandomForestClassifier(n_estimators=100,max_depth=4,min_samples_leaf=5,
                                                  random_state=42,n_jobs=1)}
    fitted={}
    for name,model in models.items():
        model.fit(X,y)
        prob=model.predict_proba(V)
        ordered=prob[:,[list(model.classes_).index(c) for c in CLASSES]]
        info["validation_brier"][name]=float(np.mean(np.sum((ordered-truth)**2,axis=1)))
        fitted[name]=model
    selected=min(fitted,key=lambda n:(info["validation_brier"][n],n))
    info["selected"]=selected
    means={c:sum(r["net_return"] for _,r in tr if _label(r)==c)/counts[c] for c in CLASSES}
    info["train_only_class_mean_returns"]=means
    return fitted[selected],means,info


def _holdout_ml(model, episodes):
    import numpy as np
    rows=_training_rows(episodes)
    if model is None or not rows:
        return {"scored":0,"brier":None,"labels":{}}
    truth=np.asarray([[float(_label(r)==c) for c in CLASSES] for _,r in rows])
    pred=model.predict_proba([e["features"] for e,_ in rows])
    ordered=pred[:,[list(model.classes_).index(c) for c in CLASSES]]
    return {"scored":len(rows),"brier":float(np.mean(np.sum((ordered-truth)**2,axis=1))),
            "labels":dict(Counter(_label(r) for _,r in rows)),
            "predicted_target_mean":float(np.mean(ordered[:,0])),
            "observed_target_fraction":float(np.mean(truth[:,0])),
            "note":"Conditional on observable fixed-stop exit; missing outcomes are not scored."}


def _ml_accept(model,means,ep):
    if model is None:
        return False
    pr=dict(zip(model.classes_,model.predict_proba([ep["features"]])[0]))
    ev=sum(float(pr[c])*means[c] for c in CLASSES)
    return float(pr["target"])>=.50 and ev>0


def _evaluate(episodes,*,method,capital,risk_budget,model=None,means=None,q=None):
    balance=capital; peak=capital;dd=0.;gross_losses=0.;day=None;halted=False
    daily=defaultdict(lambda:{"conditional_net_inr":0.,"scored":0,"unresolved":0})
    counts=Counter();journal=[];net=0.;charges=0.;winners=0;targets=0
    for ep in episodes:
        if day!=ep["session"]:
            day=ep["session"];gross_losses=0.;halted=False
            # Independent day accounts avoid carrying unobserved positions into
            # the next session. Aggregate net is not a compounded account path.
            balance=capital;peak=capital
        state=None
        if method=="no_trade":
            state="no_trade"
        elif halted:
            state="session_halted"
        elif ep["state"]=="no_affordable_observed_contract":
            state=ep["state"]
        elif ep["planned_funding"]>min(balance,risk_budget-gross_losses):
            state="remaining_budget_gate"
        elif method.startswith("ml_") and not _ml_accept(model,means,ep):
            state="ml_abstain"
        if state:
            result={"state":state}
        elif ep["state"]=="entered" and ep["funding"]>min(balance,risk_budget-gross_losses):
            result={"state":"entry_limit_exceeded"}
        else:
            result=_exit(ep,"offline_q" if method.endswith("offline_q") else method if method=="no_stop" else "fixed_stop",q)
        state=result["state"]
        counts[state]+=1
        if state=="complete":
            value=result["net"];net+=value;charges+=result["fees"];balance+=value
            gross_losses+=max(0.,-value);peak=max(peak,balance);dd=max(dd,peak-balance)
            winners+=int(value>0);targets+=int(result["target_realized"])
            daily[day]["conditional_net_inr"]+=value;daily[day]["scored"]+=1
        elif state in ("missing_entry","exit_censored"):
            halted=True
            daily[day]["unresolved"]+=1
        journal.append({"method":method,"session":day,"decision_utc":ep["decision_utc"],
                        "side":ep["side"],"strike":ep.get("strike"),**result})
    scored=counts["complete"]
    unresolved=counts["missing_entry"]+counts["exit_censored"]
    return {"states":dict(counts),"signals":len(episodes),"scored_trades":scored,
            "profitable_trades":winners,"realized_target_hits":targets,
            "conditional_net_inr":round(net,2) if scored or method=="no_trade" else None,
            "conditional_fees_inr":round(charges,2),"max_within_day_closed_drawdown_inr":round(dd,2),
            "independent_daily_accounts":True,"daily":dict(daily),
            "unresolved_trades":unresolved,"full_account_pnl_certified":False},journal


def run(*,from_date,to_date,frame=5,hold=60,capital=17000.,risk_budget=4250.,
        lot_size=30,max_lots=1,wings=3,premium_penalty_bps=25.,progress=None):
    start,stop=map(date.fromisoformat,(from_date,to_date))
    now=datetime.now(timezone.utc)
    if not alpha_retraining.safe_window(now):
        raise ValueError("Run CPR research outside Indian market priority hours")
    if not 0<(stop-start).days<=120 or stop>now.astimezone(h.IST).date():
        raise ValueError("Select up to 120 calendar days, completed sessions, end exclusive")
    if frame not in FRAMES or hold not in HOLDS or type(lot_size) is not int or not 1<=lot_size<=1000 or type(max_lots) is not int or not 1<=max_lots<=3 or type(wings) is not int or not 0<=wings<=3:
        raise ValueError("Unsupported timeframe, hold, historical lot assumption or wings")
    if not all(type(v) in (int,float) and isfinite(v) for v in (capital,risk_budget,premium_penalty_bps)) or not 1000<=capital<=1e7 or not 0<risk_budget<=capital or not 0<=premium_penalty_bps<=200:
        raise ValueError("Invalid research capital, premium exposure or cost assumption")
    if progress:progress(1,"Verifying original BANKNIFTY minute receipts")
    index,index_hashes,failures=h.shared_index_sources(start-timedelta(days=7),stop,[h.MAX_TOTAL])
    ordered=sorted(index)
    dates=[d for d in ordered if from_date<=d<to_date][-sum(SPLITS):]
    splits=[dates[:30],dates[30:40],dates[40:60]]
    signals=[];counts=Counter();day_audit={}
    for day in dates:
        i=ordered.index(day)
        if not i:
            day_audit[day]={"state":"prior_session_missing","signals":0}
            continue
        prior=ordered[i-1]
        rows,status=_signals(day,index[day],prior,index[prior],frame=frame,hold=hold,max_signals=3)
        signals.extend(rows)
        counts[status]+=1
        day_audit[day]={"state":status,"signals":len(rows),"prior_session":prior}
    needed={_stamp(s["session"],m) for s in signals
            for m in range(s["minute"],s["minute"]+hold+3)}
    table,meta=p._load_options(signals,wings,progress,needed_stamps=needed)
    if progress:progress(52,"Constructing fixed-strike delayed execution trajectories")
    # Use adverse penalty for all primary training and evaluation, not ex-post
    # stress selection. Report explicit sensitivity as an additional study later.
    bps=premium_penalty_bps+10
    episodes=[_episode(s,table,index[s["session"]],hold=hold,lot_size=lot_size,max_lots=max_lots,
                       risk_budget=risk_budget,bps=bps) for s in signals]
    parts=[[e for e in episodes if e["session"] in set(ds)] for ds in splits]
    report={"version":VERSION,"settings":{"from_date":from_date,"to_exclusive":to_date,"timeframe":frame,
             "hold_minutes":hold,"capital_inr":capital,"full_premium_and_fee_budget_inr":risk_budget,
             "historical_lot_size_assumed":lot_size,"max_lots":max_lots,"strike_wings":wings,
             "primary_adverse_penalty_bps_per_side":bps,"target_net_return":TARGET,"fixed_stop_mark":STOP},
             "recorded_index_sessions":len(dates),"required_sessions":sum(SPLITS),
             "training_dates":splits[0],"validation_dates":splits[1],"holdout_dates":splits[2],
             "signal_counts":dict(counts),"day_audit":day_audit,"episode_states":dict(Counter(e["state"] for e in episodes)),
             "split_support":{name:{"signals":len(rows),"entered":sum(e["state"]=="entered" for e in rows),
                          "fully_observed_paths":sum(bool(e.get("path")) and e["path"][-1]["terminal"] for e in rows)}
                          for name,rows in zip(("train","validation","holdout"),parts)},
             "index_source_failures":failures,"option_coverage":{k:v for k,v in meta.items() if k!="source_hashes"},
             "methods":{},"state":"descriptive_only_insufficient_sessions","broker_orders_enabled":False,
             "live_model_promoted":False,"warning":WARNING}
    journal=[]
    if len(dates)==sum(SPLITS):
        train,val,test=parts
        if progress:progress(65,"Fitting train-only ML and offline Q values; validation chooses ML")
        model,means,ml_info=_fit_ml(train,val)
        q,q_info=_fit_q(train)
        report.update(state="chronological_holdout_assessment",ml=ml_info,offline_q=q_info,
                      ml_holdout=_holdout_ml(model,test),
                      q_policy_sha256=sha256(json.dumps(sorted((list(k),list(v)) for k,v in q.items()),
                                                         separators=(",",":")).encode()).hexdigest())
        for method in METHODS:
            if (method.startswith("ml_") and model is None) or (method.endswith("offline_q") and not q):
                report["methods"][method]={"state":"insufficient_training_support"}
                continue
            metrics,rows=_evaluate(test,method=method,capital=capital,risk_budget=risk_budget,
                                   model=model,means=means,q=q)
            report["methods"][method]=metrics;journal.extend(rows)
    else:
        # Always useful mathematical diagnostic; never labeled independent holdout.
        for method in ("no_stop","fixed_stop","no_trade"):
            metrics,rows=_evaluate(episodes,method=method,capital=capital,risk_budget=risk_budget)
            report["methods"][method]=metrics;journal.extend(rows)
    evidence={"index_sources":index_hashes,"option_sources":meta["source_hashes"]}
    report["source_sha256"]=sha256(json.dumps(evidence,sort_keys=True).encode()).hexdigest()
    if progress:progress(100,"CPR strategy comparison complete")
    return report,journal,evidence
