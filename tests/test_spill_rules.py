import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import backend.db as db_module

from backend.main import app, worker
from backend.spill_rules import (SPILL_SECONDS, SpillWatch, StepClock, rule_cancel_reason, step_limit)

HEALTHY = {"gpu_util_percent": 100, "gpu_power_w": 278, "gpu_memory_util_percent": 41}
STARVED = {"gpu_util_percent": 100, "gpu_power_w": 136, "gpu_memory_util_percent": 1}


class SpillRuleTests(unittest.TestCase):
    def test_step_limits_follow_the_users_numbers(self):
        # 10 s 1 MP 200 s, 10 s 1.5 MP 450 s, 15 s 1 MP 400 s, 15 s 1.5 MP 1,000 s; shorter clips use the 10 s ones
        self.assertEqual(step_limit(10, 1.03), 200)
        self.assertEqual(step_limit(10, 1.51), 450)
        self.assertEqual(step_limit(15, 1.03), 400)
        self.assertEqual(step_limit(15, 1.51), 1000)
        self.assertEqual(step_limit(5, 1.51), 450)
        self.assertEqual(step_limit(7, 0.8), 200)

    def test_a_spill_is_a_starved_gpu_for_a_minute(self):
        watch = SpillWatch()
        self.assertFalse(watch.feed(STARVED, 0))
        self.assertFalse(watch.feed(STARVED, SPILL_SECONDS - 5))
        self.assertTrue(watch.feed(STARVED, SPILL_SECONDS))
        self.assertTrue(watch.spilled)
        self.assertTrue(watch.feed(HEALTHY, SPILL_SECONDS + 5))    # one healthy-looking reading: still spilling
        self.assertTrue(watch.feed(STARVED, SPILL_SECONDS + 10))
        self.assertTrue(watch.feed(HEALTHY, SPILL_SECONDS + 15))
        self.assertFalse(watch.feed(HEALTHY, SPILL_SECONDS + 46))  # healthy for 30 s: the spill is over
        self.assertFalse(watch.feed(STARVED, SPILL_SECONDS + 50))  # and a new spill needs a full minute again
        # a healthy busy GPU, or a missing reading, is never a spill
        fresh = SpillWatch()
        self.assertFalse(fresh.feed(HEALTHY, 0) or fresh.feed(HEALTHY, 600))
        self.assertFalse(fresh.feed({}, 0) or fresh.feed({}, 600))

    def test_only_real_steps_are_timed(self):
        clock = StepClock()
        self.assertEqual(clock.feed(0, 0, 0), 0)        # start-up / resuming: no total, never timed
        self.assertEqual(clock.feed(0, 0, 900), 0)
        self.assertEqual(clock.feed(1, 8, 1000), 0)     # the first real step starts the clock
        self.assertEqual(clock.feed(1, 8, 1150), 150)
        self.assertEqual(clock.feed(2, 8, 1200), 0)     # a new step restarts it
        self.assertEqual(clock.feed(2, 8, 1260), 60)

    def test_cancel_reasons(self):
        self.assertIsNone(rule_cancel_reason(step_seconds=150, step=1, total=8, limit=200, single_short_job=True,
                                             running_seconds=600))
        over = rule_cancel_reason(step_seconds=212, step=2, total=8, limit=200, single_short_job=False,
                                  running_seconds=3000)
        self.assertIn("step 3/8 ran 212 s", over)
        self.assertIn("No limits", over)
        self.assertIsNone(rule_cancel_reason(step_seconds=500, step=0, total=0, limit=200, single_short_job=False,
                                             running_seconds=3000))
        short = rule_cancel_reason(step_seconds=10, step=5, total=8, limit=450, single_short_job=True,
                                   running_seconds=16 * 60)
        self.assertIn("15 min", short)
        self.assertIsNone(rule_cancel_reason(step_seconds=10, step=5, total=8, limit=450, single_short_job=False,
                                             running_seconds=60 * 60))


class NoLimitsApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="h3-spill-test-")
        self.path = Path(self.temp.name) / "jobs.sqlite3"
        self.original_path = db_module.DB_PATH
        db_module.DB_PATH = self.path
        db_module.init_db()
        self.notify_patch = patch.object(worker, "notify")
        self.notify_patch.start()
        self.client = TestClient(app)
        self.token = self.client.get("/api/session").json()["csrf_token"]

    def tearDown(self):
        self.client.close()
        self.notify_patch.stop()
        db_module.DB_PATH = self.original_path
        self.temp.cleanup()

    def post(self, **values):
        data = {"prompt": "A calm cinematic forest", "mode": "text", "duration": "5", "engine": "turbo", "steps": "4",
                "resolution": "512x288", **values}
        return self.client.post("/api/jobs", data=data, headers={"X-CSRF-Token": self.token})

    def test_no_limits_is_stored_per_job(self):
        free = self.post(no_limits="true").json()["created"][0]
        ruled = self.post().json()["created"][0]
        jobs = {job["id"]: job for job in self.client.get("/api/jobs?limit=10&include_library=false").json()["jobs"]}
        self.assertTrue(jobs[free]["no_limits"])
        self.assertFalse(jobs[ruled]["no_limits"])

    def test_an_older_database_gets_the_column(self):
        connection = sqlite3.connect(self.path)
        try:
            columns = [row[1] for row in connection.execute("PRAGMA table_info(jobs)")]
        finally:
            connection.close()
        self.assertIn("no_limits", columns)


if __name__ == "__main__":
    unittest.main()
