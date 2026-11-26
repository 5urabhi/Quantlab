"""No-network regressions for BANKNIFTY spot signals -> historical CE/PE P&L.

All option candles below are synthetic TEST FIXTURES. Production never uses
them, only original Dhan responses and SHA-verified locally saved receipts.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from io import BytesIO
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from workstation_api import service, expired_options_backtest as exp
from workstation_api.app import app

START = datetime(2026, 11, 18, 4, 0, tzinfo=timezone.utc)
DAY = "2026-11-18"


def stamp(i):
    return (START + timedelta(minutes=i)).isoformat()


def source(count=70):
    rows = []
    for i in range(count):
        px = 62000 + i * .5
        rows.append({"timestamp_utc": stamp(i), "session_ist": DAY,
                     "open": px, "high": px + 1, "low": px - 1,
                     "close": px + .2, "volume": 0})
    return rows


def quote(i, strike=62000, side="CALL", open_price=300., close_price=None,
          volume=20):
    px = open_price if close_price is None else close_price
    return {"timestamp_utc": stamp(i), "session_ist": DAY, "strike": strike,
            "side": side, "open": open_price, "high": max(px, open_price) + 1,
            "low": min(px, open_price) - 1, "close": px, "volume": volume,
            "expiry_flag": "MONTH", "expiry_code": 0, "origin_offset": "ATM"}


def market(count=70, sides=("CALL", "PUT")):
    lookup = {}
    for i in range(count):
        for side in sides:
            lookup[(stamp(i), side)] = {
                62000.: quote(i, side=side, open_price=300 + .25*i,
                              close_price=300 + .25*i)}
    return lookup


def events(*pairs):
    return [{"bar_utc": stamp(i), "session_ist": DAY, "direction": signal}
            for i, signal in pairs]


def fake_dhan(body):
    assert body["securityId"] == 25
    assert body["instrument"] == "OPTIDX"
    assert body["exchangeSegment"] == "NSE_FNO"
    assert body["interval"] == "1"
    assert body["expiryFlag"] == "MONTH"
    assert body["expiryCode"] == 1
    off = body["strike"]
    index = (int(off[4:]) if off.startswith("ATM+") else
             -int(off[4:]) if off.startswith("ATM-") else 0)
    strike = 62000 + 100*index
    base = 300. + 35*index
    prices = [base + .5*i for i in range(70)]
    content = {"timestamp": [int((START + timedelta(minutes=i)).timestamp())
                             for i in range(70)],
               "open": prices, "high": [p + 1 for p in prices],
               "low": [p - 1 for p in prices], "close": prices,
               "volume": [100]*70, "oi": [200]*70, "iv": [12]*70,
               "strike": [strike]*70, "spot": [62000.]*70}
    side = "ce" if body["drvOptionType"] == "CALL" else "pe"
    return {"data": {"ce": content if side == "ce" else None,
                     "pe": content if side == "pe" else None}}


class ExpiredOptionsBacktestTests(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(prefix="quantlab_expired_options_test_")
        self.addCleanup(td.cleanup)
        self.data_patch = patch.object(service, "DATA", Path(td.name))
        self.data_patch.start()
        self.addCleanup(self.data_patch.stop)

    @staticmethod
    def _crossover_source():
        """Two turning trends and a late recovery; all within one NSE session."""
        rows = []
        for i in range(120):
            if i < 30:
                price = 63000 - 4 * i
            elif i < 65:
                price = 63000 - 4 * 29 + 8 * (i - 29)
            elif i < 99:
                price = 63000 - 4 * 29 + 8 * (65 - 29) - 12 * (i - 65)
            else:
                price = 63000 - 4 * 29 + 8 * (65 - 29) - 12 * (99 - 65) + 12 * (i - 99)
            rows.append({
                "timestamp_utc": stamp(i), "session_ist": DAY,
                "open": price, "high": price + 2, "low": price - 2,
                "close": price, "volume": 100,
            })
        return rows

    def test_pure_ema_cross_changes_direction_only_on_confirmed_cross(self):
        rows = self._crossover_source()
        signals = exp._signals(rows, signal_model="ema_crossover")
        crosses = [x for x in signals if x["direction"] != "NO_TRADE"]
        self.assertGreaterEqual(len(crosses), 2, crosses)
        self.assertEqual([x["direction"] for x in crosses[:2]],
                         ["UP", "DOWN"])
        self.assertEqual(len(crosses), len({x["bar_utc"] for x in crosses}))
        self.assertTrue(all(x["ema9"] is not None and x["ema21"] is not None
                            for x in crosses))
        for event in crosses:
            if event["direction"] == "UP":
                self.assertGreater(event["ema9"], event["ema21"])
                self.assertEqual(event["signal_kind"], "cross_above")
            else:
                self.assertLess(event["ema9"], event["ema21"])
                self.assertEqual(event["signal_kind"], "cross_below")
        self.assertTrue(all(x["direction"] == "NO_TRADE" for x in signals[:21]))
        self.assertNotEqual(exp._signals(rows, signal_model="ema_rsi"),
                            signals)

    def test_ema_cross_is_prefix_causal_no_future_candle_lookahead(self):
        rows = self._crossover_source()
        final = exp._signals(rows, signal_model="ema_crossover")
        for cutoff in (20, 29, 40, 55, 68, 82, 101, 120):
            prefix = exp._signals(rows[:cutoff], signal_model="ema_crossover")
            self.assertEqual(prefix, final[:cutoff])
        self.assertTrue(all(e["direction"] in ("UP", "DOWN", "NO_TRADE")
                            for e in final))

    def test_ema_crossover_resets_on_missing_minutes_and_new_session(self):
        rows = self._crossover_source()
        # A missing minute must not be forward-filled to generate a crossover.
        missing = rows[:43] + rows[44:70]
        broken = exp._signals(missing, signal_model="ema_crossover")
        self.assertTrue(all(e["direction"] == "NO_TRADE"
                            for e in broken[43:64]))
        tomorrow = (START + timedelta(days=1)).date().isoformat()
        other = []
        for i, item in enumerate(rows[:29]):
            other.append({**item,
                "timestamp_utc": (START + timedelta(days=1, minutes=i)).isoformat(),
                "session_ist": tomorrow})
        combined = exp._signals(rows[:45] + other, signal_model="ema_crossover")
        self.assertEqual(combined[45:],
                         exp._signals(other, signal_model="ema_crossover"))

    def test_crossover_signals_work_with_existing_ce_pe_reversal_simulator(self):
        rows = self._crossover_source()
        signals = exp._signals(rows, signal_model="ema_crossover")
        # Synthetic TEST fixture only; real backtests require original
        # Dhan option candles, exact expiry and provider lot evidence.
        options = {}
        for i in range(len(rows)):
            for side in ("CALL", "PUT"):
                options[(stamp(i), side)] = {
                    63000.: quote(i, strike=63000, side=side,
                                  open_price=300 + i * .03,
                                  close_price=300 + i * .03)}
        result = exp.simulate_options(
            signals, rows, options, policy="signal_reversal",
            hold=1, cap=2,  # Ignored for reversal-only holding.
            target_ltp=300, tolerance=50, lots=1, slippage_bps=0,
            fee_per_side=0)
        self.assertGreaterEqual(result["trade_count"], 1)
        self.assertEqual(result["trades"][0]["option_side"], "CE")
        self.assertEqual(result["trades"][0]["exit_reason"], "opposite_signal")
        self.assertGreater(result["trades"][0]["hold_minutes"], 6)
        self.assertTrue(result["trades"][0]["entry_utc"] >
                        result["trades"][0]["signal_utc"])

    def test_unrecognized_signal_model_is_rejected_before_network(self):
        with self.assertRaisesRegex(ValueError, "EMA/RSI or EMA"):
            exp._validate_params(
                limit=500, expiry_flag="MONTH", expiry_code=0,
                wings=3, lot_size=30, lots=1, target_ltp=300,
                tolerance=50, starting_capital=50000,
                stop_pct=2.5, target_pct=5, slippage_bps=5,
                fee_per_side=20, hold_rule="signal_reversal",
                hold_minutes=5, reversal_cap_minutes=10,
                signal_model="not_a_strategy")

    def test_contract_selection_uses_signal_close_and_keeps_strike(self):
        quotes = market()
        quotes[(stamp(29), "CALL")] = {
            62000.: quote(29, strike=62000, open_price=300, close_price=300),
            62100.: quote(29, strike=62100, open_price=350, close_price=330),
        }
        # ATM-relative offsets move, but actual strike 62000 must be held.
        quotes[(stamp(30), "CALL")] = {
            62000.: quote(30, strike=62000, open_price=305, close_price=305),
            62100.: quote(30, strike=62100, open_price=280, close_price=280),
        }
        result = exp.simulate_options(events((29,"UP")), source(), quotes,
                                       policy="fixed", hold=5, target_ltp=300)
        self.assertEqual(result["trade_count"], 1)
        trade = result["trades"][0]
        self.assertEqual(trade["strike"], 62000)
        self.assertEqual(trade["selection_ltp"], 300)
        self.assertEqual(trade["entry_utc"], stamp(30))
        self.assertEqual(trade["exit_utc"], stamp(35))
        self.assertEqual(trade["units"], 90)
        self.assertFalse(trade["contract_identity_verified"])

    def test_missing_strike_mid_trade_blocks_all_later_positions_in_day(self):
        quotes = market()
        quotes[(stamp(33), "CALL")] = {62100.: quote(33, strike=62100)}
        result = exp.simulate_options(events((29,"UP"), (40,"DOWN")),
                                      source(), quotes, policy="fixed", hold=5)
        self.assertEqual(result["trade_count"], 0)
        self.assertEqual(result["unscored"]["missing_exact_contract_path"], 1)
        self.assertEqual(result["unscored"]["position_open"], 1)

    def test_premium_stop_only_checks_closed_minute_and_exits_next_open(self):
        quotes = market()
        quotes[(stamp(29), "CALL")] = {
            62000.: quote(29, close_price=300, open_price=300)}
        quotes[(stamp(30), "CALL")] = {
            62000.: quote(30, open_price=300, close_price=290)}
        quotes[(stamp(31), "CALL")] = {
            62000.: quote(31, open_price=280, close_price=280)}
        result = exp.simulate_options(events((29,"UP")), source(), quotes,
                                      policy="premium_target_stop", hold=5,
                                      slippage_bps=0, stop_pct=2.5,
                                      target_pct=5, fee_per_side=20)
        self.assertEqual(result["trade_count"], 1)
        trade = result["trades"][0]
        self.assertEqual(trade["exit_utc"], stamp(31))
        self.assertEqual(trade["exit_reason"], "stop_close_next_open")
        self.assertEqual(trade["exit_premium"], 280)
        self.assertEqual(trade["net_pnl_inr"], -1840)

    def test_opposite_banknifty_signal_maps_to_put_not_short_ce(self):
        result = exp.simulate_options(events((29,"DOWN"), (35,"UP")),
                                      source(), market(), policy="signal_reversal",
                                      slippage_bps=0)
        self.assertEqual(result["trade_count"], 1)
        self.assertEqual(result["trades"][0]["option_side"], "PE")
        self.assertEqual(result["trades"][0]["exit_utc"], stamp(36))
        self.assertEqual(result["trades"][0]["exit_reason"], "opposite_signal")

    def test_full_up_down_up_flips_ce_pe_ce_at_identical_next_open(self):
        """Reverse long CE -> long PE -> long CE, no overlapping execution."""
        # Calls/puts can require different actual strikes to reach ~INR300.
        # The chosen PE must be re-selected from PUT prices, never inherit
        # the previous CE's strike.
        quotes = market()
        for i in range(70):
            premium = 300 + .25 * i
            quotes[(stamp(i), "PUT")] = {
                62100.: quote(i, strike=62100, side="PUT",
                              open_price=premium, close_price=premium)}
        outcome = exp.simulate_options(
            events((29, "UP"), (32, "NO_TRADE"), (35, "DOWN"), (40, "UP")),
            source(), quotes, policy="signal_reversal_or_cap",
            hold=5, cap=10, slippage_bps=0)
        self.assertEqual(outcome["trade_count"], 3)
        self.assertEqual(outcome["reversal_switches"], 2)
        self.assertEqual(outcome["reversal_audit"]["opposite_signal_exits"], 2)
        self.assertEqual(outcome["reversal_audit"]["same_open_reentry_attempts"], 2)
        self.assertEqual(outcome["reversal_audit"]["rejected_reentry_reasons"], {})
        first, second, third = outcome["trades"]
        self.assertEqual(
            [(t["option_side"], t["entry_utc"], t["exit_utc"])
             for t in (first, second, third)],
            [("CE", stamp(30), stamp(36)),
             ("PE", stamp(36), stamp(41)),
             ("CE", stamp(41), stamp(51))])
        self.assertEqual(
            [t["entry_reason"] for t in outcome["trades"]],
            ["signal_entry", "opposite_signal_flip", "opposite_signal_flip"])
        self.assertEqual([first["strike"], second["strike"], third["strike"]],
                         [62000., 62100., 62000.])
        self.assertEqual(first["exit_reason"], "opposite_signal")
        self.assertEqual(second["exit_reason"], "opposite_signal")
        self.assertEqual(second["flipped_from_option_side"], "CE")
        self.assertEqual(third["flipped_from_option_side"], "PE")
        self.assertEqual(first["exit_utc"], second["entry_utc"])
        self.assertEqual(second["exit_utc"], third["entry_utc"])
        self.assertEqual(sum(t["assumed_fees_inr"]
                             for t in outcome["trades"]), 120)
        self.assertEqual(outcome["unscored"].get("position_open", 0), 0)

    def test_no_trade_does_not_trigger_close_or_reverse(self):
        result = exp.simulate_options(
            events((29, "UP"), (32, "NO_TRADE"), (35, "DOWN")),
            source(), market(), policy="signal_reversal",
            slippage_bps=0)
        self.assertEqual(result["trade_count"], 1)
        self.assertEqual(result["trades"][0]["exit_utc"], stamp(36))
        self.assertEqual(result["trades"][0]["exit_reason"], "opposite_signal")
        self.assertEqual(result["reversal_switches"], 0)

    def test_fixed_time_exit_cannot_trigger_automatic_flip(self):
        result = exp.simulate_options(
            events((29, "UP"), (34, "DOWN")), source(), market(),
            policy="fixed", hold=5, slippage_bps=0)
        self.assertEqual(result["trade_count"], 1)
        self.assertEqual(result["trades"][0]["exit_utc"], stamp(35))
        self.assertEqual(result["trades"][0]["exit_reason"], "fixed_hold")
        self.assertEqual(result["reversal_switches"], 0)
        self.assertEqual(result["unscored"]["position_open"], 1)

    def test_reverse_exit_stays_flat_when_new_put_has_no_real_option_candle(self):
        only_ce = market(sides=("CALL",))
        result = exp.simulate_options(
            events((29, "UP"), (35, "DOWN")), source(), only_ce,
            policy="signal_reversal", slippage_bps=0)
        self.assertEqual(result["trade_count"], 1)
        self.assertEqual(result["reversal_switches"], 0)
        self.assertEqual(result["trades"][0]["exit_reason"], "opposite_signal")
        self.assertEqual(result["trades"][0]["exit_utc"], stamp(36))
        self.assertEqual(result["unscored"]["no_option_near_target_at_signal"], 1)
        self.assertEqual(result["reversal_audit"]["opposite_signal_exits"], 1)
        self.assertEqual(result["reversal_audit"]["completed_flips"], 0)
        self.assertEqual(result["reversal_audit"]["rejected_reentry_reasons"],
                         {"no_option_near_target_at_signal": 1})

    def test_expired_source_is_fetched_then_reused_without_second_vendor_call(self):
        start = date(2026, 11, 18)
        end = date(2026, 11, 19)
        called = []
        def first(body):
            called.append(body)
            return fake_dhan(body)
        lookup, first_receipt = exp.load_option_market(
            start, end, expiry_flag="MONTH", expiry_code=0,
            wings=1, fetcher=first)
        self.assertEqual(first_receipt["fresh_requests"], 6)
        self.assertEqual(len(called), 6)
        self.assertIn(62000., lookup[(stamp(29), "CALL")])
        def must_not_fetch(_):
            raise AssertionError("Cached original Dhan data must be reused")
        lookup2, reuse = exp.load_option_market(
            start, end, expiry_flag="MONTH", expiry_code=0,
            wings=1, fetcher=must_not_fetch)
        self.assertEqual(reuse["cached_requests"], 6)
        self.assertEqual(reuse["fresh_requests"], 0)
        self.assertEqual(len(lookup), len(lookup2))

    def test_source_sha_corruption_is_detected_not_silently_replaced(self):
        body = exp._request_body(date(2026, 11, 18),
                                 date(2026, 11, 19), "MONTH", 0,
                                 "ATM", "CALL")
        exp._save_cache(body, fake_dhan(body))
        path = exp._cache_path(body)
        contents = path.read_text()
        path.write_text(contents.replace('"sha256":"', '"sha256":"tampered'), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "corrupted"):
            exp._get_cached(body)

    def test_running_uses_only_actual_original_option_candles(self):
        spot = source()
        with patch.object(exp.cockpit_sources, "series",
                          return_value={"rows": spot, "warning": "fixture",
                                        "has_more": False}), patch.object(
                          exp, "_signals", return_value=events((29,"UP"))), patch.object(
                          exp, "_ist_today", return_value=date(2026, 12, 2)):
            report = exp.run_backtest(limit=500, wings=1, fetcher=fake_dhan,
                                      slippage_bps=0, target_ltp=315,
                                      tolerance=50, hold_rule="fixed",
                                      hold_minutes=5)
        self.assertEqual(report["mode"], "HISTORICAL_DHAN_OPTION_OHLC_NEXT_OPEN_PROXY")
        self.assertEqual(report["selected_rule_id"], "fixed_5")
        self.assertEqual(report["data_evidence"]["fresh_requests"], 6)
        self.assertEqual(report["selected"]["trade_count"], 1)
        self.assertEqual(report["research_readiness"]["observed_sessions"], 1)
        self.assertFalse(report["research_readiness"]["training_performed"])
        self.assertGreater(report["research_readiness"]["directional_signal_bars"], 0)
        self.assertEqual(report["selected"]["trades"][0]["strike"], 62000)
        self.assertEqual(report["selected"]["trades"][0]["option_side"], "CE")
        self.assertEqual(report["orders_placed"], 0)
        self.assertEqual(report["assumptions"]["lot_size_basis"],
                         "USER_INPUT_NOT_VERIFIED_FOR_EXPIRED_CONTRACTS")

    def test_api_requires_explicit_readonly_and_validates_bounds(self):
        client = TestClient(app, base_url="http://127.0.0.1:8765")
        response = client.post("/api/trading-cockpit/options/backtest",
                               json={"confirm_readonly": False})
        self.assertEqual(response.status_code, 400)
        invalid = client.post("/api/trading-cockpit/options/backtest",
                              json={"confirm_readonly": True, "wings": 50})
        self.assertEqual(invalid.status_code, 422)
        unsupported_wings = client.post("/api/trading-cockpit/options/backtest",
                                        json={"confirm_readonly": True,
                                              "expiry_code": 1, "wings": 5})
        self.assertEqual(unsupported_wings.status_code, 400)
        self.assertIn("current/near expiry",
                      unsupported_wings.json()["detail"])
        with patch("workstation_api.app._spawn",
                   return_value={"job_id": "test_local_id", "status": "queued"}) as mocked:
            okay = client.post("/api/trading-cockpit/options/backtest",
                               json={"confirm_readonly": True, "lots": 3,
                                     "target_ltp": 300, "hold_rule": "fixed"})
        self.assertEqual(okay.status_code, 200, okay.text)
        self.assertEqual(okay.json()["job_id"], "test_local_id")
        self.assertEqual(mocked.call_args.kwargs["lots"], 3)

    def test_one_click_backtest_recovers_only_absent_index_source(self):
        missing = ValueError(
            "Download an original Dhan IDX_I one-minute Bank Nifty/Nifty index spot batch first")
        with patch.object(exp.cockpit_sources, "series", side_effect=[
                missing, {"rows": source(), "warning": "fixture", "has_more": False}]), patch.object(
                exp.cockpit_sources, "download_spot",
                return_value={"status": "complete", "rows": 70}) as original_batch, patch.object(
                exp, "_signals", return_value=events((29, "UP"))), patch.object(
                exp, "_ist_today", return_value=date(2026, 12, 2)):
            report = exp.run_backtest(
                limit=500, wings=0, fetcher=fake_dhan,
                target_ltp=315, tolerance=50, hold_rule="fixed",
                hold_minutes=5, slippage_bps=0)
        self.assertTrue(report["auto_downloaded_missing_spot"])
        self.assertEqual(original_batch.call_count, 1)
        self.assertEqual(original_batch.call_args.args[0], "INDEX:BANKNIFTY")
        self.assertEqual(report["orders_placed"], 0)
        self.assertEqual(report["selected"]["trade_count"], 1)

    def test_do_not_replace_damaged_original_index_history(self):
        with patch.object(exp.cockpit_sources, "series",
                          side_effect=ValueError("Original index spot SHA-256 mismatch")), patch.object(
                          exp.cockpit_sources, "download_spot") as download:
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                exp.run_backtest(limit=500, wings=0)
        download.assert_not_called()

    def test_current_active_contract_id_and_lot_override_rolling_assumption(self):
        master = service.DATA / "dhan" / "instrument_master.csv"
        master.parent.mkdir(parents=True, exist_ok=True)
        master.write_text(
            "SECURITY_ID,EXCH_ID,SEGMENT,INSTRUMENT,TRADING_SYMBOL,LOT_SIZE,SM_EXPIRY_DATE,STRIKE_PRICE,OPTION_TYPE,UNDERLYING_SYMBOL\n"
            "41001,NSE,D,OPTIDX,BANKNIFTY-TEST-CE,20,2026-11-25,62000,CE,BANKNIFTY\n"
            "41002,NSE,D,OPTIDX,BANKNIFTY-TEST-PE,20,2026-11-25,62000,PE,BANKNIFTY\n",
            encoding="utf-8")
        def active(body):
            self.assertEqual(body["exchangeSegment"], "NSE_FNO")
            self.assertEqual(body["instrument"], "OPTIDX")
            self.assertIn(body["securityId"], {"41001", "41002"})
            opens = [300 + .5*i for i in range(70)]
            return {"timestamp": [int((START + timedelta(minutes=i)).timestamp())
                                  for i in range(70)],
                    "open": opens, "high": [x+1 for x in opens],
                    "low": [x-1 for x in opens], "close": opens,
                    "volume": [50]*70}
        def expired_not_requested(body):
            self.fail("Active master-backed options must not require expired rolling history")
        with patch.object(exp.cockpit_sources, "series",
                          return_value={"rows": source(), "warning": "fixture",
                                        "has_more": False}), patch.object(
                          exp, "_signals", return_value=events((29,"UP"))), patch.object(
                          exp, "_ist_today", return_value=date(2026, 11, 19)):
            result = exp.run_backtest(limit=500, wings=0,
                                      fetcher=expired_not_requested,
                                      active_fetcher=active, slippage_bps=0,
                                      target_ltp=315, tolerance=50,
                                      hold_rule="fixed", hold_minutes=5)
        self.assertIn("/charts/intraday", result["data_evidence"]["source"])
        self.assertEqual(result["selected"]["trade_count"], 1)
        trade = result["selected"]["trades"][0]
        self.assertTrue(trade["contract_identity_verified"])
        self.assertEqual(trade["source_identity"], "NSE_FNO:41001")
        self.assertEqual(trade["contract_expiry_date"], "2026-11-25")
        self.assertEqual(trade["lot_size_basis"], "ORIGINAL_CURRENT_DHAN_MASTER")
        self.assertEqual(trade["units"], 60)

    def test_dhan_request_spec_uses_near_monthly_25_security_id(self):
        body = exp._request_body(date(2026, 11, 18),
                                 date(2026, 11, 19), "MONTH", 0,
                                 "ATM+2", "PUT")
        self.assertEqual(body["exchangeSegment"], "NSE_FNO")
        self.assertEqual(body["securityId"], 25)
        self.assertEqual(body["instrument"], "OPTIDX")
        self.assertEqual(body["expiryCode"], 1)
        self.assertEqual(body["drvOptionType"], "PUT")
        self.assertIn("strike", body["requiredData"])
        with self.assertRaises(ValueError):
            exp._request_body(date(2026, 11, 1),
                              date(2026, 12, 2), "MONTH", 0, "ATM", "CALL")

    def test_rolling_options_uses_endpoint_specific_expiry_code_one_two_three(self):
        for choice, vendor in ((0, 1), (1, 2), (2, 3)):
            request = exp._request_body(
                date(2026, 11, 12), date(2026, 11, 13),
                "MONTH", choice, "ATM", "CALL")
            self.assertEqual(request["expiryCode"], vendor)
            self.assertEqual(request["securityId"], 25)
        with self.assertRaises(ValueError):
            exp._request_body(date(2026, 11, 12), date(2026, 11, 13),
                              "MONTH", 3, "ATM", "CALL")

    def test_dhan_dh905_http400_reports_contract_context_without_exposing_access_token(self):
        body = exp._request_body(date(2026, 11, 12), date(2026, 11, 13),
                                 "MONTH", 0, "ATM+1", "CALL")
        bad_response = (
            b'{"errorType":"Input_Exception","errorCode":"DH-905",'
            b'"errorMessage":"expiryCode is required"}')
        def rejected(request, timeout):
            self.assertEqual(request.get_method(), "POST")
            self.assertEqual(body["expiryCode"], 1)
            self.assertEqual(request.get_header("Client-id"),"1234567890")
            raise HTTPError(
                exp.ENDPOINT, 400, "Bad Request", {}, BytesIO(bad_response))
        with patch.dict("os.environ", {"DHAN_ACCESS_TOKEN": "SECRET-FOR-TEST-ONLY","DHAN_CLIENT_ID":"1234567890"}):
            with self.assertRaisesRegex(ValueError, "Dhan expired-options HTTP 400") as caught:
                exp._original_response(body, opener=rejected)
        public_message = str(caught.exception)
        self.assertIn("Dhan DH-905", public_message)
        self.assertIn("expiryCode is required", public_message)
        self.assertIn("expiry=1", public_message)
        self.assertIn("ATM+1", public_message)
        self.assertNotIn("SECRET-FOR-TEST-ONLY", public_message)

    def test_rolling_input_encoding_retry_remembers_success(self):
        import json
        calls=[]
        body=exp._request_body(date(2025,11,26),date(2025,12,26),"MONTH",0,"ATM","CALL")
        class Reply(BytesIO):
            pass
        def opener(request,timeout):
            wire=json.loads(request.data)
            self.assertEqual(request.get_header("Client-id"),"1234567890")
            self.assertEqual(wire.pop("dhanClientId"),"1234567890")
            calls.append(wire)
            if isinstance(wire["interval"],int):
                raise HTTPError(exp.ENDPOINT,400,"Bad Request",{},BytesIO(
                    b'{"errorCode":"DH-905","errorMessage":"Missing required fields"}'))
            return Reply(b'{"data":{"ce":{"timestamp":[]}}}')
        state={}
        with patch.dict("os.environ",{"DHAN_ACCESS_TOKEN":"TEST-TOKEN-ONLY","DHAN_CLIENT_ID":"1234567890"}):
            payload=exp._original_response(body,opener=opener,wire_state=state)
            exp._original_response(body,opener=opener,wire_state=state)
        self.assertEqual(len(calls),3)
        self.assertEqual(calls[0],{**body,"interval":1})
        self.assertEqual(calls[1],body)
        self.assertEqual(calls[1],calls[2])
        self.assertEqual(state["wire_request"],calls[1])
        self.assertEqual(payload,{"data":{"ce":{"timestamp":[]}}})

    def test_rolling_sdk_client_id_resolved_once_and_not_in_receipt_scope(self):
        import json
        from workstation_api import dhan_option_chain
        body=exp._request_body(date(2025,11,26),date(2025,11,27),"MONTH",0,"ATM","CALL")
        def opener(request,timeout):
            self.assertEqual(request.get_header("Client-id"),"1234567890")
            wire=json.loads(request.data)
            self.assertEqual(wire.pop("dhanClientId"),"1234567890")
            self.assertEqual(wire,{**body,"interval":1})
            return BytesIO(b'{"data":{"ce":{"timestamp":[]}}}')
        state={}
        with patch.dict("os.environ",{"DHAN_ACCESS_TOKEN":"TEST-TOKEN-ONLY","DHAN_CLIENT_ID":""}), \
             patch.object(dhan_option_chain,"_client_id",return_value="1234567890") as resolve:
            exp._original_response(body,opener=opener,wire_state=state)
            exp._original_response(body,opener=opener,wire_state=state)
        resolve.assert_called_once_with("TEST-TOKEN-ONLY")
        self.assertNotIn("dhanClientId",state["wire_request"])
        self.assertNotIn("dhanClientId",body)

    def test_rolling_auth_failure_is_not_retried(self):
        body=exp._request_body(date(2025,11,26),date(2025,12,26),"MONTH",0,"ATM","CALL")
        calls=[]
        def opener(request,timeout):
            calls.append(request)
            raise HTTPError(exp.ENDPOINT,401,"Unauthorized",{},BytesIO(b'{}'))
        with patch.dict("os.environ",{"DHAN_ACCESS_TOKEN":"TEST-TOKEN-ONLY","DHAN_CLIENT_ID":"1234567890"}):
            with self.assertRaisesRegex(ValueError,"access denied"):
                exp._original_response(body,opener=opener)
        self.assertEqual(len(calls),1)

    def test_partial_active_vendor_failure_preserves_other_contract_candles(self):
        """One Dhan 400 on a newly listed CE must not discard valid PE data."""
        from workstation_api import option_chain_live
        listing = {
            "available": True, "fresh": True,
            "by_id": {
                "41001": {"security_id": "41001", "expiry": "2026-11-23",
                          "strike": 62000.0, "option_type": "CE", "lot_size": 30},
                "41002": {"security_id": "41002", "expiry": "2026-11-23",
                          "strike": 62000.0, "option_type": "PE", "lot_size": 30},
            },
        }
        def source_response(body):
            if body["securityId"] == "41001":
                raise ValueError("Dhan active NSE_FNO options minute history failed (HTTP 400)")
            prices = [300. + i * .5 for i in range(70)]
            return {"timestamp": [
                        int((START + timedelta(minutes=i)).timestamp())
                        for i in range(70)],
                    "open": prices, "high": [p + 1 for p in prices],
                    "low": [p - 1 for p in prices], "close": prices,
                    "volume": [100] * 70}
        with patch.object(exp, "_ist_today",
                          return_value=date(2026, 11, 19)), patch.object(
                          option_chain_live, "_contracts", return_value=listing):
            candles, evidence = exp.load_active_option_market(
                source(), expiry_flag="MONTH", expiry_code=0,
                wings=0, fetcher=source_response)
        self.assertEqual(evidence["failed_contract_requests"], 1)
        self.assertEqual(evidence["fresh_requests"], 1)
        self.assertGreater(evidence["unique_option_minute_bars"], 0)
        self.assertIn((stamp(29), "PUT"), candles)
        self.assertNotIn((stamp(29), "CALL"), candles)

    def test_master_refreshes_when_file_is_fresh_but_banknifty_ids_empty(self):
        from unittest.mock import Mock
        from workstation_api import option_chain_live
        missing = {"available": True, "fresh": True,
                   "by_id": {}, "message": "zero BANKNIFTY contracts"}
        refreshed = {"available": True, "fresh": True, "by_id": {
            "41001": {"security_id": "41001", "expiry": "2026-11-23",
                      "strike": 62000., "option_type": "CE", "lot_size": 30},
        }}
        hits = Mock(return_value={"path": "original Dhan CSV"})
        def source_response(body):
            prices = [300.] * 70
            return {"timestamp": [
                        int((START + timedelta(minutes=i)).timestamp())
                        for i in range(70)],
                    "open": prices, "high": [301.] * 70,
                    "low": [299.] * 70, "close": prices,
                    "volume": [20] * 70}
        with patch.object(exp, "_ist_today",
                          return_value=date(2026, 11, 19)), patch.object(
                          option_chain_live, "_contracts",
                          side_effect=[missing, refreshed]):
            candles, evidence = exp.load_active_option_market(
                source(), expiry_flag="MONTH", expiry_code=0, wings=0,
                fetcher=source_response, master_refresher=hits)
        hits.assert_called_once()
        self.assertGreater(evidence["unique_option_minute_bars"], 0)
        self.assertIn((stamp(29), "CALL"), candles)

    def test_compact_master_uses_dhan_custom_symbol_when_trading_symbol_blank(self):
        from workstation_api import option_chain_live
        path = service.DATA / "dhan" / "instrument_master.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "SEM_EXM_EXCH_ID,SEM_SEGMENT,SEM_SMST_SECURITY_ID,SEM_INSTRUMENT_NAME,"
            "SEM_TRADING_SYMBOL,SEM_CUSTOM_SYMBOL,SM_SYMBOL_NAME,SEM_LOT_UNITS,"
            "SEM_EXPIRY_DATE,SEM_STRIKE_PRICE,SEM_OPTION_TYPE\n"
            "NSE,D,41001,OPTIDX,,BANKNIFTY 23 NOV 62000 CALL,NIFTY BANK,30,"
            "2026-11-23,62000,CE\n"
            "NSE,D,41002,OPTIDX,,BANKNIFTY 23 NOV 62000 PUT,NIFTY BANK,30,"
            "2026-11-23,62000,PE\n",
            encoding="utf-8")
        with patch.object(option_chain_live, "_clock",
                          return_value=datetime(2026, 11, 19, 4, 0,
                                                tzinfo=timezone.utc)):
            data = option_chain_live._contracts()
        self.assertTrue(data["available"], data["message"])
        self.assertEqual(data["matched_banknifty_option_contracts"], 2)
        self.assertEqual(data["by_id"]["41001"]["option_type"], "CE")
        self.assertEqual(data["by_id"]["41002"]["option_type"], "PE")

    def test_active_master_with_no_banknifty_options_returns_actionable_gap(self):
        from workstation_api import option_chain_live
        path = service.DATA / "dhan" / "instrument_master.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "SECURITY_ID,EXCH_ID,SEGMENT,INSTRUMENT,TRADING_SYMBOL,LOT_SIZE,"
            "SM_EXPIRY_DATE,STRIKE_PRICE,OPTION_TYPE\n"
            "12345,NSE,D,OPTIDX,NIFTY-OTHER-CE,65,2026-11-23,26500,CE\n",
            encoding="utf-8")
        with patch.object(option_chain_live, "_clock",
                          return_value=datetime(2026, 11, 19, 4, 0,
                                                tzinfo=timezone.utc)):
            data = option_chain_live._contracts()
        self.assertFalse(data["available"])
        self.assertIn("ZERO matching", data["message"])

    def test_nominal_expiry_guards_current_november_and_after_october_expiry(self):
        """November 23 monthly contract cannot be treated as expired on Nov 19."""
        as_of = date(2026, 11, 19)
        self.assertFalse(exp._expired_eligible(
            date(2026, 11, 6), expiry_flag="MONTH", expiry_code=0, today=as_of))
        self.assertFalse(exp._expired_eligible(
            date(2026, 11, 18), expiry_flag="MONTH", expiry_code=0, today=as_of))
        # After the October monthly expiry, near rolled to November,
        # which has ALSO not expired on November 19.
        self.assertFalse(exp._expired_eligible(
            date(2026, 10, 29), expiry_flag="MONTH", expiry_code=0, today=as_of))
        self.assertTrue(exp._expired_eligible(
            date(2026, 10, 22), expiry_flag="MONTH", expiry_code=0, today=as_of))
        # Holiday-shifted Nov 23 expiry is conservatively covered by the
        # nominal last Tuesday Nov 24: use rolling only after that date.
        self.assertFalse(exp._expired_eligible(
            date(2026, 11, 18), expiry_flag="MONTH",
            expiry_code=0, today=date(2026, 11, 24)))
        self.assertTrue(exp._expired_eligible(
            date(2026, 11, 18), expiry_flag="MONTH",
            expiry_code=0, today=date(2026, 11, 25)))
        self.assertFalse(exp._expired_eligible(
            date(2026, 11, 18), expiry_flag="MONTH", expiry_code=1, today=as_of))
        # The third listed expiry may be a quarterly, not the calendar
        # month after next; do not misroute it to expired near history.
        self.assertFalse(exp._expired_eligible(
            date(2026, 12, 5), expiry_flag="MONTH",
            expiry_code=2, today=date(2027, 4, 10)))
        self.assertTrue(exp._expired_eligible(
            date(2025, 3, 1), expiry_flag="MONTH",
            expiry_code=2, today=date(2026, 11, 19)))

    def test_missing_live_current_option_never_falls_back_to_expired_request(self):
        """Exact regression of user's Nov 6-19 Dhan DH-905 failure."""
        def forbidden(body):
            self.fail("An unexpired BANKNIFTY monthly option reached /charts/rollingoption")
        with patch.object(exp, "_ist_today", return_value=date(2026, 11, 19)), patch.object(
                exp.cockpit_sources, "series",
                return_value={"rows": source(), "warning": "fixture",
                              "has_more": False}), patch.object(
                exp, "load_active_option_market",
                return_value=({}, {"reason": "No matching current Dhan security IDs"})), patch.object(
                exp, "_signals", return_value=events((29, "UP"))):
            with self.assertRaisesRegex(ValueError, "has NOT expired") as caught:
                exp.run_backtest(limit=500, wings=3, fetcher=forbidden)
        self.assertIn("current-contract", str(caught.exception))
        self.assertIn("No matching current Dhan security IDs",
                      str(caught.exception))

    def test_partial_active_current_quotes_do_not_trigger_expired_fallback(self):
        """An incomplete live quote path is unscored, not replaced by expiry data."""
        now = date(2026, 11, 19)
        partial = {
            (stamp(29), "CALL"): {
                62000.: {**quote(29), "security_id": "41001",
                          "expiry_date": "2026-11-23", "lot_size_verified": 30}},
            (stamp(29), "PUT"): {
                62000.: {**quote(29, side="PUT"), "security_id": "41002",
                          "expiry_date": "2026-11-23", "lot_size_verified": 30}},
        }
        def forbidden(_):
            self.fail("Partial active source must not invoke expired rolling endpoint")
        with patch.object(exp, "_ist_today", return_value=now), patch.object(
                exp.cockpit_sources, "series",
                return_value={"rows": source(), "warning": "fixture",
                              "has_more": False}), patch.object(
                exp, "load_active_option_market",
                return_value=(partial, {"source": "Dhan active NSE_FNO",
                                        "requests": 2, "fresh_requests": 2})), patch.object(
                exp, "_signals", return_value=events((29, "UP"))):
            report = exp.run_backtest(
                limit=500, wings=3, fetcher=forbidden,
                target_ltp=300, tolerance=50,
                hold_rule="fixed", hold_minutes=5)
        self.assertEqual(report["selected"]["trade_count"], 0)
        self.assertGreater(report["selected"]["unscored"]["missing_option_entry"], 0)
        self.assertEqual(report["data_evidence"]["routing"]["expired_vendor_requests"], 0)
        self.assertEqual(report["orders_placed"], 0)

    def test_offline_banknifty_weekly_is_not_sent_to_recent_expired_api(self):
        with patch.object(exp, "_ist_today",
                          return_value=date(2026, 11, 19)), patch.object(
                exp.cockpit_sources, "series",
                return_value={"rows": source(), "warning": "fixture",
                              "has_more": False}):
            with self.assertRaisesRegex(ValueError, "weekly options"):
                exp.run_backtest(limit=500, expiry_flag="WEEK", wings=0,
                                 fetcher=lambda _: self.fail("unexpected rolling"))

    def test_no_history_without_confirmed_dhan_access_or_cached_originals(self):
        with patch.dict("os.environ", {"DHAN_ACCESS_TOKEN": ""}):
            with self.assertRaisesRegex(ValueError, "Connect your Dhan"):
                exp._original_response(exp._request_body(
                    date(2026, 11, 18), date(2026, 11, 19),
                    "MONTH", 0, "ATM", "CALL"))


if __name__ == "__main__":
    unittest.main()
