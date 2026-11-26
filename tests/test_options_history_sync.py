import unittest
from datetime import date,datetime,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from workstation_api import options_history_sync as sync, expired_options_backtest as exp


class OptionsHistorySyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.p=patch.object(sync.service,"DATA",Path(self.tmp.name))
        self.p.start()
        self.addCleanup(self.p.stop)
        self.today=date(2026,11,26)

    def test_preview_excludes_active_series_and_bounds_year(self):
        p=sync.preview("2025-11-26","2026-11-25",3,self.today)
        self.assertEqual(p["excluded_active_calendar_days"],1)
        self.assertLessEqual(p["full_scope_request_estimate"],300)
        with self.assertRaises(ValueError):
            sync.preview("2024-11-26","2026-11-25",3,self.today)
        self.assertEqual(sync.preview("2026-11-25","2026-11-25",0,self.today)["eligible_calendar_days"],0)

    def test_existing_overlap_reused_and_no_new_calls_on_retry(self):
        a,b=date(2026,10,1),date(2026,10,3)
        for side in ("CALL","PUT"):
            body=exp._request_body(a,b,"MONTH",0,"ATM",side)
            exp._save_cache(body,{"data":{"ce" if side=="CALL" else "pe":{"timestamp":[]}}})
        requests=[]
        def fetch(body):
            requests.append(body)
            return {"data":{"ce" if body["drvOptionType"]=="CALL" else "pe":{"timestamp":[]}}}
        r=sync.run(start_date="2026-10-01",end_date="2026-10-05",wings=0,fetcher=fetch,today=self.today)
        self.assertEqual(r["existing_verified_receipts"],2)
        self.assertEqual(r["new_receipts"],2)
        self.assertEqual({x["fromDate"] for x in requests},{"2026-10-03"})
        requests.clear()
        r=sync.run(start_date="2026-10-01",end_date="2026-10-05",wings=0,fetcher=fetch,today=self.today)
        self.assertFalse(requests)
        self.assertEqual(r["new_receipts"],0)
        self.assertFalse(r["continuous_coverage_certified"])

    def test_failed_request_keeps_prior_completed_receipt(self):
        calls=[]
        def fetch(body):
            calls.append(body)
            if len(calls)>1:
                raise ValueError("provider unavailable")
            return {"data":{"ce":{"timestamp":[]}}}
        with self.assertRaises(ValueError):
            sync.run(start_date="2026-10-01",end_date="2026-10-03",wings=0,fetcher=fetch,today=self.today)
        self.assertIsNotNone(exp._get_cached(calls[0]))
        self.assertIsNone(exp._get_cached(calls[1]))


if __name__=="__main__":
    unittest.main()
