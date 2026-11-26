"""Local-only, allowlisted metadata backups. Never restore or copy market databases.

One online SQLite backup per metadata database; these are not a cross-database
transaction. Sensitive user-entered notes may be present. No provider secrets
files, raw licensed market observations or model artifacts are copied.
"""
from __future__ import annotations
from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
from threading import RLock
import json
import os
import re
import shutil
import sqlite3
import time
import uuid
from . import database_inspector, service

LOCK=RLock()
IDS=re.compile(r"^snapshot_[0-9a-f]{16}$")
HASH=re.compile(r"^[0-9a-f]{64}$")
SOURCES=("research_library","operations")
MAX_BYTES=300*1024*1024
MIN_FREE=512*1024*1024

def _stamp():
    return datetime.now(timezone.utc).isoformat()

def _root(create=False):
    root=service.DATA
    path=root/"research_workspace"/"metadata_backups"
    if any(p.is_symlink() for p in (root,path.parent,path)) or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Unsafe metadata snapshot directory")
    if create:
        path.mkdir(parents=True,exist_ok=True,mode=0o700)
        path.chmod(0o700)
    return path

def _source(name):
    if name not in SOURCES:
        raise ValueError("Only allowlisted metadata databases are eligible")
    return database_inspector._path(name)

def _digest(path):
    if path.is_symlink() or not path.is_file() or not 0<path.stat().st_size<=MAX_BYTES:
        raise ValueError("Invalid or oversized snapshot file")
    h=sha256()
    with path.open("rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):
            h.update(block)
    return h.hexdigest()

def _check(path):
    deadline=time.monotonic()+15
    with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as conn:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA trusted_schema=OFF")
        conn.set_progress_handler(lambda:int(time.monotonic()>deadline),5000)
        result=conn.execute("PRAGMA quick_check(1)").fetchone()
    if result!=("ok",):
        raise ValueError("Metadata SQLite integrity check failed")

def _source_bytes(path):
    wal=path.with_name(path.name+"-wal")
    if wal.is_symlink():
        raise ValueError("Unsafe metadata WAL")
    return path.stat().st_size+(wal.stat().st_size if wal.is_file() else 0)

def preview():
    rows=[]
    for name in SOURCES:
        p=_source(name)
        size=_source_bytes(p) if p.is_file() else None
        rows.append({"id":name,"label":database_inspector.DATABASES[name]["label"],
                     "state":"available" if size is not None else "not_initialized",
                     "source_bytes":size,"can_snapshot":size is not None and 0<size<=MAX_BYTES})
    present=[r for r in rows if r["state"]=="available"]
    return {"databases":rows,"can_create":bool(present) and all(r["can_snapshot"] for r in present),
            "scope":"research_metadata_only",
            "warning":"Per-database consistent copies of saved research metadata, including potentially sensitive user notes. Not market data, provider settings or complete model-result backups. Use encrypted local storage."}

def create(*,confirm_authorized=False,progress=None):
    if confirm_authorized is not True:
        raise ValueError("Explicit local sensitive-metadata backup consent is required")
    with LOCK:
        inventory=preview()
        if not inventory["can_create"]:
            raise ValueError("Missing or oversized metadata databases")
        available=[r for r in inventory["databases"] if r["can_snapshot"]]
        root=_root(True)
        required=2*sum(r["source_bytes"] for r in available)+MIN_FREE
        if shutil.disk_usage(root).free<required:
            raise ValueError("Insufficient free disk space for a bounded metadata copy")
        ident="snapshot_"+uuid.uuid4().hex[:16]
        stage=root/("."+ident+".pending")
        final=root/ident
        stage.mkdir(mode=0o700)
        entries=[]
        try:
            for i,item in enumerate(available):
                name=item["id"]
                source=_source(name)
                target=stage/(name+".sqlite3")
                deadline=time.monotonic()+30
                def check(status,remaining,total):
                    if time.monotonic()>deadline or target.stat().st_size>MAX_BYTES:
                        raise ValueError("Metadata copy exceeded its time or size limit")
                fd=os.open(str(target),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
                os.close(fd)
                with closing(sqlite3.connect(source.resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as conn:
                    conn.execute("PRAGMA query_only=ON")
                    conn.execute("PRAGMA trusted_schema=OFF")
                    with closing(sqlite3.connect(target,timeout=2)) as dst:
                        conn.backup(dst,pages=128,progress=check,sleep=.05)
                _check(target)
                entries.append({"database":name,"filename":target.name,"size_bytes":target.stat().st_size,"sha256":_digest(target)})
                if progress:
                    progress(10+80*(i+1)/len(available),"Verified local metadata copy")
            manifest={"id":ident,"version":1,"created_utc":_stamp(),"scope":"research_metadata_only",
                      "files":entries,"source_market_data_included":False,"local_only":True,
                      "per_database_consistency":True,"cross_database_atomic":False,"restore_supported":False,
                      "warning":"May contain sensitive user-entered notes. Original market observations, provider credential files and research result payloads are not backed up."}
            fd=os.open(str(stage/"manifest.json"),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(fd,"w",encoding="utf-8") as stream:
                json.dump(manifest,stream,allow_nan=False)
            stage.rename(final)
            return manifest
        except Exception:
            shutil.rmtree(stage,ignore_errors=True)
            raise

def _manifest(ident):
    if not IDS.fullmatch(ident or ""):
        raise ValueError("Invalid metadata snapshot identity")
    folder=_root()/ident
    path=folder/"manifest.json"
    if folder.is_symlink() or path.is_symlink() or not path.is_file() or not 0<path.stat().st_size<=16000:
        raise ValueError("Invalid metadata snapshot receipt")
    data=json.loads(path.read_text())
    if not isinstance(data,dict) or data.get("id")!=ident or data.get("version")!=1 or data.get("scope")!="research_metadata_only":
        raise ValueError("Invalid metadata snapshot manifest")
    files=data.get("files")
    if not isinstance(files,list) or not 1<=len(files)<=len(SOURCES):
        raise ValueError("Invalid backup file inventory")
    seen=set()
    for row in files:
        if not isinstance(row,dict) or row.get("database") not in SOURCES:
            raise ValueError("Invalid backup database")
        name=row["database"]
        if name in seen or row.get("filename")!=name+".sqlite3" or not HASH.fullmatch(str(row.get("sha256",""))) or type(row.get("size_bytes")) is not int or not 0<row["size_bytes"]<=MAX_BYTES:
            raise ValueError("Invalid or repeated backup file evidence")
        seen.add(name)
    stamp=datetime.fromisoformat(data["created_utc"])
    if stamp.tzinfo is None:
        raise ValueError("Invalid backup creation time")
    return folder,data

def list_snapshots(limit=25):
    if type(limit) is not int or not 1<=limit<=60:
        raise ValueError("Snapshot limit must be 1–60")
    root=_root()
    rows=[]
    partial=False
    if root.is_dir():
        with os.scandir(root) as entries:
            for i,entry in enumerate(entries):
                if i>=2000:
                    partial=True
                    break
                if not IDS.fullmatch(entry.name) or not entry.is_dir(follow_symlinks=False):
                    continue
                try:
                    _,data=_manifest(entry.name)
                    rows.append({"id":entry.name,"created_utc":data["created_utc"],
                                 "databases":[r["database"] for r in data["files"]],
                                 "total_snapshot_bytes":sum(r["size_bytes"] for r in data["files"]),"verified_now":False})
                except (OSError,ValueError,TypeError,KeyError):
                    partial=True
    rows.sort(key=lambda r:r["created_utc"],reverse=True)
    return {"snapshots":rows[:limit],"partial":partial or len(rows)>limit,"scope":"research_metadata_only"}

def verify(ident):
    with LOCK:
        folder,data=_manifest(ident)
        checked=[]
        for row in data["files"]:
            path=folder/row["filename"]
            if path.is_symlink() or not path.is_file() or path.stat().st_size!=row["size_bytes"] or _digest(path)!=row["sha256"]:
                raise ValueError("Backup size or SHA-256 mismatch")
            _check(path)
            checked.append(row["database"])
        return {"id":ident,"verified":True,"checked_databases":checked,"checked_utc":_stamp(),
                "source_market_data_included":False,"safe_for_full_research_replay":False,"restore_supported":False}
