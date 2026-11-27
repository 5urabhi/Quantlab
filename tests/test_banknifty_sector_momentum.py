"""Deterministic unit checks for the BANKNIFTY-only rule comparison."""
from unittest import TestCase
from unittest.mock import patch
from workstation_api import banknifty_sector_momentum as m, cpr_hybrid_research as r


DAY="2026-10-06"


def bars(sign=1):
    return {i:(63000+sign*i*10,63001+sign*i*10,62999+sign*i*10,63000+sign*i*10,100) for i in range(100)}


def quote(strike,premium,side="CALL"):
    return {"session_ist":DAY,"expiry_flag":"MONTH","expiry_code":1,"side":side,"strike":strike,
            "open":premium,"close":premium,"volume":100}


class SectorMomentumTests(TestCase):
    def test_completed_clock_and_missing_data(self):
        idx=bars()
        before=m.signal_z(idx,34)
        self.assertGreater(before,1)
        idx[35]=(70000,71000,69999,71000,100)
        self.assertEqual(m.signal_z(idx,34),before)
        del idx[15]
        self.assertIsNone(m.signal_z(idx,34))

    def test_sector_confirmation_and_reversal(self):
        peers={k:{DAY:bars(s)} for k,s in zip(m.PEERS,(1,1,-1))}
        votes=m.peer_votes(peers,DAY,34)
        self.assertEqual(votes,[1,1,-1])
        self.assertEqual(m.side_for("momentum",2,votes),"CALL")
        self.assertEqual(m.side_for("mean_reversion",2,votes),"PUT")
        self.assertEqual(m.side_for("confirmed_momentum",2,votes),"CALL")
        self.assertIsNone(m.side_for("confirmed_reversion",2,votes))
        self.assertEqual(m.side_for("confirmed_reversion",-2,votes),"CALL")
        self.assertIsNone(m.side_for("momentum",.9,votes))
        del peers[m.PEERS[0]][DAY][32]
        self.assertIsNone(m.peer_votes(peers,DAY,34))

    def test_affordability_and_friction_precede_distance(self):
        table={r._stamp(DAY,34):{
            ("CALL",63000):quote(63000,500),
            ("CALL",63100):quote(63100,20),
            ("CALL",63200):quote(63200,300),
            ("CALL",63300):quote(63300,300),
            ("PUT",63000):quote(63000,300,"PUT")}}
        chosen,counts=m.choose(table,DAY,34,63000,30,12000)
        self.assertEqual(chosen["CALL"][2],63200)
        self.assertEqual(chosen["PUT"][2],63000)
        self.assertEqual(counts["observed"],5)
        self.assertEqual(counts["affordable"],4)
        self.assertEqual(counts["low_friction"],3)
        # A future attractive quote cannot alter the signal-time choice.
        table[r._stamp(DAY,35)]={("CALL",63000):quote(63000,300)}
        self.assertEqual(m.choose(table,DAY,34,63000,30,12000)[0],chosen)

    def test_qualification_flat_cost_and_minimum_support(self):
        good={"scored_trades":20,"daily_coverage":{"days_with_scored_trade":10},
              "conditional_net_inr":100.,"stress_utility_inr":50.}
        lanes={"flat_30_inr_per_order":dict(good)}
        self.assertTrue(m.qualified(lanes,minimum_trades=20,minimum_days=10))
        lanes["flat_30_inr_per_order"]["stress_utility_inr"]=-1.
        self.assertFalse(m.qualified(lanes,minimum_trades=20,minimum_days=10))
