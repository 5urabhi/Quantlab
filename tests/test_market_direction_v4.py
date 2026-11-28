"""Causal V4 data, selection, masking, resumption and neural smoke tests."""
from datetime import date,timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,skipIf

import numpy as np
from scripts import benchmark_market_dynamics as d
from scripts import market_dynamics_v3 as v3
from scripts import market_direction_v4 as v
from scripts import benchmark_market_direction_v4 as run

try:
    import torch
    from workstation_api import market_direction_v4 as net
except ImportError:
    torch=None;net=None


def bars(price=100.):
    return np.tile([price,price,price,price,100.],(375,1)).astype(float)


def toy(n=6):
    dates=[(date(2025,1,1)+timedelta(days=i)).isoformat() for i in range(n)]
    fields=d.ASSET_FIELDS+("session_vwap_proxy_distance_pct","session_log_volume")
    grid=np.zeros((n,375,3,len(fields)),np.float32)
    grid[:,:,:,0]=1
    grid[:,:,:,d.ASSET_FIELDS.index("session_prefix_complete")]=1
    di=np.repeat(np.arange(n),3);minutes=np.tile([14,19,24],n)
    classes=np.tile(np.arange(3),n)[:,None].repeat(len(v.HORIZONS),axis=1)
    y=np.zeros((len(di),len(v.HORIZONS),3),np.float32);y[:,:,0]=(classes-1)*10
    y[:,:,1]=np.maximum(y[:,:,0],0);y[:,:,2]=np.maximum(-y[:,:,0],0)
    targets=np.full((n,75,3,2,3),np.nan,np.float32)
    for i in range(len(di)):
        targets[di[i],minutes[i]//5,:2]=np.broadcast_to(y[i,:2],(2,2,3))
        if di[i]>=n-2:targets[di[i],minutes[i]//5,2]=y[i,:2]
    return {"grid":grid,"aux":np.zeros((n,375,1),np.float32),"aux_names":["synthetic"],
            "asset_fields":fields,"horizons":v.HORIZONS,"dates":dates,
            "identities":["INDEX:BANKNIFTY","NSE_EQ:1","NSE_EQ:2"],"equity_identities":["NSE_EQ:1","NSE_EQ:2"],
            "days":np.asarray(dates)[di],"day_index":di,"minutes":minutes,"classes":classes,"y":y,
            "mask":np.ones((len(di),len(v.HORIZONS)),bool),"scheduled":np.ones((len(di),len(v.HORIZONS)),bool),
            "available":np.zeros((n,375,5),bool),"availability_names":d.AVAILABILITY,
            "all_history":True,"pretrain_targets":targets}


class V4DataTests(TestCase):
    def test_eod_last_close_extended_horizons_and_gap(self):
        a=bars();a[-1,1]=104.;a[-1,2]=98.;a[-1,3]=103.
        ms,y,classes,mask,scheduled=d.labels_for_session(a,all_minutes=True,horizons=v.HORIZONS)
        self.assertEqual(int(ms[-1]),372)
        self.assertTrue(scheduled[-1,-1]);self.assertTrue(mask[-1,-1])
        self.assertFalse(scheduled[-1,0])
        np.testing.assert_allclose(y[-1,-1],[300,400,200],atol=1e-4)
        self.assertEqual(classes[-1,-1],2)
        a[20]=np.nan
        ms,y,_,mask,scheduled=d.labels_for_session(a,all_minutes=True,horizons=v.HORIZONS)
        self.assertTrue(scheduled[ms==4,-1][0]);self.assertFalse(mask[ms==4,-1][0])
        self.assertTrue(mask[ms==24,-1][0])
        self.assertTrue(mask[ms==24,v.HORIZONS.index(120)][0])
        old=d.labels_for_session(a,all_minutes=True)
        self.assertEqual(old[1].shape[1],6)
        d.labels_for_session(a,all_minutes=False,horizons=v.HORIZONS)

    def test_vwap_proxy_causal_and_volume_missing_masks(self):
        a=bars();a[1,:4]=110.
        f=d.session_volume_features(a,375)
        self.assertAlmostEqual(float(f[1,0]),100*(110-105)/110,places=5)
        altered=a.copy();altered[2:,:4]=999.
        np.testing.assert_array_equal(f[:2],d.session_volume_features(altered,375)[:2])
        a[2,4]=np.nan
        self.assertTrue(np.isnan(d.session_volume_features(a,375)[2:]).all())
        a=bars();a[:,4]=0
        self.assertTrue(np.isnan(d.session_volume_features(a,375)).all())

    def test_extended_grid_and_v3_default_unchanged(self):
        days=["2026-01-05","2026-01-06","2026-01-07"]
        index={day:bars() for day in days}
        with TemporaryDirectory() as scratch:
            data=d.build(index,{}, {},{}, {},{}, {},{},(),(),([days[0]],[days[1]],[days[2]]),
                all_history=True,scratch=Path(scratch),index_only=True,include_options=False,pretraining=True,
                horizons=v.HORIZONS,extended_features=True)
            self.assertEqual(data["grid"].shape[-1],len(d.ASSET_FIELDS)+2)
            self.assertEqual(data["y"].shape[1],9)
            self.assertTrue(np.isnan(data["pretrain_targets"][1:]).all())
            self.assertAlmostEqual(float(data["grid"][0,0,0,-2]),0.)
            self.assertEqual(len(d.HORIZONS),6)
            del data

    def test_walk_forward_dates_and_fold_known_assets(self):
        data=toy(80);dates=data["dates"]
        part=v.prepare(data,(dates[:40],dates[40:60],dates[60:]),stride=5)
        np.testing.assert_array_equal(part["known"],[True,True,False])
        first=v3.inputs(data,part["te"][:1],True,part["fit"],part["memory"],known_assets=part["known"])
        self.assertEqual(first[0].shape[2],2)
        data["grid"][:,:,2,:]=999
        other=v3.memory_grid(data,True,known_assets=part["known"])
        after=v3.inputs(data,part["te"][:1],True,part["fit"],other,known_assets=part["known"])
        for x,y in zip(first,after):np.testing.assert_array_equal(x,y)
        many=[(date(2023,1,1)+timedelta(days=i)).isoformat() for i in range(200)]
        fs=v.folds(many)
        self.assertEqual(len(fs),3)
        for tr,va,te in fs:
            self.assertLess(tr[-1],va[0]);self.assertLess(va[-1],te[0]);self.assertEqual(len(te),40)
        self.assertEqual(len(set(day for _,_,te in fs for day in te)),120)
        self.assertEqual(fs[-1][2][-1],many[-1])

    def test_selection_requires_full_fixed_matrix_and_ignores_other_scores(self):
        records=[]
        for variant,width in v.CANDIDATES:
            for fold in (1,2,3):
                records.append({"variant":variant,"width":width,"fold":fold,
                    "assessment":{"macro_sign_brier":.20 if (variant,width)==("graph_moe",64) else .25},
                    "evaluation_brier":0. if variant=="plain" else 1.})
        selected,_=v.choose(records)
        self.assertEqual((selected["variant"],selected["width"]),("graph_moe",64))
        with self.assertRaises(ValueError):v.choose(records[:-1])

    def test_run_manifest_resumption_refuses_changed_identity(self):
        with TemporaryDirectory() as tmp:
            folder=Path(tmp);manifest={"test":1}
            first=run.bind_manifest(folder,manifest)
            self.assertEqual(first,run.bind_manifest(folder,manifest))
            with self.assertRaises(ValueError):run.bind_manifest(folder,{"test":2})
            path=folder/"record.json";identity={"manifest":first,"fold":1}
            run.save_json(path,{"identity":identity,"score":.25})
            self.assertEqual(run.record(path,identity)["score"],.25)
            with self.assertRaises(ValueError):run.record(path,{"manifest":first,"fold":2})
            with run.exclusive_run(folder):
                with self.assertRaises(ValueError):
                    with run.exclusive_run(folder):pass

    def test_frozen_artifact_verification_refuses_modified_checkpoint(self):
        with TemporaryDirectory() as tmp:
            folder=Path(tmp);manifest="test"
            run.save_json(folder/"final_report.json",{"trade_qualified":False})
            (folder/"ensemble_predictions.csv").write_text("session,probability\n2026-01-05,.5\n")
            checkpoints=[]
            for seed in v.SEEDS:
                path=folder/f"final_seed_{seed}_research_only.pt";path.write_bytes(b"synthetic")
                checkpoints.append({"file":path.name,"sha256":run.file_digest(path)})
            run.save_json(folder/"frozen_research_manifest.json",{"manifest_sha256":manifest,
                "report_sha256":run.file_digest(folder/"final_report.json"),
                "prediction_sha256":run.file_digest(folder/"ensemble_predictions.csv"),"checkpoints":checkpoints})
            self.assertFalse(run.verified_frozen(folder,manifest)["trade_qualified"])
            (folder/checkpoints[0]["file"]).write_bytes(b"changed")
            with self.assertRaises(ValueError):run.verified_frozen(folder,manifest)

    def test_sign_metrics_include_flat_and_unresolved_calls(self):
        data=toy();rows=np.arange(3)
        p=np.full((3,9),.7);data["mask"][2,0]=False
        # For horizon 1 there is now only one material sign, so use another
        # unresolved flat row in a six-row cohort.
        rows=np.arange(6);p=np.full((6,9),.7)
        data["mask"][2,0]=True;data["mask"][1,0]=False
        ref={"coin":np.full_like(p,.5)}
        report=v.assessment(data,rows,p,ref)
        calls=report["horizons"]["1"]["research_sign_calls"]
        self.assertEqual(calls["calls"],6);self.assertEqual(calls["unresolved_calls"],1)
        self.assertEqual(report["horizons"]["1"]["material_rows"],4)
        journal=list(run.journal(data,rows,p,p))
        self.assertEqual(len(journal),54)
        eod=next(r for r in journal if r["horizon"]=="EOD")
        self.assertEqual(eod["exit_reference_type"],"session_close")
        self.assertEqual(eod["exit_reference_utc"],d.r._stamp(data["days"][0],375))


@skipIf(torch is None,"Optional PyTorch dependency not installed")
class V4ModelTests(TestCase):
    def test_sign_only_flat_and_unobserved_gradient(self):
        raw=torch.zeros(2,3,requires_grad=True)
        target=torch.tensor([[0.,10.,-10.],[-10.,0.,10.]])
        mask=torch.tensor([[True,True,False],[True,True,True]])
        loss=net.sign_loss(raw,target,mask,torch.ones(2));loss.backward()
        self.assertEqual(raw.grad[0,0].item(),0.)
        self.assertEqual(raw.grad[0,2].item(),0.)
        self.assertEqual(raw.grad[1,1].item(),0.)
        self.assertLess(raw.grad[0,1].item(),0.)
        self.assertGreater(raw.grad[1,0].item(),0.)

    def test_graph_no_future_or_masked_edges_and_gpu_backward(self):
        torch.set_num_threads(1)
        device=torch.device("cuda" if torch.cuda.is_available() else "cpu")
        if hasattr(torch.backends,"mha"):torch.backends.mha.set_fastpath_enabled(False)
        model=net.DirectionGraph(3,8,2,6,9,width=64,variant="graph_moe").to(device)
        model.eval()
        tokens=torch.randn(2,6,3,64,device=device);observed=torch.ones(2,6,3,dtype=torch.bool,device=device)
        observed[:,0]=False;observed[:,:,2]=False
        before=model.graph_tokens(tokens,observed)
        changed=tokens.clone();changed[:,3:]+=100.;changed[:,:,2]+=100.
        after=model.graph_tokens(changed,observed)
        torch.testing.assert_close(before[:,:3],after[:,:3])
        self.assertTrue(bool((before[:,0]==0).all()))
        model.train()
        x=torch.zeros(2,30,3,8,device=device);x[:,-10:,0,0]=1;x[:,-5:,1,0]=1
        aux=torch.zeros(2,30,2,device=device)
        s=torch.zeros(2,25,6,device=device);p=torch.zeros(2,60,6,device=device)
        sv=torch.zeros(2,25,dtype=torch.bool,device=device);pv=torch.zeros(2,60,dtype=torch.bool,device=device)
        with torch.autocast(device_type=device.type,dtype=torch.bfloat16,enabled=device.type=="cuda" and torch.cuda.is_bf16_supported()):
            logits,gates=model(x,aux,s,p,sv,pv)
        self.assertEqual(tuple(logits.shape),(2,9))
        torch.testing.assert_close(gates.sum(dim=-1),torch.ones(2,9,device=device))
        loss=net.sign_loss(logits,torch.full((2,9),10.,device=device),
                           torch.ones(2,9,dtype=torch.bool,device=device),torch.ones(2,device=device),gates)
        loss.backward()
        self.assertTrue(all(bool(torch.isfinite(z.grad).all()) for z in model.parameters() if z.grad is not None))
        self.assertIsNotNone(model.graph.in_proj_weight.grad)
        self.assertIsNotNone(model.gate[0].weight.grad)

    def test_tiny_v4_pretraining_finetuning_and_calibration(self):
        torch.set_num_threads(1)
        data=toy();tr=np.arange(12);va=np.arange(12,15);te=np.arange(15,18)
        known=np.array([True,True,False])
        part={"tr":tr,"va":va,"te":te,"pre":tr,"known":known,"fit":d.fit_aux(data,tr),
              "memory":v3.memory_grid(data,True,known_assets=known),"dates":[data["dates"][:4],data["dates"][4:5],data["dates"][5:]],"stride":1}
        device=torch.device("cuda" if torch.cuda.is_available() else "cpu")
        vp,ep,diag,ck=v.fit_model(data,part,"graph_moe",64,42,pre_epochs=1,epochs=1,batch=3,
                                  accumulate=2,patience=1,device=device)
        self.assertEqual(vp.shape,(3,9));self.assertTrue(np.isfinite(ep).all())
        self.assertEqual(diag["selected_epoch"],1)
        self.assertEqual(diag["known_assets"],data["identities"][:2])
        self.assertEqual(diag["pretraining_labels_per_asset"]["NSE_EQ:1"],[12,12])
        self.assertFalse(ck["trade_qualified"])
        p,cal=v.calibrated(data,part,vp,ep)
        self.assertEqual(len(cal),9);self.assertTrue(np.isfinite(p).all())
        self.assertEqual(len(diag["score_gate_mass"]["mean_mass"]),9)
