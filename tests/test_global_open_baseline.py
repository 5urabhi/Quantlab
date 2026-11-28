from datetime import date,timedelta
from unittest import TestCase
from scripts import benchmark_global_open as b


def bar(price):
    return (price,price,price,price,100.)


class OpeningBaselineTests(TestCase):
    def test_exact_anchors_and_no_current_bar_features(self):
        prev={0:bar(100),344:bar(101),374:bar(102)}
        current={i:bar(103+i) for i in range(30)}
        x,y=b.index_sample(prev,current)
        other={i:bar(110+i) for i in range(30)}
        self.assertEqual(x,b.index_sample(prev,other)[0])
        self.assertAlmostEqual(y["gap"],b.bps(103,102))
        self.assertAlmostEqual(y["first15"],b.bps(117,103))
        self.assertAlmostEqual(y["first30"],b.bps(132,103))
        del current[14]
        self.assertIsNone(b.index_sample(prev,current))

    def test_membership_and_dated_close(self):
        day="2026-09-01"
        stocks={"HDFCBANK":{day:{0:bar(100),359:bar(101)}}}
        x=b.constituent_sample(day,stocks,["HDFCBANK"],{"HDFCBANK":"NSE_EQ:1333"})
        self.assertAlmostEqual(x[0],100)
        self.assertEqual(x[1],100)
        self.assertIsNone(b.constituent_sample(day,stocks,["HDFCBANK","SBIN"],{"HDFCBANK":"NSE_EQ:1333"}))

    def test_paired_chronology_and_gap_cost(self):
        dates=[str(date(2025,1,1)+timedelta(days=i)) for i in range(60)]
        rows={}
        for i,d in enumerate(dates):
            if i in (4,35,49):continue
            sign=1 if i%2 else -1
            rows[d]={"date":d,"domestic":[sign,0.],"global":[sign,0.],
                     "combined":[sign,0.,sign,0.],"returns":dict.fromkeys(b.TARGETS,sign*20.)}
        result=b.evaluate(dates,rows,"gap")
        self.assertEqual(result["state"],"exploratory_comparison")
        expected=[d for d in dates[30:] if d in rows]
        for key,records in result["predictions"].items():
            self.assertEqual([r["date"] for r in records],expected)
        self.assertNotIn("hypothetical_index_net_bps_per_trade_at_5bps",result["metrics"]["combined"])
        result=b.evaluate(dates,rows,"first15")
        self.assertAlmostEqual(result["metrics"]["combined"]["hypothetical_index_net_bps_per_trade_at_5bps"],15.)

    def test_insufficient_sample_not_a_pass(self):
        dates=[str(date(2025,1,1)+timedelta(days=i)) for i in range(40)]
        self.assertEqual(b.evaluate(dates,{},"gap")["state"],"insufficient_held_out_dates")
