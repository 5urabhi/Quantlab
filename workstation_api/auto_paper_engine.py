"""Automatic local paper research, with immutable decisions and no broker orders.

The two lanes are independent virtual experiments, not simultaneous allocations
of the user's real capital. A conditional marketable basket is not an observed
fill. Missing exits are censored and halt that lane for the rest of the session.
"""
from contextlib import closing, contextmanager
from datetime import timedelta, datetime, time
from pathlib import Path
from threading import Event, Lock, Thread
import fcntl
import json
import os
import sqlite3
from time import monotonic

from . import auto_paper_selection as select, depth_replay as replay
from . import paper_execution as paper, service, dynamic_exit_policy as policy, market_observations

DEFAULTS={"enabled":False,"capital":17000.,"max_loss":4250.,"target_net":100.,
          "max_lots":3,"hold_seconds":900,"broker_profile":"zerodha",**policy.DEFAULTS}
LANES=("directional","spread")
PENDING=("awaiting_entry","paper_open","awaiting_exit")
BLOCKED=("entry_censored","exit_censored")
TICK_SECONDS=policy.POLL_SECONDS
LOCK=Lock()
STOP=Event()
WORKER=None
HEALTH={"state":"idle","last_cycle_utc":None,"last_error":None}
WARNING=("Paper research only. Each lane has a separate hypothetical budget. Scenario scores "
    "are not forecasts, and original quote-depth replay is not an actual execution. "
    "The modeled session loss allowance is reduced by scored losses and not replenished by wins. Entries are sampled from fresh observations, at most one attempt per lane per minute; monitoring is approximately every five seconds. "
    "Target/stop marks are sampled, exits can be late or unobservable, and actual loss "
    "and short-leg margin are not certified. No broker orders are enabled.")


def _path():
    root=service.DATA/"research_workspace"
    root.mkdir(parents=True,exist_ok=True)
    return root/"automatic_paper_decisions.sqlite3"


@contextmanager
def _db():
    path=_path()
    if path.is_symlink():
        raise ValueError("Unsafe automatic paper journal path")
    with closing(sqlite3.connect(path,timeout=3)) as db:
        db.execute("PRAGMA busy_timeout=3000")
        db.execute("""CREATE TABLE IF NOT EXISTS settings(
            id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS decisions(
            id INTEGER PRIMARY KEY, lane TEXT NOT NULL, minute_utc TEXT NOT NULL,
            session_ist TEXT NOT NULL, state TEXT NOT NULL, body TEXT NOT NULL,
            UNIQUE(lane,minute_utc))""")
        db.execute("CREATE INDEX IF NOT EXISTS auto_paper_session ON decisions(session_ist,lane,id)")
        yield db
        db.commit()


def _encode(value):
    return json.dumps(value,allow_nan=False,separators=(",",":"))


def _settings(db):
    row=db.execute("SELECT body FROM settings WHERE id=1").fetchone()
    if not row:
        return dict(DEFAULTS)
    saved=json.loads(row[0])
    # Existing enabled accounts do not silently switch exit policy or cost.
    if "exit_mode" not in saved:
        saved={**saved,"exit_mode":"target_stop","stop_net":saved.get("max_loss",4250.),"slippage_bps":select.SLIPPAGE}
    return {**DEFAULTS,**saved}


def validate(config):
    if type(config.get("enabled")) is not bool:
        raise ValueError("Explicit paper research enable/disable is required")
    for name,lo,hi in (("capital",1000,1e7),("max_loss",1,1e7),("target_net",1,1e6)):
        paper._check(config.get(name),lo,hi,name)
    if config["max_loss"]>config["capital"]:
        raise ValueError("Maximum modeled loss cannot exceed capital")
    if type(config.get("max_lots")) is not int or not 1<=config["max_lots"]<=10:
        raise ValueError("Choose at most ten whole lots")
    policy.validate(config)
    if config.get("broker_profile") not in replay.fees.BROKER_PROFILES:
        raise ValueError("Unknown broker fee profile")
    return {k:config[k] for k in DEFAULTS}


def configure(config):
    cfg=validate(config)
    with _db() as db:
        db.execute("INSERT OR REPLACE INTO settings VALUES(1,?)",(_encode(cfg),))
    market_observations.publish()
    return status()


def pause():
    with _db() as db:
        db.execute("BEGIN IMMEDIATE")
        cfg=_settings(db);cfg["enabled"]=False
        db.execute("INSERT OR REPLACE INTO settings VALUES(1,?)",(_encode(cfg),))
    return status()


def _records(db,sql,args=()):
    return [{**json.loads(body),"id":i,"lane":lane,"minute_utc":minute,
             "session_ist":day,"state":state}
            for i,lane,minute,day,state,body in db.execute(sql,args).fetchall()]


FIELDS="id,lane,minute_utc,session_ist,state,body"


def _update(row,state,**changes):
    updated={**row,**changes}
    body={k:v for k,v in updated.items() if k not in ("id","lane","minute_utc","session_ist","state")}
    with _db() as db:
        # Never overwrite a different transition committed by another worker.
        db.execute("UPDATE decisions SET state=?,body=? WHERE id=? AND state=?",
            (state,_encode(body),row["id"],row["state"]))


def _same_terms(books, candidate):
    return len(books)==len(candidate["legs"]) and all(
        (book["identity"],book["strike"],book["expiry"],book["option_type"],book["lot_size"])==
        (leg["identity"],leg["strike"],leg["expiry"],leg["side"],candidate["lot_size"])
        for book,leg in zip(books,candidate["legs"]))


def _entry(row,now,*,update=None,first_book=None):
    update=update or _update
    first_book=first_book or replay._first
    candidate=row["selected"];cfg=row["config"];decision=replay.ao.timestamp(row["decision_utc"])
    end=decision+timedelta(milliseconds=select.LATENCY_MS,seconds=select.WINDOW_SECONDS)
    if now<end:
        return
    # Model only the first receipt per exact leg after the declared delay.
    # Freeze the entry evidence; do not search for a better later price.
    ready=decision+timedelta(milliseconds=select.LATENCY_MS)
    books=[];missing=[]
    for identity in candidate["identities"]:
        book,reason=first_book(identity,ready,end,end)
        if reason:
            missing.append({"identity":identity,"reason":reason})
        else:
            books.append(book)
    if missing:
        update(row,"entry_censored" if books else "entry_rejected",entry_reason="missing_entry_books",missing=missing,finished_utc=paper._iso(now))
        return
    if not _same_terms(books,candidate):
        update(row,"entry_rejected",entry_reason="contract_terms_changed",finished_utc=paper._iso(now))
        return
    stamps=[b["stamp"] for b in books]
    if (max(stamps)-min(stamps)).total_seconds()>select.MAX_SKEW:
        update(row,"entry_censored",entry_reason="entry_leg_skew_exceeded",finished_utc=paper._iso(now))
        return
    entries=select.executions(books,candidate["strategy"],candidate["lots"],cfg["broker_profile"],slippage_bps=cfg.get("slippage_bps",select.SLIPPAGE))
    closes=select.executions(books,candidate["strategy"],candidate["lots"],cfg["broker_profile"],reverse=True,slippage_bps=cfg.get("slippage_bps",select.SLIPPAGE))
    if entries is None or closes is None:
        # No actual fills are assumed when the all-leg conditional entry
        # cannot be modeled. A possible partial basket is not scored as zero.
        update(row,"entry_censored",entry_reason="insufficient_displayed_roundtrip_depth",finished_utc=paper._iso(now))
        return
    cash,loss,risk=replay._entry_risk(candidate["strategy"],books,select.actions(candidate["strategy"]),entries,candidate["units"])
    risk=replay.fees._money(max(risk,loss+sum(e["fees"] for e in closes)))
    if risk>row["risk_budget_inr"] or (candidate["strategy"].endswith("debit") and cash>=0) or (candidate["strategy"].endswith("credit") and cash<=0):
        update(row,"entry_rejected",entry_reason="entry_risk_or_cashflow_changed",observed_entry_risk_inr=risk,finished_utc=paper._iso(now))
        return
    entry_time=max(stamps)
    update(row,"paper_open",entry_received_utc=paper._iso(entry_time),
        entries=entries,entry_cashflow_inr=cash,observed_entry_risk_inr=risk,
        hold_deadline_utc=paper._iso(min(entry_time+timedelta(seconds=cfg["hold_seconds"]),
            min(paper._close(entry_time,leg["expiry"]) for leg in candidate["legs"])-timedelta(seconds=15))),
        peak_net_inr=None,trail_armed=False,liquidity_bad_since_utc=None,
        entry_reason="conditional_original_depth_entry")


def _mark(row,now,*,book_lookup=None):
    candidate=row["selected"];cfg=row["config"]
    if not paper._regular(now):
        return None
    try:
        if book_lookup:
            books=[book_lookup(identity,now) for identity in candidate["identities"]]
        else:
            with closing(replay.ao._read_database()) as db:
                books=[select.latest_book(db,identity,now) for identity in candidate["identities"]]
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc) or "unable to open database file" in str(exc):
            return None
        raise
    if any(b is None for b in books) or not _same_terms(books,candidate):
        return None
    stamps=[b["stamp"] for b in books]
    if min(stamps)<replay.ao.timestamp(row["entry_received_utc"]) or (max(stamps)-min(stamps)).total_seconds()>select.MAX_SKEW:
        return None
    exits=select.executions(books,candidate["strategy"],candidate["lots"],cfg["broker_profile"],reverse=True,slippage_bps=cfg.get("slippage_bps",select.SLIPPAGE))
    if exits is None:
        return None
    return {"mark_net_inr":replay.fees._money(row["entry_cashflow_inr"]+sum(e["cashflow"] for e in exits)),
            "mark_observed_utc":paper._iso(now),"mark_book_utc":paper._iso(max(stamps)),
            "liquidity_bad":any(b["spread_bps"]>250 for b in books)}


def _monitor(row,now,*,update=None,mark_lookup=None,signal_lookup=None,actual_clock=False):
    update=update or _update
    cfg=row["config"]
    entry=replay.ao.timestamp(row["entry_received_utc"])
    close=min(paper._close(entry,leg["expiry"]) for leg in row["selected"]["legs"])
    if now>=close:
        update(row,"exit_censored",exit_reason="monitoring_missed_session_close",finished_utc=paper._iso(now))
        return
    deadline=replay.ao.timestamp(row["hold_deadline_utc"])
    mark=(mark_lookup or _mark)(row,now) if now<deadline else None
    signal=None
    if cfg.get("exit_mode") in ("signal_reversal","adaptive") and now<replay.ao.timestamp(row["hold_deadline_utc"]):
        if signal_lookup:
            signal=signal_lookup(now)
        else:
            try:
                with closing(replay.ao._read_database()) as db:
                    signal=policy.signal_from_db(db,now)
            except sqlite3.OperationalError as exc:
                if "no such table" not in str(exc) and "unable to open database file" not in str(exc):
                    raise
    reason,changes=policy.evaluate(row,now,mark,signal)
    if reason:
        # Use the actual observation/processing time, never an invented
        # earlier exit after a restart or delayed monitoring cycle.
        decision=paper._now() if actual_clock else now
        if decision>=close:
            update(row,"exit_censored",exit_reason="monitoring_missed_session_close",finished_utc=paper._iso(decision))
            return
        update(row,"awaiting_exit",**changes,exit_decision_utc=paper._iso(decision),exit_trigger=reason,
               trigger_processed_utc=paper._iso(decision))
    elif changes:
        update(row,"paper_open",**changes)


def _exit(row,now,*,update=None,first_book=None):
    update=update or _update
    first_book=first_book or replay._first
    candidate=row["selected"];cfg=row["config"];decision=replay.ao.timestamp(row["exit_decision_utc"])
    ready=decision+timedelta(milliseconds=select.LATENCY_MS)
    close=min(paper._close(decision,leg["expiry"]) for leg in candidate["legs"])
    end=min(ready+timedelta(seconds=select.WINDOW_SECONDS),close-timedelta(microseconds=1))
    if now<end:
        return
    books=[];missing=[]
    if end<ready:
        missing=[{"reason":"exit_window_unavailable_before_close"}]
    else:
        for identity in candidate["identities"]:
            book,reason=first_book(identity,ready,end,now)
            if reason:
                missing.append({"identity":identity,"reason":reason})
            else:
                books.append(book)
    if missing or not _same_terms(books,candidate):
        update(row,"exit_censored",exit_reason="missing_or_changed_exit_books",missing=missing,
                finished_utc=paper._iso(now))
        return
    stamps=[b["stamp"] for b in books]
    if (max(stamps)-min(stamps)).total_seconds()>select.MAX_SKEW:
        update(row,"exit_censored",exit_reason="exit_leg_skew_exceeded",finished_utc=paper._iso(now))
        return
    exits=select.executions(books,candidate["strategy"],candidate["lots"],cfg["broker_profile"],reverse=True,slippage_bps=cfg.get("slippage_bps",select.SLIPPAGE))
    if exits is None:
        update(row,"exit_censored",exit_reason="insufficient_displayed_exit_depth",finished_utc=paper._iso(now))
        return
    pnl=replay.fees._money(row["entry_cashflow_inr"]+sum(e["cashflow"] for e in exits))
    update(row,"complete",exits=exits,exit_received_utc=paper._iso(max(stamps)),
        net_pnl_inr=pnl,fees_inr=replay.fees._money(sum(e["fees"] for e in row["entries"]+exits)),
        target_hit=pnl>=cfg["target_net"],loss_limit_exceeded=pnl<-row["risk_budget_inr"],
        finished_utc=paper._iso(now),exit_reason="conditional_original_depth_exit",
        hold_realized_seconds=(max(stamps)-replay.ao.timestamp(row["entry_received_utc"])).total_seconds())


def _advance(now,*,actual_clock=False):
    with _db() as db:
        pending=_records(db,"SELECT "+FIELDS+" FROM decisions WHERE state IN (?,?,?) ORDER BY id",PENDING)
    for row in pending:
        stamp=paper._now() if actual_clock else now
        if row["state"]=="awaiting_entry":
            _entry(row,stamp)
        elif row["state"]=="paper_open":
            _monitor(row,stamp,actual_clock=actual_clock)
        elif row["state"]=="awaiting_exit":
            _exit(row,stamp)


def _available_lanes(db,now):
    day=now.astimezone(paper.IST).date().isoformat()
    minute=paper._iso(now.replace(second=0,microsecond=0))
    blocked={row[0] for row in db.execute("""SELECT DISTINCT lane FROM decisions
        WHERE state IN (?,?,?) OR (session_ist=? AND state IN (?,?))
        OR (minute_utc>=? AND minute_utc<? AND state!=\'no_trade\')""",(*PENDING,day,*BLOCKED,minute,paper._iso(now.replace(second=0,microsecond=0)+timedelta(minutes=1))))}
    return [lane for lane in LANES if lane not in blocked]


def _remaining_budget(db,now,cfg,lane):
    day=now.astimezone(paper.IST).date().isoformat()
    rows=_records(db,"SELECT "+FIELDS+" FROM decisions WHERE session_ist=? AND lane=? AND state='complete'",(day,lane))
    # Do not compound wins or let them replenish the session loss allowance.
    gross_losses=sum(max(0.,-r["net_pnl_inr"]) for r in rows)
    return replay.fees._money(max(0.,min(cfg["capital"],cfg["max_loss"])-gross_losses))


def cycle(now=None,*,allow_entries=True):
    # now override is for deterministic offline tests only. Production
    # records a decision timestamp AFTER source acquisition and computation.
    fixed=now is not None
    now=now or paper._now()
    if not LOCK.acquire(blocking=False):
        return
    try:
        _advance(now,actual_clock=not fixed)
        if not allow_entries:
            return
        if not fixed:
            now=paper._now()
        with _db() as db:
            cfg=_settings(db)
            lanes=_available_lanes(db,now) if cfg["enabled"] else []
            budgets={lane:_remaining_budget(db,now,cfg,lane) for lane in lanes}
        if not lanes or not paper._regular(now):
            return
        # The existing signal baseline needs a completed bar observed within
        # 30 seconds of close. Try only the first half of each minute.
        if now.second>29:
            return
        close=datetime.combine(now.astimezone(paper.IST).date(),time(15,30),paper.IST)
        if now+timedelta(seconds=30)>=close:
            return
        # Selection stress horizon is capped at five minutes; the exit cap
        # is not a forecast horizon. Reconsider failed gates on fresh ticks.
        report,decisions=select.select(now,{**cfg,"hold_seconds":300},lane_caps=budgets)
        decision=now if fixed else paper._now()
        day=decision.astimezone(paper.IST).date().isoformat()
        minute=paper._iso(decision.replace(second=0,microsecond=0))
        if not paper._regular(decision) or decision+timedelta(seconds=30)>=close:
            return
        with _db() as db:
            db.execute("BEGIN IMMEDIATE")
            # A pause or configuration change during analysis takes effect
            # before recording any new paper entry.
            if _settings(db)!=cfg:
                return
            lanes=[lane for lane in lanes if lane in _available_lanes(db,decision)]
            for lane in lanes:
                pick=dict(decisions[lane])
                selected=pick.get("selected")
                if selected and ((decision-replay.ao.timestamp(selected["oldest_book_utc"])).total_seconds()>select.MAX_BOOK_AGE
                    or (decision-now).total_seconds()>5
                    or (decision-replay.ao.timestamp(report["chain_utc"])).total_seconds()>select.MAX_CHAIN_AGE
                    or (decision-replay.ao.timestamp(report["bar_utc"])).total_seconds()>90):
                    pick.update(action="NO_TRADE",reason="source_aged_during_selection")
                    pick.pop("selected",None)
                state="awaiting_entry" if pick.get("action")=="PAPER_ENTRY" else "no_trade"
                if state=="no_trade":
                    # Keep a compact no-trade journal, but do not block an
                    # eligible entry that appears later in the same minute.
                    if db.execute("SELECT 1 FROM decisions WHERE lane=? AND minute_utc>=? AND minute_utc<? AND state=\'no_trade\'",(lane,minute,paper._iso(decision.replace(second=0,microsecond=0)+timedelta(minutes=1)))).fetchone():
                        continue
                slot=paper._iso(decision)  # legacy column; now stores exact decision clock
                if state=="awaiting_entry" and db.execute("SELECT 1 FROM decisions WHERE lane=? AND minute_utc=?",(lane,slot)).fetchone():
                    slot=paper._iso(decision+timedelta(microseconds=1))
                body={**pick,"source":report,"config":cfg,"decision_utc":paper._iso(decision),
                      "policy_version":select.VERSION+"+"+policy.VERSION,"risk_budget_inr":budgets[lane],"broker_orders_enabled":False}
                db.execute("""INSERT OR IGNORE INTO decisions(lane,minute_utc,session_ist,state,body)
                    VALUES(?,?,?,?,?)""",(lane,slot,day,state,_encode(body)))
    finally:
        LOCK.release()


def status(now=None):
    now=now or paper._now()
    day=now.astimezone(paper.IST).date().isoformat()
    with _db() as db:
        cfg=_settings(db)
        recent=_records(db,"SELECT "+FIELDS+" FROM decisions ORDER BY id DESC LIMIT 40")
        today=_records(db,"SELECT "+FIELDS+" FROM decisions WHERE session_ist=? ORDER BY id DESC",(day,))
        active=_records(db,"SELECT "+FIELDS+" FROM decisions WHERE state IN (?,?,?) ORDER BY id",PENDING)
    lanes={}
    for lane in LANES:
        rows=[r for r in today if r["lane"]==lane]
        scored=[r for r in rows if r["state"]=="complete"]
        pnl=[r["net_pnl_inr"] for r in scored]
        blocked=any(r["state"] in BLOCKED for r in rows)
        lanes[lane]={"decisions":len(rows),"no_trade":sum(r["state"]=="no_trade" for r in rows),
            "entries":sum(r["state"]!="no_trade" for r in rows),"scored":len(scored),
            "profitable":sum(v>0 for v in pnl),"losing":sum(v<0 for v in pnl),
            "target_hits":sum(r.get("target_hit",False) for r in scored),
            "censored":sum(r["state"] in BLOCKED for r in rows),
            "entry_rejected":sum(r["state"]=="entry_rejected" for r in rows),
            "conditional_net_inr":replay.fees._money(sum(pnl)) if pnl else None,
            "halted":blocked,"remaining_session_risk_inr":replay.fees._money(max(0.,min(cfg["capital"],cfg["max_loss"])-sum(max(0.,-v) for v in pnl))),"latest":rows[0] if rows else None,
            "active":next((r for r in active if r["lane"]==lane),None)}
    return {"config":cfg,"session_ist":day,"lanes":lanes,"recent":recent,"health":dict(HEALTH),
            "regular_session":paper._regular(now),"policy_version":select.VERSION+"+"+policy.VERSION,
            "broker_orders_enabled":False,"warning":WARNING}


def _worker():
    # Single recorder-independent coordinator, even if a second local API
    # process starts. No provider requests or shared market writes.
    lock_path=Path(str(_path())+".lock")
    fd=os.open(lock_path,os.O_CREAT|os.O_RDWR,0o600)
    try:
        try:
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            HEALTH.update(state="other_local_worker")
            return
        seen=-1
        last_scan=0.
        while not STOP.is_set():
            try:
                generation=market_observations.generation()
                fresh=generation!=seen or monotonic()-last_scan>=15
                if fresh:
                    seen=generation
                    last_scan=monotonic()
                # Coalesce receipt events into bounded five-second checks;
                # periodically inspect external-process writes too. Always
                # advance open positions even without new source events.
                cycle(allow_entries=fresh)
                HEALTH.update(state="monitoring",last_cycle_utc=paper._iso(paper._now()),last_error=None)
            except Exception as exc:
                # No provider/credential text is logged or surfaced.
                HEALTH.update(state="local_error",last_error=type(exc).__name__,
                              last_cycle_utc=paper._iso(paper._now()))
            STOP.wait(TICK_SECONDS)
    finally:
        os.close(fd)


def start():
    global WORKER
    if WORKER and WORKER.is_alive():
        return
    STOP.clear()
    WORKER=Thread(target=_worker,name="quantlab-automatic-paper",daemon=True)
    WORKER.start()


def stop():
    STOP.set()
    if WORKER and WORKER.is_alive():
        WORKER.join(timeout=3)
