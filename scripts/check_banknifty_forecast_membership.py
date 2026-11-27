"""Audit the exact prior forecasting partitions against locally saved membership and candles."""
import argparse
from datetime import date
import json
from pathlib import Path
import numpy as np
from workstation_api import banknifty_forecast_features as f, service


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report",type=Path,required=True,help="Existing forecast JSON, not prediction CSV")
    ap.add_argument("--shared-root",type=Path,default=service.ROOT)
    args=ap.parse_args()
    try:
        root=args.shared_root.resolve()
        if not (root/"data").is_dir():raise ValueError("Original shared data missing")
        service.DATA=root/"data"
        path=args.report if args.report.is_absolute() else root/args.report
        report=json.loads(path.read_text(encoding="utf-8"))
        start,stop=map(date.fromisoformat,(report["from_inclusive"],report["to_exclusive"]))
        parts={k:report[k+"_dates"] for k in ("training","validation","evaluation")}
        dates=[d for part in parts.values() for d in part]
        if len(dates)>400 or dates!=sorted(set(dates)) or any(not start<=date.fromisoformat(d)<stop for d in dates):
            raise ValueError("Invalid prior study dates")
        stocks,membership,weights,meta=f.load_membership(dates,start,stop,progress=lambda s:print(s,flush=True))
        print("PINNED BATCHES",json.dumps(meta["batches"]))
        print("REJECTED BATCHES",json.dumps(meta["rejected_batches"]))
        print("FALLBACK",json.dumps(meta["membership_fallback"]))
        print("SOURCE FAILURES",json.dumps(meta["failures"]))
        print("VERIFIED STOCK SOURCES",len(meta["source_hashes"]))
        for name,days in parts.items():
            available=[];partial=[];missing=[]
            for d in days:
                members=membership.get(d)
                if not members:
                    missing.append(d);continue
                count=np.zeros(f.MINUTES,dtype=int)
                for identity in members.values():
                    a=stocks.get(identity,{}).get(d)
                    if a is not None:count+=np.isfinite(a[:,:4]).all(axis=1)
                fraction=count/len(members)
                if np.mean(fraction>=.8)>=.8:available.append(d)
                else:partial.append(d)
            print("PARTITION",name,json.dumps({"sessions":len(days),
                "dated_membership_days":sum(d in membership for d in days),
                "at_least_80pct_members_on_80pct_minutes_days":len(available),
                "insufficient_stock_candle_dates":partial,
                "missing_membership_dates":missing,
                "dated_weight_days":sum(d in weights for d in days)}))
        print("AUDIT COMPLETE; no model training, downloads or data mutation")
        return 0
    except (OSError,ValueError,TypeError,KeyError,RuntimeError) as exc:
        print("Membership audit unavailable:",str(exc)[:240]);return 2


if __name__=="__main__":
    raise SystemExit(main())
