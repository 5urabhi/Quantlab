"""Offline Upstox source failover: exact ISIN, consent and Dhan-price overlap.

No real API calls, no network access, no credentials stored in fixtures.
"""
from __future__ import annotations

from datetime import date
from hashlib import sha256
from unittest.mock import patch
import json
import os
import sqlite3
import tempfile
import unittest

import pandas as pd

from workstation_api import (compatible_sources, dhan_workspace, service,
                             shared_market_data, upstox_fallback,
                             data_acquisition)


class UpstoxCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="quantlab_upstox_")
        self.addCleanup(self.temp.cleanup)
        for key,value in (("DATA","data"),("RESULTS","results")):
            p=patch.object(service,key,__import__("pathlib").Path(self.temp.name)/value)
            p.start();self.addCleanup(p.stop)
        self.row={
            "id":"NSE_EQ:1333","exchange_segment":"NSE_EQ",
            "security_id":"1333","symbol":"RELIANCE",
            "isin":"INE002A01018","instrument":"EQUITY","regular_eq":True,
        }
        baseline=pd.DataFrame(
            {"close":[100.,101.,102.,103.]},
            index=pd.to_datetime([
                "2026-09-01","2026-09-02","2026-09-03","2026-09-04"]))
        self.digest=sha256(b"test Dhan original").hexdigest()
        shared_market_data.ingest([
            ({**self.row,"source_sha256":self.digest},baseline)],
            origin="original_Dhan_test")
        self.env=patch.dict(os.environ,{"UPSTOX_ACCESS_TOKEN":"TEST_FAKE_NEVER_LOG"},clear=False)
        self.env.start();self.addCleanup(self.env.stop)
        self.cat=patch.object(dhan_workspace,"catalog",return_value=[self.row])
        self.cat.start();self.addCleanup(self.cat.stop)

    def _response(self, bad=False):
        records=[]
        for day,close in [
            ("2026-09-01",100),("2026-09-02",101),
            ("2026-09-03",102),("2026-09-04",103),
            ("2026-09-07",105)]:
            if bad and day=="2026-09-03":close=200
            records.append([day+"T00:00:00+05:30",
                            close,close,close,close,600,0])
        return json.dumps({"status":"success","data":{"candles":records}}).encode()

    def test_exact_isin_mapping_and_secondary_price_overlap(self):
        seen=[]
        def fetch(url,token):
            seen.append((url,token))
            return self._response()
        with patch.object(upstox_fallback,"_download_url",side_effect=fetch):
            result=upstox_fallback.retrieve(
                self.row,date(2026,9,4),date(2026,9,8),confirm_authorized=True)
        self.assertEqual(result["provider"],"upstox_v3")
        self.assertEqual(result["rows_added"],1)
        self.assertGreaterEqual(result["matched_sessions"],3)
        self.assertTrue(seen)
        self.assertIn("NSE_EQ%7CINE002A01018",seen[0][0])
        self.assertNotIn("TEST_FAKE_NEVER_LOG",seen[0][0])
        self.assertEqual(seen[0][1],"TEST_FAKE_NEVER_LOG")
        with sqlite3.connect(shared_market_data.database_path()) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM daily_closes").fetchone()[0],5)

    def test_conflicting_secondary_price_blocks_all_new_observations(self):
        with patch.object(upstox_fallback,"_download_url",return_value=self._response(bad=True)):
            with self.assertRaisesRegex(ValueError,"overlap gate"):
                upstox_fallback.retrieve(
                    self.row,date(2026,9,4),date(2026,9,8),confirm_authorized=True)
        receipts=compatible_sources.list_receipts()["sources"]
        self.assertEqual(receipts[0]["status"],"blocked")
        with sqlite3.connect(shared_market_data.database_path()) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM daily_closes").fetchone()[0],4)

    def test_explicit_consent_required_and_unmapped_isin_blocked(self):
        with self.assertRaisesRegex(ValueError,"Approve"):
            upstox_fallback.retrieve(self.row,date(2026,9,4),date(2026,9,8),
                                      confirm_authorized=False)
        with patch.object(dhan_workspace,"catalog",
                          return_value=[{**self.row,"isin":""}]):
            plan=upstox_fallback.eligibility(self.row)
            self.assertFalse(plan["eligible"])
            self.assertIn("ISIN",plan["reason"])
        self.assertEqual(upstox_fallback._map_instrument(self.row)["isin"],"INE002A01018")

    def test_unexpected_vendor_response_or_naive_timestamps_never_pass(self):
        with self.assertRaisesRegex(ValueError,"timezone"):
            upstox_fallback._normalize(json.dumps({"status":"success","data":{
                "candles":[["2026-09-07T00:00:00",100,101,99,100,1,0]]
            }}).encode())
        with self.assertRaisesRegex(ValueError,"invalid candle count"):
            upstox_fallback._normalize(b'{"status":"success","data":{"candles":"bad"}}')
        with patch.dict(os.environ,{"UPSTOX_ACCESS_TOKEN":""}):
            self.assertFalse(upstox_fallback.eligibility(self.row)["eligible"])

    def test_legacy_upstox_is_not_the_automated_second_provider(self):
        with patch.object(data_acquisition.model_data_manager,"inspect",
                          return_value={
                            "mode":"historical","status":"insufficient",
                            "can_download":True,"runnable":False,
                            "selected_assets":["NSE_EQ_1333"],
                            "estimated_vendor_daily_requests":2,
                            "missing_to_target":12,"missing_minimum":1
                          }),patch.object(data_acquisition.model_data_manager,
                                         "_mapping",return_value=([self.row],None)),\
             patch.object(upstox_fallback,"_download_url",
                          side_effect=AssertionError("No Upstox calls")),\
             patch.object(data_acquisition.zerodha_fallback,"eligibility",
                          return_value={"eligible":False,"configured":False}):
            plan=data_acquisition.plan("min_variance","dhan_shared",
                                       {"assets":8},with_sources=False)
        self.assertFalse(plan["zerodha_fallback_eligible"])
        self.assertTrue(any(item["id"]=="zerodha_kite" for item in plan["source_chain"]))
        self.assertFalse(any(item["id"]=="upstox_v3" for item in plan["source_chain"]))


if __name__=="__main__":
    unittest.main()
