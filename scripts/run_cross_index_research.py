"""Read-only inventory and matched historical spot-index research."""
from datetime import datetime,date,timedelta
from pathlib import Path
import argparse
import json
import os
import uuid

from workstation_api import cross_index_research as cross, historical_alpha as h
from workstation_api import index_spot, cockpit_sources
from workstation_api.cpr_hybrid_research import SESSION_SPLITS

MODES={**index_spot.CORE_RESEARCH_MODES,**{k:k for k in index_spot.RESEARCH_INDEXES}}


def inventory():
    rows=[]
    for key,mode in MODES.items():
        try:
            inst,reason=index_spot.resolve_with_evidence(mode)
            count=len(cockpit_sources._candidates(key))
            rows.append({"index":key,"security_id":inst.security_id if inst else None,
                         "identity_source":reason,"local_candidate_receipts":count,
                         "history_verified":False})
        except (ValueError,OSError,KeyError,TypeError) as exc:
            rows.append({"index":key,"state":"inventory_unavailable","reason":type(exc).__name__})
    return rows


def main():
    today=datetime.now(h.IST).date()
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-sources",action="store_true",help="Check existing local master and receipt candidates; no network")
    parser.add_argument("--indices",nargs=2,choices=tuple(MODES),default=["INDEX:BANKNIFTY","INDEX:NIFTY50"])
    parser.add_argument("--sessions",type=int,choices=tuple(SESSION_SPLITS),default=90)
    parser.add_argument("--to-date",default=today.isoformat(),help="End exclusive, completed dates only")
    args=parser.parse_args()
    if args.list_sources:
        for row in inventory():print(json.dumps(row,sort_keys=True))
        print("Candidate receipts are not verified coverage; no provider requests made.")
        return 0
    try:
        if len(set(args.indices))!=2:
            raise ValueError("Choose two distinct index identities")
        stop=date.fromisoformat(args.to_date)
        if stop>today:
            raise ValueError("Use completed historical sessions only")
        start=stop-timedelta(days={60:100,90:150,120:200}[args.sessions])
        series={};sources={};failures={}
        for identity in args.indices:
            print("Verifying:",identity,flush=True)
            series[identity],sources[identity],failures[identity]=h.shared_index_sources(start,stop,[h.MAX_TOTAL],identity=identity)
        common=sorted(set.intersection(*(set(s) for s in series.values())))
        dates=[d for d in common if start.isoformat()<=d<stop.isoformat() and date.fromisoformat(d).weekday()<5][-args.sessions:]
        print("Observed dates:",json.dumps({k:len(v) for k,v in series.items()}),"Common reserved:",len(dates),flush=True)
        if len(dates)!=args.sessions:
            raise ValueError(f"Need {args.sessions} matched dates; have {len(dates)}. No silent smaller study.")
        ntrain,nval,_=SESSION_SPLITS[args.sessions]
        splits=(dates[:ntrain],dates[ntrain:ntrain+nval],dates[ntrain+nval:])
        report=cross.assess(series,splits,progress=lambda pct,msg:print(f"{pct}% {msg}",flush=True))
        report.update(source_hashes=sources,source_failures=failures,observed_dates={k:len(v) for k,v in series.items()})
        root=Path("results");root.mkdir(exist_ok=True)
        dest=root/("cross_index_"+uuid.uuid4().hex+".json")
        tmp=dest.with_suffix(".tmp")
        try:
            with tmp.open("x",encoding="utf-8") as f:json.dump(report,f,indent=2,sort_keys=True,allow_nan=False)
            os.replace(tmp,dest)
        finally:tmp.unlink(missing_ok=True)
        for target,part in report["targets"].items():
            for horizon,item in part["horizons"].items():
                print(target,"peer",part["peer"],"horizon",horizon,"coverage",json.dumps(item["coverage"]))
                for task,change in item["comparisons"].items():
                    base=item["matched_baseline"]["tasks"][task]
                    aug=item["matched_augmented"]["tasks"][task]
                    baseline=base["holdout"][base["selected_on_validation"]]
                    augmented=aug["holdout"][aug["selected_on_validation"]]
                    print(task,json.dumps({"baseline_model":base["selected_on_validation"],"augmented_model":aug["selected_on_validation"],
                        "baseline_brier":baseline["brier"],"augmented_brier":augmented["brier"],
                        "baseline_accuracy":baseline["accuracy"],"augmented_accuracy":augmented["accuracy"],
                        "augmented_observed":augmented["observed"],"paired_difference":change,
                        "augmented_minus_prior":aug["selected_minus_prior"]}))
        print("Report:",dest.resolve())
        print("No provider requests or orders. No option profitability certification.")
        return 0
    except (ValueError,RuntimeError,OSError) as exc:
        print("Cross-index study unavailable:",str(exc)[:240])
        return 2


if __name__=="__main__":
    raise SystemExit(main())
