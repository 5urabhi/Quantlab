"""Quick standalone next-candle forecast research on saved original index bars."""
from datetime import datetime,timedelta,timezone,date
from pathlib import Path
import argparse
import json
import os
import uuid

from workstation_api import candle_pattern_research as patterns, historical_alpha as h, alpha_retraining


def main():
    today=datetime.now(h.IST).date()
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-date",default=(today-timedelta(days=100)).isoformat())
    parser.add_argument("--to-date",default=today.isoformat())
    a=parser.parse_args()
    try:
        start,stop=map(date.fromisoformat,(a.from_date,a.to_date))
        if not 0<(stop-start).days<=120 or stop>today or not alpha_retraining.safe_window(datetime.now(timezone.utc)):
            raise ValueError("Use a completed range up to 120 days, outside Indian market priority hours")
        index,hashes,failures=h.shared_index_sources(start,stop,[h.MAX_TOTAL])
        dates=[d for d in sorted(index) if start.isoformat()<=d<stop.isoformat() and date.fromisoformat(d).weekday()<5][-60:]
        if len(dates)<60:
            raise ValueError("Need 60 reserved observed sessions for 30/10/20 comparison")
        splits=(dates[:30],dates[30:40],dates[40:])
        report=patterns.assess(index,splits,progress=lambda _,msg:print(msg,flush=True))
        report.update(training_dates=splits[0],validation_dates=splits[1],holdout_dates=splits[2],
                      source_hashes=hashes,source_failures=failures)
        root=Path("results");root.mkdir(exist_ok=True)
        dest=root/("candle_patterns_"+uuid.uuid4().hex+".json")
        temp=dest.with_suffix(".tmp")
        try:
            with temp.open("x",encoding="utf-8") as file:
                json.dump(report,file,indent=2,sort_keys=True,allow_nan=False)
            os.replace(temp,dest)
        finally:
            temp.unlink(missing_ok=True)
        for horizon,item in report["horizons"].items():
            print("Horizon:",horizon,json.dumps({k:v for k,v in item.items() if k!="pattern_library"}))
            print("Holdout pattern outcomes:",json.dumps(item["pattern_library"]["holdout"]))
        print("Report:",dest.resolve())
        print("Exploratory direction forecasts, not verified execution or profits.")
        return 0
    except (ValueError,RuntimeError,OSError) as exc:
        print("Candle research unavailable:",str(exc)[:200])
        return 2


if __name__=="__main__":
    raise SystemExit(main())
