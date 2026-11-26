from datetime import datetime,timezone,timedelta
from unittest import TestCase
from unittest.mock import patch
from workstation_api import spread_speed as s, paper_execution as p

class SpreadSpeedTests(TestCase):
    def test_fixed_anchors_and_censored_paths(self):
        now=datetime(2026,11,26,4,30,tzinfo=timezone.utc)
        calls=[]
        def simulate(**kwargs):
            h=kwargs["hold_seconds"];decision=datetime.fromisoformat(kwargs["decision_utc"])
            calls.append((decision,h))
            out={"state":"exit_unobservable","entry_complete":True,"exit_complete":False,
                 "net_pnl_inr":None,"entry_received_utc":p._iso(decision+timedelta(seconds=2))}
            if h!=15:
                out.update(state="complete_conditional_quote_replay",exit_complete=True,
                    net_pnl_inr=20.,total_fees_inr=50.,exit_decision_utc=p._iso(decision+timedelta(seconds=h+2)),
                    exit_received_utc=p._iso(decision+timedelta(seconds=h+4)),
                    entries=[{"requested_units":30,"original_best_bid":99.,"cashflow":-3030.}])
            return out
        with patch.object(s.replay,"replay",side_effect=simulate):
            result=s.run(day="2026-11-26",strategy="LONG_OPTION",identities=["NSE_FNO:123"],now=now)
        self.assertGreater(result["decision_count"],0)
        self.assertEqual(len(calls),result["decision_count"]*6)
        self.assertEqual(result["matched_decisions"],0)
        row=result["rows"][1]
        self.assertEqual(row["scored"],0)
        self.assertEqual(row["unscored"],result["decision_count"])
        self.assertIsNone(row["net"]["mean"])
        row=result["rows"][0]
        self.assertEqual(row["roundtrip"]["median"],9.)
        self.assertEqual(row["entry_delay"]["p90"],2.)
        self.assertEqual(row["exit_delay"]["p90"],2.)
        self.assertEqual(row["net"]["mean"],20.)
        self.assertFalse(result["actual_fills_observed"])

    def test_future_day_rejected(self):
        with self.assertRaises(ValueError):
            s.run(day="2026-11-27",strategy="LONG_OPTION",identities=["NSE_FNO:123"],
                  now=datetime(2026,11,26,4,30,tzinfo=timezone.utc))
