"""The CLI must resample its fitted estimator, not individual-point scatter."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "fit_service_curve.py"


class ServiceCurveFitTests(unittest.TestCase):
    def fit(self, csv, *options):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "samples.csv"
            output = Path(directory) / "fit.json"
            source.write_text(csv, encoding="utf-8")
            process = subprocess.run(
                [sys.executable, str(SCRIPT), "--input", str(source),
                 "--output", str(output), "--bootstrap", "2000", *options],
                text=True, capture_output=True, timeout=15,
            )
            result = json.loads(output.read_text()) if output.exists() else None
            self.assertEqual(source.read_text(encoding="utf-8"), csv)
            return process, result

    def test_resamples_the_group_median_with_original_group_sizes(self):
        # Only one of seven x=1 measurements is an outlier. A resampled median
        # needs >=4 outliers (probability <2.5%); a single draw selects it 1/7.
        process, result = self.fit(
            "repeat,gpu_us\n0,5\n" + "1,15\n" * 6 + "1,1015\n"
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(result["fit"]["beta"], 10)
        self.assertEqual(result["fit"]["beta_p025"], 10)
        self.assertEqual(result["fit"]["beta_p975"], 10)
        self.assertEqual(result["points"][1]["samples"], [15] * 6 + [1015])
        self.assertEqual(result["uncertainty"]["groups_with_single_sample"], [0])

    def test_existing_linear_fit_and_repeatability(self):
        csv = "repeat,gpu_us\n0,1\n0,1.1\n1,3\n1,3.1\n2,5\n2,5.1\n"
        process, result = self.fit(csv, "--bootstrap", "200")
        again, repeated = self.fit(csv, "--bootstrap", "200")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertAlmostEqual(result["fit"]["alpha"], 1.05)
        self.assertAlmostEqual(result["fit"]["beta"], 2)
        self.assertEqual(result["fit"], repeated["fit"])
        self.assertEqual(result["schema_version"], "service-curve-fit-v1")

    def test_filter_range_and_negative_slopes_stay_available(self):
        process, result = self.fit(
            "repeat,gpu_us,variant\n0,invalid,keep\n1,7,keep\n2,4,keep\n"
            "3,invalid,keep\n1,invalid,drop\n",
            "--filter", "variant=keep", "--min-x", "1", "--max-x", "2",
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(result["fit"]["beta"], -3)
        self.assertEqual([point["x"] for point in result["points"]], [1, 2])

    def test_nonfinite_selected_coordinates_never_create_a_report(self):
        for x, y in (("nan", "2"), ("inf", "2"), ("1", "nan"), ("1", "inf")):
            with self.subTest(x=x, y=y):
                process, result = self.fit(f"repeat,gpu_us\n0,1\n{x},{y}\n2,3\n")
                self.assertNotEqual(process.returncode, 0)
                self.assertIsNone(result)

    def test_empty_bootstrap_never_creates_a_report(self):
        process, result = self.fit("repeat,gpu_us\n0,1\n1,3\n", "--bootstrap", "0")
        self.assertNotEqual(process.returncode, 0)
        self.assertIsNone(result)

    def test_singletons_are_described_without_claiming_physical_certainty(self):
        process, result = self.fit("repeat,gpu_us\n0,1\n1,3\n")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("uncertainty", result)
        self.assertEqual(result["uncertainty"]["groups_with_single_sample"], [0, 1])
        self.assertIn("physical-bound", result["uncertainty"]["scope"])
        self.assertIn("without proving certainty", result["uncertainty"]["scope"])


if __name__ == "__main__":
    unittest.main()
