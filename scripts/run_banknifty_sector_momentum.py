"""Compare non-ML BANKNIFTY momentum and sector-confirmed reversal policies."""
import argparse
import json
import os
import uuid
from pathlib import Path
from workstation_api import banknifty_sector_momentum as model, service


def progress(phase,rule,hold,lanes,qualified):
    for cost,m in lanes.items():
        summary={k:m[k] for k in ("scored_trades","profitable_trades","realized_target_hits",
                 "conditional_net_inr","conditional_fees_inr","stress_utility_inr","unresolved_trades",
                 "recovered_delayed_exits","exit_reasons","spot_forecast","rule_coverage")}
        print(phase,rule,hold,cost,json.dumps(summary),flush=True)
    print("QUALIFIED",phase,rule,hold,qualified,flush=True)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sessions",type=int,choices=(60,90,120),default=90)
    ap.add_argument("--to-date",help="Completed date exclusive")
    ap.add_argument("--capital",type=float,default=17000.)
    ap.add_argument("--budget",type=float,default=12000.)
    ap.add_argument("--lot-size",type=int,default=30,help="Historical assumption")
    ap.add_argument("--wings",type=int,default=10)
    ap.add_argument("--shared-root",type=Path)
    args=ap.parse_args()
    try:
        root=args.shared_root.resolve() if args.shared_root else service.ROOT
        if not (root/"data").is_dir():raise ValueError("Original shared data directory is missing")
        service.DATA=root/"data"
        report=model.run(sessions=args.sessions,to_date=args.to_date,capital=args.capital,budget=args.budget,
                         lot_size=args.lot_size,wings=args.wings,progress=progress,log=lambda s:print(s,flush=True))
        dest=root/"results"/("banknifty_sector_momentum_"+uuid.uuid4().hex+".json")
        dest.parent.mkdir(exist_ok=True)
        tmp=dest.with_suffix(".tmp")
        try:
            with tmp.open("x",encoding="utf-8") as f:json.dump(report,f,indent=2,sort_keys=True,allow_nan=False)
            os.replace(tmp,dest)
        finally:tmp.unlink(missing_ok=True)
        print("RECEIPT COVERAGE",json.dumps(report["option_window_states"]))
        print("MATCHED OPPORTUNITIES",json.dumps(report["coverage"]))
        print("SELECTED",json.dumps(report["selected"]))
        print("STATE",report["state"])
        print("REPORT",dest)
        print(report["warning"])
        return 0
    except (ValueError,OSError,RuntimeError) as exc:
        print("BANKNIFTY sector research unavailable:",str(exc)[:240])
        return 2


if __name__=="__main__":
    raise SystemExit(main())
