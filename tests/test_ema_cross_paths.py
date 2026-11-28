from unittest import TestCase
import numpy as np

from scripts import benchmark_ema_paths as p


def bars(price=100.):
    return np.tile([price,price,price,price,1.],(375,1)).astype(float)


def cross(minute,direction,price):
    return {"minute":minute,"direction":direction,"signal_close":price,
            "cpr_zone":"above"}


class EMAPathTests(TestCase):
    def test_bullish_peak_retracement_and_delayed_references(self):
        a=bars()
        a[10]=[100.,200.,90.,100.,1.] # pre-signal extreme is excluded
        a[11]=[100.,110.,99.,108.,1.]
        a[12]=[108.,118.,107.,117.,1.]
        a[13]=[117.,115+2,109.,110.,1.]
        a[14]=[110.,112.,106.,108.,1.]
        a[15]=[108.,109.,107.,108.,1.]
        a[16]=[108.,108.,108.,108.,1.]
        row=p.path_row("2026-11-26",a,cross(10,1,100.),cross(14,-1,108.),375)
        self.assertEqual(row["mfe_points"],18.)
        self.assertEqual(row["mae_points"],1.)
        self.assertEqual(row["signed_end_move_points"],8.)
        self.assertEqual(row["giveback_points"],10.)
        self.assertAlmostEqual(row["capture_fraction"],8/18)
        self.assertEqual(row["minutes_to_favorable_extreme"],2)
        self.assertEqual(row["minutes_from_favorable_extreme_to_end"],2)
        self.assertEqual(row["entry_reference_open"],108.)
        self.assertEqual(row["exit_reference_open"],108.)
        self.assertEqual(row["delayed_net_proxy_bps"],-5.)

    def test_bearish_trough_recovery_and_censoring(self):
        a=bars()
        a[11]=[100.,101.,82.,84.,1.]
        a[12]=[84.,93.,83.,91.,1.]
        row=p.path_row("2026-11-26",a,cross(10,-1,100.),cross(12,1,91.),375)
        self.assertEqual(row["favorable_extreme_price"],82.)
        self.assertEqual(row["mfe_points"],18.)
        self.assertEqual(row["mae_points"],1.)
        self.assertEqual(row["signed_end_move_points"],9.)
        self.assertEqual(row["giveback_points"],9.)
        censored=p.path_row("2026-11-26",a,cross(10,-1,100.),None,13)
        self.assertEqual(censored["state"],"censored_missing_bar")
        self.assertIsNone(censored["delayed_net_proxy_bps"])
        self.assertEqual(p.summarize([row,censored])["complete_paths"],1)
        self.assertEqual(p.summarize([row,censored])["censored_paths"],1)

    def test_reverse_before_entry_and_unobserved_exit_are_not_fills(self):
        a=bars()
        early=p.path_row("2026-11-26",a,cross(10,1,100.),cross(11,-1,100.),375)
        self.assertEqual(early["delayed_reference_state"],"opposite_signal_before_or_at_entry")
        late=p.path_row("2026-11-26",a,cross(10,1,100.),cross(374,-1,100.),375)
        self.assertEqual(late["delayed_reference_state"],"reference_unobserved")
        self.assertIsNone(late["exit_reference_open"])

    def test_causal_cross_sequence_and_gap_guard(self):
        previous=bars()
        previous[:,0:4]=np.linspace(120,100,375)[:,None]
        a=bars(100.)
        a[:20,:4]=140.
        a[20:40,:4]=80.
        a[40:,:4]=140.
        crosses,prefix,state=p.session_crosses(a,previous)
        self.assertEqual(prefix,375)
        self.assertEqual(state,"complete_regular_prefix")
        self.assertGreaterEqual(len(crosses),3)
        self.assertEqual([x["direction"] for x in crosses[:3]],[1,-1,1])
        changed=a.copy();changed[40:,:4]=60.
        earlier,_,_=p.session_crosses(changed,previous)
        self.assertEqual([x for x in crosses if x["minute"]<40],
                         [x for x in earlier if x["minute"]<40])
        a[40]=np.nan
        limited,prefix,state=p.session_crosses(a,previous)
        self.assertEqual(prefix,40)
        self.assertEqual(state,"current_gap")
        self.assertTrue(all(x["minute"]<40 for x in limited))
        self.assertEqual(p.session_crosses(a,None)[2],"prior_complete_weekday_unavailable")
