"""Source-safe, read-only plans for the unified Market Data Workspace.

A GET only inspects the existing local catalog and source receipts. No broker
or public-source download happens until an explicit approved POST. The legacy
Dhan batch engine remains the one and only original-candle writer.
"""
from __future__ import annotations

from datetime import date, timedelta
from hashlib import sha256
import json
import math
import os
import re

from . import dhan_workspace, model_data_manager, model_registry, pit_index, service

SELECTIONS = frozenset({"nifty50_pit", "banknifty_pit", "watchlist", "all_nse", "all_bse"})
INTERVALS = frozenset({None, 1, 5, 15, 25, 60})
SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,29}$")
MAX_STOCKS = 6000


def _names(tickers: list[str] | None) -> list[str]:
    if tickers is None:
        tickers = []
    if not isinstance(tickers, list) or len(tickers) > MAX_STOCKS:
        raise ValueError("Choose at most 6000 stock symbols.")
    names = list(dict.fromkeys(str(t).strip().upper() for t in tickers))
    if any(not SYMBOL.fullmatch(name) for name in names):
        raise ValueError("Enter exact exchange trading symbols, separated by commas or lines.")
    return names


def _dates(start: str, stop: str, interval: int | None) -> tuple[date, date]:
    try:
        first, last = date.fromisoformat(start), date.fromisoformat(stop)
    except (TypeError, ValueError) as exc:
        raise ValueError("Choose valid start and end dates.") from exc
    if first >= last or last > date.today() + timedelta(days=1):
        raise ValueError("The end date must follow the start and cannot be in the future.")
    if (last - first).days > 365 * 30:
        raise ValueError("Select at most 30 calendar years of history.")
    if interval not in INTERVALS:
        raise ValueError("Select daily or a supported Dhan candle interval.")
    if interval is not None and first < date.today() - timedelta(days=365 * 5 + 2):
        raise ValueError("Dhan intraday history supports only the latest five years.")
    return first, last


def _model_requirements(model_id: str) -> dict | None:
    if not model_id:
        return None
    spec = model_registry.CATALOG.get(model_id)
    if spec is None:
        raise ValueError("Choose a registered mathematical model.")
    if spec["mode"] != "historical":
        return {"model_id": model_id, "title": spec["title"], "mode": spec["mode"],
                "note": "This model does not require historical equity candles. "
                        "Use Model Laboratory for its actual input type."}
    req = model_data_manager.requirement(model_id)
    return {"model_id": model_id, "title": spec["title"],
            "mode": spec["mode"], "minimum": req["min_returns"],
            "preferred": req["target_returns"],
            "buffer": req["buffer_fraction"],
            "note": "The +20% target is an observed-return target, not a calendar-day "
                    "guarantee. Exact model readiness is checked after preparation."}


def plan(selection: str, from_date: str, to_date: str,
         interval: int | None = None, tickers: list[str] | None = None,
         model_id: str = "") -> dict:
    if selection not in SELECTIONS:
        raise ValueError("Choose NIFTY 50, BANK NIFTY, named stocks, or an advanced exchange universe.")
    first, last = _dates(from_date, to_date, interval)
    names = _names(tickers)
    if selection != "watchlist" and names:
        raise ValueError("Stock symbols are only applicable to a custom stock list.")
    requirements = _model_requirements(model_id)
    actions: list[dict] = []
    warnings: list[str] = []
    blockers: list[str] = []
    resolved = 0
    unresolved: list[dict] = []
    membership: dict = {"state": "not_required"}
    token_present = bool(os.getenv("DHAN_ACCESS_TOKEN", "").strip())
    master = service.DATA / "dhan" / "instrument_master.csv"
    master_ready = master.is_file() and not master.is_symlink()
    source_stamp = (
        str(master.stat().st_mtime_ns) + ":" + str(master.stat().st_size)
        if master_ready else "missing"
    )
    if not token_present:
        blockers.append("Connect Dhan historical Data API before downloading.")
        actions.append({"kind": "connect_dhan", "label": "Connect Dhan"})
    if not master_ready:
        blockers.append("The local stock catalog is not available.")
        actions.append({"kind": "refresh_catalog", "label": "Get instrument catalog"})
    historical = selection in pit_index.MODES
    try:
        current_membership = pit_index.status() if historical else {}
    except (ValueError, OSError, KeyError, json.JSONDecodeError):
        current_membership = {"available": False}
    membership_revision = str(current_membership.get("source_commit", "missing"))
    if historical:
        covered = str(current_membership.get("covered_through") or "")
        earliest = str(current_membership.get("first_date") or "")
        window_covered = bool(current_membership.get("available") and covered and
                              (last <= date.fromisoformat(covered) + timedelta(days=1)) and
                              earliest and first >= date.fromisoformat(earliest))
        membership = {"state": "ready" if window_covered else "needs_source",
                      "covered_through": covered or None, "earliest": earliest or None}
        if not window_covered:
            blockers.append("Historical index membership does not cover the requested dates.")
            actions.append({"kind": "sync_membership", "label": "Update historical index membership"})
        if window_covered and master_ready:
            try:
                index = pit_index.query(selection, from_date, to_date, dhan_workspace.catalog())
                resolved = int(index["resolved_count"])
                unresolved = [
                    {"symbol": item["symbol"], "reason": item["reason"]}
                    for item in index["unresolved"]
                ]
                membership["union_count"] = int(index["union_count"])
                membership["changes"] = int(index["change_count"])
            except (OSError, ValueError, KeyError) as exc:
                blockers.append("Historical constituents could not be matched safely: " + str(exc)[:150])
                actions.append({"kind": "review_mapping", "label": "Review instrument mappings"})
    elif master_ready:
        try:
            instruments = dhan_workspace._choose(
                selection, [], names if selection == "watchlist" else [])
            resolved = len(instruments)
        except (OSError, ValueError, KeyError) as exc:
            blockers.append("Instrument selection needs attention: " + str(exc)[:180])
            actions.append({"kind": "review_tickers", "label": "Review stock symbols"})
    if selection == "watchlist" and not names:
        blockers.append("Add at least one stock before continuing.")
    if resolved == 0 and not blockers:
        blockers.append("No instruments resolved; no download can be started.")
    if len(unresolved) > 0:
        warnings.append(
            str(len(unresolved)) + " historical members have no exact current Dhan Security ID. "
            "You can review gaps or explicitly approve an incomplete dataset.")
    if resolved > 100:
        warnings.append("Large download: " + str(resolved) +
                        " instruments require an additional scope confirmation.")
    if requirements and requirements["mode"] != "historical":
        warnings.append(requirements["note"])
    if requirements and requirements["mode"] == "historical":
        # Conservative calendar estimate, NOT NSE-trading-day validation.
        recommended_days = math.ceil((requirements["preferred"] + 1) * 7 / 5 * 1.25) + 18
        recommended = last - timedelta(days=recommended_days)
        requirements["suggested_from"] = recommended.isoformat()
        if first > recommended:
            warnings.append("Your dates may provide fewer than the model's preferred " +
                            str(requirements["preferred"]) + " observed returns (+20%).")
    # This intentionally does not claim a precise number of uncached vendor requests.
    # Actual Dhan checkpoint manifests decide which exact ranges are fetched.
    estimate = resolved * math.ceil((last - first).days / (365 if interval is None else 90))
    locked = {
        "selection": selection, "from_date": from_date, "to_date": to_date,
        "interval": interval, "tickers": names, "model_id": model_id,
        "master_stamp": source_stamp, "membership_revision": membership_revision,
        "resolved": resolved, "unresolved": unresolved, "day": date.today().isoformat(),
    }
    receipt = sha256(json.dumps(locked, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False).encode("utf-8")).hexdigest()
    return {"selection": selection, "from_date": from_date, "to_date": to_date,
            "interval": interval, "tickers": names, "model_id": model_id,
            "model_requirements": requirements, "membership": membership,
            "instrument_count": resolved, "unresolved": unresolved[:100],
            "unresolved_count": len(unresolved),
            "warnings": warnings, "blockers": blockers, "next_actions": actions,
            "can_start": not blockers, "preview_token": receipt,
            "estimated_request_upper_bound": estimate,
            "estimate_note": "Conservative total request upper bound before cache reuse; "
                             "not a vendor quote. Existing verified candles are reused.",
            "dhan": {"token_present": token_present,
                     "catalog_available": master_ready,
                     "credential_verified": False,
                     "note": "Token presence does not prove access. Live Data API preflight "
                             "is required before starting."},
            "provider_policy": "Dhan primary. Zerodha fallback is currently eligible only "
                               "for explicitly approved, source-matched model-data "
                               "extensions, not general universe downloads.",
            "read_only": True}


def approve(expected_token: str, selection: str, from_date: str, to_date: str,
            interval: int | None, tickers: list[str] | None,
            model_id: str, *, allow_incomplete: bool, confirm_bulk: bool) -> dict:
    current = plan(selection, from_date, to_date, interval, tickers, model_id)
    if not isinstance(expected_token, str) or expected_token != current["preview_token"]:
        raise ValueError("The source plan changed. Review it again before downloading.")
    if not current["can_start"]:
        raise ValueError("Resolve the listed source requirements before downloading.")
    if current["unresolved_count"] and not allow_incomplete:
        raise ValueError("Confirm that historical instrument gaps make this dataset incomplete.")
    if current["instrument_count"] > 100 and not confirm_bulk:
        raise ValueError("Confirm the scope of this large download.")
    return current
