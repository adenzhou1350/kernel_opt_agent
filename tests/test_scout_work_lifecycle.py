"""Offline ownership/retention controls for completed Scout request cwd."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "kimi_scout.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("scout_work_lifecycle_subject", SCRIPT)
scout = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scout)


class WorkLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        scout.initialize(self.root)
        self.packet = {
            "name": "cwd-lifetime",
            "commit": "a" * 40,
            "question": "Review supplied code only",
            "sources": [
                {
                    "url": "https://github.com/a/b/blob/" + "a" * 40 + "/x.py",
                    "text": "return 1",
                    "truncated": False,
                }
            ],
        }
        scout.enqueue(self.root, self.packet)
        self.job = scout.claim(self.root, 12, 200000, 2048)
        self.work = self.root / "work" / self.job["id"]
        analysis = {
            key: ""
            for key in (
                "title",
                "hypothesis",
                "baseline",
                "next_check",
                "duplicate_risk",
                "uncertainty",
                "knowledge_suggestion",
            )
        }
        analysis.update(decision="no_lead", evidence=[])
        self.response = {
            "ok": True,
            "text": json.dumps(analysis),
            "tools_advertised": 0,
            "tool_calls_executed": 0,
            "usage": {"total_tokens": 20},
        }

    def execute(self, side_effect=None):
        if side_effect is None:
            side_effect = lambda *args, **kwargs: subprocess.CompletedProcess(
                [], 0, json.dumps(self.response), ""
            )
        with patch.object(scout.subprocess, "run", side_effect=side_effect):
            return scout.execute(self.root, self.job, sys.executable, 30, 2048)

    def test_actual_child_empty_cwd_removed_after_receipt_and_db_commit(self):
        native_run = subprocess.run

        def child(*args, **kwargs):
            # Execute a real trusted Python child, never a model/provider.
            return native_run(
                [
                    sys.executable,
                    "-I",
                    "-B",
                    "-c",
                    "import sys; print(sys.argv[1])",
                    json.dumps(self.response),
                ],
                cwd=kwargs["cwd"],
                capture_output=True,
                text=True,
                timeout=10,
            )

        receipt = self.execute(child)
        self.assertEqual(receipt["state"], "NO_LEAD")
        self.assertFalse(self.work.exists())
        for suffix in (".json", ".request.json", ".answer.json"):
            self.assertTrue(
                (self.root / "results" / (self.job["id"] + suffix)).is_file()
            )
        with scout.connect(self.root) as db:
            state = db.execute(
                "SELECT state FROM jobs WHERE id=?", (self.job["id"],)
            ).fetchone()[0]
        self.assertEqual(state, "NO_LEAD")

    def test_backend_created_file_is_preserved(self):
        def child(*args, **kwargs):
            (kwargs["cwd"] / "diagnostic.txt").write_text("keep this evidence")
            return subprocess.CompletedProcess([], 0, json.dumps(self.response), "")

        self.assertEqual(self.execute(child)["state"], "NO_LEAD")
        self.assertEqual(
            (self.work / "diagnostic.txt").read_text(), "keep this evidence"
        )

    def test_replaced_empty_directory_is_not_owned(self):
        def child(*args, **kwargs):
            kwargs["cwd"].rename(self.work.with_name(self.work.name + "-original"))
            kwargs["cwd"].mkdir()
            return subprocess.CompletedProcess([], 0, json.dumps(self.response), "")

        self.assertEqual(self.execute(child)["state"], "NO_LEAD")
        self.assertTrue(self.work.is_dir())

    def test_preexisting_empty_directory_is_preserved(self):
        self.work.mkdir()
        with patch.object(scout.subprocess, "run") as child:
            receipt = scout.execute(self.root, self.job, sys.executable, 30, 2048)
        child.assert_not_called()
        self.assertEqual(receipt["state"], "FAILED")
        self.assertTrue(self.work.is_dir())

    def test_timeout_empty_directory_removed_but_failure_evidence_retained(self):
        def child(*args, **kwargs):
            raise subprocess.TimeoutExpired("private command", 30)

        receipt = self.execute(child)
        self.assertEqual(receipt["state"], "FAILED")
        self.assertFalse(self.work.exists())
        self.assertTrue((self.root / "results" / (self.job["id"] + ".json")).is_file())
        self.assertTrue(
            (self.root / "results" / (self.job["id"] + ".live.json")).is_file()
        )

    def test_cleanup_permission_error_does_not_change_result(self):
        rmdir = Path.rmdir

        def denied(path):
            if path == self.work:
                raise PermissionError("simulated open directory")
            return rmdir(path)

        with patch.object(Path, "rmdir", denied):
            receipt = self.execute()
        self.assertEqual(receipt["state"], "NO_LEAD")
        self.assertTrue(self.work.is_dir())

    @unittest.skipIf(os.name == "nt", "Windows symlink creation may require elevation")
    def test_symlink_replacement_preserves_target(self):
        other = self.root / "other-owner"
        other.mkdir()

        def child(*args, **kwargs):
            kwargs["cwd"].rename(self.work.with_name(self.work.name + "-original"))
            kwargs["cwd"].symlink_to(other, target_is_directory=True)
            return subprocess.CompletedProcess([], 0, json.dumps(self.response), "")

        self.assertEqual(self.execute(child)["state"], "NO_LEAD")
        self.assertTrue(self.work.is_symlink())
        self.assertTrue(other.is_dir())


if __name__ == "__main__":
    unittest.main()
