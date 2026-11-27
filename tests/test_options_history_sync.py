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
        self.assertLessEqual(p["full_scope_request_estimate"],sync.MAX_REQUESTS)
        self.assertGreater(p["full_scope_request_estimate"],2000)
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
        self.assertEqual({x["fromDate"] for x in requests},{"2026-10-04"})
        self.assertEqual({x["toDate"] for x in requests},{"2026-10-05"})
        requests.clear()
        r=sync.run(start_date="2026-10-01",end_date="2026-10-05",wings=0,fetcher=fetch,today=self.today)
        self.assertFalse(requests)
        self.assertEqual(r["new_receipts"],0)
        self.assertFalse(r["continuous_coverage_certified"])

    def test_short_inclusive_pairs_and_resume(self):
        requests=[]
        def fetch(body):
            requests.append(body)
            self.assertEqual((date.fromisoformat(body["toDate"])-date.fromisoformat(body["fromDate"])).days,1)
            side="ce" if body["drvOptionType"]=="CALL" else "pe"
            return {"data":{side:{"timestamp":[]}}}
        args=dict(start_date="2025-11-26",end_date="2025-12-25",wings=0,fetcher=fetch,today=self.today)
        r=sync.run(**args)
        self.assertEqual(r["new_receipts"],30)
        self.assertEqual(len(requests),30)
        self.assertEqual(r["rejected_requests"],[])
        self.assertFalse(r["continuous_coverage_certified"])
        requests.clear()
        r=sync.run(**args)
        self.assertEqual(r["existing_verified_receipts"],30)
        self.assertEqual(requests,[])

    def test_one_day_remainder_uses_previous_date_and_no_active_date(self):
        self.assertEqual(list(exp._rolling_windows(date(2026,11,24),date(2026,11,25))),
                         [(date(2026,11,23),date(2026,11,24))])
        calls=[]
        def fetch(body):
            calls.append(body)
            return {"data":{"ce" if body["drvOptionType"]=="CALL" else "pe":{"timestamp":[]}}}
        sync.run(start_date="2026-11-24",end_date="2026-11-25",wings=0,fetcher=fetch,today=self.today)
        self.assertEqual(len(calls),2)
        self.assertEqual({x["toDate"] for x in calls},{"2026-11-24"})

    def test_rejected_pair_is_not_marked_checked_and_can_resume(self):
        calls=[]
        def fetch(body):
            calls.append(body)
            if body["drvOptionType"]=="CALL":
                raise exp.RollingInputError("DH-905")
            return {"data":{"pe":{"timestamp":[]}}}
        args=dict(start_date="2026-10-06",end_date="2026-10-07",wings=0,today=self.today)
        r=sync.run(**args,fetcher=fetch)
        self.assertEqual(r["state"],"partial_requests")
        self.assertEqual(len(r["rejected_requests"]),1)
        self.assertEqual(r["new_receipts"],1)
        self.assertEqual(r["unattempted_requests"],0)
        calls.clear()
        def recover(body):
            calls.append(body)
            return {"data":{"ce":{"timestamp":[]}}}
        r=sync.run(**args,fetcher=recover)
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0]["drvOptionType"],"CALL")
        self.assertEqual(r["state"],"request_windows_checked")

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


    def test_scope_progress_counts_distinct_pairs_and_not_rejected_attempts(self):
        args=dict(start_date="2026-10-01",end_date="2026-10-05",wings=0,today=self.today)
        snapshots=[]
        def fetch(body):
            if body["drvOptionType"]=="CALL":
                raise exp.RollingInputError("DH-905")
            return {"data":{}}
        result=sync.run(**args,fetcher=fetch,on_counts=snapshots.append,request_limit=3)
        self.assertEqual(result["eligible_offset_date_pairs"],10)
        self.assertEqual(snapshots[0]["checked_offset_date_pairs"],0)
        self.assertEqual(result["batch_attempted"],3)
        self.assertEqual(result["remaining_planned_requests"],result["planned_missing_requests"]-result["batch_completed"])
        self.assertLess(result["checked_offset_date_pairs"],10)
        self.assertTrue(all(a["checked_offset_date_pairs"]<=b["checked_offset_date_pairs"] for a,b in zip(snapshots,snapshots[1:])))
        self.assertEqual(result["missing_offset_date_pairs"]+result["checked_offset_date_pairs"],10)
        final=sync.run(**args,fetcher=lambda _:{"data":{}})
        self.assertEqual(final["checked_offset_date_pairs"],10)
        self.assertEqual(final["remaining_planned_requests"],0)
        self.assertFalse(final["continuous_coverage_certified"])

    def test_observed_minute_coverage_is_not_request_coverage(self):
        day="2026-10-01"
        stamp=datetime(2026,10,1,4,0,tzinfo=timezone.utc).timestamp()
        def fetch(body):
            if body["drvOptionType"]=="PUT":
                return {"data":{}}
            return {"data":{"ce":{"timestamp":[stamp],"open":[10],"high":[11],"low":[9],
                                   "close":[10],"strike":[60000],"volume":[0]}}}
        args=dict(start_date=day,end_date="2026-10-02",wings=0,today=self.today,priority_sessions=[day])
        first=sync.run(**args,fetcher=fetch)
        second=sync.run(**args,fetcher=lambda _:self.fail("unexpected request"))
        for report in (first,second):
            self.assertEqual(report["checked_offset_date_pairs"],4)
            self.assertEqual(report["known_expected_minute_slots"],750)
            self.assertEqual(report["known_observed_minute_slots"],1)
            self.assertEqual(report["known_market_dates"],1)
            self.assertFalse(report["continuous_coverage_certified"])

    def test_extended_receipt_audit_does_not_change_comparison_window(self):
        day="2026-10-01"
        stamps=[datetime(2026,10,1,9,59,tzinfo=timezone.utc).timestamp(),
                datetime(2026,10,1,10,0,tzinfo=timezone.utc).timestamp(),
                datetime(2026,10,1,10,9,tzinfo=timezone.utc).timestamp(),
                datetime(2026,10,1,10,10,tzinfo=timezone.utc).timestamp()]
        payload={"data":{"ce":{"timestamp":stamps,"open":[10]*4,"high":[11]*4,
                                "low":[9]*4,"close":[10]*4,"strike":[60000]*4}}}
        body=exp._request_body(date(2026,10,1),date(2026,10,2),"MONTH",0,"ATM","CALL")
        self.assertEqual(len(exp._normalize(payload,body)),1)
        self.assertEqual(len(exp._normalize(payload,body,full_session=True)),3)
        args=dict(start_date=day,end_date="2026-10-02",wings=0,today=self.today,priority_sessions=[day])
        first=sync.run(**args,fetcher=lambda b:payload if b["drvOptionType"]=="CALL" else {"data":{}})
        second=sync.run(**args,fetcher=lambda _:self.fail("unexpected redownload"))
        for report in (first,second):
            self.assertEqual(report["known_observed_minute_slots"],1)
            self.assertEqual(report["known_expected_minute_slots"],750)
            self.assertEqual(report["extended_observed_minute_slots"],2)
            self.assertEqual(report["extended_expected_minute_slots"],20)

    def test_unchanged_receipts_skip_reparse_but_changed_and_deleted_revalidate(self):
        args=dict(start_date="2026-10-01",end_date="2026-10-02",wings=0,today=self.today)
        sync.run(**args,fetcher=lambda _:{"data":{}})
        with patch.object(sync,"_verified_summary",wraps=sync._verified_summary) as parse:
            sync.run(**args,fetcher=lambda _:self.fail("unexpected request"))
            self.assertEqual(parse.call_count,2)
            parse.reset_mock()
            result=sync.run(**args,fetcher=lambda _:self.fail("unexpected request"))
            self.assertEqual(parse.call_count,0)
            self.assertEqual(result["checked_offset_date_pairs"],4)
            body=exp._request_body(date(2026,10,1),date(2026,10,2),"MONTH",0,"ATM","CALL")
            path=exp._cache_path(body)
            path.write_text("corrupt",encoding="utf-8")
            cover,reused,rejected=sync._saved_windows(date(2026,10,1),date(2026,10,3),0)
            self.assertEqual((reused,rejected),(1,1))
            self.assertEqual(parse.call_count,1)
            self.assertNotIn(("CALL","ATM"),cover)
            path.unlink()
            result=sync.run(**args,fetcher=lambda _:{"data":{}})
            self.assertEqual(result["new_receipts"],1)
            self.assertEqual(result["checked_offset_date_pairs"],4)


    def test_profile_disconnect_keeps_verified_progress_before_provider_request(self):
        day="2026-10-01"
        body=exp._request_body(date(2026,10,1),date(2026,10,2),"MONTH",0,"ATM","CALL")
        exp._save_cache(body,{"data":{}})
        seen=[]
        with patch.object(sync.dhan_auth,"check_profile",return_value={"ok":False,"code":"profile_unreachable"}),patch.object(exp,"_original_response_once") as request:
            with self.assertRaises(exp.RollingConnectionError):
                sync.run(start_date=day,end_date="2026-10-02",wings=0,today=self.today,on_counts=seen.append)
            request.assert_not_called()
        self.assertEqual(seen[-1]["checked_offset_date_pairs"],2)
        self.assertEqual(seen[-1]["eligible_offset_date_pairs"],4)
        self.assertEqual(seen[-1]["remaining_planned_requests"],1)


    def test_pipeline_overlaps_next_download_with_current_verification(self):
        from threading import Event
        second_started=Event()
        calls=[]
        normalize=exp._normalize
        def fetch(body):
            calls.append(body)
            if len(calls)==2:
                second_started.set()
            return {"data":{}}
        def verify(payload,body,**kwargs):
            if body["drvOptionType"]=="CALL":
                self.assertTrue(second_started.wait(2),"next request did not overlap verification")
            return normalize(payload,body,**kwargs)
        with patch.object(exp,"_normalize",side_effect=verify):
            result=sync.run(start_date="2026-10-01",end_date="2026-10-02",wings=0,
                            fetcher=fetch,today=self.today,pipeline=True)
        self.assertEqual(len(calls),2)
        self.assertEqual(result["new_receipts"],2)
        self.assertEqual(result["checked_offset_date_pairs"],4)
        for body in calls:
            self.assertIsNotNone(exp._get_cached(body))

    def test_pipeline_never_prefetches_past_batch_limit_or_provider_throttle(self):
        args=dict(start_date="2026-10-01",end_date="2026-10-05",wings=0,
                  today=self.today,pipeline=True)
        calls=[]
        def fetch(body):
            calls.append(body)
            return {"data":{}}
        first=sync.run(**args,fetcher=fetch,request_limit=1)
        self.assertEqual(len(calls),1)
        self.assertEqual(first["new_receipts"],1)
        calls.clear()
        def throttled(body):
            calls.append(body)
            raise exp.RollingRateLimitError(1800)
        with self.assertRaises(exp.RollingRateLimitError) as error:
            sync.run(**args,fetcher=throttled)
        self.assertEqual(error.exception.retry_after_seconds,1800)
        self.assertEqual(len(calls),1)

    def test_pipeline_request_starts_remain_paced(self):
        import time
        calls=[]
        def fetch(body):
            calls.append(time.monotonic())
            return {"data":{}}
        with patch.object(sync.dhan_auth,"check_profile",return_value={"ok":True}),patch.object(exp,"_original_response_once",side_effect=fetch):
            result=sync.run(start_date="2026-10-01",end_date="2026-10-02",wings=0,
                            today=self.today,pipeline=True)
        self.assertEqual(result["new_receipts"],2)
        self.assertGreaterEqual(calls[1]-calls[0],sync.REQUEST_START_SPACING-.01)

    def test_provider_retry_after_is_respected(self):
        from urllib.error import HTTPError
        from io import BytesIO
        body=exp._request_body(date(2026,10,1),date(2026,10,2),"MONTH",0,"ATM","CALL")
        def opener(*args,**kwargs):
            raise HTTPError(exp.ENDPOINT,429,"rate limit",{"Retry-After":"1800"},BytesIO(b""))
        with patch.dict(exp.os.environ,{"DHAN_ACCESS_TOKEN":"fixture-token"}):
            with self.assertRaises(exp.RollingRateLimitError) as err:
                exp._original_response_once(body,opener=opener)
        self.assertEqual(err.exception.retry_after_seconds,1800)
        self.assertEqual(exp._retry_after_seconds({"Retry-After":"invalid"}),0)
        for code in ("DH-904","805"):
            def vendor_throttle(*args,**kwargs):
                raise HTTPError(exp.ENDPOINT,400,"Bad Request",{"Retry-After":"1200"},
                                BytesIO(('{"errorCode":"'+code+'"}').encode()))
            with patch.dict(exp.os.environ,{"DHAN_ACCESS_TOKEN":"fixture-token"}):
                with self.assertRaises(exp.RollingRateLimitError) as err:
                    exp._original_response_once(body,opener=vendor_throttle)
                self.assertEqual(err.exception.retry_after_seconds,1200)


if __name__=="__main__":
    unittest.main()
