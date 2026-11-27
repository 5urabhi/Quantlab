"""Synthetic mathematical and causal execution checks, not market evidence."""
from datetime import date,timedelta
from unittest import TestCase
from unittest.mock import patch
import numpy as np

from workstation_api import banknifty_math_target as m, cpr_hybrid_research as r


class BankNiftyMathTests(TestCase):
    def test_price_inversion_and_required_move_both_sides(self):
        for side,sign in (("CALL",1),("PUT",-1)):
            premium=float(m.price(63000.,63000.,10/365,.18,side))
            iv=m.implied_vol(63000.,63000.,10/365,premium,side)
            self.assertAlmostEqual(iv,.18,places=6)
            move=m.required_move(63000.,63000.,10/365,iv,side,premium,30,35)
            self.assertGreater(sign*move,0.)
            exit_=m.price(63000.+move,63000.,10/365-5/(365*1440),iv,side)
            self.assertAlmostEqual(float(m._net_array(premium,exit_,30,35)),.10,places=6)
        self.assertIsNone(m.implied_vol(63000,62000,.02,1,"CALL"))

    def test_scenario_target_trigger_not_realized_profit(self):
        # Signal m; entry m+2. First eligible close triggers, exit m+4.
        op=np.array([[100,100,100,95,95,95,95]],float)
        cl=np.array([[100,120,120,120,120,120,120]],float)
        out=m._forecast_returns(op,cl,5,30,35)
        self.assertEqual(out["target_probability"],1.)
        self.assertEqual(out["realized_target_probability"],0.)
        self.assertLess(out["expected_net_return"],0.)

    def test_stop_precedes_later_target_and_timeout(self):
        op=np.array([[100,100,100,90,130,130,130],[100,100,100,100,100,100,100]],float)
        cl=np.array([[100,90,130,130,130,130,130],[100,100,100,100,100,100,100]],float)
        out=m._forecast_returns(op,cl,5,30,35)
        self.assertEqual(out["stop_probability"],.5)
        self.assertEqual(out["target_probability"],0.)
        self.assertEqual(out["negative_probability"],1.)

    def test_past_paths_do_not_read_current_future_or_future_training_days(self):
        def bars(offset):
            return {i:(60000+i*2+offset,60005+i*2+offset,59995+i*2+offset,60001+i*2+offset,100) for i in range(100)}
        days=[(date(2026,8,1)+timedelta(days=i)).isoformat() for i in range(16)]
        index={d:bars(i) for i,d in enumerate(days)}
        day=days[-2]
        first=m.paths(index,days,day,34,5)
        self.assertIsNotNone(first)
        self.assertTrue(all(d<day for d in first["days"]))
        index[day][35]=(70000,71000,69999,71000,100)
        index[days[-1]][35]=(70000,71000,69999,71000,100)
        second=m.paths(index,days,day,34,5)
        np.testing.assert_array_equal(first["opens"],second["opens"])
        np.testing.assert_array_equal(first["closes"],second["closes"])
        self.assertEqual(first["up_probability"],second["up_probability"])

    def test_qualification_requires_both_cost_lanes_and_stress(self):
        good={"scored_trades":10,"daily_coverage":{"days_with_scored_trade":5},
              "conditional_net_inr":200.,"stress_utility_inr":10.}
        row={"lanes":{"35":{"metrics":dict(good)},"75":{"metrics":dict(good)}}}
        self.assertTrue(m._qualified(row))
        row["lanes"]["75"]["metrics"]["stress_utility_inr"]=-1.
        self.assertFalse(m._qualified(row))

    def test_cost_screen_approximately_matches_exact_fee_engine(self):
        approximate=float(m._net_array(100.,115.,30,35.))
        actual,_=r._net(100.,115.,30,35.)
        self.assertAlmostEqual(approximate,actual/(100*30*1.0035),delta=.001)
