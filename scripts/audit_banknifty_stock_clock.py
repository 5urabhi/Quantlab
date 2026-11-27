"""Read-only diagnosis of incomplete regular-session equity minute candles.

Uses saved source-verified BANKNIFTY index trading dates as the comparison
calendar, not assumed weekdays. No new provider calls or timestamp imputation.
"""
import argparse
from collections import Counter
from datetime import date
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

import pandas as pd

from workstation_api import dhan_workspace as dw, service, dhan_checkpoint as cp
from workstation_api import verified_equity_context as ve
from scripts.prepare_banknifty_data import audit_index, say


def clock_summary(payload, days, rows):
    frame=pd.read_csv(BytesIO(payload),usecols=["datetime"])
    if len(frame)!=rows:raise ValueError("Original row count mismatch")
    clock=pd.to_datetime(frame["datetime"],utc=True,errors="raise").dt.tz_convert("Asia/Kolkata")
    if clock.isna().any() or clock.duplicated().any():raise ValueError("Missing or duplicate timestamps")
    day=clock.dt.strftime("%Y-%m-%d")
    minute=clock.dt.hour*60+clock.dt.minute
    relevant=day.isin(days)
    regular=(minute>=555)&(minute<930)
    aligned=(clock.dt.second==0)&(clock.dt.microsecond==0)&(clock.dt.nanosecond==0)
    exact=pd.DataFrame({"day":day,"minute":minute}).loc[relevant&regular&aligned]
    observed=exact.groupby("day")["minute"].agg(set).to_dict()
    any_rows=set(day[relevant])
    sizes=Counter()
    missing=Counter()
    examples=[]
    empty=[]
    for d in sorted(days):
        actual=observed.get(d,set())
        sizes[len(actual)]+=1
        if not actual:
            empty.append(d)
            continue
        absent=set(range(555,930))-actual
        if absent:
            missing.update(absent)
            if len(examples)<3:
                examples.append({"session":d,"exact_minutes":len(actual),"first":fmt(min(actual)),
                                 "last":fmt(max(actual)),"missing":[fmt(x) for x in sorted(absent)[:10]]})
    return {"expected_index_sessions":len(days),"sessions_with_any_raw_rows":len(any_rows),
            "complete_regular_sessions":sizes[375],"regular_minute_count_distribution":dict(sorted(sizes.items())),
            "raw_rows_in_range":int(relevant.sum()),"off_minute_grid_regular_rows":int((relevant&regular&~aligned).sum()),
            "outside_regular_hours_rows":int((relevant&~regular).sum()),
            "last_raw_session":max(any_rows) if any_rows else None,
            "last_complete_regular_session":max((d for d,v in observed.items() if len(v)==375),default=None),
            "most_frequent_missing_minutes_partial_sessions":[[fmt(k),v] for k,v in missing.most_common(8)],
            "zero_exact_minute_dates":empty,"partial_examples":examples}


def fmt(m):
    return f"{m//60:02d}:{m%60:02d}"


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--shared-root",type=Path,required=True)
    p.add_argument("--batch-id",required=True)
    p.add_argument("--from-date",type=date.fromisoformat,required=True)
    p.add_argument("--to-date",type=date.fromisoformat,required=True,help="Exclusive end")
    a=p.parse_args()
    if not 0<(a.to_date-a.from_date).days<=366:p.error("Use a bounded diagnostic interval of at most 366 days")
    service.DATA=a.shared_root.resolve()/"data"
    b=dw._load_batch(a.batch_id)
    if b.get("selection")!="banknifty_pit" or b.get("interval")!=1:
        p.error("Expected original BANKNIFTY minute batch")
    ix=audit_index("INDEX:BANKNIFTY",a.from_date,a.to_date)
    days=set(ix["complete_dates"])
    if not days:p.error("No verified complete BANKNIFTY sessions in interval")
    say("INDEX CALENDAR",{"sessions":len(days),"from":min(days),"through":max(days)})
    budget=ve.MAX_TOTAL_BYTES
    results={}
    for row in b["items"]:
        target=dw._history_file(row,1)
        try:
            if any(q.is_symlink() for q in (target,target.parent,target.parent.parent)):
                raise ValueError("Unsafe equity source path")
            receipt=cp._read_receipt(target.with_suffix(".json"),identity=row["id"],interval=1)
            size=target.stat().st_size
            if not 0<size<=ve.MAX_FILE_BYTES or size>budget:raise ValueError("Bounded source read exceeded")
            with target.open("rb") as fd:payload=fd.read(size+1)
            budget-=len(payload)
            if len(payload)!=size or sha256(payload).hexdigest()!=receipt["sha256"]:
                raise ValueError("Original SHA mismatch; retry audit after current writer completes")
            result=clock_summary(payload,days,receipt["rows"])
            result["sha256"]=receipt["sha256"]
            result["rejected_provider_bars"]=receipt.get("rejected_provider_bars",0)
        except (OSError,ValueError,TypeError,KeyError,OverflowError) as exc:
            result={"state":"unverified","reason":type(exc).__name__}
        results[row["symbol"]]=result
        say(row["symbol"],result)
    return 0 if all(v.get("state")!="unverified" for v in results.values()) else 2


if __name__=="__main__":
    raise SystemExit(main())
