"""Persistent, causal long-option paper orders on saved original Dhan depth.

No broker connection, no actual fills, no inference of passive queue priority.
A protected market order is an IOC-style attempt on the first subsequent valid
book; a resting limit fills only against displayed contra-side prices that
satisfy the limit. Recorded local receipt times, not exchange order times.
"""
from __future__ import annotations
from contextlib import closing, contextmanager
from datetime import date, datetime, time, timedelta, timezone
from math import floor
from threading import Event, Lock, Thread
from zoneinfo import ZoneInfo
import sqlite3
import uuid
from . import advanced_options as ao, liquidity_spreads as fees
from . import option_chain_live, service, spread_scanner

IST = ZoneInfo("Asia/Kolkata")
WORKER = None
STOP = Event()
LOCK = Lock()
HEALTH = {"state":"idle","last_cycle_utc":None,"last_error":None}
WORKING = ("working","partially_filled")
MAX_ORDERS = 50
MAX_ACCOUNTS = 10
MAX_BOOKS_PER_CYCLE = 100


def _now():
    return datetime.now(timezone.utc)


def _iso(t):
    return t.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _regular(t):
    t=t.astimezone(IST)
    return t.weekday()<5 and time(9,15)<=t.time()<time(15,30)


def _close(t,expiry):
    return min(datetime.combine(t.astimezone(IST).date(),time(15,30),IST),
               datetime.combine(date.fromisoformat(expiry),time(15,30),IST)).astimezone(timezone.utc)


def _db_path():
    return service.DATA/"trading_cockpit"/"paper_execution.sqlite3"


@contextmanager
def _db(*,write=False):
    path=_db_path()
    path.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(path,timeout=5)) as db:
        db.row_factory=sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=5000")
        db.executescript("""
        CREATE TABLE IF NOT EXISTS paper_accounts(
          id TEXT PRIMARY KEY, label TEXT NOT NULL, created_utc TEXT NOT NULL,
          initial_cash REAL NOT NULL,cash REAL NOT NULL, realized REAL NOT NULL DEFAULT 0,
          fees_paid REAL NOT NULL DEFAULT 0, risk_pct REAL NOT NULL,
          loss_limit_pct REAL NOT NULL,max_positions INTEGER NOT NULL,
          broker_profile TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS paper_orders(
          id TEXT PRIMARY KEY,account_id TEXT NOT NULL REFERENCES paper_accounts(id),
          identity TEXT NOT NULL,symbol TEXT NOT NULL,expiry TEXT NOT NULL,strike REAL NOT NULL,
          side TEXT NOT NULL,lot_size INTEGER NOT NULL,action TEXT NOT NULL,kind TEXT NOT NULL,
          quantity INTEGER NOT NULL,filled INTEGER NOT NULL DEFAULT 0,turnover REAL NOT NULL DEFAULT 0,
          fees REAL NOT NULL DEFAULT 0, reserved_cash REAL NOT NULL DEFAULT 0,
          protection_price REAL NOT NULL,participation REAL NOT NULL,slippage_bps REAL NOT NULL,
          created_utc TEXT NOT NULL,ready_utc TEXT NOT NULL,deadline_utc TEXT NOT NULL,
          cursor_utc TEXT,cancel_requested_utc TEXT,state TEXT NOT NULL DEFAULT 'working',
          valid_books INTEGER NOT NULL DEFAULT 0,invalid_books INTEGER NOT NULL DEFAULT 0,
          terminal_reason TEXT);
        CREATE INDEX IF NOT EXISTS paper_order_pending ON paper_orders(state,created_utc);
        CREATE TABLE IF NOT EXISTS paper_positions(
          account_id TEXT NOT NULL REFERENCES paper_accounts(id),identity TEXT NOT NULL,
          symbol TEXT NOT NULL,expiry TEXT NOT NULL,strike REAL NOT NULL,side TEXT NOT NULL,
          lot_size INTEGER NOT NULL,quantity INTEGER NOT NULL,cost_basis REAL NOT NULL,
          PRIMARY KEY(account_id,identity));
        CREATE TABLE IF NOT EXISTS paper_fills(
          id INTEGER PRIMARY KEY AUTOINCREMENT,order_id TEXT NOT NULL REFERENCES paper_orders(id),
          account_id TEXT NOT NULL,identity TEXT NOT NULL,book_received_utc TEXT NOT NULL,
          book_pair_sha256 TEXT NOT NULL,units INTEGER NOT NULL,vwap REAL NOT NULL,
          turnover REAL NOT NULL,incremental_fees REAL NOT NULL,realized_delta REAL NOT NULL,
          UNIQUE(order_id,book_received_utc));
        CREATE TABLE IF NOT EXISTS paper_depth_consumed(
          account_id TEXT NOT NULL,identity TEXT NOT NULL,book_pair_sha256 TEXT NOT NULL,
          action TEXT NOT NULL,level_index INTEGER NOT NULL,units INTEGER NOT NULL,
          PRIMARY KEY(account_id,identity,book_pair_sha256,action,level_index));
        CREATE TABLE IF NOT EXISTS paper_equity(
          account_id TEXT NOT NULL,minute_utc TEXT NOT NULL,cash REAL NOT NULL,
          marked_equity REAL,realized REAL NOT NULL,marked_count INTEGER NOT NULL,
          position_count INTEGER NOT NULL,PRIMARY KEY(account_id,minute_utc));
        """)
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            if write:
                db.commit()
        except BaseException:
            db.rollback()
            raise


def _check(v,lo,hi,label):
    n=ao.number(v)
    if n is None or not lo<=n<=hi:
        raise ValueError("Invalid "+label)
    return n


def _account(db,aid):
    r=db.execute("SELECT * FROM paper_accounts WHERE id=?",(aid,)).fetchone()
    if not r:
        raise ValueError("Unknown paper account")
    return r


def _order(db,oid):
    r=db.execute("SELECT * FROM paper_orders WHERE id=?",(oid,)).fetchone()
    if not r:
        raise ValueError("Unknown paper order")
    return r


def _fees(action,turnover,profile):
    if turnover==0:
        return 0.
    result=fees.fee_schedule(turnover if action=="BUY" else 0.,
                             turnover if action=="SELL" else 0.,broker_profile=profile)
    return result["buy_leg" if action=="BUY" else "sell_leg"]["fees_total"]


def create_account(label,initial_cash,*,risk_pct=25.,loss_limit_pct=10.,
                   max_positions=4,broker_profile="zerodha",now=None):
    initial_cash=fees._money(_check(initial_cash,1000,1e7,"paper starting cash"))
    risk_pct=_check(risk_pct,1,100,"premium exposure percentage")
    loss_limit_pct=_check(loss_limit_pct,1,100,"cumulative realized loss limit")
    if not isinstance(max_positions,int) or isinstance(max_positions,bool) or not 1<=max_positions<=20:
        raise ValueError("Choose 1–20 concurrent positions")
    label=label.strip()[:80]
    if not label or broker_profile not in fees.BROKER_PROFILES:
        raise ValueError("Provide an account label and supported fee profile")
    aid="paper_"+uuid.uuid4().hex[:20]
    with _db(write=True) as db:
        if db.execute("SELECT COUNT(*) FROM paper_accounts").fetchone()[0]>=MAX_ACCOUNTS:
            raise ValueError("Local account limit reached (10 preserved research accounts)")
        db.execute("""INSERT INTO paper_accounts
          (id,label,created_utc,initial_cash,cash,risk_pct,loss_limit_pct,max_positions,broker_profile)
          VALUES(?,?,?,?,?,?,?,?,?)""",(aid,label,_iso(now or _now()),initial_cash,initial_cash,
                                       risk_pct,loss_limit_pct,max_positions,broker_profile))
        return dict(_account(db,aid))


def _contract(identity):
    if not fees.ID.fullmatch(identity):
        raise ValueError("Select an exact verified NSE_FNO contract identity")
    master=option_chain_live._contracts()
    c=master.get("by_id",{}).get(identity.split(":")[1])
    if not master.get("fresh") or not c or c["identity"]!=identity:
        raise ValueError("Refresh the official Dhan BANKNIFTY instrument master")
    return c


def submit(aid,identity,action,kind,lots,protection_price,*,latency_ms=1000,
           ttl_seconds=60,participation_pct=25.,slippage_bps=5.,now=None):
    now=now or _now()
    if not _regular(now):
        raise ValueError("Submit paper orders during the usual NSE regular session")
    if action not in ("BUY","SELL") or kind not in ("PROTECTED_MARKET","LIMIT"):
        raise ValueError("Unsupported long-option paper order")
    if not isinstance(lots,int) or isinstance(lots,bool) or not 1<=lots<=50:
        raise ValueError("Select 1–50 verified lots")
    protection_price=_check(protection_price,.01,1e6,"protection premium")
    latency_ms=_check(latency_ms,0,60000,"simulated latency")
    ttl_seconds=_check(ttl_seconds,1,1800,"time in force")
    participation_pct=_check(participation_pct,1,100,"depth participation assumption")
    slippage_bps=_check(slippage_bps,0,500,"slippage")
    c=_contract(identity)
    ready=now+timedelta(milliseconds=latency_ms)
    deadline=min(now+timedelta(seconds=ttl_seconds),_close(now,c["expiry"]))
    if ready>=deadline or now>=_close(now,c["expiry"]):
        raise ValueError("Order latency exceeds remaining regular-session time or expiry")
    units=lots*c["lot_size"]
    oid="po_"+uuid.uuid4().hex[:20]
    with _db(write=True) as db:
        a=_account(db,aid)
        pending=db.execute("""SELECT * FROM paper_orders WHERE account_id=?
          AND state IN ('working','partially_filled')""",(aid,)).fetchall()
        if len(pending)>=MAX_ORDERS or any(r["identity"]==identity for r in pending):
            raise ValueError("Only one working order per contract per account; cancel remaining quantity first")
        positions=db.execute("SELECT * FROM paper_positions WHERE account_id=? AND quantity>0",(aid,)).fetchall()
        p=next((r for r in positions if r["identity"]==identity),None)
        if p and (p["expiry"],p["strike"],p["side"],p["lot_size"])!=(c["expiry"],c["strike"],c["option_type"],c["lot_size"]):
            raise ValueError("Stored exact position terms differ from current master")
        reserve=0.
        if action=="SELL":
            if not p or p["quantity"]<units:
                raise ValueError("Paper SELL closes held long units only; naked shorts and unverified margin disabled")
        else:
            if a["realized"]<=-a["initial_cash"]*a["loss_limit_pct"]/100:
                raise ValueError("Cumulative realized loss limit reached; new BUY orders blocked")
            if p and p["expiry"]<now.astimezone(IST).date().isoformat():
                raise ValueError("Expired position requires explicit settlement research")
            held={r["identity"] for r in positions}
            held.update(r["identity"] for r in pending if r["action"]=="BUY")
            held.add(identity)
            if len(held)>a["max_positions"]:
                raise ValueError("Configured concurrent position limit exceeded")
            gross=fees._money(units*protection_price)
            if gross>1e10:
                raise ValueError("Paper turnover exceeds fee-model bound")
            reserve=fees._money(gross+_fees("BUY",gross,a["broker_profile"]))
            reserved=sum(r["reserved_cash"] for r in pending)
            exposure=sum(r["cost_basis"] for r in positions)+reserved+reserve
            if reserved+reserve>a["cash"]+.00001 or exposure>a["initial_cash"]*a["risk_pct"]/100+.00001:
                raise ValueError("Insufficient unreserved paper cash or configured premium exposure budget")
        db.execute("""INSERT INTO paper_orders(id,account_id,identity,symbol,expiry,strike,side,lot_size,
             action,kind,quantity,reserved_cash,protection_price,participation,slippage_bps,
             created_utc,ready_utc,deadline_utc)
             VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (oid,aid,identity,c["symbol"],c["expiry"],c["strike"],c["option_type"],c["lot_size"],
             action,kind,units,reserve,protection_price,participation_pct/100,slippage_bps,
             _iso(now),_iso(ready),_iso(deadline)))
        return dict(_order(db,oid))


def request_cancel(oid,*,now=None):
    now=now or _now()
    with _db(write=True) as db:
        o=_order(db,oid)
        if o["state"] in WORKING and not o["cancel_requested_utc"]:
            db.execute("UPDATE paper_orders SET cancel_requested_utc=? WHERE id=?",(_iso(now),oid))
        return dict(_order(db,oid))


def marketable_walk(book,action,quantity,lot_size,protection_price,participation,slippage_bps,consumed=None):
    """Pure conservative displayed-depth walk, whole lots, no passive fills.

    Each book level is haircutted, prior simulated consumption subtracted.
    Slippage is adverse and must still satisfy the order's protection price.
    """
    consumed=consumed or {}
    levels=book["ask" if action=="BUY" else "bid"]
    allocations=[]
    total=0
    for i,level in enumerate(levels):
        price=float(level["price"])*(1+(1 if action=="BUY" else -1)*slippage_bps/10000)
        if price<=0 or (price>protection_price if action=="BUY" else price<protection_price):
            break
        capacity=max(0,floor(level["quantity"]*participation)-consumed.get(i,0))
        units=min(quantity-total,capacity)
        if units>0:
            allocations.append((i,units,price))
            total+=units
        if total>=quantity:
            break
    fill_units=(total//lot_size)*lot_size
    if fill_units==0:
        return {"units":0,"turnover":0.,"vwap":None,"allocations":[]}
    # Remove a sub-lot remainder from the least favorable tail.
    left=fill_units
    used=[]
    gross=0.
    for i,q,price in allocations:
        take=min(q,left)
        if take:
            used.append((i,take))
            gross+=take*price
            left-=take
        if left==0:
            break
    gross=fees._money(gross)
    return {"units":fill_units,"turnover":gross,"vwap":gross/fill_units,"allocations":used}


def _verified(identity,stamp,raw,digest,terms):
    result=spread_scanner._original_book(identity,stamp,raw,digest)
    if not result:
        return None
    book,stats,f=result
    if (f.get("expiry"),f.get("strike"),f.get("side"),stats["lot_size"])!=(
            terms["expiry"],terms["strike"],terms["side"],terms["lot_size"]):
        return None
    return book


def _records(o,end):
    # Strictly after submit even when latency=0. The cursor is advanced
    # only for processed receipts. No latest-book lookahead or best-price pick.
    ready=max(ao.timestamp(o["ready_utc"]),ao.timestamp(o["created_utc"])+timedelta(microseconds=1))
    cursor=o["cursor_utc"]
    start=_iso(ready)
    try:
        with closing(ao._read_database()) as source:
            return source.execute("""SELECT received_utc,book_json,packet_pair_sha256
                FROM live_depth_books WHERE identity=? AND received_utc>=?
                AND received_utc>? AND received_utc<=?
                ORDER BY received_utc LIMIT ?""",
                (o["identity"],start,cursor or "",_iso(end),MAX_BOOKS_PER_CYCLE)).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc) or "unable to open database file" in str(exc):
            return []
        raise


def _terminal(db,oid,state,reason):
    db.execute("UPDATE paper_orders SET state=?,terminal_reason=?,reserved_cash=0 WHERE id=?",
               (state,reason,oid))


def _apply_fill(db,o,stamp,digest,result):
    a=_account(db,o["account_id"])
    units=result["units"]
    turnover=result["turnover"]
    total=fees._money(o["turnover"]+turnover)
    total_fees=_fees(o["action"],total,a["broker_profile"])
    increment=fees._money(total_fees-o["fees"])
    p=db.execute("SELECT * FROM paper_positions WHERE account_id=? AND identity=?",
                 (o["account_id"],o["identity"])).fetchone()
    realized=0.
    if o["action"]=="BUY":
        debit=fees._money(turnover+increment)
        if debit>a["cash"]+.00001 or debit>o["reserved_cash"]+.00001:
            raise RuntimeError("Paper reservation invariant violated")
        cash=fees._money(a["cash"]-debit)
        basis=fees._money((p["cost_basis"] if p else 0)+debit)
        new_qty=(p["quantity"] if p else 0)+units
    else:
        if not p or p["quantity"]<units:
            raise RuntimeError("Paper inventory invariant violated")
        credit=fees._money(turnover-increment)
        cash=fees._money(a["cash"]+credit)
        released=fees._money(p["cost_basis"]*units/p["quantity"])
        realized=fees._money(credit-released)
        basis=fees._money(p["cost_basis"]-released)
        new_qty=p["quantity"]-units
    db.execute("""INSERT INTO paper_positions(account_id,identity,symbol,expiry,strike,side,lot_size,quantity,cost_basis)
        VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(account_id,identity) DO UPDATE SET
        quantity=excluded.quantity,cost_basis=excluded.cost_basis""",
        (o["account_id"],o["identity"],o["symbol"],o["expiry"],o["strike"],o["side"],o["lot_size"],new_qty,basis))
    db.execute("UPDATE paper_accounts SET cash=?,realized=?,fees_paid=? WHERE id=?",
        (cash,fees._money(a["realized"]+realized),fees._money(a["fees_paid"]+increment),a["id"]))
    filled=o["filled"]+units
    remaining=o["quantity"]-filled
    reserve=0.
    if remaining and o["action"]=="BUY":
        future_gross=fees._money(remaining*o["protection_price"])
        reserve=fees._money(future_gross+_fees("BUY",total+future_gross,a["broker_profile"])-total_fees)
    db.execute("""UPDATE paper_orders SET filled=?,turnover=?,fees=?,reserved_cash=?,state=? WHERE id=?""",
        (filled,total,total_fees,reserve,"filled" if not remaining else "partially_filled",o["id"]))
    db.execute("""INSERT INTO paper_fills(order_id,account_id,identity,book_received_utc,book_pair_sha256,
        units,vwap,turnover,incremental_fees,realized_delta) VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (o["id"],a["id"],o["identity"],stamp,digest,units,result["vwap"],turnover,increment,realized))
    for level,q in result["allocations"]:
        db.execute("""INSERT INTO paper_depth_consumed VALUES(?,?,?,?,?,?)
            ON CONFLICT(account_id,identity,book_pair_sha256,action,level_index)
            DO UPDATE SET units=units+excluded.units""",(a["id"],o["identity"],digest,o["action"],level,q))


def _advance(db,o,now):
    deadline=ao.timestamp(o["deadline_utc"])
    cancel=ao.timestamp(o["cancel_requested_utc"]) if o["cancel_requested_utc"] else None
    end=min(now,deadline,cancel or deadline)
    if end<ao.timestamp(o["ready_utc"]):
        if cancel and now>=cancel:
            _terminal(db,o["id"],"cancelled","cancelled_before_eligible_time")
        return
    rows=_records(o,end)
    for stamp,raw,digest in rows:
        o=_order(db,o["id"])
        if o["state"] not in WORKING:
            return
        t=ao.timestamp(stamp)
        db.execute("UPDATE paper_orders SET cursor_utc=? WHERE id=?",(stamp,o["id"]))
        valid=ao.timestamp(o["created_utc"])<t<=end and _regular(t) and t<_close(t,o["expiry"])
        book=_verified(o["identity"],stamp,raw,digest,o) if valid else None
        if not book:
            db.execute("UPDATE paper_orders SET invalid_books=invalid_books+1 WHERE id=?",(o["id"],))
            continue
        db.execute("UPDATE paper_orders SET valid_books=valid_books+1 WHERE id=?",(o["id"],))
        used=dict(db.execute("""SELECT level_index,units FROM paper_depth_consumed
            WHERE account_id=? AND identity=? AND book_pair_sha256=? AND action=?""",
            (o["account_id"],o["identity"],digest,o["action"])).fetchall())
        result=marketable_walk(book,o["action"],o["quantity"]-o["filled"],o["lot_size"],
             o["protection_price"],o["participation"],o["slippage_bps"],used)
        if result["units"]:
            _apply_fill(db,o,stamp,digest,result)
        current=_order(db,o["id"])
        if current["state"]=="filled":
            return
        if o["kind"]=="PROTECTED_MARKET":
            _terminal(db,o["id"],"cancelled_partial" if current["filled"] else "cancelled",
                      "first_valid_book_IOC_remainder_or_price_protection")
            return
    # Wait for bounded persistence lag; if a full batch was read, continue
    # next cycle rather than discard eligible older observations.
    if len(rows)<MAX_BOOKS_PER_CYCLE and now>=min(deadline,cancel or deadline)+timedelta(seconds=15):
        o=_order(db,o["id"])
        if o["state"] in WORKING:
            if cancel:
                _terminal(db,o["id"],"cancelled_partial" if o["filled"] else "cancelled","user_cancel_after_causal_window")
            elif not o["valid_books"]:
                _terminal(db,o["id"],"unobservable","no_valid_original_book_during_order_window")
            else:
                _terminal(db,o["id"],"expired_partial" if o["filled"] else "expired","time_in_force_or_session_close")


def _position_marks(db,aid,now):
    a=_account(db,aid)
    rows=[dict(p) for p in db.execute("SELECT * FROM paper_positions WHERE account_id=? AND quantity>0 ORDER BY identity",(aid,))]
    equity=a["cash"]
    covered=0
    for p in rows:
        p.update(mark=None,mark_utc=None,liquidation_credit=None,unrealized_net=None,state="missing_recent_full_size_bid")
        if now>=datetime.combine(date.fromisoformat(p["expiry"]),time(15,30),IST):
            p["state"]="expired_settlement_unmodeled"
            continue
        if not _regular(now):
            p["state"]="outside_regular_session"
            continue
        try:
            with closing(ao._read_database()) as source:
                records=source.execute("""SELECT received_utc,book_json,packet_pair_sha256
                  FROM live_depth_books WHERE identity=? AND received_utc>=? AND received_utc<=?
                  ORDER BY received_utc DESC LIMIT 1""",
                  (p["identity"],_iso(now-timedelta(seconds=8)),_iso(now))).fetchone()
        except sqlite3.Error:
            records=None
        if not records:
            continue
        stamp,raw,digest=records
        book=_verified(p["identity"],stamp,raw,digest,p)
        if not book:
            continue
        walk=fees._walk(book["bid"],p["quantity"])
        if not walk["fillable"]:
            continue
        credit=fees._money(walk["premium_turnover"]-_fees("SELL",walk["premium_turnover"],a["broker_profile"]))
        p.update(mark=walk["vwap"],mark_utc=stamp,liquidation_credit=credit,
                 unrealized_net=fees._money(credit-p["cost_basis"]),state="observed_bid_walk_mark")
        covered+=1
        equity+=credit
    return rows,covered,fees._money(equity) if covered==len(rows) else None


def cycle(now=None):
    now=now or _now()
    if not _db_path().is_file():
        return
    with _db(write=True) as db:
        orders=db.execute("""SELECT * FROM paper_orders WHERE state IN ('working','partially_filled')
            ORDER BY created_utc,id LIMIT 500""").fetchall()
        for o in orders:
            _advance(db,o,now)
        minute=_iso(now.replace(second=0,microsecond=0))
        for a in db.execute("SELECT * FROM paper_accounts").fetchall():
            if db.execute("SELECT 1 FROM paper_equity WHERE account_id=? AND minute_utc=?",(a["id"],minute)).fetchone():
                continue
            positions,covered,equity=_position_marks(db,a["id"],now)
            db.execute("INSERT INTO paper_equity VALUES(?,?,?,?,?,?,?)",
                (a["id"],minute,a["cash"],equity,a["realized"],covered,len(positions)))


def accounts():
    if not _db_path().is_file():
        return []
    with _db() as db:
        return [dict(r) for r in db.execute("SELECT * FROM paper_accounts ORDER BY created_utc DESC")]


def overview(aid,*,now=None):
    now=now or _now()
    with _db() as db:
        a=dict(_account(db,aid))
        orders=[dict(r) for r in db.execute("SELECT * FROM paper_orders WHERE account_id=? ORDER BY created_utc DESC LIMIT 150",(aid,))]
        fills=[dict(r) for r in db.execute("SELECT * FROM paper_fills WHERE account_id=? ORDER BY id DESC LIMIT 200",(aid,))]
        reserved=db.execute("""SELECT COALESCE(SUM(reserved_cash),0) FROM paper_orders WHERE account_id=?
            AND state IN ('working','partially_filled')""",(aid,)).fetchone()[0]
        positions,covered,equity=_position_marks(db,aid,now)
        samples=[dict(r) for r in db.execute("SELECT * FROM paper_equity WHERE account_id=? ORDER BY minute_utc DESC LIMIT 500",(aid,))]
    return {"account":a,"orders":orders,"fills":fills,"positions":positions,
        "equity":equity,"marked_count":covered,"reserved_cash":fees._money(reserved),
        "available_cash":fees._money(a["cash"]-reserved),"equity_samples":list(reversed(samples)),
        "worker":{**HEALTH,"alive":bool(WORKER and WORKER.is_alive())},"generated_utc":_iso(now),
        "broker_orders_enabled":False,"simulated":True,
        "warning":"All fills are hypothetical displayed-depth walks after the paper order time. "
            "No queue position, actual passive fill, broker margin, expiry settlement or trading profitability is verified. "
            "Limit orders execute only against subsequent contra-side prices satisfying protection. "
            "Missing marks leave equity unavailable; do not treat them as zero."}


def _worker():
    while not STOP.wait(5):
        try:
            cycle()
            HEALTH.update(state="running",last_cycle_utc=_iso(_now()),last_error=None)
        except (ValueError,TypeError,KeyError,RuntimeError,sqlite3.Error,OSError) as e:
            HEALTH.update(state="degraded",last_cycle_utc=_iso(_now()),last_error=type(e).__name__)
    HEALTH["state"]="stopped"


def start():
    global WORKER
    with LOCK:
        if WORKER and WORKER.is_alive():
            return
        STOP.clear()
        WORKER=Thread(target=_worker,daemon=True,name="quantlab-paper-execution")
        HEALTH["state"]="starting"
        WORKER.start()


def stop():
    STOP.set()
    if WORKER and WORKER.is_alive():
        WORKER.join(timeout=2)
