"""Current STOP is distinct from saved exit history and resource admission."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import kimi_scout_dashboard as dashboard  # noqa: E402


class StopControlTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def test_absent_empty_and_current_reason(self):
        self.assertEqual(
            dashboard.stop_control(self.root), {"present": False, "reason": None}
        )
        stop = self.root / "STOP"
        stop.touch()
        self.assertEqual(
            dashboard.stop_control(self.root), {"present": True, "reason": None}
        )
        stop.write_text("resident physical/commit emergency floor", encoding="utf-8")
        self.assertEqual(
            dashboard.stop_control(self.root)["reason"],
            "resident physical/commit emergency floor",
        )
        self.assertTrue(stop.exists())

    def test_bounded_invalid_utf8_and_unreadable(self):
        stop = self.root / "STOP"
        stop.write_bytes(b"\xff" + b"x" * 10000)
        self.assertEqual(len(dashboard.stop_control(self.root)["reason"]), 256)
        stop.unlink()
        stop.mkdir()
        self.assertEqual(
            dashboard.stop_control(self.root),
            {"present": True, "reason": None, "unavailable": "not a regular file"},
        )

    def test_does_not_read_an_outside_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            secret = Path(directory) / "secret"
            secret.write_text("private outside content", encoding="utf-8")
            try:
                (self.root / "STOP").symlink_to(secret)
            except OSError:
                self.skipTest("symlink creation not permitted")
            self.assertEqual(
                dashboard.stop_control(self.root),
                {"present": True, "reason": None, "unavailable": "outside inbox"},
            )

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFO required")
    def test_nonregular_signal_cannot_block_viewer_on_fifo_open(self):
        os.mkfifo(self.root / "STOP")
        self.assertEqual(
            dashboard.stop_control(self.root),
            {"present": True, "reason": None, "unavailable": "not a regular file"},
        )

    def test_unknown_presence_is_not_reported_as_absent(self):
        with patch.object(Path, "exists", side_effect=PermissionError):
            self.assertEqual(
                dashboard.stop_control(self.root),
                {"present": None, "reason": None, "unavailable": "unreadable"},
            )

    def test_control_is_live_even_when_history_refresh_is_stale(self):
        inbox = object.__new__(dashboard.Inbox)
        inbox.root = self.root
        import threading
        import time

        inbox._snapshot_lock = threading.Lock()
        inbox._snapshot = {"runtime": {"state": "STOPPED", "alive": False}}
        inbox._snapshot_at = time.monotonic()
        inbox._snapshot_refreshing = False
        with patch.object(
            inbox, "state", side_effect=AssertionError("no history scan")
        ):
            first = inbox.cached_state()
            (self.root / "STOP").write_text("memory floor", encoding="utf-8")
            second = inbox.cached_state()
            (self.root / "STOP").unlink()
            third = inbox.cached_state()
        self.assertFalse(first["stop_control"]["present"])
        self.assertEqual(second["stop_control"]["reason"], "memory floor")
        self.assertFalse(third["stop_control"]["present"])
        self.assertNotIn("stop_control", inbox._snapshot)

    @unittest.skipUnless(shutil.which("node"), "Node.js unavailable")
    def test_frontend_reports_current_control_without_claiming_auto_recovery(self):
        page = (SCRIPTS / "kimi_scout_dashboard.html").read_text(encoding="utf-8")
        block = page[
            page.index("    let flow =") : page.index('    text("lastCompletion"')
        ]
        code = (
            """const render = (alive, control) => {
          const state = {stop_control: control}, runtime = {alive, state: "RUNNING"};
          const counts = {}, research = {}, heartbeatFresh = true, occupied = 0;
          const labels = {}, number = String, time = String; let output;
          const text = (id, value) => { if (id === "flowStatus") output = value; };
        """
            + block
            + """return output; };
        console.log(JSON.stringify([render(false, {present:true,reason:"memory floor"}),
          render(true, {present:true,reason:"operator stop"}), render(false, {present:false})]));"""
        )
        proc = subprocess.run(
            ["node", "-e", code],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
        offline, draining, absent = json.loads(proc.stdout)
        self.assertIn("memory floor", offline)
        self.assertIn("手动恢复", offline)
        self.assertIn("等待在途调用结束", draining)
        self.assertNotIn("STOP", absent)


if __name__ == "__main__":
    unittest.main()
