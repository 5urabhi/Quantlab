"""Paper-only, receipt-causal forecasts from explicitly pinned candidates."""
from contextlib import closing
from datetime import timedelta, timezone
from hashlib import sha256
import json
import math
import sqlite3

from . import alpha_model_registry as registry, constituent_alpha as alpha
from . import constituent_prospective as prospective, replay_storage

MAX_FORECAST_AGE_SECONDS = 90
HORIZONS = (5, 10, 15, 30, 60)


def validate_candidate(model_id, now):
    value = registry.load(model_id)
    horizon = value["horizon_minutes"]
    session = prospective._session(now).date().isoformat()
    if (value["source"] != "prospective" or horizon not in HORIZONS
            or value["source_policy_sha256"] != alpha.policy_for(horizon)
            or value["live_approved"] is not False
            or max(value["reference_holdout_dates"]) >= session
            or value["feature_key"] not in ("index", "full")
            or value["classes"] != list(alpha.CLASSES)):
        raise ValueError("Select a receipt-based frozen candidate assessed before this session")
    return value


def _feature_rows(db, now, horizon):
    now = now.astimezone(timezone.utc)
    day = prospective._session(now).date().isoformat()
    # At most 33 minute slots, including the 30-minute feature anchor and
    # a possible preceding slot. Do not even read outcome columns.
    start = now.replace(second=0, microsecond=0) - timedelta(minutes=32)
    columns = ("slot_utc", "session_ist", "cutoff_utc", "decided_utc",
               "target_utc", "horizon_minutes", "reference_price",
               "reference_sha256", "pressure", "volume_pressure", "ema_rsi", "evidence_json")
    rows = replay_storage.fetchall(db, "SELECT " + ",".join(columns) + """
        FROM banknifty_paired_signals
        WHERE protocol_hash=? AND horizon_minutes=? AND session_ist=?
        AND slot_utc>=? AND slot_utc<=? AND decided_utc<=? AND cutoff_utc<=?
        ORDER BY slot_utc LIMIT 34""",
        (prospective.protocol_for(horizon), horizon, day, start.isoformat(),
         now.isoformat(), now.isoformat(), now.isoformat()))
    if len(rows) > 33:
        raise ValueError("Unexpected duplicate forecast ledger slots")
    return [dict(zip(columns, row)) for row in rows]


def forecast(model_id, now, *, read_rows=None):
    """Return a fresh scored feature snapshot or an explicit unavailable state."""
    try:
        model = validate_candidate(model_id, now)
        if read_rows is None:
            with closing(alpha._read()) as db:
                rows = _feature_rows(db, now, model["horizon_minutes"])
        else:
            rows = read_rows(now, model["horizon_minutes"])
        samples, _ = alpha.sample_day(rows, features_only=True, as_of=now)
        if not samples:
            return {"state": "unavailable", "reason": "missing_matched_features", "model_id": model_id}
        sample = samples[-1]
        receipt = alpha._stamp(sample["decision_utc"])
        cutoff = alpha._stamp(sample["cutoff_utc"])
        age = (now - cutoff).total_seconds()
        if (not 0 <= age <= MAX_FORECAST_AGE_SECONDS or receipt > now
                or alpha._stamp(sample["target_utc"]) <= now):
            return {"state": "unavailable", "reason": "stale_or_expired_forecast", "model_id": model_id}
        probs = registry.predict(model, [sample])[0].tolist()
        if (len(probs) != 3 or any(not math.isfinite(x) or not 0 <= x <= 1 for x in probs)
                or abs(sum(probs) - 1) > 1e-8):
            raise ValueError("Invalid forecast probabilities")
        digest = sha256(json.dumps(sample, sort_keys=True, allow_nan=False,
                                   separators=(",", ":")).encode()).hexdigest()
        call = alpha._call(probs)
        return {"state": "available", "model_id": model_id, "horizon_minutes": model["horizon_minutes"],
                "decision_utc": sample["decision_utc"], "cutoff_utc": sample["cutoff_utc"],
                "target_utc": sample["target_utc"], "evaluated_utc": now.isoformat(),
                "feature_sha256": digest, "reference_sha256": sample["reference_sha256"],
                "p_down": probs[0], "p_flat": probs[1], "p_up": probs[2],
                "direction": "UP" if call == 1 else "DOWN" if call == -1 else "ABSTAIN"}
    except (ValueError, OSError, KeyError, TypeError, sqlite3.Error, OverflowError, IndexError):
        return {"state": "unavailable", "reason": "candidate_or_source_unavailable", "model_id": model_id}


def reversal(entry_direction, result, now, entry_received_utc):
    if not result or result.get("state") != "available":
        return False
    if entry_direction not in ("UP", "DOWN"):
        return False
    try:
        decision = alpha._stamp(result["decision_utc"])
        cutoff = alpha._stamp(result["cutoff_utc"])
        target = alpha._stamp(result["target_utc"])
        entry = alpha._stamp(entry_received_utc)
        # A forecast from before the conditional fill is not fresh exit evidence.
        if not entry <= cutoff <= decision <= now < target:
            return False
        if not 0 <= (now - cutoff).total_seconds() <= MAX_FORECAST_AGE_SECONDS:
            return False
        probabilities = [result["p_down"], result["p_flat"], result["p_up"]]
        if any(not math.isfinite(x) or not 0 <= x <= 1 for x in probabilities) or abs(sum(probabilities)-1)>1e-8:
            return False
        opposite = -1 if entry_direction == "UP" else 1
        return alpha._call(probabilities) == opposite and result["direction"] == ("DOWN" if opposite == -1 else "UP")
    except (KeyError, ValueError, TypeError):
        return False
