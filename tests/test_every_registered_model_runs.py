"""Prove every registered numerical model executes with valid offline inputs.

Fixtures are synthetic by construction, NEVER historical NSE evidence.
No web, token, trading, or vendor calls. A catalog 'implemented' badge must
not be supported only by a hypothetical software plan.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

import numpy as np
import pandas as pd

from workstation_api import model_lab, model_registry, option_quotes, service


class EveryModelDispatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=TemporaryDirectory(prefix="quantlab_full_catalog_")
        cls.root=Path(cls.tmp.name)
        cls.folder=cls.root/"synthetic_fixture"
        cls.folder.mkdir(parents=True)
        rng=np.random.default_rng(7004)
        dates=pd.bdate_range("2024-10-01",periods=420)
        names=[f"TEST{i:02d}" for i in range(8)]
        base=rng.normal(.0004,.006,size=(len(dates),1))
        noise=rng.normal(0,.008,size=(len(dates),len(names)))
        prices=pd.DataFrame(100*np.exp(np.cumsum(base+noise,axis=0)),
                            index=dates,columns=names)
        prices.to_csv(cls.folder/"daily_prices.csv",index_label="date")
        prices.resample("ME").last().to_csv(cls.folder/"prices.csv",index_label="date")
        cls.dataset={
            "id":"catalog_offline_fixture","label":"SYNTHETIC TEST FIXTURE ONLY",
            "kind":"synthetic","has_daily_prices":True,"has_prices":True,
            "basis":"Generated random prices; cannot be cited as NSE history.",
            "benchmark_kind":"not_applicable",
        }
        cls.patch_data=patch.object(service,"DATA",cls.root/"app_data")
        cls.patch_path=patch.object(service,"dataset_path",
                                    return_value=(cls.folder,cls.dataset))
        cls.patch_data.start()
        cls.patch_path.start()
        captured=datetime.now(timezone.utc)-timedelta(hours=1)
        expiry=captured+timedelta(days=182)
        raw=("captured_at,provider,underlying,underlying_spot,expiry_at,strike,"
             "option_type,bid,ask\n"+
             f"{captured.isoformat()},TEST_PROVIDER,TEST00,100,"
             f"{expiry.isoformat()},100,call,8.00,10.00\n").encode()
        cls.quote=option_quotes.import_quotes(cls.dataset["id"],raw)["id"]+":0"

    @classmethod
    def tearDownClass(cls):
        cls.patch_path.stop()
        cls.patch_data.stop()
        cls.tmp.cleanup()

    def test_entire_model_registry_returns_real_numerical_output(self):
        outcomes=[]
        for spec in model_registry.MODELS:
            name=spec["id"]
            params={}
            if spec["mode"]=="market":
                params={"quote":self.quote}
            if name in {"gbm_fit","ou_fit","merton_fit","heston_proxy"}:
                params={"target":"stock","ticker":"TEST00","paths":40,"steps":25}
            if spec["mode"]=="synthetic":
                allowed={x["key"] for x in spec["parameters"]}
                params={key:value for key,value in {"steps":25,"paths":40}.items()
                        if key in allowed}
            if spec["mode"]=="theoretical" and "steps" in {
                    x["key"] for x in spec["parameters"]}:
                params={"steps":40}
            try:
                out=model_lab.run_model(
                    name,None if spec["mode"] in {"synthetic","theoretical"}
                    else self.dataset["id"],params)
                self.assertEqual(out["model_id"],name)
                self.assertEqual(out["mode"],spec["mode"])
                self.assertTrue(out["metrics"] or out["plots"] or out["table"],
                                "No computed output generated")
                if spec["mode"] in {"historical","market"}:
                    self.assertIsNotNone(out["source"])
                    self.assertFalse(out["source"].get("source_independently_certified",False))
                else:
                    self.assertIsNone(out["source"])
                outcomes.append(name)
            except Exception as exc:
                self.fail(f"Advertised implemented model {name} did not execute: {exc}")
        self.assertEqual(set(outcomes),set(model_registry.CATALOG))
        self.assertGreaterEqual(len(outcomes),30)


if __name__=="__main__":
    unittest.main()
