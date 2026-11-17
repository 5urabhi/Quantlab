"""Process-crash-safe commit journal for original Dhan candle windows.

The source CSV and its SHA/coverage manifest are different filesystem files.
Writing them independently can strand a valid new CSV with the old manifest
if Python is interrupted between renames. Before changing a canonical CSV
we persist the *new* validated manifest as a small pending journal, then
atomically replace the CSV, then publish that journal as the new manifest.

On retry we resolve the journal ONLY if the actual stored CSV hashes to its
announced original bytes and the canonical exchange/security/interval match.
No candle is invented, deleted, silently overridden, or treated as externally
certified. A competing/tampered file remains blocked for human review.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json
import os
import re
import uuid

SHA256 = re.compile(r"^[a-f0-9]{64}$")
IDENTITY = re.compile(r"^(NSE_EQ|BSE_EQ):[0-9]{1,12}$")
MAX_RECEIPT_BYTES = 2_000_000
CHUNK_BYTES = 1024 * 1024


def digest(path: Path) -> str:
    """Bounded-memory SHA-256 for original CSV; never load huge minute files twice."""
    h = sha256()
    with path.open("rb") as original:
        for piece in iter(lambda: original.read(CHUNK_BYTES), b""):
            h.update(piece)
    return h.hexdigest()


def _pending(target: Path) -> Path:
    if target.suffix != ".csv":
        raise ValueError("Dhan checkpoint expects the original candle CSV path")
    return target.with_suffix(".pending.json")


def _regular(path: Path) -> bool:
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Unsafe symlink in original candle checkpoint")
    return path.is_file()


def _read_receipt(path: Path, *, identity: str, interval: int | None) -> dict:
    if not _regular(path) or path.stat().st_size > MAX_RECEIPT_BYTES:
        raise ValueError("Original Dhan checkpoint receipt missing or oversized")
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, OSError, json.JSONDecodeError) as exc:
        raise ValueError("Unreadable original Dhan checkpoint receipt") from exc
    if (not isinstance(body, dict) or body.get("instrument_id") != identity
            or body.get("interval_minutes") != interval
            or not isinstance(body.get("sha256"), str)
            or not SHA256.fullmatch(body["sha256"])
            or not isinstance(body.get("coverage"), list)
            or not isinstance(body.get("rows"), int)
            or body["rows"] < 1):
        raise ValueError("Original Dhan checkpoint receipt has invalid identity or structure")
    return body


def recover(target: Path, manifest: Path, *,
            identity: str, interval: int | None) -> bool:
    """Finish an interrupted publication only if original bytes match exactly.

    A journal left *before* its CSV was installed is discarded when the prior
    canonical CSV and manifest still agree; the window can be requested again.
    A journal left *after* its CSV was installed is promoted without a vendor
    request. Any other discrepancy fails closed, retaining the source evidence.
    """
    if not IDENTITY.fullmatch(identity):
        raise ValueError("Unknown canonical Dhan security identity")
    pending = _pending(target)
    have_pending = _regular(pending)
    have_csv = _regular(target)
    have_manifest = _regular(manifest)
    if not have_pending:
        return False
    observed = digest(target) if have_csv else None
    previous = None
    if have_manifest:
        try:
            previous = _read_receipt(manifest, identity=identity, interval=interval)
        except ValueError:
            # Do not discard a valid new CSV merely because old metadata was
            # incomplete; journal verification below determines whether to
            # finish the forward-only publication.
            previous = None
    if previous is not None and previous["sha256"] == observed:
        # The previous pair is untouched, or the transaction already finished.
        pending.unlink()
        return False
    try:
        future = _read_receipt(pending, identity=identity, interval=interval)
    except ValueError as exc:
        raise ValueError("Pending Dhan checkpoint cannot be verified; "
                         "original candle files are preserved") from exc
    if have_csv and observed == future["sha256"]:
        # The CSV was successfully published just before Python crashed.
        # The journal was constructed from exactly that same validated frame.
        os.replace(pending, manifest)
        return True
    if not have_csv and not have_manifest:
        # First download never reached its canonical data file. A pending
        # metadata receipt alone provides no observed candles.
        pending.unlink()
        return False
    raise ValueError(
        "Dhan checkpoint CSV and receipts disagree; refusing to infer, "
        "overwrite or redownload potentially conflicting original candles")


def commit(target: Path, manifest: Path, staged_csv: Path, receipt: dict) -> None:
    """Prepare journal before changing the canonical CSV; no synthetic fallback."""
    if (target.suffix != ".csv" or manifest != target.with_suffix(".json")
            or not _regular(staged_csv) or _regular(_pending(target))
            or _regular(target) != _regular(manifest)):
        raise ValueError("Original Dhan files must be consistent before checkpoint commit")
    identity = receipt.get("instrument_id")
    interval = receipt.get("interval_minutes")
    if not isinstance(identity, str) or not IDENTITY.fullmatch(identity):
        raise ValueError("Invalid source identity for checkpoint")
    if receipt.get("sha256") != digest(staged_csv):
        raise ValueError("Staged Dhan candle checksum changed before commit")
    if (not isinstance(receipt.get("rows"), int) or receipt["rows"] < 1
            or not isinstance(receipt.get("coverage"), list)):
        raise ValueError("Incomplete Dhan candle source receipt")
    if interval is not None and interval not in (1, 5, 15, 25, 60):
        raise ValueError("Unsupported Dhan source interval")
    pending = _pending(target)
    encoded = json.dumps(receipt, ensure_ascii=False, indent=2,
                         allow_nan=False).encode("utf-8")
    if len(encoded) > MAX_RECEIPT_BYTES:
        raise ValueError("Dhan source receipt unexpectedly large")
    tmp = pending.with_name(pending.name + "." + uuid.uuid4().hex[:8] + ".tmp")
    try:
        with tmp.open("xb") as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        os.replace(tmp, pending)
        # The canonical CSV is still untouched if the pending journal failed.
        os.replace(staged_csv, target)
        # Once this rename succeeds a matching restart can finish the commit.
        os.replace(pending, manifest)
    finally:
        tmp.unlink(missing_ok=True)
