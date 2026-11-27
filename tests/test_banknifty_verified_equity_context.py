"""Check original equity integrity and read-only daily aggregation."""
from datetime import datetime,timedelta,timezone
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import json
import pandas as pd
from workstation_api import verified_equity_context as m


def publish(folder,stem,rows):
    folder.mkdir(parents=True,exist_ok=True)
    csv=folder/(stem+".csv")
    pd.DataFrame(rows,columns=["datetime","close"]).to_csv(csv,index=False)
    info={"instrument_id":"NSE_EQ:"+folder.name,"interval_minutes":1 if stem=="1m" else None,
          "sha256":sha256(csv.read_bytes()).hexdigest(),"rows":len(rows),
          "coverage":[["2026-10-05","2026-10-10"]]}
    sidecar=csv.with_suffix(".json")
    sidecar.write_text(json.dumps(info))
    return sidecar


def minute_rows(day,count,start_price=100.):
    start=datetime.fromisoformat(day+"T03:45:00+00:00")
    return [((start+timedelta(minutes=i)).isoformat(),start_price+i*.01) for i in range(count)]


class VerifiedEquityTests(TestCase):
    def test_complete_regular_minutes_only_and_cutoff(self):
        with TemporaryDirectory() as tmp:
            folder=Path(tmp)/"123"
            path=publish(folder,"1m",minute_rows("2026-10-05",375)+minute_rows("2026-10-06",374)
                         +minute_rows("2026-10-07",375))
            close,info=m._original_daily(path,"NSE_EQ:123",1,"2026-10-07",[m.MAX_TOTAL_BYTES])
            self.assertEqual(list(close.index),["2026-10-05"])
            self.assertAlmostEqual(close.iloc[0],103.74)
            self.assertEqual(info["incomplete_regular_sessions"],1)
            self.assertEqual(info["original_rows"],1124)
            self.assertEqual(info["last_session"],"2026-10-05")
            csv=path.with_suffix(".csv")
            csv.write_bytes(csv.read_bytes()+b"\n")
            with self.assertRaisesRegex(ValueError,"hash mismatch"):
                m._original_daily(path,"NSE_EQ:123",1,"2026-10-07",[m.MAX_TOTAL_BYTES])

    def test_duplicate_minute_or_row_count_rejected(self):
        with TemporaryDirectory() as tmp:
            folder=Path(tmp)/"123"
            rows=minute_rows("2026-10-05",375)
            path=publish(folder,"1m",rows+[rows[-1]])
            with self.assertRaisesRegex(ValueError,"duplicate"):
                m._original_daily(path,"NSE_EQ:123",1,"2026-10-06",[m.MAX_TOTAL_BYTES])
            info=json.loads(path.read_text());info["rows"]+=1;path.write_text(json.dumps(info))
            with self.assertRaisesRegex(ValueError,"row count"):
                m._original_daily(path,"NSE_EQ:123",1,"2026-10-06",[m.MAX_TOTAL_BYTES])

    def test_daily_and_minute_same_identity_no_conflict_overwrite(self):
        with TemporaryDirectory() as tmp:
            data=Path(tmp)
            folder=data/"dhan/history/NSE_EQ/123"
            publish(folder,"1m",minute_rows("2026-10-05",375)+minute_rows("2026-10-06",375))
            publish(folder,"daily",[("2026-10-02T00:00:00+00:00",98.),
                                     ("2026-10-05T00:00:00+00:00",150.),
                                     ("2026-10-06T00:00:00+00:00",103.74)])
            before={p:p.read_bytes() for p in folder.iterdir()}
            with patch.object(m.service,"DATA",data):
                frame,meta=m.original_panel("2026-10-07")
            self.assertEqual(list(frame.columns),["NSE_EQ_123"])
            self.assertEqual(list(frame.index),["2026-10-02","2026-10-06"])
            self.assertEqual(meta["conflicting_daily_closes"],1)
            self.assertEqual(meta["verified_sources"],2)
            self.assertEqual(meta["state"],"insufficient_verified_equities")
            self.assertEqual(before,{p:p.read_bytes() for p in folder.iterdir()})

    def test_unsafe_or_wrong_identity_rejected(self):
        with TemporaryDirectory() as tmp:
            data=Path(tmp)
            folder=data/"dhan/history/NSE_EQ/123"
            path=publish(folder,"daily",[("2026-10-05T00:00:00+00:00",100.)])
            meta=json.loads(path.read_text());meta["instrument_id"]="NSE_EQ:456";path.write_text(json.dumps(meta))
            with patch.object(m.service,"DATA",data):
                frame,audit=m.original_panel("2026-10-06")
            self.assertTrue(frame.empty)
            self.assertIn("NSE_EQ:123/daily",audit["rejected_sources"])
