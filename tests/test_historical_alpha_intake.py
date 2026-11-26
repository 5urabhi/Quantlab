"""Offline source and chronology tests; no broker/provider network requests."""
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from contextlib import closing
import csv
import json
import sqlite3

from workstation_api import historical_alpha as h, participant_inbox as inbox
from workstation_api import context_cohort as cohort, market_context as m
from workstation_api import constituent_alpha as a, constituent_prospective as p

NOW=datetime(2026,11,25,12,0,tzinfo=timezone.utc)
DAY="2026-11-24"
REPORT="Original fixture\nClient Type,Future Index Long,Future Index Short,Option Index Call Long,Option Index Put Long,Option Index Call Short,Option Index Put Short\nClient,20,10,30,10,20,30\nDII,10,20,10,30,20,10\nFII,20,10,30,10,20,30\nPro,10,20,10,30,20,10\nTOTAL,60,60,80,80,80,80\n"

def bars(base=100.):
    return {i:(base+i*.01,base+i*.01+.05,base+i*.01-.05,base+i*.01,100+i) for i in range(375)}

class HistoricalTests(TestCase):
    def test_fixed_windows_features_do_not_see_future_label(self):
        index=bars(63000.);stocks={"A":{DAY:bars(100.)},"B":{DAY:bars(200.)}}
        rows,counts=h._sample_day(DAY,index,stocks,["A","B"],{"A":1.,"B":1.},15,[])
        self.assertEqual(counts["scored"],len(rows))
        self.assertEqual(counts["reserved_nonoverlap"],len(rows))
        self.assertGreater(len(rows),10)
        orig=rows[0]
        index[45]=(65000.,65001.,64999.,65000.,0)
        rows2,_=h._sample_day(DAY,index,stocks,["A","B"],{"A":1.,"B":1.},15,[])
        self.assertEqual(rows2[0]["index"],orig["index"])
        self.assertEqual(rows2[0]["full"],orig["full"])
        self.assertNotEqual(rows2[0]["return_bps"],orig["return_bps"])
        del index[45]
        rows3,c3=h._sample_day(DAY,index,stocks,["A","B"],{"A":1.,"B":1.},15,[])
        self.assertEqual(c3["reserved_nonoverlap"],counts["reserved_nonoverlap"])
        self.assertEqual(c3["missing_label"],1)
        self.assertNotEqual(rows3[0]["decision_utc"],orig["decision_utc"])
        self.assertEqual(h._member_set([{"symbol":"A","valid_from":"2026-01-01","valid_to":"2026-11-24"},
                                       {"symbol":"B","valid_from":"2026-11-24","valid_to":""}],DAY),["B"])

    def test_missing_member_and_session_close(self):
        index=bars(63000.);stocks={"A":{DAY:bars()}}
        out,c=h._sample_day(DAY,index,stocks,["A","B"],{"A":1,"B":1},30,[])
        self.assertEqual(out,[])
        self.assertEqual(c["missing_constituent_features"],c["reserved_nonoverlap"])
        rows,c=h._sample_day(DAY,index,stocks,["A"],{"A":1},0,[])
        self.assertEqual(len(rows),1)
        self.assertEqual(a._stamp(rows[0]["target_utc"]).astimezone(h.IST).strftime("%H:%M"),"15:30")

    def test_original_file_hash_and_window(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/"minute.csv"
            raw=("datetime,open,high,low,close,volume\n"
                 "2026-11-24T03:45:00+00:00,100,101,99,100,5\n").encode()
            path.write_bytes(raw)
            rows=h._read_file(path,sha256(raw).hexdigest(),date(2026,11,24),date(2026,11,25),[10000],1)
            self.assertEqual(rows[DAY][0],(100.,101.,99.,100.,5))
            with self.assertRaisesRegex(ValueError,"checksum"):
                h._read_file(path,"0"*64,date(2026,11,24),date(2026,11,25),[10000],1)

    def test_blocked_run_still_exports_source_audit(self):
        raw={"historical_index":{"intervals_sha256":"a"*64}}
        intervals=[{"symbol":"A","valid_from":"2026-01-01","valid_to":""}]
        with TemporaryDirectory() as tmp,patch.object(a,"_root",return_value=Path(tmp)), \
             patch.object(h,"_batch",return_value=(raw,date(2026,11,24),date(2026,11,25),intervals,{"A":"NSE_EQ:1"})), \
             patch.object(h,"_sources",return_value=({DAY:bars(63000.)},{"A":{DAY:bars()}},{"INDEX:BANKNIFTY":"a"*64},{})), \
             patch.object(a,"_compare") as fit:
            r=h.run(batch_id="batch_"+"a"*16,horizon=15)
            fit.assert_not_called()
            self.assertEqual(r["state"],"awaiting_recorded_sessions")
            self.assertGreater(r["evidence_counts"]["scored"],0)
            self.assertFalse(r["live_model_promoted"])
            with a.result_path(r["audit_id"],audit=True).open() as file:
                self.assertEqual(len(list(csv.DictReader(file))),2)

class InboxTests(TestCase):
    def test_consent_receipt_deduplication_and_no_file_removal(self):
        with TemporaryDirectory() as tmp,patch.object(inbox.service,"DATA",Path(tmp)), \
             patch.object(m.shared_market_data,"database_path",return_value=Path(tmp)/"shared.db"), \
             patch.object(inbox.recorder_storage,"allow",return_value=True), \
             patch.object(inbox.recorder_storage,"saved"),patch.dict(inbox._CACHE,{},clear=True):
            with self.assertRaises(ValueError):
                inbox.configure(True,"licensed test",False)
            inbox.configure(True,"licensed test",True)
            file=inbox._folder()/"fao_participant_oi_24112026.csv"
            file.write_text(REPORT)
            r=inbox.scan(now=NOW)
            self.assertEqual(r["counts"]["imported"],1)
            self.assertTrue(file.is_file())
            inbox._CACHE.clear() # simulate restart
            r=inbox.scan(now=NOW+timedelta(hours=1))
            self.assertEqual(r["counts"]["already_saved"],1)
            with closing(sqlite3.connect(Path(tmp)/"shared.db")) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM market_context_observations").fetchone()[0],12)
                self.assertEqual(db.execute("SELECT imported_utc FROM market_context_imports").fetchone()[0],m._iso(NOW))
            inbox.configure(False,"",False)
            self.assertFalse(inbox.status()["config"]["enabled"])

class CohortTests(TestCase):
    def test_fixed_future_registration_cannot_reset(self):
        with TemporaryDirectory() as tmp:
            db=Path(tmp)/"shared.db"
            with patch.object(cohort.shared_market_data,"database_path",return_value=db), \
                 patch.object(a,"_read",side_effect=lambda:sqlite3.connect(db)):
                first=cohort.register("all",30,True,now=NOW)
                again=cohort.register("all",30,True,now=NOW+timedelta(days=3))
                self.assertEqual(first,again)
                self.assertEqual(first["start_session"],"2026-11-26")
                with closing(sqlite3.connect(db)) as con:
                    con.execute("CREATE TABLE banknifty_paired_signals(protocol_hash TEXT,horizon_minutes INTEGER,session_ist TEXT)")
                    for day in ("2026-11-24","2026-11-26","2026-11-27"):
                        con.execute("INSERT INTO banknifty_paired_signals VALUES(?,?,?)",(p.PROTOCOL_HASH,30,day))
                    self.assertEqual(a._days(con,30,"2026-11-28",first["start_session"]),["2026-11-26","2026-11-27"])
