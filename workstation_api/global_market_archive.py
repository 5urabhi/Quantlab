"""Authorized JForex index-CFD OHLCV imports, opening-clock features and coverage.

These are broker BID price proxies, not cash index prints or GIFT NIFTY.
No HTTP requests, orders, synthetic candles, or changes to Dhan tables.
Historical availability is an explicit research assumption, separate from
actual local receipt availability.
"""
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo
import csv
import gzip
import io
import json
import math
import os
import sqlite3
import time as monotonic_time
import uuid

from . import service, shared_market_data, recorder_storage

UTC = timezone.utc
IST = ZoneInfo("Asia/Kolkata")
MAX_BYTES = 16_000_000
MAX_ROWS = 50_000
HEADER = ("instrument", "interval_minutes", "side", "bar_start_ms", "open",
          "high", "low", "close", "volume", "exported_ms")
# Exact broker instrument identifiers, NOT exchange-index identifiers.
INSTRUMENTS = {
    "JPN.IDX/JPY": ("Japan 200+ CFD", "Asia/Tokyo", 9, 0),
    "SGD.IDX/SGD": ("Singapore Blue Chip CFD", "Asia/Singapore", 9, 0),
    "CHI.IDX/USD": ("China A50 CFD", "Asia/Shanghai", 9, 30),
    "HKG.IDX/HKD": ("Hong Kong CFD", "Asia/Hong_Kong", 9, 30),
    "AUS.IDX/AUD": ("Australia 200 CFD", "Australia/Sydney", 10, 0),
    "USA500.IDX/USD": ("US 500 CFD", "America/New_York", 9, 30),
    "USATECH.IDX/USD": ("US 100 Tech CFD", "America/New_York", 9, 30),
    "DEU.IDX/EUR": ("Germany 40 CFD", "Europe/Berlin", 9, 0),
    "GBR.IDX/GBP": ("UK 100 CFD", "Europe/London", 8, 0),
    "EUS.IDX/EUR": ("Europe 50 CFD", "Europe/Paris", 9, 0),
}
# Opening clocks are normal CASH-market reference times only. They are not
# CFD trading hours, nor a point-in-time exchange holiday/special-day calendar.
ASIAN = tuple(list(INSTRUMENTS)[:5])


def _now():
    return datetime.now(UTC)


def _iso(value):
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _ms(value):
    if not isinstance(value, str) or not value.isascii() or not value.isdigit() or len(value) != 13:
        raise ValueError("Expected UTC epoch milliseconds")
    try:
        return int(value), datetime.fromtimestamp(int(value)/1000, UTC)
    except (ValueError, OverflowError, OSError) as exc:
        raise ValueError("Invalid UTC epoch milliseconds") from exc


def identity(symbol):
    if symbol not in INSTRUMENTS:
        raise ValueError("Unsupported exact Dukascopy instrument")
    return "DUKASCOPY_CFD:" + symbol + ":BID"


def _number(value, *, positive):
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid OHLCV field") from exc
    if not math.isfinite(result) or abs(result) > 1e15 or (result <= 0 if positive else result < 0):
        raise ValueError("Invalid OHLCV range")
    return result


def parse(raw, now):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES:
        raise ValueError("CSV exceeds bounded file size or is empty")
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
    except UnicodeError as exc:
        raise ValueError("Expected UTF-8 JForex export") from exc
    if tuple(reader.fieldnames or ()) != HEADER:
        raise ValueError("Unexpected JForex export header")
    rows = []
    group = None
    seen = set()
    for row in reader:
        if len(rows) >= MAX_ROWS or None in row or any(v is None for v in row.values()):
            raise ValueError("Malformed export or row limit reached")
        symbol = row["instrument"]
        ident = identity(symbol)
        if row["side"] != "BID" or row["interval_minutes"] not in ("1", "5"):
            raise ValueError("Only exact BID 1/5-minute series are supported")
        minutes = int(row["interval_minutes"])
        resolution = str(minutes) + "m"
        key = (ident, resolution)
        if group is not None and key != group:
            raise ValueError("One instrument and resolution per export")
        group = key
        start_ms, start = _ms(row["bar_start_ms"])
        _, exported = _ms(row["exported_ms"])
        end = start + timedelta(minutes=minutes)
        if start_ms % (minutes*60_000) or not end <= exported <= now:
            raise ValueError("Incomplete, future, misaligned or invalid bar/export time")
        if start_ms in seen:
            raise ValueError("Duplicate bar within one export")
        seen.add(start_ms)
        o,h,l,c = (_number(row[k], positive=True) for k in ("open","high","low","close"))
        v = _number(row["volume"], positive=False)
        if not l <= min(o,c) <= max(o,c) <= h:
            raise ValueError("Inconsistent OHLC")
        rows.append((ident,resolution,_iso(start),_iso(end),o,h,l,c,v,_iso(exported)))
    if not rows:
        raise ValueError("No observed bars")
    return sorted(rows, key=lambda r:r[2])


def _setup(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS global_market_receipts(
      receipt_sha256 TEXT PRIMARY KEY, raw_sha256 TEXT NOT NULL,
      identity TEXT NOT NULL, resolution TEXT NOT NULL, mode TEXT NOT NULL,
      archive_lag_minutes INTEGER, imported_utc TEXT NOT NULL,
      row_count INTEGER NOT NULL, first_utc TEXT NOT NULL, last_utc TEXT NOT NULL,
      original_csv_gzip BLOB NOT NULL
    );
    CREATE TABLE IF NOT EXISTS global_market_bars(
      identity TEXT NOT NULL, resolution TEXT NOT NULL,
      bar_start_utc TEXT NOT NULL, bar_end_utc TEXT NOT NULL,
      open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL,
      close REAL NOT NULL, volume REAL NOT NULL, exported_utc TEXT NOT NULL,
      receipt_known_utc TEXT NOT NULL, archive_known_utc TEXT,
      receipt_sha256 TEXT NOT NULL REFERENCES global_market_receipts(receipt_sha256),
      archive_sha256 TEXT REFERENCES global_market_receipts(receipt_sha256),
      PRIMARY KEY(identity,resolution,bar_start_utc)
    ) WITHOUT ROWID;
    """)


def _table_exists(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='global_market_bars'").fetchone() is not None


def ingest(raw, *, mode="receipt", confirm_reviewed=False, archive_lag_minutes=None, now=None,
           _original_export=None):
    if confirm_reviewed is not True or mode not in ("receipt","archive"):
        raise ValueError("Confirm authorized local data storage and chosen availability mode")
    if mode == "archive":
        if type(archive_lag_minutes) is not int or not 1 <= archive_lag_minutes <= 1440:
            raise ValueError("Choose a reviewed positive archive lag in minutes; not actual historical receipt proof")
    elif archive_lag_minutes is not None:
        raise ValueError("Receipt mode does not accept retrospective availability")
    now = now or _now()
    if now.tzinfo is None:
        raise ValueError("Use timezone-aware receipt time")
    rows = parse(raw,now)
    original = raw if _original_export is None else _original_export
    if not isinstance(original,bytes) or not 0<len(original)<=MAX_BYTES:
        raise ValueError("Invalid original export")
    raw_sha = sha256(original).hexdigest()
    key = [raw_sha,mode,archive_lag_minutes]
    if _original_export is not None:
        # Bind external CSV with explicit reviewed identity/resolution and
        # keep idempotence even when the import timestamp changes.
        key.extend(["reviewed_direct_bid_csv_v1",rows[0][0],rows[0][1]])
    return store_validated_rows(rows,original,mode,archive_lag_minutes,now,key)


def store_validated_rows(rows, original, mode, archive_lag_minutes, now, key):
    """Internal storage adapter: callers validate exact provider identity and OHLCV first."""
    raw_sha=sha256(original).hexdigest()
    receipt = sha256(json.dumps(key,separators=(",",":")).encode()).hexdigest()
    path = shared_market_data.database_path()
    path.parent.mkdir(parents=True,exist_ok=True)
    # Bounded transaction per export, never replace a live database or change
    # its journal mode. If a recorder holds the lock, the file remains for retry.
    with closing(sqlite3.connect(path,timeout=2)) as db:
        db.execute("PRAGMA busy_timeout=2000")
        db.execute("PRAGMA foreign_keys=ON")
        _setup(db)
        with db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM global_market_receipts WHERE receipt_sha256=?",(receipt,)).fetchone():
                return {"state":"already_imported","receipt_sha256":receipt,"inserted":0,"rows":len(rows),
                        "identity":rows[0][0],"resolution":rows[0][1]}
            db.execute("INSERT INTO global_market_receipts VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (receipt,raw_sha,rows[0][0],rows[0][1],mode,archive_lag_minutes,_iso(now),
                        len(rows),rows[0][2],rows[-1][2],gzip.compress(original,compresslevel=3)))
            inserted = upgraded = 0
            for r in rows:
                archive = None
                if mode == "archive":
                    archive_dt = datetime.fromisoformat(r[3])+timedelta(minutes=archive_lag_minutes)
                    if archive_dt > now:
                        raise ValueError("Reviewed archive availability is after actual import time")
                    archive = _iso(archive_dt)
                old = db.execute("""SELECT open,high,low,close,volume,archive_known_utc
                    FROM global_market_bars WHERE identity=? AND resolution=? AND bar_start_utc=?""",r[:3]).fetchone()
                if old:
                    if tuple(old[:5]) != r[4:9]:
                        raise ValueError("Conflicting OHLCV for an existing bar; original retained")
                    if archive is not None and old[5] is not None and old[5] != archive:
                        raise ValueError("Conflicting reviewed archive lag; original retained")
                    if archive is not None and old[5] is None:
                        db.execute("""UPDATE global_market_bars SET archive_known_utc=?,archive_sha256=?
                            WHERE identity=? AND resolution=? AND bar_start_utc=?""",(archive,receipt,*r[:3]))
                        upgraded += 1
                else:
                    db.execute("INSERT INTO global_market_bars VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                               (*r,_iso(now),archive,receipt,receipt if archive is not None else None))
                    inserted += 1
    return {"state":"imported","receipt_sha256":receipt,"inserted":inserted,
            "archive_upgraded":upgraded,"rows":len(rows),"mode":mode,
            "identity":rows[0][0],"resolution":rows[0][1]}



def import_direct_csv(raw, *, symbol, minutes, mode="receipt", confirm_reviewed=False,
                      archive_lag_minutes=None, now=None):
    """Import an authorized original BID export without JForex or a downloader.

    The user must explicitly review symbol, BID side, UTC bar-start timestamps,
    resolution and data rights; generic CSV filenames are not identity proof.
    The original bytes are retained, not merely the normalized representation.
    """
    if confirm_reviewed is not True:
        raise ValueError("Review direct export identity, timezone, price side and permitted storage")
    identity(symbol)
    if type(minutes) is not int or minutes not in (1,5):
        raise ValueError("Choose 1 or 5 minutes")
    now=now or _now()
    if now.tzinfo is None:
        raise ValueError("Use timezone-aware receipt time")
    if not isinstance(raw,bytes) or not 0<len(raw)<=MAX_BYTES:
        raise ValueError("Missing or oversized original export")
    try:
        reader=csv.DictReader(io.StringIO(raw.decode("utf-8-sig"),newline=""))
    except UnicodeError as exc:
        raise ValueError("Expected UTF-8 CSV") from exc
    names=reader.fieldnames or []
    header=tuple(x.strip().lower() for x in names)
    if header not in (("gmt time","open","high","low","close","volume"),
                      ("timestamp","open","high","low","close","volume")):
        raise ValueError("Use a reviewed GMT-time or UTC epoch-millisecond OHLCV export")
    out=io.StringIO()
    writer=csv.writer(out,lineterminator="\n")
    writer.writerow(HEADER)
    exported=str(int(now.timestamp()*1000))
    for idx,row in enumerate(reader):
        if idx>=MAX_ROWS or None in row or any(v is None for v in row.values()):
            raise ValueError("Malformed export or row limit; split original exports into smaller date ranges")
        stamp=row[names[0]].strip()
        if header[0]=="timestamp":
            _ms(stamp)
        else:
            parsed=None
            for fmt in ("%d.%m.%Y %H:%M:%S.%f","%d.%m.%Y %H:%M:%S",
                        "%d.%m.%Y %H:%M","%Y.%m.%d %H:%M:%S","%Y.%m.%d %H:%M"):
                try:
                    parsed=datetime.strptime(stamp,fmt).replace(tzinfo=UTC)
                    break
                except ValueError:
                    continue
            if parsed is None:
                raise ValueError("Unsupported GMT time; never guess local timezone")
            stamp=str(int(parsed.timestamp()*1000))
        writer.writerow((symbol,minutes,"BID",stamp,
                         *(row[name] for name in names[1:]),exported))
    return ingest(out.getvalue().encode(),mode=mode,confirm_reviewed=True,
                  archive_lag_minutes=archive_lag_minutes,now=now,_original_export=raw)


def inventory():
    path = shared_market_data.database_path()
    result = {"state":"not_recorded","series":[],"note":"Observed counts/endpoints only; not certified exchange-session completeness."}
    if not path.is_file():
        return result
    from . import alpaca_overnight as boats
    series=[(symbol,name,identity(symbol),resolution)
            for symbol,(name,*_) in INSTRUMENTS.items() for resolution in ("1m","5m")]
    series.extend((symbol,name,boats.identity(symbol),"5m") for symbol,name in boats.SYMBOLS.items())
    with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
        if not _table_exists(db):
            return result
        for symbol,name,ident,resolution in series:
            key=(ident,resolution)
            # The primary key supports these range scans. No payloads read.
            n,first,last,arch = db.execute("""SELECT COUNT(*),MIN(bar_start_utc),MAX(bar_start_utc),
                COUNT(archive_known_utc) FROM global_market_bars WHERE identity=? AND resolution=?""",key).fetchone()
            if n:
                result["series"].append({"instrument":symbol,"label":name,"identity":ident,
                    "resolution":resolution,"rows":n,"first_utc":first,"last_utc":last,"archive_rows":arch})
        result["state"]="stored" if result["series"] else "empty"
    return result


def reference_features(db, day, cutoff, *, resolution="5m", mode="archive"):
    """As-of proxy windows anchored to normal Asian cash-market reference clocks.

    A positive archive lag is an explicit assumption, not actual publication
    evidence. Require all bars in each opening window. No fabricated holidays,
    no previous-day fill, no future observations, and zero-volume bars do not
    establish a valid opening window. This does not assert that cash markets
    were open on the reference date.
    """
    if resolution not in ("1m","5m") or mode not in ("archive","receipt") or cutoff.tzinfo is None:
        raise ValueError("Invalid feature request")
    if cutoff.astimezone(IST).date()!=day:
        raise ValueError("Cutoff must belong to the requested India date")
    step=timedelta(minutes=int(resolution[:-1]))
    known="archive_known_utc" if mode=="archive" else "receipt_known_utc"
    result={}
    exists=_table_exists(db)
    for symbol in ASIAN:
        name,zone,hour,minute=INSTRUMENTS[symbol]
        opening=datetime.combine(day,time(hour,minute),ZoneInfo(zone)).astimezone(UTC)
        row={"instrument":symbol,"reference_utc":_iso(opening),"mode":mode,
             "state":"missing","proxy_not_cash":True}
        for n in (5,15,30,60):
            row["first_"+str(n)+"m_bps"]=None
        row["reference_to_cutoff_bps"]=None
        if exists and cutoff>opening:
            found=db.execute("""SELECT bar_start_utc,bar_end_utc,open,close,volume,"""+known+"""
                FROM global_market_bars WHERE identity=? AND resolution=?
                  AND bar_start_utc>=? AND bar_start_utc<? AND bar_end_utc<=?
                  AND """+known+"""<=? ORDER BY bar_start_utc""",
                (identity(symbol),resolution,_iso(opening),_iso(cutoff),_iso(cutoff),_iso(cutoff))).fetchall()
            bars={r[0]:r for r in found if r[4]>0}
            first=bars.get(_iso(opening))
            if first is not None:
                for n in (5,15,30,60):
                    if opening+timedelta(minutes=n)>cutoff:
                        continue
                    expected=[bars.get(_iso(opening+i*step)) for i in range(n//int(resolution[:-1]))]
                    if expected and all(v is not None for v in expected):
                        row["first_"+str(n)+"m_bps"]=10000*(expected[-1][3]/first[2]-1)
                last=max(bars.values(),key=lambda r:r[0])
                if cutoff-datetime.fromisoformat(last[1])<=2*step:
                    row["reference_to_cutoff_bps"]=10000*(last[3]/first[2]-1)
                    row["latest_bar_end_utc"]=last[1]
                    row["latest_known_utc"]=last[5]
                    row["state"]="observed_proxy"
                elif any(row["first_"+str(n)+"m_bps"] is not None for n in (5,15,30,60)):
                    row["state"]="opening_windows_only"
        result[symbol]=row
    return result


def import_directory(directory, *, mode="receipt", confirm_reviewed=False, archive_lag_minutes=None,
                     max_new_files=20, _known=None, _deadline=None):
    """Import finalized exports without deleting them; skip exact receipts."""
    directory=Path(directory).expanduser().resolve()
    if not directory.is_dir() or not 1<=max_new_files<=200:
        raise ValueError("Choose an existing export directory and bounded batch")
    if confirm_reviewed is not True:
        raise ValueError("Confirm authorized local import")
    entries=sorted(directory.glob("*.csv"))
    if len(entries)>20000:
        raise ValueError("Too many export files; split into bounded directories")
    results=[]; skipped=0
    for path in entries:
        if _deadline is not None and monotonic_time.monotonic()>_deadline:
            break
        if len(results)>=max_new_files:
            break
        if path.is_symlink() or not path.is_file() or path.stat().st_size>MAX_BYTES:
            results.append({"file":path.name,"state":"rejected","reason":"unsafe or oversized input"})
            continue
        # Avoid re-parsing saved raw bytes or creating duplicate receipts.
        try:
            st=path.stat()
            sig=(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)
            if _known is not None and _known.get(str(path))==sig:
                skipped+=1
                continue
            raw=path.read_bytes()
        except OSError:
            results.append({"file":path.name,"state":"rejected_or_paused","reason":"Export unavailable"})
            continue
        digest=sha256(json.dumps([sha256(raw).hexdigest(),mode,archive_lag_minutes],
                                  separators=(",",":")).encode()).hexdigest()
        target=shared_market_data.database_path()
        if target.is_file():
            with closing(sqlite3.connect(target.resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
                if _table_exists(db) and db.execute("SELECT 1 FROM global_market_receipts WHERE receipt_sha256=?",(digest,)).fetchone():
                    skipped+=1
                    if _known is not None:
                        _known[str(path)]=sig
                    continue
        try:
            if not recorder_storage.allow("global_market_bars"):
                results.append({"file":path.name,"state":"rejected_or_paused","reason":"Shared disk reserve"})
                break
            outcome=ingest(raw,mode=mode,confirm_reviewed=True,archive_lag_minutes=archive_lag_minutes)
            results.append({"file":path.name,**outcome})
            if _known is not None:
                _known[str(path)]=sig
            if outcome["inserted"]:
                recorder_storage.saved("global_market_bars",_iso(_now()),count=outcome["inserted"])
        except (ValueError,OSError,sqlite3.Error) as exc:
            results.append({"file":path.name,"state":"rejected_or_paused","reason":str(exc)[:200]})
        if len(results)>=max_new_files:
            break
    return {"files":results,"skipped_receipts":skipped,"scanned_candidates":len(entries),
            "note":"Retry remaining/rejected exports after review; no gaps were manufactured."}


# Explicit opt-in for the existing local context worker. No network access,
# no Dhan session dependency, no automatic retrospective archive assumptions.
_LIVE_KNOWN={}
_LIVE_DB_ID=None


def _live_config_path():
    return service.DATA/"research_workspace"/"global_market_live_inbox.json"


def configure_live_inbox(directory, *, confirm_reviewed=False):
    if confirm_reviewed is not True:
        raise ValueError("Confirm authorized live source and local storage")
    folder=Path(directory).expanduser().resolve()
    if not folder.is_dir() or folder.name!="quantlab_global_live":
        raise ValueError("Choose the JForex quantlab_global_live export directory")
    path=_live_config_path()
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_symlink():
        raise ValueError("Unsafe live inbox config")
    tmp=path.with_name("."+path.name+"."+uuid.uuid4().hex)
    try:
        tmp.write_text(json.dumps({"version":1,"directory":str(folder)},sort_keys=True),encoding="utf-8")
        os.replace(tmp,path)
    finally:
        tmp.unlink(missing_ok=True)
    return {"state":"configured","directory":str(folder),
            "note":"Context worker will import authorized finalized live receipts while QuantLab is running."}


def disable_live_inbox():
    path=_live_config_path()
    if path.is_symlink():
        raise ValueError("Unsafe live inbox config")
    path.unlink(missing_ok=True)
    return {"state":"disabled"}


def scan_live_inbox(*, now=None):
    global _LIVE_DB_ID
    path=_live_config_path()
    if not path.exists():
        return None
    if path.is_symlink() or path.stat().st_size>8192:
        raise ValueError("Unsafe live inbox config")
    config=json.loads(path.read_text(encoding="utf-8"))
    if set(config)!={"version","directory"} or config["version"]!=1 or not isinstance(config["directory"],str):
        raise ValueError("Invalid live inbox config")
    folder=Path(config["directory"])
    if not folder.is_absolute() or folder.name!="quantlab_global_live" or not folder.is_dir() or folder.is_symlink():
        raise ValueError("Configured live source unavailable")
    target=shared_market_data.database_path()
    st=target.stat() if target.exists() else None
    dbid=(str(target),st.st_dev,st.st_ino) if st else (str(target),None,None)
    if dbid!=_LIVE_DB_ID or len(_LIVE_KNOWN)>20000:
        _LIVE_KNOWN.clear()
        _LIVE_DB_ID=dbid
    now=now or _now()
    today=now.astimezone(UTC).date()
    deadline=monotonic_time.monotonic()+3
    files=[];skipped=0
    active=[]
    # Current and two prior UTC dates; historical repairs remain explicit.
    for delta in range(3):
        sub=folder/str(today-timedelta(days=delta))
        if sub.is_dir() and not sub.is_symlink():
            active.append(sub)
    # Prevent unbounded memory and do not delete original source files.
    for key in list(_LIVE_KNOWN):
        if not any(Path(key).parent==sub for sub in active):
            del _LIVE_KNOWN[key]
    for sub in active:
        if monotonic_time.monotonic()>deadline or len(files)>=20:
            break
        result=import_directory(sub,mode="receipt",confirm_reviewed=True,
                 max_new_files=20-len(files),_known=_LIVE_KNOWN,_deadline=deadline)
        files.extend(result["files"]);skipped+=result["skipped_receipts"]
    return {"state":"observed" if files or skipped else "waiting_for_exports",
            "inserted":sum(x.get("inserted",0) for x in files),
            "new_files":len(files),"known_files":skipped,
            "rejected_or_paused":sum(x["state"].startswith("rejected") for x in files),
            "note":"Local receipt import only; not a certificate of continuous broker coverage."}
