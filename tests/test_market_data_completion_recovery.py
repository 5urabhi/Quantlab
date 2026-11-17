"""Offline gates for automatic model completion, secondary recovery and scale.

No live Dhan/Kite requests. All prices below are synthetic test fixtures and
MUST NOT be cited as empirical NSE research.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from threading import Event
from unittest.mock import patch
import importlib
import json
import os
import tempfile
import unittest

import pandas as pd
from fastapi.testclient import TestClient

from workstation_api import (batch_secondary_recovery as secondary,
                             dhan_workspace, market_data_workflow as market,
                             service, shared_market_data as shared,
                             zerodha_fallback)
from workstation_api.app import app

api = importlib.import_module("workstation_api.app")


class MarketDataCompletionTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix="quantlab_complete_flow_")
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        p=patch.object(service,"DATA",self.root/"data")
        p.start();self.addCleanup(p.stop)
        self.client=TestClient(app,base_url="http://127.0.0.1:8765")
        self.addCleanup(self.client.close)
        master=service.DATA/"dhan"/"instrument_master.csv"
        master.parent.mkdir(parents=True,exist_ok=True)
        pd.DataFrame([
          {"SEM_EXM_EXCH_ID":"NSE","SEM_SEGMENT":"E",
           "SEM_SMST_SECURITY_ID":security,"SEM_INSTRUMENT_NAME":"EQUITY",
           "SEM_TRADING_SYMBOL":symbol,"SEM_CUSTOM_SYMBOL":symbol,
           "SEM_SERIES":"EQ"}
          for security,symbol in (("1333","RELIANCE"),("11536","TCS"))
        ]).to_csv(master,index=False)
        dhan_workspace._catalog_cached.cache_clear()
        self.addCleanup(dhan_workspace._catalog_cached.cache_clear)
        self.start="2026-01-01";self.stop="2026-04-01"

    def _plan(self,**kwargs):
        with patch.dict(os.environ,{"DHAN_ACCESS_TOKEN":"offline_fixture"}):
            return market.plan("watchlist",self.start,self.stop,None,
                               ["RELIANCE","TCS"],kwargs.get("model_id","garch"))

    def test_model_planner_preselects_only_exact_mapped_assets(self):
        plan=self._plan()
        self.assertEqual(plan["model_followup"]["params"],{"assets":2})
        self.assertTrue(plan["model_followup"]["eligible"])
        self.assertEqual(plan["model_requirements"]["minimum"],60)
        self.assertEqual(plan["model_requirements"]["preferred"],72)
        self.assertFalse(plan["capacity"]["large"])
        with patch.dict(os.environ,{"DHAN_ACCESS_TOKEN":"offline_fixture"}):
            approved=market.approve(
                plan["preview_token"],"watchlist",self.start,self.stop,None,
                ["RELIANCE","TCS"],"garch",allow_incomplete=False,
                confirm_bulk=False,run_model_after_prepare=True)
        self.assertEqual(approved["model_followup"]["params"]["assets"],2)

    def test_single_series_requires_explicit_ticker_not_auto_model(self):
        plan=self._plan(model_id="gbm_fit")
        self.assertFalse(plan["model_followup"]["eligible"])
        with patch.dict(os.environ,{"DHAN_ACCESS_TOKEN":"offline_fixture"}):
            with self.assertRaisesRegex(ValueError,"Select an exact stock"):
                market.approve(plan["preview_token"],"watchlist",self.start,self.stop,
                               None,["RELIANCE","TCS"],"gbm_fit",
                               allow_incomplete=False,confirm_bulk=False,
                               run_model_after_prepare=True)

    def test_large_minute_budget_requires_separate_approval(self):
        sized=market._size_estimate(date(2021,1,1),date(2026,1,1),100,1)
        self.assertTrue(sized["large"])
        self.assertFalse(sized["over_limit"])
        self.assertGreater(sized["rows_upper_estimate"],10_000_000)

    def test_model_start_does_not_call_primary_without_live_preflight(self):
        plan=self._plan()
        payload={"selection":"watchlist","from_date":self.start,
                 "to_date":self.stop,"tickers":["RELIANCE","TCS"],
                 "model_id":"garch","preview_token":plan["preview_token"],
                 "confirm_readonly":True,"run_model_after_prepare":True}
        with patch.dict(os.environ,{"DHAN_ACCESS_TOKEN":"offline_fixture"}), \
             patch.object(api.dhan_auth,"check_profile",
                          return_value={"ok":False,"message":"Data API inactive"}), \
             patch.object(api,"_queue_dhan_batch") as queued:
            denied=self.client.post("/api/market-data/start",json=payload)
        self.assertEqual(denied.status_code,400)
        queued.assert_not_called()
        with patch.dict(os.environ,{"DHAN_ACCESS_TOKEN":"offline_fixture"}), \
             patch.object(api.dhan_auth,"check_profile",return_value={"ok":True}), \
             patch.object(api,"_queue_dhan_batch",
                          return_value={"job_id":"test_queued","status":"queued"}) as queued:
            accepted=self.client.post("/api/market-data/start",json=payload)
        self.assertEqual(accepted.status_code,200,accepted.text)
        self.assertEqual(queued.call_args.kwargs["model_params"],{"assets":2})
        self.assertEqual(queued.call_args.kwargs["model_id"],"garch")

    def test_post_batch_model_requires_true_plus_twenty_percent_and_saves_only_real(self):
        output={"status":"completed","counts":{"complete":2,"cached":0},
                "total":2,"automatic_preparation":{"dataset_id":"dhan_batch_fixture"}}
        check={"runnable":True,"missing_to_target":4,
               "common_returns":68,"min_returns":60,"target_returns":72}
        with patch.object(api,"_run_bulk",return_value=dict(output)), \
             patch.object(api.model_data_manager,"inspect",return_value=check), \
             patch.object(api.research_workflow,"execute") as run:
            incomplete=api._run_bulk_with_model("batch_fixture",Event(),
                                                "garch",{"assets":2})
            self.assertEqual(incomplete["model_research"]["status"],"incomplete")
            run.assert_not_called()
        with patch.object(api,"_run_bulk",return_value=dict(output)), \
             patch.object(api.model_data_manager,"inspect",
                          return_value={**check,"missing_to_target":0,
                                        "common_returns":90}), \
             patch.object(api.research_workflow,"execute",
                          return_value={"status":"complete","run":{"id":"saved_r"}}) as run:
            result=api._run_bulk_with_model("batch_fixture",Event(),
                                            "garch",{"assets":2})
        self.assertEqual(result["model_research"]["status"],"complete")
        self.assertEqual(run.call_args.kwargs["prepare_buffer"],False)
        self.assertEqual(run.call_args.kwargs["confirm_download"],False)

    def test_cancelled_dhan_does_not_launch_followup(self):
        cancelled=Event();cancelled.set()
        with patch.object(api,"_run_bulk",
                          return_value={"status":"cancelled",
                                        "automatic_preparation":{"dataset_id":"fake"}}), \
             patch.object(api.research_workflow,"execute") as run:
            result=api._run_bulk_with_model("batch_fixture",cancelled,
                                            "garch",{"assets":2})
            self.assertEqual(result["model_research"]["status"],"incomplete")
            run.assert_not_called()


class ExactZerodhaRecoveryTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix="quantlab_fallback_complete_")
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        p=patch.object(service,"DATA",self.root/"data")
        p.start();self.addCleanup(p.stop)
        e=patch.dict(os.environ,{
            "KITE_API_KEY":"test_local_api_key",
            "KITE_API_SECRET":"test_local_secret",
            "KITE_ACCESS_TOKEN":"test_session_only"})
        e.start();self.addCleanup(e.stop)
        self.row={"id":"NSE_EQ:1333","exchange_segment":"NSE_EQ",
                  "security_id":"1333","symbol":"RELIANCE","series":"EQ",
                  "instrument":"EQUITY","regular_eq":True,
                  "trading_symbol_verified":True,"status":"failed",
                  "error":"Dhan HTTP 401"}
        self.batch_id="batch_0123456789abcdef"
        self.folder=service.DATA/"dhan"/"batches"/self.batch_id
        self.folder.mkdir(parents=True)
        self.manifest=self.folder/"manifest.json"
        self.manifest.write_text(json.dumps({
            "id":self.batch_id,"status":"paused",
            "created_utc":"2026-03-01T00:00:00Z",
            "selection":"watchlist","exchange":"NSE","interval":None,
            "from_date":"2026-02-01","to_date":"2026-04-01",
            "items":[self.row],"index_spot":None,
        }),encoding="utf-8")
        rows=[{"exchange":"NSE","exchange_token":"1333",
               "instrument_token":"998877","tradingsymbol":"RELIANCE"}]
        digest=sha256(json.dumps(rows,sort_keys=True,
                separators=(",",":")).encode()).hexdigest()
        zerodha_fallback._master_file().write_text(json.dumps({
            "version":1,"created_utc":datetime.now(timezone.utc).isoformat(),
            "sha256":digest,"instruments":rows
        }),encoding="utf-8")
        self.client=TestClient(app,base_url="http://127.0.0.1:8765")
        self.addCleanup(self.client.close)

    def test_secondary_preview_never_calls_broker_and_checks_exact_mapping(self):
        with patch.object(zerodha_fallback,"_request",
                          side_effect=AssertionError("GET must not contact Kite")):
            response=self.client.get("/api/market-data/secondary/plan",
                                     params={"batch_id":self.batch_id})
        self.assertEqual(response.status_code,200,response.text)
        plan=response.json()
        self.assertTrue(plan["can_recover"])
        self.assertEqual(plan["eligible_count"],1)
        self.assertFalse(plan["batch_mutated"])
        self.assertEqual(plan["destination_dataset_id"],"dhan_shared")
        self.assertEqual(self.manifest.read_text().count("Dhan HTTP 401"),1)
        with self.assertRaisesRegex(ValueError,"changed"):
            secondary.approve(self.batch_id,"0"*64,confirm_secondary=True)
        with self.assertRaisesRegex(ValueError,"Explicitly approve"):
            secondary.approve(self.batch_id,plan["preview_token"],
                              confirm_secondary=False)

    def test_secondary_requires_original_dhan_overlap_before_kite_request(self):
        plan=secondary.preview(self.batch_id)
        with patch.object(zerodha_fallback,"verify_session",
                          return_value={"authenticated":True}), \
             patch.object(zerodha_fallback,"retrieve") as download, \
             patch.object(shared,"reuse_cached",return_value={"rows_appended":0}):
            recovered=secondary.execute(self.batch_id,plan["preview_token"])
        self.assertEqual(recovered["status"],"blocked")
        self.assertEqual(recovered["recovered"],0)
        download.assert_not_called()
        self.assertFalse(recovered["original_dhan_batch_changed"])

    def test_matching_original_closes_allow_append_without_changing_batch(self):
        dates=pd.to_datetime(["2026-03-02","2026-03-03","2026-03-04","2026-03-05"])
        shared.ingest([({
            **self.row,"source_sha256":sha256(b"dhan_offline_cache").hexdigest()
        },pd.DataFrame({"close":[100.,101.,102.,103.]},index=dates))],
            origin="cached_NSE_EQ_1333")
        before=self.manifest.read_bytes()
        plan=secondary.preview(self.batch_id)
        with patch.object(zerodha_fallback,"verify_session",
                          return_value={"authenticated":True}), \
             patch.object(shared,"reuse_cached",return_value={"rows_appended":0}), \
             patch.object(zerodha_fallback,"retrieve",
                          return_value={"provider":"zerodha_kite","rows_added":1,
                              "matched_sessions":4,"source_receipt_id":"offline_receipt"}) as vendor:
            result=secondary.execute(self.batch_id,plan["preview_token"])
        self.assertEqual(result["status"],"complete")
        self.assertEqual(result["recovered"],1)
        self.assertEqual(result["items"][0]["source_receipt_id"],"offline_receipt")
        vendor.assert_called_once()
        self.assertEqual(before,self.manifest.read_bytes())

    def test_secondary_cannot_claim_minute_ohlcv_or_running_batch(self):
        batch=json.loads(self.manifest.read_text())
        batch["interval"]=1
        self.manifest.write_text(json.dumps(batch))
        first=secondary.preview(self.batch_id)
        self.assertFalse(first["can_recover"])
        self.assertIn("minute OHLCV",str(first["blockers"]))
        batch["interval"]=None
        batch["status"]="running"
        self.manifest.write_text(json.dumps(batch))
        # A stale running batch is reported as interrupted by the queue
        # reconciler, not converted into completed history.
        again=secondary.preview(self.batch_id)
        self.assertFalse(again["original_dhan_batch_changed"] if
                         "original_dhan_batch_changed" in again else again["batch_mutated"])

    def test_recovery_endpoint_enforces_approval_before_queue(self):
        plan=secondary.preview(self.batch_id)
        payload={"batch_id":self.batch_id,"preview_token":plan["preview_token"]}
        with patch.object(api,"_spawn") as worker:
            no=self.client.post("/api/market-data/secondary/recover",json=payload)
            self.assertEqual(no.status_code,400)
            worker.assert_not_called()
        with patch.object(api,"_spawn",
                          return_value={"job_id":"offline_worker","status":"queued"}) as worker:
            yes=self.client.post("/api/market-data/secondary/recover",
                json={**payload,"confirm_secondary":True})
            self.assertEqual(yes.status_code,200,yes.text)
            self.assertEqual(worker.call_args.args[0],"market_secondary_recovery")


class LowDiskCheckpointTests(unittest.TestCase):
    def test_no_original_source_replacement_if_disk_fails_preflight(self):
        with tempfile.TemporaryDirectory(prefix="quantlab_low_disk_") as temp:
            raw=Path(temp)/"1333_daily.csv"
            original=b"date,close\\n2026-01-02,100\\n"
            raw.write_bytes(original)
            free_space=type("Capacity",(),{"free":24*1024*1024})()
            with patch.object(dhan_workspace.shutil,"disk_usage",return_value=free_space):
                with self.assertRaisesRegex(OSError,"Insufficient disk space"):
                    dhan_workspace._ensure_checkpoint_space(raw)
            self.assertEqual(raw.read_bytes(),original)
            self.assertFalse(raw.with_suffix(".pending.json").exists())


class CachedDataScaleTests(unittest.TestCase):
    def test_many_90day_windows_parse_once_per_interval(self):
        mapping={"exchange_segment":"NSE_EQ","security_id":"1333",
                 "symbol":"RELIANCE","id":"NSE_EQ:1333"}
        spans=[
            (1,date(2025,1,1),date(2025,4,1)),
            (1,date(2025,4,1),date(2025,7,1)),
            (1,date(2025,7,1),date(2025,10,1)),
            (None,date(2025,1,1),date(2025,10,1)),
        ]
        frame=pd.DataFrame({"close":[100.,101.,102.]},
                           index=pd.to_datetime(["2025-01-02","2025-01-03",
                                                 "2025-01-06"]))
        provenance={"exchange_segment":"NSE_EQ","security_id":"1333",
                    "source_sha256":"a"*64}
        with patch.object(shared,"cached_spans",return_value=spans), \
             patch.object(dhan_workspace,"_batch_daily_ohlcv",
                          return_value=(frame,provenance)) as read, \
             patch.object(shared,"ingest",
                          return_value={"dataset_id":"dhan_shared",
                                        "rows_appended":3,"rows_reused":0}):
            actual=shared.reuse_cached(mapping)
        self.assertEqual(read.call_count,2)
        self.assertEqual(actual["cache_intervals_read"],2)
        self.assertEqual(actual["source_windows_collapsed"],4)


if __name__=="__main__":
    unittest.main()
