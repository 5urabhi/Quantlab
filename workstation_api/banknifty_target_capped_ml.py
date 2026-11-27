"""BANKNIFTY target-capped scenario comparison with optional supervised correction.

Only historical BANKNIFTY option paths supply option labels. Earlier shared
stock daily closes provide optional market-regime inputs, never option labels.
All policy comparisons are exploratory; no broker requests or orders.
"""
from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
from math import isfinite, log, log1p
import json
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from . import banknifty_math_target as math_target, cpr_hybrid_research as r
from . import historical_alpha as h, predictive_option_research as p
from . import cpr_execution_evidence as evidence, shared_market_data as shared
from .cpr_direct_utility import _timely

VERSION="banknifty_target_capped_ml_v1"
HOLDS=(30,60)
POLICIES=("raw","capped","capped_liquid","ml","ml_daily")
COST=math_target.ORDER_COST_INR
TARGET=math_target.TARGET
WARMUP=20
MIN_ML_ROWS=80
MIN_ML_DAYS=10
MIN_CLASS=10
MAX_DAILY_BYTES=256*1024*1024
FEATURES=("scenario_target_probability","scenario_capped_return","scenario_stop_probability",
          "scenario_expected_return","scenario_count","iv_proxy","signed_moneyness",
          "premium","units","days_to_nominal_expiry","decision_minute","median_volume",
          "one_minute_rms","signed_spot_momentum","signed_spot_forecast_points")
DAILY_FEATURES=("prior_market_median_return","prior_up_fraction","prior_cross_section_mad",
                "prior_20_session_volatility","prior_volatility_historical_percentile")


def daily_context(dates):
    """Hash-verified shared equity view, never a reconstructed BANKNIFTY.
    Missing observations are not filled. Current-day closes are forbidden.
    """
    folder=shared.shared_folder()
    manifest=folder/"SHARED_MARKET_PROVENANCE.json"
    source=folder/"daily_prices.csv"
    meta={"state":"unavailable","feature_names":list(DAILY_FEATURES)}
    try:
        if manifest.is_symlink() or source.is_symlink() or not manifest.is_file() or not source.is_file():
            raise ValueError("Shared daily view or provenance absent")
        if manifest.stat().st_size>8*1024*1024 or source.stat().st_size>MAX_DAILY_BYTES:
            raise ValueError("Shared daily view exceeds bounded read budget")
        provenance=json.loads(manifest.read_text())
        payload=source.read_bytes()
        digest=sha256(payload).hexdigest()
        if digest!=provenance.get("daily_sha256"):raise ValueError("Shared daily hash mismatch; may be updating")
        columns=[x["column"] for x in provenance["columns"] if x["exchange_segment"]=="NSE_EQ"]
        if len(columns)<20 or len(set(columns))!=len(columns):
            raise ValueError("Insufficient or duplicate NSE equity identities")
        frame=pd.read_csv(BytesIO(payload),usecols=["date",*columns])
        clock=pd.to_datetime(frame.pop("date"),errors="raise")
        if clock.isna().any() or clock.duplicated().any() or not clock.is_monotonic_increasing:
            raise ValueError("Invalid daily session dates")
        frame.index=clock.dt.strftime("%Y-%m-%d")
        frame=frame.loc[frame.index<max(dates)]
        values=frame.apply(pd.to_numeric,errors="coerce")
        values=values.where(np.isfinite(values)&(values>0))
        # Use only adjacent published sessions with observed prices on both.
        # Clip extraordinary single-stock moves to reduce unadjusted split artifacts.
        ret=(values/values.shift(1)-1).clip(-.2,.2)
        counts=ret.notna().sum(axis=1)
        median=ret.median(axis=1).where(counts>=20)
        breadth=(ret.gt(0).sum(axis=1)/counts.where(counts>=20))
        mad=ret.sub(median,axis=0).abs().median(axis=1).where(counts>=20)
        vol=median.rolling(20,min_periods=20).std()
        context={};history=[];prior={}
        for day in values.index:
            v=vol.loc[day]
            if isfinite(v):
                if len(history)>=60:
                    vector=[median.loc[day],breadth.loc[day],mad.loc[day],v,float(np.mean(np.asarray(history)<=v))]
                    if all(isfinite(x) for x in vector):
                        prior[day]=[float(x) for x in vector]
                history.append(float(v))
        # Require the immediately preceding published day to have valid context.
        clocks=list(values.index)
        for day in dates:
            i=bisect_left(clocks,day)-1
            if i>=0 and clocks[i] in prior and 0<(date.fromisoformat(day)-date.fromisoformat(clocks[i])).days<=7:
                context[day]=prior[clocks[i]]
        meta.update(state="loaded" if context else "insufficient_prior_context",
                    sha256=digest,first_session=clocks[0] if clocks else None,last_session=clocks[-1] if clocks else None,
                    sessions=len(clocks),nse_equity_columns=len(columns),matched_days=len(context),
                    requested_days=len(dates),source_origins=provenance.get("source_origins",[]),
                    note="Available-observation broad NSE equity context, not PIT BANKNIFTY weights or certified adjusted returns. Historical coverage and survivorship limitations remain.")
        return context,meta
    except (OSError,ValueError,TypeError,KeyError,pd.errors.ParserError) as exc:
        meta["reason"]=str(exc)[:200]
        return {},meta


def candidate_features(c,index_day,m):
    state=math_target._state(index_day,m)
    if state is None:return None
    _,sigma,sign=state
    forecast=c["forecasts"][0];direction=1 if c["side"]=="CALL" else -1
    x=[forecast["realized_target_probability"],forecast["expected_target_capped_return"],
       forecast["stop_probability"],forecast["expected_net_return"],len(c["scenario_days"]),
       c["iv_proxy"],direction*log(c["spot"]/c["strike"]),c["premium"],c["units"],
       365*c["tau"],m,log1p(c.get("median_recent_volume",0.)),sigma,
       direction*log(index_day[m][3]/index_day[m-15][3]),direction*c["expected_terminal_move_points"]]
    return [float(v) for v in x] if all(isfinite(v) for v in x) else None


def make_episode(index,table,day,m,hold,c,lot_size,max_lots,budget):
    f=c["forecasts"][0]
    signal={"session":day,"minute":m,"side":c["side"],"spot":c["spot"],"features":[],
            "decision_utc":r._stamp(day,m+1),"entry_utc":r._stamp(day,m+2),
            "entry_type":"math_target_capped","ranked_expected_return":f["expected_net_return"],
            "ranked_target_probability":f["realized_target_probability"]}
    pick=(abs(c["strike"]-c["spot"]),c["lots"],c["strike"],c["units"],c["planned_funding"],c["premium"])
    return r._episode(signal,table,index[day],hold=hold,lot_size=lot_size,max_lots=max_lots,
                      risk_budget=budget,bps=0,candidate=pick,fixed_order_cost=COST)


def label(ep):
    """Target event includes realized execution; gap/late/missing is failure.
    Use funding-normalized capped stress outcome for the regression label.
    A limit-rejected entry incurs no simulated P&L and is not a target.
    """
    result=r._exit(ep,"fixed_stop")
    funding=ep["planned_funding"]
    good=_timely(result)
    if good:
        net=min(result["net"],TARGET*ep["debit"])
    elif result["state"]=="entry_limit_exceeded":
        net=0.
    else:
        net=min(result.get("net",0.),-funding)
    return int(good and result["target_realized"]),float(net/funding),bool(good)


def collect(index,table,days,train,hold,*,lot_size,max_lots,budget,rolling=False,progress=None):
    rows=[];counts=Counter()
    for i,day in enumerate(days):
        if progress:progress(f"{hold}m {'development' if rolling else 'assessment'} {i+1}/{len(days)} {day}")
        earlier=[d for d in train if d<day] if rolling else train
        if len(earlier)<WARMUP:continue
        for m in range(34,r.SQUAREOFF_MINUTE-hold-1,5):
            candidates,state=math_target.select(index,earlier,table,day,m,hold,lot_size=lot_size,
                                               max_lots=max_lots,budget=budget,comparison=True)
            counts[state]+=1
            if candidates is None:continue
            cache={};row={"day":day,"minute":m,"candidates":{}}
            for kind,c in candidates.items():
                key=(c["side"],c["strike"],c["units"])
                if key not in cache:cache[key]=make_episode(index,table,day,m,hold,c,lot_size,max_lots,budget)
                ep=cache[key]
                row["candidates"][kind]={"candidate":c,"episode":ep,"features":candidate_features(c,index[day],m)}
            rows.append(row)
    return rows,dict(counts)


def training_examples(rows,context):
    result=[]
    for row in rows:
        item=row["candidates"].get("liquid")
        if item is None or item["features"] is None:continue
        target,utility,timely=label(item["episode"])
        day=row["day"]
        result.append({"day":day,"x":item["features"],"daily":context.get(day),
                       "target":target,"utility":utility,"timely":timely})
    return result


def fit(examples,*,daily=False):
    """Small regularized supervised models, not a deep network.
    Day weighting prevents a high-signal day from dominating the fit.
    """
    rows=[e for e in examples if not daily or e["daily"] is not None]
    days=Counter(e["day"] for e in rows)
    positives=sum(e["target"] for e in rows)
    info={"rows":len(rows),"days":len(days),"positive_targets":positives,
          "negative_targets":len(rows)-positives,"state":"insufficient_support"}
    if len(rows)<MIN_ML_ROWS or len(days)<MIN_ML_DAYS or min(positives,len(rows)-positives)<MIN_CLASS:
        return None,info
    X=np.asarray([e["x"]+(e["daily"] if daily else []) for e in rows],float)
    y=np.asarray([e["target"] for e in rows],int)
    u=np.asarray([e["utility"] for e in rows],float)
    if not np.isfinite(X).all() or not np.isfinite(u).all():raise ValueError("Invalid earlier ML feature/label")
    weights=np.asarray([1/days[e["day"]] for e in rows],float);weights/=weights.mean()
    classifier=make_pipeline(StandardScaler(),LogisticRegression(C=.1,max_iter=500,random_state=0))
    regressor=make_pipeline(StandardScaler(),Ridge(alpha=20.))
    classifier.fit(X,y,logisticregression__sample_weight=weights)
    regressor.fit(X,u,ridge__sample_weight=weights)
    info["state"]="fitted"
    return (classifier,regressor),info


def predict(model,item,day,context,*,daily=False):
    if model is None or item["features"] is None or (daily and day not in context):return None
    x=[item["features"]+(context[day] if daily else [])]
    return float(model[0].predict_proba(x)[0,1]),float(model[1].predict(x)[0])


def capped_account(metrics,journal,episodes):
    """Accounting sensitivity only, not a standing limit-order fill model."""
    by_key={(e["session"],e["decision_utc"]):e for e in episodes}
    daily=defaultdict(float);capped_net=0.;capped_stress=0.;removed=0.
    for t in journal:
        day=t["session"];ep=by_key[(day,t["decision_utc"])]
        state=t["state"]
        if state=="complete":
            cap=min(t["net"],TARGET*ep["debit"])
            removed+=t["net"]-cap;capped_net+=cap
            stress=cap if _timely(t) else min(t["net"],-ep["planned_funding"])
        elif state in ("missing_entry","exit_censored"):
            stress=-ep["planned_funding"]
        else:
            stress=0.
        daily[day]+=stress;capped_stress+=stress
    return {"target_capped_net_inr":round(capped_net,2) if metrics["scored_trades"] else None,
            "target_capped_stress_inr":round(capped_stress,2),
            "profit_above_target_inr":round(removed,2),
            "capped_stress_without_best_day_inr":round(capped_stress-max([0.,*daily.values()]),2),
            "capped_stress_by_day_inr":{d:round(v,2) for d,v in sorted(daily.items())}}


def evaluate(rows,dates,policy,models,context,*,capital,budget):
    episodes=[];counts=Counter();scores=[]
    if policy.startswith("ml") and models.get(policy) is None:
        return {"state":"unavailable_ml_support","qualified":False}
    for row in rows:
        day=row["day"]
        kind="raw" if policy=="raw" else "capped" if policy=="capped" else "liquid"
        item=row["candidates"].get(kind)
        if item is None:
            counts["no_candidate"]+=1;continue
        forecast=item["candidate"]["forecasts"][0]
        ep=item["episode"]
        if policy.startswith("ml"):
            pred=predict(models[policy],item,day,context,daily=policy=="ml_daily")
            if pred is None:
                counts["missing_context"]+=1;continue
            target,_,_=label(ep)
            scores.append((day,target,forecast["realized_target_probability"],pred[0]))
            if pred[0]<math_target.PROB_FLOOR or pred[1]<=0:
                counts["ml_abstain"]+=1;continue
            ep={**ep,"ranked_target_probability":pred[0],"ranked_expected_return":pred[1]}
        elif policy!="raw" and forecast["expected_target_capped_return"]<=0:
            counts["nonpositive_capped_scenario"]+=1;continue
        episodes.append(ep);counts["accepted"]+=1
    metrics,journal=r._evaluate(episodes,method="fixed_stop",capital=capital,risk_budget=budget,
                                dates=dates,strict_execution=True)
    metrics.update(capped_account(metrics,journal,episodes))
    calibration={}
    if scores:
        per_day=defaultdict(list)
        for day,target,raw,ml in scores:
            per_day[day].append(((raw-target)**2,(ml-target)**2,target,raw,ml))
        day_means=np.asarray([np.mean(v,axis=0) for v in per_day.values()])
        calibration={"candidate_rows":len(scores),"days":len(per_day),"day_weighted_raw_brier":float(day_means[:,0].mean()),
                     "day_weighted_ml_brier":float(day_means[:,1].mean()),"observed_target_rate":float(day_means[:,2].mean()),
                     "raw_target_probability":float(day_means[:,3].mean()),"ml_target_probability":float(day_means[:,4].mean())}
    # Stress gate remains separate from actual conditional P&L. Do not
    # select a strategy whose capped profit depends on one best session.
    passed=(metrics["scored_trades"]>=math_target.MIN_VALID_TRADES
            and metrics["daily_coverage"]["days_with_scored_trade"]>=math_target.MIN_VALID_DAYS
            and (metrics["conditional_net_inr"] or 0)>0
            and (metrics["target_capped_net_inr"] or 0)>0
            and metrics["target_capped_stress_inr"]>0
            and metrics["capped_stress_without_best_day_inr"]>0)
    return {"state":"assessed","qualified":bool(passed),"counts":dict(counts),"metrics":metrics,
            "candidate_calibration":calibration,"journal":journal}


def run(*,sessions=90,to_date=None,capital=17000.,budget=12000.,lot_size=30,max_lots=3,wings=10,progress=None):
    today=datetime.now(timezone.utc).astimezone(h.IST).date()
    stop=date.fromisoformat(to_date) if to_date else today
    if sessions not in (90,120) or stop>today or not 0<budget<=capital<=1e7 or capital<1000 or not 1<=lot_size<=1000 or not 1<=max_lots<=3 or not 0<=wings<=10:
        raise ValueError("Invalid date, capital, lot, or wings assumption")
    start=stop-timedelta(days={90:150,120:200}[sessions])
    if progress:progress("Verifying original BANKNIFTY spot receipts")
    index,hashes,failures=h.shared_index_sources(start,stop,[h.MAX_TOTAL])
    dates=[d for d in sorted(index) if start.isoformat()<=d<stop.isoformat() and date.fromisoformat(d).weekday()<5][-sessions:]
    if len(dates)!=sessions:raise ValueError("Insufficient saved BANKNIFTY sessions")
    ntrain,nval,_=r.SESSION_SPLITS[sessions]
    train,val,test=dates[:ntrain],dates[ntrain:ntrain+nval],dates[ntrain+nval:]
    context,context_meta=daily_context(dates)
    if progress:progress("Daily stock context: "+json.dumps(context_meta))
    needed=train[WARMUP:]+val+test
    clocks={r._stamp(d,m) for d in needed for m in range(375)}
    coverage={}
    if progress:progress("Verifying saved option receipts, no downloads")
    table,meta=p._load_options([{"session":d} for d in needed],wings,needed_stamps=clocks,
                               evidence=coverage,evidence_days=needed)
    if not table:raise ValueError("No usable saved BANKNIFTY option candles")
    out={"version":VERSION,"capital_inr":capital,"budget_inr":budget,"lot_size_assumed":lot_size,
         "max_lots":max_lots,"wings":wings,"order_cost_inr":COST,"target":TARGET,"stop":math_target.STOP,
         "training_dates":train,"validation_dates":val,"evaluation_dates":test,
         "index_sources":hashes,"index_failures":failures,"option_sources":meta,
         "option_window_states":dict(Counter(evidence.window_status(coverage,d,s,today)["state"] for d in needed for s in ("CALL","PUT"))),
         "daily_context":context_meta,"ml_features":list(FEATURES),"development":{},"validation":{},
         "selected":None,"evaluation":None,
         "warning":"Exploratory only; previously inspected dates are not fresh confirmation. Target-capped accounting is a sensitivity analysis, not verified limit fills. Same original rolling strike/side OHLC and nominal expiry proxy, constant IV scenarios, assumed lot, no historical bid/ask, INR 30 all-in/order; actual fills and charges unverified. Ten prior observed option bars and median traded volume >= units are liquidity proxies, not executable depth. Labels use earlier actual premium outcomes and full planned funding stress on missing/late exits, not stock-return labels. Candidate examples can overlap; day weighting does not make them independent. Daily closes are unadjusted available-observation broad equity context, not five years of certified option labels or historical membership. No orders, no ML auto-promotion, no compounding."}
    model_by_hold={}
    opts=dict(lot_size=lot_size,max_lots=max_lots,budget=budget,progress=progress)
    for hold in HOLDS:
        rows,counts=collect(index,table,train[WARMUP:],train,hold,rolling=True,**opts)
        examples=training_examples(rows,context)
        # When stock context has adequate support, fit both ML lanes on the
        # exact same earlier matched candidate set for a fair ablation.
        daily_model,daily_info=fit(examples,daily=True)
        matched=[e for e in examples if e["daily"] is not None]
        base_model,base_info=fit(matched if daily_model is not None else examples)
        models={"ml":base_model,"ml_daily":daily_model}
        model_by_hold[hold]=models
        out["development"][str(hold)]={"counts":counts,"ml":base_info,"ml_daily":daily_info,
                                       "matched_training":daily_model is not None}
        if progress:progress(f"ML support {hold}m "+json.dumps(out["development"][str(hold)]))
        del rows,examples,matched
        rows,counts=collect(index,table,val,train,hold,**opts)
        results={}
        for policy in POLICIES:
            # If daily lane exists, restrict the base ML lane to the same
            # context-available anchors. The mathematical lanes remain full.
            lane_rows=[row for row in rows if row["day"] in context] if policy=="ml" and daily_model is not None else rows
            result=evaluate(lane_rows,val,policy,models,context,capital=capital,budget=budget)
            results[policy]=result
            if progress:
                m=result.get("metrics",{})
                progress(f"VALIDATION {hold}m {policy} "+json.dumps({k:m.get(k) for k in
                    ("scored_trades","profitable_trades","realized_target_hits","conditional_net_inr","target_capped_net_inr",
                     "target_capped_stress_inr","capped_stress_without_best_day_inr","stress_failed_attempts")})+
                    " QUALIFIED "+str(result["qualified"]))
        out["validation"][str(hold)]={"counts":counts,"policies":results}
        del rows
    qualified=[(hold,policy,item) for hold in HOLDS for policy,item in out["validation"][str(hold)]["policies"].items() if item["qualified"]]
    if not qualified:
        out["state"]="no_robust_validation_policy";return out
    hold,policy,_=max(qualified,key=lambda x:(x[2]["metrics"]["target_capped_stress_inr"],-x[0],-POLICIES.index(x[1])))
    out["selected"]={"hold":hold,"policy":policy}
    rows,counts=collect(index,table,test,train,hold,**opts)
    if policy=="ml" and model_by_hold[hold]["ml_daily"] is not None:rows=[row for row in rows if row["day"] in context]
    out["evaluation"]={"counts":counts,"result":evaluate(rows,test,policy,model_by_hold[hold],context,capital=capital,budget=budget)}
    out["state"]="exploratory_evaluation_complete"
    return out
