"""Model-driven acquisition planning for the shared QuantLab data pipeline.

Every model uses the existing authoritative readiness calculations. This
module adds a stable browser plan + confirmation receipt; it never guesses
historical securities, silently substitutes benchmark kinds, or calls a
broker provider during a GET. Cached Dhan candles are the first fallback;
only uncovered windows can be requested from authorized Dhan after consent.
"""
from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
import sqlite3

from . import data_orchestrator, model_data_manager, model_registry, service

PARAMETERS = frozenset({"assets", "train_window", "target", "ticker", "quote"})
SINGLE = frozenset({"gbm_fit", "ou_fit", "merton_fit", "heston_proxy"})


def _settings(model_id: str, params: dict | None) -> dict:
    if model_id not in model_registry.CATALOG:
        raise ValueError("Unknown registered model")
    if not isinstance(params, dict):
        raise ValueError("Model parameters must be an object")
    unknown = set(params) - PARAMETERS
    if unknown:
        raise ValueError("Unsupported acquisition parameters: " + ", ".join(sorted(unknown)))
    spec = model_registry.CATALOG[model_id]
    known = {p["key"] for p in spec["parameters"]}
    chosen = {k: v for k, v in params.items() if k in known}
    if "assets" in known and "assets" not in chosen:
        chosen["assets"] = 8
    if "train_window" in known and "train_window" not in chosen:
        chosen["train_window"] = 60
    if model_id in SINGLE:
        chosen["target"] = str(chosen.get("target") or
                               ("benchmark_tri" if model_id == "gbm_fit" else "stock"))
        chosen["ticker"] = str(chosen.get("ticker") or "")
    if "quote" in known:
        chosen["quote"] = str(chosen.get("quote") or "")
    # Readiness must work before a stock has been selected. The actual
    # executor still requires a real, exact symbol and never auto-chooses one.
    validation = dict(chosen)
    if model_id in SINGLE and validation.get("target") == "stock" and not validation.get("ticker"):
        validation["ticker"] = "SELECTION_PENDING"
    model_registry.validate_parameters(model_id, validation)
    return chosen


def _sources() -> list[dict]:
    candidates = []
    # Source discovery is metadata-only: no untrusted file contents or
    # arbitrary path/SQL queries in the selection UI.
    for source in service.datasets(include_archived=False)[:80]:
        if source["kind"] == "synthetic":
            continue
        if not source.get("has_prices"):
            continue
        candidates.append({
            "dataset_id": source["id"],
            "label": source["label"],
            "daily_prices": bool(source.get("has_daily_prices")),
            "original_dhan": source["kind"] == "dhan",
            "files_ready": bool(source["ready"]),
            "basis": source.get("basis", "")[:180],
        })
    return candidates


def _receipt(model_id: str, dataset_id: str | None, params: dict,
             result: dict) -> str:
    # A stale preview must not authorize a changed source, instrument or
    # download window. The actual executor additionally re-checks mappings.
    locked = {
        "model": model_id, "source": dataset_id, "params": params,
        "as_of": date.today().isoformat(),
        "status": result.get("status"),
        "runnable": result.get("runnable"),
        "selected_assets": result.get("selected_assets"),
        "selected_ticker": result.get("selected_ticker"),
        "start": result.get("suggested_start"),
        "end": result.get("suggested_end_exclusive"),
        "missing_minimum": result.get("missing_minimum"),
        "missing_to_target": result.get("missing_to_target"),
        "cached_days": result.get("cached_instrument_calendar_days"),
        "missing_windows": result.get("missing_uncovered_windows"),
        "vendor_requests": result.get("estimated_vendor_daily_requests"),
    }
    payload = json.dumps(locked, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False)
    return sha256(payload.encode("utf-8")).hexdigest()


def plan(model_id: str, dataset_id: str | None = None,
         params: dict | None = None, *, with_sources: bool = True) -> dict:
    settings = _settings(model_id, params)
    model = model_registry.CATALOG[model_id]
    selected_id = dataset_id or None
    measured = model_data_manager.inspect(model_id, selected_id, settings)
    action = model_data_manager.recommend_next_action(measured)
    available = _sources() if with_sources else []
    mode = model["mode"]
    raw_requests = measured.get("estimated_vendor_daily_requests")
    can_acquire = mode == "historical" and bool(measured.get("can_download"))
    if mode in {"synthetic", "theoretical"}:
        phase = "run_without_market_data"
    elif mode == "market":
        phase = "use_quote" if measured.get("runnable") else "original_quote_required"
    elif not selected_id:
        phase = "choose_dataset"
    elif measured.get("runnable") and not measured.get("missing_to_target"):
        phase = "ready"
    elif can_acquire:
        phase = "reuse_cache" if raw_requests == 0 else "download_missing"
    elif measured.get("runnable"):
        phase = "minimum_ready"
    else:
        phase = "blocked"
    chain = [
        {"id": "selected_dataset", "label": "Selected original data",
         "state": "available" if selected_id else "choose_source",
         "detail": "Never substitute an unselected stock or benchmark."},
        {"id": "dhan_cache", "label": "SHA-checked local Dhan candle cache",
         "state": "eligible" if can_acquire else "not_applicable",
         "detail": "Reuse identical exchange-segment and Security ID observations."},
        {"id": "dhan_api", "label": "Authorized read-only Dhan historical API",
         "state": ("requires_confirmation" if can_acquire and raw_requests else
                   "unneeded" if can_acquire else "incompatible_or_unavailable"),
         "detail": "Request only uncovered daily windows; provider credentials stay local."},
        {"id": "nse_mcp", "label": "NSE informational MCP",
         "state": "not_a_research_fallback",
         "detail": "Informational lookups are not a licensed historical/TRI replacement."},
    ]
    return {
        "model_id": model_id, "model_title": model["title"],
        "dataset_id": selected_id, "params": settings,
        "mode": mode, "phase": phase,
        "requirements": measured, "next_action": action,
        "candidate_datasets": available, "source_chain": chain,
        "can_acquire": can_acquire,
        "confirmation_required": can_acquire and raw_requests != 0,
        "estimated_new_dhan_requests": raw_requests or 0,
        "preview_token": _receipt(model_id, selected_id, settings, measured),
        "evidence_note": "Source completeness and +20% sample length are not "
                         "independent verification of historical investability.",
    }


def check_confirmation(model_id: str, dataset_id: str, params: dict,
                       preview_token: str, confirm_download: bool) -> dict:
    if not isinstance(preview_token, str) or len(preview_token) != 64:
        raise ValueError("Recheck the source plan before acquiring data")
    current = plan(model_id, dataset_id, params, with_sources=False)
    if current["preview_token"] != preview_token:
        raise ValueError("Data, mappings or requested dates changed. Review the latest plan.")
    if not current["can_acquire"]:
        raise ValueError(current["requirements"].get("download_explanation") or
                         "No compatible original data acquisition is available")
    if current["confirmation_required"] and not confirm_download:
        raise ValueError("Confirm the authorized read-only Dhan request")
    return current


def _record_event(status: str, model_id: str) -> None:
    # Activity logging must never turn a successfully validated download
    # into a failed job if its independent SQLite ledger is unavailable.
    try:
        data_orchestrator.event(
            "data_acquisition", status,
            "Rechecked original market data for " + model_id[:45])
    except (OSError, sqlite3.Error, ValueError):
        pass


def execute(model_id: str, dataset_id: str, params: dict | None = None,
            *, progress=None) -> dict:
    """Existing model engine remains the only downloader/validator."""
    try:
        result = model_data_manager.execute(
            model_id, dataset_id, params or {}, progress=progress)
    except (ValueError, OSError, RuntimeError):
        # No raw exception/vendor response is stored in the activity ledger.
        _record_event("blocked", model_id)
        raise
    _record_event(
        "complete" if result.get("status") in {"ready", "minimum_ready"} else "warning",
        model_id)
    return result
