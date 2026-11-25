"""Manual long-options workflow: cross-expiry research, marks, alerts and audit.

Reuses the existing journal and original Dhan market library. No broker orders,
background quote subscriptions, account access or synthesized history. The
worker only reads already-saved receipts and writes a small local audit ledger.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
from threading import Event, Lock, Thread
import json
import sqlite3
import uuid

from . import advanced_options as ao, liquidity_spreads as fees
from . import manual_trade_journal as journal, option_chain_live, service
from . import spread_scanner

IST = ao.IST
CHAIN_SOURCE = "Dhan v2 read-only optionchain snapshot"
RECEIPT_AGE = 30
ENTRY_WINDOW = 60
EXIT_WINDOW = 60
MAX_EXPIRIES = 12
WORKER_INTERVAL = 10
LOCK = Lock()
WORKER = None
STOP = Event()
HEALTH = {"state":"idle","last_cycle_utc":None,"last_error":None}


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _regular(dt):
    local=dt.astimezone(IST)
    return local.weekday()<5 and time(9,15)<=local.time()<time(15,30)


def _end(dt, expiry):
    return min(datetime.combine(dt.astimezone(IST).date(),time(15,30),IST),
               datetime.combine(date.fromisoformat(expiry),time(15,30),IST)).astimezone(timezone.utc)


def _age(stamp, now, max_seconds=RECEIPT_AGE):
    try:
        age=(now-ao.timestamp(stamp)).total_seconds()
        return age, 0<=age<=max_seconds
    except (ValueError,TypeError):
        return None,False


def _valid_expiry(expiry):
    if date.fromisoformat(expiry).isoformat()!=expiry:
        raise ValueError("Use the original YYYY-MM-DD expiry")
    return expiry


def _snapshot(row):
    if row is None:
        return None
    stamp,digest,raw=row
    try:
        if sha256(raw.encode()).hexdigest()!=digest:
            return None
        v=json.loads(raw)
        if (v.get("source")!=CHAIN_SOURCE or v.get("received_utc")!=stamp or
            v.get("underlying")!="BANKNIFTY" or not v.get("read_only") or
            not isinstance(v.get("contracts"),list) or ao.positive(v.get("underlying_spot")) is None):
            return None
        ao.timestamp(stamp)
        return v
    except (ValueError,TypeError,AttributeError):
        return None


def _contract(chain, identity, expiry, strike, side, lot_size):
    if not chain or chain.get("expiry")!=expiry:
        return None
    matches=[r for r in chain["contracts"] if r.get("identity")==identity and
             r.get("contract_master_verified") and r.get("expiry")==expiry and
             r.get("strike")==strike and r.get("option_type")==side and
             r.get("lot_size")==lot_size]
    return matches[0] if len(matches)==1 else None


def _quote(row, field, units):
    """Full-size top-level quote, never a real fill."""
    if not row or not row.get("quote_valid"):
        return None
    bid,ask=ao.positive(row.get("bid")),ao.positive(row.get("ask"))
    qty=ao.number(row.get("top_"+field+"_quantity"))
    if bid is None or ask is None or bid>ask or qty is None or qty<units:
        return None
    return bid if field=="bid" else ask


def _latest(expiry, now):
    try:
        with closing(ao._read_database()) as db:
            row=db.execute("""SELECT captured_utc,snapshot_sha256,normalized_json
              FROM option_chain_observations WHERE underlying='BANKNIFTY'
              AND expiry=? AND captured_utc<=? ORDER BY captured_utc DESC LIMIT 1""",
              (expiry,_iso(now))).fetchone()
            return _snapshot(row)
    except (sqlite3.Error,OSError):
        return None


def _first(expiry, start, end, now):
    """First saved receipt in a preregistered window, no outcome-based picking."""
    try:
        with closing(ao._read_database()) as db:
            row=db.execute("""SELECT captured_utc,snapshot_sha256,normalized_json
              FROM option_chain_observations WHERE underlying='BANKNIFTY'
              AND expiry=? AND captured_utc>=? AND captured_utc<=?
              ORDER BY captured_utc ASC LIMIT 1""",
              (expiry,_iso(start),_iso(min(end,now)))).fetchone()
        return bool(row),_snapshot(row)
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc) or "unable to open database file" in str(exc):
            return False,None
        raise


def latest_expiries(now):
    """At most 12 nearest currently unexpired saved expiries; no REST burst."""
    today=now.astimezone(IST).date().isoformat()
    try:
        with closing(ao._read_database()) as db:
            rows=db.execute("""SELECT o.expiry,o.captured_utc,o.snapshot_sha256,o.normalized_json
                FROM option_chain_observations o JOIN (
                    SELECT expiry,MAX(captured_utc) AS newest FROM option_chain_observations
                    WHERE underlying='BANKNIFTY' AND expiry>=? AND captured_utc<=?
                    GROUP BY expiry ORDER BY expiry LIMIT ?
                ) x ON o.expiry=x.expiry AND o.captured_utc=x.newest
                WHERE o.underlying='BANKNIFTY' ORDER BY o.expiry""",
                (today,_iso(now),MAX_EXPIRIES+1)).fetchall()
        return [(r[0],_snapshot(r[1:])) for r in rows[:MAX_EXPIRIES]],len(rows)>MAX_EXPIRIES
    except (sqlite3.Error,OSError):
        return [],False


def compare(*, now=None, **settings):
    now=now or _now()
    latest,truncated=latest_expiries(now)
    coverage=[]
    rows=[]
    for expiry,snapshot in latest:
        if snapshot is None:
            coverage.append({"expiry":expiry,"state":"invalid_source","age_seconds":None,"ranked_count":0})
            continue
        age,recent=_age(snapshot["received_utc"],now)
        state="recent" if recent and _regular(now) and now<_end(now,expiry) else "delayed_or_closed"
        item={"expiry":expiry,"state":state,"age_seconds":age,"received_utc":snapshot["received_utc"],
              "returned_contracts":len(snapshot["contracts"]),"ranked_count":0}
        if state=="recent":
            analysis=ao.analyze(snapshot,now=now,**settings)
            item["ranked_count"]=analysis["ranked_count"]
            rows.extend({**r,"as_of_utc":analysis["as_of_utc"]} for r in analysis["rows"] if r.get("rank"))
        coverage.append(item)
    # Identical settings and evidence-tier ordering for all expiries. Stale
    # rows are reported in coverage rather than given a cross-expiry rank.
    tier={"recent_depth_and_trades":0,"recent_trades_snapshot_only":1,"indicative_snapshot_only":2}
    rows.sort(key=lambda r:(tier.get(r.get("rank_quality"),3),-r["score"],r["expiry"],r["strike"],r["option_type"]))
    for i,r in enumerate(rows,1):
        r["rank"]=i
    return {"rows":rows[:100],"ranked_count":len(rows),"coverage":coverage,"truncated":truncated,
            "generated_utc":_iso(now),"settings":settings,"read_only":True,"orders_enabled":False,
            "warning":"Saved original chain receipts only, not synchronized across expiries. "
               "Delayed or unavailable expiries cannot be compared live. No extra broker requests."}


def _model(chain,row,rate_pct,dividend_pct):
    if not row or not row.get("quote_valid"):
        return None,None,None
    spot=ao.positive(chain["underlying_spot"])
    strike=ao.positive(row["strike"])
    bid,ask=ao.positive(row.get("bid")),ao.positive(row.get("ask"))
    t=ao.timestamp(chain["received_utc"])
    end=datetime.combine(date.fromisoformat(row["expiry"]),time(15,30),IST)
    years=(end-t).total_seconds()/ao.YEAR_SECONDS
    if not (spot and strike and bid and ask and bid<=ask and years>0):
        return None,None,None
    sigma=ao.implied_iv((bid+ask)/2,spot,strike,years,rate_pct/100,row["option_type"],dividend_pct/100)
    if sigma is None:
        return None,None,years
    return ao.bsm(spot,strike,years,rate_pct/100,sigma,row["option_type"],dividend_pct/100),sigma,years


def _net(entry,exit_,units,profile):
    total=fees.fee_schedule(entry*units,exit_*units,broker_profile=profile)["total_estimated"]
    return fees._money((exit_-entry)*units-total),total


def _required_bid(entry,units,profile,target):
    """Sell premium for a desired fee-adjusted rupee P&L, before tick rounding."""
    if _net(entry,0.,units,profile)[0]>=target:
        return 0.
    lo,hi=0.,max(entry*2,1.)
    # Fee schedule accepts <= 1e10 INR turnover. Do not extrapolate beyond.
    ceiling=min(1e7,1e10/units)
    hi=min(hi,ceiling)
    while _net(entry,hi,units,profile)[0]<target and hi<ceiling:
        hi=min(hi*2,ceiling)
    if _net(entry,hi,units,profile)[0]<target:
        return None
    for _ in range(48):
        mid=(lo+hi)/2
        if _net(entry,mid,units,profile)[0]>=target:
            hi=mid
        else:
            lo=mid
    return round(hi,4)


def _underlying_move(chain,row,sigma,years,required_bid,horizon,iv_shock,rate,dividend,slippage):
    if sigma is None or years is None or required_bid is None or required_bid<=0:
        return None
    next_t=years-horizon*60/ao.YEAR_SECONDS
    vol=sigma+iv_shock/100
    if next_t<=0 or not ao.MIN_IV<vol<=ao.MAX_IV:
        return None
    spot=chain["underlying_spot"]
    lo,hi=.8*spot,1.2*spot
    half=(row["ask"]-row["bid"])/2
    def modeled(s):
        return max(0.,ao.bsm(s,row["strike"],next_t,rate/100,vol,row["option_type"],dividend/100)["price"]-half)*(1-slippage/10000)
    is_call=row["option_type"]=="CE"
    if not min(modeled(lo),modeled(hi))<=required_bid<=max(modeled(lo),modeled(hi)):
        return None
    for _ in range(45):
        mid=(lo+hi)/2
        if (modeled(mid)<required_bid)==is_call:
            lo=mid
        else:
            hi=mid
    return round((lo+hi)/2-spot,2)


def _depth_mark(p,now):
    """Latest original depth within 8s, exact contract, walking all units."""
    cutoff=now-timedelta(seconds=8)
    try:
        with closing(ao._read_database()) as db:
            records=db.execute("""SELECT received_utc,book_json,packet_pair_sha256
                 FROM live_depth_books WHERE identity=? AND received_utc>=?
                 AND received_utc<=? ORDER BY received_utc DESC LIMIT 1""",
                 (p["contract_identity"],_iso(cutoff),_iso(now))).fetchone()
        if not records:
            return None
        stamp,raw,digest=records
        v=spread_scanner._original_book(p["contract_identity"],stamp,raw,digest)
        if not v:
            return None
        book,stats,feature=v
        if (feature.get("expiry")!=p["expiry"] or feature.get("strike")!=p["strike"] or
            feature.get("side")!=("CE" if p["direction"]=="CALL" else "PE") or
            stats["lot_size"]!=p["lot_size"]):
            return None
        walk=fees._walk(book["bid"],p["quantity"])
        return {"received_utc":stamp,"bid":walk["vwap"],"top_bid":stats["bid"],
                "covered_units":walk["observed_units"],"source":"original_20_level_bid_walk"}
    except (ValueError,TypeError,sqlite3.Error,OSError):
        return None


def position_marks(*, target_pct=5., stop_pct=2.5, horizon_minutes=5, iv_change_points=0.,
                   rate_pct=6.5, dividend_pct=0., slippage_bps=10., now=None):
    for v,lo,hi in ((target_pct,.01,1000),(stop_pct,.01,100),(horizon_minutes,1,1440),
                     (iv_change_points,-50,50),(rate_pct,-5,25),(dividend_pct,0,25),(slippage_bps,0,500)):
        if ao.number(v) is None or not lo<=v<=hi:
            raise ValueError("Invalid exit analysis assumption")
    now=now or _now()
    positions=journal.open_trades()
    cache={}
    results=[]
    for p in positions:
        result={**p,"mark":None,"estimated_net_pnl_inr":None,"estimated_charges_inr":None,
                "greeks":None,"iv_pct":None,"model_receipt_utc":None,"exit_levels":None,
                "last_chain_bid":None,"state":"unlinked_contract"}
        results.append(result)
        if not p["contract_identity"]:
            continue
        expiry=p["expiry"]; side="CE" if p["direction"]=="CALL" else "PE"
        if expiry not in cache:
            cache[expiry]=_latest(expiry,now)
        snapshot=cache[expiry]
        row=_contract(snapshot,p["contract_identity"],expiry,p["strike"],side,p["lot_size"])
        profile=p["broker_profile"] or "zerodha"
        entry,units=p["entry_price"],p["quantity"]
        # Protect against unsupported legacy journal turnover.
        if entry*units>1e10:
            result["state"]="unsupported_turnover"
            continue
        target=entry*units*target_pct/100
        stop=-entry*units*stop_pct/100
        levels={name:{"target_net_inr":amount,"sell_bid":_required_bid(entry,units,profile,amount),
                      "model_underlying_move_points":None}
                for name,amount in (("break_even",0.),("profit_target",target),("stop_loss",stop))}
        result["exit_levels"]=levels
        open_now=_regular(now) and now<_end(now,expiry)
        fresh=False
        if row:
            stamp=snapshot["received_utc"]; age,fresh=_age(stamp,now)
            result["last_chain_bid"]=row.get("bid")
            result["model_receipt_utc"]=stamp
            model,sigma,years=_model(snapshot,row,rate_pct,dividend_pct)
            if model:
                result["greeks"]={k:v*units for k,v in model.items() if k!="price"}
                result["iv_pct"]=sigma*100
                if fresh and open_now:
                    for item in levels.values():
                        item["model_underlying_move_points"]=_underlying_move(snapshot,row,sigma,years,
                           item["sell_bid"],horizon_minutes,iv_change_points,rate_pct,dividend_pct,slippage_bps)
            if fresh:
                result["mark"]={"received_utc":stamp,"bid":_quote(row,"bid",units),
                                "top_bid":row.get("bid"),"covered_units":row.get("top_bid_quantity"),
                                "source":"saved_chain_top_bid"}
        if not open_now:
            result["state"]="market_closed_or_contract_expired"
            result["mark"]=None
            continue
        depth=_depth_mark(p,now)
        if depth and (not result["mark"] or ao.timestamp(depth["received_utc"])>=ao.timestamp(result["mark"]["received_utc"])):
            result["mark"]=depth
        mark=result["mark"]
        if not mark:
            result["state"]="no_recent_quote"
        elif mark["bid"] is None:
            result["state"]="insufficient_displayed_bid_quantity"
        else:
            net,charges=_net(entry,mark["bid"],units,profile)
            result["estimated_net_pnl_inr"]=net
            result["estimated_charges_inr"]=charges
            result["state"]="target_observed" if net>=target else "stop_observed" if net<=stop else "marked_inside_levels"
    marked=[p for p in results if p["estimated_net_pnl_inr"] is not None]
    fresh_greeks=[p for p in results if p["greeks"] and p["model_receipt_utc"] and
                  _regular(now) and now<_end(now,p["expiry"]) and _age(p["model_receipt_utc"],now)[1]]
    complete=len(results)<100
    return {"positions":results,"total_open":len(results),"marked_count":len(marked),
       "coverage_limited":not complete,
       "marked_net_pnl_inr":fees._money(sum(p["estimated_net_pnl_inr"] for p in marked)) if marked else None,
       "all_positions_marked":complete and len(marked)==len(results),
       "aggregate_greeks":{k:sum(p["greeks"][k] for p in fresh_greeks)
          for k in ("delta","gamma","theta_day","vega_iv_point","rho_rate_point")} if fresh_greeks else None,
       "fresh_greeks_count":len(fresh_greeks),"generated_utc":_iso(now),"read_only":True,"orders_enabled":False,
       "warning":"User-entered fills, estimated round-trip charges, most recent saved full-size bid. "
         "Exit levels are observations and conditional model inversions, not orders. "
         "Greek aggregation covers only fresh model receipts and is not synchronized. "
         "Targets use premium notional; price gaps can exceed the selected stop."}


@contextmanager
def _ledger():
    with journal._conn() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS option_workflow_settings(
            key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS option_alert_rules(
            id TEXT PRIMARY KEY,created_utc TEXT NOT NULL,
            identity TEXT NOT NULL,expiry TEXT NOT NULL,strike REAL NOT NULL,
            side TEXT NOT NULL,lot_size INTEGER NOT NULL,conditions_json TEXT NOT NULL,
            enabled INTEGER NOT NULL,last_match INTEGER,last_receipt_utc TEXT,
            state TEXT NOT NULL DEFAULT 'waiting_for_receipt');
        CREATE TABLE IF NOT EXISTS option_alert_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,rule_id TEXT NOT NULL,
            observed_utc TEXT NOT NULL,created_utc TEXT NOT NULL,values_json TEXT NOT NULL,
            UNIQUE(rule_id,observed_utc));
        CREATE TABLE IF NOT EXISTS option_rank_observations(
            id TEXT PRIMARY KEY,decision_utc TEXT NOT NULL,quote_utc TEXT NOT NULL,
            identity TEXT NOT NULL,expiry TEXT NOT NULL,strike REAL NOT NULL,
            side TEXT NOT NULL,lot_size INTEGER NOT NULL,units INTEGER NOT NULL,
            score REAL NOT NULL,evidence TEXT NOT NULL,decision_ask REAL NOT NULL,
            horizon_minutes INTEGER NOT NULL,broker_profile TEXT NOT NULL,
            assumptions_json TEXT NOT NULL,state TEXT NOT NULL,
            cohort TEXT NOT NULL DEFAULT 'top',pair_key TEXT,rank_at_decision INTEGER,
            entry_utc TEXT,entry_ask REAL,exit_due_utc TEXT,exit_utc TEXT,exit_bid REAL,
            net_pnl_inr REAL,charges_inr REAL,reason TEXT);
        CREATE INDEX IF NOT EXISTS option_rank_pending ON option_rank_observations(state,decision_utc);
        """)
        # Additive repair for prerelease local databases; never remove history.
        columns={r[1] for r in db.execute("PRAGMA table_info(option_rank_observations)")}
        for key,declaration in (("cohort","TEXT NOT NULL DEFAULT 'top'"),
                                ("pair_key","TEXT"),("rank_at_decision","INTEGER")):
            if key not in columns:
                try:
                    db.execute("ALTER TABLE option_rank_observations ADD COLUMN "+key+" "+declaration)
                except sqlite3.OperationalError:
                    if key not in {r[1] for r in db.execute("PRAGMA table_info(option_rank_observations)")}:
                        raise
        yield db


def set_tracking(enabled):
    with _ledger() as db:
        db.execute("INSERT OR REPLACE INTO option_workflow_settings VALUES('track_shortlist',?)",
                   ("1" if enabled else "0",))
    return {"tracking_enabled":bool(enabled)}


def _tracking(db):
    row=db.execute("SELECT value FROM option_workflow_settings WHERE key='track_shortlist'").fetchone()
    return bool(row and row[0]=="1")


def record_if_enabled(analysis,*,now=None):
    """Record the top two each side *before* future receipts are evaluated."""
    # Avoid creating or migrating any database on an ordinary analytics read.
    if not (service.DATA/"trading_cockpit"/"manual_trades.sqlite3").is_file():
        return 0
    now=now or _now()
    if not _regular(now):
        return 0
    if "chain" in analysis and analysis["chain"].get("source")!=CHAIN_SOURCE:
        return 0
    settings=analysis.get("assumptions",analysis.get("settings",{}))
    rows=sorted([r for r in analysis.get("rows",[]) if r.get("rank")],key=lambda r:r["rank"])
    chosen=[r for side in ("CE","PE") for r in [x for x in rows if x["option_type"]==side][:2]]
    payload=json.dumps(settings,sort_keys=True,separators=(",",":"))
    scope="selected_expiry" if "chain" in analysis else "across_expiries"
    chosen_ids={r["identity"] for r in chosen}
    used_controls=set()
    inserted=0
    with _ledger() as db:
        if not _tracking(db):
            return 0
        for r in chosen:
            stamp=r.get("as_of_utc",analysis.get("as_of_utc"))
            if not _age(stamp,now)[1] or not r.get("identity") or r["units"]<=0:
                continue
            horizon=int(settings["horizon_minutes"])
            if now+timedelta(seconds=ENTRY_WINDOW+60*horizon+EXIT_WINDOW)>_end(now,r["expiry"]):
                continue
            pair=sha256((scope+"|"+r["identity"]+"|"+stamp+"|"+payload).encode()).hexdigest()
            # Match using only information known at decision time. Same expiry,
            # side, evidence tier and position units; ask within 25%. Control
            # must be lower-ranked and cannot be another leading selection.
            candidates=[x for x in rows if x["identity"] not in chosen_ids and
                x["identity"] not in used_controls and x["rank"]>r["rank"] and
                x["score"]<r["score"] and x["expiry"]==r["expiry"] and
                x["option_type"]==r["option_type"] and x["rank_quality"]==r["rank_quality"] and
                x["units"]==r["units"] and abs(x["ask"]/r["ask"]-1)<=.25 and
                _age(x.get("as_of_utc",analysis.get("as_of_utc")),now)[1]]
            control=min(candidates,key=lambda x:(abs(x["ask"]-r["ask"]),x["rank"])) if candidates else None
            if control:
                used_controls.add(control["identity"])
            for cohort,item in [("top",r)]+([("control",control)] if control else []):
                item_stamp=item.get("as_of_utc",analysis.get("as_of_utc"))
                key=sha256((pair+"|"+cohort).encode()).hexdigest()
                cur=db.execute("""INSERT OR IGNORE INTO option_rank_observations
                     (id,decision_utc,quote_utc,identity,expiry,strike,side,lot_size,units,
                      score,evidence,decision_ask,horizon_minutes,broker_profile,assumptions_json,state,
                      cohort,pair_key,rank_at_decision)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'waiting_entry',?,?,?)""",
                    (key,_iso(now),item_stamp,item["identity"],item["expiry"],item["strike"],item["option_type"],
                     item["lot_size"],item["units"],item["score"],item["rank_quality"],item["ask"],horizon,
                     settings["broker_profile"],payload,cohort,pair,item["rank"]))
                inserted+=cur.rowcount
    return inserted


def create_alert(identity,conditions,*,now=None):
    now=now or _now()
    if not fees.ID.fullmatch(identity):
        raise ValueError("Choose a verified exact option identity")
    master=option_chain_live._contracts()
    c=master.get("by_id",{}).get(identity.split(":")[1])
    if (not master.get("fresh") or not c or c["identity"]!=identity or
        now>=datetime.combine(date.fromisoformat(c["expiry"]),time(15,30),IST)):
        raise ValueError("A current verified BANKNIFTY contract is required")
    bounds={"max_ask":(.01,1e6),"max_spread_bps":(0,10000),"min_abs_delta":(0,1),
        "max_abs_delta":(0,1),"min_iv_pct":(0,500),"max_iv_pct":(0,500),
        "min_bid":(.01,1e6),"max_bid":(.01,1e6),"min_top_units":(1,1000000)}
    if not conditions or set(conditions)-set(bounds):
        raise ValueError("Select at least one supported alert threshold")
    for k,v in conditions.items():
        if ao.number(v) is None or not bounds[k][0]<=v<=bounds[k][1]:
            raise ValueError("Invalid alert threshold: "+k)
    for lo,hi in (("min_abs_delta","max_abs_delta"),("min_iv_pct","max_iv_pct"),("min_bid","max_bid")):
        if lo in conditions and hi in conditions and conditions[lo]>conditions[hi]:
            raise ValueError("Minimum threshold exceeds maximum")
    aid="alert_"+uuid.uuid4().hex[:20]
    with _ledger() as db:
        if db.execute("SELECT COUNT(*) FROM option_alert_rules WHERE enabled=1").fetchone()[0]>=100:
            raise ValueError("Disable an existing alert before enabling more than 100")
        db.execute("""INSERT INTO option_alert_rules
            (id,created_utc,identity,expiry,strike,side,lot_size,conditions_json,enabled)
            VALUES(?,?,?,?,?,?,?,?,1)""",(aid,_iso(now),identity,c["expiry"],c["strike"],
                         c["option_type"],c["lot_size"],json.dumps(conditions,sort_keys=True)))
    return {"id":aid,"enabled":True}


def disable_alert(aid):
    with _ledger() as db:
        if db.execute("UPDATE option_alert_rules SET enabled=0,state='disabled' WHERE id=?",(aid,)).rowcount!=1:
            raise ValueError("Unknown alert")
    return {"id":aid,"enabled":False}


def _alert_values(snapshot,row):
    if not row or not row.get("quote_valid"):
        return {}
    bid,ask=ao.positive(row.get("bid")),ao.positive(row.get("ask"))
    if not bid or not ask or bid>ask:
        return {}
    model,sigma,_=_model(snapshot,row,6.5,0.)
    bq,aq=ao.number(row.get("top_bid_quantity")),ao.number(row.get("top_ask_quantity"))
    return {"ask":ask,"bid":bid,"spread_bps":(ask-bid)/((ask+bid)/2)*10000,
            "abs_delta":abs(model["delta"]) if model else None,
            "iv_pct":sigma*100 if sigma else None,
            "top_units":min(bq,aq) if bq is not None and aq is not None else None}


def _alert_match(values,conditions):
    if not values:
        return None
    checks=[]
    for k,threshold in conditions.items():
        op,field=k.split("_",1)
        v=values.get(field)
        if v is None:
            return None
        checks.append(v>=threshold if op=="min" else v<=threshold)
    return all(checks)


def _evaluate_alerts(db,now):
    cache={}
    rules=db.execute("SELECT * FROM option_alert_rules WHERE enabled=1 ORDER BY created_utc LIMIT 100").fetchall()
    for a in rules:
        expiry=a["expiry"]
        if now>=datetime.combine(date.fromisoformat(expiry),time(15,30),IST):
            db.execute("UPDATE option_alert_rules SET enabled=0,state='expired' WHERE id=?",(a["id"],))
            continue
        if not _regular(now):
            db.execute("UPDATE option_alert_rules SET state='outside_regular_session' WHERE id=?",(a["id"],))
            continue
        if expiry not in cache:
            cache[expiry]=_latest(expiry,now)
        snapshot=cache[expiry]
        if not snapshot or not _age(snapshot["received_utc"],now)[1]:
            db.execute("UPDATE option_alert_rules SET state='awaiting_recent_receipt' WHERE id=?",(a["id"],))
            continue
        stamp=snapshot["received_utc"]
        if stamp==a["last_receipt_utc"] or ao.timestamp(stamp)<ao.timestamp(a["created_utc"]):
            continue
        row=_contract(snapshot,a["identity"],expiry,a["strike"],a["side"],a["lot_size"])
        values=_alert_values(snapshot,row)
        match=_alert_match(values,json.loads(a["conditions_json"]))
        if match is True and a["last_match"]!=1:
            db.execute("INSERT OR IGNORE INTO option_alert_events(rule_id,observed_utc,created_utc,values_json) VALUES(?,?,?,?)",
                        (a["id"],stamp,_iso(now),json.dumps(values,sort_keys=True)))
        db.execute("""UPDATE option_alert_rules SET last_receipt_utc=?,
            last_match=COALESCE(?,last_match),state=? WHERE id=? AND enabled=1""",
            (stamp,int(match) if match is not None else None,
             "matching" if match is True else "not_matching" if match is False else "missing_metric",a["id"]))


def _evaluate_rank(db,now):
    rows=db.execute("""SELECT * FROM option_rank_observations
        WHERE state='waiting_entry' OR (state='waiting_exit' AND exit_due_utc<=?)
        ORDER BY CASE WHEN state='waiting_entry' THEN decision_utc ELSE exit_due_utc END
        LIMIT 200""",(_iso(now),)).fetchall()
    for r in rows:
        entering=r["state"]=="waiting_entry"
        start=ao.timestamp(r["decision_utc"] if entering else r["exit_due_utc"])
        if now<start:
            continue
        end=start+timedelta(seconds=ENTRY_WINDOW if entering else EXIT_WINDOW)
        found,snapshot=_first(r["expiry"],start,end,now)
        if not found and now<=end+timedelta(seconds=15):
            continue
        row=_contract(snapshot,r["identity"],r["expiry"],r["strike"],r["side"],r["lot_size"])
        price=_quote(row,"ask" if entering else "bid",r["units"])
        if price is None:
            reason=("First saved receipt missing verified contract or full-size side quote"
                     if found else "No saved original chain receipt in the fixed observation window")
            db.execute("UPDATE option_rank_observations SET state=?,reason=? WHERE id=?",
                       ("entry_unobservable" if entering else "exit_unobservable",reason,r["id"]))
            continue
        stamp=snapshot["received_utc"]
        observed=ao.timestamp(stamp)
        if not start<=observed<=end or not _regular(observed):
            db.execute("UPDATE option_rank_observations SET state='invalid_receipt',reason=? WHERE id=?",
                       ("Receipt outside registered regular-session window",r["id"]))
            continue
        if entering:
            due=observed+timedelta(minutes=r["horizon_minutes"])
            db.execute("""UPDATE option_rank_observations SET entry_utc=?,entry_ask=?,exit_due_utc=?,
                       state='waiting_exit' WHERE id=?""",(stamp,price,_iso(due),r["id"]))
        else:
            net,charges=_net(r["entry_ask"],price,r["units"],r["broker_profile"])
            db.execute("""UPDATE option_rank_observations SET exit_utc=?,exit_bid=?,net_pnl_inr=?,
                       charges_inr=?,state='observed_quote_markout' WHERE id=?""",
                       (stamp,price,net,charges,r["id"]))


def cycle(now=None):
    now=now or _now()
    if not (service.DATA/"trading_cockpit"/"manual_trades.sqlite3").is_file():
        return
    with _ledger() as db:
        _evaluate_alerts(db,now)
        _evaluate_rank(db,now)


def overview():
    with _ledger() as db:
        rules=[dict(r) for r in db.execute("SELECT * FROM option_alert_rules ORDER BY enabled DESC,created_utc DESC LIMIT 150")]
        events=[dict(r) for r in db.execute("""SELECT e.*,a.identity,a.expiry,a.strike,a.side FROM option_alert_events e
          JOIN option_alert_rules a ON a.id=e.rule_id ORDER BY e.id DESC LIMIT 100""")]
        samples=[dict(r) for r in db.execute("SELECT * FROM option_rank_observations ORDER BY decision_utc DESC,id LIMIT 100")]
        counts={r[0]:r[1] for r in db.execute("SELECT state,COUNT(*) FROM option_rank_observations GROUP BY state")}
        stats=db.execute("""SELECT COUNT(*),SUM(CASE WHEN net_pnl_inr>0 THEN 1 ELSE 0 END),
              SUM(CASE WHEN net_pnl_inr<0 THEN 1 ELSE 0 END),AVG(net_pnl_inr),SUM(net_pnl_inr)
              FROM option_rank_observations WHERE state='observed_quote_markout' AND cohort='top'""").fetchone()
        controls=db.execute("""SELECT COUNT(*) FROM option_rank_observations
            WHERE state='observed_quote_markout' AND cohort='control'""").fetchone()[0]
        paired=db.execute("""SELECT COUNT(*),AVG(100.0*(a.net_pnl_inr/(a.entry_ask*a.units)
                -b.net_pnl_inr/(b.entry_ask*b.units)))
            FROM option_rank_observations a JOIN option_rank_observations b ON a.pair_key=b.pair_key
            WHERE a.cohort='top' AND b.cohort='control'
              AND a.state='observed_quote_markout' AND b.state='observed_quote_markout'
              AND a.entry_ask>0 AND b.entry_ask>0 AND a.units>0 AND b.units>0""").fetchone()
        tracking=_tracking(db)
    for r in rules:
        r["conditions"]=json.loads(r.pop("conditions_json"));r["enabled"]=bool(r["enabled"])
    for r in events:
        r["values"]=json.loads(r.pop("values_json"))
    for r in samples:
        r["assumptions"]=json.loads(r.pop("assumptions_json"))
    return {"tracking_enabled":tracking,"rules":rules,"events":events,"samples":samples,
       "sample_counts":counts,"observed_count":stats[0],"positive_count":stats[1] or 0,
       "negative_count":stats[2] or 0,"mean_markout_inr":stats[3],"sum_markout_inr":stats[4],
       "control_observed_count":controls,"paired_count":paired[0],
       "paired_mean_return_difference_pp":paired[1],
       "worker":{**HEALTH,"alive":bool(WORKER and WORKER.is_alive())},"read_only":True,"orders_enabled":False,
       "warning":"Overlapping, conditional hypothetical positions, not realized profit or independent samples. "
          "Controls are selected before outcomes, matching expiry, side, evidence tier, units and nearby ask; "
          "paired differences use net markout divided by entry premium notional. No statistical superiority claim. "
          "No fill probability; missing entries/exits are censored, never treated as zero or wins."}


def _worker():
    while not STOP.wait(WORKER_INTERVAL):
        try:
            cycle()
            HEALTH.update(state="running",last_cycle_utc=_iso(_now()),last_error=None)
        except (ValueError,TypeError,KeyError,sqlite3.Error,OSError) as e:
            HEALTH.update(state="degraded",last_cycle_utc=_iso(_now()),last_error=type(e).__name__)
    HEALTH["state"]="stopped"


def start():
    global WORKER
    with LOCK:
        if WORKER and WORKER.is_alive():
            return
        STOP.clear()
        WORKER=Thread(target=_worker,name="quantlab-manual-options-monitor",daemon=True)
        HEALTH["state"]="starting"
        WORKER.start()


def stop():
    STOP.set()
    if WORKER and WORKER.is_alive():
        WORKER.join(timeout=2)
