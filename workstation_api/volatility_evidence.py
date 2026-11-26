"""Research-only volatility evidence; no automatic execution parameter changes."""
from collections import Counter, defaultdict
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import math
import numpy as np

from . import market_context as m, constituent_alpha as a, historical_alpha as h
from . import cockpit_sources, shared_market_data, replay_storage

VERSION="volatility_evidence_v1"
HORIZONS=(5,15,30,60)
IV_TRAIN=20
IV_TEST=10
QUANTILES=(.05,.1,.5,.9,.95)


def _range(start,stop):
    left,right=map(date.fromisoformat,(start,stop))
    if not 0<(right-left).days<=120 or right>datetime.now(h.IST).date():
        raise ValueError("Select up to 120 calendar days of completed sessions, end exclusive")
    return left,right


def _iv(c):
    v=c.get("iv")
    return float(v) if type(v) in (int,float) and math.isfinite(v) and 0<v<=500 else None


def _matched_iv(current,future):
    if not current or not future:
        return None
    before,before_hash=current;after,after_hash=future
    try:
        if before["expiry"]!=after["expiry"]:
            return None
        start,end=map(m._stamp,(before["received_utc"],after["received_utc"]))
        if end<=start or m.p._session(start).date()!=m.p._session(end).date():
            return None
        spot=m._finite(before["underlying_spot"])
        if spot<=0:
            return None
        initial=m._pairs(before,spot)
        final=m._pairs(after,spot)
        if len(initial)<5:
            return None
        strike=min(initial,key=lambda k:(abs(k-spot),k))
        if strike not in final:
            return None
        changes={}
        for side in ("CE","PE"):
            x,y=initial[strike][side],final[strike][side]
            if x["identity"]!=y["identity"] or x["lot_size"]!=y["lot_size"]:
                return None
            v0,v1=_iv(x),_iv(y)
            if v0 is None or v1 is None:
                return None
            changes[side]=v1-v0
        dte=(date.fromisoformat(before["expiry"])-m.p._session(start).date()).days
        if dte<0:
            return None
        return {"expiry":before["expiry"],"strike":strike,"spot":spot,
                "dte":dte,"entry_received_utc":before["received_utc"],"target_received_utc":after["received_utc"],
                "entry_sha256":before_hash,"target_sha256":after_hash,
                "ce_identity":initial[strike]["CE"]["identity"],"pe_identity":initial[strike]["PE"]["identity"],
                "elapsed_seconds":(end-start).total_seconds(),"ce_iv_change_pp":changes["CE"],
                "pe_iv_change_pp":changes["PE"],"atm_mean_iv_change_pp":(changes["CE"]+changes["PE"])/2}
    except (KeyError,ValueError,TypeError,OverflowError):
        return None


def _quantiles(rows,field):
    values=[r[field] for r in rows]
    return {"count":len(values),"quantiles_pp":{str(q):float(np.quantile(values,q)) for q in QUANTILES} if values else {},
            "mean_pp":float(np.mean(values)) if values else None,
            "absolute_p95_pp":float(np.quantile(np.abs(values),.95)) if values else None}


def _iv_report(rows,days):
    train=[r for r in rows if r["session"] in days[:IV_TRAIN]]
    test=[r for r in rows if r["session"] in days[IV_TRAIN:IV_TRAIN+IV_TEST]]
    fields=("ce_iv_change_pp","pe_iv_change_pp","atm_mean_iv_change_pp")
    supported=len(days)>=IV_TRAIN+IV_TEST and len(train)>=50 and len(test)>=20 and len({r["session"] for r in train})>=15 and len({r["session"] for r in test})>=7
    summary={}
    for field in fields:
        item={"descriptive_all":_quantiles(rows,field),"train":_quantiles(train,field),"test":_quantiles(test,field),
              "holdout_90pct_interval_coverage":None,"holdout_fixed_2pp_coverage":None}
        if supported:
            q=item["train"]["quantiles_pp"]
            item["holdout_90pct_interval_coverage"]=float(np.mean([q["0.05"]<=r[field]<=q["0.95"] for r in test]))
            item["holdout_fixed_2pp_coverage"]=float(np.mean([abs(r[field])<=2. for r in test]))
        summary[field]=item
    return {"state":"chronological_assessment_available" if supported else "descriptive_only_insufficient_sessions",
            "train_dates":days[:IV_TRAIN],"test_dates":days[IV_TRAIN:IV_TRAIN+IV_TEST],"metrics":summary}


def iv_run(*,from_date,to_date,horizon=15,progress=None):
    if horizon not in HORIZONS:
        raise ValueError("Select 5, 15, 30 or 60 minutes")
    left,right=_range(from_date,to_date)
    rows=[];counts=Counter();audit=[];days=[]
    if shared_market_data.database_path().is_file():
        with closing(a._read()) as db:
            if m._exists(db,"option_chain_observations"):
                days=[r[0] for r in replay_storage.fetchall(db,"""SELECT DISTINCT substr(captured_utc,1,10)
                    FROM option_chain_observations WHERE underlying='BANKNIFTY' AND captured_utc>=? AND captured_utc<?
                    ORDER BY 1""",(left.isoformat(),right.isoformat()))]
                days=[d for d in days if left<=date.fromisoformat(d)<right]
                for i,day in enumerate(days):
                    c=Counter()
                    if progress:progress(5+85*i/max(1,len(days)),"Auditing original IV receipts: "+day)
                    start=datetime.combine(date.fromisoformat(day),datetime.min.time(),h.IST)+timedelta(minutes=555)
                    # Non-overlapping windows; leave >90s between the next
                    # entry cutoff and preceding target cutoff.
                    for offset in range(2,375-horizon,horizon+2):
                        cutoff=(start+timedelta(minutes=offset)).astimezone(timezone.utc)
                        target=cutoff+timedelta(minutes=horizon)
                        c["reserved_windows"]+=1
                        before=m._chain(db,cutoff)
                        if not before:
                            c["missing_entry_chain"]+=1;continue
                        after=m._chain(db,target,expiry=before[0]["expiry"])
                        if not after:
                            c["missing_target_chain"]+=1;continue
                        paired=_matched_iv(before,after)
                        if not paired:
                            c["invalid_matched_iv"]+=1;continue
                        c["scored"]+=1
                        rows.append({"session":day,"cutoff_utc":m._iso(cutoff),"target_utc":m._iso(target),**paired})
                    counts.update(c);audit.append({"day":day,**c})
    result={"version":VERSION,"horizon_minutes":horizon,"from_date":from_date,"to_date":to_date,
            "recorded_sessions":len(days),"evidence_counts":dict(counts),"session_audit":audit,
            **_iv_report(rows,days),"run_id":a._save(rows) if rows else None,
            "warning":"IV changes are percentage points on identical original chain contract identities; nearest ATM is selected only at entry. "
            "Receipt timing and vendor IV are not executable quotes or independently computed volatility. "
            "All-sample quantiles are descriptive; only training quantiles are assessed on later sessions. "
            "No automatic replacement of the current paper IV stress or real orders."}
    summary={"day":"RUN_SUMMARY","counts_json":json.dumps(dict(counts),sort_keys=True),
             "evidence_json":json.dumps({k:v for k,v in result.items() if k!="session_audit"},sort_keys=True)}
    result["audit_id"]=a._save([summary]+[{"day":r["day"],"counts_json":json.dumps(r,sort_keys=True),"evidence_json":""} for r in audit],audit=True)
    if progress:progress(100,"Empirical IV evidence saved")
    return result


def _index_only(batch_id):
    raw,left,right,_,_=h._batch(batch_id)
    candidates=[(path,meta) for path,_,meta in cockpit_sources._candidates("INDEX:BANKNIFTY") if path.parent.name==batch_id]
    if len(candidates)!=1:
        raise ValueError("Original BANKNIFTY spot candles from the selected batch are required")
    path,meta=candidates[0]
    return h._read_file(path,meta["sha256"],left,right,[h.MAX_TOTAL],meta["row_count"]),meta["sha256"]


def _returns(index):
    # One-minute log returns, bps. Missing adjacent bars produce separate
    # segments, not cross-gap or overnight returns.
    out={}
    for k in sorted(index):
        if k-1 in index:
            out[k]=10000*math.log(index[k][3]/index[k-1][3])
    return out


def _rv_rows(days,index,horizon):
    rows=[];counts=Counter()
    for day in days:
        returns=_returns(index[day])
        for minute in range(30,375-horizon,horizon+1):
            counts["reserved_windows"]+=1
            if any(k not in returns for k in range(minute-29,minute+horizon+1)):
                counts["missing_adjacent_returns"]+=1;continue
            history=np.asarray([returns[k] for k in range(minute-29,minute+1)])
            future=np.asarray([returns[k] for k in range(minute+1,minute+horizon+1)])
            sq=history**2
            ewma=float(sq[0])
            for v in sq[1:]:
                ewma=.94*ewma+.06*v
            rows.append({"session":day,"minute":minute,"history":history,
                         "features":np.asarray([float(np.mean(sq[-n:])) for n in (5,15,30)]),
                         "ewma":ewma,"actual":float(np.mean(future**2))})
            counts["scored"]+=1
    return rows,dict(counts)


def _segments(index,days):
    out=[]
    for day in days:
        r=_returns(index[day]);segment=[];previous=None
        for k,v in sorted(r.items()):
            if previous is not None and k!=previous+1:
                if len(segment)>=30:out.append(np.asarray(segment))
                segment=[]
            segment.append(v);previous=k
        if len(segment)>=30:out.append(np.asarray(segment))
    return out


def _fit_garch(segments):
    from scipy.optimize import minimize
    if not segments:
        return None
    variance=max(1e-6,float(np.mean(np.concatenate(segments)**2)))
    # Constant mean zero, Gaussian quasi-likelihood; alpha+beta < 1.
    def unpack(z):
        w=math.exp(float(z[0]))*variance
        ea,eb=math.exp(float(z[1])),math.exp(float(z[2]))
        alpha,beta=.995*ea/(1+ea+eb),.995*eb/(1+ea+eb)
        return w,alpha,beta
    def objective(z):
        w,alpha,beta=unpack(z);total=0.
        for segment in segments:
            v=variance
            for r in segment:
                total+=math.log(v)+r*r/v
                v=w+alpha*r*r+beta*v
        return total/sum(len(s) for s in segments)
    fit=minimize(objective,[-3.,-2.,2.],method="L-BFGS-B",bounds=[(-12,3),(-8,8),(-8,8)],options={"maxiter":70})
    if not fit.success or not math.isfinite(fit.fun):
        return None
    w,alpha,beta=unpack(fit.x)
    return {"omega":w,"alpha":alpha,"beta":beta,"training_variance":variance}


def _garch_predict(history,fit,horizon):
    w,alpha,beta,v=(fit[k] for k in ("omega","alpha","beta","training_variance"))
    for r in history:
        v=w+alpha*r*r+beta*v
    forecasts=[]
    for _ in range(horizon):
        forecasts.append(v)
        v=w+(alpha+beta)*v
    return float(np.mean(forecasts))


def _score(rows,pred):
    actual=np.asarray([r["actual"] for r in rows]);pred=np.maximum(np.asarray(pred),1e-8)
    return {"samples":len(rows),"rmse_variance_bps2":float(np.sqrt(np.mean((actual-pred)**2))),
            "mae_volatility_bps":float(np.mean(abs(np.sqrt(actual)-np.sqrt(pred)))),
            "qlike":float(np.mean(np.log(pred)+actual/pred))}


def rv_run(*,batch_id,horizon=15,progress=None):
    if horizon not in HORIZONS:
        raise ValueError("Select 5, 15, 30 or 60 minutes")
    if progress:progress(1,"Verifying original BANKNIFTY spot candles")
    index,digest=_index_only(batch_id);days=sorted(index)[:60]
    splits=[days[:30],days[30:40],days[40:60]]
    rows,counts=_rv_rows(days,index,horizon)
    train,cal,test=([r for r in rows if r["session"] in set(part)] for part in splits)
    supported=len(days)==60 and len(train)>=60 and len(cal)>=20 and len(test)>=40 and all(len({r["session"] for r in part})>=n for part,n in zip((train,cal,test),(20,7,12)))
    report={"version":VERSION,"batch_id":batch_id,"source_sha256":digest,"horizon_minutes":horizon,"recorded_sessions":len(days),
            "evidence_counts":counts,"split_samples":[len(train),len(cal),len(test)],"methods":{},"run_id":None,
            "state":"insufficient_evidence","garch_parameters":None,
            "warning":"Forecasts target mean squared adjacent one-minute log returns in bps², not annualized IV or executable option prices. "
            "HAR-style regression uses trailing 5/15/30-minute realized variance, not the daily HAR-RV specification. "
            "Chronological retrospective research, no auto-promotion or order execution."}
    records=[]
    if supported:
        from sklearn.linear_model import Ridge
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        from threadpoolctl import threadpool_limits
        if progress:progress(40,"Fitting training-only HAR-style and GARCH models")
        with threadpool_limits(limits=1):
            model=make_pipeline(StandardScaler(),Ridge(alpha=1.))
            model.fit(np.log1p([r["features"] for r in train]),np.log1p([r["actual"] for r in train]))
        fit=_fit_garch(_segments(index,splits[0]))
        report["garch_parameters"]=fit
        unconditional=float(np.mean([r["actual"] for r in train]))
        for name,part in (("calibration",cal),("holdout",test)):
            with threadpool_limits(limits=1):
                har=np.expm1(np.clip(model.predict(np.log1p([r["features"] for r in part])),0,30))
            predictions={"training_unconditional":[unconditional]*len(part),"trailing_30m_rv":[r["features"][-1] for r in part],
                         "ewma_094":[r["ewma"] for r in part],"har_intraday":har}
            if fit:
                predictions["garch_11"]=[_garch_predict(r["history"],fit,horizon) for r in part]
            for method,pred in predictions.items():
                report["methods"].setdefault(method,{})[name]=_score(part,pred)
                for row,value in zip(part,pred):
                    records.append({"split":name,"session":row["session"],"minute":row["minute"],
                                    "method":method,"predicted_variance_bps2":float(max(0,value)),"actual_variance_bps2":row["actual"]})
        report.update(state="chronological_assessment_available",run_id=a._save(records),
                      garch_state="fitted" if fit else "optimizer_unavailable")
    report["audit_id"]=a._save([{"day":"RUN_SUMMARY","counts_json":json.dumps(counts,sort_keys=True),
                                "evidence_json":json.dumps(report,sort_keys=True)}],audit=True)
    if progress:progress(100,"Volatility forecast comparison saved")
    return report
