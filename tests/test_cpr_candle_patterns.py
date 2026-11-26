"""Synthetic causal and funding invariants, not market performance evidence."""
from datetime import date,datetime,timedelta,timezone
from unittest import TestCase
from unittest.mock import patch

from workstation_api import candle_pattern_research as p, cpr_hybrid_research as r
from workstation_api import cpr_debit_spreads as spreads, cpr_context_features as cx
from workstation_api import cpr_alpaca_archive as alpaca, context_feeds, data_maintenance

DAY="2026-10-06"


def candles(n=375):
    rows={}
    previous=60000.
    for i in range(n):
        price=60000.+[0,20,20,0][(i//5)%4]
        rows[i]=(previous,max(previous,price)+1,min(previous,price)-1,price,100.)
        previous=price
    return rows


def option(strike,price):
    return {"session_ist":DAY,"side":"CALL","strike":strike,"expiry_flag":"MONTH","expiry_code":1,
            "open":price,"close":price,"volume":100}


def spread_quotes():
    return {("CALL",60000):option(60000,300.),("CALL",60100):option(60100,260.)}


class CandlePatternTests(TestCase):
    def test_only_completed_prefix_used_and_missing_bar_blocks(self):
        bars=candles()
        before=p.describe(bars,29,5)
        self.assertIsNotNone(before)
        bars[30]=(1.,2.,1.,2.,1.)
        self.assertEqual(p.describe(bars,29,5),before)
        del bars[12]
        self.assertIsNone(p.describe(bars,29,5))

    def test_color_distinct_from_close_to_close_direction(self):
        bars=candles()
        bars[20]=(59980.,60000.,59979.,59990.,100.)
        bars[19]=(60020.,60021.,60019.,60020.,100.)
        out=p.outcome(bars,19,1)
        self.assertEqual(out["next_color"],"G")
        self.assertEqual(out["label"],"down")
        del bars[20]
        self.assertIsNone(p.outcome(bars,19,1))

    def test_pattern_scope_and_validation_only_model_selection(self):
        dates=[(date(2026,8,1)+timedelta(days=i)).isoformat() for i in range(27)]
        index={d:candles(50) for d in dates}
        splits=(dates[:20],dates[20:25],dates[25:])
        sig=[{"session":dates[0],"minute":24,"side":"CALL"},
             {"session":dates[-1],"minute":24,"side":"CALL"}]
        with patch.object(p,"HORIZONS",(5,)):
            result=p.assess(index,splits,sig)
            self.assertEqual(result["horizons"]["5"]["state"],"exploratory_assessment")
            chosen=result["horizons"]["5"]["selected"]
            self.assertNotIn("candle_direction_5m",sig[0])
            forecast=sig[1]["candle_direction_5m"].copy()
            self.assertAlmostEqual(sum(forecast[x] for x in p.CLASSES),1.)
            self.assertIn("patterns",sig[1]["context_vectors"])
            index[dates[-1]][25]=(60000.,61001.,59999.,61000.,100.)
            later=[{"session":dates[-1],"minute":24,"side":"CALL"}]
            again=p.assess(index,splits,later)
            self.assertEqual(again["horizons"]["5"]["selected"],chosen)
            self.assertEqual(later[0]["candle_direction_5m"],forecast)

    def test_context_q_keeps_distinct_entry_regimes_and_support(self):
        episodes=[]
        for i in range(6):
            day=(date(2026,9,1)+timedelta(days=i)).isoformat()
            vec=[0.]* (3*len(p.FEATURE_NAMES)+1)
            vec[len(p.FEATURE_NAMES)]=.8
            path=[{"minute":10,"elapsed":1,"mark_return":.01,"trend":.01,"drawdown":0.,
                  "exit_net":20.,"exit_fees":70.,"exit_utc":r._stamp(day,12),"terminal":False},
                  {"minute":11,"elapsed":2,"mark_return":-.07,"trend":-.01,"drawdown":.08,
                  "exit_net":-90.,"exit_fees":70.,"exit_utc":r._stamp(day,13),"terminal":True}]
            episodes.append({"session":day,"minute":9,"side":"CALL","strike":60000,"state":"entered",
                             "debit":1000.,"path":path,"context_vectors":{"patterns":vec}})
        q,info=r._fit_q(episodes,context_scope="patterns")
        self.assertGreater(info["supported_states"],0)
        self.assertTrue(all(len(k)==5 and k[-1]==1 for k in q))
        self.assertEqual(r._exit(episodes[-1],"offline_q",q,context_scope="patterns")["reason"],"learned_exit")
        missing={**episodes[-1],"context_vectors":{}}
        self.assertEqual(r._exit(missing,"offline_q",q,context_scope="patterns")["reason"],"stop")

    def test_debit_spread_separates_net_debit_from_gross_funding_and_retries_both_legs(self):
        signal={"session":DAY,"minute":4,"side":"CALL","spot":60000.,
                "decision_utc":r._stamp(DAY,5),"entry_utc":r._stamp(DAY,6)}
        table={r._stamp(DAY,4):spread_quotes(),r._stamp(DAY,6):spread_quotes(),
               r._stamp(DAY,8):{("CALL",60000):option(60000,300.)},
               r._stamp(DAY,9):spread_quotes()}
        gross=spreads.episode(r,signal,table,candles(),hold=15,lot_size=30,bps=35,
                             risk_budget=2500,lane="gross_funding")
        self.assertEqual(gross["state"],"no_affordable_observed_contract")
        debit=spreads.episode(r,signal,table,candles(),hold=15,lot_size=30,bps=35,
                             risk_budget=2500,lane="net_debit_counterfactual")
        self.assertEqual(debit["state"],"entered")
        self.assertGreater(debit["planned_gross_funding"],2500)
        self.assertEqual(debit["short_strike"],60100)
        result=r._exit(debit,"fixed_stop")
        self.assertEqual(result["state"],"complete")
        self.assertEqual(result["exit_utc"],r._stamp(DAY,9))
        self.assertEqual(result["exit_delay_minutes"],1)

    def test_fixed_panel_uses_pinned_identity_and_allows_separate_price_range(self):
        symbols=cx.PANEL_SYMBOLS
        raw={"from_date":"2026-01-01","historical_index":{"covered_through":"2026-10-13",
             "intervals":[{"symbol":s,"valid_from":"2026-01-01","valid_to":None} for s in symbols]},
             "items":[{"pit_symbol":s,"id":"NSE_EQ:"+str(i+1)} for i,s in enumerate(symbols)]}
        start,stop=date(2026,9,1),date(2026,11,26)
        with patch.object(cx.h.dw,"_load_batch",return_value=raw), \
             patch.object(cx.h.pq,"_source_signature",return_value={"source_sha256":"hash"}), \
             patch.object(cx.h.pq,"_raw",return_value=("fixture",None)), \
             patch.object(cx.h,"_read_file",return_value={"2026-11-25":candles(31)}) as read:
            stocks,intervals,meta=cx._load_fixed_panel(start,stop,{"batch_id":"fixture"},enabled=True)
        self.assertEqual(set(stocks),set(symbols))
        self.assertEqual(meta["state"],"loaded")
        self.assertTrue(all(call.args[3]==stop for call in read.call_args_list))
        self.assertTrue(all(v["valid_from"]==start.isoformat() for v in intervals))

    def test_live_proxy_completed_bar_clock(self):
        received=datetime(2026,11,26,12,2,tzinfo=timezone.utc)
        rows=[{"t":"2026-11-26T11:55:00Z","o":100,"h":102,"l":99,"c":101,"v":1000},
              {"t":"2026-11-26T12:00:00Z","o":100,"h":102,"l":99,"c":101,"v":1000}]
        out=alpaca.recent_rows("US_SPY_ETF_5M",rows,received,intraday=True)
        self.assertEqual(out,[(datetime(2026,11,26,12,tzinfo=timezone.utc),101.)])

    def test_old_settings_never_opt_in_new_sources(self):
        cfg={k:v for k,v in context_feeds.DEFAULT.items() if k not in ("alpaca","alpaca_feed","alpaca_intraday")}
        self.assertFalse(context_feeds._validate(cfg)["alpaca"])
        old={k:v for k,v in data_maintenance.DEFAULT.items() if k!="bank_panel"}
        self.assertFalse(data_maintenance.validate(old)["bank_panel"])
        with self.assertRaises(ValueError):
            context_feeds._validate({**context_feeds.DEFAULT,"alpaca_intraday":True})
        with self.assertRaises(ValueError):
            data_maintenance.validate({**data_maintenance.DEFAULT,"enabled":True,
                                      "bank_panel":True,"index":False,"constituents":False})

    def test_maintenance_post_route_is_unique(self):
        from workstation_api import app as api
        routes=[x for x in api.app.routes if getattr(x,"path",None)=="/api/data-manager/maintenance"
                and "POST" in (getattr(x,"methods",None) or ())]
        self.assertEqual(len(routes),1)
        with patch.object(api.data_maintenance,"configure",return_value={"configured":True}) as config:
            response=api.configure_market_library_maintenance(api.MarketMaintenanceRequest(
                enabled=True,bank_panel=True,confirm_readonly=True))
        self.assertEqual(response,{"configured":True})
        self.assertTrue(config.call_args.args[0]["bank_panel"])
