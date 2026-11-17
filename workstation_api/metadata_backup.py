"""Checksummed, local-only backups of QuantLab research metadata.

Raw broker prices, Dhan candle originals, authentication material, saved
licensed source archives, and full model result folders are intentionally
excluded. SQLite's online backup API includes a consistent WAL snapshot
without touching the live source database. No browser raw-byte download or
unsafe one-click restore endpoint is exposed. A metadata backup is not a
replacement for the original market data needed for reproducible studies.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from threading import RLock
import json
import os
import re
import shutil
import sqlite3
import uuid

from . import database_inspector, service

LOCK = RLock()
ID = re.compile(r"^snapshot_[0-9a-f]{16}$")
CHECKSUM = re.compile(r"^[0-9a-f]{64}$")
MAX_SOURCE_BYTES = 300 * 1024 * 1024
SOURCES = {
    "research_library": "research_workspace/library.sqlite3",
    "operations": "research_workspace/data_orchestrator.sqlite3",
}


def _root() -> Path:
    path = service.DATA / "research_workspace" / "metadata_backups"
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Unsafe local metadata backup directory")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def _file(name: str) -> Path:
    if name not in SOURCES:
        raise ValueError("Only original allowlisted metadata databases may be backed up")
    path = service.DATA / SOURCES[name]
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Unsafe original metadata database path")
    return path


def _digest(path: Path) -> str:
    h = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024*1024), b""):
            h.update(block)
    return h.hexdigest()


def _check_sqlite(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Missing or unsafe local SQLite snapshot file")
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro",
                         uri=True, timeout=6) as conn:
        conn.execute("PRAGMA query_only=ON")
        row = conn.execute("PRAGMA quick_check(1)").fetchone()
    if not row or row[0] != "ok":
        raise ValueError("Local research metadata SQLite integrity failed")


def preview() -> dict:
    entries=[]
    for name in SOURCES:
        file=_file(name)
        present=file.is_file()
        size=file.stat().st_size if present else 0
        entries.append({
            "id":name,
            "label": database_inspector.DATABASES[name]["label"],
            "state":"available" if present else "not_initialized",
            "source_bytes":size,
            "can_snapshot":present and size<=MAX_SOURCE_BYTES,
        })
    return {
        "databases":entries,
        "can_create":any(x["can_snapshot"] for x in entries),
        "excluded":["market_data","dhan_originals","licensed_market_prices",
                    "broker_credentials","model_result_payloads"],
        "scope":"research_metadata_only",
        "warning":"Only local saved research metadata is included; market source "
                  "data and model result files remain separate.",
    }


def create(*, confirm_authorized: bool, progress=None) -> dict:
    if not confirm_authorized:
        raise ValueError("Confirm an encrypted-disk/local metadata snapshot first")
    with LOCK:
        inventory=preview()
        if not inventory["can_create"]:
            raise ValueError("No initialized research metadata database can be safely backed up")
        oversized=[x["id"] for x in inventory["databases"]
                   if x["state"]=="available" and not x["can_snapshot"]]
        if oversized:
            raise ValueError("One or more metadata databases exceed safe snapshot limits")
        ident="snapshot_"+uuid.uuid4().hex[:16]
        root=_root()
        stage=root/("."+ident+".pending")
        final=root/ident
        stage.mkdir(mode=0o700,exist_ok=False)
        files=[]
        try:
            available=[x for x in inventory["databases"] if x["can_snapshot"]]
            for i,item in enumerate(available):
                name=item["id"]
                source=_file(name)
                destination=stage/(name+".sqlite3")
                if progress:
                    progress(5+72*i/max(1,len(available)),
                             "Creating consistent read-only snapshot of "+name)
                # An online SQLite backup includes committed WAL transactions
                # and never copies arbitrary filesystem or credential content.
                with sqlite3.connect(source.resolve().as_uri()+"?mode=ro",
                                     uri=True, timeout=15) as conn:
                    with sqlite3.connect(destination) as out:
                        conn.backup(out, pages=200, sleep=.1)
                destination.chmod(0o600)
                _check_sqlite(destination)
                files.append({
                    "database":name,"filename":name+".sqlite3",
                    "sha256":_digest(destination),
                    "size_bytes":destination.stat().st_size,
                })
            if not files:
                raise ValueError("Original research metadata databases were not initialized")
            manifest={
                "id":ident,"version":1,
                "created_utc":datetime.now(timezone.utc).isoformat(),
                "files":files,"scope":"research_metadata_only",
                "source_market_data_included":False,
                "broker_credentials_included":False,
                "user_notes_may_be_sensitive":True,
                "local_only":True,"restore_automatically":False,
                "warning":"Contains saved local research records and user notes, "
                          "which may be sensitive. Store on an encrypted disk. "
                          "Does not include licensed market data, provider tokens, "
                          "or the full model result archive.",
            }
            tmp=stage/"manifest.json"
            tmp.write_text(json.dumps(manifest,indent=2),encoding="utf-8")
            tmp.chmod(0o600)
            stage.rename(final)
            if progress:
                progress(100,"Source-safe research metadata snapshot verified")
            return {"created":True,**manifest}
        except Exception:
            shutil.rmtree(stage,ignore_errors=True)
            raise


def list_snapshots(limit: int=25) -> dict:
    if not isinstance(limit,int) or not 1<=limit<=60:
        raise ValueError("Invalid local snapshot inventory limit")
    out=[]
    for path in sorted(_root().iterdir(),reverse=True):
        if len(out)>=limit:
            break
        if path.is_symlink() or not path.is_dir() or not ID.fullmatch(path.name):
            continue
        file=path/"manifest.json"
        if file.is_symlink() or not file.is_file() or file.stat().st_size>16_000:
            continue
        try:
            record=json.loads(file.read_text(encoding="utf-8"))
            if record.get("id")!=path.name or record.get("scope")!="research_metadata_only":
                continue
            entries=record.get("files") or []
            out.append({
                "id":path.name,"created_utc":record["created_utc"],
                "databases":[r["database"] for r in entries],
                "total_snapshot_bytes":sum(r["size_bytes"] for r in entries),
                "local_only":True,"verified_now":False,
            })
        except (OSError,ValueError,TypeError,KeyError):
            continue
    return {
        "snapshots":out,
        "warning":"Snapshot discovery is metadata-only. Verify a snapshot before trusting it.",
    }


def verify(snapshot_id: str) -> dict:
    if not ID.fullmatch(snapshot_id or ""):
        raise ValueError("Unknown local metadata snapshot")
    folder=_root()/snapshot_id
    receipt=folder/"manifest.json"
    if folder.is_symlink() or receipt.is_symlink() or not receipt.is_file() or receipt.stat().st_size>16_000:
        raise ValueError("Backup receipt missing or unsafe")
    data=json.loads(receipt.read_text(encoding="utf-8"))
    rows=data.get("files")
    if (data.get("id")!=snapshot_id or data.get("version")!=1 or
            data.get("scope")!="research_metadata_only" or
            not isinstance(rows,list) or not 1<=len(rows)<=len(SOURCES)):
        raise ValueError("Backup manifest is invalid or unsupported")
    checked=[]
    for item in rows:
        if not isinstance(item,dict) or item.get("database") not in SOURCES:
            raise ValueError("Unknown backup database entry")
        source=item["database"]
        if item.get("filename") != source+".sqlite3" or not CHECKSUM.fullmatch(
                str(item.get("sha256",""))):
            raise ValueError("Backup filename or checksum contract invalid")
        file=folder/item["filename"]
        if not file.is_file() or file.is_symlink() or file.stat().st_size!=item.get("size_bytes"):
            raise ValueError("Backup file was moved or resized")
        if _digest(file)!=item["sha256"]:
            raise ValueError("Backup original metadata checksum mismatch")
        _check_sqlite(file)
        checked.append(source)
    if len(checked)!=len(set(checked)):
        raise ValueError("Duplicate backup database record")
    return {
        "id":snapshot_id,"verified":True,"checked_databases":checked,
        "checked_utc":datetime.now(timezone.utc).isoformat(),
        "source_market_data_included":False,"broker_credentials_included":False,
        "safe_for_full_research_replay":False,
        "warning":"Local research metadata snapshot verified by SHA-256 and SQLite. "
                  "Original licensed market data and model result files are NOT included. "
                  "Automatic live-server restore is intentionally unsupported.",
    }
