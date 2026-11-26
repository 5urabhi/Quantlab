"""Quick standalone next-candle forecast research on saved original index bars."""
from datetime import datetime,timedelta,timezone,date
from pathlib import Path
import argparse
import json
import os
import uuid

from workstation_api import candle_pattern_research as patterns, historical_alpha as h, alpha_retraining
from workstation_api import candle_barrier_research as barrier
from workstation_api.cpr_hybrid_research import SESSION_SPLITS,MAX_STUDY_DAYS


def main():
    today=datetime.now(h.IST).date()
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-date",default=None)
    parser.add_argument("--sessions",type=int,choices=tuple(SESSION_SPLITS),default=60)
    parser.add_argument("--first-passage",action="store_true",help="Study longer completed sequences and index movement barriers")
    parser.add_argument("--context-mode",choices=("off","receipt","archive"),default="off")
    parser.add_argument("--context-batch",default="auto")
    parser.add_argument("--fixed-panel",action="store_true")
    parser.add_argument("--to-date",default=today.isoformat())
    a=parser.parse_args()
    try:
        stop=date.fromisoformat(a.to_date)
        start=date.fromisoformat(a.from_date) if a.from_date else stop-timedelta(days={60:100,90:150,120:200}[a.sessions])
        if not a.first_passage and (a.fixed_panel or a.context_mode!="off"):
            raise ValueError("Context ablations require --first-passage")
        if not 0<(stop-start).days<=MAX_STUDY_DAYS or stop>today or not alpha_retraining.safe_window(datetime.now(timezone.utc)):
            raise ValueError("Use a completed range up to 200 days, outside Indian market priority hours")
        index,hashes,failures=h.shared_index_sources(start,stop,[h.MAX_TOTAL])
        dates=[d for d in sorted(index) if start.isoformat()<=d<stop.isoformat() and date.fromisoformat(d).weekday()<5][-a.sessions:]
        if len(dates)<a.sessions:
            raise ValueError(f"Need {a.sessions} observed sessions, have {len(dates)}; choose fewer or acquire older data")
        ntrain,nval,ntest=SESSION_SPLITS[a.sessions]
        splits=(dates[:ntrain],dates[ntrain:ntrain+nval],dates[ntrain+nval:ntrain+nval+ntest])
        if a.first_passage:
            report=barrier.assess(index,splits,context_mode=a.context_mode,fixed_panel=a.fixed_panel,
                                  context_batch=a.context_batch,progress=lambda pct,msg:print(f"{pct}% {msg}",flush=True))
        else:
            report=patterns.assess(index,splits,progress=lambda _,msg:print(msg,flush=True))
        report.update(training_dates=splits[0],validation_dates=splits[1],holdout_dates=splits[2],
                      source_hashes=hashes,source_failures=failures)
        root=Path("results");root.mkdir(exist_ok=True)
        dest=root/(("candle_barriers_" if a.first_passage else "candle_patterns_")+uuid.uuid4().hex+".json")
        temp=dest.with_suffix(".tmp")
        try:
            with temp.open("x",encoding="utf-8") as file:
                json.dump(report,file,indent=2,sort_keys=True,allow_nan=False)
            os.replace(temp,dest)
        finally:
            temp.unlink(missing_ok=True)
        for horizon,item in report["horizons"].items():
            if a.first_passage:
                print("Horizon:",horizon,"coverage:",json.dumps(item["coverage"]))
                for name,scope in item["scopes"].items():
                    print("Scope:",name,json.dumps(scope["matched_coverage"]))
                    for task,result in scope["augmented"]["tasks"].items():
                        chosen=result["selected_on_validation"]
                        scored=result["holdout"][chosen]
                        print(task,json.dumps({"selected":chosen,"brier":scored["brier"],"accuracy":scored["accuracy"],
                            "observed":scored["observed"],"predicted":scored["predicted"],
                            "matched_brier_difference":scope["selected_model_comparison"].get(task)}))
            else:
                print("Horizon:",horizon,json.dumps({k:v for k,v in item.items() if k!="pattern_library"}))
                print("Holdout pattern outcomes:",json.dumps(item["pattern_library"]["holdout"]))
        if a.first_passage:
            print("Individual bank targets:",report["bank_target_state"])
            for horizon,scope in report["bank_directions"].items():
                print("Bank horizon:",horizon,json.dumps(scope["matched_coverage"]))
                for task,result in scope["augmented"]["tasks"].items():
                    chosen=result["selected_on_validation"]
                    metric=result["holdout"][chosen]
                    print(task,json.dumps({"selected":chosen,"brier":metric["brier"],"accuracy":metric["accuracy"],
                        "predicted":metric["predicted"],"observed":metric["observed"],
                        "matched_brier_difference":scope["selected_model_comparison"].get(task)}))
        print("Report:",dest.resolve())
        print("Exploratory direction forecasts, not verified execution or profits.")
        return 0
    except (ValueError,RuntimeError,OSError) as exc:
        print("Candle research unavailable:",str(exc)[:200])
        return 2


if __name__=="__main__":
    raise SystemExit(main())
