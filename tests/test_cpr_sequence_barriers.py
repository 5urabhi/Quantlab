"""Regression tests for dense earlier training and completed-candle barrier labels."""
from datetime import date,timedelta
from unittest import TestCase
from unittest.mock import patch
import numpy as np

from workstation_api import candle_barrier_research as b, cpr_hybrid_research as r
from workstation_api import cpr_context_features as cx


def bars(n=375,offset=0):
    data={};previous=60000.+offset
    for minute in range(n):
        close=60000.+offset+20*((minute//5)%5-2)+minute*.2
        data[minute]=(previous,max(previous,close)+3,min(previous,close)-3,close,100.)
        previous=close
    return data


def label(result,kind,distance):
    i=next(i for i,(k,d,_) in enumerate(b.TASKS) if (k,d)==(kind,distance))
    return b.TASKS[i][2][result["labels"][i]]


class SequenceBarrierTests(TestCase):
    def test_sequence_masks_and_future_invariance(self):
        data=bars()
        early=b.sequence_features(data,19)
        self.assertEqual(len(early["sequence"]),len(b.SEQUENCE_NAMES))
        self.assertEqual(early["sequence"][b.SEQUENCE_NAMES.index("window_20_missing")],1.)
        late=b.sequence_features(data,104)
        self.assertEqual(late["sequence"][b.SEQUENCE_NAMES.index("window_20_missing")],0.)
        data[105]=(60000.,70000.,59000.,70000.,100.)
        self.assertEqual(b.sequence_features(data,104),late)
        del data[50]
        self.assertIsNone(b.sequence_features(data,104))

    def test_both_barriers_unknown_order_and_open_gap_known_order(self):
        data=bars()
        data[19]=(60000.,60000.,60000.,60000.,100.)
        data[20]=(60000.,60030.,59970.,60028.,100.)
        first=b.outcomes(data,19,1)
        self.assertEqual(label(first,"first_touch",25),"ambiguous")
        self.assertEqual(label(first,"terminal_move",25),"up_at_least")
        self.assertEqual(label(first,"first_touch",50),"neither")
        data[20]=(60026.,60030.,59970.,59972.,100.)
        first=b.outcomes(data,19,1)
        self.assertEqual(label(first,"first_touch",25),"upper_first")
        self.assertEqual(label(first,"terminal_move",25),"down_at_least")
        data[20]=(59974.,60030.,59970.,60028.,100.)
        self.assertEqual(label(b.outcomes(data,19,1),"first_touch",25),"lower_first")

    def test_first_touch_is_not_terminal_direction_and_gap_censors(self):
        data=bars()
        data[19]=(60000.,60000.,60000.,60000.,100.)
        data[20]=(60000.,60030.,59999.,60010.,100.)
        data[21]=(60010.,60011.,59960.,59970.,100.)
        result=b.outcomes(data,19,2)
        self.assertEqual(label(result,"first_touch",25),"upper_first")
        self.assertEqual(label(result,"terminal_move",25),"down_at_least")
        del data[21]
        self.assertIsNone(b.outcomes(data,19,2))
        self.assertIsNone(b.outcomes(data,373,2))

    def test_chronological_multitask_assessment_and_matched_context(self):
        days=[(date(2026,8,1)+timedelta(days=i)).isoformat() for i in range(27)]
        index={day:bars(65,offset=i*2) for i,day in enumerate(days)}
        splits=(days[:20],days[20:25],days[25:])
        real=b.RandomForestClassifier
        def fast(**kwargs):
            return real(**{**kwargs,"n_estimators":5})
        def attach(signals,**kwargs):
            for s in signals:
                self.assertNotIn("labels",s)
                if s["minute"]>=29:
                    s["context_vectors"]={"global":[1.,.01,1.,0.],"panel_detail":[.1]*30}
            return {"state":"fixture","anchors":{}}
        with patch.object(b,"HORIZONS",(5,)),patch.object(b,"RandomForestClassifier",side_effect=fast), \
             patch.object(cx,"attach",side_effect=attach):
            result=b.assess(index,splits,context_mode="archive",fixed_panel=True)
            study=result["horizons"]["5"]["scopes"]
            for scope in study.values():
                self.assertEqual(scope["baseline"]["state"],"exploratory_assessment")
                self.assertEqual(scope["augmented"]["state"],"exploratory_assessment")
                self.assertEqual(len(scope["augmented"]["tasks"]),8)
                self.assertEqual(scope["baseline"]["coverage"],scope["augmented"]["coverage"])
                for result in scope["augmented"]["tasks"].values():
                    chosen=result["selected_on_validation"]
                    self.assertAlmostEqual(sum(result["holdout"][chosen]["predicted"].values()),1.)
            self.assertLess(study["panel"]["matched_coverage"]["holdout"],study["sequence"]["matched_coverage"]["holdout"])
        with self.assertRaises(ValueError):
            b.assess(index,(days[20:25],days[:20],days[25:]))

    def test_dense_sampler_preserves_time_order_and_balance(self):
        rows=[{"session":"2026-10-06","minute":m,"side":"CALL","learning_day_balance":True}
              for m in (29,30,34,35,44,45,60)]
        result=r._dense_anchors(list(reversed(rows)))
        self.assertEqual([x["minute"] for x in result],[29,30,45,60])
        # Four contracts at one anchor, another anchor the same day, and a
        # second day with one contract: total mass is equal across dates.
        other={**rows[0],"session":"2026-10-07"}
        observations=[(rows[0],{})]*4+[(rows[1],{}),(other,{})]
        weights=r._anchor_weights(observations)
        self.assertAlmostEqual(sum(weights[:5]),weights[5])
        self.assertAlmostEqual(sum(weights[:4]),weights[4])
        self.assertEqual(r.SESSION_SPLITS[120],(60,20,40))

    def test_panel_detail_is_neutral_and_all_five_symbols_required(self):
        days=[(date(2026,9,1)+timedelta(days=i)).isoformat() for i in range(7)]
        day=days[-1]
        panel={symbol:{d:bars(60,i*10) for d in days} for i,symbol in enumerate(cx.PANEL_SYMBOLS)}
        intervals=[{"symbol":s,"valid_from":days[0],"valid_to":None} for s in cx.PANEL_SYMBOLS]
        signal={"session":day,"minute":34,"side":"CALL","index_return_5m_bps":0.}
        x=cx._panel_detail(signal,panel,intervals,days[:-1])
        self.assertEqual(len(x),len(cx.PANEL_DETAIL_NAMES))
        self.assertAlmostEqual(x[3],1.)
        self.assertEqual(x[4],0.)
        self.assertAlmostEqual(x[0],x[5])
        panel["HDFCBANK"][day][35]=(60000.,90000.,59000.,90000.,1000.)
        self.assertEqual(cx._panel_detail({**signal,"side":"PUT"},panel,intervals,days[:-1]),x)
        del panel["HDFCBANK"][day][20]
        self.assertIsNone(cx._panel_detail(signal,panel,intervals,days[:-1]))


    def test_derivatives_use_only_same_strike_completed_bars(self):
        day="2026-10-06";strike=60000
        table={}
        for m in range(30):
            table[r._stamp(day,m)]={("CALL",strike):{"session_ist":day,"expiry_flag":"MONTH","expiry_code":1,
                "open":100.,"close":100.,"volume":200. if m>=20 else 100.,
                "oi":1000.+m*10,"iv":20.+m*.1}}
        signal={"session":day,"minute":24,"side":"CALL"}
        result=r._derivative_vector(signal,table,strike)
        self.assertEqual(len(result),len(r.DERIVATIVE_NAMES))
        self.assertAlmostEqual(result[r.DERIVATIVE_NAMES.index("relative_volume")],2.)
        self.assertAlmostEqual(result[r.DERIVATIVE_NAMES.index("iv_5m_change_raw")],.5)
        table[r._stamp(day,25)][("CALL",strike)]["oi"]=1e12
        self.assertEqual(r._derivative_vector(signal,table,strike),result)
        for stamp in table:
            table[stamp][("CALL",strike)]["oi"]=None
            table[stamp][("CALL",strike)]["iv"]=None
        del table[r._stamp(day,10)]
        self.assertIsNone(r._derivative_vector(signal,table,strike))

    def test_original_option_normalizer_retains_aligned_optional_observations(self):
        from workstation_api import expired_options_backtest as exp
        from datetime import datetime
        day=date(2026,10,6)
        stamp=datetime.fromisoformat(r._stamp(day.isoformat(),24)).timestamp()
        body=exp._request_body(day,day+timedelta(days=1),"MONTH",0,"ATM","CALL")
        segment={"timestamp":[stamp],"open":[100.],"high":[102.],"low":[98.],"close":[101.],
                 "strike":[60000],"volume":[1000],"oi":[2000],"iv":[23.]}
        rows=exp._normalize({"data":{"ce":segment}},body)
        self.assertEqual(rows[0]["oi"],2000.)
        self.assertEqual(rows[0]["iv"],23.)
        segment["iv"]=["bad"]
        self.assertIsNone(exp._normalize({"data":{"ce":segment}},body)[0]["iv"])


    def test_dynamic_state_changes_only_after_completed_five_minute_anchor(self):
        from workstation_api import cpr_dynamic_context as dynamic
        signal={"side":"CALL","_dynamic_states":{19:1,24:-1,34:0}}
        self.assertIsNone(dynamic.state_at(signal,18))
        self.assertEqual(dynamic.state_at(signal,23),1)
        self.assertEqual(dynamic.state_at(signal,24),-1)
        self.assertIsNone(dynamic.state_at(signal,29))
        self.assertEqual(dynamic.state_at({**signal,"side":"PUT"},24),1)
        step={"mark_return":.02,"elapsed":6,"trend":.01,"drawdown":.0,"dynamic_regime":-1}
        self.assertEqual(r._q_key(step,r.DYNAMIC_SCOPE,None),r._key(step)+(-1,))
        self.assertIsNone(r._q_key({**step,"dynamic_regime":None},r.DYNAMIC_SCOPE,None))

    def test_dense_q_weighting_matches_hierarchical_mean(self):
        a=(1,1,1,1);bstate=(2,1,1,1)
        transitions={a:[("d1",1,100,1.,bstate,0.,False)]*10+
            [("d1",1,200,3.,bstate,0.,False),("d1",2,100,4.,None,2.,True),
             ("d2",1,100,7.,None,6.,True)],
             bstate:[("d1",1,100,2.,None,1.,True)]}
        q=r._dense_q_iteration(transitions,2)
        # d1 anchor mean = (2+4)/2=3; d2 = 7, equal session mean=5.
        self.assertAlmostEqual(q[a][0],5.)
        # d1 continuation mean (2+2)/2, d2=6.
        self.assertAlmostEqual(q[a][1],4.)

    def test_bank_outcomes_separate_direction_and_divergence(self):
        day="2026-10-06"
        ix={day:bars()}
        panel={s:{day:bars()} for s in cx.PANEL_SYMBOLS}
        ix[day][19]=(60000.,60000.,60000.,60000.,100.)
        ix[day][20]=(60000.,60100.,60000.,60100.,100.)
        for history in panel.values():
            history[day][19]=(60000.,60000.,60000.,60000.,100.)
            history[day][20]=(60000.,60050.,60000.,60050.,100.)
        result=b.bank_outcomes(ix,panel,day,19,1)
        self.assertEqual(result,[2]*5+[0]*5)
        del panel["HDFCBANK"][day][20]
        self.assertIsNone(b.bank_outcomes(ix,panel,day,19,1))

    def test_saved_summary_reads_only_bounded_known_report_files(self):
        from workstation_api import candle_report_summary as report
        from tempfile import TemporaryDirectory
        from pathlib import Path
        import json
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            self.assertEqual(report.latest(root)["state"],"no_saved_report")
            (root/"candle_barriers_secret.json").write_text('{"secret":"ignore"}')
            expected={"version":"sequence_first_passage_v1","horizons":{},"training_dates":["2026-08-01"],
                      "validation_dates":["2026-08-02"],"holdout_dates":["2026-08-03"],"bank_target_state":"disabled"}
            path=root/("candle_barriers_"+"a"*32+".json")
            path.write_text(json.dumps(expected))
            out=report.latest(root)
            self.assertEqual(out["state"],"available")
            self.assertEqual(out["holdout_dates"],expected["holdout_dates"])
            self.assertEqual(out["report_name"],path.name)

    def test_funding_diagnostic_does_not_treat_missing_as_affordable(self):
        rows=[{"session":"a","minimum_funding_inr":8000},{"session":"a","minimum_funding_inr":15000},
              {"session":"b","minimum_funding_inr":None}]
        result=r._funding_diagnostic(rows,12000,17000)
        self.assertEqual(result["missing_or_unqualified"],1)
        self.assertEqual(next(x["anchors"] for x in result["signal_time_funding_sensitivity"] if x["budget_inr"]==12000),1)
