"""Manually requested saved-source execution evidence study."""
from pathlib import Path
import argparse
import json
import os
import uuid

from workstation_api import cpr_execution_evidence as evidence


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions",type=int,choices=(60,90,120),default=90)
    parser.add_argument("--to-date",default=None,help="End exclusive; completed dates only")
    args=parser.parse_args()
    try:
        report=evidence.run(sessions=args.sessions,to_date=args.to_date,manual_saved_research=True,
            progress=lambda pct,msg:print(f"{pct:.0f}% {msg}",flush=True))
        root=Path("results");root.mkdir(exist_ok=True)
        dest=root/("cpr_execution_evidence_"+uuid.uuid4().hex+".json")
        temp=dest.with_suffix(".tmp")
        try:
            with temp.open("x",encoding="utf-8") as f:
                json.dump(report,f,indent=2,sort_keys=True,allow_nan=False)
            os.replace(temp,dest)
        finally:
            temp.unlink(missing_ok=True)
    except (ValueError,RuntimeError,OSError) as exc:
        print("Execution evidence unavailable:",type(exc).__name__)
        if isinstance(exc,ValueError):print(str(exc)[:240])
        return 2
    print("Request-window states:",json.dumps(report["window_state_counts"]))
    print("Expired missing offset/session pairs:",report["repairable_missing_offset_session_pairs"])
    print("Observed quote coverage:",json.dumps(report["observed_quote_coverage"]))
    for name,part in report["parts"].items():
        print("Evidence:",name,json.dumps({k:v for k,v in part.items() if k not in ("dates","events","by_session")}))
    for name,screen in report["development_screen"].items():
        print("Development scope:",name,screen["shared_opportunities"],"shared opportunities;",screen["excluded_late_opportunities"],"late exclusions")
        for hold,lanes in screen["lanes"].items():
            for cost,result in lanes.items():
                print("Holding-period screen:",name,"EOD" if hold=="0" else hold,cost+"bps/side",
                    json.dumps({k:result[k] for k in ("scored_trades","profitable_trades","conditional_net_inr","conditional_fees_inr",
                        "stress_utility_inr","stress_failed_attempts","unresolved_trades","max_exit_delay_minutes",
                        "worst_observed_mark_return","exit_reasons")} | {"days":result["daily_coverage"]["days_with_scored_trade"]}))
    print("Development-qualified holds:",report["development_qualified_holds_minutes"])
    print("Report:",dest.resolve())
    print("No strategy frozen, promoted, or executed. Recent evaluation dates audited for coverage only.")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
