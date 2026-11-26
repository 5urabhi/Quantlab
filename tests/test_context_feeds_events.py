"""Offline fixtures: no provider calls or live predictive performance claims."""
from datetime import datetime,timedelta,timezone
from email.utils import format_datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from contextlib import closing
import json
import sqlite3

from workstation_api import context_feeds as f, context_events as e, context_alpha as a, market_context as m

NOW=datetime(2026,11,25,10,0,tzinfo=timezone.utc)

def rss(title,published):
    return ('<rss version="2.0"><channel><title>Fixture</title><item><title>'+title+
            '</title><link>https://www.federalreserve.gov/fixture.htm</link><pubDate>'+
            format_datetime(published)+'</pubDate></item></channel></rss>').encode()

class ProviderTests(TestCase):
    def test_config_rejects_duplicate_or_conflicting_mapping(self):
        x={"factor":"NIKKEI","symbol":"fixture","exchange":"fixture exchange"}
        good={**f.DEFAULT,"mappings":[x]}
        self.assertEqual(f._validate(good)["mappings"],[x])
        with self.assertRaises(ValueError):
            f._validate({**good,"mappings":[x,x]})
        with self.assertRaises(ValueError):
            f._validate({**good,"mappings":[{**x,"factor":"SP500_CLOSE"}]})
        with self.assertRaises(ValueError):
            f.configure(good,False)

    def test_fred_missing_and_future_rows(self):
        raw=json.dumps({"observations":[{"date":"2026-11-24","value":"100"},
              {"date":"2026-11-25","value":"."},{"date":"2026-11-26","value":"999"}]}).encode()
        self.assertEqual(f._fred_rows(raw,NOW),[(datetime(2026,11,24,tzinfo=timezone.utc),100.)])

    def test_twelve_requires_identity_and_completed_bars(self):
        mapping={"factor":"NIKKEI","symbol":"FIX","exchange":"TEST"}
        data={"status":"ok","meta":{"symbol":"FIX","exchange":"TEST","interval":"5min"},
            "values":[{"datetime":"2026-11-25 09:50:00","close":"101"},
                      {"datetime":"2026-11-25 10:00:00","close":"999"}]}
        raw=json.dumps(data).encode()
        self.assertEqual(f._twelve_rows(raw,mapping,NOW),[(NOW-timedelta(minutes=5),101.)])
        with self.assertRaises(ValueError):
            f._twelve_rows(raw,{**mapping,"exchange":"OTHER"},NOW)
        with self.assertRaises(ValueError):
            f._http("https://example.com")

    def test_automatic_receipt_deduplication_and_revisions(self):
        with TemporaryDirectory() as tmp,patch.object(m.shared_market_data,"database_path",return_value=Path(tmp)/"market.db"),patch.object(f.recorder_storage,"allow",return_value=True):
            event=NOW-timedelta(days=1)
            self.assertEqual(f._save_factor("SP500_CLOSE","FRED:SP500",[(event,100.)],b'{}',NOW),1)
            self.assertEqual(f._save_factor("SP500_CLOSE","FRED:SP500",[(event,100.)],b'{}',NOW+timedelta(hours=1)),0)
            self.assertEqual(f._save_factor("SP500_CLOSE","FRED:SP500",[(event,101.)],b'{}',NOW+timedelta(hours=2)),1)
            with closing(sqlite3.connect(Path(tmp)/"market.db")) as db:
                rows=db.execute("SELECT value,available_utc FROM market_context_observations ORDER BY available_utc").fetchall()
                self.assertEqual(rows,[(100.,m._iso(NOW)),(101.,m._iso(NOW+timedelta(hours=2)))])

class EventTests(TestCase):
    def test_future_headlines_and_truncated_calendar_rejected(self):
        with self.assertRaises(ValueError):
            e.parse_rss(rss("Banking release",NOW+timedelta(minutes=1)),"fed_banking",NOW)
        with self.assertRaises(ValueError):
            e.parse_calendar(b'{"count":5,"release_dates":[]}',NOW)
        with self.assertRaises(ValueError):
            e.parse_rss(b'<!DOCTYPE rss><rss/>',"fed_banking",NOW)

    def test_events_require_actual_receipt_not_just_publication(self):
        with TemporaryDirectory() as tmp,patch.object(m.shared_market_data,"database_path",return_value=Path(tmp)/"market.db"):
            for source in e.SOURCES:
                e.save(source,rss("Monetary policy and banking",NOW-timedelta(hours=1)),NOW)
            raw=json.dumps({"count":1,"release_dates":[{"release_id":9,"release_name":"Consumer Price Index","date":"2026-11-26"}]}).encode()
            e.save(e.CALENDAR,raw,NOW)
            with closing(sqlite3.connect(Path(tmp)/"market.db")) as db:
                self.assertIsNone(e.features_at(db,NOW-timedelta(seconds=1)))
                values,detail=e.features_at(db,NOW)
                self.assertTrue(detail["full_source_coverage"])
                self.assertEqual(values[e.FEATURE_NAMES.index("release_dates_tomorrow")],1.)
                self.assertEqual(values[e.FEATURE_NAMES.index("fed_monetary_news_24h")],1.)
                late=e.features_at(db,NOW+timedelta(hours=2))
                self.assertFalse(late[1]["full_source_coverage"])
                row={"cutoff_utc":m._iso(NOW),"index":[0.,0.,0.],"full":[0.]}
                kept,counts,_=a._attach(db,[row],{},"events")
                self.assertEqual(len(kept),1)
                self.assertEqual(counts["events_available"],1)
                row["cutoff_utc"]=m._iso(NOW-timedelta(seconds=1))
                kept,counts,_=a._attach(db,[row],{},"events")
                self.assertEqual(kept,[])
                self.assertEqual(counts["missing_events_context"],1)
