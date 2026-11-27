"""Compare matched saved MarketDynamics evaluation predictions, no fitting."""
import argparse
import csv
import json
from pathlib import Path

import numpy as np
from workstation_api import banknifty_candle_forecast as m

MATCH_FIELDS=("training_dates","validation_dates","evaluation_dates","horizons","delay_minutes","deadband_bps")
KEY=("session","decision_utc","entry_reference_utc","exit_reference_utc","horizon_minutes")
ACTUAL=("actual_return_bps","actual_up_excursion_bps","actual_down_excursion_bps")


def load(path):
    path=Path(path);report=json.loads(path.read_text())
    name=report["prediction_csv"]
    if Path(name).name!=name:raise ValueError("Prediction CSV must be a report-local filename")
    with (path.parent/name).open(newline="") as f:
        rows={}
        for r in csv.DictReader(f):
            key=tuple(r[k] for k in KEY)
            if key in rows:raise ValueError("Duplicate evaluation key")
            rows[key]=r
    return report,rows


def compare(left,right):
    a,ar=left;b,br=right
    for field in MATCH_FIELDS:
        if a[field]!=b[field]:raise ValueError("Incompatible "+field)
    if ar.keys()!=br.keys():raise ValueError("Scheduled decision keys differ; no matched claim")
    for key,x in ar.items():
        y=br[key]
        if any(x[k]!=y[k] for k in ("outcome_observed","actual_class",*ACTUAL)):
            raise ValueError("Outcome references differ at "+str(key))
    result={"baseline":a["version"],"candidate":b["version"],"matched_scheduled_rows":len(ar),
            "warning":"Exploratory matched historical comparison; previously inspected dates, descriptive intervals, no trading qualification.","horizons":{}}
    for h in a["horizons"]:
        keys=[key for key,x in ar.items() if int(key[-1])==h and x["outcome_observed"]=="True"]
        if not keys:raise ValueError("No matched observed outcomes")
        days=np.asarray([key[0] for key in keys]);labels=np.asarray([int(ar[key]["actual_class"])+1 for key in keys])
        truth=np.eye(3)[labels];nonflat=labels!=1
        target=np.asarray([[float(ar[key][name]) for name in ACTUAL] for key in keys])
        record={"rows":len(keys),"sessions":len(set(days)),"models":{}}
        for name in ("index_only","joint"):
            if name not in a["models"] or name not in b["models"]:continue
            def arrays(rows):
                p=np.asarray([[float(rows[k][name+"_"+j+"_probability"]) for j in ("down","flat","up")] for k in keys])
                y=np.asarray([[float(rows[k][name+"_predicted_"+j+"_bps"]) for j in ("return","up_excursion","down_excursion")] for k in keys])
                if not np.isfinite(p).all() or np.any(p<0) or not np.allclose(p.sum(axis=1),1,atol=1e-5) or not np.isfinite(y).all():
                    raise ValueError("Nonfinite or invalid prediction")
                return p,y
            p0,y0=arrays(ar);p1,y1=arrays(br)
            loss0=np.sum((p0-truth)**2,axis=1);loss1=np.sum((p1-truth)**2,axis=1)
            move=lambda p:(1-p[:,1]-nonflat)**2
            sign=lambda p:(p[nonflat,2]/np.maximum(p[nonflat,0]+p[nonflat,2],1e-12)-(labels[nonflat]==2))**2
            mae0=np.abs(y0-target);mae1=np.abs(y1-target)
            record["models"][name]={"baseline_brier":float(m._avg(loss0,days)),"candidate_brier":float(m._avg(loss1,days)),
                "candidate_minus_baseline_brier":m.paired_day_interval(loss1-loss0,days),
                "candidate_minus_baseline_movement_brier":m.paired_day_interval(move(p1)-move(p0),days),
                "candidate_minus_baseline_sign_brier":m.paired_day_interval(sign(p1)-sign(p0),days[nonflat]) if nonflat.any() else None,
                "candidate_minus_baseline_mae_bps":{key:m.paired_day_interval(mae1[:,j]-mae0[:,j],days) for j,key in enumerate(ACTUAL)}}
        if not record["models"]:raise ValueError("No shared model names")
        result["horizons"][str(h)]=record
    return result


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--baseline",required=True,type=Path)
    ap.add_argument("--candidate",required=True,type=Path)
    args=ap.parse_args()
    report=compare(load(args.baseline),load(args.candidate))
    print(json.dumps(report,indent=2,allow_nan=False))


if __name__=="__main__":main()
