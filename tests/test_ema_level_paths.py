from unittest import TestCase
import numpy as np

from scripts import benchmark_ema_levels as l


def bars(price=100.):
    return np.tile([price,price,price,price,1.],(375,1)).astype(float)


def cross(minute,direction,price):
    return {"minute":minute,"direction":direction,"signal_close":price,"cpr_zone":"inside",
            "previous_open":95.,"previous_high":110.,"previous_low":90.,
            "previous_close":100.,"cpr_bottom":100.,"cpr_pivot":100.,"cpr_top":100.,
            "today_open":100.,"today_running_high":105.,"today_running_low":95.}


class EMALevelTests(TestCase):
    def test_bullish_breakout_fails_then_falls_and_reclaims_after_reverse(self):
        a=bars()
        a[11]=[100,111,99,109,1]
        a[12]=[109,115,108,112,1]
        a[13]=[112,118,111,115,1]
        a[14]=[115,116,105,107,1]
        a[15]=[107,108,96,99,1]
        a[16]=[99,111,98,109,1]
        a[17]=[109,113,108,112,1]
        row=l.level_row("2026-11-26",a,cross(10,1,100),cross(14,-1,107),375,"previous_high",110.)
        self.assertEqual(row["first_touch_state"],"rejected_close")
        self.assertEqual(row["initial_rejection_failure_minute"],11)
        self.assertEqual(row["initial_rejection_reclaim_minute"],12)
        self.assertEqual(row["initial_rejection_minutes_to_reclaim"],1)
        self.assertEqual(row["breakout_minute"],12)
        self.assertEqual(row["state"],"failed_breakout_in_leg")
        self.assertEqual(row["minutes_breakout_to_failure"],2)
        self.assertEqual(row["breakout_favorable_extension_points"],8.)
        self.assertEqual(row["failure_minute"],14)
        self.assertEqual(row["adverse_points_from_failure_close"],11.)
        self.assertEqual(row["adverse_points_from_level"],14.)
        self.assertEqual(row["minutes_to_adverse_extreme"],1)
        self.assertEqual(row["minutes_to_reclaim"],3)
        self.assertTrue(row["reclaim_after_opposite_cross"])
        self.assertEqual(row["signed_close_change_1m_points"],-8.)
        self.assertIsNone(row["signed_close_change_5m_points"])

    def test_bearish_rejection_and_rebound_with_censoring(self):
        a=bars()
        a[11]=[100,102,89,94,1]
        a[12]=[94,99,93,98,1]
        a[13]=[98,105,97,104,1]
        row=l.level_row("2026-11-26",a,cross(10,-1,100),cross(12,1,98),14,"previous_low",90.)
        self.assertEqual(row["state"],"touched_no_breakout")
        self.assertEqual(row["failure_kind"],"touch_rejection_without_leg_breakout")
        self.assertEqual(row["failure_followup_state"],"censored_gap")
        self.assertEqual(row["adverse_points_from_failure_close"],11.)
        self.assertEqual(row["adverse_points_from_level"],15.)
        self.assertEqual(row["observed_followup_minutes"],2)
        self.assertIsNone(row["minutes_to_reclaim"])

    def test_frozen_levels_and_no_future_daily_ohlc(self):
        a=bars()
        a[14]=[100,106,94,101,1]
        early=l.frozen_levels(a,cross(10,1,100))
        self.assertIsNone(early["opening_15m_high"])
        c=cross(15,1,101.)
        first=l.frozen_levels(a,c)
        a[16:,:4]=1000
        second=l.frozen_levels(a,c)
        self.assertEqual(first,second)
        self.assertEqual(first["today_running_high"],105.)
        self.assertEqual(first["opening_15m_high"],106.)
        self.assertEqual(first["opening_15m_close"],101.)

    def test_denominators_already_beyond_and_unfinished_are_separate(self):
        a=bars()
        a[11]=[100,111,99,111,1]
        a[12]=[111,112,111,112,1]
        c=cross(10,1,100)
        held=l.level_row("2026-11-26",a,c,cross(12,-1,112),375,"previous_high",110.)
        missed=l.level_row("2026-11-26",a,c,cross(12,-1,112),375,"r1",120.)
        unresolved=l.level_row("2026-11-26",a,c,None,13,"previous_high",110.)
        beyond=l.level_row("2026-11-26",a,c,cross(12,-1,112),375,"previous_low",90.)
        at=l.level_row("2026-11-26",a,c,cross(12,-1,112),375,"cpr_pivot",100.)
        none=l.level_row("2026-11-26",a,c,cross(12,-1,112),375,"opening_15m_high",None)
        self.assertEqual(held["state"],"breakout_no_failure_in_leg")
        self.assertEqual(unresolved["state"],"unresolved_breakout_no_failure")
        s=l.summarize([held,missed,unresolved,beyond,at,none])
        self.assertEqual(s["paths"],6)
        self.assertEqual(s["ahead"],3)
        self.assertEqual(s["completed_ahead"],2)
        self.assertEqual(s["breakout_all_observed"],2)
        self.assertEqual(s["completed_breakout_fraction_of_ahead"],.5)
        self.assertEqual(s["completed_breakout_fraction_of_touched"],1.)
        self.assertEqual(s["completed_failed_fraction_of_breakouts"],0.)
        self.assertTrue(all(set(x)==set(held) for x in [missed,unresolved,beyond,at,none]))

    def test_equality_is_not_a_confirmed_break_or_failure(self):
        a=bars()
        a[11]=[100,110,99,110,1]
        a[12]=[110,110,110,110,1]
        row=l.level_row("2026-11-26",a,cross(10,1,100),cross(12,-1,110),375,"previous_high",110.)
        self.assertEqual(row["first_touch_state"],"closed_at_level")
        self.assertIsNone(row["breakout_minute"])
        self.assertIsNone(row["failure_kind"])
