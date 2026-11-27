from tempfile import TemporaryDirectory
from pathlib import Path
from unittest import TestCase,skipIf
import numpy as np
from scripts import benchmark_market_dynamics as d
from scripts import market_dynamics_v3 as v
from scripts import compare_market_dynamics as compare
try:
    import torch
    from workstation_api import market_dynamics_v3 as net
except ImportError:
    torch=None;net=None


def bars(price=100.):
    return np.tile([price,price,price,price,100.],(375,1)).astype(float)


class V3DataTests(TestCase):
    def test_underlying_grid_pretrain_only_earlier_and_individual_equities(self):
        dates=["2026-01-05","2026-01-06","2026-01-07"]
        index={day:bars() for day in dates}
        equities={"NSE_EQ:1":{day:bars(110.) for day in dates}}
        equities["NSE_EQ:1"][dates[0]][20]=np.nan
        with TemporaryDirectory() as scratch:
            data=d.build(index,equities,{}, {},{}, {},{}, {},(),(),([dates[0]],[dates[1]],[dates[2]]),
                         all_history=True,scratch=Path(scratch),include_options=False,pretraining=True)
            self.assertEqual(data["aux_names"],d.BANK_AUX)
            self.assertFalse(data["available"][:,:,2].any())
            self.assertTrue(np.isnan(data["pretrain_targets"][1:]).all())
            self.assertTrue(np.isfinite(data["pretrain_targets"][0,0,1]).all())
            # 19 -> gap at 20, not a valid next 5m target.
            self.assertTrue(np.isnan(data["pretrain_targets"][0,3,1]).all())
            row=np.flatnonzero((data["day_index"]==1)&(data["minutes"]==14))
            fit=d.fit_aux(data,np.flatnonzero(data["day_index"]==0))
            mem=v.memory_grid(data,True)
            x,z,s,p,sv,pv=v.inputs(data,row,True,fit,mem)
            self.assertEqual(int(sv.sum()),1);self.assertEqual(int(pv.sum()),1)
            self.assertTrue((s[:,1:]==0).all());self.assertTrue((p[:,:-1]==0).all())
            mem[0][1,1:]=999;mem[1][1:]=999
            after=v.inputs(data,row,True,fit,mem)
            for before,new in zip((x,z,s,p,sv,pv),after):np.testing.assert_array_equal(before,new)
            del data

    def test_factorized_validation_rank_penalizes_bad_material_sign(self):
        y=np.array([[0]*6,[2]*6,[1]*6])
        data={"mask":np.ones((3,6),bool),"classes":y,"days":np.asarray(["a","b","c"])}
        p=np.tile([[.8,.1,.1],[.1,.1,.8],[.1,.8,.1]],(6,1,1)).transpose(1,0,2)
        bad=p[:,:,::-1].copy()
        self.assertLess(v.validation_rank(data,np.arange(3),p),v.validation_rank(data,np.arange(3),bad))

    def test_comparison_refuses_unmatched_outcomes(self):
        report={key:[] for key in compare.MATCH_FIELDS}
        report.update(version="v2",horizons=[5],delay_minutes=1,deadband_bps=5,models={"joint":{}})
        key=("2026-01-05","a","b","c","5")
        row={"outcome_observed":"True","actual_class":"1",**{k:"10.0" for k in compare.ACTUAL},
             **{"joint_"+p+"_probability":str(value) for p,value in zip(("down","flat","up"),(.2,.2,.6))},
             **{"joint_predicted_"+p+"_bps":"10.0" for p in ("return","up_excursion","down_excursion")}}
        result=compare.compare((report,{key:row}),(report,{key:row}))
        self.assertEqual(result["horizons"]["5"]["models"]["joint"]["candidate_minus_baseline_brier"]["mean_difference"],0.)
        with self.assertRaises(ValueError):compare.compare((report,{key:row}),(report,{key:{**row,"actual_return_bps":"11"}}))


@skipIf(torch is None,"Optional PyTorch dependency not installed")
class V3ModelTests(TestCase):
    def test_factorized_loss_masks_flat_direction_and_missing_target(self):
        raw=torch.randn(2,2,5,requires_grad=True);target=torch.zeros(2,2,3)
        target[1,0]=torch.tensor([1.,2.,0.])
        mask=torch.tensor([[1.,0.],[1.,1.]])
        loss=net.factorized_loss(raw,target,mask,torch.ones(2));loss.backward()
        self.assertEqual(float(raw.grad[0,0,1]),0.)
        self.assertTrue(bool((raw.grad[0,1]==0).all()))
        lp,reg=net.distribution(raw.detach())
        torch.testing.assert_close(lp.exp().sum(dim=-1),torch.ones(2,2))
        self.assertTrue(bool((reg[...,1]>=reg[...,0].clamp_min(0)).all()))

    def test_multiscale_pretrain_and_finetune_gpu_when_available(self):
        torch.set_num_threads(1)
        device=torch.device("cuda" if torch.cuda.is_available() else "cpu")
        if hasattr(torch.backends,"mha"):torch.backends.mha.set_fastpath_enabled(False)
        amp=device.type=="cuda" and torch.cuda.is_bf16_supported()
        model=net.MarketDynamicsV3(3,8,2,6,width=64).to(device)
        x=torch.zeros(2,30,3,8,device=device);x[:,-10:,0,0]=1;x[:,-5:,1,0]=1
        aux=torch.zeros(2,30,2,device=device)
        s=torch.zeros(2,25,6,device=device);p=torch.zeros(2,60,6,device=device)
        sv=torch.zeros(2,25,dtype=torch.bool,device=device);pv=torch.zeros(2,60,dtype=torch.bool,device=device)
        for pre in (True,False):
            model.zero_grad(set_to_none=True)
            with torch.autocast(device_type=device.type,dtype=torch.bfloat16,enabled=amp):
                raw=model(x,aux,s,p,sv,pv,pretrain=pre)
            self.assertEqual(tuple(raw.shape),(2,3,2,5) if pre else (2,6,5))
            target=torch.zeros(*raw.shape[:-1],3,device=device)
            mask=torch.ones(raw.shape[:-1],device=device);target[...,0]=1
            loss=net.factorized_loss(raw,target,mask,torch.ones(2,device=device))
            self.assertTrue(bool(torch.isfinite(loss)))
            loss.backward()
            self.assertTrue(all(bool(torch.isfinite(q.grad).all()) for q in model.parameters() if q.grad is not None))
            self.assertIsNotNone(model.patch[0].weight.grad)
            self.assertIsNotNone(model.temporal.layers[0].linear1.weight.grad)

    def test_small_training_protocol(self):
        from datetime import date,timedelta
        torch.set_num_threads(1)
        days=[(date(2025,1,1)+timedelta(days=i)).isoformat() for i in range(6)]
        grid=np.zeros((6,375,2,len(d.ASSET_FIELDS)),np.float32);grid[:,:,0,0]=1;grid[:,:,1,0]=1
        di=np.repeat(np.arange(6),3);minutes=np.tile([19,24,29],6)
        classes=np.tile(np.arange(3),6)[:,None].repeat(6,axis=1)
        y=np.zeros((18,6,3),np.float32);y[:,:,0]=(classes-1)*10
        y[:,:,1]=np.maximum(y[:,:,0],0);y[:,:,2]=np.maximum(-y[:,:,0],0)
        targets=np.full((6,75,2,2,3),np.nan,np.float32)
        for i in range(12):targets[di[i],minutes[i]//5]=np.broadcast_to(y[i,:2],(2,2,3))
        data={"grid":grid,"aux":np.zeros((6,375,1),np.float32),"dates":days,"identities":["INDEX:BANKNIFTY","NSE_EQ:1"],
              "equity_identities":["NSE_EQ:1"],"days":np.asarray(days)[di],"day_index":di,"minutes":minutes,
              "classes":classes,"y":y,"mask":np.ones((18,6),bool),"all_history":True,"pretrain_targets":targets}
        tr=np.arange(12);va=np.arange(12,15);te=np.arange(15,18)
        device=torch.device("cuda" if torch.cuda.is_available() else "cpu")
        result=v.fit(data,tr,va,te,d.fit_aux(data,tr),joint=True,epochs=1,batch=3,device=device,
                     progress=None,pretrain_epochs=1,accumulate=2,width=64)
        self.assertEqual(result["selected_epoch"],1)
        self.assertEqual(result["used_pretraining_labels"]["NSE_EQ:1"],[12,12])
        self.assertEqual(result["evaluation"][0].shape,(3,6,3))
        self.assertTrue(np.isfinite(result["evaluation"][1]).all())
