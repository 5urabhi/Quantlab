"""Independent math and original-source protocol regressions.

All data here are fabricated offline fixtures, not market observations or fills.
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
from index_research import math_models, derivatives
from workstation_api import advanced_options as ao, service, live_market, full_option_feed
from workstation_api.app import app

NOW = datetime(2026, 11, 24, 5, 0, tzinfo=timezone.utc)
EXPIRY = "2026-11-24"
SPOT = 63000.
RATE = .065


def contract(identity, side, strike, sigma=.18, **changes):
    years=(datetime(2026,11,24,15,30,tzinfo=ao.IST)-NOW).total_seconds()/ao.YEAR_SECONDS
    price=ao.bsm(SPOT,strike,years,RATE,sigma,side,0.)["price"]
    bid=max(.05,round((price-.05)*20)/20)
    ask=round(bid+.10,2)
    row={"identity":identity,"symbol":"FIXTURE"+identity.split(":")[-1],
         "strike":float(strike),"option_type":side,"expiry":EXPIRY,
         "lot_size":30,"contract_master_verified":True,"quote_valid":True,
         "bid":bid,"ask":ask,"ltp":(bid+ask)/2,
         "top_bid_quantity":600,"top_ask_quantity":600,
         "oi":3000,"volume":6000,"iv":sigma*100,
         "delta":None,"gamma":None,"vega":None,"theta":None}
    row.update(changes)
    return row


def fixture():
    return {"underlying":"BANKNIFTY","underlying_spot":SPOT,
            "expiry":EXPIRY,"received_utc":NOW.isoformat(),
            "source":"synthetic_offline_test","source_clock":"local_received_utc_not_exchange_quote_time",
            "not_live_stream":True,"read_only":True,
            "contracts":[contract("NSE_FNO:1001","CE",63000),
                         contract("NSE_FNO:1002","PE",63000),
                         contract("NSE_FNO:1003","CE",63100),
                         contract("NSE_FNO:1004","PE",63100),
                         contract("NSE_FNO:1005","CE",64000,bid=1.50,ask=2.70)]}


class AdvancedOptionsTests(TestCase):
    def setUp(self):
        temp=TemporaryDirectory(prefix="quantlab_advanced_options_")
        self.addCleanup(temp.cleanup)
        for obj,key,value in ((service,"DATA",Path(temp.name)/"data"),
                              (live_market,"DB_INITIALIZED",False),
                              (full_option_feed,"STORAGE_INITIALIZED",False)):
            p=patch.object(obj,key,value);p.start();self.addCleanup(p.stop)
        ao._daily_history.cache_clear()
        self.addCleanup(ao._daily_history.cache_clear)
        full_option_feed._init_storage()
        with live_market._database() as db:
            db.execute("""CREATE TABLE option_chain_observations(
                underlying TEXT NOT NULL, expiry TEXT NOT NULL,
                captured_utc TEXT NOT NULL, snapshot_sha256 TEXT NOT NULL,
                normalized_json TEXT NOT NULL,
                PRIMARY KEY(underlying,expiry,captured_utc))""")

    def save_snapshot(self, chain):
        raw=json.dumps(chain)
        with live_market._database() as db:
            db.execute("INSERT INTO option_chain_observations VALUES(?,?,?,?,?)",
                       ("BANKNIFTY",chain["expiry"],chain["received_utc"],
                        sha256(raw.encode()).hexdigest(),raw))

    def test_independent_bsm_matches_existing_model_and_iv_units(self):
        for side in ("CE","PE"):
            b=ao.bsm(100,101,.4,.065,.23,side,.012)
            old=math_models.black_scholes(100,101,.4,.065,.23,
                                           "call" if side=="CE" else "put",.012)
            for field in ("price","delta","gamma"):
                self.assertAlmostEqual(b[field],old[field],places=10)
            self.assertAlmostEqual(b["theta_day"],old["theta"]/365.25,places=10)
            self.assertAlmostEqual(b["vega_iv_point"],old["vega"]/100,places=10)
            self.assertAlmostEqual(b["rho_rate_point"],old["rho"]/100,places=10)
            sigma=ao.implied_iv(b["price"],100,101,.4,.065,side,.012)
            independent=derivatives.implied_volatility(b["price"],100,101,.4,.065,
                                              "call" if side=="CE" else "put",.012)
            self.assertAlmostEqual(sigma,independent,places=9)
        self.assertIsNone(ao.implied_iv(200,100,101,.4,.065,"CE",0.))
        self.assertIsNone(ao.implied_iv(0,100,101,.4,.065,"PE",0.))

    def test_conditional_shortlist_budget_costs_and_direction(self):
        x=ao.analyze(fixture(),now=NOW,capital=17000,max_lots=3,risk_pct=50,
                     direction="UP",move_points=100,horizon_minutes=5)
        self.assertFalse(x["orders_enabled"])
        self.assertIsNone(x["profit_probability"])
        self.assertIsNone(x["expected_profit_inr"])
        self.assertGreater(x["ranked_count"],0)
        self.assertEqual(x["confirmed_depth_count"],0)
        for r in x["rows"]:
            if r.get("rank"):
                self.assertEqual(r["option_type"],"CE")
                self.assertEqual(r["rank_quality"],"indicative_snapshot_only")
                self.assertLessEqual(r["entry_debit_inr"],8500)
                self.assertLessEqual(r["scenario_lots"],3)
                self.assertEqual(r["entry_debit_inr"],r["max_premium_loss_inr"])
                self.assertLess(r["same_quote_roundtrip_net_inr"],0)
                self.assertGreater(r["scenarios"]["favorable"]["net_pnl_inr"],0)
                self.assertLess(r["scenarios"]["adverse"]["net_pnl_inr"],0)
                self.assertGreater(r["break_even_exit_premium"],r["ask"])
                self.assertLessEqual(r["iv_bid_pct"],r["iv_mid_pct"])
                self.assertGreaterEqual(r["iv_ask_pct"],r["iv_mid_pct"])
        penny=next(r for r in x["rows"] if r["identity"]=="NSE_FNO:1005")
        self.assertIsNone(penny["score"])
        self.assertIn("Low premium or wide relative spread",penny["reasons"])

    def test_stale_unknown_and_invalid_quotes_remain_inspectable(self):
        data=fixture()
        data["contracts"][0].update({"contract_master_verified":False,"identity":None,"lot_size":None})
        data["contracts"][1].update({"bid":None,"quote_valid":False,"oi":None})
        x=ao.analyze(data,now=NOW+timedelta(seconds=61),capital=17000)
        self.assertFalse(x["recent_receipt"])
        self.assertEqual(x["ranked_count"],0)
        self.assertEqual(len(x["rows"]),5)
        self.assertIsNone(x["rows"][0]["affordable_lots"])
        self.assertIsNone(x["rows"][1]["model_greeks"])
        self.assertIsNone(x["oi"]["pcr"])
        self.assertIsNone(x["oi"]["max_pain_strike"])
        self.assertIsNone(x["volatility"]["iv_rank"])
        self.assertIsNone(x["volatility"]["realized_intraday_pct"])
        self.assertEqual(x["volatility"]["iv_prior_sessions"],0)

    def test_depth_and_recent_trades_promote_evidence_not_win_probability(self):
        data=fixture()
        r=data["contracts"][0]
        identity=r["identity"]
        stamp=NOW-timedelta(seconds=2)
        digest=sha256(("a"*64+"b"*64).encode()).hexdigest()
        book={"identity":identity,"received_utc":stamp.isoformat(),
              "timestamp_kind":"local_receive","source":"original_Dhan_full_market_depth_websocket",
              "collection_mode":"auto_banknifty_20_level","bid_packet_sha256":"a"*64,
              "ask_packet_sha256":"b"*64,
              "bid":[{"price":round(r["bid"]-.05*i,2),"quantity":600,"orders":3} for i in range(20)],
              "ask":[{"price":round(r["ask"]+.05*i,2),"quantity":600,"orders":3} for i in range(20)],
              "computed_features":{"lot_size_verified":30,"expiry":EXPIRY,"strike":r["strike"],"side":"CE"}}
        with live_market._database() as db:
            db.execute("INSERT INTO live_depth_books VALUES(?,?,?,?,?)",
                       (identity,stamp.isoformat(),"fixture",json.dumps(book),digest))
            for i in range(3):
                t=(NOW-timedelta(seconds=30-10*i)).isoformat()
                db.execute("INSERT INTO dhan_option_live_events VALUES(?,?,?,?,?,?,?,?,?,?)",
                           (identity,t,t,"quote",r["ltp"],3000+30*i,None,30,"packet"+str(i),"fixture"))
        x=ao.analyze(data,now=NOW,selected=identity,capital=17000)
        picked=next(row for row in x["rows"] if row["identity"]==identity)
        self.assertEqual(picked["depth_state"],"recent_original_book")
        self.assertEqual(picked["rank_quality"],"recent_depth_and_trades")
        self.assertEqual(picked["rank"],1)
        self.assertEqual(x["confirmed_depth_count"],1)
        self.assertEqual(picked["trade_activity"]["volume_delta"],60)
        self.assertIsNone(x["profit_probability"])
        # A later, materially different chain quote may not inherit the top tier.
        data["contracts"][0]["ask"]+=1
        data["contracts"][0]["bid"]+=1
        y=ao.analyze(data,now=NOW,selected=identity,capital=17000)
        second=next(row for row in y["rows"] if row["identity"]==identity)
        self.assertNotEqual(second.get("rank_quality"),"recent_depth_and_trades")

    def test_saved_iv_and_oi_history_and_contiguous_realized_vol(self):
        data=fixture()
        for day in range(1,21):
            previous=fixture();previous["received_utc"]=(NOW-timedelta(days=day)).isoformat()
            for r in previous["contracts"]:
                r["iv"]=10.+day/10
            self.save_snapshot(previous)
        previous=fixture();previous["received_utc"]=(NOW-timedelta(seconds=45)).isoformat()
        previous["contracts"][0]["oi"]=2900
        previous["contracts"][0]["volume"]=5900
        self.save_snapshot(previous)
        with live_market._database() as db:
            for i in range(31):
                t=(NOW-timedelta(minutes=i+1)).isoformat()
                price=SPOT+((-1)**i)*5
                db.execute("INSERT INTO live_minute_bars VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                           ("INDEX:BANKNIFTY",t,EXPIRY,price,price,price,price,2,t,t,t))
        x=ao.analyze(data,now=NOW,selected="NSE_FNO:1001")
        self.assertEqual(x["volatility"]["iv_prior_sessions"],20)
        self.assertAlmostEqual(x["volatility"]["iv_rank"],100)
        self.assertAlmostEqual(x["volatility"]["iv_percentile"],100)
        self.assertEqual(x["volatility"]["realized_returns"],30)
        self.assertGreater(x["volatility"]["realized_intraday_pct"],0)
        self.assertEqual(x["rows"][0]["oi_change"],100)
        self.assertEqual(x["rows"][0]["volume_change"],100)
        self.assertEqual(len(x["selected_history"]),1)
        self.assertAlmostEqual(x["oi"]["pcr"],6000/9000)
        self.assertIsNotNone(x["oi"]["max_pain_strike"])

    def test_api_returns_original_chain_and_no_order_flags(self):
        with patch.object(ao.option_chain_live,"chain",return_value=fixture()) as get:
            with TestClient(app,base_url="http://127.0.0.1:8765") as client:
                res=client.get("/api/trading-cockpit/options/analytics",params={"expiry":EXPIRY,"capital":17000})
                self.assertEqual(res.status_code,200,res.text[:300])
                body=res.json()
                self.assertEqual(body["chain"]["underlying_spot"],SPOT)
                self.assertFalse(body["orders_enabled"])
                self.assertIsNone(body["profit_probability"])
                self.assertTrue(body["read_only"])
                get.assert_called_once_with(EXPIRY)
