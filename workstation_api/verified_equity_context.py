"""Read-only daily equity research adapter over the existing original candle cache.

No new price store, DB mutation, provider requests, downloads, or receipt repair.
Every parsed original file is checked against its own identity, hash and row count.
"""
from collections import Counter
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import json
import re
import numpy as np
import pandas as pd
from . import service, dhan_checkpoint, nse_session_policy as sessions

MIN_EQUITIES=20
MAX_FILE_BYTES=160*1024*1024
MAX_TOTAL_BYTES=2*1024*1024*1024
MAX_IDENTITIES=500
SID=re.compile(r"^[0-9]{1,12}$")


def _original_daily(path,identity,interval,stop,budget):
    if any(p.is_symlink() for p in (path,path.parent,path.parent.parent)):
        raise ValueError("Unsafe original equity path")
    source=path.with_suffix(".csv")
    if not source.is_file() or source.is_symlink():
        raise ValueError("Original equity CSV missing")
    meta=dhan_checkpoint._read_receipt(path,identity=identity,interval=interval)
    size=source.stat().st_size
    if not 0<size<=MAX_FILE_BYTES or size>budget[0]:
        raise ValueError("Original equity source exceeds bounded read")
    with source.open("rb") as f:
        payload=f.read(size+1)
    budget[0]-=len(payload)
    if len(payload)!=size or sha256(payload).hexdigest()!=meta["sha256"]:
        raise ValueError("Original equity source hash mismatch")
    frame=pd.read_csv(BytesIO(payload),usecols=["datetime","close"])
    if len(frame)!=meta["rows"]:
        raise ValueError("Original equity row count mismatch")
    clock=pd.to_datetime(frame["datetime"],utc=True,errors="raise").dt.tz_convert("Asia/Kolkata")
    close=pd.to_numeric(frame["close"],errors="raise")
    if clock.isna().any() or clock.duplicated().any() or not (np.isfinite(close)&(close>0)).all():
        raise ValueError("Invalid or duplicate original equity observations")
    frame=pd.DataFrame({"date":clock.dt.strftime("%Y-%m-%d"),"close":close,"clock":clock})
    frame=frame.loc[(frame["date"]<stop)&(clock.dt.weekday<5)].sort_values("clock")
    if interval==1:
        # Compare only scheduled continuous-trading minutes. Auction and
        # post-close prints are not missing CTS bars or official close proxies.
        minute=frame["clock"].dt.hour*60+frame["clock"].dt.minute
        days=frame["date"].unique()
        expected={d:sessions.cash_bank_minutes(d,identity) for d in days}
        close_minute=frame["date"].map(expected)+sessions.OPEN_MINUTE
        frame=frame.loc[(minute>=sessions.OPEN_MINUTE)&(minute<close_minute)&(frame["clock"].dt.second==0)&
                        (frame["clock"].dt.microsecond==0)&(frame["clock"].dt.nanosecond==0)]
        counts=frame.groupby("date").size().reindex(days,fill_value=0)
        required=pd.Series(expected).reindex(counts.index)
        complete=counts[counts==required].index
        series=frame.loc[frame["date"].isin(complete)].groupby("date")["close"].last()
        incomplete=int((counts!=required).sum())
    else:
        if frame["date"].duplicated().any():
            raise ValueError("Duplicate original daily trading dates")
        series=frame.set_index("date")["close"]
        incomplete=0
    return series.astype(float),{"sha256":meta["sha256"],"original_rows":len(clock),
                                "session_policy":sessions.BANK_POLICY if interval==1 else "native_daily",
                                "close_kind":"continuous_last_trade" if interval==1 else "provider_daily_close",
                                "scheduled_session_minute_counts":dict(Counter(str(v) for v in expected.values())) if interval==1 else {},
                                "observed_sessions":len(series),"incomplete_regular_sessions":incomplete,
                                "first_session":str(series.index.min()) if len(series) else None,
                                "last_session":str(series.index.max()) if len(series) else None}


def original_panel(stop,*,progress=None):
    """Aggregate verified daily/one-minute observations in memory by security ID.
    Native daily bars supplement earlier sessions; disagreeing overlap is excluded,
    not silently overwritten. Missing prices remain missing.
    """
    root=service.DATA/"dhan"/"history"/"NSE_EQ"
    meta={"source":"original_verified_equity_cache","state":"unavailable","sources":{},"rejected_sources":{},
          "source_origins":["original_Dhan_daily_and_complete_regular_1m"],"conflicting_daily_closes":0}
    if not root.is_dir() or any(p.is_symlink() for p in (root,root.parent,root.parent.parent)):
        meta["reason"]="Original NSE equity history directory missing or unsafe";return pd.DataFrame(),meta
    ids=sorted(p for p in root.iterdir() if p.is_dir() and not p.is_symlink() and SID.fullmatch(p.name)
               and ((p/"1m.json").is_file() or (p/"daily.json").is_file()))
    if len(ids)>MAX_IDENTITIES:
        meta["reason"]="Original equity universe exceeds bounded identity limit";return pd.DataFrame(),meta
    budget=[MAX_TOTAL_BYTES];series=[]
    for i,folder in enumerate(ids):
        identity="NSE_EQ:"+folder.name
        if progress and (i==0 or (i+1)%10==0 or i+1==len(ids)):
            progress(f"Verifying original stock history {i+1}/{len(ids)}")
        observations={}
        for stem,interval in (("1m",1),("daily",None)):
            path=folder/(stem+".json")
            if not path.is_file():continue
            key=identity+"/"+stem
            try:
                values,info=_original_daily(path,identity,interval,stop,budget)
                meta["sources"][key]=info
                observations[stem]=values
            except (OSError,ValueError,KeyError,TypeError,OverflowError,pd.errors.ParserError) as exc:
                meta["rejected_sources"][key]=str(exc)[:160]
        if not observations:continue
        minute=observations.get("1m",pd.Series(dtype=float))
        daily=observations.get("daily",pd.Series(dtype=float))
        aligned=pd.concat([minute.rename("minute"),daily.rename("daily")],axis=1)
        # CAS can produce a different official daily close from the last
        # continuous trade. Keep native daily data on CAS dates; never replace
        # a missing auction/daily close with the last continuous minute.
        cas=pd.Series([sessions.bank_cas_eligible(d,identity) for d in aligned.index],
                      index=aligned.index,dtype=bool)
        both=aligned.notna().all(axis=1)&~cas
        disagree=both & ~np.isclose(aligned["minute"],aligned["daily"],rtol=1e-7,atol=1e-5)
        meta["conflicting_daily_closes"]+=int(disagree.sum())
        meta["cas_native_daily_preferred_sessions"]=meta.get("cas_native_daily_preferred_sessions",0)+int((cas&aligned["daily"].notna()).sum())
        meta["cas_daily_missing_sessions"]=meta.get("cas_daily_missing_sessions",0)+int((cas&aligned["daily"].isna()).sum())
        values=aligned["minute"].mask(cas).combine_first(aligned["daily"]).mask(disagree).dropna()
        if len(values):series.append(values.rename(identity.replace(":","_")))
    frame=pd.concat(series,axis=1).sort_index() if series else pd.DataFrame()
    meta.update(state="loaded" if frame.shape[1]>=MIN_EQUITIES else "insufficient_verified_equities",
                nse_equity_columns=int(frame.shape[1]),discovered_identities=len(ids),
                verified_sources=len(meta["sources"]),bytes_verified_or_read=MAX_TOTAL_BYTES-budget[0],
                sessions=len(frame),first_session=str(frame.index.min()) if len(frame) else None,
                last_session=str(frame.index.max()) if len(frame) else None,
                original_rows_verified=sum(x["original_rows"] for x in meta["sources"].values()),
                incomplete_regular_security_sessions=sum(x["incomplete_regular_sessions"] for x in meta["sources"].values()))
    if frame.shape[1]<MIN_EQUITIES:meta["reason"]="Fewer than 20 verified original equity identities with usable sessions"
    return frame,meta
