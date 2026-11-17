"""Read-only verification and bounded repair of derived shared price views.

The SQLite daily_closes table is the source of truth. A crash between publishing
the two CSVs and the receipt can strand otherwise valid research history.
Only derived CSV/JSON views can be replaced; never silently rewrite raw vendor
candles, original database rows, PIT memberships, TRI, or research evidence.

A light health scan hashes small views; the explicit repair path verifies all
view bytes before deciding whether to reconstruct anything. Large repairs are
refused rather than risking disk exhaustion during Pandas materialization.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json
import os
import re
import shutil
import sqlite3

from . import database_inspector, shared_market_data

MAX_RECEIPT_BYTES = 2_000_000
MAX_LIGHT_HASH_BYTES = 32 * 1024 * 1024
MAX_AUTO_SOURCE_BYTES = 96 * 1024 * 1024
MAX_REPAIR_SOURCE_BYTES = 768 * 1024 * 1024
MIN_REPAIR_FREE_BYTES = 500 * 1024 * 1024
HASH = re.compile(r"^[0-9a-f]{64}$")
FILES = (("daily_prices.csv", "daily_sha256"),
         ("prices.csv", "monthly_sha256"))


def _hash(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect(*, verify_content: bool = False) -> dict:
    """Inspect current source-to-view contract without changing any file."""
    database = shared_market_data.database_path()
    folder = shared_market_data.shared_folder()
    base = {"state": "not_initialized", "source_rows": 0,
            "source_bytes": 0, "verified_content": False,
            "repairable": False, "reason": "No original shared market database yet."}
    if database.is_symlink() or database.parent.is_symlink():
        return {**base, "state": "blocked",
                "reason": "Unsafe symlink at the canonical database location."}
    if not database.is_file():
        return base
    if folder.is_symlink() or folder.parent.is_symlink():
        return {**base, "state": "blocked",
                "reason": "Unsafe symlink at the derived-view directory."}
    size = database.stat().st_size
    try:
        with database_inspector._read_only("market_data") as conn:
            result = conn.execute("PRAGMA quick_check(1)").fetchone()
            if not result or result[0] != "ok":
                raise ValueError("Original SQLite failed its integrity check.")
            n, latest = conn.execute(
                "SELECT COUNT(*), MAX(session_date) FROM daily_closes").fetchone()
    except (OSError, ValueError, sqlite3.Error):
        return {**base, "state": "blocked", "source_bytes": size,
                "reason": "Original SQLite is unreadable or failed integrity checks."}
    ready = {**base, "source_bytes": size, "source_rows": int(n)}
    if not n:
        return {**ready, "state": "no_observations",
                "reason": "The canonical database has no observed prices to publish."}

    for name, _ in FILES:
        path = folder / name
        if path.is_symlink():
            return {**ready, "state": "blocked",
                    "reason": "Derived-view path is a symlink: " + name}
    manifest = folder / "SHARED_MARKET_PROVENANCE.json"
    if manifest.is_symlink():
        return {**ready, "state": "blocked",
                "reason": "Derived provenance receipt is a symlink."}
    if (not manifest.is_file() or
            any(not (folder / name).is_file() for name, _ in FILES)):
        return {**ready, "state": "needs_rebuild", "repairable": True,
                "reason": "One or more generated price views/receipts are absent."}
    if manifest.stat().st_size > MAX_RECEIPT_BYTES:
        return {**ready, "state": "needs_rebuild", "repairable": True,
                "reason": "Derived provenance receipt exceeds the safe size limit."}
    try:
        receipt = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {**ready, "state": "needs_rebuild", "repairable": True,
                "reason": "Generated provenance receipt is unreadable."}
    if not isinstance(receipt, dict) or receipt.get("dataset_id") != shared_market_data.SHARED_ID:
        return {**ready, "state": "needs_rebuild", "repairable": True,
                "reason": "Generated provenance identity is invalid."}
    if receipt.get("close_rows") != n or receipt.get("last_session") != latest:
        return {**ready, "state": "needs_rebuild", "repairable": True,
                "reason": "Canonical SQLite coverage differs from published views."}
    sizes = []
    for name, key in FILES:
        recorded = receipt.get(key)
        if not isinstance(recorded, str) or not HASH.fullmatch(recorded):
            return {**ready, "state": "needs_rebuild", "repairable": True,
                    "reason": "Generated view lacks a valid checksum: " + name}
        sizes.append((folder / name).stat().st_size)
    if not verify_content and sum(sizes) > MAX_LIGHT_HASH_BYTES:
        return {**ready, "state": "verification_deferred",
                "reason": "Large derived views need an explicit full checksum check."}
    for name, key in FILES:
        try:
            if _hash(folder / name) != receipt[key]:
                return {**ready, "state": "needs_rebuild", "repairable": True,
                        "reason": "Generated view checksum differs: " + name}
        except OSError:
            return {**ready, "state": "needs_rebuild", "repairable": True,
                    "reason": "Generated view cannot be read: " + name}
    return {**ready, "state": "ready", "verified_content": True,
            "reason": "Derived source coverage and both view hashes match."}


def repair(*, automatic: bool = False) -> dict:
    """Recover only generated views after verifying authoritative SQLite.

    A concurrent market ingestion is serialized by the same re-entrant lock.
    Any source-integrity, symlink or resource-limit uncertainty fails closed.
    """
    with shared_market_data.LOCK:
        status = inspect(verify_content=True)
        if status["state"] == "ready":
            return {"state": "already_ready", "changed": False,
                    "source_rows_changed": False, "health": status}
        if not status["repairable"]:
            return {"state": "blocked", "changed": False,
                    "source_rows_changed": False, "health": status}
        limit = MAX_AUTO_SOURCE_BYTES if automatic else MAX_REPAIR_SOURCE_BYTES
        if status["source_bytes"] > limit:
            return {"state": "blocked", "changed": False,
                    "source_rows_changed": False, "health": {
                        **status, "reason": "Source exceeds the bounded " +
                        ("automatic" if automatic else "manual") +
                        " derived-view reconstruction limit."}}
        folder = shared_market_data.shared_folder()
        try:
            free = shutil.disk_usage(folder if folder.exists() else folder.parent).free
        except OSError:
            free = 0
        if free < MIN_REPAIR_FREE_BYTES:
            return {"state": "blocked", "changed": False,
                    "source_rows_changed": False, "health": {
                        **status, "reason": "Insufficient local free space for safe view reconstruction."}}
        before_rows = status["source_rows"]
        shared_market_data.publish_views()
        after = inspect(verify_content=True)
        if after["state"] != "ready" or after["source_rows"] != before_rows:
            raise ValueError(
                "Derived-view regeneration did not match the canonical SQLite source.")
        return {"state": "repaired", "changed": True,
                "source_rows_changed": False, "health": after}


def recover_small_views_on_startup() -> dict:
    """Automatic crash recovery only for bounded, trustworthy local sources."""
    with shared_market_data.LOCK:
        check = inspect()
        if check["state"] != "needs_rebuild":
            return {"state": check["state"], "changed": False}
        return repair(automatic=True)
