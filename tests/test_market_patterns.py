import unittest
from datetime import date
from workstation_api import market_patterns as mp


def day(start=1000, step=1):
    return {i: (start+i*step, start+i*step+2, start+i*step-2,
                start+i*step+step) for i in range(mp.MINUTES)}


class MarketPatternTests(unittest.TestCase):
    def test_full_daily_stats_and_horizon_counts(self):
        days = {"2026-11-23": day(), "2026-11-24": day(1500, -1)}
        b = mp.baseline(days)
        self.assertEqual(b["sessions"], 2)
        self.assertEqual(b["range"]["mean"], 378)
        self.assertEqual(b["bullish_pct"], 50)
        self.assertEqual(b["bearish_pct"], 50)
        self.assertEqual(b["horizons"][0]["n"], 748)
        self.assertEqual(b["horizons"][0]["absolute_move"]["median"], 1)
        self.assertEqual(b["horizons"][-1]["n"], 630)
        self.assertEqual(len(b["time_buckets"]), 25)

    def test_no_history_is_not_zero_probability(self):
        b = mp.baseline({})
        self.assertIsNone(b["thresholds"][0]["range_pct"])
        self.assertIsNone(b["range"]["mean"])
        self.assertIsNone(mp.current_context({}, {}))

    def test_current_same_time_and_missing_open(self):
        hist = {"2026-11-23": day()}
        complete_prefix = {i: day()[i] for i in range(30)}
        c = mp.current_context(complete_prefix, hist)
        self.assertEqual(c["same_time_percentile"], 100)
        self.assertEqual(c["same_time_range"]["median"], 33)
        del complete_prefix[0]
        c = mp.current_context(complete_prefix, hist)
        self.assertIsNone(c["open"])
        self.assertIsNone(c["net"])
        self.assertIsNone(c["same_time_percentile"])
        self.assertEqual(c["missing_prefix_bars"], 1)

    def test_partial_gap_is_not_bridged(self):
        a, b = "2026-11-23", "2026-11-25"
        full = {a: day(), b: day(2000)}
        observed = {**full, "2026-11-24": {0: day()[0]}}
        out = mp.baseline(full, observed)
        self.assertEqual(out["gap_fill"][0]["n"], 0)

    def test_no_duplicate_request_windows_and_limit(self):
        a, b = date(2025,11,25), date(2026,11,25)
        existing = [(date(2026,1,1), date(2026,2,1)),
                    (date(2026,1,20), date(2026,3,1))]
        windows = mp.missing_windows(a,b,existing)
        self.assertTrue(all(0 < (y-x).days <= 90 for x,y in windows))
        self.assertEqual(sum((y-x).days for x,y in windows), 365-59)
        self.assertEqual(mp.missing_windows(a,b,[(a,b)]), [])

    def test_first_breakout_is_next_open(self):
        bars = day()
        out = mp.baseline({"2026-11-23": bars})
        r = out["opening_patterns"][0]
        self.assertEqual(r["n"], 1)
        self.assertEqual(r["signed_points"]["mean"], 5)


if __name__ == "__main__":
    unittest.main()
