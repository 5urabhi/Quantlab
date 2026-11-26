"""Regression coverage for the recovered legacy safety workspaces, using temporary files only."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import json
import sqlite3
import pandas as pd
from workstation_api import metadata_backup as backup, execution_stress as stress, service

class ReconciledLegacyTests(TestCase):
    def setUp(self):
        temp=TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        for name,path in (("DATA",self.root/"data"),("RESULTS",self.root/"results")):
            p=patch.object(service,name,path)
            p.start()
            self.addCleanup(p.stop)

    def test_metadata_backup_scope_consent_integrity_and_original_preservation(self):
        p=service.DATA/"research_workspace"/"library.sqlite3"
        p.parent.mkdir(parents=True)
        with sqlite3.connect(p) as db:
            db.execute("CREATE TABLE records(title TEXT)")
            db.execute("INSERT INTO records VALUES ('original fixture')")
        market=service.DATA/"dhan"/"shared_market.sqlite3"
        market.parent.mkdir()
        market.write_bytes(b"synthetic market fixture outside backup scope")
        self.assertTrue(backup.preview()["can_create"])
        self.assertFalse(backup._root().exists())
        self.assertEqual(backup.list_snapshots()["snapshots"],[])
        self.assertFalse(backup._root().exists())
        with self.assertRaises(ValueError):
            backup.create()
        with patch.object(backup.shutil,"disk_usage",return_value=type("Usage",(),{"free":10**10})()):
            receipt=backup.create(confirm_authorized=True)
        self.assertFalse(receipt["cross_database_atomic"])
        self.assertFalse(receipt["source_market_data_included"])
        self.assertEqual([r["database"] for r in receipt["files"]],["research_library"])
        self.assertTrue(backup.verify(receipt["id"])["verified"])
        self.assertEqual(len(backup.list_snapshots()["snapshots"]),1)
        target=backup._root()/receipt["id"]/"research_library.sqlite3"
        with sqlite3.connect(target) as db:
            self.assertEqual(db.execute("SELECT title FROM records").fetchone()[0],"original fixture")
            db.execute("UPDATE records SET title='tampered'")
        with self.assertRaises(ValueError):
            backup.verify(receipt["id"])
        with sqlite3.connect(p) as db:
            self.assertEqual(db.execute("SELECT title FROM records").fetchone()[0],"original fixture")
        self.assertEqual(market.read_bytes(),b"synthetic market fixture outside backup scope")

    def test_stress_zero_preserves_original_and_extra_cost_reduces_wealth(self):
        folder=service.RESULTS/"fixture"
        folder.mkdir(parents=True)
        gross=[.10,-.05,.04]
        costs=[.001,.002,.001]
        frame=pd.DataFrame({"date":["2026-01-31","2026-02-28","2026-03-31"],"strategy_gross":gross,
             "strategy_net":[(1-c)*(1+g)-1 for g,c in zip(gross,costs)],
             "benchmark":[.01,.02,.01],"turnover":[.5,.9,.3],"transaction_cost_fraction":costs})
        frame.to_csv(folder/"monthly_results.csv",index=False)
        (folder/"research_manifest.json").write_text(json.dumps({"input_sha256":{"prices.csv":"a"*64}}))
        (folder/"workstation_run.json").write_text(json.dumps({"dataset_kind":"synthetic","dataset_id":"fixture"}))
        before=(folder/"monthly_results.csv").read_bytes()
        zero=stress.calculate("fixture",extra_fee_bps=0,extra_half_spread_bps=0,impact_coefficient_bps=0)
        self.assertAlmostEqual(zero["metrics"]["incremental_compounded_return_drag"],0)
        extra=stress.calculate("fixture",extra_fee_bps=20)
        self.assertLess(extra["metrics"]["incremental_compounded_return_drag"],0)
        self.assertEqual(extra["evidence_class"],"synthetic_fixture")
        self.assertEqual((folder/"monthly_results.csv").read_bytes(),before)
        with self.assertRaises(ValueError):
            stress.calculate("fixture",assumed_participation=.5)
        frame.loc[0,"strategy_net"]=.8
        frame.to_csv(folder/"monthly_results.csv",index=False)
        with self.assertRaisesRegex(ValueError,"reconcile"):
            stress.calculate("fixture")
