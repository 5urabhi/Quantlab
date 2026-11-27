"""Saved-data BANKNIFTY 10% net premium target, without ML."""
import argparse
import json
import os
import uuid
from pathlib import Path
from workstation_api import banknifty_math_target as model, service


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions",type=int,choices=(60,90,120),default=90)
    parser.add_argument("--to-date",help="Completed historical end date, exclusive")
    parser.add_argument("--capital",type=float,default=17000.)
    parser.add_argument("--budget",type=float,default=12000.,help="Full premium funding and cumulative daily realized-loss cap")
    parser.add_argument("--lot-size",type=int,default=30,help="Historical lot-size assumption, not exchange-certified")
    parser.add_argument("--max-lots",type=int,default=3)
    parser.add_argument("--wings",type=int,default=5)
    parser.add_argument("--shared-root",type=Path,help="Original QuantLab root for an isolated worktree; only reads data and writes new results")
    args=parser.parse_args()
    try:
        root=args.shared_root.resolve() if args.shared_root else service.ROOT
        if not (root/"data").is_dir():raise ValueError("Original shared data directory is missing")
        service.DATA=root/"data"
        report=model.run(sessions=args.sessions,to_date=args.to_date,capital=args.capital,budget=args.budget,
                         lot_size=args.lot_size,max_lots=args.max_lots,wings=args.wings,
                         progress=lambda pct,msg:print(f"{pct}% {msg}",flush=True))
        dest=root/"results"/("banknifty_math_"+uuid.uuid4().hex+".json")
        dest.parent.mkdir(exist_ok=True)
        tmp=dest.with_suffix(".tmp")
        try:
            with tmp.open("x",encoding="utf-8") as f:json.dump(report,f,indent=2,sort_keys=True,allow_nan=False)
            os.replace(tmp,dest)
        finally:tmp.unlink(missing_ok=True)
        print("Option receipt coverage:",json.dumps(report["option_window_states"]))
        for hold,item in report["validation"].items():
            print("VALIDATION",hold,"minutes","qualified",item["qualified"],"candidate states",json.dumps(item["candidate_states"]))
            for cost,lane in item["lanes"].items():summary(cost,lane)
        if report["evaluation"]:
            print("EXPLORATORY EVALUATION",report["selected_hold"],"minutes")
            for cost,lane in report["evaluation"]["lanes"].items():summary(cost,lane)
        print("State:",report["state"])
        print("Report:",dest)
        print(report["warning"])
        return 0
    except (ValueError,OSError,RuntimeError) as exc:
        print("BANKNIFTY math research unavailable:",str(exc)[:240])
        return 2


def summary(cost,lane):
    m=lane["metrics"]
    print("Cost bps/side",cost,json.dumps({k:m[k] for k in (
        "scored_trades","profitable_trades","realized_target_hits","conditional_net_inr",
        "conditional_fees_inr","stress_utility_inr","unresolved_trades","recovered_delayed_exits",
        "exit_reasons","max_within_day_closed_drawdown_inr")}))
    print("States:",json.dumps(m["states"]))


if __name__=="__main__":
    raise SystemExit(main())
