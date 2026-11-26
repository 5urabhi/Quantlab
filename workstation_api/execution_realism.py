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


def _components(orders,profile,bps):
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
        residual+=observed*bps/10000
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
    audit=_components(entries+exits,profile,base)
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


def sample_trade(result,audit,cfg):
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


def sequential(records,indices,anchors,capital):
    """Conditional single-position account, not a live execution guarantee.

    Reject overlapping anchors and entries exceeding remaining capital.
    Missing entry books do not establish that a real order would not fill.
    An observed incomplete basket or missing exit halts reuse of capital.
    """
    cash=peak=capital
    available=None
    completed=positive=skipped_overlap=skipped_budget=unknown_entries=0
    drawdown=0.
    halted=None
    for i in indices:
        r=records[i]
        if available is not None and anchors[i]<=available:
            skipped_overlap+=1
            continue
        audit=r[4] if len(r)>4 else None
        state=r[1]
        if r[0] is None:
            if r[2] or state in ("entry_partial_or_insufficient_depth","entry_leg_skew_exceeded"):
                halted=state
                break
            if state!="insufficient_hypothetical_risk_budget":
                unknown_entries+=1
            else:
                skipped_budget+=1
            continue
        if not audit:
            halted="missing_cost_audit"
            break
        if audit["entry_risk_inr"]>cash:
            skipped_budget+=1
            continue
        cash=fees._money(cash+r[0])
        available=datetime.fromisoformat(audit["exit_utc"])
        completed+=1;positive+=int(r[0]>0)
        peak=max(peak,cash)
        drawdown=max(drawdown,peak-cash)
        if cash<1000:
            halted="remaining_capital_below_research_minimum"
            break
    return {"completed":completed,"positive":positive,"overlap_skipped":skipped_overlap,
        "budget_skipped":skipped_budget,"entry_unobserved":unknown_entries,"halted_reason":halted,
        "conditional_completed_net_inr":fees._money(cash-capital) if completed else None,
        "conditional_cash_inr":cash if completed else None,
        "closed_trade_drawdown_inr":fees._money(drawdown) if completed else None,
        "fully_observed_account_net_inr":fees._money(cash-capital) if completed and not halted and not unknown_entries else None,
        "actual_fills_observed":False}


def target_exit_vwap(result,cfg):
    """Continuous hypothetical SELL VWAP for a long option; not a tick limit."""
    if result["strategy"]!="LONG_OPTION" or len(result["entries"])!=1:
        return None
    entry=result["entries"][0]
    units=entry["requested_units"]
    need=-entry["cashflow"]
    profile=cfg["broker_profile"]
    def threshold(target):
        lo=0.;hi=max(1.,(need+target+100)/units*2)
        for _ in range(48):
            mid=(lo+hi)/2
            turnover=fees._money(mid*units)
            if turnover-paper._fees("SELL",turnover,profile)>=need+target:
                hi=mid
            else:
                lo=mid
        # Round UP to a display precision, not the exchange price tick.
        import math
        return math.ceil(hi*10000)/10000
    return {"break_even_exit_vwap":threshold(0.),"target_exit_vwap":threshold(cfg["target_net"]),
            "note":"Modeled average sell fill price before tick rounding; not a guaranteed exit price."}
