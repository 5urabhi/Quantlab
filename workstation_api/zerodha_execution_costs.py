"""Shared current-tariff NSE options calculator. No broker calls or orders."""
from decimal import Decimal, ROUND_CEILING
from math import isfinite
from . import liquidity_spreads as fees, zerodha_fallback as kite
from datetime import datetime, timezone
from threading import Lock
import json
import re
import time

SYMBOL=re.compile(r"^BANKNIFTY[A-Z0-9]{4,32}(CE|PE)$")
_LOCK=Lock()
_LAST_REQUEST={}
API_SOURCE="https://kite.trade/docs/connect/v3/margins/"


def _schedule(buy,sell,q,buy_orders,sell_orders,profile):
    return fees.fee_schedule(buy*q,sell*q,broker_profile=profile,
                             buy_orders=buy_orders,sell_orders=sell_orders)


def _target_exit(buy,q,buy_orders,sell_orders,profile,target):
    # Fee schedule is nondecreasing in exit premium. Monotone fixed-point
    # iteration starts at the zero-cost lower bound, in ₹0.05 ticks.
    tick=Decimal(".05")
    b=Decimal(str(buy))
    qd=Decimal(q)
    def ceil_tick(v):
        return max(tick,(v/tick).to_integral_value(rounding=ROUND_CEILING)*tick)
    p=ceil_tick(b+Decimal(str(target))/qd)
    for _ in range(64):
        if p>20000:
            return None
        charge=_schedule(buy,float(p),q,buy_orders,sell_orders,profile)["total_estimated"]
        need=ceil_tick(b+(Decimal(str(target))+Decimal(str(charge)))/qd)
        if need<=p:
            return float(p)
        p=need
    return None


def estimate(*,buy_premium,sell_premium,quantity,buy_orders=1,sell_orders=1,
             broker_profile="zerodha",target_net_inr=100.,extra_spread_points=0.,
             extra_slippage_points=0.,gross_winner_inr=200.,gross_loser_inr=150.,
             win_rate_pct=70.):
    if broker_profile not in ("zerodha","zerodha_debit_balance"):
        raise ValueError("Choose the applicable Zerodha resident retail tariff")
    if type(quantity) is not int or not 1<=quantity<=100000:
        raise ValueError("Enter 1–100,000 option units")
    for v,lo,hi in ((buy_premium,.05,20000),(sell_premium,.05,20000),
        (target_net_inr,0,1e8),(extra_spread_points,0,20000),
        (extra_slippage_points,0,20000),(gross_winner_inr,0,1e8),
        (gross_loser_inr,0,1e8),(win_rate_pct,0,100)):
        if type(v) not in (int,float) or not isfinite(v) or not lo<=v<=hi:
            raise ValueError("Invalid premium, cost or expectancy assumption")
    q=quantity
    extra=q*(extra_spread_points+extra_slippage_points)
    schedule=_schedule(buy_premium,sell_premium,q,buy_orders,sell_orders,broker_profile)
    gross=(sell_premium-buy_premium)*q
    result={"fees":schedule,"gross_pnl_inr":fees._money(gross),
            "extra_execution_cost_inr":fees._money(extra),
            "net_pnl_inr":fees._money(gross-schedule["total_estimated"]-extra),
            "break_even_sell_premium":_target_exit(buy_premium,q,buy_orders,sell_orders,broker_profile,extra),
            "target_sell_premium":_target_exit(buy_premium,q,buy_orders,sell_orders,broker_profile,target_net_inr+extra),
            "target_net_inr":target_net_inr,"tick_assumption":.05,
            "expectancy":None,"read_only":True,"orders_enabled":False}
    win_exit=buy_premium+gross_winner_inr/q
    loss_exit=buy_premium-gross_loser_inr/q
    if 0<loss_exit<=win_exit<=20000:
        wf=_schedule(buy_premium,win_exit,q,buy_orders,sell_orders,broker_profile)["total_estimated"]
        lf=_schedule(buy_premium,loss_exit,q,buy_orders,sell_orders,broker_profile)["total_estimated"]
        win=gross_winner_inr-wf-extra
        loss=-gross_loser_inr-lf-extra
        p=win_rate_pct/100
        result["expectancy"]={"winning_fees":wf,"losing_fees":lf,
            "net_winner":fees._money(win),"net_loser":fees._money(loss),
            "break_even_win_pct":100*(-loss)/(win-loss) if win>loss else None,
            "expected_net_inr":fees._money(p*win+(1-p)*loss)}
    return result


def _guard(key):
    with _LOCK:
        now=time.monotonic()
        if now-_LAST_REQUEST.get(key,-100000)<5:
            raise ValueError("Kite read-only request recently made; retry in a few seconds")
        _LAST_REQUEST[key]=now


def _response(raw):
    try:
        v=json.loads(raw)
    except (ValueError,TypeError,UnicodeError):
        raise ValueError("Invalid Kite response") from None
    if not isinstance(v,dict) or v.get("status")!="success" or "data" not in v:
        raise ValueError("Kite read-only response unavailable")
    return v["data"]


def _num(v):
    if type(v) not in (int,float) or not isfinite(v) or v<0:
        raise ValueError("Missing or invalid numeric Kite charge response")
    return v


def _charge(row,expected):
    if not isinstance(row,dict) or any(row.get(k)!=expected[k] for k in
        ("transaction_type","tradingsymbol","exchange","product","quantity")):
        raise ValueError("Kite charge response does not match requested contract and side")
    if abs(_num(row.get("price"))-expected["average_price"])>1e-6:
        raise ValueError("Kite charge response price mismatch")
    c=row.get("charges")
    if not isinstance(c,dict) or not isinstance(c.get("gst"),dict):
        raise ValueError("Kite charge breakdown unavailable")
    out={k:_num(c.get(k)) for k in ("brokerage","transaction_tax","exchange_turnover_charge",
                        "sebi_turnover_charge","stamp_duty","total")}
    out["gst"]=_num(c["gst"].get("total"))
    if abs(sum(v for k,v in out.items() if k!="total")-out["total"])>.05:
        raise ValueError("Kite charge breakdown does not reconcile")
    return {**out,"side":expected["transaction_type"]}


def virtual_note(*,tradingsymbol,quantity,buy_premium,sell_premium,product="MIS"):
    local=estimate(buy_premium=buy_premium,sell_premium=sell_premium,quantity=quantity)
    if not isinstance(tradingsymbol,str) or not SYMBOL.fullmatch(tradingsymbol) or product not in ("MIS","NRML"):
        raise ValueError("Enter the exact BANKNIFTY CE/PE tradingsymbol from Kite")
    _guard("virtual_note")
    requests=[{"order_id":f"quantlab_calculation_{side.lower()}","exchange":"NFO",
               "tradingsymbol":tradingsymbol,"transaction_type":side,"variety":"regular",
               "product":product,"order_type":"LIMIT","quantity":quantity,"average_price":premium}
              for side,premium in (("BUY",buy_premium),("SELL",sell_premium))]
    data=_response(kite._request("/charges/orders",method="POST",json_body=requests))
    if not isinstance(data,list) or len(data)!=2 or not all(isinstance(r,dict) for r in data):
        raise ValueError("Kite did not return both hypothetical order calculations")
    ordered=[]
    for request in requests:
        matches=[r for r in data if r.get("transaction_type")==request["transaction_type"]]
        if len(matches)!=1:
            raise ValueError("Kite charge response side mismatch")
        ordered.append(_charge(matches[0],request))
    total=fees._money(sum(r["total"] for r in ordered))
    return {"tradingsymbol":tradingsymbol,"quantity":quantity,"product":product,
            "buy_premium":buy_premium,"sell_premium":sell_premium,"sides":ordered,
            "broker_estimated_total":total,"local_estimated_total":local["fees"]["total_estimated"],
            "difference_inr":fees._money(total-local["fees"]["total_estimated"]),
            "net_pnl_inr":fees._money((sell_premium-buy_premium)*quantity-total),
            "received_utc":datetime.now(timezone.utc).isoformat(),"source":API_SOURCE,
            "read_only":True,"orders_enabled":False,
            "warning":"Hypothetical virtual contract note, not an executed order or final contract note."}


def positions():
    _guard("positions")
    v=_response(kite._request("/portfolio/positions",method="GET"))
    if not isinstance(v,dict) or not isinstance(v.get("net"),list) or len(v["net"])>10000:
        raise ValueError("Kite net positions response unavailable")
    rows=[]
    for item in v["net"]:
        if not isinstance(item,dict) or item.get("exchange")!="NFO" or not SYMBOL.fullmatch(str(item.get("tradingsymbol",""))):
            continue
        qty=item.get("quantity")
        if type(qty) is not int:
            raise ValueError("Invalid Kite position quantity")
        if qty==0:
            continue
        row={"tradingsymbol":item["tradingsymbol"],"quantity":qty,
             "product":item.get("product") if item.get("product") in ("MIS","NRML") else "OTHER"}
        for key in ("average_price","last_price","pnl","realised","unrealised"):
            value=item.get(key)
            row[key]=value if type(value) in (float,int) and isfinite(value) else None
        rows.append(row)
    return {"rows":rows,"received_utc":datetime.now(timezone.utc).isoformat(),
            "source":"Zerodha Kite GET /portfolio/positions · net",
            "read_only":True,"orders_enabled":False,
            "warning":"Broker-reported position P&L; not fee-adjusted liquidation value or an executable quote. Separate from the manual journal."}
