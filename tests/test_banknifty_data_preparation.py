"""Offline acquisition-plan and generic index identity tests."""
from datetime import date,datetime
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import json
from index_research.dhan_data import Instrument
from scripts import prepare_banknifty_data as m


class PreparationTests(TestCase):
    def test_chunks_half_open_and_bound(self):
        a=date(2026,1,1);b=date(2026,1,12)
        self.assertEqual(list(m.chunks(a,b,5)),[(a,date(2026,1,6)),(date(2026,1,6),date(2026,1,11)),(date(2026,1,11),b)])

    def test_index_plan_reuses_checked_windows_repairs_known_dates_only(self):
        a=date(2026,10,5);b=date(2026,10,12)
        audit={"checked_ranges":[["2026-10-05","2026-10-10"]],"complete_dates":["2026-10-05"]}
        result=m.index_plan(audit,{"2026-10-05","2026-10-07"},a,b)
        self.assertEqual(result,[(date(2026,10,7),date(2026,10,8))])
        audit["checked_ranges"]=[]
        self.assertEqual(m.index_plan(audit,{"2026-10-05","2026-10-07"},a,b),[(a,b)])

    def test_market_priority_guard(self):
        self.assertFalse(m.offhours(datetime(2026,10,5,9,15,tzinfo=m.h.IST)))
        self.assertTrue(m.offhours(datetime(2026,10,5,16,0,tzinfo=m.h.IST)))
        self.assertTrue(m.offhours(datetime(2026,10,10,9,15,tzinfo=m.h.IST)))

    def test_generic_original_index_receipt_requires_exact_identity(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            raw=root/"dhan"/"raw"/"download_0123456789ab"
            raw.mkdir(parents=True)
            csv=raw/"BANKNIFTY_INDEX_intraday_1m.csv"
            manifest=raw/"BANKNIFTY_INDEX_intraday_1m.manifest.json"
            csv.write_bytes(b"fixture")
            data={"source":"DhanHQ REST API v2","interval_minutes":1,
                  "instrument":{"label":"BANKNIFTY_INDEX","exchange_segment":"IDX_I","instrument":"INDEX","security_id":"25"},
                  "row_count":1,"sha256":sha256(csv.read_bytes()).hexdigest()}
            manifest.write_text(json.dumps(data))
            exact=Instrument("BANKNIFTY_INDEX","25","IDX_I","INDEX")
            with patch.object(m.service,"DATA",root),patch.object(m.index_spot,"resolve",return_value=exact):
                self.assertEqual(len(m.cs._candidates("INDEX:BANKNIFTY")),1)
                data["instrument"]["security_id"]="13";manifest.write_text(json.dumps(data))
                self.assertEqual(m.cs._candidates("INDEX:BANKNIFTY"),[])
