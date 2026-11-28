from datetime import date,timedelta
from unittest import TestCase
import numpy as np

from scripts import benchmark_ema_first_passage as f


def bars():
    return np.tile([100.,100.,100.,100.,1.],(375,1))


def cross(j,sign):
    return {"minute":j,"direction":sign}


class FirstPassageTests(TestCase):
    def test_delayed_entry_and_both_direction_barriers(self):
        a=bars();a[11]=[100,200,50,100,1] # decision latency, not outcome
        a[12]=[100,100.12,99.99,100.1,1]
        self.assertEqual(f.outcome(a,cross(10,1),cross(14,-1),375)["outcome_state"],"favorable_first")
        a[12]=[100,100.01,99.88,99.9,1]
        self.assertEqual(f.outcome(a,cross(10,-1),cross(14,1),375)["success"],1)
        self.assertEqual(f.outcome(a,cross(10,1),cross(14,-1),375)["success"],0)
        self.assertEqual(f.outcome(a,cross(10,1),cross(11,-1),375)["outcome_state"],"canceled_before_or_at_entry")

    def test_ambiguous_reverse_and_censor(self):
        a=bars();a[12]=[100,100.2,99.9,100.1,1]
        self.assertIsNone(f.outcome(a,cross(10,1),cross(14,-1),375)["success"])
        self.assertEqual(f.outcome(a,cross(10,1),cross(14,-1),375)["outcome_state"],"ambiguous_dual_touch")
        a=bars()
        self.assertEqual(f.outcome(a,cross(10,1),cross(14,-1),375)["success"],0)
        self.assertEqual(f.outcome(a,cross(10,1),None,20)["outcome_state"],"censored_gap")
        self.assertEqual(f.outcome(a,cross(10,1),None,375)["outcome_state"],"censored_session_end")
        self.assertEqual(f.outcome(a,cross(10,1),None,11)["outcome_state"],"entry_unobserved")

    def test_synchronized_features_do_not_use_future_and_obey_gap(self):
        day="2026-11-26";prev="2026-11-25"
        a=bars();a[0:11,:4]=101
        prior=bars();prior[:,1]=102;prior[:,2]=98
        before=f.aligned_levels(day,np.array([10]),{day:a,prev:prior},"INDEX:TEST")
        a[11:,:4]=200
        after=f.aligned_levels(day,np.array([10]),{day:a,prev:prior},"INDEX:TEST")
        np.testing.assert_array_equal(before,after)
        a[5]=np.nan
        self.assertTrue(np.isnan(f.aligned_levels(day,np.array([10]),{day:a,prev:prior},"INDEX:TEST")).all())

    def test_matched_context_predictions_keep_unresolved_evaluation_rows(self):
        dates=[(date(2025,1,1)+timedelta(days=i)).isoformat() for i in range(80)]
        rows=[]
        for day in dates:
            for k in range(5):
                y=k%2 if k<4 else None
                rows.append({"session":day,"signal_minute":60+k*10,"direction":1 if k%2 else -1,
                             "success":y,"outcome_state":"ambiguous_dual_touch" if y is None else
                             ("favorable_first" if y else "adverse_first")})
        x=np.arange(len(rows),dtype=float).reshape(-1,1)%5
        extra=np.sin(x)
        report,pred=f.assess_lane(x,extra,rows,np.ones(len(rows),bool),("core",),("context",))
        self.assertEqual(report["state"],"assessed_conditional_first_passage")
        self.assertEqual(report["rows"]["evaluation_all"],80)
        self.assertEqual(report["rows"]["evaluation_resolved"],64)
        self.assertEqual(len(pred),80)
        self.assertEqual(set(pred),set(range(320,400)))
        self.assertIn("context_calibrated_probability",pred[324])
        self.assertFalse(report["trade_qualified"])
        self.assertIn("index_only",report["paired_brier_differences"])
        r,p=f.assess_lane(x,extra,rows,np.array([r["session"] in dates[-50:] for r in rows]),("core",),("context",))
        self.assertEqual(r["state"],"insufficient_context_sessions")
        self.assertFalse(p)
