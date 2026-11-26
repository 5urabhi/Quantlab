"""Synthetic tests for causal regime research and strict utility accounting."""
from datetime import date,timedelta
from unittest import TestCase
from unittest.mock import patch
import numpy as np

from workstation_api import cpr_regime_research as g, cpr_direct_utility as u, cpr_hybrid_research as r
from workstation_api.stable_scaler import StableWeightedScaler
from workstation_api import cpr_context_features as cx
from test_cpr_hybrid_research import episode,step,bar,DAY


def bars(n=375,offset=0):
    out={};previous=60000.+offset
    for m in range(n):
        close=60000.+offset+float((m//5)%7)*15.+(m%5)*2.
        out[m]=(previous,max(previous,close)+3.,min(previous,close)-3.,close,100.)
        previous=close
    return out


class RegimeUtilityTests(TestCase):
    def test_stable_weighted_near_constant_features(self):
        X=np.asarray([[1e12,2.,1.],[1e12,3.,2.],[1e12,7.,3.]])
        s=StableWeightedScaler().fit(X,sample_weight=[1.,2.,3.])
        z=s.transform(X)
        self.assertTrue(np.isfinite(z).all())
        self.assertTrue((z[:,0]==0).all())
        np.testing.assert_allclose(np.average(z,axis=0,weights=[1.,2.,3.]),[0,0,0],atol=1e-12)
        np.testing.assert_allclose(np.average(z[:,1:]**2,axis=0,weights=[1.,2.,3.]),[1,1])
        with self.assertRaises(ValueError):
            StableWeightedScaler().fit([[float("nan")]])

    def test_regime_descriptions_causal_prior_clock_and_missingness(self):
        days=[(date(2026,9,1)+timedelta(days=i)).isoformat() for i in range(8)]
        index={d:bars(offset=i) for i,d in enumerate(days)}
        day=days[-1]
        before=g.describe(index,day,44,days[:-1])
        self.assertEqual(len(before["regime_features"]),len(g.NAMES))
        self.assertEqual(before["regime_features"][g.NAMES.index("seasonality_missing")],0.)
        index[day][45]=(60000.,90000.,59999.,90000.,100.)
        self.assertEqual(g.describe(index,day,44,days[:-1]),before)
        with self.assertRaises(ValueError):
            g.describe(index,day,44,days)
        self.assertEqual(g.describe(index,day,44,[])["regime_features"][g.NAMES.index("seasonality_missing")],1.)
        del index[day][20]
        self.assertIsNone(g.describe(index,day,44,days[:-1]))

    def test_normalized_barriers_freeze_scale_and_keep_ambiguous_order(self):
        data=bars()
        data[34]=(60000.,60000.,60000.,60000.,100.)
        data[35]=(60000.,60100.,59900.,60000.,100.)
        desc={"spot":60000.,"rms_bps":1.}
        result=g.outcome(data,34,1,desc)
        self.assertAlmostEqual(result["scale_points"],6.)
        self.assertEqual(result["labels"][1:], [3,3,3])
        data[35]=(60020.,60100.,59900.,60000.,100.)
        self.assertEqual(g.outcome(data,34,1,desc)["labels"][1:], [2,2,2])
        del data[35]
        self.assertIsNone(g.outcome(data,34,1,desc))

    def test_regime_study_uses_matched_bank_data_and_chronological_splits(self):
        days=[(date(2026,8,1)+timedelta(days=i)).isoformat() for i in range(27)]
        index={d:bars(75,i) for i,d in enumerate(days)}
        def attach(anchors,**kw):
            for s in anchors:
                self.assertNotIn("labels",s)
                if s["minute"]>=39:
                    s["context_vectors"]={"panel_detail":[.1]*len(cx.PANEL_DETAIL_NAMES)}
            return {"state":"fixture","anchors":{}}
        actual=g.RandomForestClassifier
        def fast(**kw):
            return actual(**{**kw,"n_estimators":5})
        with patch.object(g,"HORIZONS",(5,)),patch.object(g,"RandomForestClassifier",side_effect=fast),patch.object(cx,"attach",side_effect=attach):
            out=g.assess(index,(days[:20],days[20:25],days[25:]),context_mode="archive",fixed_panel=True)
            item=out["horizons"]["5"]
            self.assertEqual(item["index_only"]["state"],"exploratory_assessment")
            self.assertEqual(item["matched_panel"]["baseline"]["coverage"],item["matched_panel"]["augmented"]["coverage"])
            self.assertEqual(item["hdfc_icici_lead_lag"]["state"],"exploratory_assessment")
            self.assertEqual(set(item["index_only"]["tasks"]),{t for t,_ in g.TASKS})
        with self.assertRaises(ValueError):
            g.assess(index,(days[20:25],days[:20],days[25:]))

    def test_execution_features_never_use_future_fill(self):
        table={r._stamp(DAY,m):{("CALL",100):bar(20+m*.1)} for m in range(30)}
        signal={"session":DAY,"minute":24,"side":"CALL"}
        x=u.execution_features(r,signal,table,100)
        self.assertEqual(x[:2],[1.,1.])
        table[r._stamp(DAY,25)][("CALL",100)]["close"]=10000.
        self.assertEqual(u.execution_features(r,signal,table,100),x)
        del table[r._stamp(DAY,23)]
        x=u.execution_features(r,signal,table,100)
        self.assertEqual(x[:2],[.9,0.])

    def test_unresolved_and_late_are_stress_not_fabricated_realized_pnl(self):
        missing=episode(DAY,[])
        missing["state"]="missing_entry"
        self.assertEqual(u.target(r,missing)["stress_utility"],-1.)
        self.assertIsNone(u.target(r,missing)["observed_net_per_planned_funding"])
        late=step(0,.12,None)
        late["recovery"]={"exit_net":150.,"exit_fees":70.,"exit_utc":r._stamp(DAY,20),"exit_delay_minutes":18}
        ep=episode(DAY,[late])
        outcome=u.target(r,ep)
        self.assertEqual(outcome["trigger"],"unverified_or_delayed")
        self.assertEqual(outcome["observed_net_per_planned_funding"],.15)
        self.assertEqual(outcome["stress_utility"],-1.)
        second=episode(DAY,[step(100,.12,120.,True)],minute=100)
        metrics,journal=r._evaluate([ep,second],method="fixed_stop",capital=17000.,risk_budget=12000.,strict_execution=True)
        self.assertEqual(metrics["conditional_net_inr"],150.)
        self.assertEqual(metrics["stress_utility_inr"],-1000.)
        self.assertEqual(metrics["execution_quality_halts"],1)
        self.assertEqual(journal[1]["state"],"session_halted")
        self.assertFalse(u._gate(metrics))

    def test_trigger_differs_from_realized_target(self):
        ep=episode(DAY,[step(0,.12,85.,True)])
        y=u.target(r,ep)
        self.assertEqual(y["trigger"],"target_first")
        self.assertAlmostEqual(y["timely_net_per_planned_funding"],.085)

    def test_utility_models_score_missing_paths_and_rank_only_decision_features(self):
        rows=[]
        for i in range(25):
            day=(date(2026,7,1)+timedelta(days=i)).isoformat()
            for j in range(5):
                ep=episode(day,[step(0,.12,110.,True)],minute=34+j*15)
                ep.update(spot=100.,learning_day_balance=True,features=[float(j)]*13,
                          context_vectors={"regime":[.2]*len(g.NAMES),"execution":[1.,1.,4.,.01,0.]})
                if j==4:
                    ep["state"]="missing_entry";ep["path"]=[]
                rows.append(ep)
        model,info=u._fit(r,rows,True)
        self.assertIsNotNone(model)
        self.assertEqual(info["execution_failure_paths"],25)
        result=u._metrics(r,model,info,rows)
        self.assertEqual(result["scored_paths"],125)
        self.assertEqual(result["timely_paths"],100)
        self.assertAlmostEqual(sum(result["trigger_mean_forecast"].values()),1.)
        before=u._predict(model,[rows[0]])
        changed={**rows[0],"state":"missing_entry","path":[]}
        self.assertEqual(u._predict(model,[changed]),before)

    def test_gate_requires_many_timely_days_and_positive_stress(self):
        valid={"scored_trades":10,"daily_coverage":{"days_with_scored_trade":5},"unresolved_trades":0,
               "exits_after_1520":0,"max_exit_delay_minutes":2,"stress_utility_inr":1.}
        self.assertTrue(u._gate(valid))
        self.assertFalse(u._gate({**valid,"max_exit_delay_minutes":3}))
        self.assertFalse(u._gate({**valid,"stress_utility_inr":0.}))
        self.assertFalse(u._gate({**valid,"scored_trades":9}))
