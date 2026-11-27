"""Optional local PyTorch sequence research, isolated from the live recorder."""
import argparse
import csv
import json
import os
import uuid
from pathlib import Path
from workstation_api import banknifty_sequence_forecast as m, service
from scripts.run_banknifty_candle_forecast import write_atomic


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days",type=int,default=365)
    ap.add_argument("--to-date",help="Exclusive historical exchange-local end date")
    ap.add_argument("--wings",type=int,default=3)
    ap.add_argument("--no-options",action="store_true")
    ap.add_argument("--epochs",type=int,default=6)
    ap.add_argument("--batch",type=int,default=96)
    ap.add_argument("--device",choices=("cpu","cuda"),default="cpu")
    ap.add_argument("--full-grid",action="store_true",help="All 12 architecture/lookback pairs rather than the six prespecified comparisons")
    ap.add_argument("--shared-root",type=Path)
    args=ap.parse_args()
    try:
        root=args.shared_root.resolve() if args.shared_root else service.ROOT
        if not (root/"data").is_dir():raise ValueError("Original shared data directory missing")
        service.DATA=root/"data"
        torch,_=m._torch()
        report,predictions,checkpoint=m.run(days=args.days,to_date=args.to_date,
              wings=None if args.no_options else args.wings,epochs=args.epochs,batch=args.batch,
              device_name=args.device,full_grid=args.full_grid,progress=lambda s:print(s,flush=True))
        dest=root/"results";dest.mkdir(exist_ok=True)
        stem="banknifty_sequence_forecast_"+uuid.uuid4().hex
        path=dest/(stem+".json");journal=dest/(stem+"_predictions.csv");weights=dest/(stem+"_research_only.pt")
        temp=weights.with_suffix(".tmp")
        try:
            torch.save(checkpoint,temp)
            os.replace(temp,weights)
        finally:temp.unlink(missing_ok=True)
        def csv_writer(out):
            writer=csv.DictWriter(out,fieldnames=list(predictions[0]))
            writer.writeheader();writer.writerows(predictions)
        write_atomic(journal,csv_writer)
        report.update(prediction_csv=journal.name,research_checkpoint=weights.name)
        write_atomic(path,lambda out:json.dump(report,out,indent=2,sort_keys=True,allow_nan=False))
        print("PARTITION WINDOWS",json.dumps(report["partition_windows"]))
        print("ASSETS",json.dumps(report["assets"]))
        print("FEATURE COVERAGE",json.dumps(report["feature_coverage"]))
        print("BANK MEMBERSHIP AUDIT",json.dumps({part:{"reserved_days":len(report[part+"_dates"]),
            "missing_dated_membership":[day for day in report[part+"_dates"] if not report["session_bank_coverage"][day]["dated_membership"]],
            "verified_weight_days":sum(report["session_bank_coverage"][day]["verified_weights"] for day in report[part+"_dates"])}
            for part in ("training","validation","evaluation")}))
        print("SELECTED",json.dumps(report["selected"]))
        print("VALIDATION MODELS",json.dumps([{k:v for k,v in row.items() if k!="history"} for row in report["validation_models"]]))
        print("EVALUATION ADAPTIVE",json.dumps(report["adaptive_baselines"]["evaluation"]))
        print("EVALUATION V1 MATCHED",json.dumps(report["matched_v1_tabular"]["evaluation"]))
        print("EVALUATION SEQUENCE",json.dumps(report["evaluation"]))
        print("SKILL VS ADAPTIVE",json.dumps(report["evaluation_skill_vs_adaptive"]))
        print("SKILL VS V1",json.dumps(report["evaluation_skill_vs_v1"]))
        print("STATE",report["state"])
        print("REPORT",path)
        print("PREDICTIONS",journal)
        print("RESEARCH CHECKPOINT",weights)
        print(report["warning"])
        return 0
    except (ValueError,OSError,RuntimeError) as exc:
        print("BANKNIFTY sequence research unavailable:",str(exc)[:300])
        return 2


if __name__=="__main__":
    raise SystemExit(main())
