"""Deterministic exit policy. Marks are observations, never assumed fills."""
from datetime import timedelta
from . import paper_execution as paper, advanced_options as ao, trading_cockpit as trend
from . import replay_storage

VERSION="dynamic_exit_v1"
MODES=("fixed","target_stop","trailing","signal_reversal","adaptive")
HOLDS=(60,120,300,600,900,1800)
DEFAULTS={"exit_mode":"adaptive","stop_net":250.,"trail_net":50.,
          "liquidity_grace_seconds":20,"slippage_bps":0.}
POLL_SECONDS=5


def validate(cfg):
    if cfg.get("exit_mode") not in MODES:
        raise ValueError("Unknown exit policy")
    if cfg.get("hold_seconds") not in HOLDS:
        raise ValueError("Choose 1, 2, 5, 10, 15 or 30 minutes")
    for key,lo,hi in (("stop_net",1,1e7),("trail_net",1,1e7),("slippage_bps",0,500)):
        paper._check(cfg.get(key),lo,hi,key)
    if type(cfg.get("liquidity_grace_seconds")) is not int or not 5<=cfg["liquidity_grace_seconds"]<=120:
        raise ValueError("Choose a liquidity grace of 5 to 120 seconds")


def signal_from_db(db,now):
    """Use only completed local bars whose last receipt precedes the query."""
    day=now.astimezone(paper.IST).date().isoformat()
    rows=replay_storage.fetchall(db,"""SELECT minute_utc,session_ist,open,high,low,close
        FROM live_minute_bars WHERE identity='INDEX:BANKNIFTY' AND session_ist=?
        AND minute_utc<? AND last_received_utc<=? ORDER BY minute_utc DESC LIMIT 120""",
        (day,paper._iso(now.replace(second=0,microsecond=0)),paper._iso(now)))
    if not rows:
        return None
    bars=[dict(zip(("timestamp_utc","session_ist","open","high","low","close"),r),volume=0)
          for r in reversed(rows)]
    return trend.snapshot("INDEX:BANKNIFTY",bars,now=now,include_chart=False)


def ema_direction(signal,now):
    # Freshness checked again at the decision clock. A neutral/absent signal
    # is not an opposite EMA crossover. Strict EMA relation, not RSI, exits.
    if not signal or signal.get("contiguous_session_bars",0)<30:
        return None
    stamp=signal.get("last_observed_utc")
    fast,slow=signal.get("ema9"),signal.get("ema21")
    if not stamp or fast is None or slow is None:
        return None
    age=(now-ao.timestamp(stamp)).total_seconds()
    if not 60<=age<=90:
        return None
    return "UP" if fast>slow else "DOWN" if fast<slow else None


def evaluate(row,now,mark,signal=None):
    """Return (trigger, state updates). No future quote or synthetic fill."""
    cfg=row["config"]
    mode=cfg.get("exit_mode","target_stop")  # legacy active rows keep semantics
    deadline=ao.timestamp(row["hold_deadline_utc"])
    if now>=deadline:
        return "maximum_hold",{}
    updates={}
    value=mark.get("mark_net_inr") if mark else None
    if value is not None:
        updates.update(mark)
        previous=row.get("peak_net_inr")
        peak=max(value,previous) if previous is not None else value
        updates["peak_net_inr"]=peak
        stop=min(row["risk_budget_inr"],cfg.get("stop_net",row["risk_budget_inr"]))
        if value<=-stop:
            return "loss_mark",updates
        if mode=="target_stop" and value>=cfg["target_net"]:
            return "target_mark",updates
        if mode in ("trailing","adaptive"):
            armed=row.get("trail_armed",False) or peak>=cfg["target_net"]
            updates["trail_armed"]=armed
            if armed:
                floor=max(0.,peak-cfg.get("trail_net",50.))
                updates["trail_floor_inr"]=floor
                if value<=floor:
                    return "trailing_stop",updates
    if mode in ("signal_reversal","adaptive"):
        current=ema_direction(signal,now)
        if current:
            updates["latest_ema_direction"]=current
        entry=row.get("source",{}).get("direction")
        if current in ("UP","DOWN") and entry in ("UP","DOWN") and current!=entry:
            return "signal_reversal",updates
    if mode=="adaptive":
        bad=value is None or bool(mark.get("liquidity_bad",False))
        if bad:
            since=row.get("liquidity_bad_since_utc") or paper._iso(now)
            updates["liquidity_bad_since_utc"]=since
            if (now-ao.timestamp(since)).total_seconds()>=cfg.get("liquidity_grace_seconds",20):
                return "liquidity_deterioration",updates
        else:
            updates["liquidity_bad_since_utc"]=None
    return None,updates
