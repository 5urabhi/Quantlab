import tempfile
import unittest
from pathlib import Path
from workstation_api import nse_source_automation as nse

class SavedReceiptTests(unittest.TestCase):
    def test_persisted_metadata_and_redacted_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            incoming = root / "weights.csv"
            incoming.write_text("symbol,weight\nTEST,1\n")
            store = root / "intake"
            made = nse.intake_local_exports([incoming], root=store)
            result = nse.saved_intake_receipts(root=store)
            self.assertFalse(result["partial"])
            row = result["receipts"][0]
            self.assertEqual(row["id"], made["id"])
            self.assertEqual(row["files"][0]["original_sha256"], made["files"][0]["original_sha256"])
            self.assertFalse(row["source_verified_by_nse"])
            self.assertNotIn("directory", row)
            self.assertNotIn(str(root), str(row))
            (store / "intake_0000000000000000").mkdir()
            result = nse.saved_intake_receipts(root=store)
            self.assertTrue(result["partial"])
            self.assertEqual(result["unreadable"], 1)
    def test_missing_and_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/"missing"
            self.assertEqual(nse.saved_intake_receipts(root=root)["receipts"], [])
            self.assertFalse(root.exists())
            with self.assertRaises(ValueError):
                nse.saved_intake_receipts(201, root=root)
