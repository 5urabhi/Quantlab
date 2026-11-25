import unittest
import struct
from datetime import datetime,timezone
from unittest.mock import patch
from workstation_api import shared_index_feed as shared,full_option_feed as feed


class SharedIndexTests(unittest.TestCase):
    def test_spare_capacity_does_not_displace_options(self):
        message,ids=shared.subscriptions(4998)
        self.assertEqual(message["RequestCode"],15)
        self.assertEqual(message["InstrumentCount"],2)
        self.assertEqual(ids,["INDEX:BANKNIFTY","INDEX:NIFTY50"])
        self.assertEqual(shared.subscriptions(4999)[1],["INDEX:BANKNIFTY"])
        self.assertEqual(shared.subscriptions(5000),(None,[]))

    def test_decode_only_documented_ticker_and_keep_legacy_option_parser(self):
        stamp=datetime(2026,11,25,4,30,tzinfo=timezone.utc)
        ticker=struct.pack("<BHBI fI",2,16,0,25,63000.,int(stamp.timestamp()))
        unsupported=struct.pack("<BHBI fI",1,16,0,25,99999.,int(stamp.timestamp()))
        self.assertEqual(feed.decode_quote_frames(ticker+unsupported),[])
        result=feed.decode_quote_frames(ticker+unsupported,include_index=True)
        self.assertEqual(result[0]["identity"],"INDEX:BANKNIFTY")
        self.assertEqual(result[0]["packet"]["price"],63000.)
        self.assertEqual(result[1],{"kind":"index_unsupported","identity":"INDEX:BANKNIFTY"})

    def test_only_persisted_current_session_ticker_is_fresh(self):
        capture=shared.IndexCapture()
        now=datetime(2026,11,25,4,30,tzinfo=timezone.utc)
        event={"kind":"index_tick","identity":"INDEX:BANKNIFTY","packet":{"price":63000,"exchange_utc":now.isoformat()}}
        capture.begin("session",["INDEX:BANKNIFTY"])
        capture.submit(event,now,"wrong-session")
        self.assertEqual(capture.queue.qsize(),0)
        capture.submit(event,now,"session")
        with patch.object(shared.live_market,"ingest_tick",return_value=True):
            capture.write_one(capture.queue.get_nowait())
        self.assertTrue(capture.status(now)["quotes"]["INDEX:BANKNIFTY"]["fresh"])
        capture.end("session")
        self.assertFalse(capture.status(now)["quotes"]["INDEX:BANKNIFTY"]["fresh"])
