"""Research-only forecast selection and exact original book replay."""
from collections import Counter
from contextlib import closing
from datetime import timedelta
from hashlib import sha256
import json
import math
import numpy as np

from . import constituent_alpha as a, auto_paper_selection as s, auto_paper_engine as engine
from . import depth_replay as replay, paper_execution as paper

VERSION="forecast_depth_research_v1"
HORIZONS=(5,10,15,30,60)
IV_SHOCKS=(-.02,0.,.02)
MAX_POOL=6
QUANTILES=(.2,.5,.8)
POLICY={"version":VERSION,"horizons":HORIZONS,"class_quantiles":QUANTILES,"iv_shocks":IV_SHOCKS,
        "source":"original prospective decision ledger and source-qualified exact original depth",
        "selection":"worst IV stress expected net positive and profit probability >= .55",
        "execution":"fixed first receipts, verified lot sizes, existing paper entry/exit engine; target clock exit",
        "margin":"modeled funding proxy only; credit verticals optional research"}
POLICY_HASH=sha256(json.dumps(POLICY,sort_keys=True).encode()).hexdigest()

def _moves(train):
    return {c:[float(v) for v in np.quantile([r["return_bps"] for r in train if r["class"]==c],QUANTILES)]
            for c in a.CLASSES}

def _structures(books,spot,credit):
    for book in books:
        if .15<=abs(book["greeks"]["delta"])<=.85:
            yield "LONG_OPTION",[book]
    for side in ("CE","PE"):
        pool=sorted([b for b in books if b["option_type"]==side],
            key=lambda b:(b["spread_bps"],abs(b["strike"]-spot),b["identity"]))[:MAX_POOL]
        for b in pool:
            for c in pool:
                if b["strike"]>=c["strike"] or b["lot_size"]!=c["lot_size"] or b["expiry"]!=c["expiry"]:
                    continue
                if side=="CE":
                    yield "bull_call_debit",[b,c]
                    if credit:yield "bear_call_credit",[c,b]
                else:
                    yield "bear_put_debit",[c,b]
                    if credit:yield "bull_put_credit",[b,c]

def _choose(report,books,probs,moves,cfg,budget,credit):
    rejects=Counter();best=None
    if report["spot"]<=0 or not 0<budget:
        return None,{"budget_exhausted":1}
    weights=np.repeat(np.asarray(probs)/len(QUANTILES),len(QUANTILES))
    points=[report["spot"]*v/10000 for c in a.CLASSES for v in moves[c]]
    for strategy,legs in _structures(books,report["spot"],credit):
        if (max(b["stamp"] for b in legs)-min(b["stamp"] for b in legs)).total_seconds()>s.MAX_SKEW:
            rejects["leg_skew"]+=1;continue
        if strategy!="LONG_OPTION":
            try:replay.studio._validate_structure(strategy,legs)
            except ValueError:rejects["invalid_structure"]+=1;continue
        for lots in range(1,cfg["max_lots"]+1):
            units=lots*legs[0]["lot_size"]
            entries=s.executions(legs,strategy,lots,cfg["broker_profile"],slippage_bps=cfg["slippage_bps"])
            close=s.executions(legs,strategy,lots,cfg["broker_profile"],reverse=True,slippage_bps=cfg["slippage_bps"])
            if entries is None or close is None:
                rejects["insufficient_original_depth"]+=1;continue
            cash,loss,risk=replay._entry_risk(strategy,legs,s.actions(strategy),entries,units)
            risk=max(risk,loss+sum(x["fees"] for x in close))
            if not 0<risk<=budget or (strategy.endswith("debit") and cash>=0) or (strategy.endswith("credit") and cash<=0):
                rejects["risk_or_structure"]+=1;continue
            means=[];chances=[]
            for shock in IV_SHOCKS:
                values=[s._scenario_exit(legs,strategy,units,report["spot"],point,shock,cfg["hold_seconds"],
                        cfg["broker_profile"],cfg["slippage_bps"]) for point in points]
                if any(v is None for v in values):
                    break
                pnl=np.asarray(values)+cash
                means.append(float(np.dot(weights,pnl)))
                chances.append(float(weights[pnl>0].sum()))
            if len(means)!=3 or min(means)<=0 or min(chances)<.55:
                rejects["forecast_net_or_support_gate"]+=1;continue
            rank=(min(means),means[1],-risk)
            if best is None or rank>best[0]:
                best=(rank,{"strategy":strategy,"identities":[b["identity"] for b in legs],"lots":lots,
                    "units":units,"lot_size":legs[0]["lot_size"],"modeled_risk_inr":risk,
                    "stress_expected_net_inr":min(means),"expected_net_inr":means[1],
                    "stress_profit_probability":min(chances),"legs":[{"identity":b["identity"],"strike":b["strike"],
                    "side":b["option_type"],"expiry":b["expiry"],"book_sha256":b["digest"],
                    "book_utc":b["received_utc"]} for b in legs]})
    return (best[1] if best else None),dict(rejects)

def _execute(candidate,decision,target,cfg,budget,lookup):
    row={"selected":candidate,"config":cfg,"decision_utc":paper._iso(decision),
         "risk_budget_inr":budget,"state":"awaiting_entry"}
    def update(item,state,**values):
        item.update(values,state=state)
    engine._entry(row,decision+timedelta(milliseconds=s.LATENCY_MS,seconds=s.WINDOW_SECONDS),
                  update=update,first_book=lookup)
    if row["state"]=="paper_open":
        # No look at future prices to choose the exit clock.
        row["exit_decision_utc"]=paper._iso(target)
        engine._exit(row,target+timedelta(milliseconds=s.LATENCY_MS,seconds=s.WINDOW_SECONDS),
                     update=update,first_book=lookup)
    return row

def run(*,horizon=15,capital=17000.,max_loss=4250.,max_lots=3,slippage_bps=0.,
        include_credit=False,progress=None):
    if horizon not in HORIZONS or type(max_lots) is not int or not 1<=max_lots<=3 or type(include_credit) is not bool:
        raise ValueError("Invalid depth study scope")
    if not all(math.isfinite(v) for v in (capital,max_loss,slippage_bps)) or not 1000<=capital<=1e7 or not 0<max_loss<=capital or not 0<=slippage_bps<=100:
        raise ValueError("Invalid modeled funding or residual slippage")
    status=a.readiness(horizon);dates=status["training_dates"]+status["calibration_dates"]+status["holdout_dates"]
    counts=Counter();samples=[]
    if dates:
        with closing(a._read()) as db:
            for i,day in enumerate(dates):
                if progress:progress(2+30*i/max(1,len(dates)),"Auditing original prospective decisions: "+day)
                rows,c=a.sample_day(a._rows(db,day,horizon));samples.extend(rows);counts.update(c)
    train,cal,test=([r for r in samples if r["session"] in set(status[key])]
                    for key in ("training_dates","calibration_dates","holdout_dates"))
    out={"version":VERSION,"policy_sha256":POLICY_HASH,"horizon_minutes":horizon,
         "state":"insufficient_matched_evidence","recorded_sessions":len(dates),"required_sessions":status["required_sessions"],
         "capital_inr":capital,"session_loss_allowance_inr":max_loss,"credit_verticals_included":include_credit,
         "support":{"training":a.support(train),"calibration":a.support(cal),"holdout":a.support(test)},
         "evidence_counts":dict(counts),"methods":{},"run_id":None,"broker_orders_enabled":False,"live_model_promoted":False,
         "warning":"Conditional original-depth replay; not actual orders, broker margin or simultaneous basket fills. "
         "Training-class quantile scenarios are discrete approximations, with fixed ±2 percentage-point IV stresses, not a calibrated joint distribution. "
         "Model fitting is retrospective on original recorded features and later outcomes. Selection uses only books and chain known at the decision. "
         "Partial/unobserved entry or exit halts that session; conditional account results omit unresolved losses. No live promotion."}
    if len(dates)==status["required_sessions"] and a._supported(train,60,20,train=True) and a._supported(cal,20,7) and a._supported(test,40,12):
        from . import alpha_model_registry as registry
        moves=_moves(train);models=a.MODELS;predictions={};versions={}
        for name in models:
            fit=a._fit(name,train)
            temp=a._calibrate(a._predict(fit,cal),cal)
            predictions[name]=a._temperature(a._predict(fit,test),temp)
            if name.endswith("logistic"):
                try:
                    versions[name]={"state":"frozen","model_id":registry.freeze(name,fit,temp,train,cal,test,source="prospective",policy=a.policy_for(horizon),horizon=horizon,dates=[status[k] for k in ("training_dates","calibration_dates","holdout_dates")])}
                except (ValueError,OSError,TypeError):
                    versions[name]={"state":"registry_unavailable"}
        accounts={name:{"cash":capital,"day":None,"gross_losses":0.,"halt":False,"counts":Counter(),"pnl":[],"fees":0.} for name in models}
        cfg={"capital":capital,"max_loss":max_loss,"hold_seconds":60*horizon,"max_lots":max_lots,
             "broker_profile":"zerodha","slippage_bps":slippage_bps,"target_net":100.}
        records=[]
        with closing(a._read()) as db:
            def lookup(identity,ready,end,now):
                return replay._first_on_db(db,identity,ready,end,now)
            for i,r in enumerate(test):
                if progress:progress(35+64*i/max(1,len(test)),"Forecast selection and original-depth replay: "+r["session"])
                decision=a._stamp(r["decision_utc"]);target=a._stamp(r["target_utc"])
                source,books,reason=s._source(decision,cfg,historical=True,forecast_only=True)
                for name,account in accounts.items():
                    if account["day"]!=r["session"]:
                        account.update(day=r["session"],gross_losses=0.,halt=False)
                    budget=max(0.,min(capital,account["cash"],max_loss-account["gross_losses"]))
                    selected=None;details={};state="no_trade";net=None;charges=None
                    probs=predictions[name][i]
                    if account["halt"] or budget<=0:state="session_halted"
                    elif reason:state="source_unavailable";details={"source_reason":reason}
                    else:
                        selected,rejects=_choose(source,books,probs,moves,cfg,budget,include_credit)
                        details={"rejections":rejects}
                        if selected:
                            executed=_execute(selected,decision,target,cfg,budget,lookup)
                            state=executed["state"];net=executed.get("net_pnl_inr");charges=executed.get("fees_inr")
                            details["execution"]=executed
                            if state=="complete":
                                account["cash"]+=net;account["gross_losses"]+=max(0.,-net)
                                account["pnl"].append(net);account["fees"]+=charges
                            elif state in ("entry_rejected","entry_censored","exit_censored","awaiting_entry","paper_open"):
                                account["halt"]=True
                    account["counts"][state]+=1
                    records.append({"method":name,"session":r["session"],"decision_utc":r["decision_utc"],
                        "target_utc":r["target_utc"],"state":state,"probabilities_json":json.dumps([float(v) for v in probs]),
                        "source_json":json.dumps(source,sort_keys=True,allow_nan=False),
                        "selection_json":json.dumps(selected,sort_keys=True,allow_nan=False),
                        "details_json":json.dumps(details,sort_keys=True,allow_nan=False),
                        "net_pnl_inr":net,"fees_inr":charges,"conditional_balance_inr":account["cash"]})
        for name,account in accounts.items():
            out["methods"][name]={"states":dict(account["counts"]),"scored_trades":len(account["pnl"]),
                "eligible_windows":len(test),"conditional_net_inr":sum(account["pnl"]) if account["pnl"] else None,
                "conditional_fees_inr":account["fees"],"conditional_end_balance_inr":account["cash"],
                "full_account_pnl_certified":False}
        out["methods"]["no_trade"]={"states":{"no_trade":len(test)},"scored_trades":0,"eligible_windows":len(test),
            "conditional_net_inr":0.,"conditional_fees_inr":0.,"conditional_end_balance_inr":capital,"full_account_pnl_certified":False}
        out.update(state="conditional_depth_assessment_available",model_versions=versions,run_id=a._save(records))
    out["audit_id"]=a._save([{"day":"RUN_SUMMARY","evidence_json":json.dumps(out,sort_keys=True,allow_nan=False)}],audit=True)
    if progress:progress(100,"Forecast-depth evidence saved")
    return out
