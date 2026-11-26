"""Deterministic synthetic control-flow tests; not market performance evidence."""
from datetime import date, timedelta
from unittest import TestCase
from unittest.mock import patch

from workstation_api import cpr_hybrid_research as r

DAY="2026-10-06"
PREV="2026-10-05"


def index(price):
    return {m:(price,price+1,price-1,price,1000) for m in range(375)}


def bar(price,day=DAY,side="CALL",strike=100):
    return {"session_ist":day,"side":side,"strike":strike,"expiry_flag":"MONTH",
            "expiry_code":1,"open":price,"close":price,"volume":100}


def step(minute,mark,net,terminal=False,trend=.01):
    return {"minute":minute,"elapsed":minute+1,"mark_return":mark,"drawdown":0.,
            "trend":trend,"exit_net":net,"exit_fees":70.,"exit_utc":r._stamp(DAY,minute+2),
            "terminal":terminal}


def episode(day,path,minute=0):
    return {"session":day,"minute":minute,"decision_utc":r._stamp(day,minute+1),
            "side":"CALL","strike":100,"state":"entered","planned_funding":1000.,
            "funding":1000.,"debit":1000.,"path":path,"features":[0.]*13}


class CprHybridTests(TestCase):
    def test_cpr_complete_prior_only(self):
        prev=index(100)
        prev[0]=(99,103,98,100,1)
        self.assertEqual(r._cpr(prev)[:4],(99,103,98,100))
        self.assertEqual(r._cpr(prev)[4],(103+98+100)/3)
        del prev[200]
        self.assertIsNone(r._cpr(prev))
        self.assertEqual(r._signals(DAY,index(105),PREV,prev,frame=5,hold=60,max_signals=3),
                         ([],"prior_complete_session_unavailable"))

    def test_missing_weekday_does_not_reuse_stale_cpr(self):
        self.assertEqual(r._signals(DAY,index(105),"2026-10-02",index(100),frame=5,hold=60,max_signals=3),
                         ([],"prior_complete_session_unavailable"))

    def test_signals_use_completed_bars_and_prior_session(self):
        prev=index(100); current=index(105)
        rows,status=r._signals(DAY,current,PREV,prev,frame=5,hold=60,max_signals=3)
        self.assertEqual(status,"complete_clock")
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["side"],"CALL")
        self.assertEqual(rows[0]["minute"],4)
        self.assertEqual(rows[0]["decision_utc"],r._stamp(DAY,5))
        self.assertEqual(rows[0]["entry_utc"],r._stamp(DAY,6))
        changed=dict(current)
        changed[100]=(80,81,79,80,1)
        later,_=r._signals(DAY,changed,PREV,prev,frame=5,hold=60,max_signals=3)
        self.assertEqual(rows[0],later[0])

    def test_fixed_strike_and_delayed_entry_do_not_use_future_for_selection(self):
        s={"session":DAY,"minute":4,"side":"CALL","spot":100.,
           "features":[0.]*10,"decision_utc":r._stamp(DAY,5)}
        table={r._stamp(DAY,4):{("CALL",100):bar(20),("CALL",101):bar(19,strike=101)},
               r._stamp(DAY,6):{("CALL",101):bar(19,strike=101)}}
        ep=r._episode(s,table,index(100),hold=15,lot_size=30,max_lots=1,risk_budget=4250,bps=35)
        self.assertEqual(ep["strike"],100)
        self.assertEqual(ep["state"],"missing_entry")
        table[r._stamp(DAY,6)][("CALL",100)]=bar(20)
        table[r._stamp(DAY,8)]={("CALL",100):bar(25)}
        ep=r._episode(s,table,index(100),hold=15,lot_size=30,max_lots=1,risk_budget=4250,bps=35)
        self.assertEqual(ep["strike"],100)
        self.assertEqual(ep["path"][0]["exit_utc"],r._stamp(DAY,8))
        self.assertEqual(ep["state"],"entered")
        self.assertEqual(r._exit(ep,"no_stop")["state"],"exit_censored")

    def test_realized_target_is_not_a_trigger_and_no_stop_can_lose_more(self):
        ep=episode(DAY,[step(0,-.06,-80),step(1,.12,95,True)])
        baseline=r._exit(ep,"fixed_stop")
        nostop=r._exit(ep,"no_stop")
        self.assertEqual(baseline["reason"],"stop")
        self.assertEqual(nostop["reason"],"target")
        self.assertFalse(nostop["target_realized"])
        self.assertEqual(r._label(nostop),"other")
        worse=episode(DAY,[step(0,-.06,-80),step(1,-.50,-510,True)])
        self.assertLess(r._exit(worse,"no_stop")["net"],r._exit(worse,"fixed_stop")["net"])

    def test_q_learns_exit_from_earlier_paths_and_fallback(self):
        train=[episode((date(2026,9,1)+timedelta(days=i)).isoformat(),
                       [step(0,.01,10),step(1,-.07,-90,True)]) for i in range(6)]
        q,info=r._fit_q(train)
        self.assertGreater(info["supported_states"],0)
        self.assertGreater(q[r._key(train[0]["path"][0])][0],q[r._key(train[0]["path"][0])][1])
        later=episode(DAY,[step(0,.01,8),step(1,-.07,-100,True)])
        self.assertEqual(r._exit(later,"offline_q",q)["reason"],"learned_exit")
        self.assertEqual(r._exit(later,"offline_q",{})["reason"],"stop")
        self.assertEqual(r._fit_q(train[:2])[0],{})

    def test_missing_evidence_halts_day_and_not_zero_pnl(self):
        missing=episode(DAY,[])
        missing["state"]="missing_entry"
        later=episode(DAY,[step(0,.12,120,True)],minute=100)
        result,journal=r._evaluate([missing,later],method="fixed_stop",capital=17000,risk_budget=4250)
        self.assertIsNone(result["conditional_net_inr"])
        self.assertEqual(result["unresolved_trades"],1)
        self.assertEqual(result["states"]["session_halted"],1)
        self.assertFalse(result["full_account_pnl_certified"])
        self.assertEqual(journal[1]["state"],"session_halted")

    def test_unsupported_ml_returns_no_model(self):
        model,means,info=r._fit_ml([],[])
        self.assertIsNone(model)
        self.assertEqual(means,{})
        self.assertEqual(info["training_episodes"],0)

    def test_ml_uses_train_labels_and_validation_selects_model(self):
        train=[];val=[]
        for n in range(45):
            day=(date(2026,7,1)+timedelta(days=n//2)).isoformat()
            j=n%3
            mark,net=((.12,120),(-.06,-65),(.01,10))[j]
            e=episode(day,[step(0,mark,net,True)],minute=n)
            e["features"]=[float(j)]*13
            train.append(e)
        for n in range(12):
            day=(date(2026,8,1)+timedelta(days=n//2)).isoformat()
            j=n%3
            mark,net=((.12,120),(-.06,-65),(.01,10))[j]
            e=episode(day,[step(0,mark,net,True)],minute=n)
            e["features"]=[float(j)]*13
            val.append(e)
        model,means,info=r._fit_ml(train,val)
        self.assertIsNotNone(model)
        self.assertEqual(set(info["validation_brier"]),{"logistic","random_forest"})
        self.assertEqual(set(means),set(r.CLASSES))
        self.assertEqual(r._holdout_ml(model,val)["scored"],12)
