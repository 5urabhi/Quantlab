"""Source-limited intraday baseline and append-only prediction observations.

Signals use ONLY existing 1-minute bars. This is not a validated trading
strategy, broker quote feed, options signal, or execution service.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone, time
from pathlib import Path
from contextlib import contextmanager
from zoneinfo import ZoneInfo
import json
import math
import sqlite3
import uuid

from . import service

VERSION = "ema-rsi-1m-v1"
MAX_HISTORY = 100
IST = ZoneInfo("Asia/Kolkata")


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
        expected_ist = stamp.astimezone(IST).date().isoformat()
        if row.get("session_ist") != expected_ist:
            raise ValueError("Original one-minute session does not match Asia/Kolkata date")
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


def _continuous_session_tail(rows: list[dict]) -> list[dict]:
    """Only consecutive observed one-minute bars from the latest IST session."""
    if not rows:
        return []
    out = [rows[-1]]
    for row in reversed(rows[:-1]):
        current = out[0]
        if (row.get("session_ist") != current.get("session_ist")
                or _ts(current["timestamp_utc"]) -
                _ts(row["timestamp_utc"]) != timedelta(minutes=1)):
            break
        out.insert(0, row)
    return out


def snapshot(identity: str, source_rows: list[dict], *,
             now: datetime | None = None, include_chart: bool = True) -> dict:
    rows = _validated(source_rows)
    if not rows:
        raise ValueError("No original minute bars for this instrument")
    contiguous = _continuous_session_tail(rows)
    closes = [r["close"] for r in contiguous]
    fast, slow = _ema(closes, 9), _ema(closes, 21)
    rsi = _rsi(closes)
    atr = _atr(contiguous)
    last = rows[-1]
    stamp = _ts(last["timestamp_utc"])
    local = stamp.astimezone(IST)
    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age = (current_time - stamp).total_seconds()
    # Dhan 1-minute candle timestamps describe BAR START, not completed-bar
    # delivery. Never score as prospective until >= 60 seconds have elapsed.
    market_bar = (time(9, 15) <= local.time().replace(tzinfo=None)
                  <= time(15, 29) and local.weekday() < 5)
    # Accept only promptly observed completed bars. Otherwise an old bar
    # would be credited with a longer forecast horizon than was available.
    recent = 60 <= age <= 90 and market_bar
    direction = "NO_TRADE"
    if (len(contiguous) >= 30 and rsi is not None and fast[-1] is not None
            and slow[-1] is not None):
        if fast[-1] > slow[-1] and 55 <= rsi < 75 and closes[-1] > closes[-2]:
            direction = "UP"
        elif fast[-1] < slow[-1] and 25 < rsi <= 45 and closes[-1] < closes[-2]:
            direction = "DOWN"
    # Chart overlays are reset on each session/gap rather than polluted by
    # the previous day's close or an undocumented missing-minute fill.
    chart = []
    segment = []
    for row in (rows[-180:] if include_chart else []):
        if segment and (row["session_ist"] != segment[-1]["session_ist"] or
                _ts(row["timestamp_utc"]) -
                _ts(segment[-1]["timestamp_utc"]) != timedelta(minutes=1)):
            segment = []
        segment.append(row)
        prices = [s["close"] for s in segment]
        chart.append({**row, "ema9": _ema(prices, 9)[-1],
                      "ema21": _ema(prices, 21)[-1]})
    return {
        "identity": identity, "model_version": VERSION, "horizon_minutes": 6,
        "source_kind": "original_local_one_minute_candles",
        "quote_mode": "RECENT_LOCAL_CANDLE_NOT_VERIFIED_LIVE" if recent else "HISTORICAL_ONLY",
        "last_observed_utc": last["timestamp_utc"],
        "source_age_seconds": max(0, round(age)),
        "decision_delay_after_bar_close_seconds": max(0, round(age - 60)),
        "direction": direction, "confidence": None,
        "validation": "UNVALIDATED_RULE_BASELINE",
        "latest_close": last["close"], "rsi14": rsi, "atr14": atr,
        "ema9": fast[-1], "ema21": slow[-1],
        "contiguous_session_bars": len(contiguous),
        "signal_suppression": ("insufficient_consecutive_bars" if len(contiguous) < 30
                               else "overextended_or_no_confirmed_trend"
                               if direction == "NO_TRADE" else None),
        "rows": chart,
        "note": ("Underlying directional rule only; no option P&L, execution "
                 "assumptions, implied probabilities, or broker actions."),
    }


def _db_path() -> Path:
    return service.DATA / "trading_cockpit" / "predictions.sqlite3"


@contextmanager
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
    try:
        with conn:
            yield conn
    finally:
        conn.close()


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
    scored = [x for x in result if x["evaluation"] in ("CORRECT", "INCORRECT")]
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
            if observed != target:
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


def _report_summary(records: list[dict]) -> dict:
    correct = sum(row["evaluation"] == "CORRECT" for row in records)
    incorrect = sum(row["evaluation"] == "INCORRECT" for row in records)
    return {
        "total": len(records),
        "correct": correct, "incorrect": incorrect,
        "pending": sum(row["evaluation"] == "PENDING" for row in records),
        "no_trade": sum(row["evaluation"] == "NO_TRADE_REVIEWED" for row in records),
        "flat": sum(row["evaluation"] == "FLAT" for row in records),
        "unverifiable": sum(row["evaluation"] == "UNVERIFIABLE_GAP" for row in records),
        "directional_accuracy": correct / (correct + incorrect) if correct + incorrect else None,
        "scored": correct + incorrect,
    }


def day_report(identity: str, date_ist: str = "", *, limit: int = 2500) -> dict:
    """Operational day report from *prospectively logged* observations only.

    This is not inferred options P&L, nor a walk-forward performance claim.
    """
    if not 1 <= limit <= 20_000:
        raise ValueError("Invalid report limit")
    if date_ist:
        try:
            datetime.strptime(date_ist, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("Choose a valid YYYY-MM-DD Indian session") from exc
    with _connection() as conn:
        rows = conn.execute("""SELECT * FROM predictions WHERE identity=?
             ORDER BY created_utc DESC LIMIT ?""", (identity, limit)).fetchall()
    records = [_public(row) for row in rows]
    by_date: dict[str, list[dict]] = {}
    for record in records:
        ist_day = _ts(record["bar_utc"]).astimezone(IST).date().isoformat()
        if date_ist and ist_day != date_ist:
            continue
        by_date.setdefault(ist_day, []).append(record)
    days = [
        {"session_ist": session, **_report_summary(values)}
        for session, values in sorted(by_date.items(), reverse=True)
    ]
    return {
        "identity": identity,
        "date_filter": date_ist or None,
        "days": days,
        "overall": _report_summary([row for values in by_date.values() for row in values]),
        "source": "immutable-input prospective prediction ledger",
        "disclaimer": ("Direction only; no implied options P&L, no validated "
                       "out-of-sample hit rate or true current live data guarantee."),
        "truncated": len(records) >= limit,
    }


def historical_replay(identity: str, source_rows: list[dict],
                      horizon_minutes: int = 6) -> dict:
    """Historical one-minute walk-forward mechanical replay, not live predictions.

    The baseline is not fitted to the replay sample. Source candles must be
    chronological. Each signal uses prior and current candles only; the future
    close is inspected only *after* the signal label is frozen in memory.
    Results have NO option price assumptions, spreads or fees.
    """
    if horizon_minutes not in (3, 6):
        raise ValueError("Select a 3- or 6-minute replay horizon")
    rows = _validated(source_rows)
    if not rows:
        raise ValueError("No observed minute candles")
    times = {_ts(row["timestamp_utc"]): row for row in rows}
    day_map: dict[str, list[dict]] = {}
    samples = []
    for index in range(29, len(rows)):
        candle = rows[index]
        local = _ts(candle["timestamp_utc"]).astimezone(IST)
        if not (time(9, 15) <= local.time().replace(tzinfo=None) <= time(15, 29)):
            continue
        # Use an actual past-anchored window. Never reuse a signal computed
        # on a future window, even when a downloaded session is incomplete.
        observation = snapshot(identity, rows[max(0, index-200):index+1],
                               now=_ts(candle["timestamp_utc"]) + timedelta(seconds=90),
                               include_chart=False)
        target = _ts(candle["timestamp_utc"]) + timedelta(minutes=horizon_minutes)
        next_row = times.get(target)
        if next_row is None or next_row["session_ist"] != candle["session_ist"]:
            status, actual, movement = "UNVERIFIABLE_GAP", None, None
        else:
            actual = next_row["close"]
            movement = ("UP" if actual > candle["close"] else
                        "DOWN" if actual < candle["close"] else "FLAT")
            if observation["direction"] == "NO_TRADE":
                status = "NO_TRADE_REVIEWED"
            elif movement == "FLAT":
                status = "FLAT"
            else:
                status = ("CORRECT" if movement == observation["direction"]
                          else "INCORRECT")
        event = {
            "bar_utc": candle["timestamp_utc"],
            "session_ist": candle["session_ist"],
            "direction": observation["direction"],
            "reference_close": candle["close"], "observed_close": actual,
            "movement_bps": (round(10000*(actual/candle["close"]-1),2)
                             if actual is not None else None),
            "actual_direction": movement,
            "evaluation": status,
        }
        day_map.setdefault(candle["session_ist"], []).append(event)
        samples.append(event)
    return {
        "identity": identity, "horizon_minutes": horizon_minutes,
        "observed_source_bars": len(rows), "model_version": VERSION,
        "mode": "RETROSPECTIVE_HISTORICAL_RULE_REPLAY",
        "overall": _report_summary(samples),
        "days": [{"session_ist": session, **_report_summary(events)}
                 for session, events in sorted(day_map.items(), reverse=True)],
        "latest_events": samples[-100:],
        "disclaimer": ("Mechanical historical baseline only. No model training, "
                       "calibration, out-of-sample certification, executable "
                       "option prices, slippage, or brokerage costs."),
    }


def observe_and_score(identity: str, source_rows: list[dict], *,
                      live_observed: bool = False) -> dict:
    """One opt-in monitor tick. Deduplicate both horizons and evaluate due calls.

    Should be called only by an explicitly authorized session monitor.
    A background browser is *not* an always-on trading service.
    """
    observation = snapshot(identity, source_rows)
    recent = observation["quote_mode"] == "RECENT_LOCAL_CANDLE_NOT_VERIFIED_LIVE"
    if live_observed and recent:
        if identity not in {"INDEX:BANKNIFTY", "INDEX:NIFTY50"}:
            raise ValueError("Authenticated live monitoring requires an exact spot-index identity")
        # This flag is set only by the live WebSocket receiver after it
        # validates an actual received Dhan ticker and a completed minute bar.
        observation["quote_mode"] = "LIVE_OBSERVED"
        observation["source_kind"] = "locally_aggregated_Dhan_live_LTP"
    recorded = []
    if recent:
        for horizon in (3, 6):
            recorded.append(record(observation, horizon))
    outcome = evaluate(identity, source_rows)
    return {
        "last_observation": observation["last_observed_utc"],
        "source_status": observation["quote_mode"],
        "recorded": recorded,
        "updated_outcomes": outcome["updated"],
        "summary": outcome["summary"],
        "monitoring_scope": ("backend-local opt-in Dhan live observed index" if live_observed
                             else "browser-open opt-in; original source only; not a live feed"),
    }
