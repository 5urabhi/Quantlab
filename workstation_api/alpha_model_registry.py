"""Local immutable research candidates; no pickle, live promotion or trading."""
from contextlib import closing
from datetime import date,timedelta
from hashlib import sha256
import json
import os
import re
import uuid
import numpy as np

from . import constituent_alpha as a, constituent_prospective as p

VERSION="alpha_candidate_registry_v1"
MAX_MODELS=1000
MONITOR_SESSIONS=20

def _root():
    path=a._root()/"candidate_registry"
    if path.is_symlink():
        raise ValueError("Unsafe model registry")
    path.mkdir(parents=True,exist_ok=True)
    return path

def _bytes(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()

def _digest_rows(rows,key):
    return sha256(_bytes([[r["session"],r["decision_utc"],[float(x) for x in r[key]],int(r["class"])] for r in rows])).hexdigest()

def freeze(name,fit,temperature,train,cal,test,*,source,policy,horizon,dates):
    """Freeze fitted logistic coefficients, calibration and source chronology.
    This is a research candidate, not a live-approved model.
    """
    if name not in ("index_logistic","constituent_logistic") or source not in ("historical","prospective"):
        raise ValueError("Only explicitly supported logistic candidate types may be serialized")
    key,estimator=fit
    scale=estimator.named_steps["standardscaler"];model=estimator.named_steps["logisticregression"]
    if tuple(model.classes_)!=a.CLASSES:
        raise ValueError("Unexpected model classes")
    tr,ca,ho=[list(part) for part in dates]
    if not tr or not ca or not ho or max(tr)>=min(ca) or max(ca)>=min(ho):
        raise ValueError("Candidate chronology must be strictly separated")
    if any(r["session"] not in set(part) for rows,part in ((train,tr),(cal,ca),(test,ho)) for r in rows):
        raise ValueError("Candidate sample outside frozen split")
    probabilities=a._temperature(a._predict(fit,test),temperature)
    holdout=a._directional_stats(test,[a._call(v) for v in probabilities],probabilities)
    value={"version":VERSION,"name":name,"source":source,"source_policy_sha256":policy,"horizon_minutes":horizon,
           "feature_key":key,"classes":list(a.CLASSES),"mean":scale.mean_.tolist(),"scale":scale.scale_.tolist(),
           "coef":model.coef_.tolist(),"intercept":model.intercept_.tolist(),"temperature":float(temperature),
           "training_dates":tr,"calibration_dates":ca,"reference_holdout_dates":ho,
           "training_sha256":_digest_rows(train,key),"calibration_sha256":_digest_rows(cal,key),
           "reference_holdout_sha256":_digest_rows(test,key),"reference_holdout_brier":holdout["brier"],
           "reference_holdout_samples":len(test),"live_approved":False}
    # Verify the portable representation gives the exact original probabilities.
    if not np.allclose(probabilities,predict(value,test),rtol=1e-10,atol=1e-12):
        raise ValueError("Portable candidate probability mismatch")
    body=_bytes(value);ident=sha256(body).hexdigest()
    root=_root();path=root/(ident+".json")
    if path.exists():
        load(ident)
        return ident
    if sum(1 for q in root.glob("*.json"))>=MAX_MODELS:
        raise ValueError("Model registry limit reached; preserve or explicitly archive older candidates")
    temp=root/("."+uuid.uuid4().hex+".tmp")
    try:
        with temp.open("xb") as handle:
            handle.write(body)
        os.replace(temp,path)
    finally:
        temp.unlink(missing_ok=True)
    return ident

def predict(value,rows):
    x=np.asarray([r[value["feature_key"]] for r in rows],dtype=float)
    mean=np.asarray(value["mean"]);scale=np.asarray(value["scale"])
    coef=np.asarray(value["coef"]);intercept=np.asarray(value["intercept"])
    if x.ndim!=2 or x.shape[1]!=len(mean) or scale.shape!=mean.shape or coef.shape!=(3,len(mean)) or intercept.shape!=(3,) or np.any(scale<=0):
        raise ValueError("Frozen model feature schema mismatch")
    z=(((x-mean)/scale)@coef.T+intercept)/value["temperature"]
    z-=z.max(axis=1,keepdims=True)
    q=np.exp(z);q/=q.sum(axis=1,keepdims=True)
    # Reproduce the original probability floor in the calibration step.
    raw=((x-mean)/scale)@coef.T+intercept
    raw-=raw.max(axis=1,keepdims=True)
    raw=np.exp(raw);raw/=raw.sum(axis=1,keepdims=True)
    return a._temperature(raw,value["temperature"])

def load(ident):
    if not re.fullmatch(r"[a-f0-9]{64}",ident):
        raise ValueError("Invalid model version")
    path=_root()/(ident+".json")
    if not path.is_file() or path.is_symlink() or path.stat().st_size>512000:
        raise ValueError("Candidate artifact unavailable")
    body=path.read_bytes()
    if sha256(body).hexdigest()!=ident:
        raise ValueError("Candidate checksum mismatch")
    value=json.loads(body)
    if value.get("version")!=VERSION or value.get("live_approved") is not False:
        raise ValueError("Unsupported model registry artifact")
    return value

def list_candidates():
    rows=[]
    for i,path in enumerate(sorted(_root().glob("*.json"),key=lambda p:p.stat().st_mtime,reverse=True)):
        if i>=MAX_MODELS:break
        try:
            value=load(path.stem)
            rows.append({"model_id":path.stem,**{k:value[k] for k in ("name","source","horizon_minutes",
                "training_dates","calibration_dates","reference_holdout_dates","reference_holdout_brier","reference_holdout_samples","live_approved")}})
        except (ValueError,OSError,KeyError,TypeError):
            continue
        if len(rows)>=100:break
    return rows

def monitor(*,model_id,progress=None,now=None):
    value=load(model_id)
    if value["source"]!="prospective" or value["source_policy_sha256"]!=a.policy_for(value["horizon_minutes"]):
        raise ValueError("Only a matching receipt-based prospective candidate can be monitored on this ledger")
    horizon=value["horizon_minutes"]
    start=(date.fromisoformat(max(value["reference_holdout_dates"]))+timedelta(days=1)).isoformat()
    today=p._session(now or p._now()).date().isoformat()
    days=[];rows=[];coverage={}
    with closing(a._read()) as db:
        days=a._days(db,horizon,today,start_session=start)[:MONITOR_SESSIONS]
        for i,day in enumerate(days):
            if progress:progress(5+80*i/max(1,len(days)),"Monitoring frozen candidate on later session "+day)
            selected,counts=a.sample_day(a._rows(db,day,horizon))
            rows.extend(selected);coverage[day]=counts
    report={"model_id":model_id,"state":"insufficient_later_evidence","later_dates":days,
            "required_sessions":MONITOR_SESSIONS,"support":a.support(rows),"coverage":coverage,
            "reference_holdout_brier":value["reference_holdout_brier"],"metrics":None,"deterioration_flag":None,
            "warning":"Fixed later-session comparison, not a statistical change-point guarantee or automatic permission to trade. "
                      "No refit, reselection, or backdating. A Brier deterioration greater than 0.05 is a descriptive flag only."}
    required=20 if horizon==0 else 40
    if len(days)==MONITOR_SESSIONS and a._supported(rows,required,12):
        probs=predict(value,rows)
        metrics=a._directional_stats(rows,[a._call(v) for v in probs],probs)
        report.update(state="later_assessment_available",metrics=metrics,
                      deterioration_flag=bool(metrics["brier"]>value["reference_holdout_brier"]+.05))
    report["audit_id"]=a._save([{"day":"RUN_SUMMARY","evidence_json":json.dumps(report,sort_keys=True,allow_nan=False)}],audit=True)
    if progress:progress(100,"Frozen candidate monitoring evidence saved")
    return report
