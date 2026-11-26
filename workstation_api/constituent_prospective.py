"""Frozen prospective BANKNIFTY rules on receipt-time local observations.

The worker cannot backdate a signal. It opens no provider sockets, calls no
order endpoints and does not train or calibrate a model. All methods share
one actual decision and target clock. Abstention is distinct from missing data.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone, time as clock_time
from hashlib import sha256
from threading import Event, RLock, Thread
import json
import math
import random
import sqlite3
import time

from . import banknifty_constituents as bank, live_market, market_inventory, recorder_storage, shared_market_data, trading_cockpit

VERSION="bank-constituent-paired-v1"
METHODS=("pressure","volume_pressure","ema_rsi")
HORIZONS=(1,5,10,30,60)
PROTOCOL={
    "version":VERSION,"feature_minutes":5,"cadence_seconds":60,
    "min_move_pct":.02,"min_breadth_pp":20,
    "min_rvol_weight_pct":80,"rvol_cap":3,"min_signed_rvol":.20,
    "ema_baseline":trading_cockpit.VERSION,
    "horizons":HORIZONS,"spot_age_seconds":15,"max_compute_seconds":5,
    "label_window_seconds":30,"label_settle_seconds":90,
    "label":"first original index tick with exchange and receipt timestamps at or after target, within 30s; exact price comparison",
    "rules":"pressure requires complete weighted basket; volume_pressure additionally requires signed RVOL agreement; EMA-RSI uses existing unmodified baseline on same-session completed observed minute bars",
}
PROTOCOL_HASH=sha256(json.dumps(PROTOCOL,sort_keys=True).encode()).hexdigest()
# Additive protocol: retain original v1 rows and consent hash verbatim.
EXTRA_HORIZONS=(15,0)
RECORD_HORIZONS=HORIZONS+EXTRA_HORIZONS
EXTRA_PROTOCOL={**PROTOCOL,"version":"bank-constituent-paired-extra-v1",
                "horizons":EXTRA_HORIZONS,
                "close_target":"15:29:20 IST, first qualified tick within 30s, at least 5 minutes ahead; not official close"}
EXTRA_PROTOCOL_HASH=sha256(json.dumps(EXTRA_PROTOCOL,sort_keys=True).encode()).hexdigest()


def protocol_for(horizon):
    if horizon in HORIZONS:
        return PROTOCOL_HASH
    if horizon in EXTRA_HORIZONS:
        return EXTRA_PROTOCOL_HASH
    raise ValueError("Unsupported prospective horizon")


def target_for(decided,horizon):
    if horizon==0:
        local=_session(decided)
        return local.replace(hour=15,minute=29,second=20,microsecond=0).astimezone(timezone.utc)
    return decided+timedelta(minutes=horizon)

STREAM="prospective_bank_signals"
LOCK=RLock()
STOP=Event()
WORKER=None
STATE={"state":"idle","last_attempt_utc":None,"last_error":None}
TABLE="banknifty_paired_signals"


def _now():
    return datetime.now(timezone.utc)


def _iso(t):
    return bank._iso(t)


def _session(t):
    return t.astimezone(live_market.IST)


def _regular(t):
    local=_session(t)
    return local.weekday()<5 and clock_time(9,15)<=local.time().replace(tzinfo=None)<clock_time(15,30)


def _consent():
    return bank._safe_folder()/"prospective_consent.json"


def enabled():
    try:
        p=_consent()
        if not p.is_file() or p.is_symlink() or p.stat().st_size>=4096:
            return False
        body=json.loads(p.read_text())
        return body.get("enabled") is True and body.get("protocol_hash")==PROTOCOL_HASH
    except (OSError,ValueError,TypeError,AttributeError):
        return False


def configure(value):
    if type(value) is not bool:
        raise ValueError("Explicit boolean local recording consent required")
    with LOCK:
        bank._write_json(_consent(),{"enabled":value,"protocol_hash":PROTOCOL_HASH})
        if value:
            resume()
    return status()


def _setup(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS banknifty_paired_signals(
      identity TEXT NOT NULL, slot_utc TEXT NOT NULL, session_ist TEXT NOT NULL,
      protocol_hash TEXT NOT NULL, cutoff_utc TEXT NOT NULL, decided_utc TEXT NOT NULL,
      target_utc TEXT NOT NULL, horizon_minutes INTEGER NOT NULL,
      reference_price REAL, reference_sha256 TEXT, pressure TEXT NOT NULL,
      volume_pressure TEXT NOT NULL, ema_rsi TEXT NOT NULL, evidence_json TEXT NOT NULL,
      outcome TEXT NOT NULL, observed_price REAL, observed_exchange_utc TEXT,
      observed_received_utc TEXT, observed_sha256 TEXT, evaluated_utc TEXT,
      PRIMARY KEY(protocol_hash,slot_utc,horizon_minutes)
    );
    CREATE INDEX IF NOT EXISTS bank_paired_due
      ON banknifty_paired_signals(protocol_hash,outcome,target_utc);
    CREATE INDEX IF NOT EXISTS bank_paired_report
      ON banknifty_paired_signals(protocol_hash,horizon_minutes,slot_utc);
    """)


def _read():
    p=shared_market_data.database_path()
    if not market_inventory._safe_file(p):
        raise ValueError("Original shared store unavailable")
    db=sqlite3.connect(p.resolve().as_uri()+"?mode=ro",uri=True,timeout=.3)
    db.execute("PRAGMA query_only=ON")
    db.execute("PRAGMA trusted_schema=OFF")
    deadline=time.monotonic()+1.5
    db.set_progress_handler(lambda:int(time.monotonic()>deadline),5000)
    return db


def _valid_hash(v):
    return isinstance(v,str) and len(v)==64 and all(c in "0123456789abcdef" for c in v)


def _tick(db, start, stop, cutoff, *, first=False):
    order="ASC" if first else "DESC"
    row=db.execute(f"""SELECT price,exchange_utc,received_utc,packet_sha256
      FROM live_ticks WHERE identity='INDEX:BANKNIFTY'
      AND exchange_utc>=? AND exchange_utc<=? AND received_utc>=? AND received_utc<=?
      ORDER BY exchange_utc {order},received_utc {order},packet_sha256 {order} LIMIT 1""",
      (_iso(start),_iso(stop),_iso(start),_iso(cutoff))).fetchone()
    if not row:
        return None
    price,event,receipt,digest=row
    event_time=datetime.fromisoformat(event)
    receipt_time=datetime.fromisoformat(receipt)
    if (not _valid_hash(digest) or not math.isfinite(price) or price<=0
            or not start<=event_time<=stop or not start<=receipt_time<=cutoff
            or not -2<=(receipt_time-event_time).total_seconds()<=15
            or _session(event_time).date()!=_session(stop).date() or not _regular(event_time)):
        return None
    return {"price":price,"exchange_utc":event,"received_utc":receipt,"sha256":digest}


def pressure_rules(report):
    """Do not fall back to equal weights or fill missing constituents."""
    out={"pressure":"UNAVAILABLE","volume_pressure":"UNAVAILABLE","signed_rvol":None,"rvol_weight_pct":0.}
    if not report.get("complete_weighted_coverage"):
        return out
    r=report.get("weighted_return_pct")
    breadth=report.get("weighted_breadth_pct")
    snapshot=report.get("weight_snapshot") or {}
    members=report.get("membership") or {}
    rows=report.get("rows") or []
    if not _valid_hash(snapshot.get("source_csv_sha256")) or not _valid_hash(members.get("source_sha256")):
        return out
    if snapshot.get("membership_sha256")!=members["source_sha256"] or not rows:
        return out
    if any(not row.get("current") or not row.get("anchor") or
           row["current"].get("membership_sha256")!=members["source_sha256"] or
           row["anchor"].get("membership_sha256")!=members["source_sha256"] or
           not _valid_hash(row["current"].get("packet_sha256")) or
           not _valid_hash(row["anchor"].get("packet_sha256")) for row in rows):
        return out
    if not isinstance(r,(int,float)) or not math.isfinite(r) or not isinstance(breadth,(int,float)) or not math.isfinite(breadth):
        return out
    direction="UP" if r>=.02 and breadth>=20 else "DOWN" if r<=-.02 and breadth<=-20 else "ABSTAIN"
    out["pressure"]=direction
    valid=[x for x in rows if isinstance(x.get("relative_volume"),(int,float)) and math.isfinite(x["relative_volume"]) and x["relative_volume"]>=0 and x.get("baseline_sessions",0)>=5]
    covered=sum(x["weight_pct"] for x in valid)
    out["rvol_weight_pct"]=covered
    if covered<80:
        return out
    score=sum(x["weight_pct"]*(1 if x["return_pct"]>0 else -1 if x["return_pct"]<0 else 0)*min(x["relative_volume"],3) for x in valid)/covered
    out["signed_rvol"]=score
    out["volume_pressure"]=direction if ((direction=="UP" and score>=.20) or (direction=="DOWN" and score<=-.20)) else "ABSTAIN"
    return out


def _ema(db,cutoff):
    # Reconstruct the completed bars from original receipt-cutoff ticks.
    # The shared OHLC cache is mutable and its last-received field alone
    # cannot prove point-in-time information when packets arrive out of order.
    session=_session(cutoff)
    start=session.replace(hour=9,minute=15,second=0,microsecond=0)
    minute=cutoff.replace(second=0,microsecond=0)
    rows=db.execute("""SELECT exchange_utc,received_utc,price,packet_sha256
         FROM live_ticks WHERE identity='INDEX:BANKNIFTY'
         AND exchange_utc>=? AND exchange_utc<? AND received_utc<=?
         ORDER BY exchange_utc,received_utc,packet_sha256 LIMIT 60001""",
         (_iso(start),_iso(minute),_iso(cutoff))).fetchall()
    if len(rows)>60000:
        return "UNAVAILABLE",{"reason":"bounded_original_tick_limit"}
    grouped={}
    for event,receipt,price,digest in rows:
        observed=datetime.fromisoformat(event)
        received=datetime.fromisoformat(receipt)
        if not _valid_hash(digest) or not math.isfinite(price) or price<=0 or not -2<=(received-observed).total_seconds()<=15:
            continue
        if not start<=observed<minute or received>cutoff:
            continue
        key=_iso(observed.replace(second=0,microsecond=0))
        bar=grouped.get(key)
        if bar is None:
            grouped[key]={"timestamp_utc":key,"session_ist":session.date().isoformat(),
                          "open":price,"high":price,"low":price,"close":price}
        else:
            bar["high"]=max(bar["high"],price)
            bar["low"]=min(bar["low"],price)
            bar["close"]=price
    bars=list(grouped.values())
    if not bars:
        return "UNAVAILABLE",{"reason":"no_completed_original_bars"}
    snap=trading_cockpit.snapshot("INDEX:BANKNIFTY",bars,now=cutoff,include_chart=False)
    features={k:snap[k] for k in ("last_observed_utc","ema9","ema21","rsi14","contiguous_session_bars","quote_mode")}
    features["completed_bars_sha256"]=sha256(json.dumps(bars,sort_keys=True,allow_nan=False).encode()).hexdigest()
    if snap["quote_mode"]!="RECENT_LOCAL_CANDLE_NOT_VERIFIED_LIVE" or snap["contiguous_session_bars"]<30:
        return "UNAVAILABLE",features
    return ("ABSTAIN" if snap["direction"]=="NO_TRADE" else snap["direction"]),features


def _inputs(cutoff):
    result=bank.analyze(5,_iso(cutoff))
    rules=pressure_rules(result)
    try:
        with closing(_read()) as db:
            db.execute("BEGIN")
            ref=_tick(db,cutoff-timedelta(seconds=15),cutoff,cutoff)
            ema,ema_features=_ema(db,cutoff)
    except (sqlite3.Error,OSError,ValueError,TypeError):
        ref,ema,ema_features=None,"UNAVAILABLE",{"reason":"original_index_read_unavailable"}
    evidence={
        "weighted_return_pct":result["weighted_return_pct"],"weighted_breadth_pct":result["weighted_breadth_pct"],
        "observed_weight_pct":result["observed_weight_pct"],"members":result["observed_members"],
        "expected_members":result["expected_members"],"membership_sha256":result["membership"].get("source_sha256"),
        "weights_sha256":(result["weight_snapshot"] or {}).get("source_csv_sha256"),
        "weights_recorded_utc":(result["weight_snapshot"] or {}).get("recorded_utc"),
        "signed_rvol":rules["signed_rvol"],"rvol_weight_pct":rules["rvol_weight_pct"],
        "reference":ref,"ema":ema_features,"blockers":result["blockers"],
        "constituent_receipts":[{"symbol":r["symbol"],"weight_pct":r["weight_pct"],"return_pct":r["return_pct"],
                                 "relative_volume":r["relative_volume"],"baseline_sessions":r["baseline_sessions"],
                                 "current":r["current"],"anchor":r["anchor"]} for r in result["rows"]],
    }
    return ref,rules["pressure"],rules["volume_pressure"],ema,evidence


def _record(cutoff):
    # Private worker entrypoint; there is no endpoint accepting a historical
    # decision clock or arbitrary predictions. Recheck consent before writes.
    if not _regular(cutoff):
        return 0
    slot=cutoff.replace(second=0,microsecond=0)
    if not 5<=cutoff.second<=20 or not 0<=(_now()-cutoff).total_seconds()<=5:
        return 0
    try:
        with closing(_read()) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name=? AND type='table'",(TABLE,)).fetchone() and db.execute("SELECT 1 FROM banknifty_paired_signals WHERE protocol_hash=? AND slot_utc=? LIMIT 1",(PROTOCOL_HASH,_iso(slot))).fetchone():
                return 0
    except (sqlite3.Error,OSError,ValueError):
        return 0
    ref,pressure,volume,ema,evidence=_inputs(cutoff)
    with LOCK:
        decided=_now()
        if not enabled() or not bank.enabled() or not 0<=(decided-cutoff).total_seconds()<=5 or not _regular(decided):
            return 0
        if not recorder_storage.allow(STREAM,dropped=1):
            return 0
        # An absent reference is an unavailable decision for all methods.
        if ref is None:
            pressure=volume=ema="UNAVAILABLE"
        rows=[]
        for h in RECORD_HORIZONS:
            target=target_for(decided,h)
            if h==0 and target-decided<timedelta(minutes=5):
                continue
            if not _regular(target+timedelta(seconds=30)) or _session(target).date()!=_session(decided).date():
                continue
            rows.append(("INDEX:BANKNIFTY",_iso(slot),_session(decided).date().isoformat(),
                         protocol_for(h),_iso(cutoff),_iso(decided),_iso(target),h,
                         ref["price"] if ref else None,ref["sha256"] if ref else None,
                         pressure,volume,ema,json.dumps(evidence,allow_nan=False,sort_keys=True),
                         "PENDING" if ref else "UNVERIFIABLE"))
        if not rows:
            return 0
        path=shared_market_data.database_path()
        if not market_inventory._safe_file(path):
            return 0
        with closing(sqlite3.connect(path,timeout=.25)) as db:
            _setup(db)
            prior=db.total_changes
            # Lock acquisition/DDL must not create an effective backdated call.
            db.execute("BEGIN IMMEDIATE")
            if (_now()-decided).total_seconds()>1:
                db.rollback()
                return 0
            db.executemany("INSERT OR IGNORE INTO banknifty_paired_signals(identity,slot_utc,session_ist,protocol_hash,cutoff_utc,decided_utc,target_utc,horizon_minutes,reference_price,reference_sha256,pressure,volume_pressure,ema_rsi,evidence_json,outcome) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",rows)
            db.commit()
            count=db.total_changes-prior
        if count:
            recorder_storage.saved(STREAM,_iso(decided),count=count)
        return count


def _resolve(now):
    path=shared_market_data.database_path()
    if not market_inventory._safe_file(path):
        return 0
    with closing(_read()) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name=? AND type='table'",(TABLE,)).fetchone():
            return 0
        due=db.execute("""SELECT slot_utc,horizon_minutes,target_utc,reference_price,protocol_hash
           FROM banknifty_paired_signals WHERE protocol_hash IN (?,?) AND outcome='PENDING' AND target_utc<=?
           ORDER BY target_utc LIMIT 100""",(PROTOCOL_HASH,EXTRA_PROTOCOL_HASH,_iso(now-timedelta(seconds=90)))).fetchall()
    if not due:
        return 0
    updates=[]
    # Individual bounded indexed queries prevent an old backlog from locking
    # the source writer. Missing evidence is never repaired using later prices.
    for slot,horizon,target_text,reference,protocol in due:
        target=datetime.fromisoformat(target_text)
        try:
            with closing(_read()) as db:
                tick=_tick(db,target,target+timedelta(seconds=30),target+timedelta(seconds=30),first=True)
        except (OSError,sqlite3.Error,ValueError):
            continue
        outcome="UNVERIFIABLE" if not tick else "UP" if tick["price"]>reference else "DOWN" if tick["price"]<reference else "FLAT"
        updates.append((outcome,tick["price"] if tick else None,tick["exchange_utc"] if tick else None,tick["received_utc"] if tick else None,tick["sha256"] if tick else None,_iso(now),protocol,slot,horizon))
    if not updates or not recorder_storage.allow(STREAM,dropped=0):
        return 0
    with LOCK,closing(sqlite3.connect(path,timeout=.25)) as db:
        if not enabled():
            return 0
        prior=db.total_changes
        db.executemany("""UPDATE banknifty_paired_signals SET outcome=?,observed_price=?,observed_exchange_utc=?,
           observed_received_utc=?,observed_sha256=?,evaluated_utc=? WHERE protocol_hash=? AND slot_utc=?
           AND horizon_minutes=? AND outcome='PENDING'""",updates)
        db.commit()
        return db.total_changes-prior


def _loop():
    last=None
    while not STOP.wait(1):
        try:
            if not enabled():
                with LOCK:
                    STATE["state"]="paused"
                continue
            now=_now()
            slot=now.replace(second=0,microsecond=0)
            # The cadence is intentionally a real prospective slot, not a
            # catch-up replay. A missed slot is never reconstructed.
            if slot==last or now.second<5:
                continue
            last=slot
            if bank.enabled() and _regular(now) and now.second<=15:
                cutoff=_now()
                count=_record(cutoff)
                state="recording" if count else "waiting_for_eligible_slot"
            else:
                state="waiting_for_constituent_capture_or_session"
            _resolve(_now())
            with LOCK:
                STATE.update(state=state,last_attempt_utc=_iso(now),last_error=None)
        except Exception as exc:
            # A research failure must not terminate or restart the quote feed.
            with LOCK:
                STATE.update(state="research_error",last_error=type(exc).__name__)


def resume():
    global WORKER
    with LOCK:
        if not enabled() or (WORKER and WORKER.is_alive()):
            return
        STOP.clear()
        WORKER=Thread(target=_loop,daemon=True,name="quantlab-prospective-research")
        WORKER.start()


def shutdown():
    STOP.set()


def status():
    with LOCK:
        return {**STATE,"enabled":enabled(),"worker_running":bool(WORKER and WORKER.is_alive()),
                "protocol":PROTOCOL,"protocol_sha256":PROTOCOL_HASH,"extra_protocol":EXTRA_PROTOCOL,
                "extra_protocol_sha256":EXTRA_PROTOCOL_HASH,"recorded_horizons":list(RECORD_HORIZONS),"storage":recorder_storage.status(STREAM),
                "orders_enabled":False,"calibrated_probability":None}


def _summary(rows):
    total=len(rows)
    eligible=[r for r in rows if r["outcome"] in ("UP","DOWN")]
    stats={}
    for name in METHODS:
        scored=[r for r in eligible if r[name] in ("UP","DOWN")]
        correct=sum(r[name]==r["outcome"] for r in scored)
        stats[name]={"calls":sum(r[name] in ("UP","DOWN") for r in rows),
                     "abstained":sum(r[name]=="ABSTAIN" for r in rows),
                     "unavailable":sum(r[name]=="UNAVAILABLE" for r in rows),
                     "scored":len(scored),"correct":correct,"accuracy":correct/len(scored) if scored else None,
                     "scored_coverage":len(scored)/len(eligible) if eligible else None,
                     "confusion":{p+"_"+a:sum(r[name]==p and r["outcome"]==a for r in scored)
                                  for p in ("UP","DOWN") for a in ("UP","DOWN")}}
    comparisons={}
    for name in METHODS[:2]:
        joint=[r for r in eligible if r[name] in ("UP","DOWN") and r["ema_rsi"] in ("UP","DOWN")]
        clusters={}
        wins=losses=0
        for r in joint:
            a=int(r[name]==r["outcome"]);b=int(r["ema_rsi"]==r["outcome"])
            wins+=a;losses+=b
            pair=clusters.setdefault(r["session_ist"],[0,0]);pair[0]+=a-b;pair[1]+=1
        interval=None
        # Session-cluster resampling is descriptive; overlapping horizons,
        # dependence across sessions and selection still preclude certification.
        if len(clusters)>=20 and len(joint)>=100:
            rng=random.Random(2718)
            units=list(clusters.values())
            sims=[]
            for _ in range(1000):
                sample=rng.choices(units,k=len(units))
                sims.append(sum(x[0] for x in sample)/sum(x[1] for x in sample))
            sims.sort()
            interval=[sims[25],sims[974]]
        comparisons[name]={"joint_scored":len(joint),"sessions":len(clusters),
                           "method_accuracy":wins/len(joint) if joint else None,
                           "ema_accuracy":losses/len(joint) if joint else None,
                           "difference":(wins-losses)/len(joint) if joint else None,
                           "session_bootstrap_95":interval}
    return {"attempts":total,"directional_outcomes":len(eligible),
            "pending":sum(r["outcome"]=="PENDING" for r in rows),
            "flat":sum(r["outcome"]=="FLAT" for r in rows),
            "unverifiable":sum(r["outcome"]=="UNVERIFIABLE" for r in rows),
            "methods":stats,"paired_vs_ema":comparisons}


def report(horizon=5,limit=12000):
    if horizon not in RECORD_HORIZONS or type(limit) is not int or not 1<=limit<=15000:
        raise ValueError("Select an approved horizon and bounded history limit")
    rows=[]
    if market_inventory._safe_file(shared_market_data.database_path()):
        with closing(_read()) as db:
            db.row_factory=sqlite3.Row
            if db.execute("SELECT 1 FROM sqlite_master WHERE name=? AND type='table'",(TABLE,)).fetchone():
                rows=[dict(r) for r in db.execute("""SELECT slot_utc,session_ist,cutoff_utc,decided_utc,target_utc,
                     horizon_minutes,reference_price,pressure,volume_pressure,ema_rsi,outcome,observed_price,
                     observed_exchange_utc,observed_received_utc,reference_sha256,observed_sha256
                     FROM banknifty_paired_signals WHERE protocol_hash=? AND horizon_minutes=?
                     ORDER BY slot_utc DESC LIMIT ?""",(protocol_for(horizon),horizon,limit+1))]
    truncated=len(rows)>limit
    rows=rows[:limit]
    groups={}
    for r in rows:
        groups.setdefault(r["session_ist"],[]).append(r)
    daily=[{"session_ist":day,**_summary(group)} for day,group in sorted(groups.items())]
    return {"horizon_minutes":horizon,"protocol_sha256":protocol_for(horizon),"summary":_summary(rows),
            "days":daily,"latest":rows[:100],"truncated":truncated,
            "note":"Prospective local rule scoreboard, not calibrated probabilities, executable option P&L or verified alpha. Paired accuracy uses identical non-flat observed targets where both methods called. Coverage, missing outcomes and abstentions are reported separately. No retrospective backfill."}
