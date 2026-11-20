"""Offline evidence tests for BANKNIFTY Python Research Lab.

All candles in this test are SYNTHETIC fixtures; production uses SHA-checked
Dhan spot and actually recorded tick aggregations. No order endpoints called.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from zoneinfo import ZoneInfo
import os

from fastapi.testclient import TestClient
from workstation_api import strategy_lab as lab
from workstation_api import python_strategy_sandbox as sandbox
from workstation_api.app import app

IST = ZoneInfo("Asia/Kolkata")


def rows_for_day(day: date, kind: int = 1, stop: int = 375) -> list[dict]:
    beginning = datetime.combine(day, time(9, 15), tzinfo=IST)
    result = []
    for i in range(stop):
        # A falling segment, rising segment, then falling again.
        base = 63000 + (i * 1.1 if i < 70 else
                        77 - (i - 70) * 1.7 if i < 140 else
                        -42 + (i - 140) * 1.2 if i < 215 else
                        48 - (i - 215) * 1.25)
        price = base + kind * 15
        stamp = (beginning + timedelta(minutes=i)).isoformat()
        result.append({"timestamp_utc": stamp, "session_ist": day.isoformat(),
                       "open": price, "high": price + 2, "low": price - 2,
                       "close": price, "volume": 0})
    return result


class BankNiftyStrategyLabTests(TestCase):
    def test_all_fast_slow_combinations_in_requested_grid(self):
        self.assertEqual(lab._periods([3, 5, 9], [7, 21]), [
            (3, 7), (3, 21), (5, 7), (5, 21), (9, 21)])
        with self.assertRaisesRegex(ValueError, "256"):
            lab._periods(list(range(2, 34)), list(range(40, 72)))
        with self.assertRaises(ValueError):
            lab._periods([22], [9])

    def test_all_supported_periods_have_exact_11026_unique_pairs(self):
        from workstation_api import ema_grid_scorer
        pairs = ema_grid_scorer.all_supported_pairs()
        self.assertEqual(len(pairs), 11026)
        self.assertEqual(pairs[0], (2, 3))
        self.assertEqual(pairs[-1], (149, 150))
        self.assertEqual(len(set(pairs)), len(pairs))
        self.assertTrue(all(2 <= a < b <= 150 for a, b in pairs))

    def test_fast_ema_scoring_is_exactly_equal_to_original_bar_simulator(self):
        from workstation_api import ema_grid_scorer
        rows = (
            rows_for_day(date(2026, 11, 17)) +
            rows_for_day(date(2026, 11, 18)) +
            rows_for_day(date(2026, 11, 19))
        )
        # A missing original bar should not create an invented cross or fill.
        rows = rows[:400] + rows[401:]
        pairs = [(2, 3), (3, 7), (5, 13), (9, 21),
                 (21, 34), (34, 55), (89, 149)]
        grid = ema_grid_scorer.FastSweep(
            rows, {p for pair in pairs for p in pair},
            starting_capital=50000, cost_bps=7)
        for fast, slow in pairs:
            with self.subTest(fast=fast, slow=slow):
                original, _ = lab.crossover_events(rows, fast, slow)
                legacy = lab.backtest_index(
                    rows, original, starting_capital=50000,
                    cost_bps=7, include_chart=False)["metrics"]
                compact = grid.score(fast, slow)
                self.assertEqual(compact, legacy)
                events, count = grid.signals(fast, slow)
                self.assertEqual(count, sum(x != "HOLD" for x in original))
                self.assertEqual([("UP" if x[1]==1 else "DOWN") for x in events],
                                 [x for x in original if x != "HOLD"])

    def test_exhaustive_sweep_returns_real_top_five_not_just_256_samples(self):
        from workstation_api import ema_grid_scorer
        rows = (
            rows_for_day(date(2026, 11, 18)) +
            rows_for_day(date(2026, 11, 19))
        )
        evidence = {"basis": "original_Dhan_IDX_I_unadjusted_spot_index",
                    "identity": "INDEX:BANKNIFTY",
                    "original_sha256": "a"*64,
                    "rows": len(rows), "sessions": 2}
        with TemporaryDirectory() as tmp, \
             patch.object(lab, "load_index", return_value=(rows, evidence)) as source, \
             patch.object(lab, "_run_root", return_value=Path(tmp)):
            result = lab.run_sweep(
                limit=1500, fast_periods=[9], slow_periods=[21],
                mode="all", starting_capital=50000, cost_bps=5)
        source.assert_called_once_with(1500, "historical")
        self.assertEqual(result["search_mode"], "all")
        self.assertEqual(result["combinations_tested"], 11026)
        self.assertTrue(result["search_space"]["complete_supported_grid"])
        self.assertEqual(len(result["top_five"]), 5)
        self.assertEqual(len(result["ranked"]), 100)
        self.assertEqual(result["ranked_returned"], 100)
        self.assertTrue(all(2 <= x["fast"] < x["slow"] <= 150
                            for x in result["top_five"]))
        self.assertEqual(result["orders_placed"], 0)
        self.assertFalse(result["validation"]["holdout_available"])

    def test_sweep_fails_closed_for_unknown_search_modes(self):
        with self.assertRaisesRegex(ValueError, "custom EMA lists or all"):
            lab.run_sweep_process(
                fast_periods=[9], slow_periods=[21], mode="unknown")
        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            bad = client.post("/api/trading-cockpit/research-lab/ema-sweep",
                json={"mode":"unsafe","confirm_readonly":True})
            self.assertEqual(bad.status_code, 422)
            with patch("workstation_api.app._spawn",return_value={
                 "job_id":"all_grid_fixture","status":"queued"}) as queued:
                ok = client.post("/api/trading-cockpit/research-lab/ema-sweep",
                    json={"mode":"all","confirm_readonly":True})
                self.assertEqual(ok.status_code, 200)
                self.assertEqual(queued.call_args.kwargs["mode"],"all")
                self.assertEqual(queued.call_args.args[0],
                                 "banknifty_index_ema_parameter_sweep")

    def test_crossover_only_on_real_index_one_minute_observed_close(self):
        rows = rows_for_day(date(2026, 11, 19))
        signals, indicators = lab.crossover_events(rows, 9, 21)
        flips = [s for s in signals if s != "HOLD"]
        self.assertGreaterEqual(len(flips), 2)
        self.assertTrue(all(signals[i] == "HOLD" for i in range(21)))
        self.assertEqual(len(indicators["fast"]), len(rows))
        self.assertTrue(any(s == "UP" for s in flips))
        self.assertTrue(any(s == "DOWN" for s in flips))
        for count in (22, 35, 120, 200, 375):
            self.assertEqual(lab.crossover_events(rows[:count], 9, 21)[0],
                             signals[:count])

    def test_gap_resets_ema_and_never_fills_synthetic_missing_minute(self):
        rows = rows_for_day(date(2026, 11, 19))
        broken = rows[:50] + rows[51:120]
        events, indicator = lab.crossover_events(broken, 9, 21)
        self.assertEqual(indicator["fast"][50], None)
        self.assertTrue(all(v == "HOLD" for v in events[50:71]))

    def test_hold_while_no_cross_and_exit_only_observed_session_close(self):
        rows = rows_for_day(date(2026, 11, 19))
        signals = ["HOLD"] * len(rows)
        signals[30] = "UP"
        result = lab.backtest_index(rows, signals, cost_bps=0)
        self.assertEqual(result["metrics"]["trade_count"], 1)
        trade = result["trades"][0]
        self.assertEqual(trade["exit_reason"], "observed_session_end")
        self.assertEqual(trade["entry_utc"], rows[31]["timestamp_utc"])
        self.assertEqual(trade["exit_utc"], rows[-1]["timestamp_utc"])
        self.assertGreater(trade["hold_minutes"], 300)
        self.assertEqual(result["orders_placed"], 0)

    def test_opposite_cross_reverses_on_next_open_never_previous_close(self):
        rows = rows_for_day(date(2026, 11, 19))
        signals = ["HOLD"] * len(rows)
        signals[30] = "UP"
        signals[81] = "DOWN"
        result = lab.backtest_index(rows, signals, cost_bps=0)
        first, second = result["trades"]
        self.assertEqual(first["exit_reason"], "opposite_confirmed_cross")
        self.assertEqual(first["exit_utc"], rows[82]["timestamp_utc"])
        self.assertEqual(second["entry_utc"], rows[82]["timestamp_utc"])
        self.assertEqual(first["direction"], "UP")
        self.assertEqual(second["direction"], "DOWN")
        self.assertGreater(first["hold_minutes"], 6)

    def test_truncated_incomplete_live_session_is_unscored_not_fake_eod(self):
        rows = rows_for_day(date(2026, 11, 19), stop=120)
        signals = ["HOLD"] * len(rows)
        signals[35] = "UP"
        result = lab.backtest_index(rows, signals)
        self.assertEqual(result["metrics"]["trade_count"], 0)
        self.assertEqual(result["metrics"]["unscored"][
            "open_position_at_truncated_history_end"], 1)

    def test_sweep_preserves_readonly_source_and_no_holdout_when_too_few_sessions(self):
        rows = (rows_for_day(date(2026, 11, 18)) +
                rows_for_day(date(2026, 11, 19)))
        evidence = {"basis": "original_Dhan_IDX_I_unadjusted_spot_index",
                    "identity": "INDEX:BANKNIFTY",
                    "original_sha256": "a" * 64,
                    "rows": 750, "sessions": 2}
        with TemporaryDirectory() as tmp, \
             patch.object(lab, "load_index", return_value=(rows, evidence)) as source, \
             patch.object(lab, "_run_root", return_value=Path(tmp)):
            result = lab.run_sweep(limit=1500, fast_periods=[3, 5, 9],
                                   slow_periods=[13, 21],cost_bps=5)
            source.assert_called_once_with(1500, "historical")
            self.assertEqual(result["combinations_tested"], 6)
            self.assertEqual(len(result["ranked"]), 6)
            self.assertFalse(result["validation"]["holdout_available"])
            self.assertTrue(Path(tmp, result["run_id"] + ".json").is_file())
            restored = lab.read_run(result["run_id"])
            self.assertEqual(restored["best_pair"], result["best_pair"])
            self.assertEqual(result["orders_placed"], 0)

    def test_original_live_snapshot_is_read_only_and_has_no_vendor_request(self):
        source_rows = rows_for_day(date(2026, 11, 19), stop=100)
        with patch.object(lab.live_market,"minute_series",return_value={
            "basis":"Dhan_live_ticker_observed_LTP_minute_aggregate",
            "source_warning":"Incomplete observed tick candles",
            "rows":source_rows}) as captured, \
             patch.object(lab.cockpit_sources,"series") as historical:
            rows, evidence = lab.load_index(500, "recorded_live")
        captured.assert_called_once_with("INDEX:BANKNIFTY",limit=500)
        historical.assert_not_called()
        self.assertEqual(evidence["source_mode"], "recorded_live")
        self.assertEqual(evidence["original_sha256"], None)
        self.assertEqual(len(rows), 100)
        self.assertTrue(evidence["live_recorder_touched"] is False)

    def test_built_in_sweep_launches_low_priority_process_without_token(self):
        with patch.object(lab.shutil,"which",return_value="/usr/bin/nice"), \
             patch.object(lab.subprocess,"run") as child, \
             patch.object(lab,"read_run",return_value={
                 "kind":"ema_sweep","run_id":"banknifty_"+("b"*20)}) as read:
            def complete(command, **kwargs):
                self.assertEqual(command[1:3], ["-n","10"])
                self.assertIn("workstation_api.strategy_lab_process",command)
                self.assertTrue(kwargs["close_fds"])
                self.assertTrue(kwargs["start_new_session"])
                self.assertEqual(kwargs["timeout"],120)
                self.assertEqual(kwargs["env"]["OMP_NUM_THREADS"],"1")
                self.assertNotIn("DHAN_ACCESS_TOKEN",kwargs["env"])
                self.assertNotIn("DHAN_CLIENT_ID",kwargs["env"])
                Path(command[-1]).write_text(
                    '{"run_id":"banknifty_'+("b"*20)+'"}',encoding="utf-8")
                from types import SimpleNamespace
                return SimpleNamespace(returncode=0)
            child.side_effect=complete
            result = lab.run_sweep_process(
                fast_periods=[9],slow_periods=[21],limit=500)
            self.assertEqual(result["kind"],"ema_sweep")
            child.assert_called_once()
            read.assert_called_once_with("banknifty_"+("b"*20))

    def test_missing_nice_utility_fails_before_launch(self):
        with patch.object(lab.shutil,"which",return_value=None), \
             patch.object(lab.subprocess,"run") as child:
            with self.assertRaisesRegex(ValueError,"nice utility"):
                lab.run_sweep_process(fast_periods=[9],slow_periods=[21])
            child.assert_not_called()

    def test_user_python_fails_closed_without_bubblewrap(self):
        rows = rows_for_day(date(2026, 11, 19), stop=40)
        with patch.object(sandbox.shutil, "which", return_value=None), \
             patch.object(sandbox.subprocess, "run") as subprocess:
            with self.assertRaisesRegex(ValueError, "unsafe in-process fallback"):
                sandbox.run_python("def signal(history): return 'HOLD'", rows)
            subprocess.assert_not_called()

    def test_sandbox_command_does_not_mount_repo_or_broker_environment(self):
        with patch.object(sandbox,"availability",return_value={"available":True}), \
             patch.object(sandbox.shutil,"which",side_effect=lambda p:
                          "/usr/bin/" + p):
            command = sandbox._command(Path("/tmp/quantlab_isolated_unit"))
        self.assertIn("--unshare-all",command)
        self.assertIn("--tmpfs",command)
        self.assertIn("--ro-bind",command)
        self.assertEqual(command[command.index("--bind")+1],
                         "/tmp/quantlab_isolated_unit")
        self.assertNotIn(str(lab.service.ROOT),command)
        self.assertNotIn("DHAN_ACCESS_TOKEN", " ".join(command))
        self.assertEqual(command[-4:],
                         ["/usr/bin/python3","-I","-S","/work/runner.py"])

    def test_local_api_preserves_readonly_and_blocks_unisolated_code(self):
        with TestClient(app,base_url="http://127.0.0.1:8765") as client:
            with patch.object(sandbox,"availability",return_value={
                "available":False,"engine":"bubblewrap",
                "requires":["bubblewrap"]}):
                blocked = client.post("/api/trading-cockpit/research-lab/python",
                   json={"code":"def signal(history): return 'HOLD'",
                         "confirm_readonly":True})
                self.assertEqual(blocked.status_code,409)
            response = client.post("/api/trading-cockpit/research-lab/ema-sweep",
                json={"fast_periods":[9],"slow_periods":[9],
                      "confirm_readonly":True})
            self.assertEqual(response.status_code,400)
            with patch("workstation_api.app._spawn",return_value={
                    "job_id":"synthetic_queuing","status":"queued"}) as enqueue:
                request = client.post("/api/trading-cockpit/research-lab/ema-sweep",
                     json={"fast_periods":[9],"slow_periods":[21],
                           "confirm_readonly":True})
                self.assertEqual(request.status_code,200,request.text)
                enqueue.assert_called_once()
                self.assertEqual(enqueue.call_args.args[0],
                                 "banknifty_index_ema_parameter_sweep")
                self.assertTrue(enqueue.call_args.kwargs["fast_periods"]==[9])


