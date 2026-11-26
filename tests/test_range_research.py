from datetime import date, timedelta
import unittest
from workstation_api import range_research as r, depth_replay


class RangeResearchTests(unittest.TestCase):
    def test_regime(self):
        self.assertEqual(r.regime([63000]*31)["state"],"compressed")
        self.assertEqual(r.regime([63000+i*10 for i in range(31)])["state"],"trend_up")
        self.assertEqual(r.regime([63100 if i%2 else 63000 for i in range(31)])["state"],"range_bound")
        self.assertEqual(r.regime([63000]*30)["state"],"insufficient_contiguous_bars")

    def test_inward_only(self):
        previous=[63100 if i%2 else 63000 for i in range(31)]
        self.assertEqual(r.reversion_signal(previous,63020),"UP")
        self.assertEqual(r.reversion_signal(previous,62990),"HOLD")
        self.assertEqual(r.reversion_signal([63000+i*10 for i in range(31)],63310),"HOLD")
        with self.assertRaises(ValueError):
            r.reversion_signal(previous,63020,.7)

    def test_missing_current_bar(self):
        bars={i:(63000,63100,63000,63100 if i%2 else 63000) for i in range(31)}
        del bars[10]
        self.assertEqual(r.current_regime(bars)["state"],"insufficient_contiguous_bars")

    def test_exact_depth_rule_resets_after_gap(self):
        from datetime import datetime, timezone
        start=datetime(2026,11,25,4,0,tzinfo=timezone.utc)
        prices=[63100 if i%2 else 63000 for i in range(31)]+[63020]
        rows=[{"timestamp_utc":(start+timedelta(minutes=i)).isoformat(),"session_ist":"2026-11-25","close":p} for i,p in enumerate(prices)]
        signals=depth_replay.rule_signals(rows,"RANGE_REVERSION",9,21,30,.2)
        self.assertEqual(signals[-1],"UP")
        del rows[10]
        self.assertEqual(depth_replay.rule_signals(rows,"RANGE_REVERSION",9,21,30,.2)[-1],"HOLD")

    def test_chronological_nonoverlapping_study(self):
        first=date(2026,1,1)
        bars={i:(63000,63100,63000,63100 if i%2 else 63000) for i in range(375)}
        study=r.historical({(first+timedelta(days=i)).isoformat():bars for i in range(30)})
        self.assertEqual(study["development_sessions"],21)
        self.assertEqual(study["evaluation_sessions"],9)
        self.assertEqual(len(study["rows"]),10)
        self.assertTrue(all(x["mean_signals_per_session"]<=375/x["hold_minutes"] for x in study["rows"]))


if __name__=="__main__":
    unittest.main()
