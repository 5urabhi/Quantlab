"""Bounded authenticated, read-only diagnostic against real Dhan data.

Run from the repo: .venv/bin/python -m scripts.probe_dhan_rolling_history
No source file writes, no broker orders and no recorder changes.
"""
from collections import Counter
from datetime import datetime, timezone
import http.client
import json
import os
from pathlib import Path
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

IST=ZoneInfo("Asia/Kolkata")
PATH="/v2/charts/rollingoption"
HOST="api.dhan.co"
BASE={"exchangeSegment":"NSE_FNO","interval":"1","securityId":25,
      "instrument":"OPTIDX","expiryFlag":"MONTH","expiryCode":1,"strike":"ATM",
      "drvOptionType":"CALL","requiredData":["open","high","low","close","volume"],
      "fromDate":"2026-10-06","toDate":"2026-10-07"}
FULL=["open","high","low","close","volume","oi","iv","strike","spot"]
MAX_BYTES=9_000_000


def main():
    load_dotenv(Path.cwd()/".env")
    token=os.getenv("DHAN_ACCESS_TOKEN","").strip()
    if not token:
        raise SystemExit("No Dhan access token in local .env/environment")
    headers={"Host":HOST,"Accept":"application/json","Content-Type":"application/json",
             "Accept-Encoding":"identity","access-token":token}
    def probe(label,body,transport="http.client"):
        print("\n===",label,transport,"===",flush=True)
        print("POST https://"+HOST+PATH)
        print(json.dumps(body,separators=(",",":")),flush=True)
        data=json.dumps(body).encode()
        if transport=="http.client":
            connection=http.client.HTTPSConnection(HOST,timeout=40)
            try:
                connection.request("POST",PATH,data,headers)
                response=connection.getresponse()
                status=response.status
                raw=response.read(MAX_BYTES+1)
            finally:
                connection.close()
        else:
            request=Request("https://"+HOST+PATH,data=data,headers=headers,method="POST")
            try:
                with urlopen(request,timeout=40) as response:
                    status=response.status
                    raw=response.read(MAX_BYTES+1)
            except HTTPError as exc:
                status=exc.code
                raw=exc.read(4096)
        print("HTTP",status)
        if len(raw)>MAX_BYTES:
            raise SystemExit("Oversized response")
        try:
            payload=json.loads(raw)
        except ValueError:
            print("Response not JSON; bytes",len(raw))
            return False
        if status!=200:
            # Keep response structure visible but never expose credentials.
            print("Error type:",str(payload.get("errorType","")).replace(token,"[REDACTED]")[:120])
            print("Code:",str(payload.get("errorCode","")).replace(token,"[REDACTED]")[:40])
            message=str(payload.get("errorMessage",""))
            import re
            message=re.sub(r"\b[0-9]{5,}\b","[REDACTED]",message.replace(token,"[REDACTED]"))
            print("Message:",message[:300])
            if status in (401,403,429):
                raise SystemExit("Stopping on access/rate limit")
            return False
        segment=(payload.get("data") or {}).get("ce" if body["drvOptionType"]=="CALL" else "pe") or {}
        stamps=segment.get("timestamp") or []
        print("Lengths:",{k:len(v) for k,v in segment.items() if isinstance(v,list)})
        if stamps:
            sessions=Counter(datetime.fromtimestamp(float(t),timezone.utc).astimezone(IST).date().isoformat() for t in stamps)
            print("Actual IST date counts:",dict(sorted(sessions.items())))
            print("Unique timestamp count:",len(set(stamps)))
            print("First/last IST:",datetime.fromtimestamp(float(min(stamps)),timezone.utc).astimezone(IST).isoformat(),
                  datetime.fromtimestamp(float(max(stamps)),timezone.utc).astimezone(IST).isoformat())
            print("First 3 values:",{k:v[:3] for k,v in segment.items() if isinstance(v,list)})
        return bool(stamps) and all(len(segment.get(k) or [])==len(stamps) for k in body["requiredData"])
    tests=[
        ("Known-good one-day basic",BASE,"http.client"),
        ("Same request, previous urllib transport",BASE,"urllib"),
        ("One-day all required fields",{**BASE,"requiredData":FULL},"http.client"),
        ("Four-date basic",{**BASE,"toDate":"2026-10-09"},"http.client"),
        ("Four-date all fields",{**BASE,"toDate":"2026-10-09","requiredData":FULL},"http.client"),
        ("First rejected 30-day window",{**BASE,"fromDate":"2025-11-26","toDate":"2025-12-26","requiredData":FULL},"http.client"),
    ]
    results={}
    for label,body,transport in tests:
        if results:
            time.sleep(2)
        results[label]=probe(label,body,transport)
    if not results["One-day all required fields"]:
        for field in ("strike","oi","iv","spot"):
            time.sleep(2)
            label="Basic + "+field
            results[label]=probe(label,{**BASE,"requiredData":BASE["requiredData"]+[field]})
    else:
        for label,body in (("Full PE",{**BASE,"requiredData":FULL,"drvOptionType":"PUT"}),
                           ("Full CE ATM+1",{**BASE,"requiredData":FULL,"strike":"ATM+1"})):
            time.sleep(2)
            results[label]=probe(label,body)
    print("\n=== ALIGNED NONEMPTY REQUESTED FIELDS ===")
    for name,ok in results.items():
        print("PASS" if ok else "FAIL",name)
    print("No receipt saved; no order submitted.")


if __name__=="__main__":
    main()
