"""Offline-only DhanHQ v2 adapter tests. NO TOKEN and NO NETWORK."""
import tempfile
import unittest
from pathlib import Path
import numpy as np
import pandas as pd

from index_research.dhan_data import (
    Instrument, read_instruments, date_windows, candles_to_frame,
    download_candles, save_download, build_monthly_close
)


def response(rows):
    """Two trading dates with valid Unix timestamps."""
    return {
        "timestamp":[1705289400,1705375800][:rows],
        "open":[100,110][:rows],
        "high":[110,120][:rows],
        "low":[95,105][:rows],
        "close":[105,115][:rows],
        "volume":[1000,2000][:rows],
    }


class DhanOfflineTests(unittest.TestCase):
    def test_chunk_boundaries(self):
        ranges=list(date_windows("2024-01-01","2024-08-01",90))
        self.assertEqual(ranges[0][0].isoformat(),"2024-01-01")
        self.assertEqual(ranges[-1][1].isoformat(),"2024-08-01")
        self.assertTrue(all((stop-start).days<=90 for start,stop in ranges))

    def test_bad_ohlc_is_quarantined_without_changing_valid_prices(self):
        instrument=Instrument("A","1333")
        invalid=response(2)
        invalid["high"]=[98,120]
        frame=candles_to_frame(invalid,instrument)
        self.assertEqual(len(frame),1)
        self.assertEqual(int(frame.iloc[0]["high"]),120)
        self.assertEqual(frame.attrs["rejected_provider_bars"],1)
        rejected=frame.attrs["rejected_provider_rows"]
        self.assertEqual(len(rejected),1)
        self.assertIn("impossible_high",rejected.iloc[0]["reason"])
        self.assertEqual(int(rejected.iloc[0]["high"]),98)

    def test_mixed_bad_provider_bars_are_quarantined_without_synthetic_prices(self):
        inst=Instrument("BANDHANBNK","2263")
        payload=response(2)
        payload["open"]=[0,110]
        good=candles_to_frame(payload,inst)
        self.assertEqual(len(good),1)
        self.assertEqual(float(good.iloc[0]["open"]),110)
        self.assertEqual(good.attrs["rejected_provider_bars"],1)
        self.assertEqual(good.attrs["total_provider_bars"],2)
        self.assertEqual(float(good.iloc[0]["volume"]),2000)

    def test_all_invalid_provider_bars_still_fail_clearly(self):
        inst=Instrument("BANKBARODA","4668")
        payload=response(2)
        payload["open"]=[0,0]
        with self.assertRaisesRegex(ValueError,"no valid OHLCV bars"):
            candles_to_frame(payload,inst)

    def test_negative_volume_and_impossible_high_are_quarantined(self):
        inst=Instrument("CANBK","10794")
        payload=response(2)
        payload["volume"]=[-1,2000]
        result=candles_to_frame(payload,inst)
        self.assertEqual(len(result),1)
        self.assertEqual(result.attrs["rejected_provider_bars"],1)
        payload=response(2)
        payload["high"]=[99,120]
        result=candles_to_frame(payload,inst)
        self.assertEqual(len(result),1)
        self.assertEqual(result.attrs["rejected_provider_bars"],1)

    def test_zero_volume_with_valid_ohlc_is_accepted(self):
        payload=response(2)
        payload["volume"]=[0,2000]
        result=candles_to_frame(payload,Instrument("FEDERALBNK","1023"))
        self.assertEqual(len(result),2)
        self.assertEqual(result.attrs["rejected_provider_bars"],0)

    def test_chunk_download_reports_rejected_source_rows(self):
        payload=response(2)
        payload["open"]=[0,110]
        def mock_post(endpoint,request,token):
            return payload
        result=download_candles(Instrument("BANKBARODA","4668"),
            "2024-01-01","2024-02-01",token="TEST",post=mock_post,
            pause_seconds=0)
        self.assertEqual(len(result),1)
        self.assertEqual(result.attrs["rejected_provider_bars"],1)

    def test_mock_download_contains_no_secrets(self):
        seen=[]
        def fake_post(endpoint,payload,token):
            seen.append((endpoint,payload,token))
            return response(2)
        instrument=Instrument("A","1333")
        # timezone-verified test range covers both example timestamps.
        frame=download_candles(instrument,"2024-01-01","2024-02-01",
                               token="SECRET_TEST_TOKEN",post=fake_post,pause_seconds=0)
        self.assertEqual(len(frame),2)
        self.assertEqual(seen[0][0],"/charts/historical")
        self.assertEqual(seen[0][1]["securityId"],"1333")
        self.assertEqual(seen[0][1]["toDate"],"2024-02-01")
        with tempfile.TemporaryDirectory() as temp:
            csv_path,manifest=save_download(frame,instrument,temp,
                                            "2024-01-01","2024-02-01",None)
            self.assertTrue(csv_path.exists())
            self.assertNotIn("SECRET_TEST_TOKEN",manifest.read_text())
            self.assertNotIn("SECRET_TEST_TOKEN",csv_path.read_text())

    def test_monthly_requires_no_fabricated_benchmark(self):
        a=Instrument("A","1333")
        b=Instrument("B","1444")
        with tempfile.TemporaryDirectory() as tmp:
            raw=Path(tmp)/"raw"
            raw.mkdir()
            for ins in [a,b]:
                frame=candles_to_frame(response(2),ins)
                save_download(frame,ins,raw,"2024-01-01","2024-02-01",None)
            folder=Path(tmp)/"monthly"
            path=build_monthly_close(raw,[a,b],folder)
            self.assertTrue(path.exists())
            self.assertFalse((folder/"benchmark.csv").exists())
            self.assertFalse((folder/"membership.csv").exists())
            self.assertTrue((folder/"DHAN_UNADJUSTED_DATA_WARNING.txt").exists())
            values=pd.read_csv(path)
            self.assertEqual(list(values.columns),["date","A","B"])

    def test_instruments_from_local_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"instruments.csv"
            p.write_text("label,security_id,exchange_segment,instrument,expiry_code\nA,1333,NSE_EQ,EQUITY,0\n")
            instruments=read_instruments(p)
            self.assertEqual(instruments[0].security_id,"1333")
            self.assertEqual(instruments[0].exchange_segment,"NSE_EQ")

    def test_identical_duplicate_timestamp_is_quarantined_and_audited(self):
        values=response(2)
        values["timestamp"][1]=values["timestamp"][0]
        for key in ("open","high","low","close","volume"):
            values[key][1]=values[key][0]
        frame=candles_to_frame(values,Instrument("CANBK","10794"))
        self.assertEqual(len(frame),1)
        self.assertEqual(frame.iloc[0]["close"],105)
        self.assertEqual(frame.attrs["rejected_provider_bars"],1)
        self.assertEqual(frame.attrs["total_provider_bars"],2)
        reject=frame.attrs["rejected_provider_rows"]
        self.assertEqual(len(reject),1)
        self.assertEqual(reject.iloc[0]["provider_timestamp"],values["timestamp"][0])
        self.assertEqual(reject.iloc[0]["reason"],"identical_provider_timestamp_duplicate")

    def test_missing_timestamp_is_quarantined_without_inferred_date(self):
        values=response(2)
        values["timestamp"][1]=None
        frame=candles_to_frame(values,Instrument("CANBK","10794"))
        self.assertEqual(len(frame),1)
        self.assertEqual(frame.attrs["rejected_provider_bars"],1)
        self.assertEqual(frame.attrs["rejected_provider_rows"].iloc[0]["reason"],
                         "missing_or_invalid_provider_timestamp")
        values["timestamp"]=[None,None]
        with self.assertRaisesRegex(ValueError,"no timestamp-valid"):
            candles_to_frame(values,Instrument("CANBK","10794"))

    def test_duplicate_timestamp_with_conflicting_ohlcv_fails_closed(self):
        values=response(2)
        values["timestamp"][1]=values["timestamp"][0]
        with self.assertRaisesRegex(ValueError,"conflicting OHLCV"):
            candles_to_frame(values,Instrument("CANBK","10794"))

    def test_download_retains_exact_duplicate_audit_counts(self):
        raw=response(2)
        raw["timestamp"][1]=raw["timestamp"][0]
        for key in ("open","high","low","close","volume"):
            raw[key][1]=raw[key][0]
        frame=download_candles(
            Instrument("CANBK","10794"),
            "2024-01-01","2024-02-01",token="TEST",post=lambda *_:raw,
            pause_seconds=0)
        self.assertEqual(len(frame),1)
        self.assertEqual(frame.attrs["rejected_provider_bars"],1)
        self.assertEqual(len(frame.attrs["rejected_provider_rows"]),1)


    def test_equal_size_daily_chunks_preserve_rejects_without_attrs_comparison(self):
        def fake_post(endpoint, request, token):
            first=pd.Timestamp(request["fromDate"],tz="Asia/Kolkata")
            raw=response(2)
            raw["timestamp"]=[int((first+pd.Timedelta(days=i)).timestamp()) for i in (1,2)]
            raw["open"][0]=0
            return raw
        result=download_candles(Instrument("A","1333"),"2024-01-01","2025-02-01",
                                token="TEST",post=fake_post,pause_seconds=0)
        self.assertEqual(len(result),2)
        self.assertEqual(result.attrs["total_provider_bars"],4)
        self.assertEqual(result.attrs["rejected_provider_bars"],2)
        self.assertEqual(len(result.attrs["rejected_provider_rows"]),2)
        self.assertFalse(result.datetime.duplicated().any())



if __name__=="__main__":
    unittest.main()
