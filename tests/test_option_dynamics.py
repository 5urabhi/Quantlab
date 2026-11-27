from datetime import date,timedelta
from unittest import TestCase,skipIf
from types import SimpleNamespace
import numpy as np
from scripts import benchmark_option_response as b
from scripts import option_dynamics as o
try:
    import torch
except ImportError:
    torch=None


class OptionDynamicsDataTests(TestCase):
    def test_same_strike_across_rolling_offsets_and_iv_clock(self):
        day="2026-01-05"
        raw=np.full((375,8),np.nan);other=raw.copy()
        raw[54]=[63000,90,91,89,90,100,1000,15]
        raw[59]=[63000,100,101,99,100,100,1000,16]
        other[61]=[63000,110,111,109,110,100,1000,17]
        other[66]=[63000,120,121,119,120,100,1000,18]
        groups={("MONTH",1,"CALL","ATM+4"):{day:(raw,np.zeros(375,bool))},
                ("MONTH",1,"CALL","ATM+5"):{day:(other,np.zeros(375,bool))}}
        table=o.near_month_table(SimpleNamespace(groups=groups),day)
        a=np.full((375,5),63000.)
        result=b.decision_rows(day,59,a,table,np.zeros(7),extended=True)[0]
        np.testing.assert_allclose(result["target"],[20,10])
        self.assertEqual(result["iv_target"],2.)
        self.assertEqual(result["iv_exit_reference_utc"],b.r._stamp(day,67))
        other[66,0]=63100
        table=o.near_month_table(SimpleNamespace(groups=groups),day)
        second=b.decision_rows(day,59,a,table,np.zeros(7),extended=True)[0]
        np.testing.assert_array_equal(result["x"],second["x"])
        self.assertEqual(second["state"],"exit_unobserved")
        self.assertIsNone(second["iv_target"])


@skipIf(torch is None,"Optional PyTorch dependency not installed")
class OptionDynamicsModelTests(TestCase):
    def test_neural_predicts_unresolved_candidates_and_separate_iv(self):
        torch.set_num_threads(1)
        days=[(date(2025,1,1)+timedelta(days=i)).isoformat() for i in range(12)]
        rows=[]
        for i,day in enumerate(days):
            for j in range(10):
                z=float((-1)**(i+j))
                rows.append({"session":day,"x":np.array([z,np.nan,j],np.float32),
                             "target":np.array([z,z]),"iv_target":z,"signal_close":100.})
        train=rows;val=rows[:20];evaluation=[rows[0],{"session":days[-1],"x":np.array([0.,np.nan,1.],np.float32)}]
        result=o.fit(train,val,evaluation,3,device_name="cuda" if torch.cuda.is_available() else "cpu",epochs=1)
        reg,raw,cal,iv=result["predictions"]
        self.assertEqual(reg.shape,(2,2));self.assertTrue(np.isfinite(cal).all())
        self.assertTrue(np.isfinite(iv).all());self.assertEqual(result["diagnostics"]["selected_epoch"],1)
