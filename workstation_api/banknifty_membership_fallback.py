"""Read-only dated membership fallback for historical BANKNIFTY research.

A candle file is not proof of membership. Original pinned batches remain the
primary evidence; a newer checked local reconstruction or a same-day official
list saved before opening can supplement uncovered dates only.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
from . import pit_index as pit, banknifty_constituents as bank
from . import dhan_workspace as dw, historical_alpha as h


def _resolved(symbols,catalog):
    by_symbol=defaultdict(list)
    for item in catalog:
        if (item.get("exchange_segment")=="NSE_EQ" and item.get("regular_eq")
                and item.get("trading_symbol_verified") and bank.IDENTITY.fullmatch(str(item.get("id","")))):
            by_symbol[str(item.get("symbol","")).upper()].append(item["id"])
    if not symbols or any(len(by_symbol[s])!=1 for s in symbols):
        return None
    result={s:by_symbol[s][0] for s in sorted(symbols)}
    return result if len(set(result.values()))==len(result) else None


def local_archive(dates,catalog):
    """Verify the exact normalized bytes parsed, without syncing or writing."""
    csv=pit._csv_path();manifest=pit._metadata_path()
    for path in (csv,manifest):
        if path.is_symlink() or path.parent.is_symlink() or not path.is_file():
            raise ValueError("Saved reconstructed membership unavailable or unsafe")
    if not 0<csv.stat().st_size<=pit.MAX_BYTES or not 0<manifest.stat().st_size<=256000:
        raise ValueError("Saved reconstructed membership exceeds bounds")
    meta=json.loads(manifest.read_text(encoding="utf-8"))
    payload=csv.read_bytes()
    digest=sha256(payload).hexdigest()
    if digest!=meta.get("normalized_sha256") or meta.get("source_repository")!=pit.SOURCE_REPOSITORY:
        raise ValueError("Saved membership checksum or source mismatch")
    first=date.fromisoformat(meta["first_date"]);last=date.fromisoformat(meta["covered_through"])
    if first>last:raise ValueError("Invalid reconstructed membership coverage")
    frame=pit._load_frame(payload)
    out={};unresolved=[]
    for day in dates:
        d=date.fromisoformat(day)
        if not first<=d<=last:continue
        symbols=pit._asof(frame,pit.MODES["banknifty_pit"],day)
        expected=14 if day>=pit.CORRECTION_EFFECTIVE else 12 if day>="2020-03-27" else None
        if expected is not None and len(symbols)!=expected:
            unresolved.append(day);continue
        values=_resolved(symbols,catalog)
        if values is None:unresolved.append(day)
        else:out[day]=values
    return out,{"source":"local_reconstructed_membership","source_sha256":digest,
                "source_commit":meta.get("source_commit"),"first_date":first.isoformat(),
                "covered_through":last.isoformat(),"unresolved_dates":unresolved,
                "warning":"Independent reconstruction, not exchange certification."}


def supplement(dates,pinned,conflicts):
    """Fill only undocumented dates using explicitly date-bounded evidence.

    Do not resolve a contradictory pinned date by silently choosing a winner.
    If the reconstructed archive disagrees with any overlapping pinned mapping,
    reject that fallback rather than mixing incompatible histories.
    """
    out={d:dict(v) for d,v in pinned.items()}
    blocked=set(conflicts)
    source={d:"pinned_batch" for d in out}
    audit={"source_by_date":source,"local_archive":{"state":"not_needed"},
           "official_receipt_hashes":{},"official_receipt_failures":{},
           "blocked_conflicting_dates":sorted(blocked)}
    wanted=sorted(set(dates)-set(out)-blocked)
    if wanted:
        try:
            catalog=dw.catalog()
        except (OSError,ValueError,TypeError,KeyError) as exc:
            catalog=[];audit["catalog_failure"]=type(exc).__name__
        try:
            local,meta=local_archive(sorted(set(dates)),catalog)
            disagreement=sorted(d for d in set(local)&set(out) if local[d]!=out[d])
            audit["local_archive"]={**meta,"state":"overlap_conflict" if disagreement else "checked",
                                    "overlap_conflicts":disagreement}
            if not disagreement:
                for day in wanted:
                    if day in local:
                        out[day]=local[day];source[day]="local_reconstructed_membership"
        except (OSError,ValueError,TypeError,KeyError,OverflowError) as exc:
            audit["local_archive"]={"state":"unavailable","reason":str(exc)[:180]}
        for day in wanted:
            if day in out:continue
            try:
                d=date.fromisoformat(day)
                # Same-day public list is usable only if captured by the
                # regular session opening; no after-open or next-day backfill.
                cutoff=datetime.combine(d,datetime.min.time(),h.IST)+timedelta(hours=9,minutes=15)
                info=bank._current_membership(d,catalog,cutoff)
                if info is None:continue
                values=info["resolved"];symbols=info["symbols"]
                if not symbols or set(values)!=set(symbols) or len(set(values.values()))!=len(values):
                    audit["official_receipt_failures"][day]="unresolved_or_duplicate_security_ids";continue
                if any(not bank.IDENTITY.fullmatch(str(v)) for v in values.values()):
                    audit["official_receipt_failures"][day]="invalid_security_id";continue
                out[day]=dict(values);source[day]="same_day_official_preopen"
                audit["official_receipt_hashes"][day]=info["source_sha256"]
            except (OSError,ValueError,TypeError,KeyError,OverflowError) as exc:
                audit["official_receipt_failures"][day]=type(exc).__name__
    audit["remaining_missing_dates"]=sorted(set(dates)-set(out))
    audit["recovered_dates"]=sorted(set(out)-set(pinned))
    return out,audit
