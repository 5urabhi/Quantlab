from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import sqlite3

from workstation_api import session_coverage as c, banknifty_constituents as b, nse_source_automation as intake, shared_market_data, service

class ReviewedSourceTests(TestCase):
    def setUp(self):
        tmp=TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        p=patch.object(service,"DATA",self.root/"data")
        p.start()
        self.addCleanup(p.stop)

    def test_explicit_calendar_and_expected_capture(self):
        path=shared_market_data.database_path()
        path.parent.mkdir(parents=True)
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE live_ticks(identity TEXT,exchange_utc TEXT)")
            db.executemany("INSERT INTO live_ticks VALUES(?,?)",[
                ("INDEX:BANKNIFTY","2025-11-20T18:30:00+00:00"),
                ("INDEX:BANKNIFTY","2025-11-20T18:30:00.000001+00:00"),
                ("INDEX:NIFTY50","2025-11-21T04:00:00+00:00"),
                ("INDEX:BANKNIFTY","2025-11-22T18:30:00+00:00")])
        calendar="session_date,state\n2025-11-21,OPEN\n2025-11-22,OPEN\n2025-11-23,CLOSED\n"
        kwargs=dict(source="live_ticks",identity="INDEX:BANKNIFTY",start="2025-11-21",end="2025-11-23",
                    calendar_csv=calendar,source_label="Synthetic reviewed calendar",confirm_reviewed=True)
        r=c.audit(**kwargs,expect_recording=True)
        self.assertTrue(r["read_complete"])
        self.assertEqual([x["count"] for x in r["rows"]],[2,0,1])
        self.assertEqual([x["verdict"] for x in r["rows"]],["OBSERVED","MISSING_EXPECTED_SESSION","CLOSED_WITH_RECORDS"])
        self.assertEqual(r["missing_expected_sessions"],1)
        r=c.audit(**kwargs,expect_recording=False)
        self.assertEqual(r["rows"][1]["verdict"],"NO_RECORDS_EXPECTATION_UNCONFIRMED")
        with self.assertRaises(ValueError):
            c.audit(**{**kwargs,"calendar_csv":"session_date,state\n2025-11-21,OPEN\n"},expect_recording=True)
        with self.assertRaises(ValueError):
            c.audit(**{**kwargs,"confirm_reviewed":False},expect_recording=True)

    def test_archive_weight_import_and_tamper_detection(self):
        incoming=self.root/"weight.csv"
        incoming.write_text("Symbol,Weightage (%)\nBANKA,60%\nBANKB,40%\n")
        receipt=intake.intake_local_exports([incoming])
        members={"date":"2025-11-21","symbols":["BANKA","BANKB"],"source_sha256":"a"*64}
        with patch.object(b,"membership",return_value=members):
            snap=b.import_archived_weights(receipt["id"],"weight.csv","2025-11-21",True)
            self.assertEqual(snap["weights_pct"],{"BANKA":60.,"BANKB":40.})
            self.assertIn(receipt["files"][0]["original_sha256"],snap["source"])
            self.assertFalse(snap["independently_verified"])
            with self.assertRaises(ValueError):
                b.import_archived_weights(receipt["id"],"weight.csv","2025-11-21",False)
            saved=Path(receipt["directory"])/"originals"/"weight.csv"
            saved.write_text("Symbol,Weightage (%)\nBANKA,50%\nBANKB,50%\n")
            with self.assertRaisesRegex(ValueError,"SHA-256"):
                b.import_archived_weights(receipt["id"],"weight.csv","2025-11-21",True)
