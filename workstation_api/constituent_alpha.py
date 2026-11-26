"""Research on the frozen prospective constituent ledger; never places orders.

The first 60 completed *recorded* sessions are locked by the existing
protocol, not replaced by better-covered days. This is an assessment of
a previously recorded feature ledger, not an externally preregistered
live model or a substitute for historical OHLC acquisition.
"""
from collections import Counter
from contextlib import closing
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import csv
import json
import math
import os
import re
import uuid

import numpy as np

from . import constituent_prospective as p, shared_market_data, service
from . import advanced_options as ao, replay_storage

VERSION="constituent_alpha_v1"
HORIZONS=(5,10,30,60)
TRAIN=30
CALIBRATION=10
HOLDOUT=20
REQUIRED=TRAIN+CALIBRATION+HOLDOUT
DEADBAND_BPS=5.
COST_BPS=5.
CALL_PROB=.60
CLASSES=(-1,0,1)
INDEX_FEATURES=("index_5m_bps","index_15m_bps","index_30m_bps","index_rv_1m_bps","ema_gap_bps","rsi14","minute_of_session")
BANK_FEATURES=("weighted_return_bps","breadth_pct","weighted_dispersion_bps",
               "signed_rvol","rvol_missing","weighted_atp_deviation_bps","atp_missing",
               "weighted_displayed_imbalance","imbalance_missing")
MODELS=("index_logistic","constituent_logistic","constituent_boosting")
POLICY={"version":VERSION,"source_protocol_hash":p.PROTOCOL_HASH,"horizons":HORIZONS,
        "split_sessions":[TRAIN,CALIBRATION,HOLDOUT],"deadband_bps":DEADBAND_BPS,
        "roundtrip_index_cost_proxy_bps":COST_BPS,"call_probability":CALL_PROB,
        "index_features":INDEX_FEATURES,"bank_features":BANK_FEATURES,
        "minimum_samples":[60,20,40],"minimum_supported_sessions":[20,7,12],
        "sampling":"greedy nonoverlapping decision windows including 30s label allowance; reserve missing-label slots",
        "model_settings":"standardized L2 logistic C=1; histogram gradient boosting max_iter=100 max_leaf_nodes=7 min_samples_leaf=20 L2=1; temperature grid fixed; three quantile regressors",
        "development_walk_forward":[[20,5],[25,5]]}
POLICY_HASH=sha256(json.dumps(POLICY,sort_keys=True).encode()).hexdigest()


def _stamp(value):
    t=datetime.fromisoformat(value)
    if t.tzinfo is None:
        raise ValueError("Naive timestamp")
    return t.astimezone(timezone.utc)


def _num(value):
    if type(value) not in (float,int) or not math.isfinite(value):
        raise ValueError("Missing or invalid numeric evidence")
    return float(value)


def _hash(value):
    if not p._valid_hash(value):
        raise ValueError("Missing source digest")
    return value


def _read():
    return ao._read_database()


def _horizon(h):
    if h not in HORIZONS:
        raise ValueError("Use 5, 10, 30 or 60 minutes recorded by the existing protocol")


def _days(db,horizon,today):
    if not replay_storage.fetchone(db,"SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(p.TABLE,)):
        return []
    return [r[0] for r in replay_storage.fetchall(db,"""SELECT DISTINCT session_ist FROM banknifty_paired_signals
        WHERE protocol_hash=? AND horizon_minutes=? AND session_ist<? ORDER BY session_ist LIMIT ?""",
        (p.PROTOCOL_HASH,horizon,today,REQUIRED))]


def readiness(horizon=30,*,now=None):
    _horizon(horizon)
    now=now or p._now()
    today=p._session(now).date().isoformat()
    days=[]
    if shared_market_data.database_path().is_file():
        with closing(_read()) as db:
            days=_days(db,horizon,today)
    return {"version":VERSION,"policy_sha256":POLICY_HASH,"source_protocol_sha256":p.PROTOCOL_HASH,
            "horizon_minutes":horizon,"supported_horizons":list(HORIZONS),
            "required_sessions":REQUIRED,"recorded_sessions":len(days),"training_dates":days[:TRAIN],
            "calibration_dates":days[TRAIN:TRAIN+CALIBRATION],"holdout_dates":days[TRAIN+CALIBRATION:],
            "state":"ready_for_evidence_audit" if len(days)==REQUIRED else "awaiting_recorded_sessions",
            "prospective_enabled":p.enabled(),"constituent_capture_enabled":p.bank.enabled(),
            "note":"Counts are completed recorded sessions, not proof of usable data. The first 60 are retained even if coverage is poor. The existing ledger has 5/10/30/60 minute labels, not 15 minutes. No fabricated historical weights or signals."}


def _reference(row,e):
    cutoff,decided,target=(_stamp(row[k]) for k in ("cutoff_utc","decided_utc","target_utc"))
    if not 0<=(decided-cutoff).total_seconds()<=5 or target!=decided+timedelta(minutes=row["horizon_minutes"]):
        raise ValueError("Decision clock mismatch")
    if p._session(cutoff).date().isoformat()!=row["session_ist"]:
        raise ValueError("Session mismatch")
    ref=e["reference"]
    price=_num(row["reference_price"])
    received,event=_stamp(ref["received_utc"]),_stamp(ref["exchange_utc"])
    if price<=0 or price!=_num(ref["price"]) or _hash(ref["sha256"])!=_hash(row["reference_sha256"]):
        raise ValueError("Reference price mismatch")
    if not cutoff-timedelta(seconds=15)<=event<=cutoff or not cutoff-timedelta(seconds=15)<=received<=cutoff or not -2<=(received-event).total_seconds()<=15:
        raise ValueError("Reference unavailable at cutoff")
    return cutoff,decided,target,price


def _bank_features(e,cutoff):
    members=e["expected_members"]
    rows=e["constituent_receipts"]
    membership=_hash(e["membership_sha256"])
    _hash(e["weights_sha256"])
    if _stamp(e["weights_recorded_utc"])>cutoff or not 1<=members<=50 or e["members"]!=members or len(rows)!=members:
        raise ValueError("Incomplete dated constituent evidence")
    if abs(_num(e["observed_weight_pct"])-100)>.10001:
        raise ValueError("Incomplete weighted coverage")
    items=[]; symbols=set()
    for r in rows:
        symbol=r["symbol"]
        if symbol in symbols:
            raise ValueError("Duplicate constituent")
        symbols.add(symbol)
        w=_num(r["weight_pct"])
        if not 0<w<=100:
            raise ValueError("Invalid weight")
        c,a=r["current"],r["anchor"]
        if c["identity"]!=a["identity"]:
            raise ValueError("Identity mismatch")
        for quote,limit in ((c,cutoff),(a,cutoff-timedelta(minutes=5))):
            _hash(quote["packet_sha256"])
            if quote["membership_sha256"]!=membership:
                raise ValueError("Membership receipt mismatch")
            receipt,trade=_stamp(quote["received_utc"]),_stamp(quote["exchange_trade_utc"])
            if not limit-timedelta(seconds=30)<=receipt<=limit or not limit-timedelta(seconds=30)<=trade<=limit:
                raise ValueError("Quote unavailable at cutoff")
        cp,ap=_num(c["price"]),_num(a["price"])
        if min(cp,ap)<=0:
            raise ValueError("Nonpositive constituent price")
        ret=10000*(cp/ap-1)
        rvol=r.get("relative_volume")
        rv=(math.copysign(min(float(rvol),3),ret) if ret else 0.) if type(rvol) in (int,float) and math.isfinite(rvol) and rvol>=0 and r.get("baseline_sessions",0)>=5 else None
        atp=c.get("atp")
        atp_dev=10000*(cp/atp-1) if type(atp) in (int,float) and math.isfinite(atp) and atp>0 else None
        buy,sell=c.get("buy_quantity"),c.get("sell_quantity")
        imb=(buy-sell)/(buy+sell) if all(type(x) in (int,float) and math.isfinite(x) and x>=0 for x in (buy,sell)) and buy+sell>0 else None
        items.append((w,ret,rv,atp_dev,imb))
    total=sum(x[0] for x in items)
    if abs(total-100)>.10001:
        raise ValueError("Weight sum mismatch")
    avg=sum(w*r for w,r,*_ in items)/total
    breadth=sum(w*(1 if r>0 else -1 if r<0 else 0) for w,r,*_ in items)
    dispersion=math.sqrt(sum(w*(r-avg)**2 for w,r,*_ in items)/total)
    def optional(index):
        covered=sum(x[0] for x in items if x[index] is not None)
        if covered<.8*total:
            # Numeric placeholder is paired with an explicit missingness
            # flag, not an imputed market move or zero-filled constituent.
            return 0.,1.
        return sum(x[0]*x[index] for x in items if x[index] is not None)/covered,0.
    return [avg,breadth,dispersion,*optional(2),*optional(3),*optional(4)]


def _label(row,price,target):
    try:
        observed=_num(row["observed_price"])
        exchange,receipt=_stamp(row["observed_exchange_utc"]),_stamp(row["observed_received_utc"])
        _hash(row["observed_sha256"])
        if observed<=0 or not target<=exchange<=target+timedelta(seconds=30) or not target<=receipt<=target+timedelta(seconds=30) or not -2<=(receipt-exchange).total_seconds()<=15:
            return None
        outcome="UP" if observed>price else "DOWN" if observed<price else "FLAT"
        if row["outcome"]!=outcome:
            return None
        return 10000*(observed/price-1)
    except (KeyError,TypeError,ValueError,OverflowError):
        return None


def sample_day(rows):
    """One horizon, one session, chronological frozen observations.

    Features never inspect the target/outcome. Reserve a nonoverlapping
    window on feature eligibility *before* attempting to score its label.
    """
    refs={}
    samples=[]
    counts=Counter()
    next_eligible=None
    for row in rows:
        counts["ledger_rows"]+=1
        try:
            e=json.loads(row["evidence_json"])
            cutoff,decided,target,price=_reference(row,e)
            slot=_stamp(row["slot_utc"])
            if slot!=cutoff.replace(second=0,microsecond=0):
                raise ValueError("Slot mismatch")
            refs[slot]=price
        except (ValueError,TypeError,KeyError,OverflowError):
            counts["invalid_reference"]+=1
            continue
        try:
            past=[refs[slot-timedelta(minutes=m)] for m in (5,15,30)]
            one_minute=[]
            for m in range(30):
                a,b=slot-timedelta(minutes=m+1),slot-timedelta(minutes=m)
                if a in refs and b in refs:
                    one_minute.append(10000*(refs[b]/refs[a]-1))
            if len(one_minute)<20:
                raise ValueError("Insufficient one-minute returns")
            ema=e["ema"]
            if ema["quote_mode"]!="RECENT_LOCAL_CANDLE_NOT_VERIFIED_LIVE" or ema["contiguous_session_bars"]<30:
                raise ValueError("Missing completed EMA")
            if not 60<=(cutoff-_stamp(ema["last_observed_utc"])).total_seconds()<=90:
                raise ValueError("Stale EMA")
            fast,slow,rsi=(_num(ema[k]) for k in ("ema9","ema21","rsi14"))
            if slow<=0 or not 0<=rsi<=100:
                raise ValueError("Invalid EMA/RSI")
            r5,r15,r30=(10000*(price/x-1) for x in past)
            rv=float(np.std(one_minute,ddof=1))
            local=p._session(cutoff)
            index=[r5,r15,r30,rv,10000*(fast/slow-1),rsi,float(local.hour*60+local.minute-555)]
        except (ValueError,TypeError,KeyError,OverflowError):
            counts["missing_index_features"]+=1
            continue
        try:
            bank=_bank_features(e,cutoff)
            if row["pressure"] not in ("UP","DOWN","ABSTAIN"):
                raise ValueError("Unavailable weighted rule evidence")
            if not all(math.isfinite(v) for v in index+bank):
                raise ValueError("Nonfinite feature")
        except (ValueError,TypeError,KeyError,OverflowError):
            counts["missing_constituent_features"]+=1
            continue
        counts["matched_features"]+=1
        if next_eligible is not None and decided<=next_eligible:
            counts["overlap_skipped"]+=1
            continue
        next_eligible=target+timedelta(seconds=30)
        counts["reserved_nonoverlap"]+=1
        label=_label(row,price,target)
        if label is None:
            counts["missing_label"]+=1
            continue
        counts["scored"]+=1
        scale=max(1.,rv*math.sqrt(30))
        regime="trend_up" if r30>=scale else "trend_down" if r30<=-scale else "compression" if rv<=3. else "range"
        samples.append({"session":row["session_ist"],"decision_utc":row["decided_utc"],"target_utc":row["target_utc"],
            "reference_price":price,"return_bps":label,"class":1 if label>DEADBAND_BPS else -1 if label<-DEADBAND_BPS else 0,
            "index":index,"full":index+bank,"regime":regime,
            "ema_rsi":row["ema_rsi"],"pressure":row["pressure"],"volume_pressure":row["volume_pressure"]})
    return samples,dict(counts)


def _rows(db,day,horizon):
    # The existing primary protocol has at most 375 minute slots per session.
    # Cap reads, refuse a corrupt/duplicated ledger rather than truncating.
    db.row_factory=None
    start=day+"T03:45:00"
    stop=day+"T10:01:00"
    columns=("slot_utc","session_ist","cutoff_utc","decided_utc","target_utc","horizon_minutes",
             "reference_price","reference_sha256","pressure","volume_pressure","ema_rsi","evidence_json",
             "outcome","observed_price","observed_exchange_utc","observed_received_utc","observed_sha256")
    data=replay_storage.fetchall(db,"SELECT "+",".join(columns)+""" FROM banknifty_paired_signals
        WHERE protocol_hash=? AND horizon_minutes=? AND slot_utc>=? AND slot_utc<? AND session_ist=?
        ORDER BY slot_utc LIMIT 401""",(p.PROTOCOL_HASH,horizon,start,stop,day))
    if len(data)>400:
        raise ValueError("Recorded session exceeds bounded minute ledger")
    return [dict(zip(columns,row)) for row in data]


def _root():
    path=service.DATA/"research_workspace"/"constituent_alpha"
    path.mkdir(parents=True,exist_ok=True)
    return path


def result_path(run_id):
    if not re.fullmatch(r"[a-f0-9]{32}",run_id):
        raise ValueError("Invalid alpha result identifier")
    path=_root()/("run-"+run_id+".csv")
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError("Alpha result unavailable")
    return path


def support(samples):
    classes=Counter(x["class"] for x in samples)
    return {"samples":len(samples),"sessions":len({x["session"] for x in samples}),
            "classes":{str(c):classes[c] for c in CLASSES}}


def _supported(samples,n,days,*,train=False):
    s=support(samples)
    return s["samples"]>=n and s["sessions"]>=days and (not train or min(s["classes"].values())>=10)
