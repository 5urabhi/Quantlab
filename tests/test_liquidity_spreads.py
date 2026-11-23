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

    def test_zerodha_tariffs_and_exact_account_side_cashflow_ledger(self):
        source=spreads.fee_schedule(249.0*90,250.0*90,
                                    broker_profile="zerodha")
        debit=source["buy_leg"];credit=source["sell_leg"]
        self.assertEqual(source["brokerage"],40.0)
        self.assertEqual(source["broker_profile"],"zerodha")
        self.assertEqual(debit["brokerage"],20.0)
        self.assertEqual(credit["brokerage"],20.0)
        self.assertEqual(debit["stt_sell"],0.0)
        self.assertGreater(credit["stt_sell"],0.0)
        self.assertGreater(debit["cash_debit"],debit["premium_turnover"])
        self.assertLess(credit["cash_credit"],credit["premium_turnover"])
        self.assertAlmostEqual(
            debit["fees_total"]+credit["fees_total"],
            source["total_estimated"],places=2)
        self.assertAlmostEqual(
            credit["cash_credit"]-debit["cash_debit"],
            90.0-source["total_estimated"],places=2)
        special=spreads.fee_schedule(249.0*90,250.0*90,
                      broker_profile="zerodha_debit_balance")
        self.assertEqual(special["brokerage"],80.0)
        self.assertGreater(special["total_estimated"],
                           source["total_estimated"])
        dhan=spreads.fee_schedule(249.0*90,250.0*90,
                                 broker_profile="dhan")
        self.assertEqual(dhan["brokerage"],40.0)
        self.assertEqual(dhan["broker_profile_name"],"Dhan regular retail")
        self.assertRaises(ValueError,spreads.fee_schedule,1000.,1000.,
                          broker_profile="unverified")

    def test_scanner_auto_tests_affordable_lots_and_marks_unavailable(self):
        from workstation_api import spread_scanner
        wide=original_book(
            self.t0+timedelta(minutes=5),
            "NSE_FNO:62540",bid=100,ask=110,quantity=300)
        expensive=original_book(
            self.t0+timedelta(minutes=5),
            "NSE_FNO:62541",bid=2000,ask=2500,quantity=300)
        extra=[wide,expensive]
        with live_market._database() as db:
            db.executemany(
                "INSERT INTO live_depth_books "
                "(identity,received_utc,session_id,book_json,packet_pair_sha256)"
                " VALUES(?,?,?,?,?)",
                [(row["identity"],row["received_utc"],
                 "auto20_synthetic_fixture",json.dumps(row),
                 sha256(("a"*64+"b"*64).encode()).hexdigest())
                 for row in extra])
        scan=spread_scanner.scan(
            day="2026-11-23",broker_profile="zerodha",
            capital_inr=50000,max_lots=10,adverse_move_bps=25)
        self.assertEqual(scan["original_depth_contracts_found"],3)
        self.assertEqual(scan["evaluated_source_books"],3)
        self.assertEqual(scan["total_rows"],3)
        self.assertEqual(scan["brokerage_per_executed_order_inr"],20.)
        self.assertEqual(scan["fills_observed"],False)
        self.assertIsNone(scan["net_realized_profit_inr"])
        self.assertFalse(scan["source_scan_truncated"])
        self.assertGreater(scan["positive_stressed_upper_bounds"],0)
        rows={x["identity"]:x for x in scan["rows"]}
        pos=rows["NSE_FNO:62540"]
        self.assertGreater(pos["passive_stressed_upper_net_inr"],0)
        self.assertEqual(pos["classification"],
            "POSITIVE_HYPOTHETICAL_STRESS_BOUND")
        self.assertFalse(pos["two_passive_fills_observed"])
        self.assertTrue(pos["best_hypothetical_lots"]<=10)
        self.assertGreater(len(pos["lot_scenarios"]),1)
        best=next(x for x in pos["lot_scenarios"]
                  if x["lots"]==pos["best_hypothetical_lots"])
        self.assertLessEqual(best["capital_required_inr"],50000)
        self.assertAlmostEqual(
            best["hypothetical_sell_cash_credit_inr"]-
            best["hypothetical_buy_cash_debit_inr"],
            best["passive_upper_net_inr"],places=2)
        self.assertIsNone(rows["NSE_FNO:62541"]["best_hypothetical_lots"])
        self.assertEqual(rows["NSE_FNO:62541"]["classification"],
                         "NO_AFFORDABLE_VERIFIED_DEPTH")
        self.assertEqual(
            scan["rankable_with_budget_and_depth"]+
            scan["no_feasible_lots"],scan["evaluated_source_books"])
        # A Dhan Quote/OI ID with no original 20-level book is not
        # invented as a fourth execution opportunity.
        self.assertNotIn("NSE_FNO:999999",rows)

        response=self.client.get("/api/trading-cockpit/liquidity/scan",params={
            "day":"2026-11-23","broker_profile":"zerodha",
            "capital_inr":50000,"max_lots":10,"adverse_move_bps":25})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()["evaluated_source_books"],3)
        invalid=self.client.get("/api/trading-cockpit/liquidity/scan",params={
            "day":"2026-11-23","capital_inr":999,"max_lots":10})
        self.assertEqual(invalid.status_code,400)
        invalid_profile=self.client.get(
            "/api/trading-cockpit/liquidity/scan",
            params={"day":"2026-11-23","broker_profile":"unknown"})
        self.assertEqual(invalid_profile.status_code,422)

    def test_scanner_keeps_invalid_original_books_out_of_profit_list(self):
        from workstation_api import spread_scanner
        value=original_book(self.t0+timedelta(minutes=5),
                            "NSE_FNO:62543",bid=100,ask=110)
        with live_market._database() as db:
            db.execute(
                "INSERT INTO live_depth_books "
                "(identity,received_utc,session_id,book_json,packet_pair_sha256)"
                " VALUES(?,?,?,?,?)",
                (value["identity"],value["received_utc"],
                 "auto20_invalid_fixture",json.dumps(value),"f"*64))
        report=spread_scanner.scan(day="2026-11-23")
        self.assertEqual(report["invalid_or_nonoriginal_books"],1)
        self.assertNotIn("NSE_FNO:62543",
                         {row["identity"] for row in report["rows"]})

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

    def test_execution_risk_missed_exit_has_full_costs_and_no_fabricated_ev(self):
        original = original_book(self.t0, bid=100., ask=110., quantity=150)
        projection = spreads.scenario(
            original, lots=1, broker_profile="zerodha",
            adverse_move_bps=25)
        r = spreads.execution_risk(
            original, projection, broker_profile="zerodha",
            adverse_move_bps=25, exit_slippage_bps=10)
        self.assertEqual(r["status"], "FILL_PROBABILITIES_UNKNOWN")
        self.assertIsNone(r["scenario_weighted_net_inr"])
        self.assertIsNone(r["realized_pnl_inr"])
        self.assertGreater(r["both_passive_fills_net_inr"], 0)
        self.assertLess(r["buy_fills_sell_misses_forced_exit_net_inr"], 0)
        self.assertGreater(r["premium_at_risk_inr"], 0)
        self.assertGreater(r["break_even_sell_fill_probability_given_buy"], 0)
        self.assertLess(r["break_even_sell_fill_probability_given_buy"], 1)

    def test_user_assumed_probabilities_are_sensitivity_not_predictions(self):
        original = original_book(self.t0, bid=249., ask=250., quantity=150)
        projection = spreads.scenario(original, lots=1,
                                      broker_profile="zerodha")
        r = spreads.execution_risk(
            original, projection, broker_profile="zerodha",
            buy_fill_probability=.5, sell_fill_probability_given_buy=.8)
        expected = .5 * (.8 * r["both_passive_fills_net_inr"] +
                         .2 * r["buy_fills_sell_misses_forced_exit_net_inr"])
        self.assertAlmostEqual(r["scenario_weighted_net_inr"], expected, places=2)
        self.assertEqual(r["probability_no_buy_fill"], .5)
        self.assertEqual(r["probability_both_fill"], .4)
        self.assertEqual(r["probability_buy_fill_exit_fails"], .1)
        self.assertFalse(r["fill_probabilities_calibrated"])
        self.assertRaises(ValueError, spreads.execution_risk,
            original, projection, buy_fill_probability=.5)
        self.assertRaises(ValueError, spreads.execution_risk,
            original, projection, buy_fill_probability=-.1,
            sell_fill_probability_given_buy=.2)

    def test_exit_depth_shortfall_disables_expected_value(self):
        original = original_book(self.t0, bid=249., ask=250., quantity=2)
        projection = spreads.scenario(original, lots=1,
                                      broker_profile="zerodha")
        r = spreads.execution_risk(
            original, projection, broker_profile="zerodha",
            buy_fill_probability=.8, sell_fill_probability_given_buy=.9)
        self.assertIsNone(r["scenario_weighted_net_inr"])
        self.assertEqual(r["status"], "TOP_OF_BOOK_INSUFFICIENT")

    def test_api_sensitivity_and_saved_quote_markouts_not_real_fills(self):
        response = self.client.post(
            "/api/trading-cockpit/liquidity/simulate", json={
                "identity": "NSE_FNO:62539", "day": "2026-11-23",
                "lots": 1, "received_utc": self.sample[0]["received_utc"],
                "broker_profile": "zerodha",
                "buy_fill_probability": .5,
                "sell_fill_probability_given_buy": .8,
                "exit_slippage_bps": 15})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        risk = body["assumptions"]["execution_risk"]
        self.assertFalse(risk["fill_probabilities_calibrated"])
        self.assertIsNotNone(risk["scenario_weighted_net_inr"])
        self.assertEqual(risk["realized_pnl_inr"], None)
        marks = body["future_saved_quote_markouts"]
        self.assertEqual([m["horizon_seconds"] for m in marks], [60, 300])
        self.assertEqual(marks[0]["status"], "FUTURE_SAVED_QUOTE_ONLY")
        self.assertEqual(marks[1]["status"], "NO_TIMELY_FUTURE_RECEIPT")
        self.assertNotIn("executed", str(marks).lower())
        for invalid in (
                {"buy_fill_probability": .4},
                {"buy_fill_probability": 2.,
                 "sell_fill_probability_given_buy": .4},
                {"exit_slippage_bps": -1}):
            res = self.client.post(
                "/api/trading-cockpit/liquidity/simulate",
                json={"identity": "NSE_FNO:62539",
                      "day": "2026-11-23", **invalid})
            self.assertIn(res.status_code, (400, 422))

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
