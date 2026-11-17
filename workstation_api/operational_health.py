"""Read-only, bounded, actionable QuantLab operational health dashboard.

Never performs broker requests, SQL writes, automatic source repairs, or
credential disclosures. A missing local database is a not-initialized state,
not a failure or an assertion that market data is complete.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import shutil
import sqlite3

from . import (columnar_cache, database_inspector, dhan_workspace,
               materialized_view_recovery, research_library, service, zerodha_fallback)

MIN_FREE_BYTES = 500 * 1024 * 1024


def status() -> dict:
    databases = []
    blockers = []
    warnings = []
    for name, descriptor in database_inspector.DATABASES.items():
        try:
            path = database_inspector._path(name)
            if not path.is_file():
                databases.append({"id": name, "label": descriptor["label"],
                                  "state": "not_initialized", "size_bytes": 0})
                continue
            if path.is_symlink():
                raise ValueError("Unsafe symlink at original database path")
            with database_inspector._read_only(name) as connection:
                integrity = connection.execute("PRAGMA quick_check(1)").fetchone()
            valid = bool(integrity and integrity[0] == "ok")
            databases.append({"id": name, "label": descriptor["label"],
                              "state": "ok" if valid else "integrity_error",
                              "size_bytes": path.stat().st_size})
            if not valid:
                blockers.append({"component": name, "kind": "database_integrity",
                                 "action": "Stop research writes and recover from a known-good local backup. "
                                           "Never overwrite original market observations."})
        except (OSError, ValueError, sqlite3.Error):
            databases.append({"id": name, "label": descriptor["label"],
                              "state": "unreadable"})
            blockers.append({"component": name, "kind": "database_access",
                             "action": "Check local file permissions and metadata; do not run source repair."})
    try:
        disk = shutil.disk_usage(service.DATA if service.DATA.exists()
                                 else service.DATA.parent)
        if disk.free < MIN_FREE_BYTES:
            warnings.append({"kind": "disk_space",
                             "message": "Less than 500 MiB remains. Pause large downloads or "
                                        "move source files using the recovery-safe data manager."})
        storage = {"free_bytes": disk.free, "total_bytes": disk.total,
                   "low_space": disk.free < MIN_FREE_BYTES}
    except OSError:
        storage = {"free_bytes": None, "total_bytes": None,
                   "low_space": None}
        warnings.append({"kind": "disk_unavailable",
                         "message": "Local free space could not be measured."})
    try:
        history = research_library.list_job_history(100)
        failures = sum(r["status"] in ("error","interrupted") for r in history)
    except (OSError, sqlite3.Error, ValueError):
        failures = None
        warnings.append({"kind":"job_history",
                         "message":"Saved job history is unavailable; check Research Workspace."})
    try:
        batches = dhan_workspace.list_batches()
        interrupted = sum(b["status"]=="interrupted" for b in batches)
        paused = sum(b["status"]=="paused" for b in batches)
    except (OSError, ValueError):
        interrupted = paused = None
        warnings.append({"kind":"dhan_batch_catalog",
                         "message":"Saved Dhan batch manifests are unavailable."})
    try:
        cache = columnar_cache.status()
        if cache["built"] and not cache["ready"]:
            warnings.append({"kind":"columnar_cache",
                             "message":"The optional analytical cache is stale or unavailable. "
                                       "Models use validated original CSV until it is rebuilt."})
    except (ValueError, OSError, sqlite3.Error):
        cache={"state":"unavailable","ready":False}
        warnings.append({"kind":"columnar_cache",
                         "message":"Columnar acceleration status could not be inspected."})
    try:
        views = materialized_view_recovery.inspect()
        if views["state"] == "needs_rebuild":
            warnings.append({
                "kind": "shared_price_views",
                "message": "Shared research price views need repair: " + views["reason"]
                           + " Use Check & repair safely in Database Manager."})
        elif views["state"] == "blocked":
            blockers.append({
                "component": "shared_price_views", "kind": "unsafe_original_or_view",
                "action": views["reason"] + " Review original source before repair."})
        elif views["state"] == "verification_deferred":
            warnings.append({
                "kind": "shared_price_views",
                "message": "Large shared price views require a full checksum check "
                           "through Database Manager maintenance."})
    except (ValueError, OSError, sqlite3.Error):
        views = {"state": "unavailable", "verified_content": False}
        warnings.append({"kind": "shared_price_views",
                         "message": "Cannot inspect derived shared research price views."})
    # Auth flags are local presence checks, NOT requests to Kite/Dhan.
    try:
        kite = zerodha_fallback.status()
        kite_info={"app_configured": kite["api_key_configured"] and
                                   kite["api_secret_configured"],
                   "local_session_present": kite["token_present"],
                   "master_current": kite["master_current"],
                   "historical_entitlement_verified": False}
    except (ValueError, OSError):
        kite_info={"app_configured":False,"local_session_present":False,
                   "master_current":False,
                   "historical_entitlement_verified":False}
    return {
        "checked_utc":datetime.now(timezone.utc).isoformat(),
        "overall_state":("needs_repair" if blockers else "needs_attention"
                         if warnings else "operational"),
        "read_only":True,"market_data_certified":False,
        "databases":databases,"storage":storage,
        "job_failures_or_interrupted":failures,
        "dhan_interrupted_batches":interrupted,
        "dhan_paused_batches":paused,
        "columnar":cache,"kite":kite_info,"derived_views":views,
        "blockers":blockers,"warnings":warnings,
        "note":"A green operational check does not validate historical market data, "
               "broker entitlement, index research methodology or profitability.",
    }
