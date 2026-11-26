"""One command: authorized original-receipt repair, wider probe and re-audit."""
from pathlib import Path
import argparse
import json
import os
import socket
import uuid

from dotenv import load_dotenv


def save_report(prefix,report):
    root=Path("results");root.mkdir(exist_ok=True)
    path=root/(prefix+"_"+uuid.uuid4().hex+".json")
    temp=path.with_suffix(".tmp")
    try:
        with temp.open("x",encoding="utf-8") as f:
            json.dump(report,f,indent=2,sort_keys=True,allow_nan=False)
        os.replace(temp,path)
    finally:
        temp.unlink(missing_ok=True)
    return path


def backend_running():
    # An older already-running worker might not honor the new process lock.
    # Do not kill it, compete with it or start a second recorder.
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as sock:
        sock.settimeout(.5)
        return sock.connect_ex(("127.0.0.1",8765))==0


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions",type=int,choices=(60,90,120),default=90)
    args=parser.parse_args()
    load_dotenv(dotenv_path=Path.cwd()/".env")
    from workstation_api import cpr_option_repair as repair, cpr_execution_evidence as evidence
    from workstation_api import data_maintenance as dm, cpr_live_evidence
    def progress(pct,msg):
        print(f"{pct:.0f}% {msg}",flush=True)
    if backend_running():
        print("Stop the existing workstation normally outside market hours, then rerun this same command. No recorder has been stopped.")
        return 2
    try:
        result=repair.run(sessions=args.sessions,progress=progress)
        path=save_report("cpr_option_repair",result)
        print("Repair report:",path.resolve(),flush=True)
        for name in ("core","wide"):
            lane=result.get(name)
            if lane:
                print(name,json.dumps({k:lane[k] for k in ("state","planned_missing_requests","new_receipts",
                    "unattempted_requests","empty_processed_receipts","observed_session_dates")}),flush=True)
        probe=result.get("wide_probe") or {}
        print("Wide probe:",json.dumps(probe),flush=True)
        wings=probe.get("verified_wings",repair.CORE_WINGS)
        # Explicit authorization: retain or expand the existing opted-in
        # maintenance scope only for the incrementally observed width.
        cfg=dm.config()
        if result["state"]=="bounded_pass_finished" and cfg["enabled"] and cfg["options"] and wings>cfg["wings"]:
            dm.configure({**cfg,"wings":wings},True)
            dm.request_check()
        print("Repair state:",result["state"],"saved maintenance wings:",dm.config()["wings"],flush=True)
        live=cpr_live_evidence.audit()
        print("Live evidence:",json.dumps(live),flush=True)
        # Always retain a comparable ATM +/-5 audit. A wider audit is
        # additional, not an outcome-selected replacement for the baseline.
        for width in (repair.CORE_WINGS,wings) if wings>repair.CORE_WINGS else (repair.CORE_WINGS,):
            if not repair._safe():
                print("Audit paused for market priority or disk reserve; saved receipts retained.")
                return 2
            report=evidence.run(sessions=args.sessions,wings=width,progress=progress)
            report["repair_report"]=path.name
            report["saved_live_evidence"]=live
            dest=save_report("cpr_execution_evidence",report)
            print("Audit wings:",width,"request-window states:",json.dumps(report["window_state_counts"]))
            print("Expired missing offset/session pairs:",report["repairable_missing_offset_session_pairs"])
            print("Observed quote coverage:",json.dumps(report["observed_quote_coverage"]))
            for name,part in report["parts"].items():
                print("Evidence:",name,json.dumps({k:v for k,v in part.items() if k not in ("dates","events","by_session")}))
            for name,screen in report["development_screen"].items():
                for hold,lanes in screen["lanes"].items():
                    for cost,lane in lanes.items():
                        print("Hold:",name,hold,cost,json.dumps({k:lane[k] for k in (
                            "scored_trades","conditional_net_inr","stress_utility_inr","stress_failed_attempts","max_exit_delay_minutes")}))
            print("Development-qualified holds:",report["development_qualified_holds_minutes"])
            print("Report:",dest.resolve(),flush=True)
        print("No order sent or trading strategy promoted. Restart the workstation normally for new live mappings.")
        return 0 if result["state"]=="bounded_pass_finished" else 2
    except (ValueError,OSError,RuntimeError,KeyError,TypeError) as exc:
        # Provider/network exceptions can carry sensitive details.
        print("Repair or audit unavailable:",type(exc).__name__)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
