import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch
from workstation_api import user_notebooks as notebooks,user_scripts as scripts


class NotebookTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.patch=patch.object(scripts,"_db_path",lambda:Path(self.temp.name)/"library.sqlite3")
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_revision_and_run_prefix(self):
        cells=[{"kind":"markdown","source":"# Example"},{"kind":"code","source":"x=2"},{"kind":"code","source":"x+3"}]
        one=notebooks.save_notebook(title="Study",cells=cells)
        two=notebooks.save_notebook(title="Study 2",cells=cells,notebook_id=one["id"],expected_revision=1)
        self.assertEqual(two["revision"],2)
        self.assertEqual(notebooks.read_notebook(one["id"],1)["title"],"Study")
        with self.assertRaisesRegex(ValueError,"changed elsewhere"):
            notebooks.save_notebook(title="Old",cells=cells,notebook_id=one["id"],expected_revision=1)
        output={"outputs":[{"index":1,"text":"ok","charts":[],"error":None}]}
        with patch.object(scripts,"isolated_json",return_value=output) as runner:
            run=notebooks.run_notebook(notebook_id=one["id"],revision=1,through=1)
        self.assertEqual(run["outputs"][0]["index"],1)
        self.assertEqual(notebooks.read_run(one["id"],run["id"]),run)
        self.assertEqual(notebooks.read_notebook(one["id"])["runs"][0]["revision"],1)
        self.assertIn(b'x=2',runner.call_args.args[1]["notebook.json"])
        self.assertNotIn(b'x+3',runner.call_args.args[1]["notebook.json"])

    def test_validation_and_fail_closed(self):
        with self.assertRaises(ValueError):
            notebooks.save_notebook(title="Bad",cells=[{"kind":"code","source":"def :"}])
        cells=[{"kind":"code","source":"print(1)"}]
        doc=notebooks.save_notebook(title="Test",cells=cells)
        with patch.object(scripts,"isolated_json",side_effect=ValueError("sandbox unavailable")):
            with self.assertRaisesRegex(ValueError,"unavailable"):
                notebooks.run_notebook(notebook_id=doc["id"],revision=1)
        with self.assertRaises(ValueError):
            notebooks.validate_results({"outputs":[{"index":0,"text":"","charts":[{"title":"bad","x":[1],"traces":[]}]}]},cells)
        with self.assertRaises(ValueError):
            notebooks.validate_results({"outputs":[]},cells)

    def test_cell_chart_and_error(self):
        cells=[{"kind":"code","source":"pass"},{"kind":"code","source":"pass"}]
        output={"outputs":[{"index":0,"text":"value","error":"ValueError: example","charts":[{"title":"Result","x_label":"x","y_label":"y","x":[1,2],"traces":[{"name":"a","y":[2,None]}]}]}]}
        actual=notebooks.validate_results(output,cells)
        self.assertEqual(actual[0]["charts"][0]["kind"],"line2d")
        self.assertEqual(actual[0]["charts"][0]["traces"][0]["y"],[2,None])
