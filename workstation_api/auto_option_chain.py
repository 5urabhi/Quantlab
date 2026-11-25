"""Automatic source-only BANKNIFTY option-chain snapshots for all listed expiries.

After the user arms QuantLab's read-only CE/PE recorder once, this worker
captures Dhan's *complete returned chain* for every reported active expiry.
It uses the existing option_chain_observations table in dhan_shared, not a
second dataset. The nearest expiries are polled more often; far expiries are
sampled less often to avoid exhausting provider quotas or local disk.

No broker order endpoints, synthetic quotes, historical depth backfills,
or unapproved authentication flows are used.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
from threading import Event, RLock, Thread
import fcntl
import os
import sqlite3
import time

from . import auto_option_depth, dhan_session_maintenance, option_chain_live, shared_market_data

LOCK = RLock()
STOP = Event()
WORKER: Thread | None = None
RESTART_PENDING = False
SHUTTING_DOWN = False
MAX_DAILY_SNAPSHOTS = None  # Disk-aware, not count-limited.
DISCOVERY_INTERVAL_SECONDS = 300
STATE = {
    "state": "disabled", "snapshot_count_session": 0,
    "snapshots_saved_today": 0, "expiries_found": 0,
    "expiries_captured_session": 0, "last_expiry": None,
    "last_snapshot_utc": None, "last_quote_count": 0,
    "last_strike_count": 0, "last_error": None,
    "token_maintenance": "not_authorized",
    "token_maintenance_message": None,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _enabled() -> bool:
    # Existing explicit read-only subscription consent governs both collectors.
    return bool(auto_option_depth._config()["enabled"])


def _market_open() -> bool:
    return auto_option_depth._market_open()


def _period(index: int) -> int:
    """Prioritize complete Dhan chain coverage at the near expiries."""
    if index == 0:
        return 30
    if index == 1:
        return 60
    if index < 6:
        return 300
    return 1800


def _choose_due(expiries: list[str], due: dict[str, float],
                now: float) -> str | None:
    """Prioritize overdue near expiries even during a large initial backfill."""
    eligible = [(i, expiry) for i, expiry in enumerate(expiries)
                if due.get(expiry, 0.0) <= now]
    if not eligible:
        return None
    return max(eligible, key=lambda pair: (
        (now - due.get(pair[1], 0.0)) / _period(pair[0]),
        -pair[0]))[1]


def _daily_total() -> int:
    path = shared_market_data.database_path()
    if not path.is_file():
        return 0
    today = _now().astimezone(auto_option_depth.IST).date()
    start = datetime.combine(today, datetime.min.time(),
                             tzinfo=auto_option_depth.IST).astimezone(timezone.utc)
    end = (start.astimezone(auto_option_depth.IST) +
           timedelta(days=1)).astimezone(timezone.utc)
    try:
        with sqlite3.connect(path, timeout=5) as db:
            result = db.execute(
                "SELECT COUNT(*) FROM option_chain_observations "
                "WHERE underlying='BANKNIFTY' AND captured_utc>=? AND captured_utc<?",
                (start.isoformat(), end.isoformat())).fetchone()
            return int(result[0]) if result else 0
    except sqlite3.OperationalError as exc:
        # Missing new table before the very first original chain sample.
        if "no such table" in str(exc):
            return 0
        raise


def _status(**updates) -> None:
    with LOCK:
        STATE.update(updates)


def status() -> dict:
    with LOCK:
        snapshot = dict(STATE)
    return {**snapshot,
            "storage_health": auto_option_depth.recorder_storage.status("option_chain"),
            "armed": _enabled(), "market_regular_hours": _market_open(),
            "token_renewal_opted_in": bool(auto_option_depth._config().get("allow_token_renewal")),
            "read_only": True, "shared_library": shared_market_data.SHARED_ID,
            "depth_all_contracts": False,
            "capture_schedule_seconds": {"nearest": 30,
                                         "second": 60,
                                         "next_four": 300,
                                         "remaining": 1800},
            "note": "Every strike returned by Dhan for each discovered expiry "
                    "is saved as a timestamped REST snapshot. This is not "
                    "tick-by-tick option history or market-depth for every strike."}


def _run(stop: Event) -> None:
    root = auto_option_depth._root()
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / "auto_banknifty_chains.lock"
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            _status(state="other_local_worker", last_error=
                    "Another local QuantLab process already collects option chains.")
            return
        schedule: dict[str, float] = {}
        captured: set[str] = set()
        expiries: list[str] = []
        next_discovery = 0.0
        current_day = ""
        master_ready_today = False
        failures = 0
        next_token_check = 0.0
        while not stop.is_set():
            if not _enabled():
                _status(state="disabled", last_error=None)
                stop.wait(10)
                continue
            # Token checks also run overnight. An eligible token can be renewed
            # before the next market open, but only after separate opt-in.
            if time.monotonic() >= next_token_check:
                try:
                    auth = dhan_session_maintenance.maintain()
                    _status(token_maintenance=auth["state"],
                            token_maintenance_message=auth["message"])
                except (OSError, ValueError, TypeError, sqlite3.Error):
                    _status(token_maintenance="maintenance_unavailable",
                            token_maintenance_message=
                            "Dhan renewal maintenance could not complete safely.")
                next_token_check = time.monotonic() + 900
            if not _market_open():
                _status(state="armed_waiting_for_nse_hours")
                stop.wait(20)
                continue
            if not os.getenv("DHAN_ACCESS_TOKEN", "").strip():
                _status(state="token_needed", last_error=
                        "Dhan needs an authorized access token in local Connections.")
                stop.wait(30)
                continue
            day = _now().astimezone(auto_option_depth.IST).date().isoformat()
            if day != current_day:
                current_day = day
                master_ready_today = False
                captured.clear()
                schedule.clear()
                expiries.clear()
                next_discovery = 0.0
                _status(expiries_captured_session=0, snapshot_count_session=0,
                        snapshots_saved_today=0, last_error=None)
            if not master_ready_today:
                try:
                    # Same official atomic refresh used by the depth worker;
                    # never leave new expiry/lot mappings for manual repair.
                    auto_option_depth._refresh_master_if_needed()
                    master_ready_today = True
                except (OSError, ValueError, sqlite3.Error):
                    _status(state="master_unavailable", last_error=
                            "Automatic Dhan instrument-master validation failed; retrying.")
                    stop.wait(30)
                    continue
            now = time.monotonic()
            if now >= next_discovery or not expiries:
                try:
                    found = option_chain_live.expiries()["expiries"]
                    if not found:
                        raise ValueError("Empty Dhan BANKNIFTY expiry list")
                    expiries = found
                    schedule = {k: v for k, v in schedule.items() if k in expiries}
                    next_discovery = time.monotonic() + DISCOVERY_INTERVAL_SECONDS
                    _status(expiries_found=len(expiries), last_error=None)
                    failures = 0
                except (ValueError, OSError, sqlite3.Error, TypeError, KeyError) as exc:
                    failures += 1
                    _status(state="source_unavailable",
                            last_error="Option expiry discovery failed (" +
                            type(exc).__name__ + "). Check Dhan token or connectivity.")
                    stop.wait(min(120, 10 * failures))
                    continue
            try:
                total = _daily_total()
            except sqlite3.Error:
                _status(state="storage_unavailable", last_error=
                        "Local market database cannot be inspected safely.")
                stop.wait(30)
                continue
            _status(snapshots_saved_today=total)
            if not auto_option_depth.recorder_storage.allow("option_chain"):
                _status(state="storage_paused_disk_reserve", last_error="Disk safety reserve reached; coverage gap")
                stop.wait(60)
                continue
            expiry = _choose_due(expiries, schedule, time.monotonic())
            if expiry is None:
                nearest = min(schedule.values()) if schedule else time.monotonic()+30
                stop.wait(max(1, min(30, nearest - time.monotonic())))
                continue
            rank = expiries.index(expiry)
            # Schedule retries separately; failed source observations are not fabricated.
            schedule[expiry] = time.monotonic() + _period(rank)
            if not _enabled() or stop.is_set() or not _market_open():
                continue
            _status(state="collecting_original_chains")
            try:
                result = option_chain_live.chain(expiry, force_refresh=True)
                quote_count = int(result["quote_count"])
                if quote_count <= 0:
                    raise ValueError("Empty authenticated contract snapshot")
                if result.get("storage_result") == "disk_paused":
                    _status(state="storage_paused_disk_reserve", last_error="Snapshot received but not stored")
                    continue
                captured.add(expiry)
                _status(state="recording_original_chains",
                        last_error=None, last_expiry=expiry,
                        last_snapshot_utc=result["received_utc"],
                        last_quote_count=quote_count,
                        last_strike_count=int(result.get("strike_count", 0)),
                        expiries_captured_session=len(captured),
                        snapshot_count_session=STATE["snapshot_count_session"]+1)
                failures = 0
            except (ValueError, OSError, sqlite3.Error, TypeError, KeyError) as exc:
                failures += 1
                _status(state="source_unavailable",
                        last_error="Original Dhan chain capture failed (" +
                        type(exc).__name__ + "); retrying without guessing prices.")
                schedule[expiry] = time.monotonic() + min(300, 20 * failures)
                stop.wait(min(30, 5 * failures))
    finally:
        _status(state="stopped", last_error=None)
        os.close(fd)


def _restart_after_stopped(previous: Thread) -> None:
    global RESTART_PENDING
    previous.join()
    with LOCK:
        RESTART_PENDING = False
    if not SHUTTING_DOWN and _enabled():
        resume_if_armed()


def resume_if_armed() -> None:
    """Start on app startup after previously stored consent, or on explicit arm."""
    global WORKER, STOP, SHUTTING_DOWN, RESTART_PENDING
    if not _enabled():
        return
    with LOCK:
        SHUTTING_DOWN = False
        if WORKER is not None and WORKER.is_alive():
            if STOP.is_set() and not RESTART_PENDING:
                RESTART_PENDING = True
                Thread(target=_restart_after_stopped, args=(WORKER,),
                       daemon=True, name="quantlab-auto-chain-restart").start()
            return
        STOP = Event()
        WORKER = Thread(target=_run, args=(STOP,), daemon=True,
                        name="quantlab-banknifty-option-chain")
        WORKER.start()


def disarmed() -> None:
    """Disarming depth also stops subsequent option-chain HTTP captures."""
    _status(state="disabled")


def suspend_for_shutdown() -> None:
    global SHUTTING_DOWN
    SHUTTING_DOWN = True
    STOP.set()
    _status(state="stopped")
