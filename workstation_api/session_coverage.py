"""Reviewed NSE-session calendar audit using actual canonical scalar records.

No weekday/holiday guess, no invented subscriptions, no deletion or provider IO.
The submitted calendar must cover every date in the chosen interval explicitly.
Only a separately affirmed tracking expectation permits a missing-session label.
"""
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
import csv
import io
import sqlite3
import time as clock
from . import live_market, market_inventory as inv, shared_market_data

SOURCES={"daily_closes","live_ticks","live_minute_bars","constituent_quotes","option_quote","option_oi","option_chain","live_depth_books","depth_features"}

def audit(source,identity,start,end,calendar_csv,source_label,confirm_reviewed,expect_recording,qualifier=""):
    if source not in SOURCES or not isinstance(identity,str) or not 1<=len(identity)<=160 or len(qualifier)>180:
        raise ValueError("Choose one exact canonical source and recorded or expected instrument identity")
    if confirm_reviewed is not True or not isinstance(source_label,str) or not 3<=len(source_label.strip())<=300 or not isinstance(calendar_csv,str) or len(calendar_csv)>20000:
        raise ValueError("Provide reviewed calendar CSV and its source reference")
    first,last=date.fromisoformat(start),date.fromisoformat(end)
    if not 0<=(last-first).days<90 or last==date.max:
        raise ValueError("Choose an inclusive 1–90 day window")
    reader=csv.DictReader(io.StringIO(calendar_csv.strip()))
    if reader.fieldnames!=["session_date","state"]:
        raise ValueError("CSV columns must be session_date,state with OPEN or CLOSED")
    days={}
    for row in reader:
        if None in row:
            raise ValueError("Invalid calendar row")
        day=date.fromisoformat(row["session_date"])
        state=row["state"]
        if day in days or state not in {"OPEN","CLOSED"}:
            raise ValueError("Duplicate date or unreviewed session state")
        days[day]=state
    expected=[first+timedelta(days=i) for i in range((last-first).days+1)]
    if set(days)!=set(expected):
        raise ValueError("Reviewed calendar must explicitly cover every requested date exactly once")
    table,ident,stamp,condition,extra=inv.SQL[source]
    if extra and not qualifier:
        raise ValueError("Choose the exact saved expiry qualifier")
    if not extra and qualifier:
        raise ValueError("Unexpected qualifier for selected source")
    path=shared_market_data.database_path()
    rows=[]
    complete=False
    if inv._safe_file(path):
        try:
            with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=.5)) as db:
                db.execute("PRAGMA query_only=ON")
                db.execute("PRAGMA trusted_schema=OFF")
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():
                    deadline=clock.monotonic()+2.5
                    db.set_progress_handler(lambda:int(clock.monotonic()>deadline),5000)
                    db.execute("BEGIN")
                    for day in expected:
                        nxt=day+timedelta(days=1)
                        if source=="daily_closes":
                            lo,hi=day.isoformat(),nxt.isoformat()
                        else:
                            lo=datetime.combine(day,time.min,tzinfo=live_market.IST).astimezone(timezone.utc).isoformat(timespec="seconds")
                            hi=datetime.combine(nxt,time.min,tzinfo=live_market.IST).astimezone(timezone.utc).isoformat(timespec="seconds")
                        # ISO writers use UTC offsets; whole calendar-day comparisons
                        # include any fractional second formatting at the boundary.
                        predicates=[ident+"=?",stamp+">=?",stamp+"<?"]
                        args=[identity,lo,hi]
                        if condition:
                            predicates.append(condition.removeprefix("WHERE "))
                        if extra:
                            predicates.append(extra+"=?");args.append(qualifier)
                        count=db.execute("SELECT COUNT(*) FROM "+table+" WHERE "+" AND ".join(predicates),args).fetchone()[0]
                        rows.append((day,count))
                    complete=True
        except (sqlite3.Error,OSError,ValueError):
            rows=[]
    counts=dict(rows) if complete else {}
    output=[]
    for day in expected:
        count=counts.get(day)
        state=days[day]
        # Never mark today's unfinished session or a future session missing.
        past=day<datetime.now(live_market.IST).date()
        if count is None:
            verdict="NOT_VERIFIED"
        elif state=="CLOSED":
            verdict="CLOSED_WITH_RECORDS" if count else "CLOSED"
        elif count:
            verdict="OBSERVED"
        elif not past:
            verdict="SESSION_NOT_FINAL"
        elif expect_recording is True:
            verdict="MISSING_EXPECTED_SESSION"
        else:
            verdict="NO_RECORDS_EXPECTATION_UNCONFIRMED"
        output.append({"date":day.isoformat(),"calendar_state":state,"count":count,"verdict":verdict})
    return {"source":source,"identity":identity,"qualifier":qualifier,"start":start,"end":end,
            "source_label":source_label.strip(),"calendar_sha256":sha256(calendar_csv.encode()).hexdigest(),
            "read_complete":complete,"expect_recording":expect_recording is True,"rows":output,
            "missing_expected_sessions":sum(r["verdict"]=="MISSING_EXPECTED_SESSION" for r in output) if complete else None,
            "note":"User-reviewed session schedule, not independently certified exchange calendar. Counts use stored calendar dates (IST for UTC timestamp sources). OBSERVED proves at least one record, not intraday completeness. A missing session is only relative to the affirmed exact-instrument recording expectation."}
