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
    parser.add_argument("--from-date",default=None,help="Start inclusive; default expands with requested sessions")
    parser.add_argument("--sessions",type=int,choices=tuple(research.SESSION_SPLITS),default=60)
    parser.add_argument("--dense-training",action="store_true",help="Earlier scanner anchors every 15-minute bin; session-balanced ML and Q")
    parser.add_argument("--to-date",default=today.isoformat(),help="End exclusive; completed sessions only")
    parser.add_argument("--entry-mode",choices=research.ENTRY_MODES,default="crossover",
                        help="Original crossover baseline or daily scheduled CPR/EMA opportunity scan")
    parser.add_argument("--context-mode",choices=("off","receipt","archive"),default="off",
                        help="Receipt-as-of context, or explicitly reviewed historical archive availability")
    parser.add_argument("--context-batch",default="auto",help="Dated BANKNIFTY membership batch ID; auto selects by date overlap")
    parser.add_argument("--debit-spreads",action="store_true",help="Compare paired debit spread gross-funding and net-debit paper lanes")
    parser.add_argument("--dynamic-q",action="store_true",help="Compare five-minute in-position bank/global context Q with static and technical exits")
    parser.add_argument("--context-q",action="store_true",help="Compare matched technical and contextual offline-Q exits")
    parser.add_argument("--sequences",action="store_true",help="Add longer completed candle sequences and detailed bank features to matched ML")
    parser.add_argument("--derivatives",action="store_true",help="Add observed same-strike OI/raw IV/relative volume to matched ML")
    parser.add_argument("--patterns",action="store_true",help="Study and compare completed-candle pattern models")
    parser.add_argument("--fixed-panel",action="store_true",help="Add separate major-bank panel research, not historical index membership")
    parser.add_argument("--rank-entries",action="store_true",help="Compare validation-calibrated probability and affordable contract ranking")
    parser.add_argument("--frame",type=int,choices=research.FRAMES,default=5)
    parser.add_argument("--hold",type=int,choices=research.HOLDS,default=60,
                        help="Maximum holding minutes; 0 holds to mandatory 15:20 IST square-off unless exited earlier")
    parser.add_argument("--capital",type=float,default=17000)
    parser.add_argument("--risk-budget",type=float,default=4250,
                        help="Maximum modeled full premium plus fee exposure and daily gross loss allowance")
    parser.add_argument("--lot-size",type=int,default=30,help="Historical assumption, not exchange-verified")
    parser.add_argument("--max-lots",type=int,default=1)
    parser.add_argument("--wings",type=int,default=3)
    parser.add_argument("--penalty-bps",type=float,default=25,help="Base adverse premium penalty per side; primary study adds 10bps")
    a=parser.parse_args()
    if a.from_date is None:
        a.from_date=(datetime.fromisoformat(a.to_date).date()-timedelta(days={60:100,90:150,120:200}[a.sessions])).isoformat()
    try:
        report,journal,sources=research.run(from_date=a.from_date,to_date=a.to_date,
            frame=a.frame,hold=a.hold,capital=a.capital,risk_budget=a.risk_budget,entry_mode=a.entry_mode,
            context_mode=a.context_mode,context_batch=a.context_batch,rank_entries=a.rank_entries,
            pattern_research=a.patterns,fixed_panel=a.fixed_panel,context_q=a.context_q,debit_spreads=a.debit_spreads,
            sessions=a.sessions,dense_training=a.dense_training,sequence_research=a.sequences,derivative_research=a.derivatives,dynamic_q=a.dynamic_q,
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
    print("Entry mode:",report["settings"]["entry_mode"])
    print("Sessions:",report["recorded_index_sessions"],"/",report["required_sessions"])
    print("Episode states:",report["episode_states"])
    print("Account-constrained split support:",json.dumps(report["split_support"]))
    print("Capital-independent learning support:",json.dumps(report["learning_support"]))
    context=report["context_coverage"]
    print("Context coverage:",json.dumps({k:v for k,v in context.items() if k not in ("bank_feature_names","global_feature_names","factor_receipt_sha256","warning")}))
    for width,item in report["candle_patterns"].get("horizons",{}).items():
        print("Candle horizon:",width,json.dumps({k:v for k,v in item.items() if k!="pattern_library"}))
    if "ml" in report:
        print("ML:",json.dumps(report["ml"]))
        print("ML holdout:",json.dumps(report["ml_holdout"]))
        print("Offline Q (5% stop):",json.dumps(report["offline_q"]))
        print("Offline Q (15% emergency stop):",json.dumps(report["offline_q_emergency_stop"]))
        if a.dynamic_q:
            print("Dynamic context:",json.dumps({k:v for k,v in report["dynamic_context"].items() if k!="source_audit"}))
            print("Dynamic Q:",json.dumps(report.get("dynamic_q_training",{})))
    for name,result in report["methods"].items():
        summary={k:v for k,v in result.items() if k not in ("daily","daily_coverage")}
        if "daily_coverage" in result:
            summary["daily_coverage"]={k:v for k,v in result["daily_coverage"].items() if k!="by_session"}
        print(name,json.dumps(summary))
    for scope,item in report["ranked_entry_research"].items():
        print("Ranked scope:",scope,json.dumps({k:v for k,v in item.items() if k not in ("methods","models")}))
        for name,info in item["models"].items():
            print("Ranked model:",name,json.dumps({k:v for k,v in info.items() if k not in ("gate",)}))
            if "gate" in info:
                print("Development gate:",json.dumps(info["gate"]))
        for name,result in item["methods"].items():
            summary={k:v for k,v in result.items() if k not in ("daily","daily_coverage")}
            if "daily_coverage" in result:
                summary["daily_coverage"]={k:v for k,v in result["daily_coverage"].items() if k!="by_session"}
            print(name,json.dumps(summary))
    for lane,item in report["debit_spread_research"].items():
        print("Debit spread lane:",lane,json.dumps({k:v for k,v in item.items() if k!="methods"}))
        for name,result in item["methods"].items():
            print(name,json.dumps({k:v for k,v in result.items() if k not in ("daily","daily_coverage")} | {"days_with_entry":result["daily_coverage"]["days_with_entry"]}))
    print("Report:",path.resolve())
    print("No actual fills, profitability, or live RL approval certified.")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
