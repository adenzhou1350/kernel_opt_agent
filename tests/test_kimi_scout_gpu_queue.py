"""Offline approval-queue tests; no SSH, Kimi call, or GPU execution."""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout_gpu_queue as queue

JOB = "3b06b2539f2da672a9b10b28"
GPU = "GPU-36ff58ec-0188-f3a9-d932-0c3a4b3d0338"


class QueueTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        job = self.root / "delivery" / "jobs" / JOB
        job.mkdir(parents=True)
        hashes = {}
        for name in ("baseline", "candidate", "test"):
            content = ("# " + name + "\n").encode()
            (job / f"{name}.py").write_bytes(content)
            hashes[name] = hashlib.sha256(content).hexdigest()
        manifest = job / "reviewed.json"
        manifest.write_text(json.dumps(hashes), encoding="utf-8")
        self.approval = self.root / "delivery" / "gpu-approved" / f"{JOB}.json"
        self.approval.parent.mkdir()
        self.approval.write_text(
            json.dumps(
                {
                    "schema_version": queue.SCHEMA,
                    "job_id": JOB,
                    "host": "worker.example.test",
                    "port": 31201,
                    "gpu_uuid": GPU,
                    "python": "/usr/bin/python3",
                    "files": {
                        "baseline": "baseline.py",
                        "candidate": "candidate.py",
                        "test": "test.py",
                        "reviewed": "reviewed.json",
                    },
                    "reviewed_manifest_sha256": hashlib.sha256(
                        manifest.read_bytes()
                    ).hexdigest(),
                }
            ),
            encoding="utf-8",
        )

    def test_reviewed_bundle_consumed_once(self):
        with mock.patch.object(
            queue, "execute", return_value={"report": {"screen_passed": True}}
        ) as execute:
            result = queue.run_once(self.root)
            self.assertEqual(result["state"], "SCREEN_PASS_NOT_UPSTREAM_QUALIFIED")
            self.assertIsNone(queue.run_once(self.root))
        execute.assert_called_once()
        terminal = self.root / "delivery" / "gpu-results" / f"{JOB}.json"
        self.assertEqual(json.loads(terminal.read_text())["state"], result["state"])
        latest = json.loads((self.root / "delivery" / "gpu-latest.json").read_text())
        self.assertEqual(latest["lead_id"], JOB)
        self.assertEqual(
            latest["terminal_sha256"], hashlib.sha256(terminal.read_bytes()).hexdigest()
        )

    def test_hash_change_fails_before_dispatch_and_is_terminal(self):
        path = self.root / "delivery" / "jobs" / JOB / "reviewed.json"
        path.write_text("{}", encoding="utf-8")
        with mock.patch.object(queue, "execute") as execute:
            result = queue.run_once(self.root)
        execute.assert_not_called()
        self.assertEqual(result["state"], "STARTED_UNCERTAIN")
        self.assertIsNone(queue.run_once(self.root))

    def test_crash_after_claim_does_not_retry(self):
        with (
            mock.patch.object(queue, "execute", side_effect=KeyboardInterrupt),
            self.assertRaises(KeyboardInterrupt),
        ):
            queue.run_once(self.root)
        terminal = self.root / "delivery" / "gpu-results" / f"{JOB}.json"
        self.assertEqual(json.loads(terminal.read_text())["state"], "STARTED_UNCERTAIN")
        with mock.patch.object(queue, "execute") as execute:
            self.assertIsNone(queue.run_once(self.root))
        execute.assert_not_called()

    def test_versioned_attempt_requires_clean_exact_previous_terminal(self):
        old = self.root / "delivery" / "gpu-results" / f"{JOB}.json"
        old.parent.mkdir()
        old.write_text(
            json.dumps(
                {
                    "state": "SCREEN_FAIL",
                    "result": {"report": {"arms": {"baseline": {"cleanup": True}}}},
                }
            ),
            encoding="utf-8",
        )
        v2 = self.approval.with_name(f"{JOB}-v2.json")
        approval = json.loads(self.approval.read_text())
        approval.update(
            {
                "schema_version": queue.SCHEMA_V2,
                "attempt_id": f"{JOB}-v2",
                "supersedes_terminal_sha256": hashlib.sha256(
                    old.read_bytes()
                ).hexdigest(),
            }
        )
        v2.write_text(json.dumps(approval), encoding="utf-8")
        with mock.patch.object(
            queue, "execute", return_value={"report": {"screen_passed": True}}
        ) as execute:
            result = queue.run_once(self.root)
            self.assertEqual(result["state"], "SCREEN_PASS_NOT_UPSTREAM_QUALIFIED")
        execute.assert_called_once()
        self.assertTrue((old.parent / f"{JOB}-v2.json").exists())

    def test_versioned_attempt_rejects_uncertain_previous_cleanup(self):
        old = self.root / "delivery" / "gpu-results" / f"{JOB}.json"
        old.parent.mkdir()
        old.write_text(
            json.dumps(
                {
                    "state": "SCREEN_FAIL",
                    "result": {"report": {"arms": {"baseline": {"cleanup": False}}}},
                }
            ),
            encoding="utf-8",
        )
        v2 = self.approval.with_name(f"{JOB}-v2.json")
        approval = json.loads(self.approval.read_text())
        approval.update(
            {
                "schema_version": queue.SCHEMA_V2,
                "attempt_id": f"{JOB}-v2",
                "supersedes_terminal_sha256": hashlib.sha256(
                    old.read_bytes()
                ).hexdigest(),
            }
        )
        v2.write_text(json.dumps(approval), encoding="utf-8")
        with mock.patch.object(queue, "execute") as execute:
            result = queue.run_once(self.root)
        execute.assert_not_called()
        self.assertEqual(result["state"], "STARTED_UNCERTAIN")


if __name__ == "__main__":
    unittest.main()
