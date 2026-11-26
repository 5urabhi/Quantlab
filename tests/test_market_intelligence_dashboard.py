from datetime import datetime, timezone
import unittest
from workstation_api import banknifty_constituents as bc, manual_options_workflow as mw


class DashboardTests(unittest.TestCase):
    def test_opening_sample_return_not_zero_filled(self):
        start={"identity":"NSE_EQ:1","price":100,"received_utc":"2026-11-25T03:45:10+00:00"}
        current={"identity":"NSE_EQ:1","price":101}
        self.assertAlmostEqual(bc.session_return(current,start)["session_return_pct"],1)
        self.assertIsNone(bc.session_return(current,None)["session_return_pct"])
        self.assertIsNone(bc.session_return({**current,"identity":"NSE_EQ:2"},start)["session_return_pct"])

    def test_combined_scenario_requires_complete_fresh_legs(self):
        now=datetime(2026,11,25,4,0,tzinfo=timezone.utc)
        args=(now,5,0,6.5,0,10)
        self.assertEqual(mw.portfolio_scenario([],2,True,*args)["state"],"unavailable")
        p={"expiry":"2026-12-29","entry_price":150,"quantity":30,"broker_profile":"zerodha"}
        snapshot={"received_utc":now.isoformat(),"underlying_spot":63500}
        ce={"strike":64500,"option_type":"CE","bid":149,"ask":151}
        pe={"strike":62500,"option_type":"PE","bid":149,"ask":151}
        legs=[(p,snapshot,ce,.20),(p,snapshot,pe,.20)]
        result=mw.portfolio_scenario(legs,2,True,*args)
        self.assertEqual(result["state"],"ready")
        self.assertEqual(len(result["points"]),17)
        self.assertEqual(result["premium_at_risk"],9000)
        self.assertEqual(mw.portfolio_scenario(legs,2,False,*args)["state"],"unavailable")
        self.assertEqual(mw.portfolio_scenario(legs,2,True,now,5,-50,6.5,0,10)["state"],"unavailable")


if __name__ == "__main__":
    unittest.main()
