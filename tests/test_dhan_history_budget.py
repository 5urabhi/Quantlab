import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from urllib.error import HTTPError

from index_research.dhan_history_budget import HistoryBudget, HistoricalThrottle, retry_after


class HistoryBudgetTests(unittest.TestCase):
    def test_two_requests_overlap_with_common_spacing_and_capacity(self):
        budget=HistoryBudget(spacing=.025,max_in_flight=2,max_starts=20)
        starts=[]
        release=Event()
        two=Event()
        lock=Lock()
        def request():
            with budget.slot():
                with lock:
                    starts.append(time.monotonic())
                    if len(starts)==2:
                        two.set()
                release.wait(3)
        with ThreadPoolExecutor(max_workers=3) as pool:
            jobs=[pool.submit(request) for _ in range(3)]
            try:
                self.assertTrue(two.wait(2),"two historical requests did not overlap")
                self.assertEqual(budget.snapshot()["historical_active_requests"],2)
                self.assertEqual(len(starts),2)
            finally:
                release.set()
            for job in jobs:
                job.result(timeout=3)
        self.assertEqual(len(starts),3)
        self.assertTrue(all(b-a>=.015 for a,b in zip(starts,starts[1:])))
        self.assertEqual(budget.snapshot()["historical_starts_last_24h"],3)
        self.assertEqual(budget.snapshot()["historical_active_requests"],0)

    def test_provider_429_blocks_other_lanes_and_honors_retry_after(self):
        budget=HistoryBudget(spacing=0,max_starts=10,cooldown_seconds=2)
        with self.assertRaises(HTTPError):
            with budget.slot():
                raise HTTPError("https://example.invalid",429,"throttled",{"Retry-After":"30"},None)
        self.assertGreaterEqual(budget.remaining_cooldown(),29)
        with self.assertRaises(HistoricalThrottle):
            with budget.slot():
                self.fail("provider request admitted during shared cooldown")
        self.assertEqual(budget.snapshot()["historical_starts_last_24h"],1)
        self.assertEqual(budget.snapshot()["historical_active_requests"],0)

    def test_local_rolling_request_budget_counts_failed_starts(self):
        budget=HistoryBudget(spacing=0,max_starts=2,day_seconds=60)
        with self.assertRaises(ValueError):
            with budget.slot():
                raise ValueError("failed provider response")
        with budget.slot():
            pass
        with self.assertRaises(HistoricalThrottle) as exc:
            with budget.slot():
                self.fail("request beyond rolling budget")
        self.assertGreaterEqual(exc.exception.retry_after_seconds,59)
        self.assertEqual(budget.snapshot()["historical_starts_last_24h"],2)

    def test_retry_after_header(self):
        self.assertEqual(retry_after({"Retry-After":"120"}),120)
        self.assertEqual(retry_after({"Retry-After":"bad"}),0)
