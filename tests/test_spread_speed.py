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
        with patch.object(s.replay,"replay",side_effect=simulate),patch.object(s,"_coverage",return_value={}):
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
