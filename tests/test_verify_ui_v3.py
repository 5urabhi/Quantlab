import unittest
from unittest.mock import patch
from scripts import verify_ui_v3 as verify


class V3AcceptanceTests(unittest.TestCase):
    def test_missing_namespace_is_blocked_not_pass(self):
        with patch.object(verify.sandbox,"availability",return_value={"available":False}):
            self.assertEqual(verify.verify_sandbox()[0]["state"],"blocked")
            with patch("builtins.print"):
                self.assertEqual(verify.main(["--offline","--require-sandbox"]),2)

    def test_local_status_preserves_source_codes_and_closed_market(self):
        data={
            "/api/health":{"read_only_market_data":True,"broker_orders_enabled":False,"dhan_token_configured":True},
            "/api/trading-cockpit/acceptance":{"external_api_requests":0,"orders_placed":0,"checks":[
                {"code":"banknifty_history","status":"pass","detail":"history"},
                {"code":"contract_master","status":"pass","detail":"master"},
                {"code":"live_depth","status":"waiting","detail":"market closed"},
                {"code":"stored_depth","status":"partial","detail":"missing side"}]},
            "/api/trading-cockpit/option-feed/status":{"market_regular_hours":False,"observed_contracts":200,"dropped_events":3},
            "/api/trading-cockpit/auto-index/status":{"quotes":{},"state":"disconnected","unsupported_packets":12},
        }
        with patch.object(verify,"read_local",side_effect=lambda path:data[path]) as request:
            checks={r["check"]:r for r in verify.verify_local_market()}
        self.assertEqual(request.call_count,4)
        self.assertEqual(checks["banknifty_history"]["state"],"pass")
        self.assertEqual(checks["live_depth"]["state"],"waiting")
        self.assertEqual(checks["stored_depth"]["state"],"blocked")
        self.assertEqual(checks["option_stream"]["state"],"waiting")
        self.assertEqual(checks["shared_index"]["unsupported"],12)

    def test_missing_source_receipts_are_explicit(self):
        data={
            "/api/health":{"read_only_market_data":True,"broker_orders_enabled":False},
            "/api/trading-cockpit/acceptance":{"external_api_requests":0,"orders_placed":0,"checks":[]},
            "/api/trading-cockpit/option-feed/status":{"market_regular_hours":True},
            "/api/trading-cockpit/auto-index/status":{"quotes":{}},
        }
        with patch.object(verify,"read_local",side_effect=lambda path:data[path]):
            checks={r["check"]:r for r in verify.verify_local_market()}
        self.assertEqual(checks["stored_depth"]["state"],"blocked")
        self.assertEqual(checks["shared_index"]["state"],"blocked")
