"""One logical market-data library over immutable provider evidence.

The library is a *view*, not a destructive move: canonical NSE/BSE equity
closes are keyed by exchange + Dhan Security ID in shared_market.sqlite3.
Index membership is time-dated, sectors are explicitly source-dated, and
uploaded/saved research artifacts retain their independent provenance.

GETs do not contact vendors or mutate authoritative data. The only writable
operations require explicit approval: consolidating prepared local Dhan
snapshots or importing original sector classification records.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from io import StringIO
from pathlib import Path
import csv
import json
import os
import re
import sqlite3

from . import dhan_workspace, pit_index, service, shared_market_data

SAFE_SECTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 &/().,_+-]{0,79}$")
MAX_IMPORT = 2 * 1024 * 1024
MAX_SECTORS = 10000
INDEX_VIEWS = {
    "nifty50": "nifty50_pit",
    "banknifty": "banknifty_pit",
}
KNOWN_VIEWS = frozenset({"all", "nse", "bse", "nifty50", "banknifty", "nifty100", "sector"})
SECTOR_TABLE = """
CREATE TABLE IF NOT EXISTS sector_history (
    identity TEXT NOT NULL,
    effective_date TEXT NOT NULL,
    sector TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    original_source TEXT NOT NULL,
    PRIMARY KEY(identity, effective_date),
    FOREIGN KEY(identity) REFERENCES instruments(identity)
);
CREATE INDEX IF NOT EXISTS sector_asof
    ON sector_history(identity, effective_date);
"""


def _connection() -> sqlite3.Connection | None:
    path = shared_market_data.database_path()
    if not path.is_file():
        return None
    if path.is_symlink():
        raise ValueError("Unsafe canonical market-data database path")
    conn = sqlite3.connect(path.resolve().as_uri()+"?mode=ro", uri=True, timeout=5)
    conn.execute("PRAGMA query_only=ON")
    return conn


def _sector_available(conn: sqlite3.Connection) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sector_history'"
    ).fetchone() is not None


def _date(value: str | None) -> str:
    if not value:
        return date.today().isoformat()
    if len(value)>10:
        raise ValueError("Use a valid historical as-of date")
    try:
        day = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Use YYYY-MM-DD for the as-of date") from exc
    if day > date.today():
        raise ValueError("Future memberships and sectors cannot be assumed")
    return day.isoformat()


def _index_keys(view: str, day: str) -> tuple[set[str], dict]:
    """Resolve as-of members using ONLY covered and exact matched source IDs."""
    try:
        status = pit_index.status()
    except (ValueError,OSError,KeyError) as exc:
        return set(), {"state":"blocked", "reason":str(exc)[:160]}
    if not status.get("available"):
        return set(), {"state":"missing_source",
            "reason":"Sync point-in-time NIFTY 50 / BANK NIFTY membership first."}
    if not str(status.get("first_date","")) <= day <= str(status.get("covered_through","")):
        return set(), {"state":"outside_covered_dates",
            "reason":"Membership documented only from "+str(status.get("first_date"))+
                     " through "+str(status.get("covered_through"))+"."}
    try:
        members = pit_index.query(
            INDEX_VIEWS[view], day, (date.fromisoformat(day)+timedelta(days=1)).isoformat(),
            dhan_workspace.catalog())
        keys = {item["id"] for item in members["resolved"]
                if item["symbol"] in members["asof_members"]}
        return keys, {
            "state":"source_mapped", "source":"reconstructed_pit",
            "source_commit":members["source_commit"],
            "asof_member_count":len(members["asof_members"]),
            "mapped_count":len(keys), "unresolved_count":members["unresolved_count"],
            "reason":"Independent reconstruction of dated NSE announcements; "
                     "not exchange-certified and historical IDs may be unavailable."}
    except (OSError,ValueError,KeyError) as exc:
        return set(), {"state":"blocked", "reason":str(exc)[:160]}


def _catalog() -> dict:
    try:
        return {row["id"]:row for row in dhan_workspace.catalog()}
    except (OSError,ValueError):
        return {}


def browse(*, view: str = "all", as_of: str = "", sector: str = "",
           query: str = "", page: int = 1, per_page: int = 35) -> dict:
    """Bounded, source-aware, locally indexed stock browser."""
    if view not in KNOWN_VIEWS:
        raise ValueError("Select a supported universe or sector view")
    if not 1<=page<=10000 or not 1<=per_page<=100:
        raise ValueError("Invalid market library page")
    if len(query)>80 or len(sector)>80:
        raise ValueError("Search or sector label is too long")
    day = _date(as_of)
    inferred_as_of = False
    if not as_of and view in INDEX_VIEWS:
        try:
            covered = str(pit_index.status().get("covered_through") or "")
            if covered and covered < day:
                day = covered
                inferred_as_of = True
        except (ValueError,OSError,KeyError):
            pass
    source = {"state":"canonical", "reason":"Original shared unadjusted closing prices"}
    keys: set[str] | None = None
    if view in INDEX_VIEWS:
        keys,source=_index_keys(view,day)
    elif view=="nifty100":
        keys=set()
        source={"state":"missing_source",
                "reason":"Original-source, effective-dated NIFTY 100 membership has "
                         "not been connected. Current NIFTY 50 cannot substitute."}
    con=_connection()
    groups=[
        {"id":"all","label":"All downloaded stocks","source_state":"canonical"},
        {"id":"nifty50","label":"NIFTY 50","source_state":"dated_reconstruction"},
        {"id":"nifty100","label":"NIFTY 100","source_state":"missing_source"},
        {"id":"banknifty","label":"BANK NIFTY","source_state":"dated_reconstruction"},
        {"id":"nse","label":"NSE stocks","source_state":"canonical"},
        {"id":"bse","label":"BSE stocks","source_state":"canonical"},
        {"id":"sector","label":"By sector","source_state":"original_dated_classifications"},
    ]
    if con is None:
        return {"library_id":shared_market_data.SHARED_ID,"available":False,
                "as_of":day,"as_of_defaulted":inferred_as_of,
                "view":view,"sector":sector,
                "total":0,"items":[],"groups":groups,
                "sectors":[],"has_more":False,
                "source_state":source,
                "message":"No shared daily stock history yet. Download stocks first, "
                          "or consolidate your saved original Dhan batches."}
    try:
        con.row_factory=sqlite3.Row
        sectors=[]
        has_sector=_sector_available(con)
        if has_sector:
            sectors=[r[0] for r in con.execute(
                "SELECT DISTINCT sector FROM sector_history WHERE effective_date<=? "
                "ORDER BY sector LIMIT 100",(day,)).fetchall()]
        where=[]
        args: list[str]=[]
        if view=="nse":
            where.append("i.exchange_segment='NSE_EQ'")
        if view=="bse":
            where.append("i.exchange_segment='BSE_EQ'")
        if keys is not None:
            if not keys:
                where.append("0=1")
            else:
                # Exact canonical IDs only, no SQL interpolation of source names.
                where.append("i.identity IN ("+",".join("?" for _ in keys)+")")
                args.extend(sorted(keys))
        if view=="sector":
            if not has_sector or not sectors:
                where.append("0=1")
                source={"state":"missing_source",
                        "reason":"Import original effective-dated sector classifications first."}
            elif not sector:
                where.append("0=1")
                source={"state":"choose_sector","reason":"Select an original sector classification."}
            else:
                where.append("""EXISTS (
                    SELECT 1 FROM sector_history s
                    WHERE s.identity=i.identity AND s.sector=?
                      AND s.effective_date=(
                        SELECT MAX(s2.effective_date) FROM sector_history s2
                        WHERE s2.identity=i.identity AND s2.effective_date<=?
                      ))""")
                args.extend([sector,day])
        q=query.strip().casefold()
        if q:
            where.append("(LOWER(i.display_symbol) LIKE ? OR i.security_id LIKE ?)")
            args.extend(["%"+q+"%","%"+q+"%"])
        clause=" WHERE "+" AND ".join(where) if where else ""
        total=int(con.execute("SELECT COUNT(*) FROM instruments i"+clause,args).fetchone()[0])
        ids=con.execute(
            "SELECT identity, exchange_segment, security_id, display_symbol "
            "FROM instruments i"+clause+
            " ORDER BY exchange_segment,display_symbol,security_id LIMIT ? OFFSET ?",
            [*args,per_page,(page-1)*per_page]).fetchall()
        selected=[]
        cat=_catalog()
        has_sector=_sector_available(con)
        for row in ids:
            identity=row["identity"]
            evidence=con.execute(
                "SELECT COUNT(*),MIN(session_date),MAX(session_date) "
                "FROM daily_closes WHERE identity=?",(identity,)).fetchone()
            classification=(con.execute(
                "SELECT sector,source_sha256,original_source,effective_date "
                "FROM sector_history WHERE identity=? AND effective_date<=? "
                "ORDER BY effective_date DESC LIMIT 1",(identity,day)).fetchone()
                if has_sector else None)
            name=cat.get(identity,{})
            selected.append({
                "identity":identity,"symbol":name.get("symbol") or row["display_symbol"],
                "name":name.get("display_name") or row["display_symbol"],
                "exchange":row["exchange_segment"][:3],
                "security_id":row["security_id"],
                "observations":int(evidence[0]),
                "first_date":evidence[1],"last_date":evidence[2],
                "sector":classification["sector"] if classification else None,
                "sector_effective_date":classification["effective_date"] if classification else None,
                "sector_source":"user_supplied_original" if classification else "not_available",
            })
        return {
            "library_id":shared_market_data.SHARED_ID,"available":True,
            "view":view,"as_of":day,"as_of_defaulted":inferred_as_of,
            "sector":sector,
            "total":total,"page":page,"per_page":per_page,
            "items":selected,"groups":groups,"sectors":sectors,
            "has_more":page*per_page<total,"source_state":source,
            "sector_source_status":"user_supplied_not_independently_certified" if sectors else
                                  "no_original_sector_source",
            "message":"One canonical price history per exchange/security ID; "
                      "groups are filters, not duplicate original datasets.",
        }
    finally:
        con.close()


def _sector_rows(payload: bytes) -> tuple[list[tuple[str,str,str]],str]:
    if not isinstance(payload,bytes) or not 1<=len(payload)<=MAX_IMPORT:
        raise ValueError("Sector CSV must be 1 byte to 2 MiB")
    try:
        decoded=payload.decode("utf-8-sig")
        reader=csv.DictReader(StringIO(decoded))
        required={"exchange_segment","security_id","effective_date","sector"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("Sector CSV requires exchange_segment,security_id,"
                             "effective_date,sector")
        values=[]
        seen=set()
        for row in reader:
            segment=str(row["exchange_segment"]).strip().upper()
            sid=str(row["security_id"]).strip()
            identity=segment+":"+sid
            if not shared_market_data.SAFE_IDENTITY.fullmatch(identity):
                raise ValueError("Only exact NSE_EQ/BSE_EQ cash-equity IDs are supported")
            effective=_date(str(row["effective_date"]).strip())
            label=str(row["sector"]).strip()
            if not SAFE_SECTOR.fullmatch(label):
                raise ValueError("Invalid sector label; use source-original names")
            key=(identity,effective)
            if key in seen:
                raise ValueError("Duplicate identity/effective date in sector source")
            seen.add(key)
            values.append((identity,effective,label))
            if len(values)>MAX_SECTORS:
                raise ValueError("Sector import exceeds 10,000 dated source rows")
    except (UnicodeError,csv.Error,TypeError,AttributeError) as exc:
        raise ValueError("Sector import must be a valid UTF-8 CSV") from exc
    if not values:
        raise ValueError("Sector CSV contains no original records")
    return values,sha256(payload).hexdigest()


def import_sector_history(payload: bytes, *, confirm_original: bool) -> dict:
    """Validate identities, then atomically retain source BEFORE changing metadata."""
    if not confirm_original:
        raise ValueError("Confirm original-source rights and effective dates before import")
    rows,digest=_sector_rows(payload)
    with shared_market_data.LOCK:
        con=shared_market_data._connect()
        try:
            con.executescript(SECTOR_TABLE)
            keys={row[0] for row in con.execute("SELECT identity FROM instruments")}
            unknown={identity for identity,_,_ in rows}-keys
            if unknown:
                raise ValueError("Sector source includes unknown canonical instruments: "+
                                 ", ".join(sorted(unknown)[:6]))
            # Validate the whole import before either publishing original
            # evidence or mutating a single dated classification.
            for identity,effective,sector in rows:
                old=con.execute(
                    "SELECT sector FROM sector_history "
                    "WHERE identity=? AND effective_date=?",
                    (identity,effective)).fetchone()
                if old and old[0]!=sector:
                    raise ValueError("Conflicting original sector classification for "+
                                     identity+" on "+effective)
            folder=service.DATA/"dhan"/"market_library"/"sector_sources"
            if folder.is_symlink() or folder.parent.is_symlink():
                raise ValueError("Unsafe original-sector source folder")
            folder.mkdir(parents=True,exist_ok=True)
            file=folder/(digest+".csv")
            if file.is_symlink():
                raise ValueError("Unsafe original-sector source file")
            if file.exists() and sha256(file.read_bytes()).hexdigest()!=digest:
                raise ValueError("Existing sector file conflicts with expected original bytes")
            if not file.exists():
                staging=folder/(digest+"."+os.urandom(8).hex()+".tmp")
                try:
                    with staging.open("xb") as output:
                        output.write(payload)
                        output.flush()
                        os.fsync(output.fileno())
                    os.replace(staging,file)
                finally:
                    staging.unlink(missing_ok=True)
            inserted=0
            with con:
                for identity,effective,sector in rows:
                    old=con.execute(
                        "SELECT sector FROM sector_history "
                        "WHERE identity=? AND effective_date=?",
                        (identity,effective)).fetchone()
                    if old:
                        continue
                    con.execute(
                        "INSERT INTO sector_history VALUES(?,?,?,?,?)",
                        (identity,effective,sector,digest,"user_supplied_original"))
                    inserted+=1
        finally:
            con.close()
    return {"status":"imported","rows":len(rows),"new_classifications":inserted,
            "source_sha256":digest,"dataset_id":shared_market_data.SHARED_ID,
            "source_status":"user_supplied_original_not_independently_certified",
            "note":"Effective-dated sectors are metadata views, not duplicated prices. "
                   "The CSV remains recoverable; no missing historical sector is inferred."}


def consolidate(*, progress=None) -> dict:
    """Idempotently index existing locally prepared Dhan sources without vendor calls.

    Original batch snapshots and paper evidence remain separate and immutable.
    On a conflict, the affected source is blocked and never overwrites the
    canonical identity/date series.
    """
    snapshots=[
        r for r in service.datasets(include_archived=True)
        if r["kind"]=="dhan" and r["id"].startswith("dhan_")
        and r["id"]!=shared_market_data.SHARED_ID
        and r.get("has_daily_ohlcv")
    ]
    completed=[]
    blocked=[]
    for i,record in enumerate(snapshots):
        if progress:
            progress(2+90*i/max(1,len(snapshots)),
                     "Reusing original prepared Dhan source "+str(i+1)+"/"+str(len(snapshots)))
        try:
            result=shared_market_data.ingest_prepared(record["id"])
            completed.append({"source":record["id"],
                              "rows_added":result["rows_appended"],
                              "rows_reused":result["rows_reused"]})
        except (ValueError,OSError,sqlite3.Error) as exc:
            blocked.append({"source":record["id"],
                            "reason":str(exc)[:160]})
    if progress:
        progress(100,"Shared market library updated from original local source evidence")
    return {"status":"complete" if not blocked else "partial",
            "destination_dataset_id":shared_market_data.SHARED_ID,
            "sources_scanned":len(snapshots),"sources_ingested":len(completed),
            "sources_blocked":blocked,"sources_imported":completed,
            "original_snapshots_preserved":True,
            "external_market_requests":0}
