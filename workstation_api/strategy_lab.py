"""BANKNIFTY EMA parameter sweeps and direct index-paper backtests.

Reads only SHA-verified original Dhan IDX_I minute candles. It never changes
the live recorder's configuration, SQLite files, WebSocket subscriptions,
tokens or source datasets. The underlying cash index is NOT tradable; index
P&L below is a transparent directional exposure proxy, not option P&L.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, time
from pathlib import Path
from uuid import uuid4
import json
import os
import shutil
import subprocess
import sys
import tempfile
from math import isfinite, sqrt
from statistics import mean, stdev

from . import cockpit_sources, live_market, trading_cockpit, service

IDENTITY = "INDEX:BANKNIFTY"
MAX_BARS = 5000
MAX_PAIRS = 256
INDICATOR_VERSION = "ema_sma_seed_session_reset_1m_v1"
HOLD = "HOLD"
UP = "UP"
DOWN = "DOWN"
IST = trading_cockpit.IST
SESSION_OPEN = time(9, 15)
SESSION_LAST = time(15, 29)


def _market_bar(row: dict) -> bool:
    stamp = trading_cockpit._ts(row["timestamp_utc"])
    local = stamp.astimezone(IST)
    return (row["session_ist"] == local.date().isoformat()
            and SESSION_OPEN <= local.time().replace(tzinfo=None) <= SESSION_LAST)


def _contiguous(a: dict, b: dict) -> bool:
    return (a["session_ist"] == b["session_ist"]
            and trading_cockpit._ts(b["timestamp_utc"]) -
            trading_cockpit._ts(a["timestamp_utc"]) == timedelta(minutes=1))


def load_index(limit: int, source_mode: str = "historical") -> tuple[list[dict], dict]:
    if limit not in (500, 1500, 3000, 5000):
        raise ValueError("Select 500, 1500, 3000 or 5000 original 1-minute bars")
    if source_mode == "historical":
        # SHA-verified original Dhan IDX_I historical batch.
        source = cockpit_sources.series(IDENTITY, limit=limit)
    elif source_mode == "recorded_live":
        # Snapshot only already-completed original live ticks aggregated by
        # minute. No subscription, direct vendor call or recorder restart.
        source = live_market.minute_series(IDENTITY, limit=limit)
    else:
        raise ValueError("Choose historical Dhan or recorded live index candles")
    rows = [row for row in trading_cockpit._validated(source["rows"])
            if _market_bar(row)]
    if len(rows) < 50:
        raise ValueError("Need at least 50 original regular-session BANKNIFTY candles")
    return rows, {
        "identity": IDENTITY, "basis": source["basis"],
        "source_mode": source_mode,
        "source_warning": source.get("source_warning") or source.get("warning"),
        "original_sha256": source.get("source_file_sha256"),
        "rows": len(rows), "sessions": len(set(r["session_ist"] for r in rows)),
        "first_utc": rows[0]["timestamp_utc"],
        "last_utc": rows[-1]["timestamp_utc"],
        "live_recorder_touched": False,
    }


def ema_series(rows: list[dict], fast: int, slow: int) -> tuple[list, list, list]:
    if not 2 <= fast < slow <= 150:
        raise ValueError("EMA fast must be >=2, strictly below slow <=150")
    first = [None] * len(rows)
    second = [None] * len(rows)
    roc5 = [None] * len(rows)
    offset = 0
    while offset < len(rows):
        end = offset + 1
        while end < len(rows) and _contiguous(rows[end - 1], rows[end]):
            end += 1
        closes = [row["close"] for row in rows[offset:end]]
        f = trading_cockpit._ema(closes, fast)
        s = trading_cockpit._ema(closes, slow)
        for i, (a, b) in enumerate(zip(f, s)):
            first[offset + i] = a
            second[offset + i] = b
            if i >= 5 and closes[i - 5] > 0:
                roc5[offset + i] = round(
                    100 * (closes[i] / closes[i - 5] - 1), 4)
        offset = end
    return first, second, roc5


def crossover_events(rows: list[dict], fast: int, slow: int) -> tuple[list[str], dict]:
    fast_line, slow_line, momentum = ema_series(rows, fast, slow)
    signals = [HOLD] * len(rows)
    for i in range(1, len(rows)):
        if not _contiguous(rows[i - 1], rows[i]):
            continue
        f0, f1 = fast_line[i - 1], fast_line[i]
        s0, s1 = slow_line[i - 1], slow_line[i]
        if None in (f0, f1, s0, s1):
            continue
        if f0 <= s0 and f1 > s1:
            signals[i] = UP
        elif f0 >= s0 and f1 < s1:
            signals[i] = DOWN
    return signals, {"fast": fast_line, "slow": slow_line, "momentum_roc5_pct": momentum}


def _round(value, places=4):
    return round(float(value), places) if isfinite(value) else None


def backtest_index(rows: list[dict], signals: list[str], *,
                   starting_capital: float = 50000,
                   cost_bps: float = 5, include_chart: bool = True) -> dict:
    """One hypothetical index-directional exposure held until opposite cross.

    Trigger is observed at close of candle i. Entry/exit uses OPEN of i+1
    only if i+1 is real, consecutive, same session. Flat at a verified 15:29
    index close; truncated last sessions are not promoted to an EOD fill.
    """
    if len(signals) != len(rows) or len(rows) > MAX_BARS:
        raise ValueError("Research signals must align with original minute bars")
    if not (1000 <= starting_capital <= 100_000_000
            and 0 <= cost_bps <= 500):
        raise ValueError("Select a bounded starting account and trading cost")
    if any(v not in (UP, DOWN, HOLD) for v in signals):
        raise ValueError("Code returned unsupported signal (UP, DOWN, HOLD only)")
    capital = float(starting_capital)
    position = None
    pending = None
    trades, trace = [], []
    unscored = Counter()
    highs = capital
    max_dd = 0.
    actual_signal_count = sum(x != HOLD for x in signals)

    def exit_position(price: float, stamp: str, reason: str):
        nonlocal position, capital, highs, max_dd
        pos = position
        if pos is None:
            return
        shares = pos["index_units"]
        points = (price - pos["entry_price"]) * pos["direction"]
        sell_cost = price * shares * cost_bps / 10000
        pnl = points * shares - pos["entry_cost"] - sell_cost
        capital += pnl
        hold = (trading_cockpit._ts(stamp) -
                trading_cockpit._ts(pos["entry_utc"])).total_seconds() / 60
        trades.append({
            "direction": UP if pos["direction"] == 1 else DOWN,
            "entry_utc": pos["entry_utc"], "exit_utc": stamp,
            "entry_price": pos["entry_price"], "exit_price": price,
            "hold_minutes": round(hold, 2),
            "index_points": round(points, 4),
            "net_pnl_proxy_inr": round(pnl, 2),
            "equity_inr": round(capital, 2),
            "exit_reason": reason,
        })
        highs = max(highs, capital)
        max_dd = max(max_dd, (highs - capital) / highs * 100 if highs > 0 else 0.)
        position = None

    for i, row in enumerate(rows):
        if i > 0 and not _contiguous(rows[i - 1], row):
            if position is not None:
                unscored["unclosed_on_missing_bar_or_session"] += 1
                position = None
            pending = None
        if pending is not None:
            if position is None or position["direction"] != pending:
                if position is not None:
                    exit_position(row["open"], row["timestamp_utc"], "opposite_confirmed_cross")
                if capital > 0:
                    shares = capital / row["open"]
                    position = {
                        "direction": pending,
                        "index_units": shares, "entry_price": row["open"],
                        "entry_cost": shares * row["open"] * cost_bps / 10000,
                        "entry_utc": row["timestamp_utc"],
                    }
            pending = None
        # Only the actual observed regular-session 15:29 candle can provide
        # a definite EOD close; the terminal partial day is not assumed closed.
        at = trading_cockpit._ts(row["timestamp_utc"]).astimezone(IST)
        if at.time().replace(tzinfo=None) == SESSION_LAST:
            exit_position(row["close"], row["timestamp_utc"], "observed_session_end")
            pending = None
        elif signals[i] in (UP, DOWN):
            if i + 1 < len(rows) and _contiguous(row, rows[i + 1]):
                pending = 1 if signals[i] == UP else -1
            else:
                unscored["cross_without_next_original_open"] += 1
        if include_chart:
            unrealized = 0.
            if position is not None:
                unrealized = ((row["close"] - position["entry_price"])
                              * position["direction"] * position["index_units"]
                              - position["entry_cost"])
            trace.append({
                "time": row["timestamp_utc"],
                "price": _round(row["close"]),
                "account": _round(capital + unrealized, 2),
                "signal": signals[i],
                "position": (UP if position and position["direction"] == 1
                             else DOWN if position else HOLD),
            })
    if position is not None:
        unscored["open_position_at_truncated_history_end"] += 1

    wins = [t["net_pnl_proxy_inr"] for t in trades if t["net_pnl_proxy_inr"] > 0]
    losses = [t["net_pnl_proxy_inr"] for t in trades if t["net_pnl_proxy_inr"] < 0]
    realized = [t["net_pnl_proxy_inr"] for t in trades]
    sharpe = None
    if len(realized) >= 3 and len(set(round(v, 6) for v in realized)) > 1:
        # Per-trade statistic; not misleadingly annualized without elapsed time.
        sharpe = mean(realized) / stdev(realized) * sqrt(len(realized))
    profit_factor = sum(wins) / abs(sum(losses)) if losses else None
    return {
        "metrics": {
            "trade_count": len(trades),
            "crossovers": actual_signal_count,
            "win_rate_pct": _round(len(wins) / len(trades) * 100, 2) if trades else None,
            "pnl_proxy_inr": _round(capital - starting_capital, 2),
            "return_proxy_pct": _round((capital / starting_capital - 1) * 100, 3),
            "ending_capital_proxy_inr": _round(capital, 2),
            "index_points": _round(sum(t["index_points"] for t in trades), 3),
            "max_closed_trade_drawdown_pct": _round(max_dd, 3),
            "profit_factor": _round(profit_factor, 3) if profit_factor is not None else None,
            "trade_sharpe_unannualized": _round(sharpe, 3) if sharpe is not None else None,
            "avg_hold_minutes": _round(mean(t["hold_minutes"] for t in trades), 2)
                                if trades else None,
            "unscored": dict(unscored),
        },
        "trades": trades if include_chart else [],
        "chart": trace if include_chart else [],
        "read_only": True, "orders_placed": 0,
        "basis": "hypothetical_1x_banknifty_index_directional_proxy_not_tradable",
    }


def _rsi14(rows: list[dict]) -> list[float | None]:
    """Source-only 14-bar Wilder RSI with session and missing-minute resets."""
    out = [None] * len(rows)
    start = 0
    while start < len(rows):
        end = start + 1
        while end < len(rows) and _contiguous(rows[end - 1], rows[end]):
            end += 1
        closes = [r["close"] for r in rows[start:end]]
        if len(closes) > 14:
            changes = [closes[i] - closes[i-1] for i in range(1, len(closes))]
            gains = sum(max(0, x) for x in changes[:14]) / 14
            losses = sum(max(0, -x) for x in changes[:14]) / 14
            for local in range(14, len(closes)):
                if local > 14:
                    change = changes[local - 1]
                    gains = (gains * 13 + max(0, change)) / 14
                    losses = (losses * 13 + max(0, -change)) / 14
                out[start + local] = round(
                    100 - 100 / (1 + gains / losses), 2) if losses else (
                    100. if gains else 50.)
        start = end
    return out


def _overlay(rows: list[dict], signals: list[str], indicators: dict) -> list[dict]:
    result = []
    rsi = _rsi14(rows)
    for i, row in enumerate(rows):
        f = indicators["fast"][i]
        s = indicators["slow"][i]
        spread = (f - s) / row["close"] * 10000 if f is not None and s is not None else None
        result.append({
            "time": row["timestamp_utc"], "price": row["close"],
            "open": row["open"], "high": row["high"], "low": row["low"],
            "fast_ema": f, "slow_ema": s,
            "ema_spread_bps": _round(spread, 3) if spread is not None else None,
            "momentum_roc5_pct": indicators["momentum_roc5_pct"][i],
            "rsi14": rsi[i],
            "signal": signals[i],
        })
    return result


def _periods(fast_periods: list[int], slow_periods: list[int]) -> list[tuple[int, int]]:
    if not fast_periods or not slow_periods:
        raise ValueError("Enter at least one fast and one slow EMA period")
    if len(fast_periods) > 32 or len(slow_periods) > 32:
        raise ValueError("Use at most 32 distinct periods in each range")
    if any(type(i) is not int or i < 2 or i > 150 for i in fast_periods + slow_periods):
        raise ValueError("EMA periods must be integers between 2 and 150")
    result = sorted({(fast, slow) for fast in fast_periods for slow in slow_periods
                     if fast < slow})
    if not result or len(result) > MAX_PAIRS:
        raise ValueError("Select between 1 and 256 valid fast < slow EMA combinations")
    return result


def run_sweep(*, limit: int = 1500, fast_periods: list[int],
              slow_periods: list[int], starting_capital: float = 50000,
              cost_bps: float = 5, source_mode: str = "historical",
              progress=None) -> dict:
    combinations = _periods(fast_periods, slow_periods)
    rows, evidence = load_index(limit, source_mode)
    sessions = sorted({row["session_ist"] for row in rows})
    # Reserve whole calendar sessions for validation. Small samples are not
    # promoted to independently validated out-of-sample performance.
    validated = len(sessions) >= 6
    cutoff = max(2, int(len(sessions) * .7)) if validated else len(sessions)
    train_days = set(sessions[:cutoff])
    holdout_days = set(sessions[cutoff:])
    train_rows = [row for row in rows if row["session_ist"] in train_days]
    test_rows = [row for row in rows if row["session_ist"] in holdout_days]
    trials = []
    for n, (fast, slow) in enumerate(combinations):
        signals, _ = crossover_events(train_rows, fast, slow)
        train = backtest_index(train_rows, signals,
                               starting_capital=starting_capital,
                               cost_bps=cost_bps, include_chart=False)["metrics"]
        trials.append({"fast": fast, "slow": slow, "training": train})
        if progress and (n % 8 == 0 or n == len(combinations)-1):
            progress(10 + 80 * (n + 1) / len(combinations),
                     "Index-only EMA crossover sweep: " +
                     str(n + 1) + "/" + str(len(combinations)))
    # Ranking is strictly in-sample; never select a winner on test data.
    trials.sort(key=lambda x: (x["training"]["return_proxy_pct"],
                               x["training"]["trade_count"]), reverse=True)
    if validated and test_rows:
        for trial in trials[:20]:
            cross, _ = crossover_events(test_rows, trial["fast"], trial["slow"])
            trial["holdout"] = backtest_index(
                test_rows, cross, starting_capital=starting_capital,
                cost_bps=cost_bps, include_chart=False)["metrics"]
    best = trials[0]
    actual_signals, indicators = crossover_events(rows, best["fast"], best["slow"])
    selected = backtest_index(rows, actual_signals,
                              starting_capital=starting_capital,
                              cost_bps=cost_bps, include_chart=True)
    return save_run({
        "kind": "ema_sweep", "identity": IDENTITY,
        "model": INDICATOR_VERSION,
        "combinations_tested": len(combinations),
        "ranked": trials,
        "best_pair": {"fast": best["fast"], "slow": best["slow"]},
        "selected": selected,
        "overlays": _overlay(rows, actual_signals, indicators),
        "evidence": evidence,
        "validation": {
            "whole_sessions_train": len(train_days),
            "whole_sessions_holdout": len(holdout_days),
            "holdout_available": validated,
            "selection_rule": "train-only return proxy, top 20 holdout evaluated",
            "warning": ("Holdout uses separate whole sessions; no tuning on test."
                        if validated else
                        "Fewer than 6 sessions: ranking is exploratory, no "
                        "independent out-of-sample validation."),
        },
        "bid_ask_spread_source": "unavailable_for_cash_index_ohlc",
        "read_only": True, "orders_placed": 0,
    })


def run_pair(*, fast: int, slow: int, limit: int = 1500,
             starting_capital: float = 50000,
             cost_bps: float = 5, source_mode: str = "historical") -> dict:
    rows, evidence = load_index(limit, source_mode)
    signals, indicators = crossover_events(rows, fast, slow)
    selected = backtest_index(rows, signals, starting_capital=starting_capital,
                              cost_bps=cost_bps, include_chart=True)
    output = {
        "kind": "ema_pair", "identity": IDENTITY, "model": INDICATOR_VERSION,
        "best_pair": {"fast": fast, "slow": slow},
        "selected": selected, "overlays": _overlay(rows, signals, indicators),
        "evidence": evidence,
        "bid_ask_spread_source": "unavailable_for_cash_index_ohlc",
        "read_only": True, "orders_placed": 0,
    }
    return save_run(output)


def _run_root() -> Path:
    root = service.DATA / "research_lab" / "runs"
    if root.is_symlink() or root.parent.is_symlink():
        raise ValueError("Unsafe local strategy results directory")
    root.mkdir(parents=True, exist_ok=True)
    return root


def save_run(payload: dict) -> dict:
    """Save exact local model/chart evidence without touching Dhan source files."""
    run_id = "banknifty_" + uuid4().hex[:20]
    data = {**payload, "run_id": run_id}
    encoded = json.dumps(data, allow_nan=False, ensure_ascii=False,
                         separators=(",", ":")).encode("utf-8")
    if len(encoded) > 5_000_000:
        raise ValueError("Research result exceeds local save limit")
    path = _run_root() / (run_id + ".json")
    temp = path.with_suffix(".tmp")
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(encoded)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()
    return data


def saved_runs(limit: int = 25) -> dict:
    if not 1 <= limit <= 50:
        raise ValueError("Saved run limit must be 1-50")
    results = []
    root = _run_root()
    for path in sorted(root.glob("banknifty_*.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
        if path.is_symlink():
            continue
        results.append({"run_id": path.stem,
                        "file_bytes": path.stat().st_size,
                        "modified_utc": datetime.fromtimestamp(
                            path.stat().st_mtime,
                            tz=trading_cockpit.timezone.utc).isoformat()})
    return {"runs": results, "source": "local_read_only_research_archive"}


def read_run(run_id: str) -> dict:
    import re
    if not re.fullmatch(r"banknifty_[0-9a-f]{20}", run_id):
        raise ValueError("Unknown saved research ID")
    path = _run_root() / (run_id + ".json")
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 5_000_000:
        raise ValueError("Saved research result unavailable")
    return json.loads(path.read_text(encoding="utf-8"))


def _run_low_priority(kind: str, params: dict, progress=None) -> dict:
    """CPU-intensive EMA grid runs OUTSIDE FastAPI and live Dhan recorder.

    The child sees only bounded analysis configuration and local source data,
    never the Dhan access token, API jobs, WebSocket or broker state.
    """
    nice = shutil.which("nice")
    if not nice:
        raise ValueError("Ubuntu nice utility is required to protect live recording")
    if kind not in ("ema_sweep", "ema_pair"):
        raise ValueError("Only built-in EMA grid/pair analysis is supported")
    if progress:
        progress(10, "Launching separate lower-priority BANKNIFTY research process")
    with tempfile.TemporaryDirectory(prefix="quantlab_index_research_") as temp:
        work = Path(temp)
        work.chmod(0o700)
        request = work / "request.json"
        response = work / "response.json"
        encoded = json.dumps({"kind": kind, "params": params},
                             allow_nan=False).encode("utf-8")
        if len(encoded) > 16000:
            raise ValueError("Research configuration is too large")
        descriptor = os.open(request, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as file:
            file.write(encoded)
        command = [nice, "-n", "10", sys.executable, "-m",
                   "workstation_api.strategy_lab_process",
                   str(request), str(response)]
        safe_environment = {
            "PATH": os.defpath, "HOME": str(work),
            "PYTHONPATH": str(service.ROOT),
            "LANG": "C.UTF-8", "TZ": "Asia/Kolkata",
            "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
        }
        # Do not inherit DHAN_ACCESS_TOKEN, other broker secrets or open FDs.
        try:
            proc = subprocess.run(
                command, cwd=service.ROOT, env=safe_environment,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=120, start_new_session=True, close_fds=True,
                check=False)
        except subprocess.TimeoutExpired as exc:
            raise ValueError(
                "The isolated EMA parameter grid exceeded 120 seconds; "
                "try fewer combinations. Live Dhan recording was untouched.") from exc
        except OSError as exc:
            raise ValueError(
                "Could not launch the separate index-research process") from exc
        if not response.is_file() or response.is_symlink() or response.stat().st_size > 4096:
            raise ValueError("Isolated EMA process produced no verified result receipt")
        try:
            status = json.loads(response.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            raise ValueError("Invalid isolated EMA research completion receipt") from exc
        if proc.returncode != 0 or "run_id" not in status:
            raise ValueError("EMA research process: " +
                             str(status.get("detail") or status.get("error")
                                 or "worker failed")[:210])
    if progress:
        progress(93, "Loading saved index-only research and charts")
    return read_run(status["run_id"])


def run_sweep_process(*, limit: int = 1500, fast_periods: list[int],
                      slow_periods: list[int],
                      starting_capital: float = 50000, cost_bps: float = 5,
                      source_mode: str = "historical", progress=None) -> dict:
    _periods(fast_periods, slow_periods)
    return _run_low_priority("ema_sweep", {
        "limit": limit, "fast_periods": fast_periods,
        "slow_periods": slow_periods,
        "starting_capital": starting_capital, "cost_bps": cost_bps,
        "source_mode": source_mode}, progress=progress)


def run_pair_process(*, fast: int, slow: int, limit: int = 1500,
                     starting_capital: float = 50000,
                     cost_bps: float = 5, source_mode: str = "historical",
                     progress=None) -> dict:
    _periods([fast], [slow])
    return _run_low_priority("ema_pair", {
        "fast": fast, "slow": slow, "limit": limit,
        "starting_capital": starting_capital,
        "cost_bps": cost_bps, "source_mode": source_mode},
        progress=progress)


def run_custom(*, code: str, limit: int = 1500,
               starting_capital: float = 50000, cost_bps: float = 5,
               source_mode: str = "historical", progress=None) -> dict:
    from . import python_strategy_sandbox
    rows, evidence = load_index(limit, source_mode)
    if progress:
        progress(12, "Snapshotting original BANKNIFTY candles for isolated Python")
    signals, sandbox = python_strategy_sandbox.run_python(code, rows)
    if progress:
        progress(85, "Scoring causal index-directional fills and plotting")
    selected = backtest_index(rows, signals,
                              starting_capital=starting_capital,
                              cost_bps=cost_bps, include_chart=True)
    # Always label the reference 9/21 EMA overlay as independent of custom
    # strategy. It can explain the spread, not claim authorship of signals.
    _, indicators = crossover_events(rows, 9, 21)
    return save_run({
        "kind": "python_strategy", "identity": IDENTITY,
        "strategy_origin": "user_entered_python_isolated_no_broker_access",
        "selected": selected,
        "overlays": _overlay(rows, signals, indicators),
        "evidence": evidence, "sandbox": sandbox,
        "reference_ema": {"fast": 9, "slow": 21,
                          "note": "Reference overlays, not a claim about user strategy"},
        "bid_ask_spread_source": "unavailable_for_cash_index_ohlc",
        "read_only": True, "orders_placed": 0,
    })
