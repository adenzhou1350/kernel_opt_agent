"""The small calculator must not turn measurements into physical limits."""

import contextlib
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import hardware_profile as profile  # noqa: E402


def model():
    return {
        "device": "fictional device, not a measurement",
        "workload": "fixed cold copy with verified output",
        "assumptions": ["2 MB mandatory traffic; rates below are illustrative"],
        "resources": [
            {
                "name": "dram",
                "unit": "bytes",
                "minimum_work": 2e6,
                "minimum_work_basis": "assumed mandatory cold input+output traffic",
                "upper_rate_per_second": 2e11,
                "upper_rate_basis": "hypothetical capacity",
                "reference_work": 2e6,
                "measured_rate_per_second": 1.6e11,
                "measurement_basis": "hypothetical matched samples, not real evidence",
            }
        ],
        "observed_us": 11,
        "observation_basis": "hypothetical matched correct timing",
    }


class HardwareProfileTests(unittest.TestCase):
    def test_known_bound_and_reference_are_separate(self):
        data = model()
        original = copy.deepcopy(data)
        report = profile.estimate(data)
        self.assertEqual(data, original)
        self.assertEqual(report["status"], "CONDITIONAL_ESTIMATE")
        self.assertEqual(report["conditional_lower_us"], 10)
        self.assertEqual(report["empirical_resource_reference_us"], 12.5)
        self.assertAlmostEqual(report["conditional_speedup_ceiling"], 1.1)
        self.assertEqual(report["limiting_known_resources"], ["dram"])

    def test_empirical_only_never_creates_a_bound(self):
        data = model()
        del data["resources"][0]["upper_rate_per_second"]
        report = profile.estimate(data)
        self.assertEqual(report["status"], "NO_BOUND")
        self.assertIsNone(report["conditional_lower_us"])
        self.assertIsNone(report["conditional_speedup_ceiling"])
        self.assertEqual(report["empirical_resource_reference_us"], 12.5)

    def test_impossible_observation_is_not_super_peak_efficiency(self):
        data = model()
        data["observed_us"] = 9
        report = profile.estimate(data)
        self.assertEqual(report["status"], "MODEL_CONTRADICTION")
        self.assertIsNone(report["conditional_speedup_ceiling"])

    def test_empirical_rate_over_claimed_capacity_invalidates_model(self):
        data = model()
        data["resources"][0]["measured_rate_per_second"] = 3e11
        report = profile.estimate(data)
        self.assertEqual(report["status"], "MODEL_CONTRADICTION")
        self.assertIsNone(report["conditional_speedup_ceiling"])
        self.assertIn("exceeds claimed upper capacity", report["contradictions"][0])

    def test_parallel_constraints_max_and_separate_serial_path(self):
        data = model()
        data.pop("observed_us")
        data["resources"].append(
            {
                "name": "tensor",
                "unit": "FLOP",
                "minimum_work": 8e6,
                "minimum_work_basis": "hypothetical algorithm-class floor",
                "upper_rate_per_second": 1e12,
                "upper_rate_basis": "hypothetical dense rate",
            }
        )
        self.assertEqual(profile.estimate(data)["conditional_lower_us"], 10)
        data.update(
            dependency_lower_us=18, dependency_basis="assumed mandatory serial path"
        )
        self.assertEqual(profile.estimate(data)["conditional_lower_us"], 18)

    def test_missing_resources_stay_unknown(self):
        data = model()
        data["resources"] = [{"name": "L2", "unit": "bytes"}]
        report = profile.estimate(data)
        self.assertIsNone(report["conditional_lower_us"])
        self.assertIn("L2: no minimum-work/upper-capacity bound", report["unknowns"])

    def test_bad_arithmetic_and_unscoped_inputs_rejected(self):
        for key in (
            "minimum_work",
            "upper_rate_per_second",
            "reference_work",
            "measured_rate_per_second",
        ):
            for value in (-1, True, "1", float("nan"), float("inf"), 10**400):
                with self.subTest(key=key, value=value):
                    data = model()
                    data["resources"][0][key] = value
                    with self.assertRaises(ValueError):
                        profile.estimate(data)
        for key in ("upper_rate_per_second", "measured_rate_per_second"):
            data = model()
            data["resources"][0][key] = 0
            with self.assertRaises(ValueError):
                profile.estimate(data)
        for key in (
            "minimum_work_basis",
            "upper_rate_basis",
            "measurement_basis",
            "reference_work",
        ):
            data = model()
            del data["resources"][0][key]
            with self.assertRaises(ValueError):
                profile.estimate(data)
        for change in ({"resources": [None]}, {"device": ""}, {"assumptions": []}):
            with self.assertRaises(ValueError):
                profile.estimate({**model(), **change})
        data = model()
        data["resources"].append(data["resources"][0])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            profile.estimate(data)
        data = model()
        data["resources"][0]["reference_work"] = 1
        with self.assertRaisesRegex(ValueError, "below claimed minimum"):
            profile.estimate(data)

    def test_cli_example_identity_fresh_output_and_duplicate_keys(self):
        example = ROOT / "hardware" / "examples" / "resource-gap.json"
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "report.json"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    profile.main(
                        ["estimate", "--model", str(example), "--output", str(output)]
                    ),
                    0,
                )
            original = output.read_bytes()
            self.assertEqual(len(json.loads(original)["input_sha256"]), 64)
            with (
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit),
            ):
                profile.main(
                    ["estimate", "--model", str(example), "--output", str(output)]
                )
            self.assertEqual(output.read_bytes(), original)
            with self.assertRaisesRegex(ValueError, "duplicate"):
                json.loads(
                    '{"device":"a","device":"b"}',
                    object_pairs_hook=profile.no_duplicate_keys,
                )

    def test_public_cli_forwarding(self):
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(ROOT / "scripts" / "kernel_opt.py"),
                "hardware-profile",
                "--help",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("inspect", result.stdout)
        self.assertIn("estimate", result.stdout)


if __name__ == "__main__":
    unittest.main()
