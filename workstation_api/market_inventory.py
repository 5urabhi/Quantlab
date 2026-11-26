"""Read-only inventory of the unified market library and its original receipts.

Rows describe observed extents, never requested date windows or continuous
coverage. Different resolutions/record types and overlapping historical
receipts are intentionally not summed into a fictitious total. Bounded scans
run only on demand and are cached; no provider calls or recorder locks.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, date, timezone, timedelta
import csv
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import time

from . import shared_market_data, service, cockpit_sources

# (id, label, unit, timestamp basis, storage, provenance)
SOURCES = {
    "daily_closes": ("Daily stock closes", "closes", "Session date", "Canonical SQLite", "Canonical unadjusted observed closes"),
    "raw_daily": ("Historical equity OHLCV", "candles", "Observation time", "Original Dhan CSV", "Original daily cache; may overlap canonical closes"),
    "raw_intraday": ("Historical equity intraday", "candles", "Observation time", "Original Dhan CSV", "Separate resolution per instrument"),
    "index_history": ("Historical index candles", "candles", "Observation time", "Original IDX_I batches", "Each batch listed separately; batches can overlap"),
    "constituent_derivative_quote": ("Constituent derivative quotes", "sampled quote packets", "Receipt time (UTC)", "Canonical SQLite", "Original optional stock futures and stock option quote observations"),
    "constituent_derivative_oi": ("Constituent derivative open interest", "sampled OI packets", "Receipt time (UTC)", "Canonical SQLite", "Original optional stock derivative OI observations; no exchange trade timestamp"),
    "prospective_signals": ("Prospective paired research decisions", "horizon decision rows", "Decision time (UTC)", "Canonical SQLite", "Derived frozen-rule research ledger; not additional original market data"),
    "constituent_quotes": ("BANKNIFTY constituent quotes", "sampled quote packets", "Receipt time (UTC)", "Canonical SQLite", "Original cash-equity quotes sampled at most once per two seconds per instrument"),
    "live_ticks": ("Recorded index ticks", "ticks", "Exchange time (UTC)", "Canonical SQLite", "Original observed ticker packets"),
    "live_minute_bars": ("Recorded minute OHLC", "minute bars", "Bar time (UTC)", "Canonical SQLite", "Derived from recorded ticks; not additional tick coverage"),
    "option_quote": ("Live option quotes", "quote packets", "Receipt time (UTC)", "Canonical SQLite", "Original quote events, not unique trades"),
    "option_oi": ("Live option open interest", "OI packets", "Receipt time (UTC)", "Canonical SQLite", "Original OI events, not unique trades"),
    "option_chain": ("Option chain snapshots", "snapshots", "Receipt time (UTC)", "Canonical SQLite", "One snapshot per underlying, expiry and receipt time"),
    "live_depth_books": ("Recorded depth books", "books", "Receipt time (UTC)", "Canonical SQLite", "Saved books; count does not certify 20 valid levels"),
    "depth_features": ("Depth analytics", "feature rows", "Receipt time (UTC)", "Canonical SQLite", "Derived from recorded books"),
    "sector_history": ("Dated sector classifications", "classifications", "Effective date", "Canonical SQLite", "Effective-dated source classifications"),
    "active_option_history": ("Contract-specific option history", "returned timestamp rows", "Observation time (UTC)", "Original Dhan intraday receipts", "Exact NSE_FNO security IDs captured while listed; strike, expiry and lot require archived instrument evidence; receipt ranges may overlap"),
    "expired_options": ("Expired option history", "returned timestamp rows", "Observation time (UTC)", "Original rolling-option receipts", "Rolling strike-offset responses; may overlap and include unusable prices"),
    "market_context": ("Cross-market factor observations", "observations", "Source availability time (UTC)", "Canonical SQLite", "Reviewed imports and automatic provider receipts; revisions may coexist"),
    "market_event_receipts": ("Macro calendar & news receipts", "source snapshots", "Receipt time (UTC)", "Canonical SQLite", "Official feed snapshots, not individual independent news events"),
    "market_news": ("Official announcement observations", "headlines", "First receipt time (UTC)", "Canonical SQLite", "First observed official announcement identities, not a complete news universe"),
    "archives": ("Saved session archives", "archive receipts", "Session date", "Session archives", "Copies of canonical data, not extra observations"),
}

# SQL is fixed and internal. Payload columns (book_json, normalized_json,
# feature_json) are never read by inventory SQL.
SQL = {
    "market_context": ("market_context_observations", "factor", "available_utc", "", ""),
    "market_event_receipts": ("market_event_receipts", "source", "received_utc", "", ""),
    "market_news": ("market_news_observations", "source", "first_received_utc", "", ""),
    "constituent_derivative_quote": ("constituent_derivative_events", "identity", "received_utc", "WHERE kind='quote'", ""),
    "constituent_derivative_oi": ("constituent_derivative_events", "identity", "received_utc", "WHERE kind='oi'", ""),
    "prospective_signals": ("banknifty_paired_signals", "identity", "decided_utc", "", "horizon_minutes"),
    "constituent_quotes": ("banknifty_constituent_quotes", "identity", "received_utc", "", ""),
    "daily_closes": ("daily_closes", "identity", "session_date", "", ""),
    "live_ticks": ("live_ticks", "identity", "exchange_utc", "", ""),
    "live_minute_bars": ("live_minute_bars", "identity", "minute_utc", "", ""),
    "option_quote": ("dhan_option_live_events", "identity", "received_utc", "WHERE kind='quote'", ""),
    "option_oi": ("dhan_option_live_events", "identity", "received_utc", "WHERE kind='oi'", ""),
    "option_chain": ("option_chain_observations", "underlying", "captured_utc", "", "expiry"),
    "live_depth_books": ("live_depth_books", "identity", "received_utc", "", ""),
    "depth_features": ("auto_banknifty_depth_features", "identity", "received_utc", "", ""),
    "sector_history": ("sector_history", "identity", "effective_date", "", ""),
}
MAX_GROUPS = 20000
MAX_RECEIPTS = 20000
MAX_JSON = 10_000_000
TTL = 60
LOCK = threading.Lock()
CACHE = None
CACHE_KEY = None
CACHE_TIME = 0.0


def _now():
    return datetime.now(timezone.utc).isoformat()


def _safe_file(path):
    root = service.DATA.resolve()
    return (path.is_file() and not path.is_symlink() and
            path.resolve().is_relative_to(root) and
            not any(p.is_symlink() for p in path.parents if p != root and p.is_relative_to(root)))


def _stamp(value):
    raw = str(value or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return date.fromisoformat(raw).isoformat()
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        # Don't guess a time zone for stored naive timestamps.
        return dt.isoformat()
    return dt.astimezone(timezone.utc).isoformat()


def _entry(source, identity, name, resolution, count, start, end, evidence, qualifier=""):
    if type(count) is not int or count < 0:
        raise ValueError("Invalid stored row count")
    start = _stamp(start) if start else None
    end = _stamp(end) if end else None
    if count and (not start or not end or start > end):
        raise ValueError("Stored date extent unavailable")
    return dict(source=source, identity=str(identity)[:160], name=str(name)[:180],
                resolution=str(resolution)[:120], count=count, first=start, last=end,
                evidence=evidence, qualifier=str(qualifier)[:180])


def _summary(source, rows, state, detail=""):
    label, unit, basis, storage, provenance = SOURCES[source]
    nonempty = [r for r in rows if r["count"] > 0]
    return dict(id=source, label=label, unit=unit, time_basis=basis, storage=storage,
                provenance=provenance, state=state, detail=detail,
                groups=len(rows), instruments=len({r["identity"] for r in nonempty}),
                count=sum(r["count"] for r in nonempty) if state in ("stored","receipt","empty") else None,
                first=min((r["first"] for r in nonempty),default=None),
                last=max((r["last"] for r in nonempty),default=None),
                inspected_count=sum(r["count"] for r in nonempty))


def _sql_inventory(path):
    rows = []
    summaries = []
    if not _safe_file(path):
        return rows, [_summary(key, [], "not_recorded", "Canonical store not present") for key in SQL]
    try:
        with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=0.5)) as db:
            db.execute("PRAGMA query_only=ON")
            db.execute("PRAGMA trusted_schema=OFF")
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            names = dict(db.execute("SELECT identity,display_symbol FROM instruments")) if "instruments" in tables else {}
            for key,(table,identity,stamp,where,extra) in SQL.items():
                if table not in tables:
                    summaries.append(_summary(key, [], "not_recorded", "Source table not created"))
                    continue
                subset = []
                deadline = time.monotonic()+1.5
                db.set_progress_handler(lambda: int(time.monotonic()>deadline), 5000)
                try:
                    fields = identity + (","+extra if extra else "")
                    query = ("SELECT "+fields+",COUNT(*),MIN("+stamp+"),MAX("+stamp+") FROM "+table+" "+where+
                             " GROUP BY "+fields+" ORDER BY "+fields+" LIMIT ?")
                    found = db.execute(query,(MAX_GROUPS+1,)).fetchall()
                    bounded = len(found)>MAX_GROUPS
                    for result in found[:MAX_GROUPS]:
                        ident, qualifier = (result[0],result[1]) if extra else (result[0],"")
                        count,first,last = result[-3:]
                        subset.append(_entry(key,ident,names.get(ident,ident),qualifier or
                            ("1 min" if key=="live_minute_bars" else "Daily" if key=="daily_closes" else "Event"),
                            count,first,last,"stored_rows",qualifier))
                    summaries.append(_summary(key,subset,"partial" if bounded else "stored" if subset else "empty",
                        "Group limit reached; only inspected groups shown" if bounded else
                        "Exact SQL counts and stored endpoints; payload integrity and missing sessions not audited"))
                    rows.extend(subset)
                except (sqlite3.Error,ValueError,TypeError):
                    # A grouped full-table count can time out even with millions
                    # of valid records. Make an independent bounded presence
                    # probe; never turn a failed count into a zero count.
                    present=None
                    sample_deadline=time.monotonic()+.25
                    db.set_progress_handler(lambda: int(time.monotonic()>sample_deadline),500)
                    try:
                        present=db.execute("SELECT 1 FROM "+table+" "+where+" LIMIT 1").fetchone() is not None
                    except sqlite3.Error:
                        pass
                    detail="Bounded grouped query did not finish or schema/date evidence needs review"
                    if present is True:
                        detail+="; at least one matching stored row confirmed, exact count and dates unavailable"
                    elif present is False:
                        detail+="; separate presence probe found no matching rows at inspection time"
                    summaries.append({**_summary(key,[],"not_verified",detail),"sample_present":present})
                finally:
                    db.set_progress_handler(None,0)
    except (sqlite3.Error,OSError,ValueError):
        done={s["id"] for s in summaries}
        summaries.extend(_summary(key,[],"not_verified","Canonical store could not be safely read") for key in SQL if key not in done)
    return rows,summaries


def _json(path, limit):
    if not _safe_file(path) or not 0<path.stat().st_size<=limit:
        raise ValueError("Receipt unavailable or exceeds bound")
    return json.loads(path.read_text(encoding="utf-8"))


def _signature(path):
    st=path.stat()
    return (st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)


def _csv_endpoints(path):
    """Bounded edge read of a writer-sorted CSV; no claim of full integrity."""
    if not _safe_file(path) or path.stat().st_size<=0:
        raise ValueError("Original CSV unavailable")
    before=_signature(path)
    with path.open("rb") as f:
        header=f.readline(65537).decode("utf-8-sig")
        first=f.readline(65537).decode("utf-8")
        if len(header)>65536 or len(first)>65536:
            raise ValueError("Oversized CSV row")
        f.seek(max(0,before[2]-65536))
        tail=f.read(65536)
    last=tail.rstrip(b"\r\n").splitlines()[-1].decode("utf-8")
    columns=next(csv.reader([header]))
    idx=columns.index("datetime")
    a=next(csv.reader([first]))[idx]
    b=next(csv.reader([last]))[idx]
    if _signature(path)!=before:
        raise ValueError("Source changed while inspecting")
    return a,b


def _historical():
    rows=[]
    failures={"raw_daily":0,"raw_intraday":0,"index_history":0}
    bounded=False
    root=service.DATA/"dhan"/"history"
    deadline=time.monotonic()+3.0
    scanned=0
    if root.is_dir() and not root.is_symlink():
        for segment in ("NSE_EQ","BSE_EQ"):
            folder=root/segment
            if not folder.is_dir() or folder.is_symlink():
                continue
            for child in folder.iterdir():
                if bounded:
                    break
                if not child.is_dir() or child.is_symlink() or not re.fullmatch(r"[0-9]{1,12}",child.name):
                    continue
                identity=segment+":"+child.name
                for period in ("daily","1m","5m","15m","25m","60m"):
                    path=child/(period+".csv")
                    receipt=path.with_suffix(".json")
                    if not path.exists() and not receipt.exists():
                        continue
                    scanned+=1
                    if scanned>MAX_RECEIPTS or time.monotonic()>deadline:
                        bounded=True
                        break
                    key="raw_daily" if period=="daily" else "raw_intraday"
                    try:
                        signature=_signature(receipt)
                        data=_json(receipt,128000)
                        interval=None if period=="daily" else int(period[:-1])
                        if (data["instrument_id"]!=identity or data["interval_minutes"]!=interval or
                                not re.fullmatch(r"[0-9a-f]{64}",str(data["sha256"]))):
                            raise ValueError("Receipt identity mismatch")
                        a,b=_csv_endpoints(path)
                        if signature!=_signature(receipt):
                            raise ValueError("Receipt changed")
                        rows.append(_entry(key,identity,data.get("display_symbol") or identity,
                            "Daily" if interval is None else str(interval)+" min",
                            data["rows"],a,b,"receipt_count_csv_edges"))
                    except (OSError,ValueError,TypeError,KeyError,IndexError,UnicodeError):
                        failures[key]+=1
    # Index original batches retain their own independent receipts.
    try:
        for identity in cockpit_sources.INDEX_IDENTITIES:
            for path,receipt,data in cockpit_sources._candidates(identity):
                if scanned>=MAX_RECEIPTS or time.monotonic()>deadline:
                    bounded=True
                    break
                scanned+=1
                try:
                    a,b=_csv_endpoints(path)
                    rows.append(_entry("index_history",identity,cockpit_sources.INDEX_IDENTITIES[identity][1],
                        "1 min",data["row_count"],a,b,"receipt_count_csv_edges",path.parent.name))
                except (OSError,ValueError,TypeError,KeyError,IndexError,UnicodeError):
                    failures["index_history"]+=1
    except (OSError,ValueError):
        failures["index_history"]+=1
    summaries=[]
    for key,failed in failures.items():
        selected=[r for r in rows if r["source"]==key]
        state="partial" if bounded or failed else "receipt" if selected else "not_recorded"
        summaries.append(_summary(key,selected,state,
            (f"{failed} unreadable/mismatched receipt(s). " if failed else "")+
            ("Scan budget reached. " if bounded else "")+
            "Count from saved receipt and first/last actual CSV rows; full SHA and gap audit not repeated."))
    return rows,summaries


def _expired():
    """Separate flat intraday contract receipts from nested rolling receipts.

    Older versions saved both in the same folder with the same rolling
    source label. Classify using the original request AND response shape.
    Retain the old files byte-for-byte; no inferred strike or expiry.
    """
    root=service.DATA/"dhan_expired_options"
    kinds=("expired_options","active_option_history")
    rows={k:[] for k in kinds}
    failed={k:0 for k in kinds}
    empty={k:0 for k in kinds}
    inspected=0
    unknown=0
    bounded=False
    deadline=time.monotonic()+2.5
    if root.is_dir() and not root.is_symlink():
        for path in root.iterdir():
            if not re.fullmatch(r"[0-9a-f]{64}\.json",path.name):
                continue
            if inspected>=MAX_RECEIPTS or time.monotonic()>deadline:
                bounded=True
                break
            inspected+=1
            kind=None
            try:
                item=_json(path,MAX_JSON)
                body=item["request"]
                payload=item["payload"]
                if not isinstance(body,dict) or not isinstance(payload,dict):
                    raise ValueError("Bad receipt")
                canonical=json.dumps(body,sort_keys=True,separators=(",",":")).encode()
                raw=json.dumps(payload,sort_keys=True,separators=(",",":")).encode()
                if sha256(canonical).hexdigest()!=path.stem or sha256(raw).hexdigest()!=item["sha256"]:
                    raise ValueError("Option receipt SHA mismatch")
                if body.get("exchangeSegment")!="NSE_FNO" or body.get("instrument")!="OPTIDX":
                    raise ValueError("Unknown option instrument")
                sid=str(body["securityId"])
                if not sid.isdigit():
                    raise ValueError("Bad option security ID")
                interval=str(body.get("interval",""))
                if interval not in ("1","5","15","25","60"):
                    raise ValueError("Bad option interval")
                if "drvOptionType" in body and isinstance(payload.get("data"),dict):
                    kind="expired_options"
                    side=body["drvOptionType"]
                    if side not in ("CALL","PUT") or item.get("source")!="Dhan v2 /charts/rollingoption":
                        raise ValueError("Unknown rolling option receipt")
                    segment=payload["data"].get("ce" if side=="CALL" else "pe")
                    if segment is None:
                        segment={}
                    if not isinstance(segment,dict):
                        raise ValueError("Bad rolling response")
                    stamps=segment.get("timestamp",[])
                    identity="ROLLING:"+sid+":"+side+":"+str(body.get("strike",""))
                    qualifier=str(body.get("expiryFlag",""))+" "+str(body.get("expiryCode",""))+" · "+path.stem[:12]
                elif ("drvOptionType" not in body and type(body.get("oi")) is bool
                      and isinstance(payload.get("timestamp"),list)):
                    kind="active_option_history"
                    if item.get("source") not in ("Dhan v2 /charts/intraday","Dhan v2 /charts/rollingoption"):
                        raise ValueError("Unknown contract option receipt")
                    stamps=payload["timestamp"]
                    if any(not isinstance(payload.get(k),list) or len(payload[k])!=len(stamps)
                           for k in ("open","high","low","close","volume")):
                        raise ValueError("Unaligned contract response")
                    identity="NSE_FNO:"+sid
                    qualifier="Exact ID · "+path.stem[:12]
                else:
                    raise ValueError("Unknown option receipt structure")
                if not isinstance(stamps,list):
                    raise ValueError("Bad source times")
                if not stamps:
                    empty[kind]+=1
                    continue
                times=[datetime.fromtimestamp(float(t),tz=timezone.utc).isoformat() for t in stamps]
                rows[kind].append(_entry(kind,identity,identity,interval+" min",
                    len(times),min(times),max(times),"receipt_timestamps",qualifier))
            except (OSError,ValueError,TypeError,KeyError,AttributeError,OverflowError,UnicodeError):
                if kind is None:
                    unknown+=1
                else:
                    failed[kind]+=1
    summaries=[]
    for kind in kinds:
        state=("partial" if failed[kind] or unknown or bounded else
               "receipt" if rows[kind] else "empty" if empty[kind] else "not_recorded")
        summaries.append(_summary(kind,rows[kind],state,
            f"{len(rows[kind])} nonempty verified receipts; {empty[kind]} empty; {failed[kind]} invalid; {unknown} unclassified. "
            +("Scan budget reached. " if bounded else "")
            +"Request and payload SHA-256 checked. Observed timestamp rows may overlap; no price or contract-term certification."))
    return [r for kind in kinds for r in rows[kind]],summaries


def _archives():
    rows=[];failed=0;bounded=False
    root=shared_market_data.database_path().parent/"session_archives"
    deadline=time.monotonic()+0.5
    if root.is_dir() and not root.is_symlink():
        for child in root.iterdir():
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}",child.name):
                continue
            if len(rows)+failed>=MAX_RECEIPTS or time.monotonic()>deadline:
                bounded=True;break
            try:
                item=_json(child/"manifest.json",256000)
                if item.get("session_ist")!=child.name or item.get("version")!=1:
                    raise ValueError("Archive manifest mismatch")
                rows.append(_entry("archives",child.name,"Session "+child.name,
                    "Backup",1,child.name,child.name,"archive_manifest"))
            except (OSError,ValueError,TypeError,KeyError):
                failed+=1
    return rows,_summary("archives",rows,"partial" if bounded or failed else "receipt" if rows else "not_recorded",
        f"{failed} unreadable archive manifests. Archive files not rehashed; no duplicate observation totals.")


def collect():
    rows,summaries=_sql_inventory(shared_market_data.database_path())
    for collector in (_historical,_expired,_archives):
        try:
            found,info=collector()
            rows.extend(found)
            summaries.extend(info if isinstance(info,list) else [info])
        except (OSError,ValueError):
            pass
    by_id={s["id"]:s for s in summaries}
    summaries=[by_id.get(key) or _summary(key,[],"not_verified","Local inspection unavailable") for key in SOURCES]
    return {"library_id":"dhan_shared","checked_utc":_now(),"sources":summaries,"rows":rows,
            "read_only":True,"external_requests":0,
            "note":"Observed extents are not continuous coverage. Counts have different units and may overlap; never sum across sources."}


def inventory(source="all",query="",page=1,per_page=50,refresh=False):
    global CACHE,CACHE_KEY,CACHE_TIME
    if source not in {"all",*SOURCES} or not 1<=page<=10000 or not 1<=per_page<=100 or len(query)>120:
        raise ValueError("Invalid inventory filter")
    key=str(service.DATA.resolve())
    with LOCK:
        if CACHE is None or CACHE_KEY!=key or time.monotonic()-CACHE_TIME>=TTL or (refresh and time.monotonic()-CACHE_TIME>=10):
            CACHE=collect();CACHE_KEY=key;CACHE_TIME=time.monotonic()
        result=CACHE
    needle=query.strip().casefold()
    selected=[r for r in result["rows"] if (source=="all" or r["source"]==source) and
              (not needle or needle in " ".join(str(r[k]) for k in ("identity","name","resolution","qualifier")).casefold())]
    selected.sort(key=lambda r:(r["source"],r["name"],r["identity"],r["resolution"],r["qualifier"]))
    offset=(page-1)*per_page
    return {**{k:v for k,v in result.items() if k!="rows"},"items":selected[offset:offset+per_page],
            "total":len(selected),"page":page,"has_more":offset+per_page<len(selected),
            "cache_age_seconds":round(time.monotonic()-CACHE_TIME,1)}


# Fixed, small scalar record previews. No credentials, original JSON payloads
# or raw file paths. Full depth and chain payloads remain in Trading / Replay.
RECORD_COLUMNS = {
    "market_context": ("available_utc","factor","event_utc","value","receipt_sha256"),
    "market_event_receipts": ("received_utc","source","sha256"),
    "market_news": ("first_received_utc","source","published_utc","event_id","title","topic","link"),
    "constituent_derivative_quote": ("received_utc","exchange_trade_utc","identity","underlying","instrument","expiry","strike","option_type","lot_size","price","volume","packet_sha256","membership_sha256"),
    "constituent_derivative_oi": ("received_utc","identity","underlying","instrument","expiry","strike","option_type","open_interest","packet_sha256","membership_sha256"),
    "prospective_signals": ("decided_utc","identity","protocol_hash","slot_utc","cutoff_utc","target_utc","horizon_minutes","reference_price","pressure","volume_pressure","ema_rsi","outcome","observed_price","observed_received_utc","reference_sha256","observed_sha256"),
    "constituent_quotes": ("received_utc","exchange_trade_utc","identity","symbol","session_ist","price","volume","atp","buy_quantity","sell_quantity","packet_sha256","membership_sha256"),
    "daily_closes": ("session_date","identity","close","source_sha256"),
    "live_ticks": ("exchange_utc","received_utc","identity","price","packet_sha256"),
    "live_minute_bars": ("minute_utc","identity","open","high","low","close","tick_count","last_received_utc"),
    "option_quote": ("received_utc","exchange_trade_utc","identity","price","volume","last_trade_quantity","packet_sha256"),
    "option_oi": ("received_utc","identity","open_interest","packet_sha256"),
    "option_chain": ("captured_utc","underlying","expiry","snapshot_sha256"),
    "live_depth_books": ("received_utc","identity","packet_pair_sha256"),
    "depth_features": ("received_utc","identity","book_pair_sha256"),
    "sector_history": ("effective_date","identity","sector","source_sha256"),
}


def records(source, identity, qualifier="", before="", limit=50):
    if source not in RECORD_COLUMNS or not 1<=limit<=100 or not 0<len(identity)<=160 or len(qualifier)>180 or len(before)>40:
        raise ValueError("Invalid record preview selection")
    table,identity_col,stamp,condition,extra=SQL[source]
    path=shared_market_data.database_path()
    if not _safe_file(path):
        raise ValueError("Canonical source not present")
    where=[identity_col+"=?"]
    args=[identity]
    if condition:
        where.append(condition.removeprefix("WHERE "))
    if extra:
        if not qualifier:
            raise ValueError("Choose the exact saved group qualifier")
        where.append(extra+"=?");args.append(qualifier)
    if before:
        _stamp(before)
        where.append(stamp+"<?");args.append(before)
    try:
        with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=0.5)) as db:
            db.execute("PRAGMA query_only=ON")
            db.execute("PRAGMA trusted_schema=OFF")
            deadline=time.monotonic()+1.5
            db.set_progress_handler(lambda:int(time.monotonic()>deadline),5000)
            existing={r[1] for r in db.execute("PRAGMA table_info("+table+")")}
            columns=[name for name in RECORD_COLUMNS[source] if name in existing]
            if stamp not in columns or identity_col not in columns:
                raise ValueError("Saved record schema unavailable")
            found=db.execute("SELECT "+",".join(columns)+" FROM "+table+" WHERE "+
                " AND ".join(where)+" ORDER BY "+stamp+" DESC LIMIT ?",(*args,limit+1)).fetchall()
            output=found[:limit]
    except sqlite3.Error as exc:
        raise ValueError("Record preview exceeded its bounded read budget or source is unavailable") from exc
    # Timestamp cursor is deliberately strict. Multiple same-time packets can
    # share a receipt time; this is a preview, not a lossless event export.
    return {"source":source,"identity":identity,"qualifier":qualifier,"columns":columns,
            "rows":[list(r) for r in output],"has_more":len(found)>limit,
            "before":output[-1][columns.index(stamp)] if output and len(found)>limit else None,
            "note":"Newest matching stored rows (scalar preview). Equal-time packets at a page boundary may be omitted. Not a complete source export."}


def daily_activity(source, start, end):
    """Bounded read-only calendar-day counts for one canonical record type.

    Zero means no matching stored records for that calendar day after a
    completed query, not a missing exchange session or a data outage.
    """
    if source not in SQL or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", start) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", end):
        raise ValueError("Choose a canonical source and ISO calendar dates")
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if not 0 <= (last-first).days < 90 or last == date.max:
        raise ValueError("Choose an inclusive window of 1 to 90 calendar days")
    table, identity, stamp, condition, _ = SQL[source]
    label, unit, basis, _, _ = SOURCES[source]
    report = {"source":source,"label":label,"unit":unit,"time_basis":basis,
              "start":start,"end":end,"checked_utc":_now(),"rows":[],
              "note":"Stored date prefixes; counts are distinct records of the selected type. Zero is not a confirmed missing trading session."}
    path = shared_market_data.database_path()
    if not _safe_file(path):
        return {**report,"state":"not_recorded","detail":"Canonical store is unavailable."}
    try:
        with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=0.5)) as db:
            db.execute("PRAGMA query_only=ON")
            db.execute("PRAGMA trusted_schema=OFF")
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                return {**report,"state":"not_recorded","detail":"Source table has not been created."}
            where = [stamp+">=?", stamp+"<?"]
            if condition:
                where.append(condition.removeprefix("WHERE "))
            deadline = time.monotonic()+2.0
            db.set_progress_handler(lambda:int(time.monotonic()>deadline),5000)
            result = db.execute("SELECT substr("+stamp+",1,10),COUNT(*),COUNT(DISTINCT "+identity+") FROM "+
                 table+" WHERE "+" AND ".join(where)+" GROUP BY 1 ORDER BY 1",
                 (start,(last+timedelta(days=1)).isoformat())).fetchall()
            counts = {}
            for day, count, instruments in result:
                if not isinstance(day,str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}",day) or not first<=date.fromisoformat(day)<=last:
                    raise ValueError("Invalid saved timestamp")
                counts[day] = (count,instruments)
            rows=[]
            for i in range((last-first).days+1):
                day=(first+timedelta(days=i)).isoformat()
                count,instruments=counts.get(day,(0,0))
                rows.append({"date":day,"count":count,"instruments":instruments})
            return {**report,"state":"stored","rows":rows,"detail":"Completed bounded SQLite query; original data unchanged."}
    except (sqlite3.Error,OSError,ValueError):
        return {**report,"state":"not_verified","detail":"The bounded read could not complete. Try a shorter date window."}
