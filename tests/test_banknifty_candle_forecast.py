"""Regression tests for the next-five-minute candle research clock."""
from datetime import date,timedelta
from unittest import TestCase
import numpy as np
from workstation_api import banknifty_forecast_features as f, banknifty_candle_forecast as m


def bars():
    c=63000.+np.arange(375)*.4+np.sin(np.arange(375)/8)
    o=c-.2
    return np.column_stack((o,c+.5,o-.5,c,np.full(375,100.)))


class ForecastTests(TestCase):
    def test_exact_next_five_minutes_and_valid_reconstruction(self):
        a=bars();minutes,y,real=f.anchors(a)
        self.assertEqual(minutes[0],59)
        self.assertEqual(minutes[-1],369)
        self.assertEqual(len(minutes),311)
        b=a[60:65]
        np.testing.assert_allclose(real[0],[b[0,0],b[:,1].max(),b[:,2].min(),b[-1,3]])
        np.testing.assert_allclose(m.decode(a[minutes,3],y),real,rtol=1e-12)
        out=m.decode(np.array([63000.]),np.array([[.1,-.1,-.4,-.4]]))
        self.assertGreaterEqual(out[0,1],max(out[0,0],out[0,3]))
        self.assertLessEqual(out[0,2],min(out[0,0],out[0,3]))

    def test_missing_minute_excludes_input_and_target_not_filled(self):
        a=bars();a[70,:]=np.nan
        minutes,_,_=f.anchors(a)
        self.assertNotIn(65,minutes) # next-five-minute target contains gap
        self.assertNotIn(70,minutes)
        self.assertNotIn(129,minutes) # 60-minute input includes missing bar
        self.assertIn(130,minutes)
        self.assertIsNone(f.daily_ohlc(a))

    def test_features_unchanged_when_future_candles_change(self):
        a=bars();b=a.copy();b[121:,:4]*=2
        prior=np.array([62900.,63200.,62700.,63000.])
        n,x=f.price_features(a,index=True,prior=prior,earlier_days=[prior])
        n2,x2=f.price_features(b,index=True,prior=prior,earlier_days=[prior])
        self.assertEqual(n,n2)
        np.testing.assert_allclose(x[:121],x2[:121],equal_nan=True)
        np.testing.assert_allclose(f.sequence(a,np.array([120])),f.sequence(b,np.array([120])))
        self.assertAlmostEqual(x[120,n.index("pivot_distance_pct")],100*(a[120,3]-(63200+62700+63000)/3)/a[120,3],places=5)
        # m=120 is the first minute of a new clock-aligned five-minute bar.
        self.assertAlmostEqual(x[120,n.index("completed_5m_close_distance_pct")],100*(a[120,3]-a[119,3])/a[120,3],places=5)

    def test_historical_banks_only_and_volume_context(self):
        a=bars();day="2026-10-05";minutes=np.array([100,101])
        ids=["NSE_EQ:1","NSE_EQ:2","NSE_EQ:3"]
        stocks={identity:{day:a.copy()} for identity in ids}
        names,v,ok=f.banks_at(day,minutes,ids,stocks,set(ids),{k:1. for k in ids},[],a[:,3])
        self.assertTrue(ok.all())
        self.assertTrue(np.isfinite(v[:,names.index("bank_weighted_5m_pct")]).all())
        names,v,ok=f.banks_at(day,minutes,ids,stocks,set(),None,[],a[:,3])
        self.assertFalse(ok.any())
        self.assertTrue(np.isnan(v[:,names.index("bank_weighted_5m_pct")]).all())
        self.assertTrue(np.isnan(v[:,names.index("NSE_EQ:1_return_5m_pct")]).all())

    def test_option_features_match_same_strike_and_ignore_future(self):
        day="2026-10-05";strike=63000.;minute=90
        def q(p,oi):
            return {"session_ist":day,"expiry_flag":"MONTH","expiry_code":1,
                    "volume":100,"close":p,"oi":oi,"iv":18.}
        table={m.r._stamp(day,minute):{("CALL",strike):q(300.,100),("PUT",strike):q(280.,120)},
               m.r._stamp(day,minute-5):{("CALL",strike):q(250.,80),("PUT",strike):q(290.,100)}}
        first=f.option_at(table,day,minute,strike)
        self.assertAlmostEqual(first[2],100*(580/540-1))
        self.assertAlmostEqual(first[10],.2-.25)
        table[m.r._stamp(day,minute+1)]={("CALL",strike):q(10000.,900000)}
        np.testing.assert_allclose(first,f.option_at(table,day,minute,strike),equal_nan=True)

    def test_split_and_train_only_feature_support(self):
        days=[(date(2026,1,1)+timedelta(days=i)).isoformat() for i in range(80)]
        tr,va,te=m.split_days(days)
        self.assertEqual((len(tr),len(va),len(te)),(48,16,16))
        self.assertLess(max(tr),min(va));self.assertLess(max(va),min(te))
        x=np.array([[1.,np.nan],[2.,np.nan],[3.,10.]])
        np.testing.assert_array_equal(m.select_columns(x,np.array([True,True,False])),[True,False])

    def test_end_to_end_ridge_selected_and_test_clock(self):
        dates=[(date(2026,1,1)+timedelta(days=i)).isoformat() for i in range(80)]
        days=np.repeat(dates,6);minutes=np.tile(np.arange(59,90,5)[:6],80)
        z=np.sin(np.arange(len(days))/4)
        x=np.column_stack((z,np.ones(len(z)))).astype(np.float32)
        y=np.column_stack((np.zeros(len(z)),.06*z,np.full(len(z),.02),np.full(len(z),.02)))
        ref=np.full(len(z),63000.)
        data={"days":days,"minutes":minutes,"ref":ref,"y":y,"actual":m.decode(ref,y),
              "blocks":{"index":x,**{k:np.full((len(z),1),np.nan,dtype=np.float32) for k in ("banks","peers","options")}},
              "available":{k:np.zeros(len(z),dtype=bool) for k in ("banks","peers","options")}}
        result,pred=m.assess(data,m.split_days(dates),algorithms=("ridge",))
        self.assertEqual(result["selected"]["scope"],"index")
        self.assertEqual(result["training_days"],48)
        self.assertEqual(len(pred),16*6)
        self.assertTrue(all(p["session"] in dates[-16:] for p in pred))
        self.assertTrue(all(p["predicted_high"]>=max(p["predicted_open"],p["predicted_close"]) for p in pred))
        self.assertTrue(all(p["predicted_low"]<=min(p["predicted_open"],p["predicted_close"]) for p in pred))
        self.assertEqual(result["validation"]["index_banks"]["state"],"insufficient_training_context")
