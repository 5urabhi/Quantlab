"""Optional local file intake for participant reports from a licensed delivery.

Never contacts NSE, scrapes websites or acquires new permissions. Files stay
in the inbox. Only explicitly authorized, receipt-timed evidence is used.
"""
from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from threading import Lock
import json
import os
import re
import sqlite3
import stat
import time

from . import market_context as m, service, shared_market_data, recorder_storage

NAME=re.compile(r"fao_participant_(oi|vol)_([0-9]{8})\.csv",re.I)
MAX_BYTES=64000
MAX_FILES=2000
MAX_BATCH=24
_LOCK=Lock()
_SCAN=Lock()
_CACHE={}
_STATUS={"state":"idle","last_scan_utc":None,"files":[],"eligible_files":0}
_RETRY_SECONDS=300

def _folder():
    return service.DATA/"research_workspace"/"participant_inbox"

def _config_path():
    return service.DATA/"research_workspace"/"participant_inbox_consent.json"

def _ensure_folder():
    root=service.DATA.resolve()
    folder=_folder()
    folder.mkdir(parents=True,exist_ok=True)
    if not folder.resolve().is_relative_to(root) or folder.is_symlink() or folder.parent.is_symlink():
        raise ValueError("Unsafe participant inbox")
    return folder

def _config():
    path=_config_path()
    if not path.exists():
        return {"enabled":False,"source":""}
    if path.is_symlink() or path.stat().st_size>4096:
        raise ValueError("Invalid local inbox consent")
    value=json.loads(path.read_text(encoding="utf-8"))
    if set(value)!={"enabled","source"} or type(value["enabled"]) is not bool or not isinstance(value["source"],str) or len(value["source"])>200 or (value["enabled"] and len(value["source"].strip())<3):
        raise ValueError("Invalid local inbox consent")
    return value

def configure(enabled,source,confirm_reviewed):
    if type(enabled) is not bool or not isinstance(source,str) or len(source)>200:
        raise ValueError("Invalid inbox configuration")
    if enabled and (confirm_reviewed is not True or len(source.strip())<3):
        raise ValueError("Confirm written source permissions for storage and model research")
    _ensure_folder()
    path=_config_path();tmp=path.with_suffix(".tmp")
    with _LOCK:
        if path.is_symlink() or tmp.is_symlink():
            raise ValueError("Unsafe inbox consent file")
        try:
            tmp.write_text(json.dumps({"enabled":enabled,"source":source.strip()},sort_keys=True),encoding="utf-8")
            os.replace(tmp,path)
        finally:
            tmp.unlink(missing_ok=True)
        _CACHE.clear()
    return status()

def status():
    try:
        cfg=_config();error=None
    except (OSError,ValueError,TypeError):
        cfg={"enabled":False,"source":""};error="Local inbox consent invalid"
    with _LOCK:
        return {**_STATUS,"config":cfg,"error":error,"folder":str(_folder()),
                "scanning":_SCAN.locked(),"note":"Only authorized local files. Receipt time is first successful intake, not the report publication time. NSE website scraping and order execution are not enabled."}

def _read(path):
    # The publisher should atomically rename complete files into the inbox.
    # Reject symlinks, special files and files modified during the read.
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,"rb") as f:
        first=os.fstat(f.fileno())
        if not stat.S_ISREG(first.st_mode) or not 0<first.st_size<=MAX_BYTES:
            raise ValueError("Require bounded regular CSV file")
        data=f.read(MAX_BYTES+1)
        last=os.fstat(f.fileno())
        if len(data)!=first.st_size or (first.st_size,first.st_mtime_ns,first.st_ino)!=(last.st_size,last.st_mtime_ns,last.st_ino):
            raise ValueError("File is still changing")
        return data.decode("utf-8")

def _already_saved(raw,day,kind,source):
    path=shared_market_data.database_path()
    if not path.is_file():
        return False
    digest=sha256(raw.encode()).hexdigest()
    with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=3)) as db:
        if not m._exists(db,"market_context_raw_reports"):
            return False
        row=db.execute("""SELECT 1 FROM market_context_raw_reports r
          JOIN market_context_imports i USING(receipt_sha256)
          JOIN market_context_observations o USING(receipt_sha256)
          WHERE r.original_sha256=? AND i.source=? AND i.mode='receipt'
          AND substr(o.event_utc,1,10)=? LIMIT 1""",
          (digest,source+" participant-wise "+kind,day)).fetchone()
        return bool(row)

def scan(now=None):
    if not _SCAN.acquire(blocking=False):
        return status()
    try:
        cfg=_config()
        if not cfg["enabled"]:
            return status()
        folder=_ensure_folder()
        now=now or m._now()
        files=[]
        # Explicit bound; do not silently drop the tail of a large directory.
        for i,path in enumerate(folder.iterdir()):
            if i>=MAX_FILES:
                raise ValueError("Inbox directory exceeds file limit; move processed files to your authorized archive")
            if NAME.fullmatch(path.name):
                files.append(path)
        files.sort(key=lambda p:p.name)
        results=[];attempts=0
        for path in files:
            try:
                info=path.lstat()
                fp=(info.st_ino,info.st_size,info.st_mtime_ns,cfg["source"])
            except OSError:
                continue
            with _LOCK:
                cached=_CACHE.get(path.name)
            if cached and cached[0]==fp and (cached[1]["state"] in ("imported","already_saved") or time.monotonic()-cached[2]<_RETRY_SECONDS):
                results.append(cached[1]);continue
            if attempts>=MAX_BATCH:
                results.append({"file":path.name,"state":"queued"});continue
            attempts+=1
            result={"file":path.name,"state":"unavailable"}
            try:
                match=NAME.fullmatch(path.name)
                kind="oi" if match.group(1).lower()=="oi" else "volume"
                day=datetime.strptime(match.group(2),"%d%m%Y").date().isoformat()
                raw=_read(path)
                if _already_saved(raw,day,kind,cfg["source"]):
                    result.update(state="already_saved",rows=0)
                else:
                    if not recorder_storage.allow("participant_inbox",dropped=1):
                        raise ValueError("Shared storage paused")
                    # Confirm the source configuration was not revoked while
                    # reading; no archive mode or filesystem timestamp used.
                    if _config()!=cfg:
                        raise ValueError("Inbox authorization changed")
                    receipt=m.ingest_participant(raw,day,m._iso(now),kind,"receipt",True,now=now,source_identity=cfg["source"])
                    result.update(state="imported" if receipt["inserted"] else "already_saved",rows=receipt["rows"] if receipt["inserted"] else 0,receipt_sha256=receipt["receipt_sha256"])
                    if receipt["inserted"]:
                        recorder_storage.saved("participant_inbox",m._iso(now),receipt["rows"])
            except (OSError,ValueError,TypeError,OverflowError,sqlite3.Error):
                result["detail"]="File incomplete, invalid, conflicting source, unavailable storage or session not closed. Will retry."
            with _LOCK:
                _CACHE[path.name]=(fp,result,time.monotonic())
            results.append(result)
        with _LOCK:
            for key in list(_CACHE):
                if key not in {p.name for p in files}:
                    del _CACHE[key]
            _STATUS.update(state="scanned",last_scan_utc=m._iso(now),eligible_files=len(files),
                           files=results[:100],counts={k:sum(r["state"]==k for r in results) for k in ("imported","already_saved","queued","unavailable")})
    except (OSError,ValueError,TypeError):
        with _LOCK:
            _STATUS.update(state="unavailable",last_scan_utc=m._iso(now or m._now()),files=[],eligible_files=0,
                           counts={},detail="Inbox configuration or bounded directory read unavailable")
    finally:
        _SCAN.release()
    return status()
