"""Train and assess a rolling BANKNIFTY OHLC forecast locally."""
import argparse
import csv
import json
import os
import uuid
from pathlib import Path
from workstation_api import banknifty_candle_forecast as m, service


def write_atomic(path,writer):
    tmp=path.with_suffix(path.suffix+".tmp")
    try:
        with tmp.open("x",encoding="utf-8",newline="") as out:writer(out)
        os.replace(tmp,path)
    finally:tmp.unlink(missing_ok=True)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days",type=int,default=365,help="Calendar lookback, 120-400 days; up to 1827 with --index-only")
    ap.add_argument("--index-only",action="store_true",help="Core index-only study; skip bank, peer and option loaders")
    ap.add_argument("--horizon",type=int,choices=m.f.HORIZONS,default=m.f.HORIZON,help="Future minutes; nondefault requires --index-only")
    ap.add_argument("--to-date",help="Exclusive end date in exchange timezone")
    ap.add_argument("--wings",type=int,default=3,help="Saved rolling monthly option offsets per side")
    ap.add_argument("--no-options",action="store_true")
    ap.add_argument("--ridge-only",action="store_true",help="Fast baseline check; default compares nonlinear model too")
    ap.add_argument("--shared-root",type=Path)
    args=ap.parse_args()
    try:
        root=args.shared_root.resolve() if args.shared_root else service.ROOT
        if not (root/"data").is_dir():raise ValueError("Original shared data directory is missing")
        service.DATA=root/"data"
        report,predictions=m.run(days=args.days,to_date=args.to_date,wings=None if args.no_options else args.wings,
                         index_only=args.index_only,horizon=args.horizon,algorithms=("ridge",) if args.ridge_only else m.ALGORITHMS,progress=lambda s:print(s,flush=True))
        folder=root/"results";folder.mkdir(exist_ok=True)
        stem="banknifty_ohlc_forecast_"+uuid.uuid4().hex
        path=folder/(stem+".json");journal=folder/(stem+"_predictions.csv")
        def csv_writer(out):
            w=csv.DictWriter(out,fieldnames=list(predictions[0]))
            w.writeheader();w.writerows(predictions)
        write_atomic(journal,csv_writer)
        report["prediction_csv"]=journal.name
        write_atomic(path,lambda out:json.dump(report,out,indent=2,sort_keys=True,allow_nan=False))
        print("MODE",report["mode"],"REQUESTED_DAYS",report["requested_calendar_days"],"OBSERVED_SPAN",report["observed_date_span"])
        print("HORIZON",report["horizon_minutes"],"TRAINING_STRIDE",report["training_stride_minutes"])
        print("CORE_MATRIX_BYTES",report["core_feature_matrix_bytes"])
        print("SESSIONS",json.dumps({k:len(report[k+"_dates"]) for k in ("training","validation","evaluation")}))
        print("SOURCE COVERAGE",json.dumps({"index_sessions":report["sources"]["index"]["sessions"],
              "bank_membership_days":report["sources"]["banks"]["membership_days"],
              "bank_stock_sources":len(report["sources"]["banks"]["source_hashes"]),
              "bank_weight_days":report["sources"]["banks"]["weighted_days"],
              "peer_sessions":{k:v.get("sessions",0) for k,v in report["sources"]["peers"].items()},
              "options_state":report["sources"]["options"]["state"],
              "options_reason":report["sources"]["options"].get("reason")}))
        print("FEATURE COVERAGE",json.dumps(report["feature_coverage"]))
        print("BASELINES",json.dumps(report["baselines"]))
        print("SELECTED",json.dumps(report["selected"]))
        print("VALIDATION SKILL",json.dumps(report["validation_skill"]))
        print("EVALUATION",json.dumps(report["evaluation"]))
        print("EVALUATION SKILL",json.dumps(report["evaluation_skill"]))
        print("DIRECTION PROBABILITY",json.dumps(report["direction_probability"]))
        print("ADAPTIVE COMPARISON",json.dumps(report["adaptive_comparison"]))
        print("CLOSE INTERVAL",json.dumps(report["close_interval"]))
        print("STATE",report["state"])
        print("REPORT",path)
        print("PREDICTIONS",journal)
        print(report["warning"])
        return 0
    except (ValueError,OSError,RuntimeError) as exc:
        print("BANKNIFTY OHLC forecast unavailable:",str(exc)[:240])
        return 2


if __name__=="__main__":
    raise SystemExit(main())
