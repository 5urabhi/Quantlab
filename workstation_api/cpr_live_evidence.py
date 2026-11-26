"""Bounded audit of already saved exact identities and original live quotes."""
from contextlib import closing
from datetime import datetime
from hashlib import sha256
from math import isfinite
import json
import sqlite3
from statistics import median
from . import shared_market_data

MAX_QUOTE_EVENTS=20000
MAX_CHAIN_SNAPSHOTS=20


def _stats(values):
    data=sorted(v for v in values if isfinite(v))
    if not data:
        return {"samples":0,"median":None,"p95":None}
    return {"samples":len(data),"median":round(median(data),3),
            "p95":round(data[int(.95*(len(data)-1))],3)}


def audit():
    path=shared_market_data.database_path()
    if not path.is_file() or path.is_symlink():
        return {"state":"no_saved_live_database"}
    with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)) as db:
        db.execute("PRAGMA query_only=ON")
        tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        report={"state":"saved_evidence","quote_sample":{},"chain_sample":{},
                "warning":"Latest bounded samples only. Trade receipt age includes time since last trade, not network or order latency. REST duration is request round-trip, not exchange freshness or execution. No fills inferred."}
        if "dhan_option_live_events" in tables:
            rows=db.execute("SELECT session_id,identity,received_utc,exchange_trade_utc "
                "FROM dhan_option_live_events ORDER BY received_utc DESC LIMIT ?",(MAX_QUOTE_EVENTS,)).fetchall()
            pairs={(session,identity) for session,identity,_,_ in rows}
            mappings=set()
            if "dhan_option_contract_sessions" in tables:
                for session in sorted({s for s,_ in pairs}):
                    mappings.update((session,x[0]) for x in db.execute(
                        "SELECT identity FROM dhan_option_contract_sessions WHERE session_id=?",(session,)))
            ages=[]
            for _,_,received,trade in rows:
                if trade:
                    try:
                        age=(datetime.fromisoformat(received)-datetime.fromisoformat(trade)).total_seconds()
                        if isfinite(age):ages.append(age)
                    except (ValueError,TypeError):
                        pass
            report["quote_sample"]={"events":len(rows),"contract_session_pairs":len(pairs),
                 "exact_mapped_pairs":len(pairs&mappings),"unmapped_legacy_pairs":len(pairs-mappings),
                 "trade_receipt_age_seconds":_stats(ages),"bounded":len(rows)==MAX_QUOTE_EVENTS}
        if "option_chain_observations" in tables:
            rows=db.execute("SELECT snapshot_sha256,normalized_json FROM option_chain_observations "
                "WHERE length(normalized_json)<=4000000 ORDER BY captured_utc DESC LIMIT ?",(MAX_CHAIN_SNAPSHOTS,)).fetchall()
            accepted=0;rejected=0;spreads=[];durations=[];identities=set()
            for digest,payload in rows:
                try:
                    if sha256(payload.encode()).hexdigest()!=digest:
                        raise ValueError("Snapshot hash mismatch")
                    snapshot=json.loads(payload)
                    contracts=snapshot["contracts"]
                    if not isinstance(contracts,list):
                        raise ValueError("Invalid contracts")
                    accepted+=1
                    elapsed=snapshot.get("rest_request_elapsed_ms")
                    if type(elapsed) in (int,float) and isfinite(elapsed) and elapsed>=0:
                        durations.append(elapsed)
                    for c in contracts:
                        if not isinstance(c,dict) or not c.get("contract_master_verified") or not c.get("identity"):
                            continue
                        bid,ask,lot=c.get("bid"),c.get("ask"),c.get("lot_size")
                        if (type(bid) in (int,float) and type(ask) in (int,float) and
                            isfinite(bid) and isfinite(ask) and 0<bid<=ask and type(lot) is int and lot>0):
                            identities.add(c["identity"])
                            spreads.append((ask-bid)*lot)
                except (ValueError,TypeError,KeyError,AttributeError):
                    rejected+=1
            report["chain_sample"]={"verified_snapshots":accepted,"rejected_snapshots":rejected,
                "exact_bid_ask_identities":len(identities),"spread_inr_per_lot":_stats(spreads),
                "rest_round_trip_ms":_stats(durations)}
        return report
