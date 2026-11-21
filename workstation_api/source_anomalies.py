"""Read-only causal statistical and train-only ML checks of original price panels.

These detectors flag *candidates for source review*, not verified data errors,
tradable signals, or model accuracy. Source CSV, Dhan cache, and live recording
are never modified, fetched, or automatically repaired.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import research_insights, service

VERSION = "source_anomaly_audit_v1"
MAX_ASSETS = 8
MAX_DATES = 15000
MAX_EVENTS = 100
MIN_TRAIN = 80
MIN_HOLDOUT = 20
SYM = re.compile(r"^[A-Za-z0-9_.:-]{1,90}$")


def _ml_flags(returns: np.ndarray, row_numbers: np.ndarray, *, seed: int = 2026):
    """Fit only the earliest 70% of observed returns; score strictly later.

    The forest learns the observed training distribution. It does not learn
    which provider records are correct and is not a predictive return model.
    """
    if len(returns) < MIN_TRAIN + MIN_HOLDOUT:
        return {}, {"status": "not_enough_history", "train": 0, "holdout": 0}
    from sklearn.ensemble import IsolationForest

    features = []
    for index, value in enumerate(returns):
        trailing = np.abs(returns[max(0, index - 20):index])
        baseline = float(np.median(trailing)) if len(trailing) else 0.0
        features.append([float(value), abs(float(value)), baseline])
    matrix = np.asarray(features, dtype=float)
    split = int(len(matrix) * .70)
    if split < MIN_TRAIN or len(matrix) - split < MIN_HOLDOUT:
        return {}, {"status": "not_enough_history", "train": split,
                    "holdout": len(matrix)-split}
    forest = IsolationForest(
        n_estimators=64, contamination=.025,
        max_samples=min(256, split), random_state=seed, n_jobs=1,
    )
    forest.fit(matrix[:split])
    scores = forest.decision_function(matrix[split:])
    return {
        int(row_numbers[split + i]): round(float(score), 6)
        for i, score in enumerate(scores) if score < 0
    }, {
        "status": "trained_and_scored", "train": split,
        "holdout": len(matrix) - split,
        "holdout_only": True, "contamination_setting": .025,
        "seed": seed,
    }


def scan(dataset_id: str, *, symbol: str | None = None, max_assets: int = 6,
         max_events: int = 50, lookback: int = 60) -> dict:
    if not isinstance(max_assets, int) or not 1 <= max_assets <= MAX_ASSETS:
        raise ValueError("Select between 1 and 8 securities for a bounded scan")
    if not isinstance(max_events, int) or not 1 <= max_events <= MAX_EVENTS:
        raise ValueError("Select between 1 and 100 displayed events")
    if not isinstance(lookback, int) or not 30 <= lookback <= 120:
        raise ValueError("Causal return lookback must be 30–120 observations")
    folder, record = service.dataset_path(dataset_id)
    if not (record.get("has_daily_prices") or record.get("has_prices")):
        raise ValueError("No original prepared daily/monthly price panel to inspect")
    filename = "daily_prices.csv" if record.get("has_daily_prices") else "prices.csv"
    path = folder / filename
    if not path.is_file() or path.is_symlink():
        raise ValueError("Original price source unavailable or unsafe")
    columns = list(pd.read_csv(path, nrows=0).columns)
    if columns.count("date") != 1:
        raise ValueError("Price panel needs exactly one date column")
    symbols = [c for c in columns if c != "date"]
    if len(symbols) > 10000:
        raise ValueError("Unbounded source width")
    if symbol is not None:
        if not SYM.fullmatch(symbol) or symbol not in symbols:
            raise ValueError("Select an existing original price symbol")
        selected = [symbol]
    else:
        selected = symbols[:max_assets]
    if not selected:
        raise ValueError("No price symbols in prepared source")
    original = pd.read_csv(path, usecols=["date", *selected], nrows=MAX_DATES+1)
    if len(original) > MAX_DATES:
        raise ValueError("Source spans more than 15,000 dates; choose a smaller prepared source")
    dates = pd.to_datetime(original["date"], errors="coerce")
    if dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing:
        raise ValueError("Ambiguous, duplicated or nonchronological session dates; review source first")
    all_events: list[dict] = []
    per_asset = []
    forest_training = {}
    for ticker in selected:
        raw = pd.to_numeric(original[ticker], errors="coerce")
        values = raw.to_numpy(dtype=float)
        valid = np.isfinite(values) & (values > 0)
        # Invalid rows are reportable and cannot become a fabricated return.
        invalid = np.flatnonzero(~valid)
        for index in invalid:
            all_events.append({
                "symbol": ticker, "date": dates.iloc[index].date().isoformat(),
                "type": "invalid_or_missing_price", "severity": "source_review",
                "return_fraction": None, "robust_z": None, "forest_score": None,
                "reason": "Nonfinite, nonpositive or missing original close; never forward-filled",
            })
        row_ids = np.flatnonzero(valid[1:] & valid[:-1]) + 1
        # Adjacent original observations only: no leaps across unknown values.
        ret = np.log(values[row_ids] / values[row_ids-1])
        finite = np.isfinite(ret)
        row_ids = row_ids[finite]
        ret = ret[finite]
        forest_flags, training = _ml_flags(ret, row_ids)
        forest_training[ticker] = training
        robust = {}
        for k in range(20, len(ret)):
            historic = ret[max(0, k-lookback):k]
            med = float(np.median(historic))
            mad = float(np.median(np.abs(historic-med)))
            scale = max(1.4826*mad, 1e-6)
            score = float(abs(ret[k]-med)/scale)
            if score >= 6 or abs(math.expm1(float(ret[k]))) > .40:
                robust[int(row_ids[k])] = round(score, 3)
        highlighted = set(robust) | set(forest_flags)
        for index in sorted(highlighted):
            k = int(np.searchsorted(row_ids, index))
            ratio = float(math.expm1(float(ret[k])))
            reasons = []
            if index in robust:
                reasons.append("6-MAD trailing return deviation (past observations only)")
            if index in forest_flags:
                reasons.append("IsolationForest anomaly in unseen chronological holdout")
            all_events.append({
                "symbol": ticker, "date": dates.iloc[index].date().isoformat(),
                "type": "unusual_observed_return",
                "severity": "review_high" if abs(ratio) >= .40 else "review",
                "return_fraction": round(ratio, 8),
                "robust_z": robust.get(index),
                "forest_score": forest_flags.get(index),
                "reason": "; ".join(reasons),
            })
        per_asset.append({
            "symbol": ticker, "observed_prices": int(valid.sum()),
            "invalid_or_missing": int(len(invalid)),
            "eligible_adjacent_returns": int(len(ret)),
            "ml_train_observations": int(training["train"]),
            "ml_holdout_observations": int(training["holdout"]),
            "ml_status": training["status"],
            "review_candidates": len(invalid) + len(highlighted),
        })
    all_events.sort(key=lambda e: (
        e["severity"] != "source_review",
        e["severity"] != "review_high",
        -(abs(e["return_fraction"]) if e["return_fraction"] is not None else 0),
        e["symbol"], e["date"],
    ))
    return {
        "dataset_id": dataset_id, "dataset_label": record.get("label", dataset_id),
        "source_file": filename,
        "source_sha256": research_insights.file_sha256(path),
        "as_of_utc": datetime.now(timezone.utc).isoformat(),
        "detector": VERSION, "frequency": "daily" if filename.startswith("daily") else "monthly",
        "method": {
            "trailing_robust": "One-sided rolling median / MAD of log returns; prior observations only",
            "unsupervised_ml": "IsolationForest trained only on first 70% of eligible returns; "
                               "out-of-sample anomaly scores on later 30%",
            "original_bytes_modified": False, "provider_requests": False,
            "inference": "Unsupervised statistical deviations, NOT verified source corruption",
        },
        "inspected_assets": per_asset,
        "source_assets_total": len(symbols),
        "assets_not_assessed": len(symbols) - len(selected),
        "price_rows": len(original), "lookback_returns": lookback,
        "candidate_count": len(all_events),
        "events": all_events[:max_events],
        "events_not_displayed": max(0, len(all_events) - max_events),
        "limitations": [
            "Unadjusted closes, stock splits, dividends, extraordinary events and "
            "thinly traded assets can legitimately create outlier scores.",
            "The ML model fits one early chronological segment and scores later rows. "
            "Without labeled source errors there is NO precision/recall certification.",
            "This bounded scan does not inspect every instrument by default and "
            "cannot verify NSE holidays or total returns.",
            "Price rows are never changed; review flagged original records with the provider."
        ],
        "ready": True,
    }
