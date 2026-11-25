"""Non-destructive verified per-IST-day archive of existing market records.

Run off-hours. The canonical database remains authoritative; this is an
export/backup, not transparent archive hydration or disk reclamation.
"""
from __future__ import annotations
import argparse
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
import gzip
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
from zoneinfo import ZoneInfo
from . import shared_market_data, recorder_storage

IST = ZoneInfo("Asia/Kolkata")
TABLES = {
    "live_ticks": ("received_utc", "identity,exchange_utc,packet_sha256"),
    "live_minute_bars": ("minute_utc", "identity,minute_utc"),
    "live_depth_books": ("received_utc", "identity,received_utc"),
    "auto_banknifty_depth_features": ("received_utc", "identity,received_utc"),
    "option_chain_observations": ("captured_utc", "underlying,expiry,captured_utc"),
    "dhan_option_live_events": ("received_utc", "identity,received_utc,packet_sha256"),
}


def _file_hash(path):
    h=sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""):
            h.update(block)
    return h.hexdigest()


def _json(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False)


def verify(path):
    path=Path(path)
    manifest=json.loads((path/"manifest.json").read_text())
    if manifest.get("version")!=1 or not manifest.get("session_ist"):
        raise ValueError("Unrecognized market archive")
    if set(manifest["tables"])!=set(TABLES):
        raise ValueError("Archive table coverage does not match the declared schema")
    for table,info in manifest["tables"].items():
        if info["state"]=="table_absent":
            continue
        file=path/(table+".jsonl.gz")
        if _file_hash(file)!=info["sha256"]:
            raise ValueError("Archive file checksum mismatch: "+table)
        h=sha256();count=0
        with gzip.open(file,"rb") as src:
            for line in src:
                h.update(line)
                if not isinstance(json.loads(line),dict):
                    raise ValueError("Invalid archived row")
                count+=1
        if count!=info["rows"] or h.hexdigest()!=info["row_sha256"]:
            raise ValueError("Archive row count or checksum mismatch: "+table)
    return {**manifest,"verified":True}


def archive(day, *, output_dir=None, now=None):
    now=now or datetime.now(timezone.utc)
    day=date.fromisoformat(day) if isinstance(day,str) else day
    if day>=now.astimezone(IST).date():
        raise ValueError("Archive only completed IST dates, not today's active session")
    if not shared_market_data.database_path().is_file():
        raise ValueError("No local source database")
    root=Path(output_dir) if output_dir else shared_market_data.database_path().parent/"session_archives"
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    dest=root/day.isoformat()
    if dest.exists():
        return verify(dest)
    stage=root/("."+day.isoformat()+".partial")
    stage.mkdir(mode=0o700)  # Never overwrite interrupted staging or other writers.
    start=datetime.combine(day,time.min,IST).astimezone(timezone.utc).isoformat()
    end=(datetime.combine(day+timedelta(days=1),time.min,IST)
         .astimezone(timezone.utc).isoformat())
    manifest={"version":1,"session_ist":day.isoformat(),"created_utc":now.isoformat(),
              "start_utc":start,"end_utc":end,"source":"canonical_local_market_library",
              "tables":{},"canonical_rows_deleted":False,"source_completeness_certified":False}
    try:
        with closing(sqlite3.connect(shared_market_data.database_path().resolve().as_uri()+"?mode=ro",
                                     uri=True,timeout=10)) as db:
            db.row_factory=sqlite3.Row
            db.execute("BEGIN")  # Consistent read snapshot across the six tables.
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table,(clock,order) in TABLES.items():
                if table not in tables:
                    manifest["tables"][table]={"state":"table_absent","rows":None}
                    continue
                h=sha256();count=0
                file=stage/(table+".jsonl.gz")
                with gzip.open(file,"wb",compresslevel=3) as target:
                    for row in db.execute(f"SELECT * FROM {table} WHERE {clock}>=? AND {clock}<? ORDER BY {order}",(start,end)):
                        line=(_json(dict(row))+"\n").encode()
                        target.write(line);h.update(line);count+=1
                        if count%10000==0:
                            usage=shutil.disk_usage(root)
                            reserve=min(10*1024**3,max(512*1024**2,int(usage.total*.03)))
                            if usage.free<=reserve:
                                raise OSError("Archive destination disk reserve reached")
                manifest["tables"][table]={"state":"exported","rows":count,
                    "sha256":_file_hash(file),"row_sha256":h.hexdigest()}
            db.rollback()
        (stage/"manifest.json").write_text(_json(manifest)+"\n")
        verified=verify(stage)
        os.rename(stage,dest)
        return verified
    except BaseException:
        # Retain interrupted stage for diagnosis; no automatic destructive cleanup.
        raise


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--day",help="Completed IST date YYYY-MM-DD")
    p.add_argument("--output-dir",type=Path)
    p.add_argument("--verify",type=Path,help="Verify an existing archive directory")
    args=p.parse_args()
    if args.verify:
        print(json.dumps(verify(args.verify),indent=2))
    elif args.day:
        print(json.dumps(archive(args.day,output_dir=args.output_dir),indent=2))
    else:
        p.error("Specify --day or --verify")


if __name__=="__main__":
    main()
