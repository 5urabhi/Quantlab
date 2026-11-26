"""Conditional execution accounting, not exchange fills or broker certification.

The stress scenarios preserve the exact observed receipt, side, depth
allocation and quantity. Only the hypothetical price multiplier changes.
No passive queue fills or missing quotes are fabricated.
"""
from datetime import datetime
from statistics import mean
from . import depth_replay as replay, paper_execution as paper, liquidity_spreads as fees

STRESS_BPS=(1.,5.,10.)
FEE_KEYS=("brokerage","exchange_indicative","sebi","gst","stt_sell","stamp_buy")


def _reprice(order,bps,profile):
    sign=1 if order["action"]=="BUY" else -1
    turnover=fees._money(order["observed_depth_turnover"]*(1+sign*bps/10000))
    charge=paper._fees(order["action"],turnover,profile)
    return {**order,"turnover":turnover,"fees":charge,
            "vwap":turnover/order["displayed_fill_units"],
            "cashflow":fees._money(-sign*turnover-charge)}


def _valid_entry(strategy,entries,capital):
    cash,loss,risk=replay._entry_risk(strategy,entries,[o["action"] for o in entries],
                                    entries,entries[0]["requested_units"])
    valid=risk<=capital and not ((strategy.endswith("debit") and cash>=0) or
                                  (strategy.endswith("credit") and cash<=0))
    return valid,cash,risk


def _components(orders,profile):
    breakdown={key:0. for key in FEE_KEYS}
    mid=spread=depth=residual=0.
    for o in orders:
        buy=o["action"]=="BUY";sign=-1 if buy else 1
        units=o["displayed_fill_units"]
        top=o["original_best_ask"] if buy else o["original_best_bid"]
        midpoint=(o["original_best_bid"]+o["original_best_ask"])/2
        observed=o["observed_depth_turnover"]
        mid+=sign*midpoint*units
        spread+=sign*(midpoint-top)*units
        depth+=sign*(top*units-observed)
        residual+=sign*(observed-o["turnover"])
        leg=fees.fee_schedule(o["turnover"] if buy else 0.,
                              0. if buy else o["turnover"],broker_profile=profile)
        leg=leg["buy_leg" if buy else "sell_leg"]
        for k in breakdown:
            breakdown[k]+=leg[k]
    total=fees._money(sum(o["fees"] for o in orders))
    net=fees._money(sum(o["cashflow"] for o in orders))
    out={"gross_midpoint_move_inr":fees._money(mid),"spread_cost_inr":fees._money(spread),
         "depth_impact_inr":fees._money(depth),"extra_slippage_inr":fees._money(residual),
         "fee_components_inr":{k:fees._money(v) for k,v in breakdown.items()},
         "fees_inr":total,"net_inr":net}
    out["rounding_reconciliation_inr"]=fees._money(net-(out["gross_midpoint_move_inr"]-
        out["spread_cost_inr"]-out["depth_impact_inr"]-out["extra_slippage_inr"]-total))
    return out


def analyze(result, cfg):
    """A scored baseline path and matched adverse-price stress summaries."""
    if result.get("net_pnl_inr") is None or not result.get("exit_complete"):
        return None
    entries=result["entries"];exits=result["exits"]
    profile=cfg["broker_profile"];base=cfg["slippage_bps"]
    audit=_components(entries+exits,profile)
    stress={}
    for increment in STRESS_BPS:
        bps=base+increment
        ins=[_reprice(o,bps,profile) for o in entries]
        outs=[_reprice(o,bps,profile) for o in exits]
        valid,cash,risk=_valid_entry(result["strategy"],ins,cfg["capital"])
        stress[str(int(increment))]={"net_inr":fees._money(cash+sum(o["cashflow"] for o in outs)) if valid else None,
           "entry_risk_inr":risk,"state":"conditional_complete" if valid else "stress_budget_or_structure_rejected"}
    audit.update(stress=stress,entry_risk_inr=result["entry_risk_proxy"],
        decision_utc=result["decision_utc"],entry_utc=result["entry_received_utc"],
        exit_decision_utc=result["exit_decision_utc"],exit_utc=result["exit_received_utc"],
        entry_delay_seconds=(datetime.fromisoformat(result["entry_received_utc"])-datetime.fromisoformat(result["decision_utc"])).total_seconds(),
        exit_delay_seconds=(datetime.fromisoformat(result["exit_received_utc"])-datetime.fromisoformat(result["exit_decision_utc"])).total_seconds())
    return audit


def sample_trade(result,audit):
    def order(o):
        return {k:o[k] for k in ("identity","action","strike","option_type","expiry","requested_units",
            "original_best_bid","original_best_ask","received_utc","vwap","turnover","fees","cashflow")}
    return {**audit,"entries":[order(o) for o in result["entries"]],"exits":[order(o) for o in result["exits"]],
            "actual_fills_observed":False,"broker_margin_verified":False}


def aggregate(audits):
    if not audits:
        return None
    keys=("gross_midpoint_move_inr","spread_cost_inr","depth_impact_inr","extra_slippage_inr",
          "fees_inr","net_inr","rounding_reconciliation_inr","entry_delay_seconds","exit_delay_seconds")
    output={k:round(mean(a[k] for a in audits),2) for k in keys}
    output["fee_components_inr"]={k:round(mean(a["fee_components_inr"][k] for a in audits),2) for k in FEE_KEYS}
    output["stress"]={}
    for inc in STRESS_BPS:
        key=str(int(inc))
        values=[a["stress"][key]["net_inr"] for a in audits if a["stress"][key]["net_inr"] is not None]
        output["stress"][key]={"attempted":len(audits),"scored":len(values),
            "rejected":len(audits)-len(values),"mean_net":round(mean(values),2) if values else None,
            "worst_net":min(values) if values else None}
    return output
