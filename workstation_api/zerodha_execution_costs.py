"""Shared current-tariff NSE options calculator. No broker calls or orders."""
from decimal import Decimal, ROUND_CEILING
from math import isfinite
from . import liquidity_spreads as fees


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
