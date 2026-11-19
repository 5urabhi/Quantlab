"""No-network regressions for BANKNIFTY spot signals -> historical CE/PE P&L.

All option candles below are synthetic TEST FIXTURES. Production never uses
them, only original Dhan responses and SHA-verified locally saved receipts.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
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
    assert body["expiryCode"] == 0
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
                          exp, "_signals", return_value=events((29,"UP"))):
            report = exp.run_backtest(limit=500, wings=1, fetcher=fake_dhan,
                                      slippage_bps=0, target_ltp=315,
                                      tolerance=50, hold_rule="fixed",
                                      hold_minutes=5)
        self.assertEqual(report["mode"], "HISTORICAL_DHAN_OPTION_OHLC_NEXT_OPEN_PROXY")
        self.assertEqual(report["selected_rule_id"], "fixed_5")
        self.assertEqual(report["data_evidence"]["fresh_requests"], 6)
        self.assertEqual(report["selected"]["trade_count"], 1)
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
        with patch("workstation_api.app._spawn",
                   return_value={"job_id": "test_local_id", "status": "queued"}) as mocked:
            okay = client.post("/api/trading-cockpit/options/backtest",
                               json={"confirm_readonly": True, "lots": 3,
                                     "target_ltp": 300, "hold_rule": "fixed"})
        self.assertEqual(okay.status_code, 200, okay.text)
        self.assertEqual(okay.json()["job_id"], "test_local_id")
        self.assertEqual(mocked.call_args.kwargs["lots"], 3)

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
                          exp, "_signals", return_value=events((29,"UP"))):
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
        self.assertEqual(body["expiryCode"], 0)
        self.assertEqual(body["drvOptionType"], "PUT")
        self.assertIn("strike", body["requiredData"])
        with self.assertRaises(ValueError):
            exp._request_body(date(2026, 11, 1),
                              date(2026, 12, 2), "MONTH", 0, "ATM", "CALL")

    def test_no_history_without_confirmed_dhan_access_or_cached_originals(self):
        with patch.dict("os.environ", {"DHAN_ACCESS_TOKEN": ""}):
            with self.assertRaisesRegex(ValueError, "Connect your Dhan"):
                exp._original_response(exp._request_body(
                    date(2026, 11, 18), date(2026, 11, 19),
                    "MONTH", 0, "ATM", "CALL"))


if __name__ == "__main__":
    unittest.main()
