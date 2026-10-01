"""Admission must account for children not yet reflected in host memory."""

import sys
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout as scout
from kimi_scout import memory_admits_call


class MemoryAdmissionTests(unittest.TestCase):
    def test_disabled_guard_keeps_legacy_behavior(self):
        self.assertTrue(memory_admits_call(None, 0, 16))

    def test_unknown_memory_fails_closed_for_either_guard(self):
        self.assertFalse(memory_admits_call(None, 2048, 0))
        self.assertFalse(memory_admits_call(None, 0, 0, 256))

    def test_unchanged_host_reading_cannot_admit_a_full_burst(self):
        admitted = 0
        while admitted < 16 and memory_admits_call(2600, 2048, admitted, 256):
            admitted += 1
        self.assertEqual(admitted, 2)

    def test_finished_call_releases_reserved_capacity(self):
        self.assertFalse(memory_admits_call(2600, 2048, 2, 256))
        self.assertTrue(memory_admits_call(2600, 2048, 1, 256))

    def test_exact_boundary_is_admitted_but_next_call_is_not(self):
        self.assertTrue(memory_admits_call(3072, 2048, 3, 256))
        self.assertFalse(memory_admits_call(3072, 2048, 4, 256))

    def test_floor_only_semantics_unchanged(self):
        self.assertTrue(memory_admits_call(2048, 2048, 16))
        self.assertFalse(memory_admits_call(2047, 2048, 0))

    def test_real_scheduler_bounds_burst_and_drains_remaining_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scout.initialize(root)
            for i in range(8):
                scout.enqueue(
                    root,
                    {
                        "name": str(i),
                        "question": "check source",
                        "sources": [
                            {
                                "url": "https://raw.githubusercontent.com/a/b/"
                                + "a" * 40
                                + "/f.py",
                                "text": "return value",
                                "truncated": False,
                            }
                        ],
                    },
                )
            args = SimpleNamespace(
                root=root,
                hours=0,
                concurrency=16,
                max_jobs=0,
                token_budget=0,
                feeds=None,
                github_auth=False,
                poll_seconds=300,
                output_tokens=2048,
                timeout=30,
                error_cooldown_seconds=60,
                kimi_python=sys.executable,
                once=True,
                min_free_memory_mb=2048,
                worker_memory_mb=256,
            )
            lock = threading.Lock()
            active = peak = 0

            def execute(root, job, *unused):
                nonlocal active, peak
                with lock:
                    active += 1
                    peak = max(peak, active)
                time.sleep(0.05)
                with scout.connect(root) as db:
                    db.execute(
                        "UPDATE jobs SET state='NO_LEAD',finished=? WHERE id=?",
                        (time.time(), job["id"]),
                    )
                with lock:
                    active -= 1
                return {"state": "NO_LEAD", "finished": time.time()}

            with (
                patch.object(scout, "available_memory_mb", return_value=2600),
                patch.object(scout, "execute", side_effect=execute),
            ):
                result = scout.run(args)
            self.assertEqual(peak, 2)
            self.assertEqual(result["runtime"]["attempted_this_run"], 8)
            self.assertEqual(result["runtime"]["worker_memory_mb"], 256)
            self.assertTrue(all(j["state"] == "NO_LEAD" for j in result["jobs"]))


if __name__ == "__main__":
    unittest.main()
