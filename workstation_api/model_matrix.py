"""One canonical price-matrix contract for readiness and numerical models.

All consumers require the original source view, with positive finite prices
and no forward-fill. An explicitly enabled, current Parquet mirror may serve
the same model matrix, after comparing source manifests and database stamps.
A missing/stale accelerator falls back to the original verified CSV; a *ready*
but corrupted accelerator fails closed rather than silently changing numbers.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json
import re

import pandas as pd

from index_research.data import read_matrix
from . import columnar_cache, shared_market_data, service

CHUNK = 1024 * 1024
ALLOWED = {"daily_prices.csv": "daily_sha256",
           "prices.csv": "monthly_sha256"}


def _digest(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError("Canonical original model-price view is unavailable")
    hash_obj = sha256()
    with path.open("rb") as fd:
        for piece in iter(lambda: fd.read(CHUNK), b""):
            hash_obj.update(piece)
    return hash_obj.hexdigest()


def load(dataset_id: str, folder: Path, view: str) -> tuple[pd.DataFrame, str]:
    if view not in ALLOWED:
        raise ValueError("Unsupported source-bound historical price view")
    original = folder / view
    if dataset_id != shared_market_data.SHARED_ID:
        return read_matrix(original, positive=True), "original_csv"
    if original.parent.resolve() != shared_market_data.shared_folder().resolve():
        raise ValueError("Shared research dataset path does not match canonical source")
    metadata = folder / "SHARED_MARKET_PROVENANCE.json"
    if not metadata.is_file() or metadata.is_symlink() or metadata.stat().st_size > 2_000_000:
        raise ValueError("Shared market price contract is missing provenance")
    receipt = json.loads(metadata.read_text(encoding="utf-8"))
    declared = receipt.get(ALLOWED[view])
    if (not isinstance(declared, str) or
            not re.fullmatch(r"[a-f0-9]{64}", declared) or
            _digest(original) != declared):
        raise ValueError("Shared market view bytes changed without matching source receipt")
    cache = columnar_cache.status()
    if cache["ready"] and cache["engine_available"]:
        data = columnar_cache.model_matrix(view)
        # Check both sources again after constructing the model matrix.
        if _digest(original) != declared:
            raise ValueError("Original source view changed while model matrix loaded")
        if (view == "daily_prices.csv" and
                len(data) != receipt.get("daily_sessions")) or (
                    view == "prices.csv" and
                    len(data) != receipt.get("monthly_marks")):
            raise ValueError("Parquet and canonical original-model calendar disagree")
        if data.shape[1] != receipt.get("securities"):
            raise ValueError("Parquet model securities disagree with source receipt")
        return data, "source_locked_duckdb_parquet"
    return read_matrix(original, positive=True), (
        "original_csv_cache_" + cache["state"])
