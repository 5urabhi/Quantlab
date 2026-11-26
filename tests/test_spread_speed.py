from datetime import datetime,timezone,timedelta
from unittest import TestCase
from unittest.mock import patch
from workstation_api import spread_speed as s, paper_execution as p

class SpreadSpeedTests(TestCase):
    def test_fixed_anchors_and_censored_paths(self):
        now=datetime(2026,11,26,4,30,tzinfo=timezone.utc)
        calls=[]
        def simulate(**kwargs):
            h=kwargs["hold_seconds"];decision=datetime.fromisoformat(kwargs["decision_utc"])
            calls.append((decision,h))
            out={"state":"exit_unobservable","entry_complete":True,"exit_complete":False,
                 "net_pnl_inr":None,"entry_received_utc":p._iso(decision+timedelta(seconds=2))}
            if h!=15:
                out.update(state="complete_conditional_quote_replay",exit_complete=True,
                    net_pnl_inr=20.,total_fees_inr=50.,exit_decision_utc=p._iso(decision+timedelta(seconds=h+2)),
                    exit_received_utc=p._iso(decision+timedelta(seconds=h+4)),
                    entries=[{"requested_units":30,"original_best_bid":99.,"cashflow":-3030.}])
            return out
        with patch.object(s.replay,"replay",side_effect=simulate),patch.object(s,"_coverage",return_value={}),patch.object(s,"_worker_count",return_value=1):
            result=s.run(day="2026-11-26",strategy="LONG_OPTION",identities=["NSE_FNO:123"],now=now)
        self.assertGreater(result["decision_count"],0)
        self.assertEqual(len(calls),result["decision_count"]*len(s.HORIZONS))
        self.assertEqual(result["matched_decisions"],0)
        row=next(r for r in result["rows"] if r["hold_seconds"]==15)
        self.assertEqual(row["scored"],0)
        self.assertEqual(row["unscored"],result["decision_count"])
        self.assertIsNone(row["net"]["mean"])
        row=next(r for r in result["rows"] if r["hold_seconds"]==5)
        self.assertEqual(row["roundtrip"]["median"],9.)
        self.assertEqual(row["entry_delay"]["p90"],2.)
        self.assertEqual(row["exit_delay"]["p90"],2.)
        self.assertEqual(row["net"]["mean"],20.)
        self.assertFalse(result["actual_fills_observed"])

    def test_latency_grid_identical_anchors_and_matched_samples(self):
        now=datetime(2026,11,26,4,30,tzinfo=timezone.utc)
        calls={}
        def simulate(**kwargs):
            h=kwargs["hold_seconds"];d=kwargs["latency_ms"];stamp=kwargs["decision_utc"]
            calls.setdefault((d,h),[]).append(stamp)
            decision=datetime.fromisoformat(stamp)
            out={"state":"entry_unobservable","entry_complete":False,"exit_complete":False,"net_pnl_inr":None}
            # One missing path in one cell must be excluded from all same-hold
            # comparisons, but not from unrelated holds.
            if d==5000 and h==1 and len(calls[d,h])==1:
                return out
            return {"state":"complete_conditional_quote_replay","entry_complete":True,"exit_complete":True,
                    "net_pnl_inr":float(h-d/1000),"total_fees_inr":50.,
                    "entry_received_utc":p._iso(decision+timedelta(milliseconds=d)),
                    "exit_decision_utc":p._iso(decision+timedelta(milliseconds=d,seconds=h)),
                    "exit_received_utc":p._iso(decision+timedelta(milliseconds=2*d,seconds=h)),
                    "entries":[{"requested_units":30,"original_best_bid":99.,"cashflow":-3030.}]}
        with patch.object(s.replay,"replay",side_effect=simulate),patch.object(s,"_coverage",return_value={}),patch.object(s,"_worker_count",return_value=1):
            result=s.run(day="2026-11-26",strategy="LONG_OPTION",identities=["NSE_FNO:123"],now=now,compare_delays=True)
        n=result["decision_count"]
        self.assertGreater(n,1)
        self.assertEqual(result["configuration_count"],48)
        self.assertEqual(len(calls),48)
        self.assertTrue(all(v==calls[100,1] for v in calls.values()))
        self.assertEqual(result["matched_decisions"],n-1)
        for row in result["rows"]:
            self.assertEqual(row["matched_same_hold_count"],n-1 if row["hold_seconds"]==1 else n)
            self.assertEqual(row["matched_same_delay_count"],n-1 if row["latency_ms"]==5000 else n)
            self.assertEqual(row["observations"],[])
        cell=next(r for r in result["rows"] if r["latency_ms"]==5000 and r["hold_seconds"]==1)
        self.assertEqual(cell["scored"],n-1)
        self.assertEqual(cell["net"]["mean"],-4)
        self.assertEqual(cell["roundtrip"]["p90"],11)

    def test_timestamp_coverage_does_not_fill_missing_seconds(self):
        import sqlite3
        db=sqlite3.connect(":memory:")
        db.execute("CREATE TABLE live_depth_books(identity TEXT, received_utc TEXT)")
        start=datetime(2026,11,26,3,45,tzinfo=timezone.utc)
        for i in (0,1,3):
            db.execute("INSERT INTO live_depth_books VALUES (?,?)",("NSE_FNO:123",p._iso(start+timedelta(seconds=i))))
        for i in (1,2,3):
            db.execute("INSERT INTO live_depth_books VALUES (?,?)",("NSE_FNO:456",p._iso(start+timedelta(seconds=i))))
        class Keep:
            def execute(self,*args):return db.execute(*args)
            def close(self):pass
        from datetime import date
        try:
            with patch.object(s.replay.ao,"_read_database",return_value=Keep()):
                result=s._coverage(date(2026,11,26),["NSE_FNO:123","NSE_FNO:456"],start+timedelta(seconds=5))
            self.assertEqual(result["elapsed_seconds"],5)
            self.assertEqual(result["common_observed_seconds"],2)
            self.assertEqual(result["common_coverage_pct"],40)
            self.assertEqual(result["contracts"][0]["coverage_pct"],60)
            self.assertEqual(result["contracts"][0]["largest_internal_gap_seconds"],2)
        finally:
            db.close()

    def test_future_day_rejected(self):
        with self.assertRaises(ValueError):
            s.run(day="2026-11-27",strategy="LONG_OPTION",identities=["NSE_FNO:123"],
                  now=datetime(2026,11,26,4,30,tzinfo=timezone.utc))


    def test_worker_budget_reserves_resources_and_caps_work(self):
        with patch.object(s,"_available_cpus",return_value=12),patch.object(s,"_available_memory",return_value=4096*s.MIB):
            self.assertEqual(s._worker_count(100),6)
            self.assertEqual(s._worker_count(2),2)
            self.assertEqual(s._worker_count(0),0)
        with patch.object(s,"_available_cpus",return_value=2),patch.object(s,"_available_memory",return_value=4096*s.MIB):
            self.assertEqual(s._worker_count(100),1)
        with patch.object(s,"_available_cpus",return_value=12),patch.object(s,"_available_memory",return_value=768*s.MIB):
            self.assertEqual(s._worker_count(100),1)
        with patch.object(s,"_available_memory",return_value=None):
            self.assertEqual(s._worker_count(100),1)

    def test_parallel_matches_serial_and_progress_is_monotonic(self):
        now=datetime(2026,11,26,4,30,tzinfo=timezone.utc)
        def simulate(**kwargs):
            h=kwargs["hold_seconds"];d=kwargs["latency_ms"]
            decision=datetime.fromisoformat(kwargs["decision_utc"])
            if h==15:
                return {"state":"entry_unobservable","entry_complete":False,"exit_complete":False,"net_pnl_inr":None}
            return {"state":"complete_conditional_quote_replay","entry_complete":True,"exit_complete":True,
                "net_pnl_inr":float(h-d/1000),"total_fees_inr":50.,
                "entry_received_utc":p._iso(decision+timedelta(milliseconds=d)),
                "exit_decision_utc":p._iso(decision+timedelta(milliseconds=d,seconds=h)),
                "exit_received_utc":p._iso(decision+timedelta(milliseconds=2*d,seconds=h)),
                "entries":[{"requested_units":30,"original_best_bid":99.,"cashflow":-3030.}]}
        params=dict(day="2026-11-26",strategy="LONG_OPTION",identities=["NSE_FNO:123"],now=now,compare_delays=True)
        progress=[]
        with patch.object(s.replay,"replay",side_effect=simulate),patch.object(s,"_coverage",return_value={}):
            with patch.object(s,"_worker_count",return_value=1):
                serial=s.run(**params)
            with patch.object(s,"_worker_count",return_value=3):
                parallel=s.run(**params,progress=lambda n,stage:progress.append(n))
        self.assertEqual(serial.pop("worker_count"),1)
        self.assertEqual(parallel.pop("worker_count"),3)
        self.assertEqual(serial,parallel)
        self.assertEqual(progress,sorted(progress))
        self.assertEqual(progress[-1],100)

    def test_parallel_cancellation_stops_refilling(self):
        from threading import Lock
        started=[]
        lock=Lock()
        def evaluate(anchor,stop):
            with lock:
                started.append(anchor)
            stop.wait(.05)
            return anchor
        def cancel(percent,stage):
            raise RuntimeError("cancelled")
        with self.assertRaisesRegex(RuntimeError,"cancelled"):
            s._parallel_anchors(list(range(50)),evaluate,3,cancel)
        self.assertLessEqual(len(started),3)


    def test_unscored_paths_report_budget_and_exact_missing_reasons(self):
        now=datetime(2026,11,26,4,30,tzinfo=timezone.utc)
        def simulate(**kwargs):
            if kwargs["hold_seconds"]==1:
                return {"state":"insufficient_hypothetical_risk_budget","entry_complete":False,
                        "exit_complete":False,"net_pnl_inr":None,"entry_risk_proxy":19000.}
            return {"state":"entry_unobservable","entry_complete":False,"exit_complete":False,
                    "net_pnl_inr":None,"missing":[{"stage":"entry","reason":"no_book_in_fixed_window"}]}
        with patch.object(s.replay,"replay",side_effect=simulate),patch.object(s,"_coverage",return_value={}),patch.object(s,"_worker_count",return_value=1):
            result=s.run(day="2026-11-26",strategy="LONG_OPTION",identities=["NSE_FNO:123"],now=now)
        budget=result["rows"][0]
        missing=result["rows"][1]
        self.assertEqual(budget["minimum_observed_entry_budget_inr"],19000.)
        self.assertEqual(budget["scored"],0)
        self.assertIsNone(budget["net"]["mean"])
        self.assertEqual(missing["missing_receipt_reasons"],{"entry:no_book_in_fixed_window":result["decision_count"]})
        self.assertIsNone(missing["minimum_observed_entry_budget_inr"])
