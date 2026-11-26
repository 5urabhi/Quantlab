"""On-demand standalone Kite basket margin for a saved paper decision.

The calculation endpoint cannot submit orders. No account holdings, available
cash or positions are considered. The result is a current broker estimate,
not a historical margin record or a reservation of funds.
"""
import csv
import gzip
import io
import json
from datetime import datetime, date, time, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from math import isfinite
from . import zerodha_fallback as kite, zerodha_execution_costs as costs


def _terms(candidate, now):
    legs = candidate["legs"]
    units, lots, lot_size = (candidate[k] for k in ("units","lots","lot_size"))
    if (not isinstance(legs,list) or len(legs) not in (1,2)
            or any(type(x) is not int or x<1 for x in (units,lots,lot_size))
            or units != lots*lot_size or units>100000):
        raise ValueError("Invalid saved paper basket sizing")
    local = now.astimezone(kite.IST)
    keys=[]
    for leg in legs:
        expiry=date.fromisoformat(leg["expiry"])
        strike=Decimal(str(leg["strike"]))
        side=leg["side"]
        if (not strike.is_finite() or strike<=0 or side not in ("CE","PE")
                or leg["action"] not in ("BUY","SELL")
                or expiry<local.date() or (expiry==local.date() and local.time()>=time(15,30))
                or not str(leg["identity"]).startswith("NSE_FNO:")):
            raise ValueError("Saved BANKNIFTY leg is invalid or expired")
        keys.append((expiry,strike,side,lot_size))
    if len(set(keys)) != len(keys):
        raise ValueError("Duplicate option terms in paper basket")
    if len(legs)==1:
        if candidate["strategy"]!="LONG_OPTION" or legs[0]["action"]!="BUY":
            raise ValueError("Only long single options are supported")
    elif (keys[0][0]!=keys[1][0] or keys[0][2]!=keys[1][2]
          or {l["action"] for l in legs}!={"BUY","SELL"}
          or candidate["strategy"] not in ("bull_call_debit","bear_put_debit","bull_put_credit","bear_call_credit")):
        raise ValueError("Only same-expiry defined-risk verticals are supported")
    return keys


def _map_master(raw,keys):
    if not isinstance(raw,bytes) or len(raw)>kite.MAX_RESPONSE:
        raise ValueError("Invalid bounded Kite instrument response")
    if raw[:2]==b"\x1f\x8b":
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as handle:
            raw=handle.read(kite.MAX_MASTER_UNCOMPRESSED+1)
    if len(raw)>kite.MAX_MASTER_UNCOMPRESSED:
        raise ValueError("Kite derivative master exceeds bounded size")
    reader=csv.DictReader(io.StringIO(raw.decode("utf-8-sig"),newline=""))
    expected={"exchange","segment","name","tradingsymbol","exchange_token","expiry","strike","instrument_type","lot_size"}
    if not expected.issubset(reader.fieldnames or []):
        raise ValueError("Kite derivative instrument master lacks required columns")
    matches={key:[] for key in keys}
    for row in reader:
        if row.get("exchange")!="NFO" or row.get("segment")!="NFO-OPT" or row.get("name")!="BANKNIFTY":
            continue
        try:
            key=(date.fromisoformat(row["expiry"]),Decimal(row["strike"]),row["instrument_type"],int(row["lot_size"]))
        except (ValueError,TypeError,InvalidOperation):
            continue
        if key not in matches:
            continue
        symbol=row.get("tradingsymbol","")
        token=row.get("exchange_token","")
        if not costs.SYMBOL.fullmatch(symbol) or not token.isdigit():
            raise ValueError("Invalid mapped Kite option identity")
        matches[key].append({"tradingsymbol":symbol,"exchange_token":token})
    if any(len(rows)!=1 for rows in matches.values()):
        raise ValueError("Exact current Kite option terms are missing or ambiguous; margin not calculated")
    return [matches[key][0] for key in keys]


def _decision(decision_id):
    from . import auto_paper_engine as engine
    with engine._db() as db:
        rows=engine._records(db,"SELECT "+engine.FIELDS+" FROM decisions WHERE id=?",(decision_id,))
    if len(rows)!=1 or not rows[0].get("selected"):
        raise ValueError("Selected saved paper candidate unavailable")
    return rows[0]


def _numeric(value):
    if type(value) not in (int,float) or not isfinite(value) or value<0:
        raise ValueError("Invalid Kite margin total")
    return float(value)


def preview(*, decision_id, product="MIS", confirm_readonly=False, now=None):
    if confirm_readonly is not True:
        raise ValueError("Authorize one read-only Kite margin calculation")
    if type(decision_id) is not int or decision_id<1 or product not in ("MIS","NRML"):
        raise ValueError("Select a saved paper decision and supported product")
    row=_decision(decision_id)
    candidate=row["selected"]
    when=now or datetime.now(timezone.utc)
    try:
        keys=_terms(candidate,when)
        capital=_numeric(row["config"]["capital"])
    except (KeyError,TypeError,ValueError,InvalidOperation) as exc:
        raise ValueError("Saved paper basket is invalid or expired") from exc
    costs._guard("basket_margin")
    master=kite._request("/instruments/NFO",timeout=45)
    try:
        mapped=_map_master(master,keys)
    except (UnicodeError,csv.Error,OSError,ValueError,InvalidOperation) as exc:
        raise ValueError("Exact Kite derivative master mapping unavailable: "+str(exc)[:160]) from exc
    if now is None:
        _terms(candidate,datetime.now(timezone.utc))
    pairs=list(zip(candidate["legs"],mapped))
    # Hypothetical buy-before-sell sequence is explicit; no leg is submitted.
    pairs.sort(key=lambda item:item[0]["action"]!="BUY")
    requests=[{"exchange":"NFO","tradingsymbol":m["tradingsymbol"],
               "transaction_type":leg["action"],"variety":"regular","product":product,
               "order_type":"MARKET","quantity":candidate["units"],"price":0,"trigger_price":0}
              for leg,m in pairs]
    raw=kite._request(kite.BASKET_MARGIN_PATH,method="POST",json_body=requests)
    data=costs._response(raw)
    if not isinstance(data,dict) or not isinstance(data.get("initial"),dict) or not isinstance(data.get("final"),dict):
        raise ValueError("Kite did not return both initial and final basket margin")
    initial=_numeric(data["initial"].get("total"))
    final=_numeric(data["final"].get("total"))
    orders=data.get("orders")
    if not isinstance(orders,list) or len(orders)!=len(requests):
        raise ValueError("Kite margin response has incomplete leg coverage")
    details=[]
    for req,(leg,m) in zip(requests,pairs):
        matched=[r for r in orders if isinstance(r,dict) and r.get("exchange")=="NFO" and r.get("tradingsymbol")==req["tradingsymbol"]]
        if len(matched)!=1:
            raise ValueError("Kite margin response does not match exact requested option")
        result=matched[0]
        details.append({"tradingsymbol":req["tradingsymbol"],"side":req["transaction_type"],
                        "quantity":req["quantity"],"dhan_identity":leg["identity"],
                        "kite_exchange_token":m["exchange_token"],"margin_inr":_numeric(result.get("total")),
                        "estimated_charges_inr":_numeric(result["charges"]["total"]) if isinstance(result.get("charges"),dict) else None})
    required=max(initial,final)
    return {"decision_id":decision_id,"decision_utc":row["decision_utc"],"product":product,
            "received_utc":datetime.now(timezone.utc).isoformat(),
            "initial_margin_inr":initial,"final_margin_inr":final,"conservative_margin_inr":required,
            "paper_capital_inr":capital,"within_paper_capital":required<=capital,
            "modeled_risk_inr":candidate.get("modeled_risk_inr"),"legs":details,
            "master_response_sha256":sha256(master).hexdigest(),"margin_response_sha256":sha256(raw).hexdigest(),
            "request_sha256":sha256(json.dumps(requests,sort_keys=True,separators=(",",":")).encode()).hexdigest(),
            "consider_positions":False,"source":costs.API_SOURCE,"orders_enabled":False,"read_only":True,
            "warning":"Current standalone broker calculation, hypothetical buy-before-sell sequence. "
                      "Not actual available funds, order approval, execution or historical margin. "
                      "Does not modify the paper engine or authorize real trades."}
