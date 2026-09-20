"""Local-only viewer checks: no model, external network or GPU calls."""

import importlib.util
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dashboard = load("kimi_scout_dashboard")
scout = load("kimi_scout")


class DashboardTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        scout.initialize(self.root)
        self.packet = {
            "name": "public issue review",
            "repo": "a/b",
            "question": "Review a public snippet",
            "sources": [{"url": "https://github.com/a/b/issues/1", "text": "return x"}],
        }
        self.job_id = scout.enqueue(self.root, self.packet)
        self.inbox = dashboard.Inbox(self.root)

    def artifact(self, suffix, value):
        scout.write_json(self.root / "results" / f"{self.job_id}.{suffix}.json", value)

    def test_read_only_database(self):
        before = (self.root / "scout.sqlite").read_bytes()
        self.assertEqual(self.inbox.state()["summary"]["total_jobs"], 1)
        self.assertEqual(self.inbox.detail(self.job_id)["packet"], self.packet)
        self.assertEqual(before, (self.root / "scout.sqlite").read_bytes())
        with closing(sqlite3.connect(self.root / "scout.sqlite")) as db:
            self.assertEqual(
                db.execute("SELECT state FROM jobs").fetchone()[0], "PENDING"
            )

    def test_actual_usage_not_reservations_including_failed_answers(self):
        with scout.connect(self.root) as db:
            db.execute("UPDATE jobs SET state='FAILED',charge=30000")
        summary = self.inbox.state()["summary"]
        self.assertEqual(summary["reported_tokens"], 0)
        self.assertEqual(summary["reserved_tokens"], 30000)
        self.artifact(
            "answer",
            {
                "text": "invalid JSON",
                "usage": {
                    "total_tokens": 123,
                    "input_tokens": 100,
                    "output_tokens": 23,
                },
            },
        )
        summary = self.inbox.state()["summary"]
        self.assertEqual(summary["reported_tokens"], 123)
        self.assertEqual(summary["reserved_tokens"], 0)
        self.assertEqual(summary["usage_known_jobs"], 1)

    def test_legacy_prompts_are_explicitly_reconstructed(self):
        detail = self.inbox.detail(self.job_id)
        self.assertTrue(detail["prompt_reconstructed"])
        self.artifact("request", {"prompt": "exact saved prompt"})
        detail = self.inbox.detail(self.job_id)
        self.assertFalse(detail["prompt_reconstructed"])
        self.assertEqual(detail["prompt"], "exact saved prompt")

    def test_live_partial_and_malformed_file(self):
        with scout.connect(self.root) as db:
            db.execute("UPDATE jobs SET state='RUNNING',started=?", (time.time() - 10,))
        self.artifact(
            "live",
            {
                "text": "partial <script>alert(1)</script>",
                "phase": "streaming",
                "updated_at": time.time(),
                "unexpected": "not exposed",
            },
        )
        detail = self.inbox.detail(self.job_id)
        self.assertEqual(detail["live"]["phase"], "streaming")
        self.assertNotIn("unexpected", detail["live"])
        self.assertTrue(detail["job"]["has_live_output"])
        self.assertGreaterEqual(detail["job"]["elapsed_seconds"], 10)
        (self.root / "results" / f"{self.job_id}.live.json").write_text(
            "{", encoding="utf-8"
        )
        self.assertIsNone(self.inbox.detail(self.job_id)["live"])

    def test_dead_and_stale_runner_are_not_silently_running(self):
        scout.write_json(
            self.root / "runtime.json",
            {"pid": 123, "state": "RUNNING", "heartbeat_at": time.time() - 500},
        )
        with patch.object(dashboard, "process_alive", return_value=False):
            state = self.inbox.state()
            self.assertEqual(state["runtime"]["state"], "OFFLINE")
            self.assertTrue(state["warnings"])
        with patch.object(dashboard, "process_alive", return_value=True):
            self.assertIn("心跳", self.inbox.state()["warnings"][0])

    def test_reject_arbitrary_paths_and_symlink_escape(self):
        for value in ("../runtime.json", "1", "a" * 24 + "/secret", "a" * 23):
            with self.assertRaises(KeyError):
                self.inbox.detail(value)
        with tempfile.TemporaryDirectory() as other:
            path = Path(other) / "secret.json"
            path.write_text('{"private":"never"}', encoding="utf-8")
            self.assertEqual(dashboard.read_artifact(self.root, str(path)), {})
            link = self.root / "results" / f"{self.job_id}.answer.json"
            try:
                link.symlink_to(path)
            except OSError:
                return  # Some Windows accounts lack symlink privileges.
            self.assertEqual(self.inbox.artifact(self.job_id, "answer"), {})

    def test_read_only_http_routes_headers_and_origin(self):
        server = dashboard.make_server(self.root, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with urlopen(base + "/api/state", timeout=3) as response:
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                self.assertNotIn("Access-Control-Allow-Origin", response.headers)
                self.assertEqual(json.load(response)["summary"]["total_jobs"], 1)
            for path, headers, method, status in (
                ("/api/state", {"Host": "evil.example"}, "GET", 403),
                ("/api/state", {"Origin": "https://evil.example"}, "GET", 403),
                ("/api/jobs/../../config.toml", {}, "GET", 404),
                ("/runtime.json", {}, "GET", 404),
                ("/api/stop", {}, "POST", 501),
            ):
                with (
                    self.subTest(path=path, method=method),
                    self.assertRaises(HTTPError) as error,
                ):
                    urlopen(
                        Request(base + path, headers=headers, method=method), timeout=3
                    )
                self.assertEqual(error.exception.code, status)
            with urlopen(base + "/api/jobs/" + self.job_id, timeout=3) as response:
                self.assertEqual(json.load(response)["packet"], self.packet)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_unknown_usage_never_invented(self):
        for value in (None, {}, {"total_tokens": True}, {"total_tokens": -1}):
            self.assertIsNone(dashboard.valid_usage(value))
        self.assertEqual(
            dashboard.valid_usage({"total_tokens": 0}), {"total_tokens": 0}
        )


if __name__ == "__main__":
    unittest.main()
