"""Zerodha as the SECOND original daily-price provider (fully offline tests).

All external Kite and Dhan API responses are mocked. Real entitlement, login
and broker data availability must be verified on the user's own machine.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
import json
import os
import sqlite3
import tempfile
import unittest

import pandas as pd
from fastapi.testclient import TestClient

from workstation_api import (compatible_sources, data_acquisition,
                             model_data_manager, service, shared_market_data,
                             zerodha_fallback)
from workstation_api.app import app


class KiteSecondaryProviderTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix="quantlab_kite_second_")
        self.addCleanup(tmp.cleanup)
        root=Path(tmp.name)
        for name,directory in (("DATA","data"),("RESULTS","results")):
            patcher=patch.object(service,name,root/directory)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.env=patch.dict(os.environ,{
            "KITE_API_KEY":"test_app_key",
            "KITE_API_SECRET":"test_secret_local_only",
            "KITE_ACCESS_TOKEN":"test_local_access_token",
            "UPSTOX_ACCESS_TOKEN":"",
        })
        self.env.start();self.addCleanup(self.env.stop)
        self.row={
            "id":"NSE_EQ:1333","exchange_segment":"NSE_EQ","security_id":"1333",
            "symbol":"RELIANCE","instrument":"EQUITY","series":"EQ",
            "trading_symbol_verified":True,"regular_eq":True,
        }
        frame=pd.DataFrame(
            {"close":[100.,101.,102.,103.]},
            index=pd.to_datetime(["2026-09-01","2026-09-02",
                                  "2026-09-03","2026-09-04"]))
        shared_market_data.ingest([
            ({**self.row,
              "source_sha256":sha256(b"original_dhan_test").hexdigest()},frame)],
            origin="original_dhan")
        self.client=TestClient(app,base_url="http://127.0.0.1:8765")
        self.addCleanup(self.client.close)
        self._seed_master()

    def _seed_master(self):
        rows=[{"exchange":"NSE","exchange_token":"1333",
               "instrument_token":"343434","tradingsymbol":"RELIANCE"}]
        digest=sha256(json.dumps(rows,sort_keys=True,
                    separators=(",",":")).encode()).hexdigest()
        path=zerodha_fallback._master_file()
        path.write_text(json.dumps({
            "version":1,"created_utc":datetime.now(timezone.utc).isoformat(),
            "sha256":digest,"instruments":rows}),encoding="utf-8")

    @staticmethod
    def _candles(*,conflict=False,missing_timezone=False):
        lines=[]
        for d,p in [("2026-09-01",100),("2026-09-02",101),
                    ("2026-09-03",102),("2026-09-04",103),
                    ("2026-09-07",105)]:
            if conflict and d=="2026-09-03":p=200
            stamp=d+("T00:00:00" if missing_timezone else "T09:15:00+05:30")
            lines.append([stamp,p,p,p,p,300])
        return json.dumps({"status":"success","data":{"candles":lines}}).encode()

    def _count(self):
        with sqlite3.connect(shared_market_data.database_path()) as conn:
            return conn.execute("SELECT count(*) FROM daily_closes").fetchone()[0]

    def test_status_and_mapping_use_exchange_token_and_exact_symbol(self):
        status=self.client.get("/api/data-manager/zerodha/status")
        self.assertEqual(status.status_code,200,status.text)
        self.assertTrue(status.json()["master_current"])
        self.assertTrue(status.json()["token_present"])
        self.assertNotIn("test_local_access_token",status.text)
        mapping=zerodha_fallback._map_instrument(self.row)
        self.assertEqual(mapping["kite_instrument_token"],"343434")
        self.assertEqual(mapping["matched_by"],
                         "exchange+exchange_token+exact_tradingsymbol")
        with self.assertRaisesRegex(ValueError,"do not agree"):
            zerodha_fallback._map_instrument({**self.row,"symbol":"OTHER"})
        with self.assertRaisesRegex(ValueError,"trading symbol"):
            zerodha_fallback._map_instrument({
                **self.row,"trading_symbol_verified":False})

    def test_auth_and_provider_master_are_read_only_and_not_order_endpoints(self):
        with patch.object(zerodha_fallback,"_request",
                          return_value=b'{"status":"success","data":{"user_id":"XX123"}}') as fn, \
             patch("workstation_api.app._spawn",
                   return_value={"job_id":"offline_kite_probe","status":"queued"}):
            res=self.client.post("/api/data-manager/zerodha/verify")
            self.assertEqual(res.status_code,200,res.text)
            # The test may not dispatch a real provider job after mocks exit.
            result=zerodha_fallback.verify_session()
            self.assertTrue(result["authenticated"])
            self.assertNotIn("access_token",str(result))
            fn.assert_called_with("/user/profile")
        csv_rows=("instrument_token,exchange_token,tradingsymbol,name,"
                  "last_price,expiry,strike,tick_size,lot_size,instrument_type,segment,exchange\n"
                  "343434,1333,RELIANCE,RELIANCE,0,,,0.05,1,EQ,NSE,NSE\n")
        nse=zerodha_fallback._parse_master(csv_rows.encode(),"NSE")
        self.assertEqual(nse[0]["exchange_token"],"1333")
        self.assertEqual(zerodha_fallback._parse_master(csv_rows.encode(),"BSE"),[])

    def test_approved_secondary_source_appends_only_missing_original_rows(self):
        paths=[]
        def approved(path,**kwargs):
            paths.append(path)
            return self._candles()
        with patch.object(zerodha_fallback,"_request",side_effect=approved):
            result=zerodha_fallback.retrieve(
                self.row,date(2026,9,4),date(2026,9,8),
                confirm_authorized=True)
        self.assertEqual(result["provider"],"zerodha_kite")
        self.assertEqual(result["rows_added"],1)
        self.assertGreaterEqual(result["matched_sessions"],3)
        self.assertEqual(self._count(),5)
        self.assertIn("/instruments/historical/343434/day?",paths[0])
        self.assertNotIn("test_local_access_token",paths[0])
        receipt=compatible_sources.list_receipts()["sources"][0]
        self.assertEqual(receipt["status"],"imported")
        self.assertEqual(receipt["provider"],"zerodha_kite")

    def test_conflicting_prices_never_replace_existing_dhan_history(self):
        with patch.object(zerodha_fallback,"_request",
                          return_value=self._candles(conflict=True)):
            with self.assertRaisesRegex(ValueError,"overlap gate"):
                zerodha_fallback.retrieve(
                    self.row,date(2026,9,4),date(2026,9,8),
                    confirm_authorized=True)
        self.assertEqual(self._count(),4)
        self.assertEqual(compatible_sources.list_receipts()["sources"][0]["status"],
                         "blocked")

    def test_authorization_and_timezone_invariants(self):
        with self.assertRaisesRegex(ValueError,"Confirm"):
            zerodha_fallback.retrieve(
                self.row,date(2026,9,4),date(2026,9,8),
                confirm_authorized=False)
        with self.assertRaisesRegex(ValueError,"timezone"):
            zerodha_fallback._normalize(self._candles(missing_timezone=True))
        with self.assertRaisesRegex(ValueError,"read-only"):
            zerodha_fallback._request("/orders",method="POST")
        with self.assertRaisesRegex(ValueError,"Invalid fixed-host"):
            zerodha_fallback._request("https://attacker.example/x")
        self.assertEqual(self._count(),4)

    def test_user_can_configure_local_kite_app_without_echoing_secrets(self):
        with patch.dict(os.environ,{"KITE_API_KEY":"","KITE_API_SECRET":"",
                                 "ZERODHA_API_KEY":"","ZERODHA_API_SECRET":""}):
            response=self.client.post("/api/data-manager/zerodha/configure",json={
                "api_key":"my_test_kite_app","api_secret":"private_test_secret",
                "confirm_local_storage":True})
            self.assertEqual(response.status_code,200,response.text)
            self.assertTrue(response.json()["configured"])
            self.assertNotIn("private_test_secret",response.text)
            saved=zerodha_fallback._base()/"app_credentials.json"
            self.assertEqual(os.stat(saved).st_mode & 0o777,0o600)
            self.assertEqual(zerodha_fallback._api_key(),"my_test_kite_app")
            status=self.client.get("/api/data-manager/zerodha/status")
            self.assertEqual(status.status_code,200)
            self.assertNotIn("private_test_secret",status.text)
            self.assertTrue(status.json()["api_secret_configured"])
            invalid=self.client.post("/api/data-manager/zerodha/configure",json={
                "api_key":"my_test_kite_app","api_secret":"private_test_secret",
                "confirm_local_storage":False})
            self.assertEqual(invalid.status_code,400)

    def test_official_login_nonce_and_session_are_not_exposed(self):
        login=zerodha_fallback.start_login()
        url=urlparse(login["login_url"])
        self.assertEqual(url.hostname,"kite.zerodha.com")
        params=parse_qs(url.query)
        state=parse_qs(params["redirect_params"][0])["quantlab_state"][0]
        self.assertNotIn("test_secret_local_only",login["login_url"])
        response=json.dumps({"status":"success","data":{
            "access_token":"valid_test_session_2026"}}).encode()
        with patch.object(zerodha_fallback,"_request",return_value=response) as fetch:
            result=zerodha_fallback.finish_login("test_request_token_2026",state)
        self.assertTrue(result["connected"])
        body=(zerodha_fallback._base()/"session.json").read_text()
        self.assertNotIn("test_secret_local_only",body)
        self.assertTrue(zerodha_fallback.configured())
        self.assertEqual(os.stat(zerodha_fallback._base()/"session.json").st_mode & 0o777,0o600)
        fetch.assert_called_once()
        with self.assertRaisesRegex(ValueError,"expired or unsolicited"):
            zerodha_fallback.finish_login("test_request_token_2026",state)

    def test_acquisition_plan_never_contacts_second_provider_on_get(self):
        readiness={"mode":"historical","status":"insufficient",
                   "can_download":True,"runnable":False,
                   "selected_assets":["NSE_EQ_1333"],
                   "estimated_vendor_daily_requests":2,
                   "missing_to_target":12,"missing_minimum":1}
        with patch.object(model_data_manager,"inspect",return_value=readiness),\
             patch.object(model_data_manager,"_mapping",return_value=([self.row],None)),\
             patch.object(zerodha_fallback,"_request",
                          side_effect=AssertionError("GET must not call Kite")):
            plan=data_acquisition.plan("min_variance","dhan_shared",
                                       {"assets":8},with_sources=False)
        self.assertTrue(plan["zerodha_fallback_eligible"])
        self.assertTrue(any(x["id"]=="zerodha_kite" for x in plan["source_chain"]))
        self.assertFalse(any(x["id"]=="upstox_v3" for x in plan["source_chain"]))


if __name__=="__main__":
    unittest.main()
