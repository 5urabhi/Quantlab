"""Market-priority policy regression, without provider or live recorder calls."""
from datetime import datetime, timedelta, timezone
from unittest import TestCase
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO

from workstation_api import cpr_execution_evidence as e, cpr_hybrid_research as r
from workstation_api import alpha_retraining as auto
from scripts import check_cpr_context as context, run_candle_patterns as candles


class ManualMarketHoursTests(TestCase):
    def test_manual_execution_reaches_saved_source_reader(self):
        now=datetime(2026,11,27,5,tzinfo=timezone.utc)
        with patch.object(e.h,"shared_index_sources",side_effect=ValueError("saved source sentinel")) as read:
            with self.assertRaisesRegex(ValueError,"outside Indian market"):
                e.run(now=now)
            read.assert_not_called()
            with self.assertRaisesRegex(ValueError,"saved source sentinel"):
                e.run(now=now,manual_saved_research=True)
            read.assert_called_once()
        self.assertFalse(auto.safe_window(now))

    def test_manual_hybrid_keeps_completed_date_validation(self):
        today=datetime.now(r.h.IST).date()
        start=(today-timedelta(days=100)).isoformat()
        with patch.object(auto,"safe_window",return_value=False),patch.object(r.h,"shared_index_sources",side_effect=ValueError("saved source sentinel")) as read:
            with self.assertRaisesRegex(ValueError,"outside Indian market"):
                r.run(from_date=start,to_date=today.isoformat())
            with self.assertRaisesRegex(ValueError,"completed sessions"):
                r.run(from_date=start,to_date=(today+timedelta(days=1)).isoformat(),manual_saved_research=True)
            read.assert_not_called()
            with self.assertRaisesRegex(ValueError,"saved source sentinel"):
                r.run(from_date=start,to_date=today.isoformat(),manual_saved_research=True)
            read.assert_called_once()

    def test_context_read_allowed_but_provider_backfill_remains_blocked(self):
        with patch.object(auto,"safe_window",return_value=False),patch.object(context,"load_dotenv"),patch.object(context.h,"shared_index_sources",side_effect=ValueError("No usable original source")) as read,patch.object(context.archive,"backfill") as fetch:
            with patch("sys.argv",["context","--fetch-fred","--confirm-reviewed"]),redirect_stdout(StringIO()):
                self.assertEqual(context.main(),2)
            read.assert_not_called()
            fetch.assert_not_called()
            with patch("sys.argv",["context"]),redirect_stdout(StringIO()):
                self.assertEqual(context.main(),2)
            read.assert_called_once()
            fetch.assert_not_called()

    def test_candle_cli_reads_saved_sources_during_market(self):
        with patch.object(auto,"safe_window",return_value=False),patch.object(candles.h,"shared_index_sources",return_value=({}, {}, {})) as read,patch("sys.argv",["candles"]),redirect_stdout(StringIO()):
            self.assertEqual(candles.main(),2)  # no fixture data, not a time restriction
            read.assert_called_once()
