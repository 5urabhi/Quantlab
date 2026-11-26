from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import sleep
from unittest import TestCase
from unittest.mock import Mock, patch
import sqlite3

from workstation_api import shared_market_data, replay_storage, advanced_options
from workstation_api import app as api


class ReplayStorageTests(TestCase):
    def test_wal_snapshot_does_not_block_recorder_commit(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/"shared_market.sqlite3"
            with closing(sqlite3.connect(path)) as db:
                db.execute("CREATE TABLE receipts(id INTEGER PRIMARY KEY)")
                db.execute("INSERT INTO receipts VALUES (1)")
                db.commit()
            with patch.object(shared_market_data,"database_path",return_value=path):
                self.assertEqual(shared_market_data.configure_concurrency()["journal_mode"],"wal")
                self.assertEqual(replay_storage.journal_mode(),"wal")
                with closing(advanced_options._read_database()) as reader:
                    reader.execute("BEGIN")
                    self.assertEqual(replay_storage.fetchone(reader,"SELECT COUNT(*) FROM receipts"),(1,))
                    with closing(sqlite3.connect(path,timeout=.2)) as writer:
                        writer.execute("INSERT INTO receipts VALUES (2)")
                        writer.commit()
                    self.assertEqual(replay_storage.fetchone(reader,"SELECT COUNT(*) FROM receipts"),(1,))
                    reader.rollback()
                    self.assertEqual(replay_storage.fetchone(reader,"SELECT COUNT(*) FROM receipts"),(2,))
                    with self.assertRaises(sqlite3.OperationalError):
                        reader.execute("INSERT INTO receipts VALUES (3)")

    def test_locked_query_retries_and_never_returns_missing(self):
        db=Mock()
        cursor=Mock();cursor.fetchone.return_value=("original receipt",)
        db.execute.side_effect=[sqlite3.OperationalError("database is locked"),cursor]
        with patch.object(replay_storage,"sleep"):
            self.assertEqual(replay_storage.fetchone(db,"SELECT 1"),("original receipt",))
        self.assertEqual(db.execute.call_count,2)
        cursor.close.assert_called_once()
        db.execute.reset_mock()
        db.execute.side_effect=sqlite3.OperationalError("database is locked")
        with patch.object(replay_storage,"sleep"):
            with self.assertRaisesRegex(RuntimeError,"without scoring lock failures"):
                replay_storage.fetchone(db,"SELECT 1")
        self.assertEqual(db.execute.call_count,replay_storage.ATTEMPTS)

    def test_non_lock_errors_not_retried(self):
        db=Mock()
        db.execute.side_effect=sqlite3.OperationalError("no such table: receipts")
        with self.assertRaisesRegex(sqlite3.OperationalError,"no such table"):
            replay_storage.fetchone(db,"SELECT 1")
        self.assertEqual(db.execute.call_count,1)

    def test_metadata_lock_does_not_abort_replay_job(self):
        with patch.object(api.research_library,"store_job",side_effect=sqlite3.OperationalError("database is locked")):
            api._persist_job({"id":"fixture","status":"running","stage":"Testing"})
