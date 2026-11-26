"""Bounded general queue, independent spread replay and safe cancellation."""
from __future__ import annotations

from concurrent.futures import Future
from unittest.mock import patch
import unittest

from fastapi import HTTPException

from workstation_api import app as module


class StoppedWorker:
    def __init__(self):
        self.pending=[]
    def submit(self,task):
        future=Future()
        self.pending.append((task,future))
        return future


class JobQueueTests(unittest.TestCase):
    def setUp(self):
        self.worker=StoppedWorker()
        self.spread_worker=StoppedWorker()
        self.before=(module.JOBS,module.JOB_FUTURES,
                     module.JOB_RETRY_SPECS,module.JOB_STOP_SIGNALS)
        module.JOBS={}
        module.JOB_FUTURES={}
        module.JOB_RETRY_SPECS={}
        module.JOB_STOP_SIGNALS={}
        self.mocks=[
            patch.object(module,"RUNNER",self.worker),
            patch.object(module,"SPREAD_REPLAY_RUNNER",self.spread_worker),
            patch.object(module,"_persist_job",return_value=None),
            patch.object(module.research_library,"list_job_history",return_value=[]),
        ]
        for p in self.mocks:p.start()

    def tearDown(self):
        for p in reversed(self.mocks):p.stop()
        (module.JOBS,module.JOB_FUTURES,
         module.JOB_RETRY_SPECS,module.JOB_STOP_SIGNALS)=self.before

    def test_bounded_serial_queue_and_positions(self):
        ids=[]
        for i in range(module.MAX_ACTIVE_LOCAL_JOBS):
            response=module._spawn("workspace_validation",lambda:{"step":i})
            ids.append(response["job_id"])
        self.assertEqual(len(self.worker.pending),6)
        self.assertEqual(len(module.JOBS),6)
        snapshot=module.workspace_jobs()
        self.assertEqual(snapshot["max_pending_or_running"],6)
        self.assertEqual(snapshot["worker_concurrency"],2)
        self.assertEqual(snapshot["research_worker_concurrency"],1)
        self.assertEqual(snapshot["spread_replay_worker_concurrency"],1)
        order=[j for j in reversed(snapshot["jobs"])]
        self.assertEqual([j["queue_position"] for j in order],[1,2,3,4,5,6])
        self.assertTrue(all(j["status"]=="queued" for j in order))
        with self.assertRaises(HTTPException) as fail:
            module._spawn("workspace_validation",lambda:None)
        self.assertEqual(fail.exception.status_code,409)
        self.assertIn("full",fail.exception.detail)

    def test_spread_replay_can_complete_while_history_download_is_waiting(self):
        first=module._spawn("expired_option_history_acquisition",lambda:None)["job_id"]
        second=module._spawn("workspace_validation",lambda:None)["job_id"]
        spread=module._spawn("spread_speed_study",lambda:{"ok":True})["job_id"]
        self.assertEqual(len(self.worker.pending),2)
        self.assertEqual(len(self.spread_worker.pending),1)
        rows={j["id"]:j for j in module.workspace_jobs()["jobs"]}
        self.assertEqual(rows[first]["queue_position"],1)
        self.assertEqual(rows[second]["queue_position"],2)
        self.assertEqual(rows[spread]["queue_position"],1)
        self.assertEqual(rows[spread]["worker_lane"],"spread_replay")
        with self.assertRaises(HTTPException) as fail:
            module._spawn("spread_speed_study",lambda:None)
        self.assertEqual(fail.exception.status_code,409)
        action,future=self.spread_worker.pending[0]
        self.assertTrue(future.set_running_or_notify_cancel())
        action()
        future.set_result(None)
        self.assertEqual(module.JOBS[spread]["status"],"complete")
        self.assertEqual(module.JOBS[first]["status"],"queued")
        self.assertEqual(module.JOBS[second]["status"],"queued")
        new=module._spawn("spread_speed_study",lambda:None)["job_id"]
        self.assertEqual(module.workspace_cancel_job(new)["status"],"cancelled")
        self.assertTrue(module.JOB_FUTURES[new].cancelled())

    def test_batch_and_frozen_validation_share_bounded_spread_lane(self):
        first=module._spawn("spread_batch_study",lambda:{"ok":True})["job_id"]
        self.assertEqual(module.JOBS[first]["worker_lane"],"spread_replay")
        self.assertTrue(module.JOBS[first]["cancellable"])
        for kind in ("spread_speed_study","spread_batch_study","spread_batch_validation"):
            with self.assertRaises(HTTPException) as failure:
                module._spawn(kind,lambda:None)
            self.assertEqual(failure.exception.status_code,409)
        module.workspace_cancel_job(first)
        second=module._spawn("spread_batch_validation",lambda:None)["job_id"]
        self.assertEqual(module.JOBS[second]["worker_lane"],"spread_replay")
        self.assertTrue(module.JOBS[second]["cancellable"])
        self.assertEqual(len(self.worker.pending),0)

    def test_cancel_queued_releases_capacity_and_safe_retry(self):
        first=module._spawn("workspace_validation",lambda:None)["job_id"]
        for _ in range(5):module._spawn("workspace_validation",lambda:None)
        stopped=module.workspace_cancel_job(first)
        self.assertEqual(stopped["status"],"cancelled")
        self.assertFalse(module.JOB_FUTURES[first].running())
        self.assertTrue(module.JOB_FUTURES[first].cancelled())
        snapshot=module.workspace_jobs()
        self.assertTrue(next(j for j in snapshot["jobs"] if j["id"]==first)["retryable"])
        retried=module.workspace_retry_job(first)
        self.assertEqual(retried["status"],"queued")
        self.assertNotEqual(retried["job_id"],first)

    def test_failure_actions_do_not_include_vendor_content(self):
        self.assertIn("Dhan",module._job_next_action(
            {"status":"error","error":"Dhan token expired"}))
        self.assertIn("throttling",module._job_next_action(
            {"status":"error","error":"HTTP 429 rate limit"}))
        self.assertIn("Model Laboratory",module._job_next_action(
            {"status":"error","error":"Insufficient source history"}))
        self.assertIn("queue order",module._job_next_action(
            {"status":"queued"}))
        self.assertIn("checkpoint",module._job_next_action(
            {"status":"running","cancellable":True}))
