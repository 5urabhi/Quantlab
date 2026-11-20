"""Efficient, source-causal scoring of every supported BANKNIFTY EMA pair.

The default 2..150 period universe contains 11,026 ordered fast<slow
combinations. EMA values are computed once per period and consecutive
observed session, then full strategy paper outcomes are evaluated only at
crossovers, gaps and verified end-of-day bars.

The evaluator is exclusively used inside the lower-priority research child.
It does not modify, read subscriptions from, or send commands to Dhan.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from itertools import combinations
from math import sqrt
from statistics import mean, stdev

import numpy as np

from . import trading_cockpit

MAX_PERIOD = 150
MIN_PERIOD = 2
ALL_PAIRS_COUNT = (MAX_PERIOD - MIN_PERIOD + 1) * (MAX_PERIOD - MIN_PERIOD) // 2
MIN_RANK_TRADES = 3


def all_supported_pairs() -> list[tuple[int, int]]:
    pairs = list(combinations(range(MIN_PERIOD, MAX_PERIOD + 1), 2))
    if len(pairs) != ALL_PAIRS_COUNT:
        raise AssertionError("EMA period universe count mismatch")
    return pairs


class FastSweep:
    """Exact sampled-index fill rules; no full-bar resimulation per pair."""

    def __init__(self, rows: list[dict], periods: set[int],
                 *, starting_capital: float = 50000, cost_bps: float = 5):
        from . import strategy_lab as lab
        self.lab = lab
        self.rows = rows
        self.starting_capital = starting_capital
        self.cost_bps = cost_bps
        n = len(rows)
        self.consecutive = np.zeros(n, dtype=np.bool_)
        for i in range(1, n):
            self.consecutive[i] = lab._contiguous(rows[i-1], rows[i])
        self.gaps = [i for i in range(1, n) if not self.consecutive[i]]
        self.eod = [
            i for i, row in enumerate(rows)
            if trading_cockpit._ts(row["timestamp_utc"]).astimezone(
                lab.IST).time().replace(tzinfo=None) == lab.SESSION_LAST
        ]
        self.eod_set = set(self.eod)
        self.opens = [row["open"] for row in rows]
        self.closes = [row["close"] for row in rows]
        self.timestamps = [trading_cockpit._ts(row["timestamp_utc"]) for row in rows]
        sections: list[tuple[int, int]] = []
        start = 0
        for gap in self.gaps:
            sections.append((start, gap))
            start = gap
        if n:
            sections.append((start, n))
        self.ema: dict[int, np.ndarray] = {}
        for p in sorted(periods):
            if p < MIN_PERIOD or p > MAX_PERIOD:
                raise ValueError("EMA period outside supported 2-150 range")
            out = np.full(n, np.nan, dtype=np.float64)
            for first, last in sections:
                closes = self.closes[first:last]
                values = trading_cockpit._ema(closes, p)
                if len(values) != len(closes):
                    raise ValueError("Inconsistent EMA source observations")
                out[first:last] = [
                    np.nan if x is None else x for x in values
                ]
            self.ema[p] = out

    def signals(self, fast: int, slow: int) -> tuple[list[tuple[int, int]], int]:
        first, second = self.ema[fast], self.ema[slow]
        n = len(first)
        up = np.zeros(n, dtype=np.bool_)
        down = np.zeros(n, dtype=np.bool_)
        if n > 1:
            # NaN warmup comparisons are False. No missing minute is stitched.
            up[1:] = (
                self.consecutive[1:] &
                (first[:-1] <= second[:-1]) &
                (first[1:] > second[1:])
            )
            down[1:] = (
                self.consecutive[1:] &
                (first[:-1] >= second[:-1]) &
                (first[1:] < second[1:])
            )
        events = np.flatnonzero(up | down).tolist()
        return [(i, 1 if up[i] else -1) for i in events], len(events)

    def score(self, fast: int, slow: int) -> dict:
        rows = self.rows
        n = len(rows)
        events, cross_count = self.signals(fast, slow)
        orders: dict[int, int] = {}
        unscored = Counter()
        for idx, direction in events:
            if idx in self.eod_set:
                continue  # EOD close overrides signal, matching baseline.
            if idx+1 < n and self.consecutive[idx+1]:
                orders[idx+1] = direction
            else:
                unscored["cross_without_next_original_open"] += 1

        cash = self.starting_capital
        high = cash
        drawdown = 0.
        position = None
        profit = []
        points_seen = []
        holdings = []

        def close(index: int, use_close: bool):
            nonlocal cash, high, drawdown, position
            if position is None:
                return
            price = self.closes[index] if use_close else self.opens[index]
            shares, entry, direction, entry_cost, from_idx = position
            points = (price-entry)*direction
            cost = price*shares*self.cost_bps/10000
            pnl = points*shares-entry_cost-cost
            cash += pnl
            high = max(high, cash)
            drawdown = max(drawdown,
                           (high-cash)/high*100 if high > 0 else 0.)
            # The canonical engine records *rounded* trade returns and
            # index point changes before computing profit factor/Sharpe.
            # Keep the ranking identical to its audited report, while
            # preserving unrounded capital for subsequent position sizing.
            profit.append(round(pnl, 2))
            points_seen.append(round(points, 4))
            holdings.append(round((self.timestamps[index] -
                                   self.timestamps[from_idx]).total_seconds()/60, 2))
            position = None

        # Only event times (not every minute for each EMA pair) are needed.
        for idx in sorted(set(orders)|set(self.gaps)|self.eod_set):
            if idx in self.gaps:
                if position is not None:
                    unscored["unclosed_on_missing_bar_or_session"] += 1
                    position = None
            desired = orders.get(idx)
            if desired is not None and (
                    position is None or position[2] != desired):
                if position is not None:
                    close(idx, False)
                if cash > 0:
                    entry = self.opens[idx]
                    units = cash/entry
                    position = (
                        units, entry, desired, units*entry*self.cost_bps/10000,
                        idx,
                    )
            if idx in self.eod_set:
                close(idx, True)
        if position is not None:
            unscored["open_position_at_truncated_history_end"] += 1

        wins = [p for p in profit if p > 0]
        losses = [p for p in profit if p < 0]
        trade_sharpe = None
        if len(profit) >= 3 and len({round(p, 6) for p in profit}) > 1:
            trade_sharpe = mean(profit)/stdev(profit)*sqrt(len(profit))
        profit_factor = sum(wins)/abs(sum(losses)) if losses else None
        rnd = self.lab._round
        return {
            "trade_count": len(profit),
            "crossovers": cross_count,
            "win_rate_pct": rnd(len(wins)/len(profit)*100, 2) if profit else None,
            "pnl_proxy_inr": rnd(cash-self.starting_capital, 2),
            "return_proxy_pct": rnd((cash/self.starting_capital-1)*100, 3),
            "ending_capital_proxy_inr": rnd(cash, 2),
            "index_points": rnd(sum(points_seen), 3),
            "max_closed_trade_drawdown_pct": rnd(drawdown, 3),
            "profit_factor": rnd(profit_factor, 3) if profit_factor is not None else None,
            "trade_sharpe_unannualized": rnd(trade_sharpe, 3)
                                        if trade_sharpe is not None else None,
            "avg_hold_minutes": rnd(mean(holdings), 2) if holdings else None,
            "unscored": dict(unscored),
        }
