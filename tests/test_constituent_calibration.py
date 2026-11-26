from datetime import date,timedelta
from unittest import TestCase
from workstation_api import constituent_calibration as c

class CalibrationTests(TestCase):
    def cohort(self,days,start,reverse=False):
        rows=[]
        for i in range(days):
            day=(start+timedelta(days=i)).isoformat()
            for signal in ("UP","DOWN"):
                for j in range(5):
                    correct=(j<4) != reverse
                    outcome=signal if correct else "UP" if signal=="DOWN" else "DOWN"
                    rows.append({"session_ist":day,"pressure":signal,"volume_pressure":signal,"ema_rsi":signal,"outcome":outcome})
        return rows
    def test_insufficient_support_withholds_estimates(self):
        rows=self.cohort(2,date(2025,1,1))
        self.assertIsNone(c.evaluate(rows,rows)["pressure"]["probability_by_call"])
    def test_frozen_holdout_gate_without_refit(self):
        train=self.cohort(30,date(2025,1,1))
        test=self.cohort(20,date(2025,3,1))
        good=c.evaluate(train,test)["pressure"]
        self.assertEqual(good["state"],"passes_predeclared_descriptive_gate")
        self.assertGreater(good["brier_skill"],0)
        self.assertAlmostEqual(good["probability_by_call"]["UP"],121/152)
        reversed_test=self.cohort(20,date(2025,3,1),True)
        bad=c.evaluate(train,reversed_test)["pressure"]
        self.assertEqual(bad["state"],"fails_predeclared_gate")
        self.assertIsNone(bad["probability_by_call"])
        self.assertEqual(good["groups"]["UP"]["candidate_up_probability"],bad["groups"]["UP"]["candidate_up_probability"])
