"""Source-bound transaction-friction scenario on an archived index experiment.

This is a hypothetical incremental-cost sensitivity calculation, not market
depth reconstruction or realized fills. Preserves the saved gross returns and
original transaction costs. Applies extra assumed fees/spreads/square-root
impact to observed saved monthly turnover; never silently replaces original
gross/net performance or charges the original base cost twice.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import io
import math

import numpy as np
import pandas as pd

from . import service

MAX_ROWS = 1200


def _read(file: Path) -> tuple[pd.DataFrame, str]:
    if not file.is_file() or file.is_symlink() or file.stat().st_size > 10_000_000:
        raise ValueError("Saved observed monthly return evidence is unavailable or oversized")
    raw = file.read_bytes()
    if len(raw)>10_000_000:
        raise ValueError('Saved monthly returns exceed read limit')
    digest = sha256(raw).hexdigest()
    frame = pd.read_csv(io.BytesIO(raw))
    required = {"date", "strategy_net", "strategy_gross", "benchmark",
                "turnover", "transaction_cost_fraction"}
    if not required.issubset(frame.columns) or not 2 <= len(frame) <= MAX_ROWS:
        raise ValueError("Saved result lacks a complete bounded original monthly return record")
    dates = pd.to_datetime(frame["date"], errors="raise")
    if (dates.isna().any() or dates.duplicated().any() or
            not dates.is_monotonic_increasing):
        raise ValueError("Archived return dates must be unique and strictly increasing")
    names = sorted(required-{"date"})
    for col in names:
        frame[col] = pd.to_numeric(frame[col], errors="raise")
    values = frame[names].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("Archived monthly research contains nonfinite returns/costs")
    if (frame[["strategy_net","strategy_gross","benchmark"]].le(-1).any().any()
            or frame["turnover"].lt(0).any()
            or frame["turnover"].gt(2+1e-8).any()
            or frame["transaction_cost_fraction"].lt(0).any()
            or frame["transaction_cost_fraction"].ge(1).any()):
        raise ValueError("Archived research has invalid gross return or cost convention")
    implied = (1-frame["transaction_cost_fraction"])*(1+frame["strategy_gross"])-1
    if not np.allclose(implied.to_numpy(),
                       frame["strategy_net"].to_numpy(), rtol=1e-8, atol=1e-8):
        raise ValueError("Saved net returns do not reconcile with gross returns "
                         "and base transaction costs")
    frame["date"] = dates.dt.date.astype(str)
    return frame, digest


def calculate(run_id: str, *, extra_fee_bps: float = 0.,
              extra_half_spread_bps: float = 5.,
              impact_coefficient_bps: float = 40.,
              assumed_participation: float = .02) -> dict:
    params = {
        "extra_fee_bps": extra_fee_bps,
        "extra_half_spread_bps": extra_half_spread_bps,
        "impact_coefficient_bps": impact_coefficient_bps,
        "assumed_participation": assumed_participation,
    }
    if (not all(isinstance(v,(float,int)) and not isinstance(v,bool) and
                math.isfinite(v) for v in params.values())
            or not 0 <= extra_fee_bps <= 250
            or not 0 <= extra_half_spread_bps <= 250
            or not 0 <= impact_coefficient_bps <= 500
            or not 0 <= assumed_participation <= .20):
        raise ValueError("Bound execution friction to nonnegative fees/spread/impact "
                         "and 0–20% assumed participation")
    folder = service._run_path(run_id)
    results, original_digest = _read(folder / "monthly_results.csv")
    for name in ("research_manifest.json","workstation_run.json"):
        p=folder/name
        if p.is_symlink() or not p.is_file() or p.stat().st_size>4_000_000:
            raise ValueError("Missing or unsafe saved run manifest")
    metadata = service._json(folder / "research_manifest.json")
    status = service._json(folder / "workstation_run.json")
    if not metadata or not status or not metadata.get("input_sha256"):
        raise ValueError("Archived run needs a real source fingerprint and saved configuration")
    extra_bps = (extra_fee_bps + extra_half_spread_bps +
                 impact_coefficient_bps*math.sqrt(assumed_participation))
    gross = results["strategy_gross"].to_numpy(dtype=float)
    turnover = results["turnover"].to_numpy(dtype=float)
    base_cost = results["transaction_cost_fraction"].to_numpy(dtype=float)
    extra_cost = turnover*extra_bps/10000
    combined = base_cost + extra_cost
    if not np.isfinite(combined).all() or np.any(combined>=1):
        raise ValueError("Hypothetical additional execution friction exceeds capital")
    stressed = (1.-combined)*(1.+gross)-1.
    original = results["strategy_net"].to_numpy(dtype=float)
    baseline = results["benchmark"].to_numpy(dtype=float)
    stressed_wealth = np.cumprod(1+stressed)
    original_wealth = np.cumprod(1+original)
    benchmark_wealth = np.cumprod(1+baseline)
    if any(not np.isfinite(v).all() for v in (stressed_wealth,original_wealth,benchmark_wealth)):
        raise ValueError('Compounded scenario is outside finite numerical range')
    stressed_drawdown = stressed_wealth/np.maximum.accumulate(
        np.r_[1., stressed_wealth])[1:]-1.
    def as_float(x):
        return float(x)
    return {
        "run_id":run_id,
        "original_monthly_sha256":original_digest,
        "archived_source_sha256":metadata["input_sha256"],
        "dataset_id":status.get("dataset_id"),
        "evidence_class":"synthetic_fixture" if status.get("dataset_kind")=="synthetic"
                         else "archived_market_observations_not_independently_certified",
        "parameters":params,"incremental_per_turnover_bps":extra_bps,
        "original_base_cost_preserved":True,
        "model":"additional_weight_change_cost_fraction = observed_gross_turnover "
                "* (extra_fee_bps + extra_half_spread_bps + impact_coefficient_bps "
                "* sqrt(assumed_participation)) / 10000",
        "observations":len(results),
        "metrics":{
            "original_compounded_net_return":as_float(original_wealth[-1]-1),
            "stressed_compounded_net_return":as_float(stressed_wealth[-1]-1),
            "benchmark_compounded_return":as_float(benchmark_wealth[-1]-1),
            "incremental_compounded_return_drag":
                as_float(stressed_wealth[-1]-original_wealth[-1]),
            "mean_incremental_monthly_cost_fraction":as_float(np.mean(extra_cost)),
            "stressed_max_drawdown":as_float(np.min(stressed_drawdown)),
            "total_incremental_cost_fraction_sum":as_float(np.sum(extra_cost)),
        },
        "rows":[{
            "date":date,
            "original_strategy_net":as_float(original[i]),
            "hypothetical_stressed_net":as_float(stressed[i]),
            "benchmark":as_float(baseline[i]),
            "observed_turnover":as_float(turnover[i]),
            "saved_base_cost_fraction":as_float(base_cost[i]),
            "extra_modeled_cost_fraction":as_float(extra_cost[i]),
            "total_modeled_cost_fraction":as_float(combined[i]),
            "original_wealth":as_float(original_wealth[i]),
            "stressed_wealth":as_float(stressed_wealth[i]),
            "benchmark_wealth":as_float(benchmark_wealth[i]),
        } for i,date in enumerate(results["date"])],
        "execution_fills_observed":False,"exchange_taxes_verified":False,
        "capacity_verified":False,"historical_source_independently_verified":False,
        "warnings":[
            "Scenario is incremental to the original archived transaction cost. "
            "Set assumptions ONLY for costs not already included in that saved run.",
            "Flat monthly assumed participation is not actual date-security-specific ADV.",
            "No lots, short selling, partial fills, intraday slippage, exchange taxes "
            "or order-routing timestamps are manufactured from monthly turnover.",
            "Original source hash is archived, not independent market-data approval; "
            "strategy training or frozen final-test eligibility is unchanged.",
        ],
    }
