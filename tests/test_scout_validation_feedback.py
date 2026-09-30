"""Feedback must retain actionable failures without becoming an authority."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_validation_feedback import cpu_feedback, tirx_context


class FeedbackTests(unittest.TestCase):
    def test_failure_and_normal_arm_are_distinct(self):
        before = (
            "noise\nFAIL: test_tail (Tests)\nTraceback (most recent call last):\n"
            "  file.py:33\nAssertionError: 1 != 0\nRan 3 tests\nFAILED (failures=1)\n"
        )
        result = cpu_feedback(
            {
                "before": {"output": before, "exit_code": 1, "reported_tests_run": 3},
                "fixed": {
                    "output": "Ran 3 tests\nOK\n",
                    "exit_code": 0,
                    "reported_tests_run": 3,
                },
            }
        )
        self.assertIn(
            "FAIL: test_tail (Tests)", result["arms"]["before"]["diagnostic_excerpts"]
        )
        self.assertIn(
            "AssertionError: 1 != 0", result["arms"]["before"]["diagnostic_excerpts"]
        )
        self.assertEqual(result["arms"]["fixed"]["exit_code"], 0)
        self.assertIn("No official suite", result["boundary"])

    def test_environment_error_not_lost_or_promoted(self):
        result = cpu_feedback(
            {
                "inconclusive": True,
                "before": {
                    "output": "ModuleNotFoundError: no torch\n",
                    "cleanup_ok": False,
                },
            }
        )
        self.assertTrue(result["inconclusive"])
        self.assertFalse(result["arms"]["before"]["cleanup_ok"])
        self.assertIn("ModuleNotFoundError", str(result))
        self.assertNotIn("qualified", result)

    def test_large_log_and_line_are_bounded(self):
        output = ("noise\n" * 6000) + ("AssertionError: " + "x" * 4000 + "\n") * 100
        brief = cpu_feedback({"before": {"output": output, "output_truncated": True}})
        arm = brief["arms"]["before"]
        self.assertLessEqual(len(arm["diagnostic_excerpts"]), 12)
        self.assertLess(len(json.dumps(brief)), 5000)
        self.assertTrue(arm["output_truncated_by_runner"])
        self.assertGreater(arm["excerpt_lines_truncated"], 0)
        self.assertGreater(arm["log_lines_omitted"], 0)
        self.assertEqual(
            arm["output_sha256"], hashlib.sha256(output.encode()).hexdigest()
        )

    def test_tirx_copy_matches_without_import_or_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            case = Path(directory) / "case.py"
            case.write_text(
                "raise RuntimeError('must not execute')\n", encoding="utf-8"
            )
            result = Path(directory) / "result.json"
            result.write_text(
                json.dumps(
                    {
                        "status": "FAIL",
                        "scope": "CPU concrete-input checks; limited coverage",
                        "case_file": "/different/machine/case.py",
                        "source_sha256": hashlib.sha256(case.read_bytes()).hexdigest(),
                        "cases": {"broken": {"status": "FAIL"}},
                    }
                ),
                encoding="utf-8",
            )
            context = tirx_context(result, case)
            self.assertEqual(
                context["validation_feedback"]["local_source_check"],
                "MATCH_SUPPLIED_COPY",
            )
            self.assertEqual(context["validation_feedback"]["declared_status"], "FAIL")
            case.write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not match"):
                tirx_context(result, case)


if __name__ == "__main__":
    unittest.main()
