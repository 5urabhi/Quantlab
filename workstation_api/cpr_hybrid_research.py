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

VERSION = "cpr_ml_offline_q_v5"
ENTRY_MODES = ("crossover", "daily_scan", "regime_scan")
SCAN_MINUTES = 15
MAX_DAILY_ATTEMPTS = 3
TRAIL_ACTIVATION = .03
TRAIL_GAP = .03
MAX_LEARNING_STRIKES = 11
FEATURE_FUNDING_SCALE = 17000.
EMERGENCY_STOP = -.15
SOURCE_STATES = ("missing_signal_quotes", "no_qualified_observed_contract",
                 "no_affordable_observed_contract")
SPLITS = (30, 10, 20)
TARGET = .10
STOP = -.05
CLASSES = ("target", "stop", "other")
METHODS = ("no_stop", "fixed_stop", "ml_fixed", "offline_q", "ml_offline_q",
           "fixed_emergency_stop", "offline_q_emergency_stop",
           "trailing_stop", "trailing_emergency_stop", "volatility_trailing_stop", "no_trade")
FRAMES = (1, 3, 5, 15)
HOLDS = (15, 30, 60, 120)
MIN_STATE_EPISODES = 5
MIN_STATE_DAYS = 3
WARNING = (
    "Historical conditional OHLC proxies only: same-session rolling near-monthly "
    "strike/side, assumed lot size, no verified exact contract, bid/ask or fills. "
    "Prior OHLC requires the preceding weekday complete index session; "
    "unverified holidays/special sessions are skipped, not inferred. Positive minute volume is an observation-quality "
    "condition, not execution proof. Decisions use completed bars, then delay "
    "one full minute before modeled entry/exit at an observed open. Stops and targets "
    "are net marks, not guaranteed realized prices. Missing paths are censored, not "
    "zero P&L. Current tariff and adverse premium penalties are cost assumptions. "
    "Independent daily accounts reset to starting capital; the aggregate is not a compounded account path. "
    "Learning uses earlier unleveraged counterfactual single-lot trajectories independently of account funding; "
    "multiple strikes at the same signal are correlated and are grouped in support and training weights. "
    "Daily scan opportunities can overlap, but positions cannot; skip signals while holding, halt on unresolved positions, "
    "Ranked entry, global and constituent variants are development-selected retrospective studies; no independently validated live policy. "
    "and cap attempted entries at three per day. Daily trade coverage is not guaranteed. "
    "Previously viewed evaluation dates are exploratory, not a new untouched confirmation set. "
    "Trailing floors use completed net marks only; delayed exits can realize losses beyond those floors. "
    "Open-position risk diagnostics are sampled marks through the exit decision, not intrabar or fill-time maxima. "
    "No-stop and wider-stop modes are paper comparators only; full premium may be lost. No live approval."
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


def _signals(day, bars, prev_day, previous, *, frame, hold, max_signals, learning_grid=False, entry_mode="crossover"):
    levels = _cpr(previous)
    # Fail closed on an unverified missing weekday rather than using a stale
    # CPR. Official holidays/special sessions need separate calendar evidence.
    current=date.fromisoformat(day)
    expected=current-timedelta(days=1)
    while expected.weekday()>=5:
        expected-=timedelta(days=1)
    if levels is None or current.weekday()>=5 or date.fromisoformat(prev_day)!=expected:
        return [], "prior_complete_session_unavailable"
    op,hi,lo,close,pivot,bottom,top=levels
    seed=_bar_closes(previous,frame)
    if len(seed)<21:
        return [], "ema_warmup_unavailable"
    fast,slow=h._ema(seed,9),h._ema(seed,21)
    rows=[]
    last=-hold-10
    # Earlier training only: a fixed calendar grid of nonoverlapping CPR/EMA
    # aligned continuation windows, independent of returns and future availability.
    stride=((max(hold+3,60)+frame-1)//frame)*frame
    first=((30+frame-1)//frame)*frame-1
    grid=set(range(first,375,stride)) if learning_grid else set()
    daily=entry_mode in ("daily_scan","regime_scan") and not learning_grid
    scan_stride=((SCAN_MINUTES+frame-1)//frame)*frame
    opening_complete=False
    opening_hi=opening_lo=None
    previous_close=close
    for m in range(frame-1,375,frame):
        if any(k not in bars for k in range(m-frame+1,m+1)):
            # A later EMA would silently skip a missing interval. Stop this session.
            return rows,"index_gap"
        price=bars[m][3]
        old=fast-slow
        fast+=(price-fast)*2/10
        slow+=(price-slow)*2/22
        gap=fast-slow
        prev_close=previous_close
        previous_close=price
        # Opening range becomes available only after the first 15 minutes.
        if not opening_complete and m>=14:
            opening_hi=max(bars[k][1] for k in range(15))
            opening_lo=min(bars[k][2] for k in range(15))
            opening_complete=True
        # The daily scanner reserves overlapping *opportunities*, never
        # overlapping positions. Account policies enforce that separately.
        if m+2+hold>374 or (not daily and m<=last+hold+2) or len(rows)>=max_signals:
            continue
        cross="CALL" if old<=0<gap and price>top else "PUT" if old>=0>gap and price<bottom else None
        entry_type=None
        if learning_grid:
            side=("CALL" if gap>0 and price>top else "PUT" if gap<0 and price<bottom else None) if m in grid else None
        elif daily:
            # Every scheduled checkpoint, plus fresh confirmed crossovers.
            # No ranking using later bars or best-of-day hindsight.
            scheduled=(m+1)%scan_stride==0
            side=cross
            if scheduled and opening_complete and side is None:
                side="CALL" if gap>0 and price>top else "PUT" if gap<0 and price<bottom else None
            # Separate exploratory sideways regime: completed-bar rejection
            # inside CPR, small EMA separation, no ambiguous both-edge touch.
            if entry_mode=="regime_scan" and scheduled and opening_complete and side is None and bottom<price<top and top>bottom and abs(gap)/price*10000<=5:
                width=top-bottom
                low=min(bars[k][2] for k in range(m-frame+1,m+1))
                high=max(bars[k][1] for k in range(m-frame+1,m+1))
                bull=bottom<=prev_close<=top and low<=bottom and high<top and price>=bottom+.2*width and price>prev_close
                bear=bottom<=prev_close<=top and high>=top and low>bottom and price<=top-.2*width and price<prev_close
                if bull!=bear:
                    side="CALL" if bull else "PUT"
                    entry_type="sideways_cpr_rejection"
            if side is not None:
                bar_lo=min(bars[k][2] for k in range(m-frame+1,m+1))
                bar_hi=max(bars[k][1] for k in range(m-frame+1,m+1))
                if entry_type=="sideways_cpr_rejection":
                    pass
                elif side==cross:
                    entry_type="crossover"
                elif (side=="CALL" and prev_close<=hi<price) or (side=="PUT" and price<lo<=prev_close):
                    entry_type="previous_day_breakout"
                elif (side=="CALL" and prev_close>top and bar_lo<=top<price) or (side=="PUT" and prev_close<bottom and price<bottom<=bar_hi):
                    entry_type="cpr_retest"
                elif (side=="CALL" and prev_close<=top<price) or (side=="PUT" and price<bottom<=prev_close):
                    entry_type="cpr_breakout"
                elif m>=15+frame-1 and ((side=="CALL" and prev_close<=opening_hi<price) or (side=="PUT" and price<opening_lo<=prev_close)):
                    entry_type="opening_range_breakout"
                else:
                    entry_type="trend_continuation"
        else:
            side=cross
        if side is None:
            continue
        # Continuous EMA warmup uses only prior completed bars. The crossover
        # plus CPR side is one explicit hypothesis, not a claim about manual rules.
        scale=10000/price
        direction=1 if side=="CALL" else -1
        x=[direction*(price-z)*scale for z in (op,hi,lo,close,pivot,bottom,top)]
        x += [(top-bottom)*scale, direction*gap*scale, m/375.,float(side==cross)]
        rows.append({"session":day,"prior_session":prev_day,"minute":m,
                     "side":side,"spot":price,"features":x,
                     "entry_type":entry_type or ("crossover" if side==cross else "scheduled_continuation"),
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


def _candidate_pool(signal,table,*,lot_size,max_lots,bps):
    day,m,side,spot=(signal[k] for k in ("session","minute","side","spot"))
    quotes=table.get(_stamp(day,m),{})
    candidates=[]
    observed=0
    for (s,k),row in quotes.items():
        if s!=side or not _observed(table,day,m,s,k):
            continue
        observed+=1
        if abs(k/spot-1)>.015 or row["close"]<5:
            continue
        for lots in range(1,max_lots+1):
            units=lots*lot_size
            funding=_fund(row["close"],units,bps)
            candidates.append((abs(k-spot),lots,k,units,funding,row["close"]))
    return sorted(candidates),{"observed_side_quotes":observed,
        "qualified_contracts":len({x[2] for x in candidates}),
        "minimum_funding_inr":min((x[4] for x in candidates),default=None)}


def _episode(signal,table,index,*,hold,lot_size,max_lots,risk_budget,bps,
             candidate=None,learning=False):
    day,m,side,spot=(signal[k] for k in ("session","minute","side","spot"))
    if candidate is None:
        pool,diagnostics=_candidate_pool(signal,table,lot_size=lot_size,max_lots=max_lots,bps=bps)
        allowed=[v for v in pool if v[4]<=risk_budget]
        if not allowed:
            state=("missing_signal_quotes" if not diagnostics["observed_side_quotes"]
                   else "no_qualified_observed_contract" if not pool
                   else "no_affordable_observed_contract")
            return {**signal,"state":state,**diagnostics}
        candidate=allowed[0]
    else:
        diagnostics={}
    _,lots,strike,units,planned,signal_premium=candidate
    ep={**signal,**diagnostics,"strike":strike,"lots":lots,"units":units,"planned_funding":planned,
        "features":signal["features"]+[(strike/spot-1)*10000,signal_premium/spot*10000,
                                      planned/FEATURE_FUNDING_SCALE],
        "state":"missing_entry","path":[]}
    first=m+2
    entry=_observed(table,day,first,side,strike)
    if entry is None:
        return ep
    funding=_fund(entry["open"],units,bps)
    if not learning and funding>risk_budget:
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
        if bar is None or spot_bar is None:
            ep["path_gap_minute"]=j
            break
        mark,_=_net(ep["entry"],bar["close"],units,bps)
        # The availability of a counterfactual exit does not decide whether
        # HOLD is possible. Censor only if a chosen exit lacks evidence.
        net,charges=_net(ep["entry"],future["open"],units,bps) if future is not None else (None,None)
        r=mark/debit
        peak=r if peak is None else max(peak,r)
        trend=(1 if side=="CALL" else -1)*(spot_bar[3]/spot-1)
        ep["path"].append({"minute":j,"elapsed":j-first+1,"mark_return":r,
                           "drawdown":peak-r,"trend":trend,
                           "exit_net":net,"exit_fees":charges,
                           "exit_utc":_stamp(day,j+2),"terminal":j==first+hold-2})
    return ep


def _learning_episodes(signals,table,index,*,hold,lot_size,bps):
    episodes=[]
    for s in signals:
        pool,_=_candidate_pool(s,table,lot_size=lot_size,max_lots=1,bps=bps)
        for candidate in pool[:MAX_LEARNING_STRIKES]:
            episodes.append(_episode(s,table,index[s["session"]],hold=hold,lot_size=lot_size,
                max_lots=1,risk_budget=FEATURE_FUNDING_SCALE,bps=bps,candidate=candidate,learning=True))
    return episodes


def _full_path(ep):
    return bool(ep.get("path")) and ep["path"][-1]["terminal"] and all(
        s["exit_net"] is not None for s in ep["path"])


def _key(step):
    r=step["mark_return"]
    pnl=sum(r>=b for b in (-.15,-.10,-.05,-.02,0.,.03,.06,.10))
    elapsed=sum(step["elapsed"]>=b for b in (5,15,30,60))
    return (pnl,elapsed,int(step["trend"]>=0),int(step["drawdown"]>=.03))


def _forced(step, *, stop, stop_mark=STOP):
    if step["mark_return"]>=TARGET:
        return "target"
    if stop and step["mark_return"]<=stop_mark:
        return "stop"
    if step["terminal"]:
        return "timeout"
    return None


def _exit(ep, policy, q=None, *, stop_mark=STOP):
    if ep["state"]!="entered":
        return {"state":ep["state"]}
    low=high=None
    drawdown=0.
    floor=None
    observed_marks=[]
    diagnostics={"min_observed_mark_return":None,"max_observed_mark_return":None,
                 "max_observed_peak_to_mark_drawdown":None,"trailing_floor_return":None}
    for step in ep["path"]:
        mark=step["mark_return"]
        low=mark if low is None else min(low,mark)
        high=mark if high is None else max(high,mark)
        drawdown=max(drawdown,high-mark)
        observed_marks.append(mark)
        if policy in ("trailing","volatility_trailing") and high>=TRAIL_ACTIVATION-1e-12:
            gap=TRAIL_GAP
            if policy=="volatility_trailing" and len(observed_marks)>=6:
                from statistics import pstdev
                recent=observed_marks[-6:]
                gap=min(.06,max(.02,2*pstdev([b-a for a,b in zip(recent,recent[1:])])))
            candidate=max(stop_mark,high-gap)
            floor=candidate if floor is None else max(floor,candidate)
        diagnostics={"min_observed_mark_return":low,"max_observed_mark_return":high,
                     "max_observed_peak_to_mark_drawdown":drawdown,
                     "trailing_floor_return":floor}
        reason=_forced(step,stop=policy!="no_stop",stop_mark=stop_mark)
        if reason is None and floor is not None and mark<=floor+1e-12:
            reason="trailing_stop"
        if reason is None and policy=="offline_q":
            values=(q or {}).get(_key(step))
            # Unknown or tied states use the fixed target/stop baseline.
            if values is not None and values[0]>values[1]:
                reason="learned_exit"
        if reason:
            if step["exit_net"] is None:
                return {"state":"exit_censored","reason":"missing_chosen_exit","trigger":reason,**diagnostics}
            return {"state":"complete","reason":reason,"net":step["exit_net"],
                    "fees":step["exit_fees"],"exit_utc":step["exit_utc"],
                    "net_return":step["exit_net"]/ep["debit"],
                    "target_realized":step["exit_net"]/ep["debit"]>=TARGET,**diagnostics}
    return {"state":"exit_censored",**diagnostics}


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


def _fit_q(episodes, *, sweeps=20, stop_mark=STOP):
    """Batch fitted tabular Q iteration on earlier, fully observed paths.

    Reward is terminal net return. Hold reward is zero. Finite horizon and
    compulsory exits are outside the learned action set. Each observed path
    supplies counterfactual hold/exit marks under the same price proxy.
    """
    transitions=defaultdict(list)
    for ep in episodes:
        if ep["state"]!="entered" or not _full_path(ep):
            continue
        # Value of following the fixed rule from each next state, used when
        # the learned state has insufficient support.
        fallback={}
        continuation=ep["path"][-1]["exit_net"]/ep["debit"]
        for j in range(len(ep["path"])-1,-1,-1):
            s=ep["path"][j]
            if _forced(s,stop=True,stop_mark=stop_mark):
                continuation=s["exit_net"]/ep["debit"]
            fallback[j]=continuation
        for i,step in enumerate(ep["path"][:-1]):
            if _forced(step,stop=True,stop_mark=stop_mark):
                break
            nxt=ep["path"][i+1]
            transitions[_key(step)].append((ep["session"],ep["minute"],ep.get("strike"),
                step["exit_net"]/ep["debit"],_key(nxt),
                fallback[i+1],bool(_forced(nxt,stop=True,stop_mark=stop_mark))))
    supported={k:v for k,v in transitions.items()
               if len({(x[0],x[1]) for x in v})>=MIN_STATE_EPISODES
               and len({x[0] for x in v})>=MIN_STATE_DAYS}
    q={k:(0.,0.) for k in supported}
    for _ in range(sweeps):
        new={}
        for k,rows in supported.items():
            # Average within each episode first, so long paths cannot dominate.
            per_episode=defaultdict(list)
            for day,minute,strike,exit_r,nk,next_r,terminal in rows:
                continuation=next_r if terminal or nk not in q else max(q[nk])
                per_episode[(day,minute,strike)].append((exit_r,continuation))
            by_anchor=defaultdict(list)
            for (day,minute,strike),v in per_episode.items():
                by_anchor[(day,minute)].append((sum(x[0] for x in v)/len(v),sum(x[1] for x in v)/len(v)))
            averages=[(sum(x[0] for x in v)/len(v),sum(x[1] for x in v)/len(v))
                      for v in by_anchor.values()]
            new[k]=(sum(x[0] for x in averages)/len(averages),
                    sum(x[1] for x in averages)/len(averages))
        q=new
    return q,{"supported_states":len(q),"observed_states":len(transitions),
              "training_transitions":sum(len(v) for v in transitions.values()),
              "sweeps":sweeps,"stop_mark":stop_mark,
              "supported_unique_anchors":len({(x[0],x[1]) for rows in supported.values() for x in rows})}


def _anchor_weights(rows):
    counts=Counter((e["session"],e["minute"]) for e,_ in rows)
    return [1./counts[(e["session"],e["minute"])] for e,_ in rows]


def _fit_ml(train,validation):
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    import numpy as np
    tr=_training_rows(train);va=_training_rows(validation)
    counts=Counter(_label(r) for _,r in tr)
    train_anchors={(e["session"],e["minute"]) for e,_ in tr}
    val_anchors={(e["session"],e["minute"]) for e,_ in va}
    class_anchors={c:len({(e["session"],e["minute"]) for e,r in tr if _label(r)==c}) for c in CLASSES}
    info={"training_labels":dict(counts),"validation_labels":dict(Counter(_label(r) for _,r in va)),
          "training_episodes":len(tr),"validation_episodes":len(va),"validation_brier":{},
          "training_anchors":len(train_anchors),"validation_anchors":len(val_anchors),
          "training_class_anchors":class_anchors,
          "training_days":len({e["session"] for e,_ in tr}),
          "validation_days":len({e["session"] for e,_ in va})}
    if (len(tr)<40 or len(train_anchors)<20 or info["training_days"]<15
            or min(class_anchors.values())<5
            or len(va)<10 or len(val_anchors)<10 or info["validation_days"]<5):
        return None,{},info
    X=[e["features"] for e,_ in tr];y=[_label(r) for _,r in tr]
    V=[e["features"] for e,_ in va]
    truth=np.asarray([[float(_label(r)==c) for c in CLASSES] for _,r in va])
    models={"logistic":make_pipeline(StandardScaler(),LogisticRegression(max_iter=500,random_state=42)),
            "random_forest":RandomForestClassifier(n_estimators=100,max_depth=4,min_samples_leaf=5,
                                                  random_state=42,n_jobs=1)}
    fitted={}
    weights=np.asarray(_anchor_weights(tr));vweights=np.asarray(_anchor_weights(va))
    for name,model in models.items():
        if name=="logistic":
            model.fit(X,y,standardscaler__sample_weight=weights,logisticregression__sample_weight=weights)
        else:
            model.fit(X,y,sample_weight=weights)
        prob=model.predict_proba(V)
        ordered=prob[:,[list(model.classes_).index(c) for c in CLASSES]]
        info["validation_brier"][name]=float(np.average(np.sum((ordered-truth)**2,axis=1),weights=vweights))
        fitted[name]=model
    selected=min(fitted,key=lambda n:(info["validation_brier"][n],n))
    info["selected"]=selected
    means={c:float(np.average([r["net_return"] for _,r in tr if _label(r)==c],
                              weights=[w for w,(_,r) in zip(weights,tr) if _label(r)==c])) for c in CLASSES}
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
    return float(pr["target"])>=getattr(model,"target_threshold",.50) and ev>0


def _evaluate(episodes,*,method,capital,risk_budget,model=None,means=None,q=None,dates=None,max_attempts=MAX_DAILY_ATTEMPTS,context_filter=None):
    balance=capital; peak=capital;dd=0.;gross_losses=0.;day=None;halted=False
    daily=defaultdict(lambda:{"conditional_net_inr":0.,"scored":0,"unresolved":0})
    counts=Counter();journal=[];net=0.;charges=0.;winners=0;targets=0
    exit_reasons=Counter();worst_mark=None;open_dd=None
    daily_coverage={d:{"opportunities":0,"affordable_observed_entries":0,"entry_attempts":0,
                        "entered_positions":0,"scored_trades":0,"states":{}} for d in (dates or [])}
    active_until=None;attempts=0
    for ep in sorted(episodes,key=lambda e:(e["session"],e["decision_utc"])):
        if day!=ep["session"]:
            day=ep["session"];gross_losses=0.;halted=False
            # Independent day accounts avoid carrying unobserved positions into
            # the next session. Aggregate net is not a compounded account path.
            balance=capital;peak=capital;active_until=None;attempts=0
        coverage=daily_coverage.setdefault(day,{"opportunities":0,"affordable_observed_entries":0,
            "entry_attempts":0,"entered_positions":0,"scored_trades":0,"states":{}})
        coverage["opportunities"]+=1
        coverage["affordable_observed_entries"]+=int(ep["state"]=="entered")
        state=None
        if method=="no_trade":
            state="no_trade"
        elif halted:
            state="session_halted"
        elif active_until is not None and ep["decision_utc"]<=active_until:
            state="position_still_open"
        elif attempts>=max_attempts:
            state="daily_attempt_limit"
        elif ep["state"] in SOURCE_STATES:
            state=ep["state"]
        elif ep["planned_funding"]>min(balance,risk_budget-gross_losses):
            state="remaining_budget_gate"
        elif context_filter is not None and not context_filter(ep):
            state="context_abstain"
        elif method.startswith("ml_") and not _ml_accept(model,means,ep):
            state="ml_abstain"
        if state:
            result={"state":state}
        else:
            attempts+=1
            coverage["entry_attempts"]+=1
            if ep["state"]=="entered" and ep["funding"]>min(balance,risk_budget-gross_losses):
                result={"state":"entry_limit_exceeded"}
            else:
                learned=method in ("offline_q","ml_offline_q","offline_q_emergency_stop")
                wide=method in ("fixed_emergency_stop","offline_q_emergency_stop","trailing_emergency_stop")
                policy="offline_q" if learned else "volatility_trailing" if method=="volatility_trailing_stop" else "trailing" if method in ("trailing_stop","trailing_emergency_stop","ml_trailing_stop") else method if method=="no_stop" else "fixed_stop"
                result=_exit(ep,policy,q,stop_mark=EMERGENCY_STOP if wide else STOP)
        state=result["state"]
        counts[state]+=1
        coverage["states"][state]=coverage["states"].get(state,0)+1
        coverage["entered_positions"]+=int(state in ("complete","exit_censored"))
        if result.get("min_observed_mark_return") is not None:
            low=result["min_observed_mark_return"]
            dd_open=result["max_observed_peak_to_mark_drawdown"]
            worst_mark=low if worst_mark is None else min(worst_mark,low)
            open_dd=dd_open if open_dd is None else max(open_dd,dd_open)
        if state=="complete":
            exit_reasons[result["reason"]]+=1
            active_until=result["exit_utc"]
            coverage["scored_trades"]+=1
            value=result["net"];net+=value;charges+=result["fees"];balance+=value
            gross_losses+=max(0.,-value);peak=max(peak,balance);dd=max(dd,peak-balance)
            winners+=int(value>0);targets+=int(result["target_realized"])
            daily[day]["conditional_net_inr"]+=value;daily[day]["scored"]+=1
        elif state=="entry_limit_exceeded":
            active_until=ep.get("entry_utc",ep["decision_utc"])
        elif state in ("missing_entry","exit_censored"):
            halted=True
            daily[day]["unresolved"]+=1
        journal.append({"method":method,"session":day,"decision_utc":ep["decision_utc"],
                        "side":ep["side"],"entry_type":ep.get("entry_type"),"strike":ep.get("strike"),
                        "minimum_funding_inr":ep.get("minimum_funding_inr"),
                        "observed_side_quotes":ep.get("observed_side_quotes"),
                        "qualified_contracts":ep.get("qualified_contracts"),
                        "ranked_expected_return":ep.get("ranked_expected_return"),
                        "ranked_target_probability":ep.get("ranked_target_probability"),
                        "ranked_candidate_count":ep.get("ranked_candidate_count"),**result})
    scored=counts["complete"]
    unresolved=counts["missing_entry"]+counts["exit_censored"]
    return {"states":dict(counts),"signals":len(episodes),"scored_trades":scored,
            "profitable_trades":winners,"realized_target_hits":targets,
            "conditional_net_inr":round(net,2) if scored or method=="no_trade" else None,
            "conditional_fees_inr":round(charges,2),"max_within_day_closed_drawdown_inr":round(dd,2),
            "exit_reasons":dict(exit_reasons),"worst_observed_mark_return":worst_mark,
            "max_observed_peak_to_mark_drawdown":open_dd,
            "independent_daily_accounts":True,"daily":dict(daily),
            "daily_coverage":{"reserved_sessions":len(daily_coverage),
                "days_with_opportunity":sum(d["opportunities"]>0 for d in daily_coverage.values()),
                "days_with_affordable_candidate":sum(d["affordable_observed_entries"]>0 for d in daily_coverage.values()),
                "days_with_entry":sum(d["entered_positions"]>0 for d in daily_coverage.values()),
                "days_with_scored_trade":sum(d["scored_trades"]>0 for d in daily_coverage.values()),
                "days_without_entry":sum(d["entered_positions"]==0 for d in daily_coverage.values()),
                "by_session":daily_coverage},
            "unresolved_trades":unresolved,"full_account_pnl_certified":False},journal


def run(*,from_date,to_date,frame=5,hold=60,capital=17000.,risk_budget=4250.,
        lot_size=30,max_lots=1,wings=3,premium_penalty_bps=25.,entry_mode="crossover",
        context_mode="off",context_batch="auto",rank_entries=False,progress=None):
    start,stop=map(date.fromisoformat,(from_date,to_date))
    now=datetime.now(timezone.utc)
    if not alpha_retraining.safe_window(now):
        raise ValueError("Run CPR research outside Indian market priority hours")
    if not 0<(stop-start).days<=120 or stop>now.astimezone(h.IST).date():
        raise ValueError("Select up to 120 calendar days, completed sessions, end exclusive")
    if context_mode not in ("off","receipt","archive"):
        raise ValueError("Unsupported context availability mode")
    if entry_mode not in ENTRY_MODES:
        raise ValueError("Unsupported entry mode")
    if frame not in FRAMES or hold not in HOLDS or type(lot_size) is not int or not 1<=lot_size<=1000 or type(max_lots) is not int or not 1<=max_lots<=3 or type(wings) is not int or not 0<=wings<=5:
        raise ValueError("Unsupported timeframe, hold, historical lot assumption or wings")
    if not all(type(v) in (int,float) and isfinite(v) for v in (capital,risk_budget,premium_penalty_bps)) or not 1000<=capital<=1e7 or not 0<risk_budget<=capital or not 0<=premium_penalty_bps<=200:
        raise ValueError("Invalid research capital, premium exposure or cost assumption")
    if progress:progress(1,"Verifying original BANKNIFTY minute receipts")
    index,index_hashes,failures=h.shared_index_sources(start-timedelta(days=7),stop,[h.MAX_TOTAL])
    ordered=sorted(index)
    dates=[d for d in ordered if from_date<=d<to_date and date.fromisoformat(d).weekday()<5][-sum(SPLITS):]
    splits=[dates[:30],dates[30:40],dates[40:60]]
    signals=[];learning_grid=[];train_crossovers=[];counts=Counter();day_audit={}
    for day in dates:
        i=ordered.index(day)
        if not i:
            day_audit[day]={"state":"prior_session_missing","signals":0}
            continue
        prior=ordered[i-1]
        rows,status=_signals(day,index[day],prior,index[prior],frame=frame,hold=hold,
                             max_signals=375 if entry_mode!="crossover" else 3,entry_mode=entry_mode)
        signals.extend(rows)
        if day in splits[0]:
            extra,_=_signals(day,index[day],prior,index[prior],frame=frame,hold=hold,max_signals=5,learning_grid=True)
            learning_grid.extend(extra)
            base,_=_signals(day,index[day],prior,index[prior],frame=frame,hold=hold,max_signals=3)
            train_crossovers.extend(base)
            if entry_mode=="regime_scan":
                # Earlier regime candidates only, selected on signal type and
                # timestamp, not observed returns. Bounded one per hold window.
                last_rejection=-hold-3
                for s in rows:
                    if s["entry_type"]=="sideways_cpr_rejection" and s["minute"]>=last_rejection+hold+3:
                        train_crossovers.append(s);last_rejection=s["minute"]
        counts[status]+=1
        day_audit[day]={"state":status,"signals":len(rows),"prior_session":prior,
                        "entry_types":dict(Counter(s["entry_type"] for s in rows))}
    by_anchor={(s["session"],s["minute"]):s for s in learning_grid}
    # Prefer the original crossover if a scheduled anchor coincides.
    by_anchor.update({(s["session"],s["minute"]):s for s in train_crossovers})
    train_signals=sorted(by_anchor.values(),key=lambda s:(s["session"],s["minute"]))
    val_signals=[s for s in signals if s["session"] in splits[1]]
    all_signals=signals+train_signals
    from . import cpr_context_features as cx
    context_audit=cx.attach(all_signals,mode=context_mode,batch_id=context_batch)
    needed={_stamp(s["session"],m) for s in all_signals
            for m in range(s["minute"],s["minute"]+hold+3)}
    table,meta=p._load_options(all_signals,wings,progress,needed_stamps=needed)
    if progress:progress(52,"Constructing fixed-strike delayed execution trajectories")
    # Use adverse penalty for all primary training and evaluation, not ex-post
    # stress selection. Report explicit sensitivity as an additional study later.
    bps=premium_penalty_bps+10
    episodes=[_episode(s,table,index[s["session"]],hold=hold,lot_size=lot_size,max_lots=max_lots,
                       risk_budget=risk_budget,bps=bps) for s in signals]
    parts=[[e for e in episodes if e["session"] in set(ds)] for ds in splits]
    broad_train=_learning_episodes(train_signals,table,index,hold=hold,lot_size=lot_size,bps=bps)
    broad_val=_learning_episodes(val_signals,table,index,hold=hold,lot_size=lot_size,bps=bps)
    report={"version":VERSION,"settings":{"from_date":from_date,"to_exclusive":to_date,"timeframe":frame,
             "hold_minutes":hold,"entry_mode":entry_mode,"scan_interval_minutes":SCAN_MINUTES,
             "max_daily_entry_attempts":MAX_DAILY_ATTEMPTS,"capital_inr":capital,
             "context_mode":context_mode,"context_batch":context_batch,"rank_entries":rank_entries,"full_premium_and_fee_budget_inr":risk_budget,
             "historical_lot_size_assumed":lot_size,"max_lots":max_lots,"strike_wings":wings,
             "primary_adverse_penalty_bps_per_side":bps,"target_net_return":TARGET,"fixed_stop_mark":STOP,
             "experimental_emergency_stop_mark":EMERGENCY_STOP,"max_learning_strikes_per_anchor":MAX_LEARNING_STRIKES,
             "trailing_activation_net_return":TRAIL_ACTIVATION,"trailing_gap_return_points":TRAIL_GAP,
             "volatility_trailing_gap_range":[.02,.06]},
             "recorded_index_sessions":len(dates),"required_sessions":sum(SPLITS),
             "training_dates":splits[0],"validation_dates":splits[1],"holdout_dates":splits[2],
             "signal_counts":dict(counts),"day_audit":day_audit,"episode_states":dict(Counter(e["state"] for e in episodes)),
             "split_support":{name:{"signals":len(rows),"entered":sum(e["state"]=="entered" for e in rows),
                          "fully_observed_paths":sum(_full_path(e) for e in rows),
                          "states":dict(Counter(e["state"] for e in rows))}
                          for name,rows in zip(("train","validation","holdout"),parts)},
             "learning_support":{name:{"reserved_anchors":len(ss),"candidate_paths":len(es),
                     "candidate_states":dict(Counter(e["state"] for e in es)),
                     "entered":sum(e["state"]=="entered" for e in es),
                     "fully_observed_paths":sum(_full_path(e) for e in es),
                     "signal_types":dict(Counter(s["entry_type"] for s in ss))}
                     for name,ss,es in (("train",train_signals,broad_train),("validation",val_signals,broad_val))},
             "index_source_failures":failures,"option_coverage":{k:v for k,v in meta.items() if k!="source_hashes"},
             "context_coverage":{k:v for k,v in context_audit.items() if k!="anchors"},
             "ranked_entry_research":{},
             "methods":{},"state":"descriptive_only_insufficient_sessions","broker_orders_enabled":False,
             "live_model_promoted":False,"warning":WARNING}
    journal=[]
    if len(dates)==sum(SPLITS):
        train,val,test=parts
        if progress:progress(65,"Fitting train-only ML and offline Q values; validation chooses ML")
        model,means,ml_info=_fit_ml(broad_train,broad_val)
        q,q_info=_fit_q(broad_train)
        wide_q,wide_info=_fit_q(broad_train,stop_mark=EMERGENCY_STOP)
        report.update(state="chronological_holdout_assessment",ml=ml_info,offline_q=q_info,
                      offline_q_emergency_stop=wide_info,
                      wider_q_policy_sha256=sha256(json.dumps(sorted((list(k),list(v)) for k,v in wide_q.items()),separators=(",",":")).encode()).hexdigest(),
                      ml_holdout=_holdout_ml(model,test),
                      q_policy_sha256=sha256(json.dumps(sorted((list(k),list(v)) for k,v in q.items()),
                                                         separators=(",",":")).encode()).hexdigest())
        for method in METHODS:
            if (method.startswith("ml_") and model is None) or (method.endswith("offline_q") and not q) or (method=="offline_q_emergency_stop" and not wide_q):
                report["methods"][method]={"state":"insufficient_training_support"}
                continue
            metrics,rows=_evaluate(test,method=method,capital=capital,risk_budget=risk_budget,
                                   model=model,means=means,q=wide_q if method=="offline_q_emergency_stop" else q,dates=splits[2])
            report["methods"][method]=metrics;journal.extend(rows)
        if rank_entries or context_mode!="off":
            from . import cpr_ranked_entries as ranked
            ranked_results,ranked_rows=ranked.assess(
                __import__(__name__,fromlist=["run"]),signals=signals,table=table,index=index,
                train=broad_train,val=broad_val,test=test,dates=(splits[1],splits[2]),
                hold=hold,lot_size=lot_size,bps=bps,capital=capital,risk_budget=risk_budget,
                context_audit=context_audit,q=q,progress=progress)
            report["ranked_entry_research"]=ranked_results
            journal.extend(ranked_rows)
    else:
        # Always useful mathematical diagnostic; never labeled independent holdout.
        for method in ("no_stop","fixed_stop","fixed_emergency_stop","trailing_stop","trailing_emergency_stop","volatility_trailing_stop","no_trade"):
            metrics,rows=_evaluate(episodes,method=method,capital=capital,risk_budget=risk_budget,dates=dates)
            report["methods"][method]=metrics;journal.extend(rows)
    evidence={"index_sources":index_hashes,"option_sources":meta["source_hashes"],
              "context_evidence":context_audit}
    report["source_sha256"]=sha256(json.dumps(evidence,sort_keys=True).encode()).hexdigest()
    if progress:progress(100,"CPR strategy comparison complete")
    return report,journal,evidence
