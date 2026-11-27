from unittest import TestCase
from scripts.audit_banknifty_stock_clock import clock_summary
import pandas as pd


class StockClockTests(TestCase):
    def test_incomplete_missing_final_minute_and_off_grid_bar(self):
        clocks=[]
        for day,minutes in (("2026-07-30",375),("2026-07-31",374)):
            clocks.extend(pd.date_range(day+" 09:15",periods=minutes,freq="min",tz="Asia/Kolkata"))
        clocks.append(pd.Timestamp("2026-07-31 15:29:30",tz="Asia/Kolkata"))
        raw=pd.DataFrame({"datetime":clocks}).to_csv(index=False).encode()
        report=clock_summary(raw,{"2026-07-30","2026-07-31","2026-08-03"},750)
        self.assertEqual(report["complete_regular_sessions"],1)
        self.assertEqual(report["regular_minute_count_distribution"],{0:1,374:1,375:1})
        self.assertEqual(report["off_minute_grid_regular_rows"],1)
        self.assertEqual(report["most_frequent_missing_minutes_partial_sessions"],[["15:29",1]])
        self.assertEqual(report["zero_exact_minute_dates"],["2026-08-03"])
        self.assertEqual(report["last_raw_session"],"2026-07-31")
