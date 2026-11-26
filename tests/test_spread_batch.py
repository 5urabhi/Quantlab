"""Offline tests; synthetic receipts are never live execution evidence."""
from datetime import datetime, timedelta, timezone, date
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest import TestCase
from unittest.mock import patch
import csv
import json
import sqlite3

from workstation_api import spread_batch as batch, spread_batch_core as core
from workstation_api import paper_execution as paper, depth_replay as replay
from workstation_api import spread_speed as speed, auto_option_depth as recorder

DAY=date(2026,11,26)
START=datetime(2026,11,26,3,45,tzinfo=timezone.utc)
NOW=START+timedelta(hours=7)
CFG=batch._settings(17000.,3,100.,1,1,25.,5.,"zerodha","","ALL","",True)


def group():
    return core._group("LONG_OPTION",[{"identity":"NSE_FNO:1","strike":63000.,"option_type":"CE",
                          "expiry":"2026-12-29","lot_size":30}],[1,2,3],50.)


class BatchTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.db=self.root/"market.sqlite3"
        with sqlite3.connect(self.db) as conn:
            conn.executescript("""CREATE TABLE live_depth_books(identity TEXT,received_utc TEXT,
                book_json TEXT,packet_pair_sha256 TEXT,PRIMARY KEY(identity,received_utc));
                CREATE TABLE live_ticks(identity TEXT,exchange_utc TEXT,received_utc TEXT,
                price REAL,packet_sha256 TEXT,session_id TEXT);""")
        p=patch.object(replay.ao,"_read_database",side_effect=lambda:sqlite3.connect(self.db.as_uri()+"?mode=ro",uri=True))
        p.start();self.addCleanup(p.stop)
        p=patch.object(batch,"_root",return_value=self.root)
        p.start();self.addCleanup(p.stop)

    def put(self,identity,stamp,ask,strike=63000,side="CE",quantity=2000):
        bid=ask-1.; b="a"*64; a="b"*64
        book={"identity":identity,"received_utc":paper._iso(stamp),
              "source":"original_Dhan_full_market_depth_websocket",
              "collection_mode":"auto_banknifty_20_level",
              "bid_packet_sha256":b,"ask_packet_sha256":a,
              "bid":[{"price":bid,"quantity":quantity,"orders":10}],
              "ask":[{"price":ask,"quantity":quantity,"orders":10}],
              "computed_features":{"lot_size_verified":30,"expiry":"2026-12-29","strike":strike,"side":side}}
        with sqlite3.connect(self.db) as conn:
            conn.execute("INSERT INTO live_depth_books VALUES (?,?,?,?)",
                (identity,paper._iso(stamp),json.dumps(book),sha256((b+a).encode()).hexdigest()))

    def test_all_affordable_contracts_and_lot_sizes(self):
        for i in range(1,24):
            self.put("NSE_FNO:"+str(i),START+timedelta(minutes=40),200 if i==1 else 100,
                     strike=63000+i*100)
        self.put("NSE_FNO:99",START+timedelta(minutes=40),700,strike=67000)
        ids=["NSE_FNO:"+str(i) for i in range(1,24)]+["NSE_FNO:99"]
        with patch.dict(recorder.STATE,{"contracts":[{"identity":i} for i in ids]}):
            groups,meta=core.universe(DAY.isoformat(),CFG,NOW)
        singles=[g for g in groups if g["family"]=="directional"]
        self.assertEqual(len(singles),23)  # not truncated to the UI's top twenty
        self.assertEqual(meta["affordable_contracts"],23)
        self.assertEqual(next(g for g in singles if g["identities"]==["NSE_FNO:1"])["lot_options"],[1,2])
        self.assertEqual(next(g for g in singles if g["identities"]==["NSE_FNO:2"])["lot_options"],[1,2,3])
        self.assertNotIn(["NSE_FNO:99"],[g["identities"] for g in singles])
        self.assertLessEqual(meta["vertical_baskets"],48)

    def test_replay_matches_existing_first_receipt_and_missing_stays_unscored(self):
        anchor=START+timedelta(minutes=40)
        self.put("NSE_FNO:1",anchor+timedelta(seconds=1),100.)
        self.put("NSE_FNO:1",anchor+timedelta(seconds=7),110.)
        anchors=[anchor,anchor+timedelta(minutes=1)]
        rows=core.evaluate(group(),[(1,1000,5),(2,1000,5)],CFG,DAY,anchors,{0:"UP"},NOW,Event())
        for size in (1,2):
            direct=replay.replay(strategy="LONG_OPTION",identities=["NSE_FNO:1"],lots=size,
                decision_utc=paper._iso(anchor),capital=17000.,hold_seconds=5,latency_ms=1000,
                window_seconds=1,participation_pct=25.,slippage_bps=5.,broker_profile="zerodha",now=NOW)
            row=next(r for r in rows if r["lots"]==size and r["cohort"]=="fixed")
            self.assertTrue(direct["exit_complete"])
            self.assertEqual(row["scored"],1)
            self.assertEqual(row["unscored"],1)
            self.assertEqual(row["mean_net"],direct["net_pnl_inr"])
            self.assertEqual(row["total_net"],direct["net_pnl_inr"])
            self.assertFalse(row["rankable"])
            signal=next(r for r in rows if r["lots"]==size and r["cohort"]=="signal")
            self.assertEqual(signal["attempted"],signal["random_control"]["attempted"])

    def test_causal_tick_reconstruction_excludes_late_bar_revision(self):
        anchors=[START+timedelta(minutes=30),START+timedelta(minutes=31)]
        with sqlite3.connect(self.db) as conn:
            for i in range(31):
                t=START+timedelta(minutes=i,seconds=30)
                conn.execute("INSERT INTO live_ticks VALUES(?,?,?,?,?,?)",
                    ("INDEX:BANKNIFTY",paper._iso(t),paper._iso(t+timedelta(seconds=1)),63000+i,"a"*64,"test"))
            late=START+timedelta(minutes=29,seconds=59)
            conn.execute("INSERT INTO live_ticks VALUES(?,?,?,?,?,?)",
                ("INDEX:BANKNIFTY",paper._iso(late),paper._iso(anchors[0]+timedelta(seconds=10)),64000,"b"*64,"test"))
        seen=[]
        def observe(identity,rows,*,now,include_chart):
            seen.append([r["close"] for r in rows])
            return {"quote_mode":"RECENT_LOCAL_CANDLE_NOT_VERIFIED_LIVE","contiguous_session_bars":len(rows),"direction":"UP"}
        with patch.object(core.trend,"snapshot",side_effect=observe):
            directions,stats=core.signal_cohorts(DAY,anchors,NOW)
        self.assertEqual(seen[0][-1],63029)
        self.assertEqual(seen[1][-2],64000)
        self.assertEqual(directions,{0:"UP",1:"UP"})
        self.assertEqual(stats["valid"],2)

    def test_rank_requires_sample_coverage_and_distinct_blocks(self):
        anchors=[START+timedelta(minutes=15+i) for i in range(120)]
        few=[(1000.,"complete",True,20.) if i<5 else (None,"missing",False,0.) for i in range(120)]
        stats=core.summarize(few,list(range(120)),anchors,100.)
        self.assertEqual(stats["mean_net"],1000.)
        self.assertIsNone(stats["robust_score"])
        self.assertFalse(stats["rankable"])
        good=[(20.,"complete",True,20.) if i%2==0 else (None,"missing",False,0.) for i in range(120)]
        stats=core.summarize(good,list(range(120)),anchors,100.)
        self.assertTrue(stats["rankable"])
        self.assertEqual(stats["scored_blocks"],4)
        self.assertEqual(stats["robust_score"],20.)
        self.assertLess(core.rank_key({**stats,"strategy":"LONG_OPTION","identities":["NSE_FNO:1"],"lots":1,"latency_ms":1000,"hold_seconds":5}),
                        core.rank_key({**core.summarize(few,list(range(120)),anchors,100.),"strategy":"LONG_OPTION","identities":["NSE_FNO:1"],"lots":1,"latency_ms":1000,"hold_seconds":5}))

    def test_freeze_exact_config_and_validate_without_reselection(self):
        g=group()
        anchors=[START+timedelta(minutes=i) for i in range(120)]
        metrics=core.summarize([(110.,"complete",True,20.)]*120,list(range(120)),anchors,100.)
        metrics["execution_costs"]={"stress":{str(x):{"scored":120,"mean_net":90.} for x in (1,5,10)}}
        calls=[]
        def evaluate(g,specs,cfg,day,anchors,directions,now,stop,cohorts):
            calls.append((g,specs,cfg.copy(),day,cohorts))
            return [{**metrics,"family":g["family"],"strategy":g["strategy"],"identities":g["identities"],
                     "legs":g["legs"],"direction":g["direction"],"selection_coverage_pct":g["coverage_pct"],
                     "lots":n,"latency_ms":d,"hold_seconds":h,"cohort":c}
                    for n,d,h in specs for c in cohorts if c=="fixed"]
        meta={"scanned_contracts":1,"affordable_contracts":1,"vertical_baskets":0}
        with patch.object(core,"universe",return_value=([g],meta)) as universe, \
             patch.object(core,"signal_cohorts",return_value=({},{"state":"missing_original_index_ticks","valid":0})), \
             patch.object(core,"evaluate",side_effect=evaluate), \
             patch.object(speed,"LATENCIES_MS",(1000,)),patch.object(speed,"HORIZONS",(5,)):
            result=batch.run(day=DAY.isoformat(),now=NOW,max_lots=3)
            self.assertEqual(result["configuration_count"],3)
            self.assertIsNotNone(result["plan_id"])
            plan=batch.load_plan(result["plan_id"])
            self.assertEqual(len(plan["configurations"]),1)
            self.assertEqual(plan["configurations"][0]["lots"],1)
            with batch.result_path(result["run_id"]).open() as f:
                self.assertEqual(len(list(csv.DictReader(f))),3)
            self.assertEqual(batch.list_plans()[0]["plan_id"],result["plan_id"])
            with self.assertRaisesRegex(ValueError,"strictly later"):
                batch.validate(plan_id=result["plan_id"],day=DAY.isoformat(),now=NOW)
            future=DAY+timedelta(days=1)
            with self.assertRaisesRegex(ValueError,"completed later"):
                batch.validate(plan_id=result["plan_id"],day=future.isoformat(),now=START+timedelta(days=1))
            confirmed=batch.validate(plan_id=result["plan_id"],day=future.isoformat(),now=NOW+timedelta(days=1))
            self.assertEqual(confirmed["mode"],"validation")
            self.assertEqual(confirmed["configuration_count"],1)
            self.assertEqual(confirmed["validation_rows"][0]["lots"],1)
            self.assertEqual(calls[-1][1],[(1,1000,5)])
            self.assertEqual(universe.call_count,1)
            self.assertEqual(confirmed["plan_id"],result["plan_id"])
        path=batch._plan_path(result["plan_id"])
        path.write_bytes(path.read_bytes()+b" ")
        with self.assertRaisesRegex(ValueError,"digest"):
            batch.load_plan(result["plan_id"])

    def test_expired_frozen_contract_is_unscored(self):
        anchor=START+timedelta(minutes=40,days=35)
        rows=core.evaluate(group(),[(1,1000,5)],CFG,anchor.date(),[anchor],{},anchor+timedelta(minutes=10),Event(),("fixed",))
        self.assertEqual(rows[0]["scored"],0)
        self.assertEqual(rows[0]["states"],{"expired_frozen_contract":1})
        self.assertIsNone(rows[0]["mean_net"])

    def test_cancel_stops_refill(self):
        g=group()
        started=[]
        def evaluate(group,specs,cfg,day,anchors,directions,now,stop,cohorts):
            started.append(1)
            stop.wait(.1)
            return []
        def cancel(percent,stage):
            raise RuntimeError("cancelled")
        with patch.object(core,"evaluate",side_effect=evaluate):
            with self.assertRaisesRegex(RuntimeError,"cancelled"):
                batch._task_groups([(g,[(1,1000,5)],("fixed",))]*20,CFG,DAY,[],{},NOW,2,cancel,lambda _:None)
        self.assertLessEqual(len(started),2)
