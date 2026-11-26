from datetime import datetime,timedelta,timezone
from unittest import TestCase
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory
import numpy as np

from workstation_api import predictive_option_research as r, constituent_alpha as a
from workstation_api import historical_alpha as h, constituent_prospective as p

DAY="2026-11-24"
NOW=datetime(2026,11,24,4,30,tzinfo=timezone.utc)

def row():
    return {"session":DAY,"decision_utc":NOW.isoformat(),"target_utc":(NOW+timedelta(minutes=15)).isoformat(),
            "reference_price":63000.,"index":[0.,0.,0.,0.,0.,50.,44.],"class":1,
            "full":[0.],"regime":"range"}

def leg(side,strike,price):
    return {"side":side,"strike":strike,"close":price,"open":price,"high":price,"low":price,
            "volume":1000,"session_ist":DAY,"expiry_flag":"MONTH","expiry_code":1}

def analogs(family,legs,ratios):
    feature=r._feature(legs,63000.,44.)
    return {(family,cls):{"x":np.tile(feature,(12,1)),"ratios":np.tile(ratios,(12,1)),
                          "anchors":np.arange(12),"days":["day"+str(i%6) for i in range(12)]}
            for cls in a.CLASSES}

class PredictiveOptionsTests(TestCase):
    def test_only_debit_verticals_and_fixed_terms(self):
        first,second=leg("CALL",63000.,100.),leg("CALL",63100.,70.)
        quotes={(v["side"],v["strike"]):v for v in (first,second)}
        candidates=list(r._structures(quotes,63000.))
        self.assertEqual([name for name,_ in candidates].count("bull_call_debit"),1)
        self.assertEqual([name for name,_ in candidates].count("long_call"),2)
        self.assertTrue(all("credit" not in name for name,_ in candidates))
        future={(v["side"],v["strike"]):dict(v) for v in (first,second)}
        future[("CALL",63100.)]["expiry_code"]=2
        self.assertIsNone(r._observations({NOW.isoformat():future},NOW,(first,second)))

    def test_joint_analog_support_and_cost_gate(self):
        first=leg("CALL",63000.,100.)
        pool=analogs("long_call",(first,),[1.5])
        result=r._scenarios("long_call",(first,),row(),[.1,.2,.7],pool)
        values,weights,support=result
        self.assertAlmostEqual(float(sum(weights)),1.)
        self.assertTrue(np.allclose(values,150.))
        self.assertEqual(support["1"]["anchors"],12)
        # Replicated rows from a single training anchor cannot inflate support.
        pool[("long_call",1)]["anchors"][:]=0
        self.assertIsNone(r._scenarios("long_call",(first,),row(),[.1,.2,.7],pool))

    def test_selection_does_not_read_entry_or_exit_quotes(self):
        first=leg("CALL",63000.,100.)
        pool=analogs("long_call",(first,),[1.5])
        signal,entry,target=r._clock(row())
        table={signal.isoformat():{("CALL",63000.):first},
               entry.isoformat():{("CALL",63000.):leg("CALL",63000.,101.)},
               target.isoformat():{("CALL",63000.):leg("CALL",63000.,150.)}}
        args=(row(),table,[.1,.2,.7],pool,4250.,30,3,25.,"zerodha")
        chosen,_=r._select(*args)
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen["lots"],1)
        scored=r._outcome(chosen,row(),table,4250.,25.,"zerodha")
        self.assertEqual(scored["state"],"scored_conditional_ohlc")
        self.assertGreater(scored["net_pnl_inr"],scored["stress_net_pnl_inr"])
        table[target.isoformat()]={}
        selected,_=r._select(*args)
        self.assertEqual(chosen,selected)
        self.assertEqual(r._outcome(selected,row(),table,4250.,25.,"zerodha")["state"],"exit_unobservable")
        rejected,_=r._select(row(),table,[.1,.2,.7],pool,1000.,30,3,25.,"zerodha")
        self.assertIsNone(rejected)

    def test_no_training_evidence_exports_audit(self):
        raw={"historical_index":{"intervals_sha256":"a"*64}}
        interval=[{"symbol":"A","valid_from":"2026-01-01","valid_to":""}]
        with TemporaryDirectory() as tmp,patch.object(a,"_root",return_value=Path(tmp)), \
             patch.object(h,"_batch",return_value=(raw,NOW.date(),NOW.date()+timedelta(days=1),interval,{"A":"NSE_EQ:1"})), \
             patch.object(h,"_sources",return_value=({}, {}, {}, {})),patch.object(r,"_load_options") as load:
            result=r.run(batch_id="batch_"+"a"*16)
            self.assertEqual(result["state"],"insufficient_matched_evidence")
            self.assertTrue(a.result_path(result["audit_id"],audit=True).is_file())
            self.assertFalse(result["broker_orders_enabled"])
            load.assert_not_called()

    def test_new_horizons_do_not_change_original_protocol(self):
        self.assertEqual(p.protocol_for(30),p.PROTOCOL_HASH)
        self.assertEqual(a.policy_for(30),a.POLICY_HASH)
        self.assertNotEqual(p.protocol_for(15),p.PROTOCOL_HASH)
        self.assertEqual(a.split_sizes(0),(60,20,40))
        self.assertEqual(p.target_for(NOW,0).astimezone(h.IST).strftime("%H:%M:%S"),"15:29:20")
