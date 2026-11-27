from unittest import TestCase
import numpy as np

from scripts import benchmark_cross_market_levels as c


def bars(price=100.):
    return np.tile([price,price,price,price,1.],(375,1)).astype(float)


class CrossMarketLevelTests(TestCase):
    def test_scheduled_cash_prefix_and_dated_membership(self):
        day="2026-11-26";prev="2026-11-25";identity="NSE_EQ:1333"
        a=bars();a[360:]=np.nan
        index={day:bars(),prev:bars()}
        bank={day:a,prev:a.copy()}
        matched,counts=c.common_dates(index,bank,identity,[day],{day:{"HDFCBANK":identity}})
        self.assertEqual(matched,[(day,360,360)])
        self.assertEqual(counts["matched_complete_sessions"],1)
        self.assertEqual(c.common_dates(index,bank,identity,[day],{})[0],[])
        crosses,prefix,state=c.p.session_crosses(a,a,previous_minutes=360,session_minutes=360)
        self.assertEqual((crosses,prefix,state),([],360,"complete_regular_prefix"))
        self.assertEqual(c.p.session_crosses(a,a)[2],"prior_complete_weekday_unavailable")

    def test_scheduled_end_is_censor_not_gap(self):
        a=bars();a[360:]=np.nan
        a[11]=[100.,112.,99.,111.,1.]
        a[12]=[111.,112.,105.,107.,1.]
        cross={"minute":10,"direction":1,"signal_close":100.,"cpr_zone":"inside"}
        row=c.l.level_row("2026-11-26",a,cross,None,360,"previous_high",110.,session_minutes=360)
        self.assertEqual(row["leg_state"],"censored_session_end")
        self.assertEqual(row["state"],"failed_breakout_in_leg")
        self.assertEqual(row["failure_followup_state"],"censored_session_end")
        self.assertIsNone(row["minutes_to_reclaim"])

    def test_scale_normalization_and_identical_date_comparator(self):
        day="2026-11-26";prev="2026-11-25"
        previous=bars();previous[:,:4]=np.linspace(120,100,375)[:,None]
        a=bars(100.);a[:20,:4]=140.;a[20:40,:4]=80.;a[40:,:4]=140.
        index={day:a,prev:previous}
        scaled={key:np.column_stack((value[:,:4]*10,value[:,4])) for key,value in index.items()}
        result=c.compare(index,scaled,"INDEX:TEST",[day],[day])
        self.assertEqual(result["matched_dates"],[day])
        self.assertEqual(result["evaluation_dates"],[day])
        self.assertEqual(result["crossovers"]["banknifty"],result["crossovers"]["instrument"])
        for side in ("bullish","bearish"):
            for name in c.l.LEVEL_NAMES:
                x=result["all"]["banknifty"][side][name];y=result["all"]["instrument"][side][name]
                for key in ("ahead","completed_ahead","touch","breakout","failed"):
                    self.assertEqual(x[key],y[key])
                if x["distance_bps"]["count"]:
                    self.assertAlmostEqual(x["distance_bps"]["p50"],y["distance_bps"]["p50"])
