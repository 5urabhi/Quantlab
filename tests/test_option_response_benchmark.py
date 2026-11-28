from datetime import date,timedelta
from unittest import TestCase

import numpy as np

from scripts import benchmark_option_response as b


def quote(day,side,strike,price,**extra):
    return {"session_ist":day,"expiry_flag":"MONTH","expiry_code":1,
            "side":side,"strike":strike,"open":price,"close":price,
            "volume":100.,"oi":1000.,"iv":15.,**extra}


class OptionResponseTests(TestCase):
    def test_signal_only_selection_and_delayed_exact_strike_labels(self):
        day="2025-11-27";a=np.full((375,5),63000.)
        table={}
        for minute,price in ((54,90.),(59,100.),(61,110.),(66,120.)):
            table[b.r._stamp(day,minute)]={("CALL",63000.):quote(day,"CALL",63000.,price)}
        first=b.decision_rows(day,59,a,table,np.zeros(len(b.INDEX_FEATURES)))[0]
        self.assertEqual(first["state"],"scored_conditional_ohlc")
        self.assertEqual(first["entry_reference_utc"],b.r._stamp(day,61))
        self.assertEqual(first["exit_reference_utc"],b.r._stamp(day,66))
        np.testing.assert_allclose(first["target"],[20.,10.])
        table[b.r._stamp(day,66)]={("CALL",63000.):quote(day,"CALL",63000.,140.),
                                  ("CALL",63100.):quote(day,"CALL",63100.,1000.)}
        second=b.decision_rows(day,59,a,table,np.zeros(len(b.INDEX_FEATURES)))[0]
        np.testing.assert_array_equal(first["x"],second["x"])
        np.testing.assert_allclose(second["target"],[40.,30.])
        table[b.r._stamp(day,66)]={("CALL",63100.):quote(day,"CALL",63100.,140.)}
        third=b.decision_rows(day,59,a,table,np.zeros(len(b.INDEX_FEATURES)))[0]
        self.assertEqual(third["state"],"exit_unobserved")

    def test_missing_outcomes_and_chronological_pairs(self):
        days=[(date(2025,1,1)+timedelta(days=i)).isoformat() for i in range(80)]
        rows=[]
        for i,day in enumerate(days):
            for j in range(4):
                z=float((-1)**(i+j))
                rows.append({"session":day,"minute":59+5*j,"side":"CALL","strike":63000.,
                             "expiry_family":"MONTH:1","signal_close":100.,"index_close":63000.,
                             "x":np.full(len(b.FEATURES)+len(b.INDEX_FEATURES),z,dtype=np.float32),
                             "bucket":("CALL",0,0),"decision_utc":b.r._stamp(day,60+5*j),
                             "entry_reference_utc":b.r._stamp(day,61+5*j),
                             "exit_reference_utc":b.r._stamp(day,66+5*j),
                             "state":"scored_conditional_ohlc","entry_open":100.,"exit_open":100.+z,
                             "target":np.array([z,z])})
            rows.append({**rows[-1],"state":"exit_unobserved","decision_utc":b.r._stamp(day,90)})
        report,journal=b.assess(rows,b.m.split_days(days))
        self.assertEqual(report["state"],"assessed_conditional_premium_only")
        self.assertEqual(report["coverage"]["evaluation"]["states"],
                         {"scored_conditional_ohlc":64,"exit_unobserved":16})
        self.assertEqual(len(journal),80)
        self.assertTrue(all(r["session"] in days[-16:] for r in journal))
        self.assertTrue(all(r["option_only_predicted_exit_premium"] is None for r in journal
                            if r["state"]!="scored_conditional_ohlc"))
        self.assertTrue(all(set(r)==set(journal[0]) for r in journal))
        self.assertIn("minus_option_only",report["models"]["option_plus_index"])
