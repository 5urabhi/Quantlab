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

    def test_learning_budget_is_independent_and_source_states_are_distinct(self):
        s={"session":DAY,"minute":4,"side":"CALL","spot":100.,
           "features":[0.]*11,"decision_utc":r._stamp(DAY,5)}
        kwargs=dict(hold=15,lot_size=30,max_lots=1,risk_budget=4250,bps=35)
        self.assertEqual(r._episode(s,{},index(100),**kwargs)["state"],"missing_signal_quotes")
        table={r._stamp(DAY,4):{("CALL",110):bar(200,strike=110)}}
        self.assertEqual(r._episode(s,table,index(100),**kwargs)["state"],"no_qualified_observed_contract")
        table[r._stamp(DAY,4)][("CALL",100)]=bar(200)
        table[r._stamp(DAY,6)]={("CALL",100):bar(200)}
        self.assertEqual(r._episode(s,table,index(100),**kwargs)["state"],"no_affordable_observed_contract")
        learning=r._learning_episodes([s],table,{DAY:index(100)},hold=15,lot_size=30,bps=35)
        self.assertEqual(len(learning),1)
        self.assertEqual(learning[0]["state"],"entered")
        funded=r._episode(s,table,index(100),**{**kwargs,"risk_budget":12000})
        self.assertEqual(learning[0]["features"],funded["features"])
        self.assertGreater(learning[0]["funding"],4250)

    def test_missing_counterfactual_exit_does_not_prevent_holding(self):
        ep=episode(DAY,[step(0,.01,None),step(1,.12,120,True)])
        self.assertFalse(r._full_path(ep))
        self.assertEqual(r._exit(ep,"fixed_stop")["net"],120)
        ep["path"][0]["mark_return"]=-.06
        self.assertEqual(r._exit(ep,"fixed_stop")["state"],"exit_censored")

    def test_wider_stop_compares_recovery_but_retains_emergency_exit(self):
        ep=episode(DAY,[step(0,-.08,-80),step(1,.12,120,True)])
        self.assertEqual(r._exit(ep,"fixed_stop")["net"],-80)
        self.assertEqual(r._exit(ep,"fixed_stop",stop_mark=r.EMERGENCY_STOP)["net"],120)
        ep["path"][0]["mark_return"]=-.17
        self.assertEqual(r._exit(ep,"offline_q",{},stop_mark=r.EMERGENCY_STOP)["reason"],"stop")

    def test_correlated_strikes_do_not_create_independent_q_support(self):
        rows=[]
        for n in range(12):
            ep=episode(DAY,[step(0,.01,10),step(1,-.07,-90,True)])
            ep["strike"]=100+n
            rows.append(ep)
        self.assertEqual(r._fit_q(rows)[0],{})
        self.assertAlmostEqual(sum(r._anchor_weights([(e, {}) for e in rows])),1.)

    def test_training_grid_is_fixed_and_does_not_change_crossover_baseline(self):
        prev=index(100);current=index(105)
        base,_=r._signals(DAY,current,PREV,prev,frame=5,hold=60,max_signals=3)
        grid,_=r._signals(DAY,current,PREV,prev,frame=5,hold=60,max_signals=5,learning_grid=True)
        self.assertEqual(len(base),1)
        self.assertGreater(len(grid),1)
        self.assertTrue(all(x["entry_type"]=="scheduled_continuation" for x in grid))
        self.assertTrue(all(b["minute"]-a["minute"]>=63 for a,b in zip(grid,grid[1:])))

    def test_trailing_activates_and_ratchets_only_on_observed_marks(self):
        ep=episode(DAY,[step(0,.02,20),step(1,.005,5),step(2,.04,40),
                        step(3,.08,80),step(4,.06,60),step(5,.049,35),
                        step(6,.12,120,True)])
        result=r._exit(ep,"trailing")
        self.assertEqual(result["reason"],"trailing_stop")
        self.assertAlmostEqual(result["trailing_floor_return"],.05)
        self.assertEqual(result["net"],35)
        self.assertAlmostEqual(result["max_observed_mark_return"],.08)
        self.assertEqual(r._exit(ep,"fixed_stop")["reason"],"target")

    def test_trailing_preserves_initial_stop_and_target(self):
        early_loss=episode(DAY,[step(0,-.06,-65),step(1,.12,120,True)])
        self.assertEqual(r._exit(early_loss,"trailing")["reason"],"stop")
        self.assertEqual(r._exit(early_loss,"trailing",stop_mark=r.EMERGENCY_STOP)["reason"],"target")
        target=episode(DAY,[step(0,.04,40),step(1,.11,105,True)])
        self.assertEqual(r._exit(target,"trailing")["reason"],"target")

    def test_trailing_missing_fill_is_censored(self):
        ep=episode(DAY,[step(0,.06,60),step(1,.02,None),step(2,.12,120,True)])
        result=r._exit(ep,"trailing")
        self.assertEqual(result["state"],"exit_censored")
        self.assertEqual(result["trigger"],"trailing_stop")
        self.assertAlmostEqual(result["max_observed_peak_to_mark_drawdown"],.04)

    def test_report_open_loss_despite_profitable_close(self):
        ep=episode(DAY,[step(0,-.12,-120),step(1,.12,110,True)])
        metrics,_=r._evaluate([ep],method="no_stop",capital=17000,risk_budget=4250)
        self.assertAlmostEqual(metrics["worst_observed_mark_return"],-.12)
        self.assertEqual(metrics["max_within_day_closed_drawdown_inr"],0)
        self.assertEqual(metrics["conditional_net_inr"],110)

    def test_trailing_comparators_match_initial_risk_and_report_reasons(self):
        ep=episode(DAY,[step(0,-.08,-85),step(1,.06,60),step(2,.02,10),step(3,.12,120,True)])
        narrow,_=r._evaluate([ep],method="trailing_stop",capital=17000,risk_budget=4250)
        wide,_=r._evaluate([ep],method="trailing_emergency_stop",capital=17000,risk_budget=4250)
        self.assertEqual(narrow["exit_reasons"],{"stop":1})
        self.assertEqual(wide["exit_reasons"],{"trailing_stop":1})
        self.assertEqual(wide["conditional_net_inr"],10)

    def test_daily_scan_finds_continuations_without_altering_baseline(self):
        prev=index(100);current=index(105)
        base,_=r._signals(DAY,current,PREV,prev,frame=5,hold=60,max_signals=3)
        scan,_=r._signals(DAY,current,PREV,prev,frame=5,hold=60,max_signals=375,entry_mode="daily_scan")
        self.assertEqual(len(base),1)
        self.assertGreater(len(scan),3)
        self.assertEqual(scan[0],base[0])
        self.assertTrue(any(x["entry_type"]=="trend_continuation" for x in scan))
        self.assertTrue(all(x["side"]=="CALL" for x in scan))
        changed=dict(current)
        changed[200]=(80,81,79,80,1)
        later,_=r._signals(DAY,changed,PREV,prev,frame=5,hold=60,max_signals=375,entry_mode="daily_scan")
        self.assertEqual([x for x in scan if x["minute"]<200],[x for x in later if x["minute"]<200])

    def test_daily_scan_abstains_inside_cpr(self):
        scan,_=r._signals(DAY,index(100),PREV,index(100),frame=5,hold=60,
                           max_signals=375,entry_mode="daily_scan")
        self.assertEqual(scan,[])

    def test_daily_account_does_not_overlap_positions(self):
        a=episode(DAY,[step(0,.12,120,True)],minute=0)
        a["path"][0]["exit_utc"]=r._stamp(DAY,40)
        b=episode(DAY,[step(0,.12,120,True)],minute=15)
        b["path"][0]["exit_utc"]=r._stamp(DAY,25)
        c=episode(DAY,[step(0,.12,120,True)],minute=45)
        c["path"][0]["exit_utc"]=r._stamp(DAY,55)
        out,rows=r._evaluate([c,b,a],method="fixed_stop",capital=17000,risk_budget=4250,
                              dates=[DAY,"2026-10-07"])
        self.assertEqual([x["state"] for x in rows],["complete","position_still_open","complete"])
        self.assertEqual(out["daily_coverage"]["reserved_sessions"],2)
        self.assertEqual(out["daily_coverage"]["days_with_entry"],1)
        self.assertEqual(out["daily_coverage"]["days_without_entry"],1)

    def test_daily_attempt_cap_and_missing_sources(self):
        eps=[]
        for m in (0,15,30,45,60):
            ep=episode(DAY,[step(0,.12,120,True)],minute=m)
            ep["path"][0]["exit_utc"]=r._stamp(DAY,m+5)
            eps.append(ep)
        eps[0]["state"]="missing_signal_quotes"
        out,rows=r._evaluate(eps,method="fixed_stop",capital=17000,risk_budget=4250)
        self.assertEqual(out["states"],{"missing_signal_quotes":1,"complete":3,"daily_attempt_limit":1})
        self.assertEqual(out["daily_coverage"]["by_session"][DAY]["entry_attempts"],3)

    def test_daily_scan_never_uses_incomplete_prior(self):
        prev=index(100)
        del prev[74]
        self.assertEqual(r._signals(DAY,index(105),PREV,prev,frame=5,hold=60,
                                    max_signals=375,entry_mode="daily_scan"),
                         ([],"prior_complete_session_unavailable"))
