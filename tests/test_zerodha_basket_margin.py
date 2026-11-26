import json
from datetime import datetime,timezone
from unittest import TestCase
from unittest.mock import patch
from workstation_api import zerodha_basket_margin as margin, zerodha_fallback as kite

NOW=datetime(2026,11,26,5,tzinfo=timezone.utc)
MASTER=b"""exchange,segment,name,tradingsymbol,exchange_token,expiry,strike,instrument_type,lot_size
NFO,NFO-OPT,BANKNIFTY,BANKNIFTY26DEC63000CE,123,2026-12-30,63000,CE,30
NFO,NFO-OPT,BANKNIFTY,BANKNIFTY26DEC63100CE,124,2026-12-30,63100,CE,30
"""
CANDIDATE={"units":90,"lots":3,"lot_size":30,"strategy":"bull_call_debit","modeled_risk_inr":1500,
           "legs":[{"identity":"NSE_FNO:123","expiry":"2026-12-30","strike":63000,"side":"CE","action":"BUY"},
                   {"identity":"NSE_FNO:124","expiry":"2026-12-30","strike":63100,"side":"CE","action":"SELL"}]}
ROW={"selected":CANDIDATE,"decision_utc":NOW.isoformat(),"config":{"capital":17000}}


class BasketMarginTests(TestCase):
    def test_only_current_exact_terms_and_broker_estimate(self):
        def request(path,**kw):
            if path=="/instruments/NFO":
                return MASTER
            self.assertEqual(path,"/margins/basket?consider_positions=false")
            self.assertEqual(kw["method"],"POST")
            legs=kw["json_body"]
            self.assertEqual([x["transaction_type"] for x in legs],["BUY","SELL"])
            self.assertTrue(all(x["quantity"]==90 and x["product"]=="MIS" for x in legs))
            return json.dumps({"status":"success","data":{"initial":{"total":19000},"final":{"total":10000},
                "orders":[{"exchange":"NFO","tradingsymbol":x["tradingsymbol"],"total":5000,
                           "charges":{"total":20}} for x in legs]}}).encode()
        with patch.object(margin,"_decision",return_value=ROW),patch.object(margin.costs,"_guard"),patch.object(kite,"_request",side_effect=request):
            out=margin.preview(decision_id=1,confirm_readonly=True,now=NOW)
        self.assertEqual(out["initial_margin_inr"],19000)
        self.assertEqual(out["final_margin_inr"],10000)
        self.assertFalse(out["within_paper_capital"])
        self.assertFalse(out["consider_positions"])
        self.assertFalse(out["orders_enabled"])
        self.assertEqual(len(out["margin_response_sha256"]),64)

    def test_no_consent_and_missing_or_ambiguous_terms(self):
        with patch.object(kite,"_request") as request:
            with self.assertRaises(ValueError):
                margin.preview(decision_id=1,now=NOW)
            request.assert_not_called()
        keys=margin._terms(CANDIDATE,NOW)
        with self.assertRaises(ValueError):
            margin._map_master(MASTER.splitlines()[0]+b"\n",keys)
        with self.assertRaises(ValueError):
            margin._map_master(MASTER+MASTER.splitlines()[1]+b"\n",keys)
        with self.assertRaises(ValueError):
            margin._terms(CANDIDATE,datetime(2027,1,1,tzinfo=timezone.utc))

    def test_provider_still_denies_orders_and_unapproved_margin_paths(self):
        for path in ("/orders/regular","/margins/basket?consider_positions=true","/margins/orders"):
            with self.assertRaises(ValueError):
                kite._request(path,method="POST",json_body=[{}])
        with self.assertRaises(ValueError):
            kite._request(kite.BASKET_MARGIN_PATH,method="POST",json_body=[{},{},{}])
