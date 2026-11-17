"""One library, as-of classifications and model-first selection (offline fixtures)."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from unittest.mock import patch
import tempfile
import unittest

import pandas as pd
from fastapi.testclient import TestClient

from workstation_api import (data_acquisition, market_library, service,
                             shared_market_data, dhan_workspace, pit_index)
from workstation_api.app import app


class MarketLibraryTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix="quantlab_library_test_")
        self.addCleanup(temp.cleanup)
        p=patch.object(service,"DATA",Path(temp.name)/"data")
        p.start();self.addCleanup(p.stop)
        self.client=TestClient(app,base_url="http://127.0.0.1:8765")
        self.addCleanup(self.client.close)
        master=service.DATA/"dhan"/"instrument_master.csv"
        master.parent.mkdir(parents=True,exist_ok=True)
        source=[("1333","RELIANCE"),("11536","TCS"),("1334","HDFCBANK")]
        pd.DataFrame([{
            "SEM_EXM_EXCH_ID":"NSE","SEM_SEGMENT":"E",
            "SEM_SMST_SECURITY_ID":sid,"SEM_INSTRUMENT_NAME":"EQUITY",
            "SEM_TRADING_SYMBOL":symbol,"SEM_CUSTOM_SYMBOL":symbol,
            "SEM_SERIES":"EQ"} for sid,symbol in source]).to_csv(master,index=False)
        dhan_workspace._catalog_cached.cache_clear()
        self.addCleanup(dhan_workspace._catalog_cached.cache_clear)
        prices=pd.DataFrame({"close":[100+i/100 for i in range(120)]},
                            index=pd.bdate_range("2026-01-05",periods=120))
        entries=[({
            "exchange_segment":"NSE_EQ","security_id":sid,
            "source_sha256":sha256(symbol.encode()).hexdigest(),
            "display_symbol":symbol
        },prices) for sid,symbol in source]
        shared_market_data.ingest(entries,origin="cached_NSE_EQ_1333")

    def test_one_canonical_stock_library_not_universe_copies(self):
        all_=market_library.browse()
        self.assertTrue(all_["available"])
        self.assertEqual(all_["library_id"],"dhan_shared")
        self.assertEqual(all_["total"],3)
        self.assertEqual({r["observations"] for r in all_["items"]},{120})
        self.assertEqual(market_library.browse(view="nse")["total"],3)
        self.assertEqual(market_library.browse(view="bse")["total"],0)
        self.assertEqual(self.client.get("/api/data-manager/market-library").json()["total"],3)

    def test_nifty100_unavailable_until_original_membership(self):
        result=market_library.browse(view="nifty100")
        self.assertEqual(result["total"],0)
        self.assertEqual(result["source_state"]["state"],"missing_source")

    def test_exact_dated_nifty50_membership_not_today_assumed(self):
        catalog={r["id"]:r for r in dhan_workspace.catalog()}
        sample={"resolved":[catalog["NSE_EQ:1333"],catalog["NSE_EQ:11536"]],
                "asof_members":["RELIANCE","TCS"],
                "unresolved_count":1,"source_commit":"test_hash"}
        status={"available":True,"first_date":"2020-01-01",
                "covered_through":"2026-04-30"}
        with patch.object(pit_index,"status",return_value=status), \
             patch.object(pit_index,"query",return_value=sample) as source:
            eligible=market_library.browse(view="nifty50",as_of="2026-03-15")
        self.assertEqual(eligible["total"],2)
        self.assertEqual(eligible["source_state"]["unresolved_count"],1)
        self.assertEqual(source.call_args.args[0],"nifty50_pit")
        with patch.object(pit_index,"status",return_value=status):
            future=market_library.browse(view="nifty50",as_of="2026-06-01")
        self.assertEqual(future["source_state"]["state"],"outside_covered_dates")

    def test_source_dated_sector_history_not_backfilled(self):
        payload=(
            "exchange_segment,security_id,effective_date,sector\n"
            "NSE_EQ,1333,2026-01-01,Information Technology\n"
            "NSE_EQ,1333,2026-03-01,Financial Services\n"
            "NSE_EQ,11536,2026-01-01,Information Technology\n"
        ).encode()
        with self.assertRaisesRegex(ValueError,"Confirm"):
            market_library.import_sector_history(payload,confirm_original=False)
        first=market_library.import_sector_history(payload,confirm_original=True)
        self.assertEqual(first["new_classifications"],3)
        self.assertEqual(market_library.browse(
            view="sector",sector="Information Technology",as_of="2026-02-15")["total"],2)
        self.assertEqual(market_library.browse(
            view="sector",sector="Information Technology",as_of="2026-04-15")["total"],1)
        self.assertEqual(market_library.browse(
            view="sector",sector="Financial Services",as_of="2026-04-15")["total"],1)
        self.assertEqual(market_library.import_sector_history(
            payload,confirm_original=True)["new_classifications"],0)
        with self.assertRaisesRegex(ValueError,"Conflicting"):
            market_library.import_sector_history(
                payload.replace(b"Financial Services",b"Utilities"),
                confirm_original=True)

    def test_unknown_sector_identity_never_injected(self):
        payload=b"exchange_segment,security_id,effective_date,sector\nNSE_EQ,999999,2026-02-01,IT\n"
        reply=self.client.post("/api/data-manager/market-library/sectors/import",
            files={"file":("sectors.csv",payload,"text/csv")},
            data={"confirm_original":"true"})
        self.assertEqual(reply.status_code,400,reply.text)
        self.assertIn("unknown canonical",reply.text)
        self.assertEqual(market_library.browse()["total"],3)

    def test_model_first_selects_shared_source_no_picker(self):
        plan=data_acquisition.plan("garch",None,{"assets":2},with_sources=False)
        self.assertEqual(plan["dataset_id"],"dhan_shared")
        self.assertTrue(plan["one_library_default"])
        self.assertTrue(plan["requirements"]["runnable"])
        self.assertGreaterEqual(plan["requirements"]["common_returns"],72)

    def test_local_consolidation_reuses_without_provider_calls(self):
        record={"id":"dhan_batch_aaaa","kind":"dhan","has_daily_ohlcv":True}
        with patch.object(service,"datasets",return_value=[record]), \
             patch.object(shared_market_data,"ingest_prepared",
                  return_value={"rows_appended":3,"rows_reused":90}) as imported, \
             patch.object(dhan_workspace,"_fetch_history",
                  side_effect=AssertionError("Vendor calls forbidden")):
            result=market_library.consolidate()
        self.assertTrue(result["original_snapshots_preserved"])
        self.assertEqual(result["external_market_requests"],0)
        self.assertEqual(result["sources_ingested"],1)
        imported.assert_called_once_with(record["id"])


if __name__=="__main__":
    unittest.main()
