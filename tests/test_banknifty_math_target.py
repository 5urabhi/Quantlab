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
            move=m.required_move(63000.,63000.,10/365,iv,side,premium,30,30)
            self.assertGreater(sign*move,0.)
            exit_=m.price(63000.+move,63000.,10/365-5/(365*1440),iv,side)
            self.assertAlmostEqual(float(m._net_array(premium,exit_,30,30)),.10,places=6)
        self.assertIsNone(m.implied_vol(63000,62000,.02,1,"CALL"))

    def test_scenario_target_trigger_not_realized_profit(self):
        # Signal m; entry m+2. First eligible close triggers, exit m+4.
        op=np.array([[100,100,100,95,95,95,95]],float)
        cl=np.array([[100,120,120,120,120,120,120]],float)
        out=m._forecast_returns(op,cl,5,30,30)
        self.assertEqual(out["target_probability"],1.)
        self.assertEqual(out["realized_target_probability"],0.)
        self.assertLess(out["expected_net_return"],0.)

    def test_stop_precedes_later_target_and_timeout(self):
        op=np.array([[100,100,100,90,130,130,130],[100,100,100,100,100,100,100]],float)
        cl=np.array([[100,90,130,130,130,130,130],[100,100,100,100,100,100,100]],float)
        out=m._forecast_returns(op,cl,5,30,30)
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

    def test_qualification_requires_positive_stress_and_support(self):
        good={"scored_trades":10,"daily_coverage":{"days_with_scored_trade":5},
              "conditional_net_inr":200.,"stress_utility_inr":10.}
        row={"lanes":{"flat_30_inr_per_order":{"metrics":dict(good)}}}
        self.assertTrue(m._qualified(row))
        row["lanes"]["flat_30_inr_per_order"]["metrics"]["stress_utility_inr"]=-1.
        self.assertFalse(m._qualified(row))

    def test_flat_cost_matches_replay_and_does_not_double_count(self):
        for units in (30,90):
            modeled=float(m._net_array(300.,332.,units,30.))
            actual,charges=r._net(300.,332.,units,0,fixed_order_cost=30.)
            self.assertEqual(charges,60.)
            self.assertEqual(actual,32*units-60)
            self.assertEqual(r._fund(300.,units,0,fixed_order_cost=30.),300*units+60)
            self.assertAlmostEqual(modeled,actual/(300*units),places=10)
        with self.assertRaises(ValueError):
            r._net(300.,332.,30,35,fixed_order_cost=30.)

    def test_flat_cost_marks_and_exit_fill(self):
        day="2026-10-06";strike=63000
        signal={"session":day,"minute":4,"side":"CALL","spot":63000.,"features":[],
                "decision_utc":r._stamp(day,5),"entry_utc":r._stamp(day,6)}
        def quote(p):
            return {"session_ist":day,"expiry_flag":"MONTH","expiry_code":1,"open":p,"close":p,"volume":100}
        table={r._stamp(day,j):{("CALL",strike):quote(p)} for j,p in [(6,300.),(7,332.),(8,330.),(9,332.),(10,332.),(11,332.)]}
        bars={j:(63000.,63000.,63000.,63000.,100) for j in range(375)}
        episode=r._episode(signal,table,bars,hold=5,lot_size=30,max_lots=1,
                           risk_budget=12000,bps=0,fixed_order_cost=30.,
                           candidate=(0,1,strike,30,9060.,300.))
        result=r._exit(episode,"fixed_stop")
        self.assertEqual(result["reason"],"target")
        self.assertEqual(result["fees"],60.)
        self.assertEqual(result["net"],900.)
        self.assertAlmostEqual(result["net_return"],.10)
        self.assertTrue(result["target_realized"])
