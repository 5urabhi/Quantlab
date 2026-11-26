from datetime import datetime,timedelta,timezone
from unittest import TestCase
from unittest.mock import patch
import numpy as np

from workstation_api import paper_forecast as forecast, constituent_alpha as alpha
from workstation_api import auto_paper_engine as engine, paper_execution as paper

NOW=datetime(2026,11,26,5,0,30,tzinfo=timezone.utc)
MODEL="a"*64
CANDIDATE={"source":"prospective","source_policy_sha256":alpha.policy_for(15),
           "horizon_minutes":15,"reference_holdout_dates":["2026-11-25"],"live_approved":False,
           "feature_key":"full","classes":list(alpha.CLASSES)}


def evidence(cutoff=None,decision=None):
    cutoff=cutoff or NOW-timedelta(seconds=10)
    decision=decision or cutoff+timedelta(seconds=1)
    return {"state":"available","model_id":MODEL,"direction":"DOWN",
            "p_down":.8,"p_flat":.1,"p_up":.1,
            "cutoff_utc":cutoff.isoformat(),"decision_utc":decision.isoformat(),
            "target_utc":(decision+timedelta(minutes=15)).isoformat()}


class ForecastTests(TestCase):
    def test_candidate_must_be_earlier_prospective_matching_policy(self):
        with patch.object(forecast.registry,"load",return_value=CANDIDATE):
            self.assertEqual(forecast.validate_candidate(MODEL,NOW),CANDIDATE)
        for change in ({"source":"historical"},{"reference_holdout_dates":["2026-11-26"]},
                       {"source_policy_sha256":"wrong"},{"live_approved":True}):
            with patch.object(forecast.registry,"load",return_value={**CANDIDATE,**change}):
                with self.assertRaises(ValueError):
                    forecast.validate_candidate(MODEL,NOW)

    def test_predicts_without_outcome_and_checks_staleness(self):
        base=evidence()
        sample={**{k:base[k] for k in ("cutoff_utc","decision_utc","target_utc")},
                "session":"2026-11-26","reference_sha256":"b"*64,"reference_price":63000.,
                "index":[1.]*7,"full":[1.]*16}
        with patch.object(forecast.registry,"load",return_value=CANDIDATE), \
             patch.object(alpha,"sample_day",return_value=([sample],{})) as features, \
             patch.object(forecast.registry,"predict",return_value=np.array([[.8,.1,.1]])):
            out=forecast.forecast(MODEL,NOW,read_rows=lambda *_:[])
            self.assertEqual(out["direction"],"DOWN")
            self.assertEqual(out["state"],"available")
            self.assertEqual(features.call_args.kwargs,{"features_only":True,"as_of":NOW})
            self.assertEqual(forecast.forecast(MODEL,NOW+timedelta(minutes=2),read_rows=lambda *_:[])["reason"],
                             "stale_or_expired_forecast")

    def test_only_fresh_post_entry_opposite_probability_triggers(self):
        entry=(NOW-timedelta(seconds=20)).isoformat()
        good=evidence()
        self.assertTrue(forecast.reversal("UP",good,NOW,entry))
        self.assertFalse(forecast.reversal("DOWN",good,NOW,entry))
        self.assertFalse(forecast.reversal("UP",{**good,"p_down":.55,"p_flat":.25,"p_up":.2},NOW,entry))
        self.assertFalse(forecast.reversal("UP",{**good,"state":"unavailable"},NOW,entry))
        self.assertFalse(forecast.reversal("UP",evidence(NOW+timedelta(seconds=1)),NOW,entry))
        self.assertFalse(forecast.reversal("UP",good,NOW,NOW.isoformat()))
        self.assertFalse(forecast.reversal("UP",good,NOW+timedelta(minutes=2),entry))

    def test_paper_monitor_keeps_risk_guards_and_uses_model_reversal(self):
        row={"config":{**engine.DEFAULTS,"exit_mode":"forecast_adaptive","forecast_model_id":MODEL},
             "entry_received_utc":(NOW-timedelta(seconds=20)).isoformat(),
             "hold_deadline_utc":(NOW+timedelta(minutes=5)).isoformat(),
             "selected":{"legs":[{"expiry":"2026-11-26"}]},
             "source":{"direction":"UP"},"risk_budget_inr":4250.}
        events=[]
        def update(row,state,**changes):
            events.append((state,changes))
        mark={"mark_net_inr":20.,"mark_observed_utc":paper._iso(NOW),"liquidity_bad":False}
        engine._monitor(row,NOW,update=update,mark_lookup=lambda *_:mark,forecast_lookup=lambda *_:evidence())
        self.assertEqual(events[-1][0],"awaiting_exit")
        self.assertEqual(events[-1][1]["exit_trigger"],"forecast_reversal")
        self.assertNotIn("net_pnl_inr",events[-1][1])
        self.assertEqual(events[-1][1]["latest_forecast"]["model_id"],MODEL)
        engine._monitor(row,NOW,update=update,mark_lookup=lambda *_:{**mark,"mark_net_inr":-500.},
                        forecast_lookup=lambda *_:self.fail("Hard loss guard must run first"))
        self.assertEqual(events[-1][1]["exit_trigger"],"loss_mark")
        engine._monitor(row,NOW,update=update,mark_lookup=lambda *_:mark,
                        forecast_lookup=lambda *_:{"state":"unavailable","reason":"no_receipts","model_id":MODEL})
        self.assertEqual(events[-1][0],"paper_open")
        self.assertEqual(events[-1][1]["latest_forecast"]["state"],"unavailable")
