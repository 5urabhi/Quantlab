"""Source-limited intraday baseline and append-only prediction observations.

Signals use ONLY existing 1-minute bars. This is not a validated trading
strategy, broker quote feed, options signal, or execution service.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import math
import sqlite3
import uuid

from . import service

VERSION = "ema-rsi-1m-v1"
MAX_HISTORY = 100


def _ts(value: str) -> datetime:
    stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("Source bar must contain an explicit timezone")
    return stamp.astimezone(timezone.utc)


def _validated(rows: list[dict]) -> list[dict]:
    if len(rows) > 5000:
        raise ValueError("Too many one-minute observations")
    result = []
    previous = None
    for row in rows:
        stamp = _ts(row["timestamp_utc"])
        if previous is not None and stamp <= previous:
            raise ValueError("Source bars must be unique and increasing")
        values = [float(row[k]) for k in ("open", "high", "low", "close")]
        if not all(math.isfinite(v) and v > 0 for v in values):
            raise ValueError("Invalid original price")
        op, hi, lo, close = values
        if lo > min(op, close) or hi < max(op, close):
            raise ValueError("Invalid original candle high/low")
        result.append({**row, "open": op, "high": hi, "low": lo,
                       "close": close, "timestamp_utc": stamp.isoformat()})
        previous = stamp
    return result


def _ema(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    level = sum(values[:period]) / period
    out[period - 1] = level
    alpha = 2 / (period + 1)
    for idx in range(period, len(values)):
        level = alpha * values[idx] + (1 - alpha) * level
        out[idx] = round(level, 4)
    return out


def _rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) <= period:
        return None
    differences = [values[i] - values[i - 1] for i in range(1, len(values))]
    avg_up = sum(max(x, 0) for x in differences[:period]) / period
    avg_down = sum(max(-x, 0) for x in differences[:period]) / period
    for change in differences[period:]:
        avg_up = (avg_up * (period - 1) + max(change, 0)) / period
        avg_down = (avg_down * (period - 1) + max(-change, 0)) / period
    if avg_down == 0:
        return 100.0 if avg_up else 50.0
    return round(100 - 100 / (1 + avg_up / avg_down), 2)


def _atr(rows: list[dict], period: int = 14) -> float | None:
    if len(rows) <= period:
        return None
    tr = []
    for previous, current in zip(rows, rows[1:]):
        tr.append(max(current["high"] - current["low"],
                      abs(current["high"] - previous["close"]),
                      abs(current["low"] - previous["close"])))
    avg = sum(tr[:period]) / period
    for x in tr[period:]:
        avg = (avg * (period - 1) + x) / period
    return round(avg, 3)


def snapshot(identity: str, source_rows: list[dict], *,
             now: datetime | None = None) -> dict:
    rows = _validated(source_rows)
    if not rows:
        raise ValueError("No original minute bars for this instrument")
    closes = [r["close"] for r in rows]
    fast, slow = _ema(closes, 9), _ema(closes, 21)
    rsi = _rsi(closes)
    atr = _atr(rows)
    last = rows[-1]
    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age = (current_time - _ts(last["timestamp_utc"])).total_seconds()
    recent = 0 <= age <= 120  # Not evidence that broker tick updates are live.
    direction = "NO_TRADE"
    if (len(rows) >= 30 and rsi is not None and fast[-1] is not None and
            slow[-1] is not None):
        if fast[-1] > slow[-1] and 55 <= rsi < 75 and closes[-1] > closes[-2]:
            direction = "UP"
        elif fast[-1] < slow[-1] and 25 < rsi <= 45 and closes[-1] < closes[-2]:
            direction = "DOWN"
    return {
        "identity": identity, "model_version": VERSION, "horizon_minutes": 6,
        "source_kind": "original_local_one_minute_candles",
        "quote_mode": "RECENT_LOCAL_CANDLE_NOT_VERIFIED_LIVE" if recent else "HISTORICAL_ONLY",
        "last_observed_utc": last["timestamp_utc"],
        "source_age_seconds": max(0, round(age)),
        "direction": direction, "confidence": None,
        "validation": "UNVALIDATED_RULE_BASELINE",
        "latest_close": last["close"], "rsi14": rsi, "atr14": atr,
        "ema9": fast[-1], "ema21": slow[-1],
        "rows": [{**r, "ema9": fast[i], "ema21": slow[i]}
                 for i, r in enumerate(rows[-180:], start=max(0, len(rows) - 180))],
        "note": ("Underlying directional rule only; no option P&L, execution "
                 "assumptions, implied probabilities, or broker actions."),
    }


def _db_path() -> Path:
    return service.DATA / "trading_cockpit" / "predictions.sqlite3"


def _connection() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("""CREATE TABLE IF NOT EXISTS predictions (
        id TEXT PRIMARY KEY,
        created_utc TEXT NOT NULL,
        identity TEXT NOT NULL,
        bar_utc TEXT NOT NULL,
        reference_close REAL NOT NULL,
        direction TEXT NOT NULL,
        horizon_minutes INTEGER NOT NULL,
        model_version TEXT NOT NULL,
        quote_mode TEXT NOT NULL,
        features_json TEXT NOT NULL,
        evaluation TEXT NOT NULL DEFAULT 'PENDING',
        evaluated_utc TEXT,
        observed_close REAL,
        actual_direction TEXT,
        UNIQUE(identity,bar_utc,horizon_minutes,model_version)
    )""")
    return conn


def _public(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["features"] = json.loads(data.pop("features_json"))
    return data


def record(observation: dict, horizon_minutes: int = 6) -> dict:
    if horizon_minutes not in (3, 6):
        raise ValueError("Only 3- or 6-minute horizons are available")
    if observation["model_version"] != VERSION:
        raise ValueError("Unsupported baseline model")
    reference = float(observation["latest_close"])
    if not math.isfinite(reference) or reference <= 0:
        raise ValueError("Invalid source close")
    fields = {"rsi14": observation["rsi14"], "atr14": observation["atr14"],
              "ema9": observation["ema9"], "ema21": observation["ema21"]}
    with _connection() as conn:
        conn.execute("""INSERT OR IGNORE INTO predictions
            (id,created_utc,identity,bar_utc,reference_close,direction,
             horizon_minutes,model_version,quote_mode,features_json)
            VALUES(?,?,?,?,?,?,?,?,?,?)""",
            ("pred_" + uuid.uuid4().hex[:18],
             datetime.now(timezone.utc).isoformat(),
             observation["identity"], observation["last_observed_utc"],
             reference, observation["direction"], horizon_minutes, VERSION,
             observation["quote_mode"], json.dumps(fields, sort_keys=True)))
        row = conn.execute("""SELECT * FROM predictions WHERE identity=?
            AND bar_utc=? AND horizon_minutes=? AND model_version=?""",
            (observation["identity"], observation["last_observed_utc"],
             horizon_minutes, VERSION)).fetchone()
        return _public(row)


def list_predictions(identity: str = "", limit: int = 50) -> dict:
    if not 1 <= limit <= MAX_HISTORY:
        raise ValueError("Invalid prediction history limit")
    with _connection() as conn:
        if identity:
            rows = conn.execute("""SELECT * FROM predictions WHERE identity=?
                ORDER BY created_utc DESC LIMIT ?""", (identity, limit)).fetchall()
        else:
            rows = conn.execute("""SELECT * FROM predictions
                ORDER BY created_utc DESC LIMIT ?""", (limit,)).fetchall()
    result = [_public(r) for r in rows]
    scored = [x for x in result if x["evaluation"] in ("CORRECT", "INCORRECT", "FLAT")]
    correct = sum(x["evaluation"] == "CORRECT" for x in scored)
    return {"predictions": result,
            "summary": {"evaluated_directions": len(scored),
                        "correct_directions": correct,
                        "direction_accuracy": (correct / len(scored)) if scored else None,
                        "qualification": "In-sample operational scoreboard, not out-of-sample strategy evidence"}}


def evaluate(identity: str, source_rows: list[dict]) -> dict:
    """Resolve only due horizons backed by observed same-session minute bars.

    Pending fields never change. When a later session exists but the horizon
    bar is missing, mark unverified instead of filling the gap.
    """
    rows = _validated(source_rows)
    with _connection() as conn:
        pending = conn.execute("""SELECT * FROM predictions
            WHERE identity=? AND evaluation='PENDING'""", (identity,)).fetchall()
        updates = 0
        for item in pending:
            target = _ts(item["bar_utc"]) + timedelta(minutes=item["horizon_minutes"])
            later = [r for r in rows if _ts(r["timestamp_utc"]) >= target]
            if not later:
                continue
            actual = later[0]
            observed = _ts(actual["timestamp_utc"])
            if observed - target > timedelta(seconds=60) or observed.date() != target.date():
                result, movement, close = "UNVERIFIABLE_GAP", None, None
            else:
                close = actual["close"]
                movement = "UP" if close > item["reference_close"] else (
                    "DOWN" if close < item["reference_close"] else "FLAT")
                if item["direction"] == "NO_TRADE":
                    result = "NO_TRADE_REVIEWED"
                elif movement == "FLAT":
                    result = "FLAT"
                else:
                    result = "CORRECT" if movement == item["direction"] else "INCORRECT"
            conn.execute("""UPDATE predictions SET evaluation=?,evaluated_utc=?,
                observed_close=?,actual_direction=? WHERE id=? AND evaluation='PENDING'""",
                (result, datetime.now(timezone.utc).isoformat(),
                 close, movement, item["id"]))
            updates += 1
    return {"updated": updates, **list_predictions(identity)}
