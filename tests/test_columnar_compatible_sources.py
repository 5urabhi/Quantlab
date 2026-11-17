"""Original-source fallbacks and optional DuckDB acceleration: offline integration.

Never access brokerage endpoints; all values below are isolated test fixtures.
"""
from __future__ import annotations

from datetime import date
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch
import json
import sqlite3
import tempfile
import unittest

import pandas as pd
from fastapi.testclient import TestClient

from workstation_api import columnar_cache, compatible_sources, service, shared_market_data
from workstation_api.app import app


class CompatibleMarketSourcesAndParquetTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="quantlab_columnar_fallback_")
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        for attr,folder in (("DATA","data"),("RESULTS","results")):
            p = patch.object(service, attr, root / folder)
            p.start()
            self.addCleanup(p.stop)
        self.source_digest = sha256(b"test original Dhan fixture").hexdigest()
        self.source_id = "NSE_EQ:1333"
        self.sessions = [
            "2026-08-31","2026-09-01","2026-09-02",
            "2026-09-03","2026-09-04","2026-09-07",
        ]
        self.values = [100.0, 101.0, 101.5, 103.0, 104.0, 103.5]
        self.mapping = {
            "exchange_segment": "NSE_EQ", "security_id": "1333",
            "display_symbol": "RELIANCE", "source_sha256": self.source_digest,
        }
        frame = pd.DataFrame(
            {"close": self.values},
            index=pd.to_datetime(self.sessions))
        shared_market_data.ingest([(self.mapping, frame)], origin="test_original")
        self.client = TestClient(app, base_url="http://127.0.0.1:8765")
        self.addCleanup(self.client.close)

    @staticmethod
    def _csv(rows):
        return "date,close\n".encode("utf-8") + "\n".join(
            f"{d},{p}" for d,p in rows).encode("utf-8") + b"\n"

    def _db_count(self):
        with sqlite3.connect(shared_market_data.database_path()) as conn:
            return conn.execute("SELECT COUNT(*) FROM daily_closes").fetchone()[0]

    def test_model_cache_build_is_lossless_and_returns_latest_source_dates(self):
        original_digest = sha256(shared_market_data.database_path().read_bytes()).hexdigest()
        status = self.client.get("/api/data-manager/columnar/status").json()
        self.assertEqual(status["state"], "not_built")
        made = columnar_cache.build()
        self.assertTrue(made["ready"], made)
        self.assertEqual(made["observations"], 6)
        self.assertGreater(made["parquet_bytes"], 0)
        now = self.client.get("/api/data-manager/columnar/status").json()
        self.assertTrue(now["ready"])
        data = self.client.get("/api/data-manager/columnar/series", params={
            "identity": self.source_id, "limit": 3})
        self.assertEqual(data.status_code, 200, data.text)
        self.assertEqual([r["date"] for r in data.json()["rows"]],
                         self.sessions[-3:])
        self.assertTrue(data.json()["has_more"])
        self.assertEqual(data.json()["basis"], "unadjusted_close")
        self.assertEqual(original_digest,
                         sha256(shared_market_data.database_path().read_bytes()).hexdigest())

    def test_cache_is_stale_on_source_write_then_automatically_refreshed(self):
        columnar_cache.build()
        fresh = pd.DataFrame({"close":[106.0]},
                             index=pd.to_datetime(["2026-09-08"]))
        shared_market_data.ingest(
            [({**self.mapping,
               "source_sha256": sha256(b"next original source").hexdigest()}, fresh)],
            origin="test_followup")
        state = columnar_cache.status()
        self.assertFalse(state["ready"])
        self.assertEqual(state["state"], "stale")
        refused = self.client.get("/api/data-manager/columnar/series",
                                  params={"identity":self.source_id})
        self.assertEqual(refused.status_code, 400)
        refreshed = columnar_cache.refresh_if_enabled()
        self.assertEqual(refreshed["state"], "refreshed")
        result = columnar_cache.series(self.source_id, limit=1)
        self.assertEqual(result["rows"][0]["close"],106.0)

    def test_missing_database_cannot_materialize_synthetic_data(self):
        clean=patch.object(shared_market_data,"database_path",
                           return_value=service.DATA/"missing.sqlite3")
        with clean:
            status=columnar_cache.status()
            self.assertEqual(status["state"],"source_missing")
            with self.assertRaisesRegex(ValueError,"original"):
                columnar_cache.build()

    def test_exact_identity_and_at_least_three_matches_accept_only_new_rows(self):
        rows = list(zip(self.sessions[-4:],self.values[-4:]))
        rows += [("2026-09-08",107.5)]
        payload=self._csv(rows)
        result=compatible_sources.import_original(
            payload=payload,identity=self.source_id,
            provider="licensed_vendor_csv",
            confirm_authorized=True,confirm_unadjusted=True)
        self.assertEqual(result["status"],"imported",result)
        self.assertEqual(result["matched_sessions"],4)
        self.assertEqual(result["rows_added"],1)
        self.assertEqual(self._db_count(),7)
        archive=service.DATA/"research_workspace"/"compatible_sources"/result["id"]
        self.assertEqual((archive/"original.csv").read_bytes(),payload)
        receipt=json.loads((archive/"receipt.json").read_text())
        self.assertEqual(receipt["source_sha256"],sha256(payload).hexdigest())
        self.assertNotIn("original_path",receipt)
        before=compatible_sources.list_receipts()["sources"]
        self.assertEqual(before[0]["id"],result["id"])

    def test_timezone_aware_dhan_daily_export_preserves_ist_sessions(self):
        rows=[
            ("2026-09-02T15:30:00+0530",101.5),
            ("2026-09-03T15:30:00+0530",103.0),
            ("2026-09-04T15:30:00+0530",104.0),
            ("2026-09-08T15:30:00+0530",107.5),
        ]
        payload=("datetime,close\\n"+"\\n".join(
            f"{d},{p}" for d,p in rows)+"\\n").encode("utf-8")
        output=compatible_sources.import_original(
            payload=payload,identity=self.source_id,provider="dhan_export",
            confirm_authorized=True,confirm_unadjusted=True)
        self.assertEqual(output["status"],"imported",output)
        self.assertEqual(output["rows_added"],1)
        with sqlite3.connect(shared_market_data.database_path()) as conn:
            saved=conn.execute(
                "SELECT close FROM daily_closes WHERE identity=? AND session_date=?",
                (self.source_id,"2026-09-08")).fetchone()
        self.assertEqual(saved[0],107.5)

    def test_conflicting_external_close_is_never_promoted(self):
        rows=list(zip(self.sessions[-4:],self.values[-4:]))
        rows[1]=(rows[1][0], 999.99)
        rows.append(("2026-09-08",108.0))
        result=compatible_sources.import_original(
            payload=self._csv(rows),identity=self.source_id,
            provider="licensed_vendor_csv",
            confirm_authorized=True,confirm_unadjusted=True)
        self.assertEqual(result["status"],"blocked",result)
        self.assertGreaterEqual(result["conflicting_sessions"],1)
        self.assertEqual(self._db_count(),6)

    def test_unmatched_external_identity_is_quarantined(self):
        rows=list(zip(self.sessions[:2],self.values[:2]))
        rows.append(("2026-09-08",102.0))
        result=compatible_sources.import_original(
            payload=self._csv(rows),identity=self.source_id,
            provider="dhan_export",confirm_authorized=True,
            confirm_unadjusted=True)
        self.assertEqual(result["status"],"blocked")
        self.assertIn("three",str(result["blockers"]).lower())
        self.assertEqual(self._db_count(),6)
        with self.assertRaisesRegex(ValueError,"exact canonical"):
            compatible_sources.import_original(
                payload=self._csv(rows),identity="NSE_EQ:9999",
                provider="dhan_export",confirm_authorized=True,
                confirm_unadjusted=True)

    def test_adjusted_close_and_missing_rights_are_rejected(self):
        with self.assertRaisesRegex(ValueError,"Confirm"):
            compatible_sources.import_original(
                payload=b"date,close\n2026-09-01,100\n",identity=self.source_id,
                provider="dhan_export",confirm_authorized=False,
                confirm_unadjusted=True)
        with self.assertRaisesRegex(ValueError,"Adjusted"):
            compatible_sources.import_original(
                payload=b"date,close,adj_close\n2026-09-01,100,101\n",
                identity=self.source_id,provider="dhan_export",
                confirm_authorized=True,confirm_unadjusted=True)
        self.assertEqual(self._db_count(),6)

    def test_browser_api_has_no_raw_source_files_or_sql_mutation(self):
        catalog=self.client.get("/api/data-manager/fallback/registry")
        self.assertEqual(catalog.status_code,200,catalog.text)
        nse=next(p for p in catalog.json()["providers"] if p["id"]=="nse_mcp")
        self.assertFalse(nse["compatible"])
        found=self.client.get("/api/data-manager/columnar/instruments",
                              params={"query":"RELIANCE"})
        self.assertEqual(found.status_code,200,found.text)
        self.assertEqual(found.json()["instruments"][0]["identity"],self.source_id)
        no_consent=self.client.post("/api/data-manager/fallback/import",data={
            "identity":self.source_id,"provider":"licensed_vendor_csv",
            "confirm_authorized":"false","confirm_unadjusted":"true"},
            files={"file":("source.csv",self._csv(
                list(zip(self.sessions,self.values))),"text/csv")})
        self.assertEqual(no_consent.status_code,400)
        self.assertEqual(self._db_count(),6)

if __name__=="__main__":
    unittest.main()
