import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.scout_arm_costs import STAGES, UNITS, summarize, summarize_arm


def complete():
    return [dict(id=stage, stage=stage, status="not_run", **dict.fromkeys(UNITS, 0))
            for stage in STAGES]


class ArmCostsTests(unittest.TestCase):
    def test_explicit_zero_is_not_missing(self):
        report = summarize_arm(complete(), inventory_complete=True)
        self.assertEqual(report["totals"], dict.fromkeys(UNITS, 0))
        self.assertIsNone(report["elapsed_wall_seconds"])

    def test_undeclared_inventory_cannot_be_complete(self):
        report = summarize_arm(complete())
        self.assertTrue(all(v is None for v in report["totals"].values()))

    def test_missing_stage_prevents_total(self):
        report = summarize_arm(complete()[:-1], inventory_complete=True)
        self.assertEqual(report["missing_stages"], ["verification"])
        self.assertTrue(all(v is None for v in report["totals"].values()))

    def test_unknown_unit_is_not_zero_or_substituted_from_another_arm(self):
        rows = complete()
        del rows[0]["model_tokens"]
        report = summarize({"unknown": {"attempts": rows, "inventory_complete": True},
                            "known": {"attempts": complete(), "inventory_complete": True}})
        self.assertIsNone(report["arms"]["unknown"]["totals"]["model_tokens"])
        self.assertEqual(report["arms"]["unknown"]["totals"]["gpu_seconds"], 0)
        self.assertEqual(report["arms"]["unknown"]["unknown_attempts_by_unit"]["model_tokens"],
                         ["selection"])
        self.assertIsNone(report["winner"])

    def test_failed_attempt_and_retry_are_charged(self):
        rows = complete()
        for identity, status in (("timeout", "failure"), ("retry", "success")):
            rows.append(dict(id=identity, stage="selection", status=status,
                             model_tokens=50, call_seconds=4.0, body_bytes=0, gpu_seconds=0))
        report = summarize_arm(rows, inventory_complete=True, elapsed_wall_seconds=6)
        self.assertEqual(report["failed_attempts"], 1)
        self.assertEqual(report["totals"]["model_tokens"], 100)
        self.assertEqual(report["totals"]["call_seconds"], 8)
        self.assertEqual(report["elapsed_wall_seconds"], 6)

    def test_not_run_rejects_nonzero_but_retains_unknown(self):
        rows = complete()
        rows[0]["model_tokens"] = None
        self.assertIsNone(summarize_arm(rows, inventory_complete=True)["totals"]["model_tokens"])
        rows[0]["call_seconds"] = 1
        with self.assertRaisesRegex(ValueError, "not_run"):
            summarize_arm(rows)

    def test_negative_nonfinite_boolean_fractional_and_overflow(self):
        for value in (-1, float("nan"), float("inf"), True, "3", 0.5, 10 ** 400):
            rows = complete()
            rows[0].update(status="success", model_tokens=value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                summarize_arm(rows)
        rows = complete()
        for row in rows[:2]:
            row.update(status="success", call_seconds=1e308)
        with self.assertRaisesRegex(ValueError, "overflow"):
            summarize_arm(rows)

    def test_duplicate_bad_stage_status_extra_and_nonobject(self):
        mutations = [complete() + [copy.deepcopy(complete()[0])], [None],
                     [{"id": "x", "stage": "outside", "status": "success"}],
                     [{"id": "x", "stage": "review", "status": "unknown"}],
                     [{"id": "x", "stage": "review", "status": "success", "cost_usd": 0}]]
        for rows in mutations:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                summarize_arm(rows)

    def test_invalid_arm_inventory_elapsed_and_no_mutation(self):
        for value in (None, {}, [], {"x": {}}, {"x": {"attempts": [], "winner": True}},
                      {"x": {"attempts": [], "inventory_complete": 1}},
                      {"x": {"attempts": [], "elapsed_wall_seconds": True}}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                summarize(value)
        rows = complete()
        before = copy.deepcopy(rows)
        summarize_arm(rows)
        self.assertEqual(rows, before)

    def test_cli_read_only_summary_and_no_winner_for_complete_arms(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "arms.json"
            arms = {name: {"attempts": complete(), "inventory_complete": True}
                    for name in ("rules", "model")}
            raw = json.dumps(arms).encode("utf-8")
            path.write_bytes(raw)
            script = Path(__file__).resolve().parents[1] / "scripts/scout_arm_costs.py"
            result = subprocess.run([sys.executable, "-B", str(script), str(path)],
                                    capture_output=True, timeout=10, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertIsNone(report["winner"])
            self.assertEqual(report["arms"]["rules"]["totals"], dict.fromkeys(UNITS, 0))
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(list(Path(directory).iterdir()), [path])


if __name__ == "__main__":
    unittest.main()
