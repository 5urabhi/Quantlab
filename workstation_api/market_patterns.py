"""Rolling, source-verified intraday market context (not a trading signal).

Original Dhan IDX_I receipts are the historical baseline. Live observations
are read from the same shared SQLite library; no second price store or socket.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from statistics import mean, median
from threading import Event, RLock, Thread
from zoneinfo import ZoneInfo
import csv
import io
import json
import math
import os
import sqlite3
import time
import uuid

from . import cockpit_sources, intraday_parquet, live_market, service, dhan_auth

IST = ZoneInfo("Asia/Kolkata")
MINUTES = 375
HORIZONS = (1, 3, 5, 10, 15, 30, 60)
POINTS = (50, 100, 200, 300, 500, 750, 1000, 1500)
PERCENT = (.25, .5, .75, 1, 1.5, 2)
WINDOWS = (10, 20, 60, 252)
LOCK = RLock()
CACHE = {}
SYNC_LOCK = RLock()
SYNC_STOP = Event()
SYNC_WAKE = Event()
SYNC_THREAD = None
SYNC_STATE = {"state": "idle", "last_attempt_utc": None, "message": ""}
SYNC_LAST = {}


def _minute(stamp):
    local = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(IST)
    return local.date().isoformat(), local.hour * 60 + local.minute - 555


def _rate(n, total):
    return 100 * n / total if total else None


def _stats(values):
    if not values:
        return {"n": 0, "mean": None, "median": None, "p10": None,
                "p25": None, "p75": None, "p90": None, "p95": None, "max": None}
    values = sorted(values)

    def q(p):
        x = (len(values) - 1) * p
        a, b = int(x), math.ceil(x)
        return values[a] + (values[b] - values[a]) * (x - a)

    return {"n": len(values), "mean": mean(values), "median": median(values),
            "p10": q(.1), "p25": q(.25), "p75": q(.75), "p90": q(.9),
            "p95": q(.95), "max": values[-1]}


def _receipt(path, metadata):
    raw = path.read_bytes()
    if len(raw) > cockpit_sources.MAX_FILE_BYTES:
        raise ValueError("Original source exceeds byte limit")
    if sha256(raw).hexdigest() != metadata["sha256"]:
        raise ValueError("Original source SHA-256 mismatch")
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    if not {"datetime", "open", "high", "low", "close", "volume"}.issubset(reader.fieldnames or []):
        raise ValueError("Invalid original candle headers")
    rows, previous = {}, ""
    count = 0
    for row in reader:
        stamp, day, o, h, l, c, _ = intraday_parquet._decode(row)
        if stamp <= previous:
            raise ValueError("Repeated or unsorted source timestamps")
        previous = stamp
        count += 1
        _, minute = _minute(stamp)
        if 0 <= minute < MINUTES:
            rows.setdefault(day, {})[minute] = (o, h, l, c)
    if count != metadata["row_count"]:
        raise ValueError("Original source row count mismatch")
    return rows


def _history(identity, today):
    """Memoize verified originals by source fingerprint; newest receipt wins overlaps."""
    start = today - timedelta(days=365)
    candidates = []
    for path, manifest, meta in cockpit_sources._candidates(identity):
        try:
            if date.fromisoformat(meta["to_exclusive"]) <= start:
                continue
            if date.fromisoformat(meta["from_inclusive"]) > today:
                continue
        except (KeyError, ValueError, TypeError):
            # Legacy manifests may lack requested bounds; observed rows still count.
            pass
        try:
            candidates.append((path, manifest, meta, path.stat(), manifest.stat()))
        except OSError:
            continue
    candidates.sort(key=lambda x: (str(x[2].get("retrieved_utc", "")), str(x[0])), reverse=True)
    fingerprint = (today, str(service.DATA), tuple(
        (str(p), s.st_size, s.st_mtime_ns, s.st_ctime_ns, m.st_mtime_ns,
         m.st_ctime_ns, d["sha256"]) for p, _, d, s, m in candidates))
    with LOCK:
        cached = CACHE.get(identity)
        if cached and cached[0] == fingerprint:
            return cached[1]
        days = defaultdict(dict)
        rejected, conflicts, verified, used_bytes = 0, 0, 0, 0
        coverage = []
        omitted = 0
        for path, _, meta, stat, _ in candidates:
            if verified + rejected >= 512 or used_bytes + stat.st_size > 300 * 1024 * 1024:
                omitted += 1
                continue
            used_bytes += stat.st_size
            try:
                values = _receipt(path, meta)
            except (ValueError, OSError, UnicodeError, csv.Error):
                rejected += 1
                continue
            verified += 1
            try:
                coverage.append((date.fromisoformat(meta["from_inclusive"]),
                                 date.fromisoformat(meta["to_exclusive"])))
            except (KeyError, ValueError, TypeError):
                pass
            for day, bars in values.items():
                if not start.isoformat() <= day <= today.isoformat():
                    continue
                for minute, bar in bars.items():
                    if minute in days[day] and days[day][minute] != bar:
                        conflicts += 1
                    days[day].setdefault(minute, bar)
        completed = {d: bars for d, bars in days.items()
                     if d < today.isoformat() and len(bars) == MINUTES}
        result = {"days": dict(days), "complete": completed, "coverage": coverage,
                  "baseline": baseline(completed, days),
                  "verified_receipts": verified, "rejected_receipts": rejected,
                  "omitted_receipts": omitted, "overlap_revisions": conflicts}
        CACHE[identity] = (fingerprint, result)
        return result


def _session(bars):
    keys = sorted(bars)
    if not keys:
        return None
    seq = [bars[k] for k in keys]
    o = bars[0][0] if 0 in bars else None
    h, l, c = max(x[1] for x in seq), min(x[2] for x in seq), seq[-1][3]
    return {"open": o, "high": h, "low": l, "close": c, "range": h-l,
            "range_pct": 100*(h-l)/o if o else None,
            "up": h-o if o else None, "down": o-l if o else None,
            "net": c-o if o else None, "bars": len(keys), "last_minute": keys[-1],
            "missing_prefix_bars": keys[-1]+1-len(keys)}


def conditional_patterns(complete):
    """Fixed descriptive rules, first qualifying trigger per direction/session.

    Fit range thresholds on the first 70% of sessions only; report the
    remaining chronological sample separately. No strategy selection or fees.
    """
    dates = sorted(complete)
    split = int(len(dates)*.7)
    if split < 20 or len(dates)-split < 5:
        return {"state":"insufficient_sessions","development_sessions":split,
                "evaluation_sessions":len(dates)-split,"rows":[]}
    development = dates[:split]
    evaluation = dates[split:]
    # Percent-of-open range threshold at minute 59 from development only.
    def prefix_range(bars,k):
        values = [bars[i] for i in range(k+1)]
        return 100*(max(v[1] for v in values)-min(v[2] for v in values))/bars[0][0]
    high_range = _stats([prefix_range(complete[d],59) for d in development])["p90"]
    rows = []
    for cohort, sample in (("development",development),("evaluation",evaluation)):
        for kind in ("open_move_0_5pct","five_consecutive_candles","prior_high_low_break","wide_first_hour"):
            for horizon in (5,15,30,60):
                outcomes = []
                for day in sample:
                    bars = complete[day]
                    op = bars[0][0]
                    idx = dates.index(day)
                    prev = complete[dates[idx-1]] if idx else None
                    prev_high = max(x[1] for x in prev.values()) if prev else None
                    prev_low = min(x[2] for x in prev.values()) if prev else None
                    for i in range(4, MINUTES-horizon):
                        side = 0
                        close = bars[i][3]
                        if kind == "open_move_0_5pct":
                            r = close/op-1
                            side = 1 if r >= .005 else -1 if r <= -.005 else 0
                        elif kind == "five_consecutive_candles":
                            signs = [bars[j][3]-bars[j][0] for j in range(i-4,i+1)]
                            side = 1 if min(signs)>0 else -1 if max(signs)<0 else 0
                        elif kind == "prior_high_low_break" and prev_high is not None:
                            side = 1 if close > prev_high else -1 if close < prev_low else 0
                        elif kind == "wide_first_hour" and i==59 and prefix_range(bars,i)>=high_range:
                            side = 1 if close>op else -1 if close<op else 0
                        if not side:
                            continue
                        entry = bars[i+1][0]
                        future = [bars[j] for j in range(i+1,i+horizon+1)]
                        end = future[-1][3]
                        hi,lo = max(x[1] for x in future),min(x[2] for x in future)
                        mfe = max(0,hi-entry if side>0 else entry-lo)
                        mae = max(0,entry-lo if side>0 else hi-entry)
                        outcomes.append((side*(end-entry),mfe,mae))
                        break
                n=len(outcomes)
                wins=sum(x[0]>0 for x in outcomes)
                # Wilson interval for session-level descriptive outcome fraction.
                interval=None
                if n:
                    p=wins/n; z=1.96; den=1+z*z/n
                    center=(p+z*z/(2*n))/den
                    half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
                    interval=[100*max(0,center-half),100*min(1,center+half)]
                rows.append({"cohort":cohort,"pattern":kind,"horizon":horizon,"n":n,
                             "continuation_pct":_rate(wins,n),"reversal_pct":_rate(sum(x[0]<0 for x in outcomes),n),
                             "continuation_interval_pct":interval,
                             "mean_signed_points":mean([x[0] for x in outcomes]) if n else None,
                             "median_mfe":median([x[1] for x in outcomes]) if n else None,
                             "median_mae":median([x[2] for x in outcomes]) if n else None})
    return {"state":"descriptive","development_sessions":len(development),
            "evaluation_sessions":len(evaluation),"evaluation_from":evaluation[0],
            "development_first_hour_p90_pct":high_range,"rows":rows}


def baseline(complete, observed=None):
    """Complete regular sessions only. Forward windows overlap: not independent trades."""
    dates = sorted(complete)
    summaries = [{"date": d, **_session(complete[d])} for d in dates]
    n = len(summaries)
    windows = []
    for size in WINDOWS:
        subset = summaries[-size:]
        windows.append({"window": size, "sessions": len(subset),
                        "range": _stats([s["range"] for s in subset]),
                        "range_pct": _stats([s["range_pct"] for s in subset]),
                        "abs_open_close": _stats([abs(s["net"]) for s in subset])})
    thresholds = []
    for p in POINTS:
        thresholds.append({"points": p, "n": n,
                           "range_pct": _rate(sum(s["range"] >= p for s in summaries), n),
                           "either_pct": _rate(sum(max(s["up"], s["down"]) >= p for s in summaries), n),
                           "up_pct": _rate(sum(s["up"] >= p for s in summaries), n),
                           "down_pct": _rate(sum(s["down"] >= p for s in summaries), n),
                           "both_pct": _rate(sum(min(s["up"], s["down"]) >= p for s in summaries), n)})
    percent_thresholds = [{"threshold_pct": p, "n": n,
                          "range_pct": _rate(sum(s["range_pct"] >= p for s in summaries), n),
                          "either_pct": _rate(sum(100*max(s["up"], s["down"])/s["open"] >= p for s in summaries), n)}
                         for p in PERCENT]
    # Compare previous observed complete close; do not bridge a known partial session.
    gaps = []
    ordered = sorted(observed if observed is not None else complete)
    for prev, day in zip(ordered, ordered[1:]):
        if prev not in complete or day not in complete:
            continue
        # No exchange calendar here; label as previous observed session.
        if (date.fromisoformat(day)-date.fromisoformat(prev)).days > 4:
            continue
        previous = complete[prev][374][3]
        s = _session(complete[day])
        gap = s["open"] - previous
        gaps.append((gap, s["low"] <= previous <= s["high"]))
    gap_fill = []
    for p in (100, 200, 300, 500, 750):
        for side in ("either", "up", "down"):
            selection = [fill for g, fill in gaps if abs(g) >= p and
                         (side == "either" or (g > 0 if side == "up" else g < 0))]
            gap_fill.append({"points": p, "side": side, "n": len(selection),
                             "fill_pct": _rate(sum(selection), len(selection))})
    horizons = []
    for h in HORIZONS:
        moves = [bars[i+h][3] - bars[i][3]
                 for bars in complete.values() for i in range(MINUTES-h)]
        horizons.append({"minutes": h, "n": len(moves),
                         "absolute_move": _stats([abs(v) for v in moves]),
                         "up_pct": _rate(sum(v > 0 for v in moves), len(moves)),
                         "down_pct": _rate(sum(v < 0 for v in moves), len(moves)),
                         "move_50_pct": _rate(sum(abs(v) >= 50 for v in moves), len(moves)),
                         "move_100_pct": _rate(sum(abs(v) >= 100 for v in moves), len(moves)),
                         "move_200_pct": _rate(sum(abs(v) >= 200 for v in moves), len(moves))})
    time_buckets = []
    for i in range(0, MINUTES, 15):
        values = [max(bars[j][1] for j in range(i, i+15)) -
                  min(bars[j][2] for j in range(i, i+15)) for bars in complete.values()]
        minutes = 555+i
        time_buckets.append({"time_ist": f"{minutes//60:02d}:{minutes%60:02d}",
                             "range": _stats(values)})
    opening_patterns = []
    for size in (5, 15, 30):
        for h in (5, 15, 30):
            moves, signals = [], 0
            for bars in complete.values():
                high = max(bars[i][1] for i in range(size))
                low = min(bars[i][2] for i in range(size))
                for i in range(size, MINUTES-1):
                    close = bars[i][3]
                    side = 1 if close > high else -1 if close < low else 0
                    if side:
                        signals += 1
                        # Earliest possible index proxy entry is next bar open.
                        if i+h < MINUTES:
                            moves.append(side*(bars[i+h][3] - bars[i+1][0]))
                        break
            opening_patterns.append({"opening_minutes": size, "hold_minutes": h,
                                     "signals": signals, "n": len(moves),
                                     "positive_pct": _rate(sum(m > 0 for m in moves), len(moves)),
                                     "signed_points": _stats(moves)})
    return {"sessions": n, "first": dates[0] if n else None,
            "last": dates[-1] if n else None, "daily": summaries,
            "range": _stats([s["range"] for s in summaries]),
            "range_pct": _stats([s["range_pct"] for s in summaries]),
            "up": _stats([s["up"] for s in summaries]),
            "down": _stats([s["down"] for s in summaries]),
            "abs_open_close": _stats([abs(s["net"]) for s in summaries]),
            "bullish_pct": _rate(sum(s["net"] > 0 for s in summaries), n),
            "bearish_pct": _rate(sum(s["net"] < 0 for s in summaries), n),
            "windows": windows, "thresholds": thresholds, "percent_thresholds": percent_thresholds,
            "gap_fill": gap_fill, "horizons": horizons, "time_buckets": time_buckets,
            "opening_patterns": opening_patterns,
            "conditional": conditional_patterns(complete)}


def current_context(bars, complete):
    now = _session(bars)
    if now is None:
        return None
    n = len(complete)
    now["full_day_range_percentile"] = _rate(
        sum(_session(v)["range"] <= now["range"] for v in complete.values()), n)
    now["same_time_range"] = _stats([])
    now["same_time_percentile"] = None
    now["historical_remaining_excursion"] = _stats([])
    # Equal-clock comparison is only honest with an uninterrupted open-to-now prefix.
    k = now["last_minute"]
    if now["missing_prefix_bars"] == 0:
        ranges = []
        remaining = []
        for v in complete.values():
            prefix = [v[i] for i in range(k+1)]
            ranges.append(max(x[1] for x in prefix)-min(x[2] for x in prefix))
            if k < MINUTES-1:
                future = [v[i] for i in range(k+1, MINUTES)]
                c = v[k][3]
                remaining.append(max(max(x[1] for x in future)-c,
                                     c-min(x[2] for x in future)))
        now["same_time_range"] = _stats(ranges)
        now["same_time_percentile"] = _rate(sum(r <= now["range"] for r in ranges), n)
        now["historical_remaining_excursion"] = _stats(remaining)
    return now


def report(identity="INDEX:BANKNIFTY", now=None):
    if identity not in cockpit_sources.INDEX_IDENTITIES:
        raise ValueError("Select a supported original spot index")
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(IST).date()
    source = _history(identity, today)
    day = today.isoformat()
    bars = dict(source["days"].get(day, {}))
    local = now.astimezone(IST)
    minute_now = local.hour*60+local.minute-555
    bars = {i: bar for i, bar in bars.items() if i < minute_now}
    historical_count = len(bars)
    live_count = 0
    live_error = None
    last = None
    try:
        live = live_market.minute_series(identity, limit=500)
        for row in live["rows"]:
            d, i = _minute(row["timestamp_utc"])
            if d == day and 0 <= i < min(MINUTES, minute_now):
                if i not in bars:
                    bars[i] = tuple(row[x] for x in ("open", "high", "low", "close"))
                    live_count += 1
    except (ValueError, OSError, sqlite3.Error) as exc:
        live_error = type(exc).__name__
    current = current_context(bars, source["complete"])
    if current:
        last = datetime(today.year, today.month, today.day, 9, 15, tzinfo=IST) + timedelta(minutes=current["last_minute"]+1)
        current.update({"as_of_ist": last.isoformat(),
                        "age_seconds": max(0, (now-last).total_seconds()),
                        "historical_bars": historical_count, "live_observed_bars": live_count,
                        "state": "recent_completed_bar" if 0 <= (now-last).total_seconds() <= 120
                        and 0 < minute_now < MINUTES else "saved_or_stale",
                        "gap": None})
        previous_dates = sorted(d for d in source["days"] if d < day)
        if current["open"] is not None and previous_dates:
            p = previous_dates[-1]
            if p in source["complete"] and (today-date.fromisoformat(p)).days <= 4:
                current["gap"] = current["open"] - source["complete"][p][374][3]
    historical_observed = [d for d in source["days"] if d < day]
    return {"identity": identity, "date_ist": day, "generated_utc": now.isoformat(),
            "requested_calendar_days": 365, "requested_start": (today-timedelta(days=365)).isoformat(),
            "source": "Original Dhan IDX_I 1-minute receipts; current observed shared minute bars",
            "baseline": source["baseline"], "current": current,
            "coverage": {"observed_prior_sessions": len(historical_observed),
                         "excluded_partial_sessions": len(historical_observed)-len(source["complete"]),
                         "verified_receipts": source["verified_receipts"],
                         "rejected_receipts": source["rejected_receipts"],
                         "omitted_receipts": source["omitted_receipts"],
                         "overlap_revisions": source["overlap_revisions"],
                         "live_read_error": live_error},
            "sync": sync_status(),
            "warning": "Historical baseline uses only 375 observed regular-session minutes, excluding today. Missing whole sessions and exchange holidays are not inferred. Overlapping receipts use the newest verified value. Live bars can miss ticks; incomplete ranges are lower bounds. Gap fills reference the prior observed complete close. Forward windows overlap, and opening-breakout results are descriptive index proxies, not executable option returns, probabilities of profitable trades or signals."}


# Optional, explicit persisted consent for bounded read-only history sync.
def _settings_path():
    return Path(service.DATA) / "dhan" / "market_pattern_sync.json"


def _enabled():
    try:
        return json.loads(_settings_path().read_text(encoding="utf-8")).get("enabled") is True
    except (ValueError, OSError, TypeError, AttributeError):
        return False


def sync_status():
    with SYNC_LOCK:
        return {"enabled": _enabled(), **SYNC_STATE}


def configure_sync(enabled):
    with SYNC_LOCK:
        path = _settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name+"."+uuid.uuid4().hex+".tmp")
        try:
            temp.write_text(json.dumps({"enabled": enabled}), encoding="utf-8")
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)
        SYNC_STATE.update(state="idle" if enabled else "disabled",
                          message="Sync enabled; uses existing Dhan credentials." if enabled else "Automatic historical downloads disabled.")
        if enabled:
            SYNC_LAST.clear()
    SYNC_WAKE.set()
    return sync_status()


def missing_windows(start, stop, coverage):
    """Request uncovered calendar intervals only, split at provider's 90-day cap."""
    cursor = start
    result = []
    for a, b in sorted(coverage):
        if b <= cursor or a >= stop:
            continue
        while cursor < min(a, stop):
            end = min(a, stop, cursor+timedelta(days=90))
            result.append((cursor, end))
            cursor = end
        cursor = min(stop, max(cursor, b))
    while cursor < stop:
        end = min(stop, cursor+timedelta(days=90))
        result.append((cursor, end))
        cursor = end
    return result


def _sync_once():
    if not _enabled():
        return
    now = datetime.now(IST)
    today = now.date()
    # Request only already closed regular sessions; after 16:00 allow today.
    stop = today+timedelta(days=1) if now.hour >= 16 and today.weekday() < 5 else today
    start = today-timedelta(days=365)
    identity = "INDEX:BANKNIFTY"
    key = (str(service.DATA), stop)
    with SYNC_LOCK:
        if time.monotonic()-SYNC_LAST.get(key, -100000) < 1800:
            return
        SYNC_LAST.clear()
        SYNC_LAST[key] = time.monotonic()
        SYNC_STATE.update(state="checking", last_attempt_utc=datetime.now(timezone.utc).isoformat(), message="Checking verified original receipts.")
    try:
        source = _history(identity, today)
        windows = missing_windows(start, stop, source["coverage"])
        # Do not repeatedly request windows consisting only of weekends.
        windows = [(a, b) for a, b in windows if any(
            (a+timedelta(days=i)).weekday() < 5 for i in range((b-a).days))]
        if windows:
            profile = dhan_auth.check_profile()
            if not profile.get("ok"):
                raise ValueError("Dhan historical access needs verification in Connections.")
            for a, b in windows[:5]:
                if SYNC_STOP.is_set() or not _enabled():
                    return
                with SYNC_LOCK:
                    SYNC_STATE.update(state="downloading", message=f"Original BANKNIFTY history {a} to {b} (exclusive).")
                cockpit_sources.download_spot(identity, a.isoformat(), b.isoformat())
                # Invalidate history after each completed receipt.
                with LOCK:
                    CACHE.pop(identity, None)
        with SYNC_LOCK:
            SYNC_STATE.update(state="checked", message="Verified receipt windows checked; missing minute/session coverage remains visible.")
    except Exception as exc:
        # No provider response or credentials returned; retries are bounded.
        with SYNC_LOCK:
            SYNC_STATE.update(state="blocked", message=f"History sync unavailable ({type(exc).__name__}); inspect Dhan connection and existing receipt coverage.")


def _sync_worker():
    while not SYNC_STOP.is_set():
        _sync_once()
        SYNC_WAKE.wait(60)
        SYNC_WAKE.clear()


def start_sync():
    global SYNC_THREAD
    with SYNC_LOCK:
        if SYNC_THREAD and SYNC_THREAD.is_alive():
            return
        SYNC_STOP.clear()
        SYNC_WAKE.clear()
        SYNC_THREAD = Thread(target=_sync_worker, daemon=True, name="market-pattern-history")
        SYNC_THREAD.start()


def stop_sync():
    SYNC_STOP.set()
    SYNC_WAKE.set()
