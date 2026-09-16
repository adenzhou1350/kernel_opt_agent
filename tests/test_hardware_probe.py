"""Portable NVIDIA inventory tests; no executable or GPU is required."""

import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "hardware_probe.py"
SPEC = importlib.util.spec_from_file_location("hardware_probe", SCRIPT)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class HardwareProbeTests(unittest.TestCase):
    def inspect(self, side_effect, available=True):
        with (
            patch.object(
                probe.shutil,
                "which",
                return_value="/tools/nvidia-smi" if available else None,
            ),
            patch.object(probe.subprocess, "run", side_effect=side_effect) as run,
        ):
            result = probe.inspect_nvidia()
        for call in run.call_args_list:
            self.assertLessEqual(call.kwargs["timeout"], 2)
            self.assertFalse(call.kwargs.get("shell", False))
            self.assertEqual(call.args[0][0], "/tools/nvidia-smi")
            self.assertTrue(call.args[0][1].startswith("--query-gpu="))
            self.assertEqual(call.args[0][2:], ["--format=csv,noheader,nounits"])
        return result, run

    @staticmethod
    def completed(stdout="", stderr="", returncode=0):
        return subprocess.CompletedProcess([], returncode, stdout, stderr)

    def metadata(self, index, uuid, overrides=None):
        values = {field: "100" for field in probe.OPTIONAL_FIELDS}
        values.update(
            {
                "compute_cap": "8.6",
                "driver_version": "580.1",
                "pci.bus_id": "00000000:01:00.0",
            }
        )
        values.update(overrides or {})
        return ", ".join([str(index), uuid, *values.values()])

    def test_sparse_out_of_order_indices_and_uuid_are_joined(self):
        result, run = self.inspect(
            [
                self.completed('7, "GPU, Seven", GPU-seven\n2, GPU Two, GPU-two\n'),
                self.completed(
                    self.metadata(2, "GPU-two", {"memory.total": "24000"})
                    + "\n"
                    + self.metadata(7, "GPU-seven", {"memory.total": "48000"})
                ),
            ]
        )
        self.assertEqual(result["status"], "OBSERVED")
        self.assertEqual([device["index"] for device in result["devices"]], [2, 7])
        self.assertEqual(
            [device["memory_total_mib"] for device in result["devices"]], [24000, 48000]
        )
        self.assertEqual(result["devices"][1]["name"], "GPU, Seven")
        self.assertEqual(result["devices"][0]["compute_capability"], "8.6")
        self.assertEqual(run.call_count, 2)
        self.assertTrue(result["evidence"]["captured_at"].endswith("Z"))

    def test_unsupported_optional_field_does_not_hide_inventory_or_other_fields(self):
        def fake(argv, **kwargs):
            fields = argv[1].removeprefix("--query-gpu=").split(",")
            if fields == ["index", "name", "uuid"]:
                return self.completed("9, GPU Nine, GPU-nine")
            if "compute_cap" in fields:
                return self.completed(
                    stderr='Field "compute_cap" is not a valid field to query.',
                    returncode=2,
                )
            return self.completed(
                "9, GPU-nine, " + ("580.1" if fields[-1] == "driver_version" else "123")
            )

        result, run = self.inspect(fake)
        device = result["devices"][0]
        self.assertEqual(result["status"], "OBSERVED")
        self.assertIsNone(device["compute_capability"])
        self.assertEqual(device["memory_total_mib"], 123)
        self.assertEqual(device["driver_version"], "580.1")
        self.assertTrue(
            any("compute_cap unavailable" in item for item in result["unknowns"])
        )
        self.assertEqual(run.call_count, 2 + len(probe.OPTIONAL_FIELDS))
        self.assertEqual(result["evidence"]["commands"][1]["returncode"], 2)

    def test_missing_executable_does_not_run_commands(self):
        result, run = self.inspect([], available=False)
        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertIsNone(result["tools"]["nvidia-smi"])
        self.assertEqual(result["devices"], [])
        self.assertTrue(
            any("executable not found" in item for item in result["unknowns"])
        )
        run.assert_not_called()

    def test_identity_query_failure_and_empty_inventory_are_explicit(self):
        for response in (
            self.completed(stderr="Driver unavailable", returncode=9),
            self.completed(),
        ):
            with self.subTest(response=response):
                result, run = self.inspect([response])
                self.assertEqual(result["status"], "UNAVAILABLE")
                self.assertEqual(result["devices"], [])
                self.assertGreater(len(result["unknowns"]), 2)
                self.assertEqual(run.call_count, 1)

    def test_malformed_values_are_null_and_real_zero_is_retained(self):
        result, _ = self.inspect(
            [
                self.completed("bad, invalid, GPU-bad\n4, GPU Four, GPU-four"),
                self.completed(
                    self.metadata(
                        4,
                        "GPU-four",
                        {
                            "memory.total": "N/A",
                            "memory.used": "0",
                            "utilization.gpu": "101",
                            "power.draw": "NaN",
                            "power.limit": "inf",
                            "power.min_limit": "-2",
                            "power.max_limit": "bad",
                            "compute_cap": "nonsense",
                            "clocks.current.sm": "[Not Supported]",
                        },
                    )
                ),
            ]
        )
        device = result["devices"][0]
        self.assertEqual(device["memory_used_mib"], 0)
        for key in (
            "memory_total_mib",
            "gpu_utilization_percent",
            "power_draw_w",
            "power_limit_w",
            "power_min_limit_w",
            "power_max_limit_w",
            "compute_capability",
            "sm_clock_current_mhz",
        ):
            self.assertIsNone(device[key], key)
        self.assertTrue(
            any("Malformed required identity" in item for item in result["unknowns"])
        )

    def test_changed_uuid_does_not_attach_another_devices_metadata(self):
        result, _ = self.inspect(
            [
                self.completed("4, GPU Four, GPU-four"),
                self.completed(self.metadata(4, "GPU-replaced")),
            ]
        )
        self.assertIsNone(result["devices"][0]["memory_total_mib"])
        self.assertTrue(any("Unmatched" in item for item in result["unknowns"]))

    def test_timeouts_stop_further_queries_and_keep_observed_identity(self):
        timeout = subprocess.TimeoutExpired("nvidia-smi", probe.TIMEOUT_SECONDS)
        for responses, status in (
            ([timeout], "UNAVAILABLE"),
            ([self.completed("0, GPU Zero, GPU-zero"), timeout], "OBSERVED"),
        ):
            with self.subTest(status=status):
                result, run = self.inspect(responses)
                self.assertEqual(result["status"], status)
                self.assertEqual(run.call_count, len(responses))
                self.assertTrue(
                    any("TimeoutExpired" in item for item in result["unknowns"])
                )

    def test_execution_failure_is_explicit(self):
        result, run = self.inspect([OSError("executable disappeared")])
        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertIn("executable disappeared", result["unknowns"][-1])
        self.assertEqual(run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
