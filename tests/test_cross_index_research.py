"""Cross-index research source identity and causal alignment regression."""
from datetime import date,timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from workstation_api import cross_index_research as c, index_spot, service
from workstation_api import cpr_regime_research as g
from test_cpr_regime_utility import bars


class CrossIndexTests(TestCase):
    def test_extra_index_identity_not_guessed(self):
        with TemporaryDirectory() as root,patch.object(service,"DATA",Path(root)):
            folder=Path(root)/"dhan";folder.mkdir()
            path=folder/"instrument_master.csv"
            path.write_text("SEGMENT,INSTRUMENT,SECURITY_ID,TRADING_SYMBOL\nE,EQUITY,100,NIFTY 100\nI,INDEX,88,NIFTY 50\n")
            self.assertEqual(index_spot.resolve_with_evidence("INDEX:NIFTY100"),(None,"no_unique_master_index_match"))
            with path.open("a") as f:f.write("I,INDEX,99,NIFTY 100\n")
            inst,source=index_spot.resolve_with_evidence("INDEX:NIFTY100")
            self.assertEqual(inst.security_id,"99")
            self.assertEqual(inst.label,"NIFTY100_INDEX")
            self.assertEqual(source,"verified_unique_dhan_scrip_master_match")
            with path.open("a") as f:f.write("I,INDEX,101,NIFTY 100\n")
            self.assertEqual(index_spot.resolve_with_evidence("INDEX:NIFTY100"),(None,"conflicting_index_sids_in_dhan_master"))

    def test_peer_future_invariance_and_no_forward_fill(self):
        day="2026-08-03"
        target={day:bars(75,0)}
        peer={day:bars(75,20)}
        split=([day],[],[])
        _,before,_=c._rows(target,peer,split,5)
        first=before[0][0]
        peer[day][35]=(60000.,90000.,59999.,90000.,100.)
        _,after,_=c._rows(target,peer,split,5)
        self.assertEqual(after[0][0]["peer_features"],first["peer_features"])
        self.assertEqual(after[0][0]["labels"],first["labels"])
        del peer[day][20]
        all_rows,matched,cov=c._rows(target,peer,split,5)
        self.assertGreater(len(all_rows[0]),len(matched[0]))
        self.assertNotIn(34,[r["minute"] for r in matched[0]])
        self.assertEqual(cov["train"]["matched_scored"],len(matched[0]))

    def test_both_targets_matched_and_separate_direction_task(self):
        days=[];d=date(2026,8,3)
        while len(days)<27:
            if d.weekday()<5:days.append(d.isoformat())
            d+=timedelta(days=1)
        series={"INDEX:BANKNIFTY":{d:bars(75,i) for i,d in enumerate(days)},
                "INDEX:NIFTY50":{d:bars(75,i+20) for i,d in enumerate(days)}}
        splits=(days[:20],days[20:25],days[25:])
        actual=g.RandomForestClassifier
        def fast(**kw):return actual(**{**kw,"n_estimators":3})
        with patch.object(c,"HORIZONS",(5,)),patch.object(g,"RandomForestClassifier",side_effect=fast):
            report=c.assess(series,splits)
        for target,part in report["targets"].items():
            self.assertNotEqual(target,part["peer"])
            item=part["horizons"]["5"]
            self.assertEqual(item["matched_baseline"]["coverage"],item["matched_augmented"]["coverage"])
            self.assertIn("terminal_direction",item["comparisons"])
        with self.assertRaisesRegex(ValueError,"chronological"):
            c.assess(series,(days[20:25],days[:20],days[25:]))
