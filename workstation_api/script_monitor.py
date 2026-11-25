"""Opt-in local script monitoring. No broker calls, orders or fabricated data.

One low-frequency worker reads saved observations, runs immutable revisions in
the existing sandbox and replaces only its own latest result. Every monitor
starts disabled after a server restart; enabling is an explicit session action.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone, timedelta
from hashlib import sha256
from threading import Event, RLock, Thread
from zoneinfo import ZoneInfo
import json
import math
import sqlite3
import uuid

from . import user_scripts as library, python_strategy_sandbox as sandbox
from . import live_market, shared_market_data, trading_cockpit

LOCK = RLock()
STOP = Event()
WORKER = None
IST = ZoneInfo("Asia/Kolkata")
SOURCES = {"index_minutes", "option_chain", "chain_spot_receipts"}
COMPATIBLE = {"index_minutes": {"strategy","indicator","chart","research","model","risk","transform"},
              "option_chain": {"scanner","indicator","chart","research","model","risk","transform"},
              "chain_spot_receipts": {"indicator","chart","research","model","risk","transform"}}
MAX_ENABLED = 4
MAX_MONITORS = 100


def _now():
    return datetime.now(timezone.utc)


def _stamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _regular(now):
    t = now.astimezone(IST)
    return t.weekday() < 5 and (9,15) <= (t.hour,t.minute) < (15,30)


def _fresh(stamp, now, min_age, max_age):
    try:
        age = (now - _stamp(stamp)).total_seconds()
        return min_age <= age <= max_age and _stamp(stamp).astimezone(IST).date() == now.astimezone(IST).date()
    except (ValueError, TypeError, AttributeError):
        return False


def _json_row(row):
    out = dict(row)
    out["enabled"] = bool(out["enabled"])
    out["output"] = json.loads(out["output"]) if out["output"] else None
    return out


def list_monitors():
    with closing(library._connect()) as db:
        rows = db.execute("""SELECT m.*, v.name, v.kind, v.source_sha256
            FROM script_monitors m JOIN versions v ON m.script_id=v.script_id
            AND m.revision=v.revision ORDER BY m.created_utc DESC""")
        return [_json_row(r) for r in rows]


def register(*, script_id, revision, source, profile):
    item = library.read_script(script_id, revision)
    if source not in COMPATIBLE or item["kind"] not in COMPATIBLE[source]:
        raise ValueError("This script category does not support that source")
    if profile not in sandbox.PROFILES:
        raise ValueError("Invalid Python profile")
    if not sandbox.availability()["available"]:
        raise ValueError("Isolated Python runner unavailable")
    with closing(library._connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT count(*) FROM script_monitors").fetchone()[0] >= MAX_MONITORS:
            raise ValueError("Monitor library is full")
        if db.execute("SELECT count(*) FROM script_monitors WHERE enabled=1").fetchone()[0] >= MAX_ENABLED:
            raise ValueError("At most four enabled script monitors")
        ident = uuid.uuid4().hex
        db.execute("""INSERT INTO script_monitors
            (id,script_id,revision,source,profile,enabled,created_utc,state)
            VALUES(?,?,?,?,?,1,?,'waiting_for_new_observation')""",
            (ident,script_id,revision,source,profile,_now().isoformat()))
    return next(r for r in list_monitors() if r["id"] == ident)


def set_enabled(ident, enabled):
    if not library.ID.fullmatch(ident):
        raise ValueError("Invalid monitor ID")
    with closing(library._connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        current = db.execute("SELECT enabled FROM script_monitors WHERE id=?", (ident,)).fetchone()
        if current is None:
            raise ValueError("Monitor not found")
        if enabled and not current["enabled"]:
            if not sandbox.availability()["available"]:
                raise ValueError("Isolated Python runner unavailable")
            if db.execute("SELECT count(*) FROM script_monitors WHERE enabled=1").fetchone()[0] >= MAX_ENABLED:
                raise ValueError("At most four enabled script monitors")
        db.execute("UPDATE script_monitors SET enabled=?,state=?,message=NULL WHERE id=?",
                   (int(enabled),"waiting_for_new_observation" if enabled else "paused",ident))
    return next(r for r in list_monitors() if r["id"] == ident)


def remove(ident):
    if not library.ID.fullmatch(ident):
        raise ValueError("Invalid monitor ID")
    with closing(library._connect()) as db, db:
        if not db.execute("DELETE FROM script_monitors WHERE id=? AND enabled=0",(ident,)).rowcount:
            raise ValueError("Pause the monitor before removing it")
    return {"removed":ident}


def _chain_rows(now, limit=1, *, recent=True):
    path = shared_market_data.database_path()
    if not path.is_file() or path.is_symlink():
        return []
    try:
        with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro", uri=True, timeout=2)) as db:
            # Choose the nearest currently valid expiry that has a saved recent
            # receipt. Never switch expiry within a time series.
            if recent:
                expiry = db.execute("""SELECT expiry FROM option_chain_observations
                    WHERE underlying='BANKNIFTY' AND expiry>=? AND captured_utc>=?
                    ORDER BY expiry LIMIT 1""",
                    (now.astimezone(IST).date().isoformat(),
                     (now-timedelta(seconds=120)).isoformat())).fetchone()
                cutoff = (now-timedelta(hours=7)).isoformat()
            else:
                # Historical viewing is allowed with the source time visible.
                # Do not reuse a previous session to drive a running monitor.
                latest = db.execute("""SELECT expiry,captured_utc FROM option_chain_observations
                    WHERE underlying='BANKNIFTY' ORDER BY captured_utc DESC LIMIT 1""").fetchone()
                expiry = (latest[0],) if latest else None
                cutoff = (_stamp(latest[1])-timedelta(hours=7)).isoformat() if latest else ""
            if not expiry:
                return []
            rows = db.execute("""SELECT captured_utc,snapshot_sha256,normalized_json
                FROM option_chain_observations WHERE underlying='BANKNIFTY' AND expiry=?
                AND captured_utc>=? ORDER BY captured_utc DESC LIMIT ?""",
                (expiry[0],cutoff,limit)).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return []
        raise
    result = []
    for stamp,digest,raw in reversed(rows):
        if len(raw) > 8_000_000 or sha256(raw.encode()).hexdigest() != digest:
            raise ValueError("Saved chain receipt integrity check failed")
        data = json.loads(raw)
        if data.get("received_utc") != stamp or data.get("underlying") != "BANKNIFTY" or data.get("expiry") != expiry[0]:
            raise ValueError("Saved chain receipt metadata mismatch")
        result.append((stamp,digest,data))
    return result


def source_snapshot(source, now=None):
    now = now or _now()
    if not _regular(now):
        return None
    if source == "index_minutes":
        raw = live_market.minute_series("INDEX:BANKNIFTY", limit=500)
        bars = trading_cockpit._validated(raw["rows"])
        if not bars or not _fresh(bars[-1]["timestamp_utc"],now,60,150):
            return None
        bars = trading_cockpit._continuous_session_tail(bars)[-150:]
        if len(bars) < 2:
            return None
        stamp = bars[-1]["timestamp_utc"]
        snap = {"title":"BANKNIFTY recorded completed index minutes",
                "provenance":"Recorded Dhan index LTP aggregates; no authenticated volume",
                "columns":["Time (UTC)","Open (points)","High (points)","Low (points)","Close (points)"],
                "rows":[[b["timestamp_utc"],b["open"],b["high"],b["low"],b["close"]] for b in bars]}
        return stamp,stamp,snap,bars
    if source not in SOURCES:
        raise ValueError("Unknown source")
    receipts = _chain_rows(now, 150 if source=="chain_spot_receipts" else 1)
    if not receipts or not _fresh(receipts[-1][0],now,0,120):
        return None
    stamp,digest,data = receipts[-1]
    if source == "chain_spot_receipts":
        points = [[t, d.get("underlying_spot")] for t,_,d in receipts
                  if _fresh(t,now,0,7*3600) and isinstance(d.get("underlying_spot"),(float,int))
                  and math.isfinite(d["underlying_spot"])]
        if len(points) < 2:
            return None
        snap = {"title":"BANKNIFTY underlying spot at recorded chain receipts",
                "provenance":"Original Dhan REST receipts; irregular local receipt times, not OHLC or streaming index ticks",
                "columns":["Receipt time (UTC)","Underlying spot (points)"],"rows":points}
    else:
        # Exact contract IDs (not duplicated CE/PE strikes) identify scores.
        rows = [[c["identity"],c["strike"],c["option_type"],c.get("ltp"),c.get("bid"),c.get("ask"),
                 c.get("oi"),c.get("volume"),c.get("iv"),c.get("delta"),c.get("lot_size")]
                for c in data.get("contracts",[]) if c.get("identity") and c.get("contract_master_verified")]
        if not rows:
            return None
        rows = rows[:library.MAX_ROWS]
        snap = {"title":"BANKNIFTY nearest saved chain "+data["expiry"],
                "provenance":"Dhan REST saved receipt "+stamp+"; not executable fills",
                "columns":["Contract ID","Strike (points)","Side","LTP (INR)","Bid (INR)","Ask (INR)",
                           "OI (provider units)","Volume (provider units)","IV (%)","Delta","Lot size"],"rows":rows}
    return stamp+":"+digest,stamp,snap,None


def _evaluate(row, snap, bars):
    script = library.read_script(row["script_id"],row["revision"])
    if script["kind"] == "strategy":
        if not bars:
            raise ValueError("Strategies require actual completed index minutes")
        decisions,meta = sandbox.run_python(script["code"],bars,row["profile"])
        return {"signal":decisions[-1],"source_sha256":meta["source_sha256"],
                "note":"Custom research signal on completed observed index minutes; no order or fill"}
    output = library.run_chart(code=script["code"],snapshot=snap,profile=row["profile"],kind=script["kind"],persist=False)
    output["warning"] = "Saved source observations; custom result is unvalidated research, not broker execution."
    return output


def _update(ident, state, message=None, key=None, stamp=None, output=None):
    with closing(library._connect()) as db, db:
        if key is None:
            db.execute("UPDATE script_monitors SET state=?,message=? WHERE id=? AND enabled=1",
                       (state,message,ident))
        else:
            db.execute("""UPDATE script_monitors SET state=?,message=?,last_key=?,last_utc=?,output=?
                       WHERE id=? AND enabled=1""",
                       (state,message,key,stamp,json.dumps(output,allow_nan=False) if output is not None else None,ident))


def cycle():
    if not library._db_path().is_file():
        return
    cache = {}
    for row in list_monitors():
        if STOP.is_set():
            break
        if not row["enabled"]:
            continue
        key = stamp = None
        try:
            if row["source"] not in cache:
                cache[row["source"]] = source_snapshot(row["source"])
            packet = cache[row["source"]]
            if packet is None:
                _update(row["id"],"waiting_for_fresh_source","No new fresh recorded source; previous output is not current")
                continue
            key,stamp,snap,bars = packet
            if key == row["last_key"]:
                if row['output'] is not None and row['state'] != 'complete':
                    _update(row['id'],'complete')
                continue
            _update(row["id"],"running")
            output = _evaluate(row,snap,bars)
            _update(row["id"],"complete",key=key,stamp=stamp,output=output)
        except Exception as exc:
            # Do not log code, source rows or exception text. A failing revision
            # cannot trigger repeated computation on the same receipt.
            _update(row["id"],"error",type(exc).__name__,key=key,stamp=stamp)


def _loop():
    while not STOP.wait(5):
        try:
            cycle()
        except (OSError,sqlite3.Error,ValueError):
            STOP.wait(10)


def start():
    global WORKER
    with LOCK:
        if WORKER and WORKER.is_alive():
            if not STOP.is_set():
                return
            WORKER.join(timeout=2)
            if WORKER.is_alive():
                return
        # No automatic execution of user code following a server restart.
        # Do not touch data directories at application startup unless the
        # script library already exists.
        if library._db_path().is_file():
            with closing(library._connect()) as db, db:
                db.execute("UPDATE script_monitors SET enabled=0,state='paused_after_restart' WHERE enabled=1")
        STOP.clear()
        WORKER = Thread(target=_loop,name="quantlab-script-monitor",daemon=True)
        WORKER.start()


def stop():
    STOP.set()
    if WORKER and WORKER.is_alive():
        WORKER.join(timeout=1)
