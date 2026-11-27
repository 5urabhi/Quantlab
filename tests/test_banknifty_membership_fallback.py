"""Offline dated-membership fallback tests; no real source or network access."""
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from workstation_api import banknifty_membership_fallback as m


def catalog():
    return [{"id":f"NSE_EQ:{i+1}","symbol":f"BANK{i}","exchange_segment":"NSE_EQ",
             "regular_eq":True,"trading_symbol_verified":True} for i in range(14)]


def mapping():
    return {x["symbol"]:x["id"] for x in catalog()}


class MembershipFallbackTests(TestCase):
    def test_hash_verified_archive_covers_only_documented_dates(self):
        with TemporaryDirectory() as tmp:
            csv=Path(tmp)/"members.csv";manifest=Path(tmp)/"source.json"
            body=("index_name,symbol,valid_from,valid_to,source,source_url\n"+
                  "".join(f"Nifty Bank,BANK{i},2026-10-01,,fixture,fixture\n" for i in range(14))).encode()
            csv.write_bytes(body)
            manifest.write_text(json.dumps({"normalized_sha256":sha256(body).hexdigest(),
                "source_repository":m.pit.SOURCE_REPOSITORY,"first_date":"2026-10-01",
                "covered_through":"2026-10-20","source_commit":"a"*40}))
            dates=["2026-09-30","2026-10-14","2026-10-21"]
            with patch.object(m.pit,"_csv_path",return_value=csv),patch.object(m.pit,"_metadata_path",return_value=manifest):
                out,audit=m.local_archive(dates,catalog())
                self.assertEqual(out,{"2026-10-14":mapping()})
                self.assertEqual(audit["covered_through"],"2026-10-20")
                csv.write_bytes(body+b"\n")
                with self.assertRaisesRegex(ValueError,"checksum"):
                    m.local_archive(dates,catalog())

    def test_fills_gap_without_replacing_pinned_or_conflicting_date(self):
        a,b,c="2026-10-13","2026-10-14","2026-10-15"
        pinned={a:mapping()}
        with patch.object(m.dw,"catalog",return_value=catalog()), \
             patch.object(m,"local_archive",return_value=({a:mapping(),b:mapping(),c:mapping()},{})), \
             patch.object(m.bank,"_current_membership",return_value=None) as official:
            out,audit=m.supplement([a,b,c],pinned,[c])
        self.assertEqual(out,{a:mapping(),b:mapping()})
        self.assertEqual(audit["recovered_dates"],[b])
        self.assertEqual(audit["remaining_missing_dates"],[c])
        self.assertEqual(audit["source_by_date"][a],"pinned_batch")
        official.assert_not_called()

    def test_archive_overlap_conflict_blocks_archive_and_uses_only_preopen_receipt(self):
        a,b,c="2026-10-13","2026-10-14","2026-10-15"
        different=mapping();different["BANK0"]="NSE_EQ:900"
        def official(day,items,asof):
            self.assertEqual(asof,datetime.combine(day,datetime.min.time(),m.h.IST)+timedelta(hours=9,minutes=15))
            return {"resolved":mapping(),"symbols":list(mapping()),"source_sha256":"a"*64} if day==date.fromisoformat(c) else None
        with patch.object(m.dw,"catalog",return_value=catalog()), \
             patch.object(m,"local_archive",return_value=({a:different,b:mapping()},{})), \
             patch.object(m.bank,"_current_membership",side_effect=official):
            out,audit=m.supplement([a,b,c],{a:mapping()},[])
        self.assertEqual(audit["local_archive"]["state"],"overlap_conflict")
        self.assertNotIn(b,out)
        self.assertEqual(audit["source_by_date"][c],"same_day_official_preopen")

    def test_unresolved_or_ambiguous_mapping_never_guessed(self):
        self.assertIsNone(m._resolved({"BANK0"},catalog()+[catalog()[0]]))
        self.assertIsNone(m._resolved({"UNKNOWN"},catalog()))
        day="2026-10-14"
        with patch.object(m.dw,"catalog",return_value=catalog()), \
             patch.object(m,"local_archive",side_effect=ValueError("absent")), \
             patch.object(m.bank,"_current_membership",return_value={"resolved":{"BANK0":"NSE_EQ:1"},
                            "symbols":["BANK0","BANK1"],"source_sha256":"a"*64}):
            out,audit=m.supplement([day],{},[])
        self.assertEqual(out,{})
        self.assertIn(day,audit["official_receipt_failures"])
