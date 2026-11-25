"""Shared capacity guard and independent persistence diagnostics.

The original source database is never deleted or silently pruned. A disk
pause or write error is an explicit coverage gap, not a market observation.
"""
from datetime import datetime, timezone
import json
import os
import shutil
import time
from threading import RLock
from . import shared_market_data

LOCK = RLock()
STATE = {}
CACHE = {}
CHECK_SECONDS = 5


def _stamp():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _path():
    return shared_market_data.database_path()


def _capacity():
    parent = _path().parent
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    usage = shutil.disk_usage(parent)
    reserve = min(10 * 1024**3, max(512 * 1024**2, int(usage.total * .03)))
    return usage.free > reserve, usage.free, reserve


def _state(stream):
    return STATE.setdefault((str(_path()), stream), {
        "state": "not_observed", "saved": 0, "dropped": 0,
        "gap_count": 0, "gap_started_utc": None, "last_saved_utc": None,
        "last_drop_utc": None, "last_error": None, "ledger_error": False})


def _transition(stream, state, reason):
    """Log only transitions, avoiding per-packet disk/error-log storms."""
    try:
        target = _path().parent / "recorder_storage_gaps.jsonl"
        target.parent.mkdir(parents=True, exist_ok=True)
        event = {"stream": stream, "utc": _stamp(), "state": state,
                 "reason": reason}
        with target.open("a", encoding="utf-8") as fd:
            fd.write(json.dumps(event, sort_keys=True) + "\n")
    except OSError:
        _state(stream)["ledger_error"] = True


def failure(stream, reason, *, dropped=0):
    with LOCK:
        row = _state(stream)
        previous = row["state"]
        if row["gap_started_utc"] is None:
            row["gap_started_utc"] = _stamp()
            row["gap_count"] += 1
        row.update(state="paused" if reason=="disk_reserve" else "write_error",
                   last_error=reason)
        if dropped:
            row["dropped"] += dropped
            row["last_drop_utc"] = _stamp()
        if row["state"] != previous:
            _transition(stream, row["state"], reason)


def allow(stream, *, dropped=0):
    with LOCK:
        key = str(_path())
        now = time.monotonic()
        prior = CACHE.get(key)
        if prior is None or now-prior[0]>=CHECK_SECONDS:
            try:
                safe, free, reserve = _capacity()
                prior = (now, safe, free, reserve, None)
            except OSError:
                prior = (now, False, None, None, "capacity_check_failed")
            CACHE.clear()
            CACHE[key] = prior
        if not prior[1]:
            failure(stream, prior[4] or "disk_reserve", dropped=dropped)
            return False
        return True


def saved(stream, stamp, count=1):
    with LOCK:
        row = _state(stream)
        if row["gap_started_utc"] is not None:
            _transition(stream, "resumed", "subsequent_original_write_committed")
        row.update(state="recording", gap_started_utc=None, last_saved_utc=stamp,
                   last_error=None)
        row["saved"] += count


def status(stream):
    with LOCK:
        row = dict(_state(stream))
        capacity = CACHE.get(str(_path()))
        return {**row, "fixed_row_limit": None,
                "free_bytes": capacity[2] if capacity else None,
                "reserve_bytes": capacity[3] if capacity else None,
                "coverage_complete": None,
                "note": "Process-local counts; skipped or paused intervals remain missing. "
                        "Capacity and receipt delivery are separate from successful writes."}
