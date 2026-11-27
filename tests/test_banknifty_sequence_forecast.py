"""Synthetic regression tests; never access live or historical user files."""
from datetime import date,timedelta
from unittest import TestCase,skipIf
from unittest.mock import patch
import numpy as np
from workstation_api import banknifty_sequence_data as d
from workstation_api import banknifty_sequence_forecast as m
from workstation_api import banknifty_forecast_features as f
from workstation_api import banknifty_candle_forecast as base

try:
    import torch
    from workstation_api import banknifty_sequence_models as net
except ImportError:
    torch=None;net=None


def tiny():
    a=np.zeros((2,375,3,5),dtype=np.float32)
    c=63000+np.arange(375)*.2
    a[:,:,:,0]=c[None,:,None]-.2
    a[:,:,:,1]=c[None,:,None]+.5
    a[:,:,:,2]=c[None,:,None]-.5
    a[:,:,:,3]=c[None,:,None]
    a[:,:,:,4]=100
    a[:,:,0,4]=np.nan;a[:,:,2,4]=np.nan
    a[0,105:110,1,:]=np.nan
    ref=a[[0,1],[120,121],0,3].astype(float)
    y=np.array([[0,.04,.03,.01],[0,-.06,.02,.03]],float)
    return {"grid":a,"day_index":np.array([0,1]),"minutes":np.array([120,121]),
            "days":np.array(["2026-01-05","2026-01-06"]),"ref":ref,
            "y":y,"actual":base.decode(ref,y),"scale":np.array([.03,.04],np.float32),
            "bank_count":1,"bank_slice":slice(1,2),"identities":["INDEX:BANKNIFTY","NSE_EQ:1","INDEX:NIFTY50"],
            "context":np.array([[1.,2.,np.nan,4.],[2.,4.,3.,5.]],np.float32),
            "bank_columns":[1],"option_columns":[2]}


class SequenceDataTests(TestCase):
    def test_raw_shapes_and_future_immutability(self):
        data=tiny()
        for length in d.LOOKBACKS:
            x=d.raw_windows(data,np.array([0]),length)
            self.assertEqual(x.shape,(1,length,3,8))
            self.assertTrue(np.isfinite(x).all())
            self.assertTrue((x[0,:,0,6]==1).all())
            self.assertEqual(x[0,-1,0,3],0)
            other=tiny();other["grid"][0,121:,:,:4]*=2
            np.testing.assert_array_equal(x,d.raw_windows(other,np.array([0]),length))

    def test_missing_banks_masks_and_missing_volume(self):
        data=tiny();x=d.raw_windows(data,np.array([0]),60)
        self.assertTrue((x[0,:,0,7]==0).all())
        self.assertTrue((x[0,:,2,7]==0).all())
        self.assertEqual(int((x[0,:,1,6]==0).sum()),5)
        missing=d.raw_windows(data,np.array([0]),60,drop_banks=np.array([True]))
        self.assertTrue((missing[:,:,1,:]==0).all())
        np.testing.assert_array_equal(x[:,:,0,:],missing[:,:,0,:])
        data["grid"][0,120,1,:]=np.nan
        self.assertTrue((d.raw_windows(data,np.array([0]),60)[:,:,1,:]==0).all())

    def test_context_fit_ignores_future_and_masks_groups(self):
        data=tiny();fit=d.context_fit(data,np.array([0]))
        np.testing.assert_array_equal(fit["keep"],[True,True,False,True])
        other=tiny();other["context"][1]=999
        fit2=d.context_fit(other,np.array([0]))
        np.testing.assert_array_equal(fit["mean"],fit2["mean"])
        x=d.context_windows(data,np.array([0]),fit,drop_banks=np.array([True]))
        self.assertEqual(x.shape,(1,6))
        self.assertEqual(x[0,1],0)
        self.assertEqual(x[0,4],0)

    def test_target_thresholds_and_adaptive_scores(self):
        data=tiny()
        np.testing.assert_array_equal(d.event_targets(data,np.array([0,1])),
                                      [[1,1,0,0,0,0,0],[0,0,0,0,1,1,0]])
        fit=m.adaptive_fit(data,np.array([0]))
        pred,prob,interval=m.adaptive_predict(data,np.array([1]),fit)
        self.assertEqual(pred.shape,(1,4))
        np.testing.assert_array_equal(prob,[[1,1,0,0,0,0,0]])
        self.assertLessEqual(interval[0,0],interval[0,1])
        result=m.score(data,np.array([1]),pred,prob,interval)
        self.assertEqual(result["direction_brier"],1.)
        self.assertEqual(result["rows"],1)

    def test_common_lookback_and_training_asset_identities(self):
        days=["2026-01-05","2026-01-06"]
        grid=tiny()["grid"]
        index={day:grid[j,:,0].astype(float) for j,day in enumerate(days)}
        stocks={"NSE_EQ:1":{days[0]:grid[0,:,1].astype(float)},
                "NSE_EQ:9":{days[1]:grid[1,:,1].astype(float)}}
        membership={days[0]:{"BANKA":"NSE_EQ:1"},days[1]:{"BANKB":"NSE_EQ:9"}}
        data=d.build(index,stocks,membership,{}, {},{},([days[0]],[],[days[1]]))
        self.assertEqual(len(data["minutes"]),2*251)
        self.assertEqual(min(data["minutes"]),119)
        self.assertEqual(max(data["minutes"]),369)
        self.assertIn("NSE_EQ:1",data["identities"])
        self.assertNotIn("NSE_EQ:9",data["identities"])
        self.assertEqual(data["session_audit"][days[1]]["training_known_members"],0)
        self.assertTrue(np.isnan(data["grid"][1,:,1,:]).all())
        self.assertTrue(np.isfinite(data["scale"]).all())


@skipIf(torch is None,"Optional PyTorch dependency not installed")
class TorchSequenceTests(TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_all_architectures_backward_and_probability_order(self):
        data=tiny();rows=np.array([0,1]);fit=d.context_fit(data,rows)
        for kind in net.MODEL_TYPES:
            model=net.MarketSequence(kind,3,8,int(fit["keep"].sum())*2)
            x=torch.from_numpy(d.raw_windows(data,rows,60))
            c=torch.from_numpy(d.context_windows(data,rows,fit))
            candle,probs,interval=model(x,c)
            self.assertEqual(tuple(candle.shape),(2,4))
            self.assertEqual(tuple(probs.shape),(2,7))
            self.assertTrue(bool((candle[:,2:]>=0).all()))
            self.assertTrue(bool((probs[:,1]<=probs[:,0]).all()))
            self.assertTrue(bool((probs[:,4]<=1-probs[:,0]).all()))
            self.assertTrue(bool((probs[:,1:3]>=probs[:,2:4]).all()))
            self.assertTrue(bool((probs[:,4:6]>=probs[:,5:7]).all()))
            self.assertTrue(bool((interval[:,0]<=candle[:,1]).all()))
            self.assertTrue(bool((interval[:,1]>=candle[:,1]).all()))
            loss=net.objective((candle,probs,interval),torch.from_numpy(m._target(data,rows)),
                               torch.from_numpy(d.event_targets(data,rows)),torch.ones(2))
            self.assertTrue(bool(torch.isfinite(loss)))
            loss.backward()
            self.assertTrue(any(p.grad is not None and bool(torch.isfinite(p.grad).all()) for p in model.parameters()))

    def test_missing_target_patch_rejected(self):
        model=net.MarketSequence("transformer",3,8,4)
        with self.assertRaisesRegex(ValueError,"Target index patch missing"):
            model(torch.zeros(1,15,3,8),torch.zeros(1,4))

    def test_small_fit_and_selected_checkpoint(self):
        data=tiny();rows=np.array([0,1])
        fit=d.context_fit(data,rows)
        benchmark=m.score(data,rows,*m.adaptive_predict(data,rows,m.adaptive_fit(data,rows)))
        result=m.fit_one(data,rows,rows,fit,"transformer",15,benchmark,
                         epochs=1,batch=2,device=torch.device("cpu"))
        self.assertEqual(result["epoch"],1)
        self.assertTrue(np.isfinite(result["rank"]))
        self.assertTrue(result["state"])
