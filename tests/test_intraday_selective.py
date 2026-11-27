from datetime import date,timedelta
from unittest import TestCase
from scripts import benchmark_intraday_selective as b


def bar(p,v=100.):
    return (p,p,p,p,v)


class IntradaySelectiveTests(TestCase):
    def test_completed_features_and_delayed_entry(self):
        bars={k:bar(100+k*.1) for k in range(100)}
        row,error=b.sample_index(bars,15,15)
        self.assertIsNone(error)
        self.assertEqual((row["entry_minute"],row["exit_minute"]),(16,31))
        changed=dict(bars)
        changed[15]=bar(999)
        changed[16]=bar(105)
        changed[31]=bar(110)
        other,_=b.sample_index(changed,15,15)
        self.assertEqual(row["index"],other["index"])
        self.assertNotEqual(row["return_bps"],other["return_bps"])
        del changed[16]
        self.assertEqual(b.sample_index(changed,15,15)[1],"missing_later_entry_or_exit")

    def test_member_volume_uses_prior_dates_only(self):
        day="2026-09-10"
        dates=[str(date(2026,9,1)+timedelta(days=i)) for i in range(6)]
        stocks={"A":{d:{k:bar(100+k,100.) for k in range(5)} for d in dates}}
        stocks["A"][day]={k:bar(100+k,200.) for k in range(5)}
        x=b.member_features(day,5,stocks,["A"],dates)
        self.assertAlmostEqual(x[3],2.)
        self.assertEqual(x[4],0.)
        self.assertIsNone(b.member_features(day,5,stocks,["A","B"],dates))
        self.assertEqual(b.member_features(day,5,stocks,["A"],dates[:2])[-1],1.)

    def test_selective_cost_and_abstention(self):
        records=[{"p_up":.7,"action":1,"return_bps":10.},
                 {"p_up":.51,"action":0,"return_bps":-100.},
                 {"p_up":.2,"action":-1,"return_bps":-3.}]
        m=b.metrics(records,reserved=4)
        self.assertEqual(m["trades"],2)
        self.assertAlmostEqual(m["net_bps_per_trade"]["5"],1.5)
        self.assertAlmostEqual(m["net_bps_per_scored_opportunity"]["5"],1.)
        self.assertAlmostEqual(m["win_rate_after_5bps"],.5)
        self.assertIsNone(b.metrics([{"p_up":.5,"action":0,"return_bps":1.}],reserved=1)["net_bps_per_trade"]["5"])

    def test_paired_cohort_and_chronological_predictions(self):
        dates=[str(date(2026,1,1)+timedelta(days=i)) for i in range(100)]
        rows={}
        for i,d in enumerate(dates):
            sign=(-1)**i
            rows[d]={"date":d,"index":[float(sign)],"members":[float(sign)] if i%5 else None,
                     "momentum":sign,"return_bps":20.*sign}
        x=b.evaluate(dates,rows,matched=True)
        expected=[d for i,d in enumerate(dates) if i>=b.INITIAL and i%5]
        for records in x["predictions"].values():
            self.assertEqual([r["date"] for r in records],expected)
        self.assertEqual(x["state"],"exploratory_comparison")
        self.assertEqual(b.evaluate(dates,{},matched=True)["state"],"insufficient_held_out_dates")
        for r in x["predictions"]["index_selective"]:
            self.assertEqual(bool(r["action"]),max(r["p_up"],1-r["p_up"])>=b.CONFIDENCE)
