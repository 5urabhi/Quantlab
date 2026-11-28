"""Synthetic full-history checks; no vendor calls or user history mutation."""
from datetime import date,datetime,time,timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import numpy as np

from scripts import benchmark_market_dynamics as d
from scripts import market_dynamics_history as h


def bars(price=100.):
    return np.tile([price,price,price,price,100.],(375,1)).astype(float)


class FullHistoryTests(TestCase):
    def test_chronological_full_history_reservation(self):
        start=date(2022,1,1)
        dates=[(start+timedelta(days=i)).isoformat() for i in range(1800)
               if (start+timedelta(days=i)).weekday()<5]
        tr,va,te=h.full_splits(dates)
        self.assertEqual(tr+va+te,dates)
        self.assertGreater(len(tr),len(dates)*.8)
        self.assertLess(tr[-1],va[0]);self.assertLess(va[-1],te[0])
        self.assertGreaterEqual(len(va),15);self.assertGreaterEqual(len(te),15)

    def test_gap_does_not_discard_later_minutes_or_invent_day_extrema(self):
        a=bars();prior=bars()
        prior[:,1]=110.;prior[:,2]=90.
        a[18]=np.nan;a[19:,:4]=105.
        f=d.full_asset_features(a,prior,[])
        col=d.ASSET_FIELDS.index
        self.assertTrue(np.isnan(f[18]).all())
        self.assertEqual(f[19,col("observed")],1.)
        self.assertEqual(f[19,col("session_prefix_complete")],0.)
        self.assertAlmostEqual(f[19,col("previous_high_distance_pct")],100*(105-110)/105,places=5)
        self.assertTrue(np.isnan(f[19,col("today_running_high_distance_pct")]))
        self.assertTrue(np.isnan(f[19,col("today_developing_pivot_distance_pct")]))
        self.assertAlmostEqual(f[19,col("opening_15m_high_distance_pct")],100*(105-100)/105,places=5)
        ms,y,c,mask,scheduled=d.labels_for_session(a,all_minutes=True)
        self.assertEqual(ms[0],0);self.assertNotIn(18,ms);self.assertIn(19,ms)
        self.assertTrue(scheduled[ms==16,0][0]);self.assertFalse(mask[ms==16,0][0])
        self.assertTrue(mask[ms==19,0][0])
        changed=a.copy();changed[21:,:4]=200.
        np.testing.assert_array_equal(f[:21],d.full_asset_features(changed,prior,[])[:21])

    def test_completed_aggregate_and_aged_previous_observation_are_causal(self):
        a=bars()
        a[4,1]=110.;a[5,1]=200.
        f=d.full_asset_features(a,None,[])
        d.add_clock_context(f,a,"2026-01-06",("2026-01-02",(90.,100.,80.,95.)),375)
        col=d.ASSET_FIELDS.index
        self.assertTrue(np.isnan(f[3,col("completed_5m_high_distance_pct")]))
        self.assertAlmostEqual(f[4,col("completed_5m_high_distance_pct")],-10.)
        self.assertAlmostEqual(f[5,col("completed_5m_high_distance_pct")],-10.)
        self.assertEqual(f[5,col("prior_observed_gap_days")],4.)
        self.assertAlmostEqual(f[5,col("last_observed_close_distance_pct")],5.)
        changed=a.copy();changed[6:,1]=1000.
        other=d.full_asset_features(changed,None,[])
        d.add_clock_context(other,changed,"2026-01-06",("2026-01-02",(90.,100.,80.,95.)),375)
        np.testing.assert_array_equal(f[:6],other[:6])

    def test_full_grid_includes_nonmember_only_as_individual_context(self):
        dates=["2026-01-05","2026-01-06","2026-01-07"]
        idx={day:bars() for day in dates}
        stocks={"NSE_EQ:1":{day:bars(110.) for day in dates},
                "NSE_EQ:2":{day:bars(120.) for day in dates},
                "NSE_EQ:3":{dates[2]:bars(130.)}}
        membership={day:{"A":"NSE_EQ:1"} for day in dates}
        with TemporaryDirectory() as scratch:
            data=d.build(idx,stocks,membership,{}, {},{}, {},{},(),(),
                 ([dates[0]],[dates[1]],[dates[2]]),all_history=True,scratch=Path(scratch))
            self.assertIsInstance(data["grid"],np.memmap)
            self.assertIn("NSE_EQ:2",data["identities"])
            self.assertNotIn("NSE_EQ:3",data["identities"])
            j=data["identities"].index("NSE_EQ:2")
            self.assertEqual(data["grid"][0,0,j,0],1.)
            self.assertEqual(data["grid"][0,0,j,d.ASSET_FIELDS.index("dated_bank_member")],0.)
            self.assertEqual(data["minutes"][0],0)
            self.assertEqual(data["aux"][0,10,d.BANK_AUX.index("scheduled_count")],1.)
            self.assertEqual(data["aux"][0,10,d.BANK_AUX.index("observed_fraction")],1.)
            tr=np.flatnonzero(data["day_index"]==0)
            fit=d.fit_aux(data,tr)
            x,z=d.windows(data,tr[:1],True,fit)
            self.assertTrue((x[0,:-1]==0).all())
            self.assertTrue(np.isfinite(x).all() and np.isfinite(z).all())
            self.assertEqual(x[0,-1,0,0],1.)
            del data

    def test_all_resolved_training_minutes_and_local_shuffle(self):
        dates=[(date(2025,1,1)+timedelta(days=i)).isoformat() for i in range(80)]
        days=np.repeat(dates,3);di=np.repeat(np.arange(80),3)
        ms=np.tile([0,1,2],80)
        classes=np.tile(np.arange(3),80)[:,None].repeat(len(d.HORIZONS),axis=1)
        mask=np.ones_like(classes,bool);mask[0]=False
        data={"all_history":True,"days":days,"day_index":di,"minutes":ms,"classes":classes,"mask":mask}
        tr,va,te=d.partitions(data,(dates[:48],dates[48:64],dates[64:]))
        self.assertEqual(len(tr),48*3-1)
        self.assertEqual(len(va),48);self.assertEqual(len(te),48)
        order=h.shuffled_sessions(tr,di,np.random.default_rng(42))
        np.testing.assert_array_equal(np.sort(order),tr)
        self.assertEqual(len(order),len(set(order.tolist())))

    def test_verified_rolling_groups_and_same_strike_change(self):
        start=date(2026,1,5);end=start+timedelta(days=1)
        day=start.isoformat();later=end.isoformat()
        def payload(side,when,strikes):
            t=datetime.combine(when,time(9,15),h.h.IST)
            stamp=[int((t+timedelta(minutes=i)).timestamp()) for i in (0,5,10)]
            rows={"timestamp":stamp,"strike":strikes,"open":[10.,12.,14.],
                  "high":[11.,13.,15.],"low":[9.,11.,13.],"close":[10.,12.,14.],
                  "volume":[100,110,120],"oi":[1000,1100,1200],"iv":[10.,11.,12.]}
            return {"data":{"ce" if side=="CALL" else "pe":rows}}
        with TemporaryDirectory() as tmp,patch.object(h.service,"DATA",Path(tmp)):
            for flag,code,offset,side,when,strikes in (
                ("MONTH",0,"ATM+10","CALL",start,[101.,101.,102.]),
                ("MONTH",1,"ATM-5","PUT",start,[99.,99.,99.]),
                ("WEEK",0,"ATM","CALL",end,[100.,100.,100.])):
                body=h.exp._request_body(start,end,flag,code,offset,side)
                h.exp._save_cache(body,payload(side,when,strikes))
            archive=h.load_options({day:bars(),later:bars()},[day])
            self.assertEqual(archive.evidence["verified_receipts"],3)
            self.assertIn("MONTH:1:CALL:ATM+10",archive.evidence["observed_groups"])
            self.assertFalse(archive.evidence["observed_groups"]["WEEK:1:CALL:ATM"]["training_supported"])
            self.assertIn(("MONTH",2,"PUT","ATM-5"),archive.keys)
            self.assertNotIn(("WEEK",1,"CALL","ATM"),archive.keys)
            x,seen=archive.features(day,np.full(375,100.))
            name="rolling:MONTH:1:CALL:ATM+10:"
            self.assertAlmostEqual(x[0,archive.names.index(name+"strike_distance_pct")],1.)
            self.assertAlmostEqual(x[5,archive.names.index(name+"same_strike_5m_return_pct")],20.)
            self.assertTrue(np.isnan(x[10,archive.names.index(name+"same_strike_5m_return_pct")]))
            self.assertEqual(int(seen.sum()),3)
            json.dumps(archive.evidence,allow_nan=False)

    def test_streaming_stats_do_not_drop_shorter_observed_source(self):
        x=np.array([[1.,np.nan,np.nan],[2.,np.nan,np.nan],[3.,4.,np.nan],[999.,999.,999.]])
        fit=h.stats(lambda rows:x[rows],np.arange(3))
        np.testing.assert_array_equal(fit["keep"],[True,True,False])
        np.testing.assert_allclose(fit["mean"],[2.,4.,0.])
        z=h.scaled(lambda rows:x[rows],np.array([0,2]),fit)
        self.assertEqual(z[0,-1],0.)
        self.assertEqual(z[1,-1],1.)
