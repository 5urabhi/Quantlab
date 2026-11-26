from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import sqlite3
import numpy as np
from workstation_api import alpha_model_registry as r, constituent_alpha as a

def samples(first,n):
    out=[]
    for i in range(n):
        day=(first+timedelta(days=i//6)).isoformat()
        cls=i%3-1
        out.append({"session":day,"decision_utc":day+"T05:"+str(i%6).zfill(2)+":00+00:00",
                    "index":[float(cls),float(i%5)],"full":[float(cls),float(i%5),1.],
                    "class":cls,"return_bps":float(cls*20)})
    return out

class RegistryTests(TestCase):
    def test_portable_model_and_no_backdated_monitor(self):
        train=samples(date(2026,1,1),90);cal=samples(date(2026,2,1),36);test=samples(date(2026,3,1),36)
        dates=[sorted({x["session"] for x in rows}) for rows in (train,cal,test)]
        fit=a._fit("index_logistic",train)
        temp=a._calibrate(a._predict(fit,cal),cal)
        with TemporaryDirectory() as tmp,patch.object(a,"_root",return_value=Path(tmp)):
            ident=r.freeze("index_logistic",fit,temp,train,cal,test,source="prospective",policy=a.policy_for(15),horizon=15,dates=dates)
            self.assertEqual(len(ident),64)
            self.assertEqual(ident,r.freeze("index_logistic",fit,temp,train,cal,test,source="prospective",policy=a.policy_for(15),horizon=15,dates=dates))
            artifact=r.load(ident)
            self.assertFalse(artifact["live_approved"])
            np.testing.assert_allclose(r.predict(artifact,test),a._temperature(a._predict(fit,test),temp))
            self.assertEqual(len(r.list_candidates()),1)
            with patch.object(a,"_read",side_effect=lambda:sqlite3.connect(":memory:")),patch.object(a,"_days",return_value=[]) as days:
                report=r.monitor(model_id=ident,now=datetime(2026,11,25,tzinfo=timezone.utc))
            self.assertEqual(days.call_args.kwargs["start_session"],(date.fromisoformat(dates[2][-1])+timedelta(days=1)).isoformat())
            self.assertEqual(report["state"],"insufficient_later_evidence")
            self.assertIsNone(report["deterioration_flag"])
            with self.assertRaises(ValueError):
                r.freeze("index_logistic",fit,temp,train,cal,test,source="prospective",policy=a.policy_for(15),horizon=15,dates=[dates[0],dates[0],dates[2]])
