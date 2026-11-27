from datetime import date,timedelta
from unittest import TestCase

import numpy as np

from scripts import benchmark_direction_gate as b


class DirectionGateTests(TestCase):
    def test_completed_input_delayed_label_and_missing_outcome(self):
        bars=np.full((375,5),63000.)
        bars[17,0]=63000.
        bars[22,0]=63100.
        x,out=b.sample(bars,15)
        self.assertEqual(out[0:2],(63000.,63100.))
        self.assertEqual(out[-1],1)
        bars[22,0]=62900.
        x2,out2=b.sample(bars,15)
        np.testing.assert_array_equal(x,x2)
        self.assertEqual(out2[-1],-1)
        bars[22,0]=63010.
        self.assertEqual(b.sample(bars,15)[1][-1],0)
        bars[20]=np.nan
        self.assertIsNone(b.sample(bars,15)[1])
        self.assertIsNone(b.sample(bars,14))
        self.assertIsNone(b.sample(bars,368))

    def test_no_trade_is_zero_and_flat_not_directional_hit(self):
        days=np.array(["2025-01-02"]*3)
        stats,net=b._action_metrics(np.array([1,-1,0]),np.array([0,-1,1]),
                                    np.array([1.,-12.,20.]),days)
        np.testing.assert_array_equal(net,[-4.,7.,0.])
        self.assertEqual(stats["material_hit_rate"],.5)
        self.assertEqual(stats["flat_rate"],.5)

    def test_fixed_chronological_evaluation_and_gate(self):
        dates=[(date(2025,1,1)+timedelta(days=i)).isoformat() for i in range(80)]
        days=np.repeat(dates,15);minutes=np.tile(np.arange(19,34),80)
        labels=np.tile([-1,0,1],400)
        x=np.zeros((len(days),len(b.FEATURES)),dtype=np.float32)
        x[:,0]=labels
        moves=10.*labels
        data={"days":days,"minutes":minutes,"x":x,"label":labels,"move":moves,
              "entry":np.full(len(days),63000.),"exit":63000.*(1+moves/10000)}
        report,journal=b.assess(data,b.m.split_days(dates))
        self.assertEqual(report["training_rows"],48*3)
        self.assertEqual(report["evaluation_rows"],16*15)
        self.assertEqual(len(journal),16*15)
        self.assertTrue(all(row["session"] in dates[-16:] for row in journal))
        self.assertFalse(report["retrospective_gate"]["minimum_calls_and_sessions"])
        self.assertEqual(report["state"],"direction_not_qualified")
        self.assertIn("model_minus_clock_prior_calibrated",report["paired_brier"])
