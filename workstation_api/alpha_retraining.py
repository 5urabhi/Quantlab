"""Opt-in rolling research candidates on completed original ledger sessions.

No broker calls, historical reconstruction, model promotion or orders.
The original fixed-cohort research and its monitoring remain unchanged.
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone, time
from threading import Event, RLock, Thread
from zoneinfo import ZoneInfo
import json
import os
import uuid

import numpy as np

from . import (alpha_model_registry as registry, constituent_alpha as a,
               constituent_prospective as p, replay_storage, shared_market_data)

CADENCE = 5  # Additional observed, completed sessions before the next attempt.
MODELS = ("index_logistic", "constituent_logistic")
DEFAULT = {"enabled": False, "horizon": 15}
LOCK = RLock()
STOP = Event()
WAKE = Event()
THREAD = None
IST = ZoneInfo("Asia/Kolkata")


def _now():
    return datetime.now(timezone.utc)


def _path(name):
    return a._root() / ("rolling_retraining_" + name + ".json")


def _read(name, default):
    path = _path(name)
    if path.is_symlink():
        raise ValueError("Unsafe retraining state")
    if not path.exists():
        return default
    if path.stat().st_size > 512000:
        raise ValueError("Oversized retraining state")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Invalid retraining state")
    return data


def _write(name, data):
    path = _path(name)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Unsafe retraining state")
    tmp = path.with_name("." + uuid.uuid4().hex + ".tmp")
    try:
        with tmp.open("x", encoding="utf-8") as handle:
            json.dump(data, handle, sort_keys=True, allow_nan=False)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def config():
    with LOCK:
        cfg = _read("config", dict(DEFAULT))
    if (set(cfg) != set(DEFAULT) or type(cfg["enabled"]) is not bool
            or type(cfg["horizon"]) is not int or cfg["horizon"] not in a.HORIZONS):
        raise ValueError("Invalid rolling retraining settings")
    return cfg


def configure(*, enabled, horizon, confirm_local_research=False):
    if type(enabled) is not bool or type(horizon) is not int or horizon not in a.HORIZONS:
        raise ValueError("Invalid rolling retraining settings")
    if enabled and confirm_local_research is not True:
        raise ValueError("Authorize recurring local research first")
    with LOCK:
        _write("config", {"enabled": enabled, "horizon": horizon})
    WAKE.set()
    return status()


def safe_window(now):
    local = now.astimezone(IST)
    clock = local.time().replace(tzinfo=None)
    return local.weekday() >= 5 or clock < time(8, 30) or clock >= time(16)


def _recent_days(db, horizon, today):
    if not replay_storage.fetchone(db, "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (p.TABLE,)):
        return []
    rows = replay_storage.fetchall(db, """SELECT DISTINCT session_ist FROM banknifty_paired_signals
        WHERE protocol_hash=? AND horizon_minutes=? AND session_ist<?
        ORDER BY session_ist DESC LIMIT ?""",
        (p.protocol_for(horizon), horizon, today, sum(a.split_sizes(horizon))))
    return sorted(row[0] for row in rows)


def _latest(horizon, now):
    if not shared_market_data.database_path().is_file():
        return []
    today = p._session(now).date().isoformat()
    with closing(a._read()) as db:
        return _recent_days(db, horizon, today)


def _previous(horizon):
    with LOCK:
        return _read("state", {}).get(str(horizon), {})


def _record(horizon, report):
    with LOCK:
        state = _read("state", {})
        state[str(horizon)] = report
        _write("state", state)


def _due(days, previous, required):
    if len(days) != required:
        return False
    last = previous.get("window_end")
    return last is None or sum(day > last for day in days) >= CADENCE


def status(*, now=None):
    now = now or _now()
    cfg = config()
    previous = _previous(cfg["horizon"])
    return {"config": cfg, "cadence_sessions": CADENCE, "last_run": previous or None,
            "safe_window": safe_window(now),
            "worker_running": bool(THREAD and THREAD.is_alive()),
            "required_sessions": sum(a.split_sizes(cfg["horizon"])),
            "live_promotion_enabled": False,
            "note": "Rolling research uses the latest completed recorded sessions, including unsupported days. "
                    "New candidates remain research-only; their reference holdout is not independent future evidence."}


def run(*, progress=None, now=None):
    now = now or _now()
    cfg = config()
    horizon = cfg["horizon"]
    if not cfg["enabled"] or not safe_window(now) or STOP.is_set():
        return {"state": "paused", "reason": "Disabled or market-session priority"}
    required = sum(a.split_sizes(horizon))
    days = _latest(horizon, now)
    previous = _previous(horizon)
    if len(days) != required:
        return {"state": "awaiting_recorded_sessions", "recorded_sessions": len(days),
                "required_sessions": required}
    if not _due(days, previous, required):
        return {"state": "awaiting_new_sessions", "window_end": days[-1],
                "last_attempted_window_end": previous["window_end"]}
    nt, nc, nh = a.split_sizes(horizon)
    dates = [days[:nt], days[nt:nt+nc], days[nt+nc:]]
    report = {"state": "running", "horizon": horizon, "window_end": days[-1],
              "training_dates": dates[0], "calibration_dates": dates[1],
              "holdout_dates": dates[2], "started_utc": now.isoformat(),
              "models": [], "live_promotion_enabled": False,
              "source_policy_sha256": a.policy_for(horizon)}
    def check():
        if STOP.is_set() or config() != cfg or not safe_window(_now()):
            raise InterruptedError("Rolling retraining paused at a safe boundary")
    rows = []
    try:
        with closing(a._read()) as db:
            for i, day in enumerate(days):
                check()
                if progress:
                    progress(5 + 70 * i / len(days), "Reading completed session " + day)
                selected, _ = a.sample_day(a._rows(db, day, horizon))
                rows.extend(selected)
        train, cal, test = ([r for r in rows if r["session"] in set(part)] for part in dates)
        report["support"] = {k: a.support(v) for k, v in
                             zip(("training", "calibration", "holdout"), (train, cal, test))}
        if not (a._supported(train, 60, 20, train=True) and a._supported(cal, 20, 7)
                and a._supported(test, 40, 12)):
            report["state"] = "insufficient_matched_evidence"
        else:
            prior = np.asarray([(1 + sum(r["class"] == c for r in train)) /
                                (len(train) + 3) for c in a.CLASSES])
            baseline = np.tile(prior, (len(test), 1))
            report["training_prior_brier"] = a._directional_stats(
                test, [a._call(v) for v in baseline], baseline)["brier"]
            for i, name in enumerate(MODELS):
                check()
                if progress:
                    progress(80 + 8*i, "Training rolling " + name)
                fit = a._fit(name, train)
                temp = a._calibrate(a._predict(fit, cal), cal)
                probs = a._temperature(a._predict(fit, test), temp)
                metrics = a._directional_stats(test, [a._call(v) for v in probs], probs)
                check()
                ident = registry.freeze(name, fit, temp, train, cal, test,
                                        source="prospective", policy=a.policy_for(horizon),
                                        horizon=horizon, dates=dates)
                report["models"].append({"name": name, "model_id": ident,
                                         "holdout": metrics, "live_approved": False})
            report["state"] = "candidates_saved"
        check()
        report["finished_utc"] = _now().isoformat()
        if progress:
            progress(100, "Rolling research assessment saved")
        _record(horizon, report)
        return report
    except InterruptedError:
        # Leave the old completed-attempt watermark untouched so a later safe
        # window can retry. Any fully written candidate is immutable/deduplicated.
        return {"state": "paused", "reason": "Configuration or safe window changed"}


def _worker(submit):
    while not STOP.is_set():
        try:
            cfg = config()
            now = _now()
            if cfg["enabled"] and safe_window(now):
                days = _latest(cfg["horizon"], now)
                if _due(days, _previous(cfg["horizon"]), sum(a.split_sizes(cfg["horizon"]))):
                    submit()
        except (OSError, ValueError, TypeError, RuntimeError):
            pass
        WAKE.wait(60)
        WAKE.clear()


def start(submit):
    global THREAD
    with LOCK:
        if THREAD and THREAD.is_alive():
            return
        STOP.clear()
        THREAD = Thread(target=_worker, args=(submit,), daemon=True, name="rolling-alpha-retraining")
        THREAD.start()


def shutdown():
    STOP.set()
    WAKE.set()
