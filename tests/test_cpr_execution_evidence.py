"""Synthetic receipt and execution-evidence regression cases."""
from collections import defaultdict
from datetime import date,datetime,timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from workstation_api import cpr_execution_evidence as e, cpr_hybrid_research as r
from workstation_api import options_history_sync as sync, expired_options_backtest as exp
from workstation_api import predictive_option_research as p, service
from test_cpr_hybrid_research import bar,DAY

TODAY=date(2026,11,27)


def evidence(checked=(),conflicts=()):
    return {"expected_offsets":("ATM","ATM+1","ATM-1"),
            "checked_offsets":{(DAY,"CALL"):set(checked)},"conflicts":set(conflicts)}


def signal(day=DAY,m=34):
    return {"session":day,"minute":m,"side":"CALL","spot":100.,
            "features":[0.]*11,"decision_utc":r._stamp(day,m+1),"entry_utc":r._stamp(day,m+2),
            "entry_type":"trend_continuation"}


def index(days):
    return {d:{m:(100.,101.,99.,100.,100.) for m in range(375)} for d in days}


class ExecutionEvidenceTests(TestCase):
    def test_checked_receipts_and_zero_volume_are_distinct(self):
        checked=evidence(("ATM","ATM+1","ATM-1"))
        self.assertEqual(e.window_status(checked,DAY,"CALL",TODAY)["state"],"checked")
        self.assertEqual(e.window_status(evidence(("ATM",)),DAY,"CALL",TODAY)["missing_offsets"],["ATM+1","ATM-1"])
        self.assertEqual(e.window_status(checked,"2026-11-26","CALL",TODAY)["state"],"not_yet_expired")
        stamp=r._stamp(DAY,36)
        rows={("CALL",100):{**bar(20),"volume":0},("CALL",101):{**bar(20,strike=101),"volume":None}}
        table={stamp:rows}
        self.assertEqual(e.quote_status(table,checked,DAY,36,"CALL",100),"zero_volume")
        self.assertEqual(e.quote_status(table,checked,DAY,36,"CALL",101),"volume_unavailable")
        self.assertEqual(e.quote_status(table,checked,DAY,36,"CALL",102),"outside_observed_strike_range")
        self.assertEqual(e.quote_status(table,checked,DAY,35,"CALL",100),"no_side_bars_at_minute")
        self.assertEqual(e.observed_coverage(table,DAY,"CALL")["zero_volume_strike_bars"],1)
        self.assertNotIn("minutes_with_positive_volume",e.observed_coverage(table,DAY,"CALL"))
        conflict=evidence(conflicts=[(stamp,"CALL",100)])
        self.assertEqual(e.quote_status(table,conflict,DAY,36,"CALL",100),"conflicting_original_bars")

    def test_only_chosen_exit_and_monitoring_gap_are_audited(self):
        s=signal()
        table={r._stamp(DAY,34):{("CALL",100):bar(20)},
               r._stamp(DAY,36):{("CALL",100):bar(20)},
               r._stamp(DAY,39):{("CALL",100):bar(19)}}
        ix=index([DAY])
        ep=r._episode(s,table,ix[DAY],hold=15,lot_size=30,max_lots=1,risk_budget=12000,bps=35)
        result=r._exit(ep,"fixed_stop")
        self.assertEqual(result["reason"],"monitoring_gap_exit")
        ev=e.events(ep,result,table,evidence(),ix,TODAY)
        self.assertEqual(len(ev),1)
        self.assertEqual(ev[0]["event"],"monitoring_gap")
        self.assertEqual(ev[0]["minute"],37)
        self.assertEqual(ev[0]["quote_state"],"no_side_bars_at_minute")
        del table[r._stamp(DAY,36)]
        ep=r._episode(s,table,ix[DAY],hold=15,lot_size=30,max_lots=1,risk_budget=12000,bps=35)
        ev=e.events(ep,r._exit(ep,"fixed_stop"),table,evidence(),ix,TODAY)
        self.assertEqual([v["event"] for v in ev],["missing_entry"])

    def test_cost_lanes_share_signal_time_candidate(self):
        s=signal();table={r._stamp(DAY,34):{("CALL",100):bar(20),("CALL",101):bar(18,strike=101)}}
        candidates,diag=e._matched_candidates(s,table)
        self.assertEqual(candidates[0][:4],candidates[1][:4])
        self.assertLess(candidates[0][4],candidates[1][4])
        self.assertEqual(candidates[0][5],candidates[1][5])
        table[r._stamp(DAY,36)]={("CALL",101):bar(18,strike=101)}
        self.assertEqual(e._matched_candidates(s,table)[0],candidates)

    def test_screen_only_development_and_same_clock(self):
        days=["2026-10-05","2026-10-06","2026-10-07"]
        ix=index(days)
        signals=[signal(d) for d in days]+[signal(days[0],m=349)]
        table={}
        for d in days:
            for m in range(375):
                table[r._stamp(d,m)]={("CALL",100):bar(20,day=d)}
        ev={"expected_offsets":("ATM",),"checked_offsets":defaultdict(set),"conflicts":set()}
        result=e.assess(ix,[[d] for d in days],signals,table,ev,today=TODAY)
        self.assertEqual(set(result["development_screen"]),{"train","validation"})
        self.assertEqual(result["development_screen"]["train"]["shared_opportunities"],1)
        self.assertEqual(result["development_screen"]["train"]["excluded_late_opportunities"],1)
        for part in result["development_screen"].values():
            self.assertEqual(set(part["lanes"]),{str(x) for x in e.HOLDS})
            for lane in part["lanes"].values():
                self.assertEqual(lane["35"]["signals"],lane["75"]["signals"])
        self.assertFalse(result["live_model_promoted"])
        self.assertEqual(result["development_qualified_holds_minutes"],[])

    def test_verified_empty_receipt_is_checked_not_observed_and_no_signal_day_scanned(self):
        left=date(2026,10,5);right=left+timedelta(days=1)
        body=exp._request_body(left,right,"MONTH",0,"ATM","CALL")
        with TemporaryDirectory() as tmp,patch.object(service,"DATA",Path(tmp)):
            exp._save_cache(body,{"data":{}})
            ev={}
            table,meta=p._load_options([signal()],0,needed_stamps={r._stamp(DAY,34)},evidence=ev,
                                      evidence_days=[left.isoformat(),right.isoformat()])
            self.assertEqual(meta["verified_receipts"],1)
            self.assertEqual(dict(table),{})
            self.assertEqual(ev["checked_offsets"][(left.isoformat(),"CALL")],{"ATM"})
            self.assertEqual(ev["checked_offsets"][(right.isoformat(),"CALL")],{"ATM"})
            self.assertEqual(e.window_status(ev,DAY,"CALL",TODAY)["state"],"checked")
            self.assertEqual(e.observed_coverage(table,DAY,"CALL")["minutes_no_side_bars"],375)

    def test_observed_session_priority_does_not_drop_unknown_dates(self):
        earlier=exp._request_body(date(2026,10,5),date(2026,10,6),"MONTH",0,"ATM","CALL")
        later=exp._request_body(date(2026,10,10),date(2026,10,11),"MONTH",0,"ATM","CALL")
        rank={"ATM":0}
        self.assertEqual(sync._prioritize([earlier,later],rank,["2026-10-06"]),[earlier,later])
        self.assertEqual(sync._prioritize([earlier,later],rank,[]),[later,earlier])
