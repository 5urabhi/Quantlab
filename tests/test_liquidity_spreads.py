"""Offline acceptance for read-only BANKNIFTY Liquidity & Spreads.

Every observed book used by this suite is a synthetic protocol-valid fixture,
not a claim of Dhan market delivery, order execution or positive realized P&L.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import json

from fastapi.testclient import TestClient

from workstation_api import live_market, service, auto_option_depth as auto
from workstation_api import liquidity_spreads as spreads
from workstation_api.app import app


def original_book(stamp, identity="NSE_FNO:62539", *,
                  bid=249.0, ask=250.0, quantity=150):
    bids = [{"price": bid - i * .05, "quantity": quantity, "orders": 3}
            for i in range(20)]
    asks = [{"price": ask + i * .05, "quantity": quantity, "orders": 3}
            for i in range(20)]
    return {
        "identity":identity,"received_utc":stamp.isoformat(),
        "timestamp_kind":"local_receive",
        "bid":bids,"ask":asks,
        "bid_packet_sha256":"a"*64,
        "ask_packet_sha256":"b"*64,
        "source":"original_Dhan_full_market_depth_websocket",
        "collection_mode":"auto_banknifty_20_level",
        "computed_features":{
            "lot_size_verified":30,"expiry":"2026-11-23",
            "strike":63400.0,"side":"CE",
        },
    }


class LiquiditySpreadResearchTests(TestCase):
    def setUp(self):
        folder=TemporaryDirectory(prefix="quantlab_liquidity_offline_")
        self.addCleanup(folder.cleanup)
        root=Path(folder.name)
        p=patch.object(service,"DATA",root/"data")
        p.start();self.addCleanup(p.stop)
        pdb=patch.object(live_market,"DB_INITIALIZED",False)
        pdb.start();self.addCleanup(pdb.stop)
        self.client=TestClient(app,base_url="http://127.0.0.1:8765")
        self.addCleanup(self.client.close)
        live_market._init_db()
        self.t0=datetime(2026,11,23,4,5,tzinfo=timezone.utc)
        self.sample=[
            original_book(self.t0),
            original_book(self.t0+timedelta(minutes=2),bid=247.5,ask=249.),
            original_book(self.t0+timedelta(minutes=4),bid=245.,ask=246.75),
        ]
        with live_market._database() as db:
            db.executemany(
                "INSERT INTO live_depth_books "
                "(identity,received_utc,session_id,book_json,packet_pair_sha256)"
                " VALUES(?,?,?,?,?)",
                [("NSE_FNO:62539",book["received_utc"],
                  "auto20_20261123_fixture",json.dumps(book),
                  sha256(("a"*64+"b"*64).encode()).hexdigest())
                 for book in self.sample])

    def test_original_only_daily_history_and_exact_20_level_rows(self):
        data=spreads.book_history("NSE_FNO:62539","2026-11-23",limit=300)
        self.assertEqual(data["count"],3)
        self.assertEqual(len(data["books"][0]["bid_levels"]),20)
        self.assertEqual(len(data["books"][0]["ask_levels"]),20)
        self.assertAlmostEqual(data["books"][0]["spread_bps"],40.08,places=1)
        self.assertTrue(data["sampled_books_not_continuous"])
        self.assertEqual(data["source"],
                         "validated_original_Dhan_20_level_books_saved_to_dhan_shared")
        # Tampered source packet-pair digests must never become usable books.
        with live_market._database() as db:
            db.execute(
                "UPDATE live_depth_books SET packet_pair_sha256=? "
                "WHERE identity=? AND received_utc=?",
                ("f"*64,"NSE_FNO:62539",self.sample[0]["received_utc"]))
        verified=spreads.book_history("NSE_FNO:62539","2026-11-23")
        self.assertEqual(verified["count"],2)
        self.assertGreaterEqual(verified["rejected_or_not_auto_dhan"],1)
        self.assertEqual(spreads.book_history(
            "NSE_FNO:62539","2026-11-24")["count"],0)
        minimal=spreads.book_history(
            "NSE_FNO:62539","2026-11-23",include_levels=False)
        self.assertNotIn("bid_levels",minimal["books"][0])
        self.assertEqual(self.client.get(
            "/api/trading-cockpit/liquidity/history",
            params={"identity":"NSE_FNO:62539","day":"2026-11-23"}).status_code,200)

    def test_very_wide_spread_is_not_treated_as_guaranteed_profit(self):
        enormous=original_book(self.t0,bid=2753.15,ask=3625.75)
        result=spreads.scenario(enormous,lots=3)
        self.assertGreater(result["spread_bps"],2500)
        self.assertEqual(result["broker_orders_sent"],0)
        self.assertFalse(result["passive_capture_upper_bound"]["fills_observed"])
        self.assertIsNone(result["passive_capture_upper_bound"]["fill_probability"])
        self.assertEqual(result["marketable_roundtrip"]["fills_observed"],False)
        self.assertLess(result["marketable_roundtrip"]["estimated_net_inr"],0)

    def test_one_lot_market_making_cost_and_90_unit_depth_walking(self):
        one=spreads.scenario(self.sample[0],lots=1)
        three=spreads.scenario(self.sample[0],lots=3,adverse_move_bps=50)
        self.assertLess(one["passive_capture_upper_bound"][
            "upper_bound_net_inr_before_unmodelled_costs"],0)
        self.assertEqual(three["units"],90)
        self.assertEqual(three["marketable_buy"]["observed_units"],90)
        self.assertEqual(three["marketable_sell"]["levels_used"],1)
        self.assertEqual(three["marketable_buy"]["levels_used"],1)
        self.assertLess(three["marketable_roundtrip"]["gross_inr"],0)
        self.assertLess(three["marketable_roundtrip"]["estimated_net_inr"],0)
        self.assertLess(three["passive_capture_upper_bound"][
            "after_adverse_move_stress_inr"],three[
                "passive_capture_upper_bound"][
                "upper_bound_net_inr_before_unmodelled_costs"])
        fees=three["passive_capture_upper_bound"]["fees"]
        self.assertEqual(fees["brokerage"],40.0)
        self.assertGreater(fees["stt_sell"],0)
        self.assertGreater(fees["exchange_indicative"],0)

    def test_insufficient_observed_depth_blocks_marketable_fill_assumption(self):
        weak=original_book(self.t0,quantity=1)
        out=spreads.scenario(weak,lots=3)
        self.assertFalse(out["marketable_buy"]["fillable"])
        self.assertFalse(out["marketable_sell"]["fillable"])
        self.assertIsNone(out["marketable_roundtrip"]["estimated_net_inr"])
        self.assertFalse(out["passive_capture_upper_bound"][
            "top_of_book_quantity_sufficient_both_sides"])

    def test_original_history_selection_is_exact_and_no_orders(self):
        resp=self.client.post("/api/trading-cockpit/liquidity/simulate",json={
            "identity":"NSE_FNO:62539","lots":3,
            "day":"2026-11-23",
            "received_utc":self.sample[0]["received_utc"],
            "executed_orders_per_side":1,"adverse_move_bps":25,
        })
        self.assertEqual(resp.status_code,200,resp.text)
        row=resp.json()
        self.assertEqual(row["status"],"ORIGINAL_BOOK_SCENARIO_ONLY")
        self.assertEqual(row["selected_book_received_utc"],
                         self.sample[0]["received_utc"])
        self.assertEqual(row["assumptions"]["broker_orders_sent"],0)
        self.assertFalse(row["assumptions"]["passive_capture_upper_bound"][
            "fills_observed"])
        missing=self.client.post("/api/trading-cockpit/liquidity/simulate",json={
            "identity":"NSE_FNO:62539","day":"2026-11-24","lots":1})
        self.assertEqual(missing.status_code,200,missing.text)
        self.assertEqual(missing.json()["status"],"ORIGINAL_BOOK_MISSING")
        unknown=self.client.post("/api/trading-cockpit/liquidity/simulate",json={
            "identity":"NSE_FNO:62539","day":"2026-11-23",
            "received_utc":"2026-11-23T04:06:00+00:00","lots":2})
        self.assertEqual(unknown.status_code,400)

    def test_local_source_filters_and_no_untrusted_external_id(self):
        for invalid in ("../../.env","NSE_EQ:62539","NSE_FNO:invalid"):
            response=self.client.get("/api/trading-cockpit/liquidity/history",
                params={"identity":invalid,"day":"2026-11-23"})
            self.assertEqual(response.status_code,400,response.text)
        invalid=self.client.post("/api/trading-cockpit/liquidity/simulate",json={
            "identity":"NSE_FNO:62539","day":"2026-11-23",
            "lots":0,"confirm_live_order":True})
        self.assertEqual(invalid.status_code,422)
        self.assertTrue(spreads.book_history("NSE_FNO:62539","2026-11-23")["read_only"])

    def test_snapshot_sensitivity_is_not_filled_order_backtest(self):
        result=spreads.research("NSE_FNO:62539","2026-11-23",lots=3,
                                adverse_move_bps=30)
        self.assertEqual(result["observed_saved_books"],3)
        self.assertIsNone(result["realized_pnl"])
        self.assertIsNone(result["fill_rate"])
        self.assertIsNone(result["sharpe"])
        self.assertIsNone(result["net_profitable_executed_trades"])
        self.assertEqual(result["executed_trades"],0)
        self.assertEqual(len(result["samples"]),3)
        res=self.client.get("/api/trading-cockpit/liquidity/research",
            params={"identity":"NSE_FNO:62539","day":"2026-11-23",
                    "lots":3,"adverse_move_bps":30})
        self.assertEqual(res.status_code,200,res.text)
        self.assertIn("NOT a backtest",res.json()["warning"])

    def test_live_selected_source_summary_does_not_invent_stale_quotes(self):
        fake={
          "contracts":[
            {"identity":"NSE_FNO:62539","expiry":"2026-11-23","strike":63400,
             "side":"CE","lot_size":30,"coverage_role":"core"},
            {"identity":"NSE_FNO:62540","expiry":"2026-11-23","strike":63400,
             "side":"PE","lot_size":30,"coverage_role":"rotating"},
          ],
          "latest":{"NSE_FNO:62539":{
              "best_bid":249.,"best_ask":250.,"book_imbalance_20":.1,
              "feed_fresh":True,"age_seconds":30,
              "received_utc":"2026-11-23T04:05:00+00:00"},
            "NSE_FNO:62540":{"best_bid":220.,"best_ask":221.,
              "feed_fresh":False,"age_seconds":100}},
          "contract_receipts":{"NSE_FNO:62539":{"pair_age_seconds":2}},
          "connected":True,"market_regular_hours":True,"state":"source_active",
        }
        with patch.object(auto,"status",return_value=fake):
            overview=spreads.overview()
            self.assertEqual(overview["configured_depth_contracts"],2)
            self.assertEqual(overview["fresh_spread_sample_size"],1)
            self.assertEqual(overview["rows"][0]["identity"],"NSE_FNO:62539")
            self.assertTrue(overview["rows"][0]["feed_fresh"])
            self.assertFalse(overview["rows"][1]["feed_fresh"])
            self.assertAlmostEqual(
                overview["mean_fresh_spread_bps"],40.08,places=1)
            self.assertEqual(
                self.client.get("/api/trading-cockpit/liquidity/overview").status_code,200)
