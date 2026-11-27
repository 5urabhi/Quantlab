from datetime import date,timedelta
from unittest import TestCase,skipIf
import numpy as np

from scripts import benchmark_market_dynamics as d

try:
    import torch
    from workstation_api import banknifty_sequence_models as net
except ImportError:
    torch=None;net=None


def bars(price=100.):
    a=np.tile([price,price,price,price,100.],(375,1)).astype(float)
    return a


class DynamicsDataTests(TestCase):
    def test_causal_asset_features_and_prior_levels(self):
        a=bars();prior=bars()
        prior[:,1]=110.;prior[:,2]=90.
        a[:20,:4]=101.;a[20:,:4]=102.
        f=d.asset_features(a,prior,[100.]*61)
        self.assertEqual(f.shape,(375,len(d.ASSET_FIELDS)))
        col=lambda key:d.ASSET_FIELDS.index(key)
        self.assertAlmostEqual(f[15,col("previous_high_distance_pct")],100*(101-110)/101,places=5)
        self.assertTrue(np.isnan(f[13,col("opening_15m_high_distance_pct")]))
        self.assertEqual(f[14,col("opening_15m_high_distance_pct")],0.)
        changed=a.copy();changed[20:,:4]=200.
        np.testing.assert_array_equal(f[:20],d.asset_features(changed,prior,[100.]*61)[:20])
        a[20]=np.nan
        self.assertTrue(np.isnan(d.asset_features(a,prior,[])[20:]).all())
        missing=d.asset_features(bars(),None,[])
        self.assertEqual(missing[15,col("prior_complete")],0.)
        self.assertTrue(np.isnan(missing[15,col("previous_high_distance_pct")]))

    def test_delayed_multihorizon_labels_no_future_exit_extreme(self):
        a=bars()
        a[15]=[100.,200.,50.,100.,100.] # latency bar not in outcome
        a[16]=[100.,101.,99.8,100.5,100.]
        a[17]=[100.5,300.,1.,100.5,100.]
        ms,y,c,mask,scheduled=d.labels_for_session(a)
        self.assertEqual(ms[0],14)
        np.testing.assert_allclose(y[0,0],[50.,100.,20.],atol=.001)
        self.assertEqual(c[0,0],2)
        self.assertTrue(mask[0,0])
        self.assertFalse(scheduled[-1,-1])
        a[17]=np.nan
        _,y,c,mask,scheduled=d.labels_for_session(a)
        self.assertTrue(scheduled[0,0]);self.assertFalse(mask[0,0])

    def test_padded_windows_training_only_aux_and_identity(self):
        dates=["2026-01-05","2026-01-06"]
        idx={day:bars() for day in dates}
        stock={"NSE_EQ:1":{dates[0]:bars()},"NSE_EQ:2":{dates[1]:bars()}}
        membership={dates[0]:{"A":"NSE_EQ:1"},dates[1]:{"B":"NSE_EQ:2"}}
        data=d.build(idx,stock,membership,{}, {},{}, {},{},(),(),([dates[0]],[],[dates[1]]))
        self.assertIn("NSE_EQ:1",data["identities"]);self.assertNotIn("NSE_EQ:2",data["identities"])
        rows=np.array([0]);fit=d.fit_aux(data,rows)
        x,z=d.windows(data,rows,True,fit)
        self.assertEqual(x.shape,(1,30,len(data["identities"]),2*len(d.ASSET_FIELDS)))
        self.assertTrue((x[0,:15]==0).all())
        self.assertTrue((x[0,15:,0,0]==1).all())
        self.assertTrue(np.isfinite(x).all() and np.isfinite(z).all())
        self.assertTrue(np.isnan(data["grid"][1,:,1]).all())
        data["grid"][0,15:]*=99
        np.testing.assert_array_equal(x,d.windows(data,rows,True,fit)[0])
        data["aux"][1]=999
        np.testing.assert_array_equal(fit["mean"],d.fit_aux(data,rows)["mean"])


@skipIf(torch is None,"Optional PyTorch dependency not installed")
class DynamicsModelTests(TestCase):
    @classmethod
    def setUpClass(cls):torch.set_num_threads(1)

    def test_attention_padding_and_coherent_multitask_backward(self):
        b,t,a,c=3,30,4,8
        x=torch.zeros(b,t,a,c);x[:,15:,0,0]=1
        aux=torch.zeros(b,t,2)
        model=net.MarketDynamics(a,c,2,len(d.HORIZONS))
        logits,reg=model(x,aux)
        self.assertEqual(tuple(logits.shape),(b,6,3))
        self.assertTrue(bool(torch.isfinite(logits).all()))
        self.assertTrue(bool((reg[:,:,1]>=reg[:,:,0].clamp_min(0)).all()))
        self.assertTrue(bool((reg[:,:,2]>=(-reg[:,:,0]).clamp_min(0)).all()))
        mask=torch.ones(b,6);mask[:,5]=0
        target=torch.zeros(b,6,3);labels=torch.ones(b,6,dtype=torch.long)
        loss=net.dynamics_objective((logits,reg),labels,target,mask,torch.ones(b))
        target[:,5]=1e6;labels[:,5]=0
        other=net.dynamics_objective((logits,reg),labels,target,mask,torch.ones(b))
        self.assertAlmostEqual(float(loss),float(other),places=6)
        loss.backward()
        self.assertTrue(any(p.grad is not None and bool(torch.isfinite(p.grad).all()) for p in model.parameters()))

    def test_small_training_and_unresolved_journal(self):
        days=[(date(2025,1,1)+timedelta(days=i)).isoformat() for i in range(6)]
        grid=np.zeros((6,375,2,len(d.ASSET_FIELDS)),np.float32);grid[:,:,0,0]=1
        di=np.repeat(np.arange(6),3);minutes=np.tile([19,24,29],6)
        y=np.zeros((18,6,3),np.float32);cl=np.tile(np.arange(3),6)[:,None].repeat(6,axis=1)
        y[:,:,0]=(cl-1)*10;y[:,:,1]=np.maximum(y[:,:,0],0);y[:,:,2]=np.maximum(-y[:,:,0],0)
        ok=np.ones((18,6),bool);ok[-1,-1]=False
        data={"grid":grid,"aux":np.zeros((6,375,1),np.float32),"days":np.asarray(days)[di],
              "day_index":di,"minutes":minutes,"y":y,"classes":cl,"mask":ok,
              "scheduled":np.ones_like(ok),"available":np.zeros((6,375,5),bool)}
        tr=np.arange(12);va=np.arange(12,15);te=np.arange(15,18)
        fit=d.fit_aux(data,tr)
        result=d.fit_neural(data,tr,va,te,fit,joint=True,epochs=1,batch=3,device=torch.device("cpu"),progress=None)
        self.assertEqual(result["selected_epoch"],1)
        self.assertEqual(result["evaluation"][0].shape,(3,6,3))
        rows=list(d.journal_rows(data,te,{"joint":result},{"joint":result["evaluation"][0]}))
        self.assertEqual(len(rows),18);self.assertFalse(rows[-1]["outcome_observed"])
        self.assertIsNone(rows[-1]["actual_return_bps"])
        self.assertIsNotNone(rows[-1]["joint_up_probability"])
