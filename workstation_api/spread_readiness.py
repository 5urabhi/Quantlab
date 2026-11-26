"""Read-only, latest-observed depth screening before a fixed-clock study.

Ranking is a research-data diagnostic, not a directional signal or a live
trade recommendation. Never substitute a contract inside a historical run.
"""
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
import sqlite3
from time import monotonic

from . import depth_replay as replay, liquidity_spreads as fees, paper_execution as paper

MAX_CANDIDATES=400
MAX_LOTS=10
TOP_RESULTS=20
SCAN_SECONDS=8


def _bounds(day, now):
    chosen=date.fromisoformat(day)
    if chosen>now.astimezone(paper.IST).date():
        raise ValueError("Choose an observed date")
    start=datetime.combine(chosen,time(9,15),paper.IST).astimezone(timezone.utc)
    close=datetime.combine(chosen,time(15,30),paper.IST).astimezone(timezone.utc)
    return start,min(close,now)


def _inventory(day, identities, now, include_candidates, candidate_ids=None):
    """Single read transaction; actual saved timestamp inventory, not fills."""
    start,end=_bounds(day,now)
    elapsed=max(0,int((end-start).total_seconds()))
    if elapsed<=0:
        return [],elapsed,False
    # The same complete-second denominator as the speed-study inventory.
    limits=(paper._iso(start),paper._iso(start+timedelta(seconds=elapsed)))
    try:
        with closing(replay.ao._read_database()) as db:
            db.execute("BEGIN")
            # Timestamp inventory is ranked before fetching any book JSON.
            base="""SELECT identity,MAX(received_utc),COUNT(*),
                COUNT(DISTINCT substr(received_utc,1,19))
                FROM live_depth_books WHERE received_utc>=? AND received_utc<?"""
            selected=db.execute(base+" AND identity IN ("+
                ",".join("?" for _ in identities)+") GROUP BY identity",
                (*limits,*identities)).fetchall() if identities else []
            candidates=[]
            truncated=False
            if include_candidates and candidate_ids is not None:
                # Indexed reads for the current watchlist; retain completed
                # results if the time budget is exhausted.
                deadline=monotonic()+SCAN_SECONDS
                db.set_progress_handler(lambda:int(monotonic()>deadline),10000)
                try:
                    for identity in candidate_ids[:MAX_CANDIDATES]:
                        if monotonic()>deadline:
                            truncated=True
                            break
                        candidates.extend(db.execute(base+" AND identity=? GROUP BY identity",(*limits,identity)).fetchall())
                except sqlite3.OperationalError as exc:
                    if "interrupted" not in str(exc):
                        raise
                    truncated=True
                finally:
                    db.set_progress_handler(None,0)
                truncated=truncated or len(candidate_ids)>MAX_CANDIDATES
            elif include_candidates:
                # The existing index is identity-first. A very large archive
                # may require a long covering-index scan. Bound that optional
                # scan rather than starving the live writer.
                deadline=monotonic()+SCAN_SECONDS
                db.set_progress_handler(lambda:int(monotonic()>deadline),10000)
                try:
                    candidates=db.execute(base+""" GROUP BY identity
                        ORDER BY 4 DESC,identity LIMIT ?""",(*limits,MAX_CANDIDATES+1)).fetchall()
                    truncated=len(candidates)>MAX_CANDIDATES
                except sqlite3.OperationalError as exc:
                    if "interrupted" not in str(exc):
                        raise
                    truncated=True
                finally:
                    db.set_progress_handler(None,0)
            by_id={row[0]:row for row in candidates[:MAX_CANDIDATES]}
            by_id.update({row[0]:row for row in selected})
            output=[]
            for identity,stamp,count,seconds in by_id.values():
                raw=db.execute("""SELECT book_json,packet_pair_sha256
                    FROM live_depth_books WHERE identity=? AND received_utc=?
                    LIMIT 1""",(identity,stamp)).fetchone()
                item=None
                if raw:
                    original=replay.spread_scanner._original_book(identity,stamp,*raw)
                    if original:
                        item=replay.studio._book_row(*original)
                        if item and (not paper._regular(item["stamp"]) or
                            item["stamp"]>=paper._close(item["stamp"],item["expiry"])):
                            item=None
                        if item:
                            item={**item,"digest":raw[1]}
                output.append(dict(identity=identity,received_utc=stamp,
                    saved_receipts=count,observed_seconds=seconds,
                    coverage_pct=round(100*seconds/elapsed,2) if elapsed else None,
                    book=item))
            return output,elapsed,truncated
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc) or "unable to open database file" in str(exc):
            return [],elapsed,False
        raise


def _entry_requirements(strategy, books, lots, participation_pct, slippage_bps, broker_profile):
    # Identical displayed-depth walk and risk proxy used by depth_replay.
    actions=("BUY",) if strategy=="LONG_OPTION" else replay.studio.STRATEGIES[strategy]["actions"]
    units=lots*books[0]["lot_size"]
    entries=[replay._execute(row,action,units,participation_pct,slippage_bps,broker_profile)
             for row,action in zip(books,actions)]
    if any(row["displayed_fill_units"]!=units for row in entries):
        return None
    return replay._entry_risk(strategy,books,actions,entries,units)[2]


def _screen(strategy, rows, capital, lots, participation_pct, slippage_bps, broker_profile, max_skew_seconds):
    books=[row.get("book") for row in rows]
    coverage=min((row.get("coverage_pct") or 0 for row in rows),default=0)
    result={"identities":[row["identity"] for row in rows],"minimum_leg_coverage_pct":coverage,
        "one_lot_required_inr":None,"requested_lots_required_inr":None,
        "max_affordable_lots":0,"max_lots_tested":MAX_LOTS,"lot_size":None,
        "spread_bps":None,"status":"missing_or_invalid_original_book","reason":"No verified original book for at least one selected leg"}
    if not books or any(book is None for book in books):
        return result
    if strategy!="LONG_OPTION":
        try:
            replay.studio._validate_structure(strategy,books)
        except ValueError:
            return {**result,"status":"invalid_basket","reason":"Original contract terms do not form the selected spread"}
    stamps=[book["stamp"] for book in books]
    result.update(lot_size=books[0]["lot_size"],
        received_utc=min(stamps).isoformat(),latest_leg_skew_seconds=(max(stamps)-min(stamps)).total_seconds(),
        spread_bps=round(sum(book["spread_bps"] for book in books)/len(books),2))
    if result["latest_leg_skew_seconds"]>max_skew_seconds:
        return {**result,"status":"latest_legs_not_synchronized","reason":"Latest saved legs exceed the requested receipt skew; budget not evaluated"}
    required={n:_entry_requirements(strategy,books,n,participation_pct,slippage_bps,broker_profile)
              for n in range(1,MAX_LOTS+1)}
    affordable=[n for n,v in required.items() if v is not None and v<=capital]
    result.update(one_lot_required_inr=required[1],requested_lots_required_inr=required[lots],
        max_affordable_lots=max(affordable,default=0),
        affordable_lot_options=affordable)
    if required[lots] is None:
        result.update(status="insufficient_displayed_depth",reason="Requested whole lots exceed haircut displayed entry depth")
    elif required[lots]>capital:
        result.update(status="over_budget",reason="Modeled entry risk exceeds the research budget")
    else:
        result.update(status="ready",reason="Latest observed entry fits modeled depth and budget; historical paths and exit remain unverified")
    return result


def inspect(*,day,strategy,identities,capital=17000.,lots=3,participation_pct=25.,
            slippage_bps=5.,broker_profile="zerodha",max_skew_seconds=2.,now=None):
    now=now or paper._now()
    if strategy not in replay.STRATEGIES or broker_profile not in fees.BROKER_PROFILES:
        raise ValueError("Unsupported strategy or fee profile")
    actions=("BUY",) if strategy=="LONG_OPTION" else replay.studio.STRATEGIES[strategy]["actions"]
    if len(identities)!=len(actions) or len(set(identities))!=len(identities) or any(not fees.ID.fullmatch(i) for i in identities):
        raise ValueError("Select exact distinct identities in leg order")
    if type(lots) is not int or not 1<=lots<=MAX_LOTS:
        raise ValueError("Choose 1–10 lots")
    for value,lo,hi,label in ((capital,1000,1e7,"capital"),(participation_pct,1,100,"participation"),
        (slippage_bps,0,500,"slippage"),(max_skew_seconds,0,30,"leg skew")):
        paper._check(value,lo,hi,label)
    inventory,elapsed,truncated=_inventory(day,identities,now,strategy=="LONG_OPTION")
    lookup={row["identity"]:row for row in inventory}
    selected=[lookup.get(i,{"identity":i,"book":None}) for i in identities]
    screen=_screen(strategy,selected,capital,lots,participation_pct,slippage_bps,broker_profile,max_skew_seconds)
    candidates=[]
    if strategy=="LONG_OPTION":
        for row in inventory:
            if row["book"] is None:
                continue
            book=row["book"]
            candidate=_screen(strategy,[row],capital,lots,participation_pct,slippage_bps,broker_profile,max_skew_seconds)
            if candidate["max_affordable_lots"]<1:
                continue
            candidate.update(identity=row["identity"],strike=book["strike"],option_type=book["option_type"],
                latest_book_age_seconds=round(max(0.,(now-book["stamp"]).total_seconds()),2),
                expiry=book["expiry"],bid=book["bid"],ask=book["ask"],saved_receipts=row["saved_receipts"],
                observed_seconds=row["observed_seconds"],coverage_pct=row["coverage_pct"])
            candidates.append(candidate)
        # First favor requested size, then actual timestamp coverage and
        # tighter normalized spread. No profit-based or future-fill ranking.
        candidates.sort(key=lambda r:(r["status"]!="ready",-r["minimum_leg_coverage_pct"],
            r["spread_bps"],-r["saved_receipts"],r["identity"]))
    return {"day_ist":day,"cutoff_utc":paper._iso(now),"capital":capital,"lots":lots,
        "elapsed_seconds":elapsed,"scanned_contracts":len(inventory),"scan_truncated":truncated,
        "selected":screen,"affordable_candidates":len(candidates),"candidates":candidates[:TOP_RESULTS],
        "warning":"Latest saved original books for this day, not live quotes or verified fills. Coverage counts saved timestamps across elapsed session, not independently verified books for every second or guaranteed sampling. A bounded scan may omit candidates. Historical candidates are in-sample research screens; validate on later data. Multi-leg budget is a risk proxy, not broker margin."}


def automatic(*,day,capital=17000.,lots=3,participation_pct=25.,
              slippage_bps=5.,broker_profile="zerodha",expiry="",side="ALL",
              search="",now=None):
    """Select an affordable exact research contract before launching replay.

    Today's subscribed identities are an efficient, bounded indexed universe.
    Older dates fall back to the bounded saved-date scan. No historical outcome
    or future fill is used in ranking; same-day selection is still in-sample.
    """
    from . import auto_option_depth as recorder
    now=now or paper._now()
    if broker_profile not in fees.BROKER_PROFILES or side not in ("ALL","CE","PE"):
        raise ValueError("Unsupported fee profile or option side")
    if expiry and date.fromisoformat(expiry).isoformat()!=expiry:
        raise ValueError("Choose an ISO expiry")
    if type(lots) is not int or not 1<=lots<=MAX_LOTS:
        raise ValueError("Choose 1–10 maximum lots")
    for value,lo,hi,label in ((capital,1000,1e7,"capital"),(participation_pct,1,100,"participation"),
                              (slippage_bps,0,500,"slippage")):
        paper._check(value,lo,hi,label)
    if not isinstance(search,str) or len(search)>80:
        raise ValueError("Search is limited to 80 characters")
    query=search.strip().lower()
    candidate_ids=None
    scope="saved_date_inventory"
    if day==now.astimezone(paper.IST).date().isoformat():
        with recorder.LOCK:
            ids=sorted({row["identity"] for row in recorder.STATE.get("contracts",[])
                        if fees.ID.fullmatch(row.get("identity") or "")})
        if ids:
            candidate_ids=ids
            scope="current_depth_watchlist"
    inventory,elapsed,truncated=_inventory(day,[],now,True,candidate_ids)
    rejected={}
    def reject(reason):
        rejected[reason]=rejected.get(reason,0)+1
    candidates=[]
    for row in inventory:
        book=row["book"]
        if book is None:
            reject("missing_or_invalid_original_book")
            continue
        if (expiry and expiry!=book["expiry"]) or (side!="ALL" and side!=book["option_type"]) or (
            query and query not in f'{book["identity"]} {book["strike"]:g} {book["option_type"]} {book["expiry"]}'.lower()):
            reject("outside_selected_filters")
            continue
        screen=_screen("LONG_OPTION",[row],capital,lots,participation_pct,slippage_bps,broker_profile,2.)
        # Both entry budget and immediate displayed exit capacity must pass.
        # This is not evidence that a later exit will execute.
        actual=0
        for n in reversed(screen.get("affordable_lot_options",[])):
            if n>lots:
                continue
            units=n*book["lot_size"]
            close=replay._execute(book,"SELL",units,participation_pct,slippage_bps,broker_profile)
            if close["displayed_fill_units"]==units:
                actual=n
                break
        if not actual:
            reject("budget_or_roundtrip_depth")
            continue
        if not row["observed_seconds"]:
            reject("no_observed_seconds")
            continue
        cost=_entry_requirements("LONG_OPTION",[book],actual,participation_pct,slippage_bps,broker_profile)
        candidates.append({**screen,"identity":row["identity"],"strike":book["strike"],
            "option_type":book["option_type"],"expiry":book["expiry"],"bid":book["bid"],"ask":book["ask"],
            "saved_receipts":row["saved_receipts"],"observed_seconds":row["observed_seconds"],
            "coverage_pct":row["coverage_pct"],"latest_book_age_seconds":round(max(0.,(now-book["stamp"]).total_seconds()),2),
            "study_lots":actual,"study_entry_inr":cost})
    # For a data-availability diagnostic, evidence density outranks sizing.
    # Prefer a narrow spread and affordable whole lots, never historical P&L.
    candidates.sort(key=lambda c:(-c["observed_seconds"],c["spread_bps"],
                    -c["study_lots"],c["latest_book_age_seconds"],c["identity"]))
    pick=candidates[0] if candidates else None
    return {"day_ist":day,"cutoff_utc":paper._iso(now),"capital":capital,"lots":lots,
        "elapsed_seconds":elapsed,"scanned_contracts":len(inventory),"scan_truncated":truncated,
        "scope":scope,"affordable_candidates":len(candidates),"candidates":candidates[:TOP_RESULTS],
        "automatic_pick":pick,"rejections":rejected,
        "reason":"selected_by_saved_coverage_spread_and_affordability" if pick else "no_eligible_recorded_contract",
        "warning":"Selection uses the chosen date's observed evidence, not a buy signal or unbiased backtest. "
          "Low coverage and missing future receipts remain unscored. Same-book exit capacity is not an actual fill. "
          "The scan is bounded; a partial scan may omit better-covered candidates."}
