"""Local manual option-trade journal; no brokers, no live order execution.

User-entered prices are NOT authenticated trade fills. Server-receipt times
are immutable and may differ from true exchange fill times.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager
from zoneinfo import ZoneInfo
import math
import re
import sqlite3
import uuid

from . import service

IST = ZoneInfo("Asia/Kolkata")
SYMBOL = re.compile(r"^[A-Z0-9_.&-]{2,48}$")
TRADE = re.compile(r"^trade_[a-f0-9]{20}$")
MAX_ITEMS = 100


@contextmanager
def _conn() -> sqlite3.Connection:
    path = service.DATA / "trading_cockpit" / "manual_trades.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("""CREATE TABLE IF NOT EXISTS manual_trades (
        id TEXT PRIMARY KEY,
        symbol TEXT NOT NULL,
        direction TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        entry_price REAL NOT NULL,
        entry_recorded_utc TEXT NOT NULL,
        exit_price REAL,
        exit_recorded_utc TEXT,
        fees_inr REAL,
        note TEXT NOT NULL DEFAULT '',
        source_type TEXT NOT NULL DEFAULT 'USER_ENTERED_UNVERIFIED'
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS manual_trade_contracts (
        trade_id TEXT PRIMARY KEY REFERENCES manual_trades(id),
        contract_identity TEXT NOT NULL, expiry TEXT NOT NULL, strike REAL NOT NULL,
        lot_size INTEGER NOT NULL, broker_profile TEXT NOT NULL
    )""")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _money(value: float, name: str, zero_ok: bool = False) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0 or (not zero_ok and number == 0):
        raise ValueError(f"{name} must be a valid positive rupee amount")
    return round(number, 4)


def _format(row: sqlite3.Row, now: datetime | None = None) -> dict:
    v = dict(row)
    start = datetime.fromisoformat(v["entry_recorded_utc"])
    end = (datetime.fromisoformat(v["exit_recorded_utc"])
           if v["exit_recorded_utc"] else (now or datetime.now(timezone.utc)))
    seconds = max(0, round((end - start).total_seconds()))
    closed = v["exit_recorded_utc"] is not None
    net = (round((v["exit_price"] - v["entry_price"]) * v["quantity"] -
                 (v["fees_inr"] or 0), 2) if closed else None)
    v.update({
        "status": "CLOSED" if closed else "OPEN",
        "holding_seconds": seconds,
        "holding_rule_exceeded": seconds > 360,
        "gross_notional_inr": round(v["entry_price"] * v["quantity"], 2),
        "net_pnl_inr": net,
        "entry_session_ist": start.astimezone(IST).date().isoformat(),
        "exit_session_ist": end.astimezone(IST).date().isoformat() if closed else None,
        "data_quality": "MANUAL_PRICE_AND_SERVER_RECEIPT_NOT_BROKER_VERIFIED",
    })
    return v


def _verified_contract(identity: str, symbol: str, direction: str, quantity: int,
                       broker_profile: str) -> dict:
    from . import option_chain_live, liquidity_spreads
    if not liquidity_spreads.ID.fullmatch(identity) or broker_profile not in liquidity_spreads.BROKER_PROFILES:
        raise ValueError("Choose a verified exact NSE_FNO identity and supported brokerage profile")
    master=option_chain_live._contracts()
    contract=master.get("by_id",{}).get(identity.split(":")[1])
    if not master.get("fresh") or not contract or contract["identity"]!=identity:
        raise ValueError("Refresh the current Dhan instrument master before linking a trade")
    if (contract["symbol"].strip().upper()!=symbol.strip().upper() or
        contract["option_type"]!=("CE" if direction=="CALL" else "PE") or
        quantity % contract["lot_size"]):
        raise ValueError("Contract symbol, direction or lot quantity does not match the verified identity")
    return contract


def _linked_query(where="", suffix=""):
    return ("SELECT t.*,c.contract_identity,c.expiry,c.strike,c.lot_size,c.broker_profile "
            "FROM manual_trades t LEFT JOIN manual_trade_contracts c ON c.trade_id=t.id "
            + where + " " + suffix)


def enter(symbol: str, direction: str, quantity: int,
          entry_price: float, note: str = "", contract_identity: str | None = None,
          broker_profile: str = "zerodha") -> dict:
    if not SYMBOL.fullmatch(symbol) or direction not in ("CALL", "PUT"):
        raise ValueError("Enter an exact supported option symbol and CALL or PUT")
    if not 1 <= quantity <= 1_000_000:
        raise ValueError("Quantity must be between 1 and 1,000,000")
    price = _money(entry_price, "Entry premium")
    if len(note) > 250:
        raise ValueError("Trade note too long")
    contract=_verified_contract(contract_identity,symbol,direction,quantity,broker_profile) if contract_identity else None
    created = datetime.now(timezone.utc).isoformat()
    trade_id = "trade_" + uuid.uuid4().hex[:20]
    with _conn() as conn:
        conn.execute("""INSERT INTO manual_trades
            (id,symbol,direction,quantity,entry_price,entry_recorded_utc,note)
            VALUES(?,?,?,?,?,?,?)""",
            (trade_id, symbol, direction, quantity, price, created, note))
        if contract:
            conn.execute("INSERT INTO manual_trade_contracts VALUES(?,?,?,?,?,?)",
                         (trade_id,contract_identity,contract["expiry"],contract["strike"],
                          contract["lot_size"],broker_profile))
        row = conn.execute(_linked_query("WHERE t.id=?"), (trade_id,)).fetchone()
    return _format(row)


def link_trade(trade_id: str, contract_identity: str, broker_profile: str = "zerodha") -> dict:
    """Explicitly link an existing unlinked open user-entered journal position."""
    if not TRADE.fullmatch(trade_id):
        raise ValueError("Invalid manual trade identifier")
    with _conn() as conn:
        row=conn.execute(_linked_query("WHERE t.id=?"),(trade_id,)).fetchone()
        if row is None or row["exit_recorded_utc"] or row["contract_identity"]:
            raise ValueError("Only an open, unlinked manual record can be linked")
        contract=_verified_contract(contract_identity,row["symbol"],row["direction"],row["quantity"],broker_profile)
        conn.execute("INSERT INTO manual_trade_contracts VALUES(?,?,?,?,?,?)",
                     (trade_id,contract_identity,contract["expiry"],contract["strike"],contract["lot_size"],broker_profile))
        return _format(conn.execute(_linked_query("WHERE t.id=?"),(trade_id,)).fetchone())


def open_trades(limit: int = 100) -> list[dict]:
    with _conn() as conn:
        rows=conn.execute(_linked_query("WHERE t.exit_recorded_utc IS NULL",
                    "ORDER BY t.entry_recorded_utc DESC LIMIT ?"),(limit,)).fetchall()
    return [_format(row) for row in rows]


def exit_trade(trade_id: str, exit_price: float, fees_inr: float = 0) -> dict:
    if not TRADE.fullmatch(trade_id):
        raise ValueError("Invalid manual trade identifier")
    price = _money(exit_price, "Exit premium", zero_ok=True)
    fees = _money(fees_inr, "Combined charges", zero_ok=True)
    with _conn() as conn:
        result = conn.execute("""UPDATE manual_trades SET exit_price=?,
            exit_recorded_utc=?,fees_inr=? WHERE id=? AND exit_recorded_utc IS NULL""",
            (price, datetime.now(timezone.utc).isoformat(), fees, trade_id))
        if result.rowcount != 1:
            raise ValueError("Trade not found or already closed; original record is immutable")
        row = conn.execute(_linked_query("WHERE t.id=?"), (trade_id,)).fetchone()
    return _format(row)


def list_trades(limit: int = 50) -> dict:
    if not 1 <= limit <= MAX_ITEMS:
        raise ValueError("Invalid trade journal limit")
    with _conn() as conn:
        rows = conn.execute(_linked_query(suffix="ORDER BY t.entry_recorded_utc DESC LIMIT ?"),
                            (limit,)).fetchall()
    trades = [_format(row) for row in rows]
    closed = [row for row in trades if row["status"] == "CLOSED"]
    days: dict[str,dict] = {}
    for row in closed:
        day = row["exit_session_ist"]
        group = days.setdefault(day, {"exit_session_ist": day, "closed": 0,
                                       "net_pnl_inr": 0.0, "over_6_min": 0})
        group["closed"] += 1
        group["net_pnl_inr"] = round(group["net_pnl_inr"] + row["net_pnl_inr"],2)
        group["over_6_min"] += int(row["holding_rule_exceeded"])
    return {
        "trades": trades,
        "summary": {
            "open": sum(row["status"] == "OPEN" for row in trades),
            "closed": len(closed),
            "closed_net_pnl_inr": round(sum(row["net_pnl_inr"] for row in closed),2),
            "holding_violations": sum(row["holding_rule_exceeded"] for row in closed),
            "days": sorted(days.values(), key=lambda x:x["exit_session_ist"], reverse=True),
            "limited_to_recent": len(trades) >= limit,
        },
        "disclaimer": ("User-entered prices and server-recorded times only, "
                       "not independently observed exchange fills. "
                       "Charges are the user-supplied total per trade."),
    }
