"""Run saved-data BANKNIFTY target-capped mathematical and ML research."""
import argparse
import json
import os
import uuid
from pathlib import Path
from workstation_api import banknifty_target_capped_ml as model, service


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sessions",type=int,choices=(90,120),default=90)
    ap.add_argument("--to-date",help="Exclusive completed historical end date")
    ap.add_argument("--capital",type=float,default=17000.)
    ap.add_argument("--budget",type=float,default=12000.)
    ap.add_argument("--lot-size",type=int,default=30,help="Historical assumption")
    ap.add_argument("--max-lots",type=int,default=3)
    ap.add_argument("--wings",type=int,default=10)
    ap.add_argument("--shared-root",type=Path)
    args=ap.parse_args()
    try:
        root=args.shared_root.resolve() if args.shared_root else service.ROOT
        if not (root/"data").is_dir():raise ValueError("Original shared data directory is missing")
        service.DATA=root/"data"
        report=model.run(sessions=args.sessions,to_date=args.to_date,capital=args.capital,budget=args.budget,
                         lot_size=args.lot_size,max_lots=args.max_lots,wings=args.wings,progress=lambda s:print(s,flush=True))
        dest=root/"results"/("banknifty_target_capped_ml_"+uuid.uuid4().hex+".json")
        dest.parent.mkdir(exist_ok=True)
        tmp=dest.with_suffix(".tmp")
        try:
            with tmp.open("x",encoding="utf-8") as f:json.dump(report,f,indent=2,sort_keys=True,allow_nan=False)
            os.replace(tmp,dest)
        finally:tmp.unlink(missing_ok=True)
        print("COST INR PER ORDER",report["order_cost_inr"])
        print("DAILY CONTEXT",json.dumps({k:v for k,v in report["daily_context"].items() if k not in ("sources","context_source_dates","rejected_sources","original_view")}))
        print("DAILY CONTEXT REJECTIONS",json.dumps(report["daily_context"].get("rejected_sources",{})))
        print("OPTION COVERAGE",json.dumps(report["option_window_states"]))
        for hold,part in report["validation"].items():
            for policy,item in part["policies"].items():
                print("VALIDATION CALIBRATION",hold,policy,json.dumps(item.get("candidate_calibration",{})))
                print("VALIDATION LIMIT TOUCH",hold,policy,json.dumps(item.get("standing_target_touch_diagnostic",{})))
        print("SELECTED",json.dumps(report["selected"]))
        if report["evaluation"]:
            result=report["evaluation"]["result"]
            m=result.get("metrics",{})
            print("EXPLORATORY EVALUATION",json.dumps({k:m.get(k) for k in
                  ("scored_trades","profitable_trades","realized_target_hits","conditional_net_inr","conditional_fees_inr",
                   "target_capped_net_inr","target_capped_stress_inr","capped_stress_without_best_day_inr",
                   "stress_failed_attempts","max_within_day_closed_drawdown_inr","daily_coverage")}))
            print("EVALUATION QUALIFIED",result["qualified"])
            print("EVALUATION CALIBRATION",json.dumps(result.get("candidate_calibration",{})))
            print("EVALUATION LIMIT TOUCH",json.dumps(result.get("standing_target_touch_diagnostic",{})))
        print("STATE",report["state"])
        print("REPORT",dest)
        print(report["warning"])
        return 0
    except (ValueError,OSError,RuntimeError) as exc:
        print("BANKNIFTY capped/ML research unavailable:",str(exc)[:240])
        return 2


if __name__=="__main__":
    raise SystemExit(main())
