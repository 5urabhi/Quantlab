"""Offline fixtures for persistent manual-options workflow; no broker orders."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import json

from workstation_api import advanced_options as ao, india_vix, live_market, service
from workstation_api import manual_options_workflow as wf, manual_trade_journal as journal
from workstation_api import option_chain_live, liquidity_spreads

NOW=datetime(2026,11,24,5,0,0,123456,tzinfo=timezone.utc)
EXPIRY="2026-11-24"
FAR="2026-12-29"
ID="NSE_FNO:1001"


def row(identity=ID, strike=63000., expiry=EXPIRY, bid=None, ask=None,
        side="CE", quantity=600):
    years=(datetime.fromisoformat(expiry+"T15:30:00+05:30")-NOW).total_seconds()/ao.YEAR_SECONDS
    mid=ao.bsm(63000.,strike,years,.065,.18,side,0.)["price"]
    bid=round(mid-.05,2) if bid is None else bid
    ask=round(mid+.05,2) if ask is None else ask
    return {"identity":identity,"symbol":"BANKNIFTY"+identity.split(":")[1]+side,
            "expiry":expiry,"strike":strike,"option_type":side,"lot_size":30,
            "contract_master_verified":True,"quote_valid":True,"bid":bid,"ask":ask,
            "ltp":(bid+ask)/2,"top_bid_quantity":quantity,"top_ask_quantity":quantity,
            "oi":3000,"volume":6000,"iv":18.,"delta":None,"gamma":None,
            "theta":None,"vega":None}


def chain(stamp=NOW, expiry=EXPIRY, rows=None):
    return {"source":wf.CHAIN_SOURCE,"underlying":"BANKNIFTY","underlying_spot":63000.,
            "expiry":expiry,"received_utc":stamp.isoformat(),"read_only":True,
            "contracts":rows if rows is not None else [row(expiry=expiry)]}


def master(c):
    return {"fresh":True,"by_id":{c["identity"].split(":")[1]:c}}


class ManualOptionsWorkflowTests(TestCase):
    def setUp(self):
        folder=TemporaryDirectory(prefix="quantlab_manual_options_")
        self.addCleanup(folder.cleanup)
        self.root=Path(folder.name)/"data"
        for obj,key,value in ((service,"DATA",self.root),(live_market,"DB_INITIALIZED",False)):
            p=patch.object(obj,key,value);p.start();self.addCleanup(p.stop)
        live_market._init_db()
        ao._daily_history.cache_clear()
        self.addCleanup(ao._daily_history.cache_clear)
        with live_market._database() as db:
            db.execute("""CREATE TABLE option_chain_observations(
                underlying TEXT,expiry TEXT,captured_utc TEXT,snapshot_sha256 TEXT,
                normalized_json TEXT,PRIMARY KEY(underlying,expiry,captured_utc))""")

    def save(self, data, bad_hash=False):
        raw=json.dumps(data,sort_keys=True,separators=(",",":"))
        with live_market._database() as db:
            db.execute("INSERT INTO option_chain_observations VALUES(?,?,?,?,?)",
                ("BANKNIFTY",data["expiry"],data["received_utc"],
                 "bad" if bad_hash else sha256(raw.encode()).hexdigest(),raw))

    def test_cross_expiry_only_current_integrity_checked_receipts(self):
        self.save(chain())
        self.save(chain(NOW-timedelta(seconds=80),FAR))
        x=wf.compare(now=NOW,capital=50000,max_lots=3,direction="UP",move_points=100,
                     horizon_minutes=5,broker_profile="zerodha")
        self.assertFalse(x["orders_enabled"])
        self.assertGreater(x["ranked_count"],0)
        self.assertEqual({r["expiry"] for r in x["rows"]},{EXPIRY})
        self.assertEqual(x["coverage"][1]["state"],"delayed_or_closed")
        self.save(chain(NOW+timedelta(seconds=1),FAR),bad_hash=True)
        x=wf.compare(now=NOW+timedelta(seconds=1))
        self.assertEqual(x["coverage"][1]["state"],"invalid_source")

    def test_existing_journal_link_marks_exit_and_no_stale_profit(self):
        c=row()
        # Old journal records stay readable and are not guessed from symbol.
        p=journal.enter(c["symbol"],"CALL",30,150.)
        self.assertIsNone(p["contract_identity"])
        self.assertEqual(wf.position_marks(now=NOW)["positions"][0]["state"],"unlinked_contract")
        with patch.object(option_chain_live,"_contracts",return_value=master(c)):
            with self.assertRaises(ValueError):
                journal.enter(c["symbol"],"CALL",31,150.,contract_identity=ID)
            linked=journal.link_trade(p["id"],ID)
        self.assertEqual(linked["contract_identity"],ID)
        self.save(chain(rows=[c]))
        x=wf.position_marks(now=NOW,target_pct=5,stop_pct=2.5)
        pos=x["positions"][0]
        expected=wf._net(150.,c["bid"],30,"zerodha")[0]
        self.assertAlmostEqual(pos["estimated_net_pnl_inr"],expected)
        self.assertEqual(pos["mark"]["source"],"saved_chain_top_bid")
        self.assertIsNotNone(pos["greeks"])
        self.assertGreater(pos["exit_levels"]["break_even"]["sell_bid"],150.)
        self.assertGreater(pos["exit_levels"]["profit_target"]["sell_bid"],
                           pos["exit_levels"]["break_even"]["sell_bid"])
        self.assertLess(pos["exit_levels"]["stop_loss"]["sell_bid"],
                        pos["exit_levels"]["break_even"]["sell_bid"])
        self.assertIsNotNone(pos["exit_levels"]["profit_target"]["model_underlying_move_points"])
        stale=wf.position_marks(now=NOW+timedelta(seconds=31))["positions"][0]
        self.assertIsNone(stale["estimated_net_pnl_inr"])
        self.assertEqual(stale["state"],"no_recent_quote")
        closed=journal.exit_trade(p["id"],160.,65.)
        self.assertEqual(closed["contract_identity"],ID)
        self.assertEqual(closed["net_pnl_inr"],235.)
        self.assertEqual(wf.position_marks(now=NOW)["total_open"],0)

    def test_insufficient_full_size_quote_does_not_create_mark(self):
        c=row(quantity=5)
        with patch.object(option_chain_live,"_contracts",return_value=master(c)):
            journal.enter(c["symbol"],"CALL",30,150.,contract_identity=ID)
        self.save(chain(rows=[c]))
        x=wf.position_marks(now=NOW)
        self.assertEqual(x["marked_count"],0)
        self.assertEqual(x["positions"][0]["state"],"insufficient_displayed_bid_quantity")
        self.assertIsNone(x["positions"][0]["estimated_net_pnl_inr"])

    def test_alerts_use_new_receipts_only_and_deduplicate_matching_state(self):
        c=row(bid=99,ask=100)
        self.save(chain(NOW-timedelta(seconds=1),rows=[c]))
        with patch.object(option_chain_live,"_contracts",return_value=master(c)):
            a=wf.create_alert(ID,{"max_ask":101,"max_spread_bps":250,"min_top_units":30},now=NOW)
        wf.cycle(now=NOW)
        self.assertEqual(len(wf.overview()["events"]),0)
        self.save(chain(NOW+timedelta(seconds=2),rows=[c]))
        wf.cycle(now=NOW+timedelta(seconds=3))
        wf.cycle(now=NOW+timedelta(seconds=4))
        self.assertEqual(len(wf.overview()["events"]),1)
        self.save(chain(NOW+timedelta(seconds=5),rows=[{**c,"ask":110}]))
        wf.cycle(now=NOW+timedelta(seconds=6))
        self.save(chain(NOW+timedelta(seconds=7),rows=[c]))
        wf.cycle(now=NOW+timedelta(seconds=8))
        self.assertEqual(len(wf.overview()["events"]),2)
        wf.disable_alert(a["id"])
        self.assertFalse(wf.overview()["rules"][0]["enabled"])

    def test_preregistered_markout_and_matched_controls_use_only_future_receipts(self):
        rows=[row("NSE_FNO:"+str(i),strike=63000.+(i-1001)*25,bid=99,ask=100)
              for i in range(1001,1005)]
        observed=chain(rows=rows)
        self.save(observed)
        ranked=[{**r,"rank":i+1,"units":30,"score":90-i*10,
                  "rank_quality":"indicative_snapshot_only"} for i,r in enumerate(rows)]
        analysis={"chain":observed,"rows":ranked,"as_of_utc":NOW.isoformat(),
                  "assumptions":{"horizon_minutes":1,"broker_profile":"zerodha"}}
        self.assertEqual(wf.record_if_enabled(analysis,now=NOW),0)
        wf.set_tracking(True)
        decision=NOW+timedelta(seconds=1)
        self.assertEqual(wf.record_if_enabled(analysis,now=decision),4)
        self.assertEqual(wf.record_if_enabled(analysis,now=decision+timedelta(seconds=1)),0)
        wf.cycle(now=decision)
        self.assertEqual(wf.overview()["sample_counts"]["waiting_entry"],4)
        entry=decision+timedelta(seconds=10)
        self.save(chain(entry,rows=rows))
        wf.cycle(now=entry)
        self.assertEqual(wf.overview()["sample_counts"]["waiting_exit"],4)
        # A much better bid before the registered horizon is ignored.
        self.save(chain(entry+timedelta(seconds=30),rows=[{**r,"bid":200,"ask":201} for r in rows]))
        exit_=entry+timedelta(seconds=61)
        self.save(chain(exit_,rows=[{**r,"bid":110 if i<2 else 105,"ask":111 if i<2 else 106}
                                    for i,r in enumerate(rows)]))
        wf.cycle(now=exit_)
        report=wf.overview()
        self.assertEqual(report["observed_count"],2)
        self.assertEqual(report["control_observed_count"],2)
        self.assertEqual(report["paired_count"],2)
        self.assertGreater(report["paired_mean_return_difference_pp"],0)
        for s in report["samples"]:
            self.assertEqual(s["entry_ask"],100)
            self.assertEqual(s["entry_utc"],entry.isoformat())
            self.assertEqual(s["exit_utc"],exit_.isoformat())
            self.assertLess(s["exit_bid"],200)

    def test_missing_forward_window_is_censored_not_zero_profit(self):
        r=row()
        observed=chain(rows=[r])
        self.save(observed)
        wf.set_tracking(True)
        x={"chain":observed,"as_of_utc":NOW.isoformat(),
            "assumptions":{"horizon_minutes":1,"broker_profile":"zerodha"},
            "rows":[{**r,"rank":1,"units":30,"score":80.,"rank_quality":"indicative_snapshot_only"}]}
        decision=NOW+timedelta(seconds=1)
        self.assertEqual(wf.record_if_enabled(x,now=decision),1)
        wf.cycle(now=decision+timedelta(seconds=76))
        report=wf.overview()
        self.assertEqual(report["sample_counts"]["entry_unobservable"],1)
        self.assertEqual(report["observed_count"],0)
        self.assertIsNone(report["samples"][0]["net_pnl_inr"])

    def test_india_vix_unique_official_master_and_cache(self):
        import os
        path=self.root/"dhan"/"instrument_master.csv"
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text("EXCH_ID,SEGMENT,SECURITY_ID,INSTRUMENT,TRADING_SYMBOL\n"
                        "NSE,I,999,INDEX,INDIA VIX\n"
                        "NSE,E,123,EQUITY,INDIA VIX\n")
        india_vix.CACHE.clear();india_vix._resolve.cache_clear()
        self.addCleanup(india_vix.CACHE.clear)
        with patch.dict(os.environ,{"DHAN_ACCESS_TOKEN":"offline_fixture_token"}), \
             patch.object(india_vix.dhan_workspace,"_master",return_value=path), \
             patch.object(option_chain_live,"_credentials",return_value=("offline_fixture_token","1")), \
             patch.object(india_vix.dhan_option_chain,"_json_http",return_value=(
                 {"status":"success","data":{"IDX_I":{"999":{"last_price":15.4}}}},b"{}")) as get:
            first=india_vix.current();second=india_vix.current()
            self.assertEqual(first["identity"],"IDX_I:999")
            self.assertEqual(first["value"],15.4)
            self.assertTrue(second["cache_hit"])
            get.assert_called_once()
            self.assertEqual(get.call_args.kwargs["body"],{"IDX_I":[999]})
            self.assertNotIn("offline_fixture_token",json.dumps(first))
