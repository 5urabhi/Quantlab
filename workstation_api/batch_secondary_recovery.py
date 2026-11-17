"""Explicit secondary-provider recovery for incomplete Dhan daily batches.

This does NOT rewrite Dhan caches, mark Dhan batch items completed, or replace
PIT/TRI/corporate-action data. Verified Zerodha closes may enter only the
separate canonical shared close store after exact security mapping and at
least three original-Dhan overlap sessions. All plans are metadata-only.
"""
from __future__ import annotations

from datetime import date, timedelta
from hashlib import sha256
import json
import sqlite3

from . import (dhan_workspace, job_safety, service, shared_market_data,
               zerodha_fallback)

MAX_RECOVERY_INSTRUMENTS = 24
MAX_RECOVERY_DAYS = 5 * 366
ELIGIBLE_STATES = frozenset({"pending", "failed", "no_data", "downloading"})
DHAN_ORIGINS = ("cached_%", "cache_%", "dhan_%")

def _original_baseline(identity: str, start: date, stop: date) -> int:
    db = shared_market_data.database_path()
    if not db.is_file() or db.is_symlink():
        return 0
    with sqlite3.connect(db.resolve().as_uri()+"?mode=ro", uri=True) as conn:
        conn.execute("PRAGMA query_only=ON")
        return int(conn.execute(
            "SELECT COUNT(*) FROM daily_closes WHERE identity=? "
            "AND session_date>=? AND session_date<? "
            "AND source_sha256 IN (SELECT source_sha256 FROM ingestions "
            "WHERE identity=? AND (origin LIKE ? OR origin LIKE ? OR origin LIKE ?))",
            (identity,(start-timedelta(days=60)).isoformat(),stop.isoformat(),
             identity,*DHAN_ORIGINS)).fetchone()[0])


def preview(batch_id: str) -> dict:
    """Preview precise source identity and recovery size, with NO provider calls."""
    data = dhan_workspace._load_batch(batch_id)
    status = dhan_workspace._summarize(data)["status"]
    blocked = []
    if status in {"running","queued"}:
        blocked.append("Stop or complete the current Dhan batch before secondary recovery.")
    if data["interval"] is not None:
        blocked.append("Zerodha supplies daily equity closes, not historical minute OHLCV.")
    first, last = date.fromisoformat(data["from_date"]), date.fromisoformat(data["to_date"])
    if (last-first).days > MAX_RECOVERY_DAYS:
        blocked.append("Secondary recovery is bounded to five years per approved job. "
                       "Split the original date range into smaller authorized downloads.")
    requested = [row for row in data["items"] if row.get("status") in ELIGIBLE_STATES]
    if not requested:
        blocked.append("No incomplete Dhan instruments remain for secondary recovery.")
    if len(requested) > MAX_RECOVERY_INSTRUMENTS:
        blocked.append("More than 24 incomplete instruments; use smaller named-stock "
                       "batches so each secondary-source request can be verified.")
    rows = []
    for row in requested[:MAX_RECOVERY_INSTRUMENTS]:
        eligibility = zerodha_fallback.eligibility(row)
        rows.append({"instrument_id": str(row["id"]),
                     "symbol": str(row.get("symbol", "")),
                     "original_status": str(row.get("status", "")),
                     "eligible": bool(eligibility.get("eligible")),
                     "reason": str(eligibility.get("reason",""))[:180]})
    eligible = [row for row in rows if row["eligible"]]
    if not eligible:
        blocked.append("No original Dhan identities have an authorized, exact Kite "
                       "cash-equity exchange-token and trading-symbol match.")
    manifest = dhan_workspace._batch_path(batch_id)
    if manifest.is_symlink():
        raise ValueError("Cannot verify symlinked original batch manifest")
    raw = manifest.read_bytes()
    master = zerodha_fallback._parsed_master()
    master_digest = str(master.get("sha256","missing"))
    digest = sha256(json.dumps({
        "batch_sha256":sha256(raw).hexdigest(),
        "kite_master_sha256":master_digest,
        "eligible_ids":[r["instrument_id"] for r in eligible],
    },sort_keys=True,separators=(",",":")).encode()).hexdigest()
    return {"batch_id": batch_id, "status": status,
            "from_date": first.isoformat(), "to_date": last.isoformat(),
            "candidate_count": len(requested),
            "eligible_count":len(eligible),
            "items": rows, "blockers": blocked,
            "can_recover":not blocked,
            "preview_token":digest,
            "destination_dataset_id":shared_market_data.SHARED_ID,
            "batch_mutated":False, "requires_user_authorization":True,
            "note": "Zerodha only extends the separate shared daily-close store after "
                    "three agreeing original Dhan sessions. Dhan batch manifests, "
                    "OHLCV files and prepared PIT datasets remain unchanged. "
                    "A matched price series is not an official TRI benchmark."}


def approve(batch_id: str, preview_token: str, *, confirm_secondary: bool) -> dict:
    if not confirm_secondary:
        raise ValueError("Explicitly approve licensed read-only Zerodha history retrieval.")
    if not isinstance(preview_token,str) or len(preview_token)!=64:
        raise ValueError("Review the secondary provider recovery plan.")
    current = preview(batch_id)
    if preview_token != current["preview_token"]:
        raise ValueError("Batch or Kite mappings changed. Review the recovery plan again.")
    if not current["can_recover"]:
        raise ValueError("; ".join(current["blockers"])[:280])
    return current


def execute(batch_id: str, preview_token: str, *, progress=None) -> dict:
    """Recover only eligible failed daily sources; never rewrite Dhan batches."""
    plan = approve(batch_id, preview_token, confirm_secondary=True)
    if progress:
        progress(3, "Checking authorized Zerodha session and source provenance")
    zerodha_fallback.verify_session()
    batch = dhan_workspace._load_batch(batch_id)
    records = {str(row["id"]):row for row in batch["items"]}
    outputs = []
    for index,item in enumerate(x for x in plan["items"] if x["eligible"]):
        row = records[item["instrument_id"]]
        if progress:
            progress(5+90*index/max(1,plan["eligible_count"]),
                     "Verifying secondary identity " + str(index+1)+"/"+
                     str(plan["eligible_count"]))
        result = {"instrument_id":item["instrument_id"],"symbol":item["symbol"]}
        try:
            # Original Dhan source bytes are verified before attempting any
            # secondary request, including cached windows from other batches.
            shared_market_data.reuse_cached(row)
            baseline = _original_baseline(
                row["id"],date.fromisoformat(plan["from_date"]),
                date.fromisoformat(plan["to_date"]))
            if baseline < 3:
                raise ValueError("Need three original Dhan sessions in this interval "
                                 "to authenticate secondary close overlap.")
            fetched = zerodha_fallback.retrieve(
                row,date.fromisoformat(plan["from_date"]),
                date.fromisoformat(plan["to_date"]),
                confirm_authorized=True)
            result.update(status="imported",rows_added=fetched.get("rows_added",0),
                          matched_sessions=fetched.get("matched_sessions",0),
                          source_receipt_id=fetched["source_receipt_id"])
        except (ValueError, OSError, sqlite3.Error) as exc:
            result.update(status="blocked",reason=job_safety.scrub(exc)[:200])
        outputs.append(result)
    complete = sum(r["status"]=="imported" for r in outputs)
    if progress:
        progress(100, "Verified fallback receipts saved without rewriting original Dhan batch")
    return {"status":"complete" if complete==len(outputs) else
            "partial" if complete else "blocked",
            "batch_id":batch_id,"recovered":complete,"attempted":len(outputs),
            "items":outputs,"dataset_id":shared_market_data.SHARED_ID,
            "original_dhan_batch_changed":False,
            "message":("Secondary daily closes, when validated, were appended to "
                       "the separate shared data store. Original Dhan batch statuses "
                       "and completeness are unchanged."),
            "next_action":"Inspect dhan_shared in My Datasets or retry Dhan for missing original OHLCV."}
