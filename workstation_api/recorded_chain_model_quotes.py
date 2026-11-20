"""Explicitly reuse saved BANKNIFTY chain observations for quote-based models.

The existing read-only Dhan chain recorder persists normalized provider
observations into the shared Market Library. This adapter never calls Dhan,
places orders, or invents bid/ask prices. An opt-in local action selects an
immutable SHA-checked snapshot, subsets valid quoted contracts and imports
their observed values into the dataset-bound model quote catalog.

The Dhan response's expiry DATE is known, but its exact expiry TIME is not.
15:30 IST is strictly an indicated convention/assumption, NOT source truth.
The upstream vendor JSON is not stored in the chain database, so this
adapter never claims to hold a raw original-vendor response.
"""
from __future__ import annotations

import csv
from datetime import date, datetime, time, timezone
from hashlib import sha256
from io import StringIO
import json
import math
from pathlib import Path
import re
import sqlite3
from urllib.parse import quote
from zoneinfo import ZoneInfo

from . import option_quotes, service, shared_market_data

HEX = re.compile(r"^[a-f0-9]{64}$")
IST = ZoneInfo("Asia/Kolkata")
MAX_PAYLOAD_BYTES = 12_000_000
SCAN_LIMIT = 30
MAX_IMPORTED_CONTRACTS = 200


def _open_db():
    path = shared_market_data.database_path()
    if path.is_symlink() or not path.is_file():
        return None
    # Opening SQLite read-only is important: a catalog GET must never create
    # a database or interfere with the live Dhan capture worker.
    uri = "file:" + quote(str(path.resolve()), safe="/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _entries(*, digest: str | None = None, limit: int = 12) -> list[dict]:
    if not 1 <= limit <= SCAN_LIMIT:
        raise ValueError("Invalid chain inventory limit")
    if digest is not None and not HEX.fullmatch(digest):
        raise ValueError("Select an exact saved SHA-256 BANKNIFTY snapshot")
    connection = _open_db()
    if connection is None:
        return []
    try:
        condition = "underlying='BANKNIFTY'"
        args: list[object] = []
        if digest is not None:
            condition += " AND snapshot_sha256=?"
            args.append(digest)
        args.append(limit)
        statement = (
            "SELECT expiry,captured_utc,snapshot_sha256,normalized_json "
            "FROM option_chain_observations WHERE " + condition +
            " ORDER BY captured_utc DESC LIMIT ?"
        )
        try:
            data = connection.execute(statement, args).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc):
                return []
            raise
        return [
            {"expiry":expiry,"captured_utc":captured,"sha256":snapshot,
             "raw":raw}
            for expiry,captured,snapshot,raw in data
        ]
    finally:
        connection.close()


def _checked(row: dict) -> dict:
    raw = row["raw"]
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise ValueError("Recorded chain source is missing or larger than limit")
    if sha256(raw.encode("utf-8")).hexdigest() != row["sha256"]:
        raise ValueError("Saved chain source checksum mismatch")
    source = json.loads(raw)
    if not isinstance(source, dict) or (
            source.get("underlying") != "BANKNIFTY" or
            source.get("expiry") != row["expiry"] or
            source.get("received_utc") != row["captured_utc"]):
        raise ValueError("Stored BANKNIFTY chain metadata is inconsistent")
    try:
        captured = datetime.fromisoformat(row["captured_utc"])
        expiry = date.fromisoformat(row["expiry"])
    except (TypeError, ValueError) as exc:
        raise ValueError("Recorded quote clock or expiry is invalid") from exc
    if captured.tzinfo is None:
        raise ValueError("Captured quote timestamp lacks timezone")
    captured = captured.astimezone(timezone.utc)
    assumption = datetime.combine(expiry, time(15, 30), tzinfo=IST)
    if captured >= assumption:
        raise ValueError("Captured chain does not precede its assumed expiry instant")
    spot = float(source["underlying_spot"])
    if not math.isfinite(spot) or spot <= 0:
        raise ValueError("Recorded chain has no valid underlying spot")
    contracts = source.get("contracts")
    if not isinstance(contracts, list) or len(contracts) > 10000:
        raise ValueError("Recorded chain contracts are malformed or excessive")
    valid = []
    for row_contract in contracts:
        if not isinstance(row_contract, dict) or not row_contract.get("quote_valid"):
            continue
        try:
            strike = float(row_contract["strike"])
            bid = float(row_contract["bid"])
            ask = float(row_contract["ask"])
            side = row_contract["option_type"]
        except (TypeError, ValueError, KeyError):
            continue
        if (not all(math.isfinite(value) for value in (strike, bid, ask))
                or strike <= 0 or bid <= 0 or ask < bid
                or side not in {"CE", "PE"}
                or row_contract.get("expiry") != row["expiry"]):
            continue
        valid.append({
            "captured_at": captured.isoformat(),
            "provider": "DhanHQ_StoredNormalizedChain",
            "underlying": "BANKNIFTY",
            "underlying_spot": spot,
            "expiry_at": assumption.isoformat(),
            "strike": strike, "option_type": "call" if side == "CE" else "put",
            "bid": bid, "ask": ask,
        })
    valid.sort(key=lambda value: (
        abs(float(value["strike"]) - spot),
        value["strike"], value["option_type"]))
    return {"captured_at": captured.isoformat(), "expiry": row["expiry"],
            "original_contracts": len(contracts),
            "valid_contracts": len(valid),
            "contracts": valid[:MAX_IMPORTED_CONTRACTS],
            "snapshot_sha256": row["sha256"],
            "source_clock": source.get("source_clock", "local_received_utc"),
            "market_master_fresh_at_capture": bool(source.get("market_master_fresh")),
            "expiry_time_is_assumed": True}


def _session_context(received_utc: str) -> dict:
    """Classify local receive clock against SCHEDULED NSE hours, not holidays.

    This is not the exchange's event timestamp and does not certify a
    trading session, quote age at exchange, or market availability.
    """
    received = datetime.fromisoformat(received_utc)
    if received.tzinfo is None:
        raise ValueError("Saved chain receive time must have timezone")
    observed_ist = received.astimezone(IST)
    during = (
        observed_ist.weekday() < 5 and
        time(9, 15) <= observed_ist.time() < time(15, 30)
    )
    return {
        "received_ist": observed_ist.isoformat(),
        "received_during_scheduled_nse_hours": during,
        "regular_session_clock_only_not_exchange_verified": True,
    }


def available(*, limit: int = 12) -> dict:
    """Summaries only; no broker call and no option price payload to the UI."""
    found = []
    for row in _entries(limit=limit):
        try:
            item = _checked(row)
            if item["valid_contracts"] < 1:
                continue
            found.append({
                **{key: item[key] for key in (
                    "captured_at", "expiry", "original_contracts",
                    "valid_contracts", "snapshot_sha256", "expiry_time_is_assumed")},
                **_session_context(item["captured_at"]),
            })
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            # Ignore unusable observations; never count them as available quotes.
            continue
    preferred = next(
        (item for item in found
         if item["received_during_scheduled_nse_hours"]), None
    )
    if preferred is None and found:
        preferred = found[0]
    return {
        "dataset_id": shared_market_data.SHARED_ID, "snapshots": found,
        "recommended_snapshot_sha256": (
            preferred["snapshot_sha256"] if preferred else None
        ),
        "preference": "Newest valid locally received snapshot within scheduled "
                      "weekday 09:15-15:30 IST window; falls back to newest "
                      "available snapshot if none exist in that window.",
        "read_only_inventory": True, "vendor_request_performed": False,
        "warning": "Scheduled-hours test is only a clock check, not an NSE "
                   "holiday-calendar or exchange-event-time verification. "
                   "The source has normalized Dhan observations, not raw vendor JSON. "
                   "Expiry time assumes 15:30 IST. This is not an executable live quote.",
    }


def use_saved(dataset_id: str, snapshot_sha256: str, *,
              confirm_reuse: bool = False) -> dict:
    if not confirm_reuse:
        raise ValueError("Confirm use of the recorded source for mathematical model calibration")
    if dataset_id != shared_market_data.SHARED_ID:
        raise ValueError("Recorded BANKNIFTY chains belong to the shared Dhan dataset")
    service.dataset_path(dataset_id)
    rows = _entries(digest=snapshot_sha256, limit=1)
    if not rows:
        raise ValueError("No matching saved original-source BANKNIFTY chain")
    item = _checked(rows[0])
    if not item["contracts"]:
        raise ValueError("This historical chain has no valid original bid/ask contracts")
    # Idempotent by original recorder SHA and dataset; avoid duplicate copies.
    for snapshot in option_quotes.list_for(dataset_id):
        receipt = option_quotes.get(snapshot["id"], dataset_id)
        if (receipt.get("source_type") == "dhan_cached_normalized_optionchain_v1"
                and receipt.get("provider_metadata", {}).get(
                    "stored_chain_snapshot_sha256") == snapshot_sha256):
            return {"id": snapshot["id"], "dataset_id": dataset_id,
                    "contracts": len(receipt["contracts"]),
                    "reused_existing": True,
                    "original_chain_sha256": snapshot_sha256,
                    "source": "saved_normalized_dhan_chain",
                    "warning": receipt["warning"]}
    output = StringIO()
    fields = ["captured_at", "provider", "underlying", "underlying_spot",
              "expiry_at", "strike", "option_type", "bid", "ask"]
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(item["contracts"])
    receipt = option_quotes.import_quotes(
        dataset_id, output.getvalue().encode("utf-8"),
        source_type="dhan_cached_normalized_optionchain_v1",
        provider_metadata={
            "stored_chain_snapshot_sha256": snapshot_sha256,
            "original_vendor_response_present": False,
            "saved_normalized_chain_only": True,
            "source_clock": item["source_clock"],
            "market_master_fresh_at_capture": item["market_master_fresh_at_capture"],
            "source_expiry_time_is_exact": False,
            "expiry_close_time_assumption": "15:30 Asia/Kolkata regular NSE session",
            "original_contract_count": item["original_contracts"],
            "valid_contract_count": item["valid_contracts"],
            "selected_contract_count": len(item["contracts"]),
        },
    )
    return {"id": receipt["id"], "dataset_id": dataset_id,
            "contracts": len(receipt["contracts"]), "reused_existing": False,
            "original_chain_sha256": snapshot_sha256,
            "source": "saved_normalized_dhan_chain",
            "warning": "Used saved original-source normalized Dhan bid/ask without a "
                       "new provider request. The full vendor JSON is NOT preserved "
                       "by this recorder. Quote received time is local; exact expiry "
                       "time is ASSUMED at 15:30 IST. This is historical, not tradable."}
