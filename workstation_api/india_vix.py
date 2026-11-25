"""India VIX via an exact official Dhan INDEX/IDX_I master match and LTP REST.

No guessed security ID, no order API, no exchange timestamp claim. The
60-second cache includes failures to avoid retry storms and isolates tokens.
"""
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from threading import RLock
import csv
import re
import time

from . import dhan_workspace, dhan_option_chain, option_chain_live
from .advanced_options import positive

LOCK = RLock()
CACHE = {}


@lru_cache(maxsize=4)
def _resolve(path, mtime_ns, size):
    matches=set()
    with Path(path).open("r",encoding="utf-8-sig",newline="") as fd:
        reader=csv.DictReader(fd)
        columns=option_chain_live._fields(reader)
        col=lambda *names:option_chain_live._get_field(columns,*names)
        identifier=col("SECURITY_ID","SEM_SMST_SECURITY_ID")
        exchange=col("EXCH_ID","SEM_EXM_EXCH_ID")
        segment=col("SEGMENT","SEM_SEGMENT")
        kind=col("INSTRUMENT","SEM_INSTRUMENT_NAME")
        names=[col(n) for n in ("TRADING_SYMBOL","SEM_TRADING_SYMBOL","SEM_CUSTOM_SYMBOL",
                    "SYMBOL_NAME","SM_SYMBOL_NAME","DISPLAY_NAME","UNDERLYING_SYMBOL")]
        names=[n for n in names if n]
        if not all((identifier,exchange,segment,kind)) or not names:
            raise ValueError("Official instrument master lacks required index columns")
        for r in reader:
            if (str(r[exchange]).strip().upper()!="NSE" or
                str(r[segment]).strip().upper() not in ("I","IDX_I") or
                str(r[kind]).strip().upper()!="INDEX"):
                continue
            if not any(re.sub(r"[^A-Z0-9]","",str(r[n]).upper())=="INDIAVIX" for n in names):
                continue
            sid=str(r[identifier]).strip()
            if re.fullmatch(r"[0-9]{1,12}",sid):
                matches.add(sid)
    if len(matches)!=1:
        raise ValueError("No unique NSE India VIX INDEX/IDX_I identity in the official local master")
    return next(iter(matches))


def current():
    unavailable={"value":None,"identity":None,"received_utc":None,"source_clock":"local_receive_only",
                 "source":"Dhan v2 marketfeed/ltp","read_only":True}
    with LOCK:
        try:
            import os
            token=os.getenv("DHAN_ACCESS_TOKEN","").strip()
            path=dhan_workspace._master()
            stat=path.stat()
            now=datetime.now(timezone.utc)
            if not token or path.is_symlink() or stat.st_size>option_chain_live.MAX_MASTER_BYTES:
                raise ValueError("Current official Dhan master and authorized token required")
            if now.timestamp()-stat.st_mtime>48*3600:
                raise ValueError("Refresh official Dhan master to verify India VIX")
            key=(option_chain_live._auth_key(token),str(path),stat.st_mtime_ns,stat.st_size)
            entry=CACHE.get(key)
            if entry and time.monotonic()-entry[0]<60:
                return {**entry[1],"cache_hit":True}
            try:
                sid=_resolve(str(path),stat.st_mtime_ns,stat.st_size)
                token,client=option_chain_live._credentials()
                response,_=dhan_option_chain._json_http(dhan_option_chain.MARKET_LTP_ENDPOINT,
                       token=token,client_id=client,body={"IDX_I":[int(sid)]})
                if response.get("status")!="success":
                    raise ValueError("Dhan did not return successful India VIX market data")
                v=positive(response["data"]["IDX_I"][sid]["last_price"])
                if v is None:
                    raise ValueError("Dhan returned no positive India VIX level")
                result={**unavailable,"value":v,"identity":"IDX_I:"+sid,
                        "received_utc":datetime.now(timezone.utc).isoformat(),
                        "state":"observed_snapshot","reason":None}
            except (ValueError,OSError,KeyError,TypeError) as e:
                result={**unavailable,"state":"unavailable","reason":str(e)[:180] if isinstance(e,ValueError)
                        else "Original Dhan India VIX snapshot unavailable"}
            CACHE.clear()
            CACHE[key]=(time.monotonic(),result)
            return {**result,"cache_hit":False}
        except (ValueError,OSError):
            return {**unavailable,"state":"unavailable","reason":"Current authorized token and fresh official Dhan instrument master required",
                    "cache_hit":False}
