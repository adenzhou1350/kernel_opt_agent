"""Fresh disk observations and saved stop records never imply launch approval."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/kimi_scout_dashboard.py"
SPEC = importlib.util.spec_from_file_location("dashboard_resources", SCRIPT)
dashboard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dashboard)


class ResourceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()

    def observe(self, runtime, free_mb=100):
        with patch.object(
            dashboard.shutil,
            "disk_usage",
            return_value=SimpleNamespace(free=free_mb * 1024 * 1024),
        ):
            return dashboard.resource_observation(self.root, runtime, 123)

    def test_fresh_disk_does_not_overwrite_saved_runtime(self):
        runtime = {"available_disk_mb": 2745, "min_free_disk_mb": 4096}
        first = self.observe(runtime, 100)
        second = self.observe(runtime, 5000)
        self.assertEqual(first["disk_free_mb"], 100)
        self.assertTrue(first["below_disk_floor"])
        self.assertFalse(second["below_disk_floor"])
        self.assertEqual(runtime["available_disk_mb"], 2745)
        self.assertNotIn("authorized", second)

    def test_failed_observation_and_unknown_floor_are_unknown(self):
        with patch.object(
            dashboard.shutil, "disk_usage", side_effect=OSError("unavailable")
        ):
            value = dashboard.resource_observation(
                self.root, {"min_free_disk_mb": 4096}, 123
            )
        self.assertIsNone(value["disk_free_mb"])
        self.assertIsNone(value["below_disk_floor"])
        for invalid in [None, True, "4096", -1, float("inf")]:
            value = self.observe({"min_free_disk_mb": invalid})
            self.assertIsNone(value["min_free_disk_mb"])
            self.assertIsNone(value["below_disk_floor"])

    def test_stop_record_must_match_saved_dead_pid(self):
        (self.root / "low-memory-supervision.json").write_text(
            json.dumps(
                {
                    "scout_pid": 7,
                    "stop_reason": "pool growth",
                    "observed_at": "historical",
                }
            ),
            encoding="utf-8",
        )
        for runtime in [
            {"pid": 8, "alive": False},
            {"pid": 7, "alive": True},
            {"pid": 7},
        ]:
            self.assertIsNone(self.observe(runtime)["recorded_stop_reason"])
        value = self.observe({"pid": 7, "alive": False})
        self.assertEqual(value["recorded_stop_reason"], "pool growth")
        self.assertEqual(value["recorded_stop_at"], "historical")

    def test_stop_reason_is_bounded_and_bad_record_is_optional(self):
        path = self.root / "low-memory-supervision.json"
        path.write_text(
            json.dumps({"scout_pid": 7, "stop_reason": "x" * 1000}), encoding="utf-8"
        )
        runtime = {"pid": 7, "alive": False}
        self.assertEqual(len(self.observe(runtime)["recorded_stop_reason"]), 256)
        path.write_text("broken JSON", encoding="utf-8")
        self.assertIsNone(self.observe(runtime)["recorded_stop_reason"])

    def test_powershell_bom_record_is_read_without_rewriting(self):
        path = self.root / "low-memory-supervision.json"
        path.write_text(
            json.dumps({"scout_pid": 7, "stop_reason": "pool growth"}),
            encoding="utf-8-sig",
        )
        before = path.read_bytes()
        self.assertEqual(
            self.observe({"pid": 7, "alive": False})["recorded_stop_reason"],
            "pool growth",
        )
        self.assertEqual(path.read_bytes(), before)

    def test_boolean_supervisor_pid_cannot_match_integer_pid(self):
        path = self.root / "low-memory-supervision.json"
        path.write_text(
            json.dumps({"scout_pid": True, "stop_reason": "wrong process"}),
            encoding="utf-8",
        )
        self.assertIsNone(
            self.observe({"pid": 1, "alive": False})["recorded_stop_reason"]
        )


if __name__ == "__main__":
    unittest.main()
