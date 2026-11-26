from datetime import date,datetime,timedelta,timezone
from unittest import TestCase
from unittest.mock import patch
import numpy as np
from workstation_api import fitted_alpha as f

def samples():
    rng=np.random.default_rng(419)
    rows=[]
    for day in range(12):
        d=(date(2026,9,1)+timedelta(days=day)).isoformat()
        for i in range(20):
            cls=(i//5+day)%3-1
            x=list(rng.normal(cls*2,.3,size=4))
            t=datetime.fromisoformat(d+"T05:00:00+00:00")+timedelta(minutes=6*i)
            rows.append({"session":d,"decision_utc":t.isoformat(),"target_utc":(t+timedelta(minutes=5)).isoformat(),
                         "index":x,"full":x+[float(cls)],"class":cls,"return_bps":float(cls*20),
                         "reference_price":63000.,"regime":"range"})
    return rows

class FittedAlphaTests(TestCase):
    def test_hmm_filter_cannot_see_future_observations(self):
        rows=samples()
        model=f._fit_regimes(rows[:160],5)
        self.assertIsNotNone(model["hmm"])
        test=rows[160:180]
        before=f._probabilities(model,test,5,"hmm")
        changed=[dict(r) for r in test]
        changed[-1]["index"]=[100.,100.,100.,100.]
        after=f._probabilities(model,changed,5,"hmm")
        np.testing.assert_allclose(before[:-1],after[:-1])
        np.testing.assert_allclose(before.sum(axis=1),np.ones(len(test)))
        self.assertEqual(len(f._groups(test[:5]+test[6:],5)),2)

    def test_session_close_hmm_unavailable_and_optional_not_substituted(self):
        rows=samples()
        self.assertIsNone(f._fit_regimes(rows[:160],0)["hmm"])
        with patch.object(f.importlib.util,"find_spec",return_value=None):
            self.assertEqual(f._optional_fit("lightgbm",rows[:160],rows[160:180],rows[180:]),(None,"optional_dependency_missing"))

    def test_matched_advanced_comparisons(self):
        rows=samples()
        baseline={name:{"brier":1.} for name in ("training_class_prior","index_logistic","constituent_logistic")}
        with patch.object(f.importlib.util,"find_spec",return_value=None):
            methods,states,records=f.assess(rows[:160],rows[160:200],rows[200:],5,baseline)
        self.assertEqual(states["constituent_xgboost"],"optional_dependency_missing")
        self.assertIn("constituent_hmm_logistic",methods)
        self.assertTrue(all(r["eligible_samples"]==40 for r in methods.values()))
        self.assertEqual(len(records),40*len(methods))
