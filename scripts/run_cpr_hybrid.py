"""Run the CPR baseline, ML filter and offline-Q study on saved sources."""
from datetime import datetime, timedelta
from pathlib import Path
import argparse
import json
import os
import uuid

from workstation_api import cpr_hybrid_research as research
from workstation_api.historical_alpha import IST


def main():
    today=datetime.now(IST).date()
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-date",default=(today-timedelta(days=100)).isoformat())
    parser.add_argument("--to-date",default=today.isoformat(),help="End exclusive; completed sessions only")
    parser.add_argument("--frame",type=int,choices=research.FRAMES,default=5)
    parser.add_argument("--hold",type=int,choices=research.HOLDS,default=60)
    parser.add_argument("--capital",type=float,default=17000)
    parser.add_argument("--risk-budget",type=float,default=4250,
                        help="Maximum modeled full premium plus fee exposure and daily gross loss allowance")
    parser.add_argument("--lot-size",type=int,default=30,help="Historical assumption, not exchange-verified")
    parser.add_argument("--max-lots",type=int,default=1)
    parser.add_argument("--wings",type=int,default=3)
    parser.add_argument("--penalty-bps",type=float,default=25,help="Base adverse premium penalty per side; primary study adds 10bps")
    a=parser.parse_args()
    try:
        report,journal,sources=research.run(from_date=a.from_date,to_date=a.to_date,
            frame=a.frame,hold=a.hold,capital=a.capital,risk_budget=a.risk_budget,
            lot_size=a.lot_size,max_lots=a.max_lots,wings=a.wings,premium_penalty_bps=a.penalty_bps,
            progress=lambda pct,msg:print(f"{pct:.0f}% {msg}",flush=True))
        root=Path("results");root.mkdir(exist_ok=True)
        path=root/("cpr_hybrid_"+uuid.uuid4().hex+".json")
        temp=path.with_suffix(".tmp")
        try:
            with temp.open("x",encoding="utf-8") as f:
                json.dump({"report":report,"journal":journal,"sources":sources},f,
                          indent=2,sort_keys=True,allow_nan=False)
            os.replace(temp,path)
        finally:
            temp.unlink(missing_ok=True)
    except (ValueError,RuntimeError,OSError) as exc:
        print("Research unavailable:",type(exc).__name__)
        # ValueError messages from this local study describe bounded data/settings,
        # not provider responses or credentials.
        if isinstance(exc,ValueError):
            print(str(exc)[:240])
        return 2
    print("State:",report["state"])
    print("Sessions:",report["recorded_index_sessions"],"/",report["required_sessions"])
    print("Episode states:",report["episode_states"])
    print("Split support:",json.dumps(report["split_support"]))
    if "ml" in report:
        print("ML:",json.dumps(report["ml"]))
        print("ML holdout:",json.dumps(report["ml_holdout"]))
        print("Offline Q:",json.dumps(report["offline_q"]))
    for name,result in report["methods"].items():
        print(name,json.dumps({k:v for k,v in result.items() if k!="daily"}))
    print("Report:",path.resolve())
    print("No actual fills, profitability, or live RL approval certified.")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
