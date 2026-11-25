"""Read-only local QuantLab V3 acceptance, without restarting the recorder.

Only synthetic inputs enter temporary isolated research databases. Local
market checks read loopback API status/evidence; no broker requests or orders.
A blocked namespace, unavailable scientific import, closed market or missing
source is reported distinctly from a passed software check.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import build_opener, ProxyHandler, HTTPRedirectHandler, Request

from workstation_api import python_strategy_sandbox as sandbox
from workstation_api import user_notebooks as notebooks, user_scripts as scripts


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Unexpected redirect from local API")


def read_local(path):
    """Fixed loopback origin, no proxy, redirects, credentials or external URLs."""
    if not isinstance(path,str) or not path.startswith("/api/"):
        raise ValueError("Expected a local API path")
    with build_opener(ProxyHandler({}), NoRedirect()).open(
            Request("http://127.0.0.1:8765"+path, headers={"Accept":"application/json"}),timeout=15) as response:
        raw=response.read(4_000_001)
    if len(raw)>4_000_000:
        raise ValueError("Local status response exceeds limit")
    return json.loads(raw)


def check(ident, state, detail, **extra):
    return {"check":ident,"state":state,"detail":detail,**extra}


def verify_sandbox(scientific=False):
    checks=[]
    if not sandbox.availability()["available"]:
        return [check("sandbox","blocked","Install approved bubblewrap/prlimit packages with bash run.sh python-packages install.")]
    with TemporaryDirectory(prefix="quantlab-v3-acceptance-") as root:
        host=Path(root)/"host_only.txt"
        host.write_text("synthetic marker",encoding="utf-8")
        probe="import os,json\n"+(
            "result={'host_file_visible':os.path.exists("+repr(str(host))+"),"
            "'secret_environment_visible':'QL_ACCEPTANCE_MARKER' in os.environ,"
            "'network_namespace':os.readlink('/proc/self/ns/net')}\n"
            "with open('/work/result.json','w') as f: json.dump(result,f)\n")
        try:
            with patch.dict(os.environ,{"QL_ACCEPTANCE_MARKER":"synthetic-not-a-token"}):
                result=scripts.isolated_json(probe,{},profile="stdlib")
        except (OSError,ValueError) as exc:
            return [check("sandbox","blocked","Namespace probe did not execute; inspect bubblewrap permissions. No unsafe fallback.",category=type(exc).__name__)]
        if (result.get("host_file_visible") or result.get("secret_environment_visible") or
                result.get("network_namespace")==os.readlink("/proc/self/ns/net")):
            return [check("sandbox","fail","Isolation did not exclude host marker, environment or network namespace.")]
        checks.append(check("sandbox","pass","Real bounded subprocess excludes host marker and environment; network namespace is separate."))
        snap={"title":"Synthetic acceptance values","provenance":"CI fixture, not market evidence",
              "columns":["x","value"],"rows":[[1,2],[2,4],[3,8]]}
        code='def analyze(data):\n    return {"title":"Check","x_label":"Input","y_label":"Squared value","traces":[{"name":"Squared","y":[r[1]**2 for r in data["rows"]]}]}'
        try:
            with patch.object(scripts,"_db_path",lambda:Path(root)/"temporary.sqlite3"):
                item=scripts.save_script(name="Acceptance model",kind="model",code=code)
                scripts.save_script(name="Acceptance model",kind="model",code=code.replace("**2","**3"),script_id=item["script_id"],expected_revision=1)
                model=scripts.run_saved(script_id=item["script_id"],revision=1,snapshot=snap)
                if model["plot"]["traces"][0]["y"]!=[4,16,64] or scripts.read_chart_run(model["run_id"])!=model:
                    raise AssertionError("Pinned model result or persisted receipt differs")
                checks.append(check("saved_model","pass","Actual isolated revision 1 executed after revision 2 was saved; exact output and receipt verified."))
                scan=scripts.save_script(name="Acceptance scanner",kind="scanner",code=code)
                ranking=scripts.run_saved(script_id=scan["script_id"],revision=1,snapshot=snap)
                if [r["score"] for r in ranking["ranking"]]!=[64,16,4]:
                    raise AssertionError("Scanner ranking differs")
                checks.append(check("saved_scanner","pass","Actual isolated scanner ranked synthetic rows correctly."))
                doc=notebooks.save_notebook(title="Acceptance notebook",snapshot=snap,cells=[
                    {"kind":"markdown","source":"Synthetic test"},
                    {"kind":"code","source":"values = [row[1] for row in data['rows']]"},
                    {"kind":"code","source":"show_chart('Squares','x','value',[1,2,3],[{'name':'squared','y':[v*v for v in values]}])\nprint(sum(values))"}])
                run=notebooks.run_notebook(notebook_id=doc["id"],revision=1)
                out=run["outputs"][-1]
                if (not run["complete"] or out["text"].strip()!="14" or out["charts"][0]["traces"][0]["y"]!=[4,16,64] or
                        notebooks.read_run(doc["id"],run["id"])!=run):
                    raise AssertionError("Notebook cells or saved result differ")
                checks.append(check("notebook","pass","Actual isolated ordered cells, text, chart output and persisted receipt verified."))
                signals,meta=sandbox.run_python("def signal(history):\n    return 'UP' if len(history)>1 else 'HOLD'",
                    [{"session_ist":"2026-11-25","close":2},{"session_ist":"2026-11-25","close":4}])
                if signals!=["HOLD","UP"] or meta["orders_placed"]!=0:
                    raise AssertionError("Causal strategy result differs")
                checks.append(check("causal_strategy","pass","Actual isolated causal strategy runs on synthetic completed observations."))
        except (ValueError,OSError,KeyError,IndexError,AssertionError) as exc:
            checks.append(check("research_execution","fail","An actual isolated research workflow failed.",category=type(exc).__name__,reason=str(exc)[:220]))
        if scientific:
            try:
                packages=sandbox.probe_scientific()["packages"]
                missing=sorted(name for name,value in packages.items() if not value.get("available"))
                checks.append(check("scientific_imports","blocked" if missing else "pass",
                                    "Missing or failed isolated scientific imports." if missing else "All approved scientific packages imported in the isolated profile.",
                                    missing=missing))
            except (OSError,ValueError,KeyError) as exc:
                checks.append(check("scientific_imports","blocked","Scientific isolated profile could not complete.",category=type(exc).__name__))
    return checks


def verify_local_market():
    try:
        health=read_local("/api/health")
    except (HTTPError,URLError,TimeoutError,OSError,ValueError):
        return [check("local_api","blocked","Start QuantLab with bash run.sh; the verifier does not start or stop services.")]
    if health.get("read_only_market_data") is not True or health.get("broker_orders_enabled") is not False:
        return [check("local_api","fail","Local workstation did not report read-only broker access.")]
    checks=[check("local_api","pass","Local API reports read-only market data and disabled broker orders.")]
    checks.append(check("dhan_token","pass" if health.get("dhan_token_configured") else "blocked",
                        "Token is locally configured; this does not prove provider authentication." if health.get("dhan_token_configured") else "No local Dhan token configured."))
    try:
        report=read_local("/api/trading-cockpit/acceptance")
        if report.get("orders_placed")!=0 or report.get("external_api_requests")!=0:
            checks.append(check("market_source_audit","fail","Local source audit unexpectedly reported external actions."))
        else:
            expected={"banknifty_history","contract_master","live_depth","stored_depth"}
            found={}
            for item in report.get("checks",[]):
                if item.get("code") in expected:
                    found[item["code"]]=item
            for code in sorted(expected):
                item=found.get(code)
                if item is None:
                    checks.append(check(code,"blocked","Expected source check is missing from local API response."))
                    continue
                state=item.get("status","not_verified")
                checks.append(check(code,"pass" if state=="pass" else "waiting" if state=="waiting" else "blocked",
                                    str(item.get("detail","Inspect local source acceptance."))[:400]))
        options=read_local("/api/trading-cockpit/option-feed/status")
        market=bool(options.get("market_regular_hours"))
        observed=int(options.get("observed_contracts") or 0)
        drops=int(options.get("dropped_events") or 0)
        coverage=bool(options.get("storage_coverage_complete"))
        checks.append(check("option_stream","pass" if market and options.get("connected") and observed>0 and coverage and drops==0 else "waiting" if not market else "blocked",
                            "Observed source contracts and storage status; no assumption that silent contracts trade.",
                            subscribed=options.get("requested_contracts",0),observed=observed,dropped=drops,storage_complete=coverage))
        index=read_local("/api/trading-cockpit/auto-index/status")
        fresh=sorted(ident for ident,quote in index.get("quotes",{}).items() if quote.get("fresh"))
        checks.append(check("shared_index","pass" if market and fresh else "waiting" if not market else "blocked",
                            "Requires actual documented index ticker packets; no inferred prices.",
                            state_code=index.get("state"),fresh_indexes=fresh,unsupported=index.get("unsupported_packets",0)))
    except (HTTPError,URLError,TimeoutError,OSError,ValueError,KeyError,TypeError) as exc:
        checks.append(check("market_source_audit","blocked","Local source evidence could not be read.",category=type(exc).__name__))
    return checks


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline",action="store_true",help="Only isolated synthetic execution; no local API calls")
    parser.add_argument("--scientific",action="store_true",help="Also verify actual approved scientific imports")
    parser.add_argument("--strict",action="store_true",help="Nonzero if a check is blocked or waiting")
    parser.add_argument("--require-sandbox",action="store_true",help="Nonzero if real isolated execution cannot be demonstrated")
    args=parser.parse_args(argv)
    checks=verify_sandbox(args.scientific)
    if not args.offline:
        checks+=verify_local_market()
    print(json.dumps({"scope":"Synthetic computation and local read-only source evidence; no orders or broker API calls",
                      "checks":checks},indent=2,ensure_ascii=False))
    if any(row["state"]=="fail" for row in checks):
        return 1
    if args.require_sandbox and checks[0]["state"]!="pass":
        return 2
    if args.strict and any(row["state"]!="pass" for row in checks):
        return 2
    return 0


if __name__=="__main__":
    raise SystemExit(main())
