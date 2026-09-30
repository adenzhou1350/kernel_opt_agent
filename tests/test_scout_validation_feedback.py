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

    def test_native_runner_failed_entry_survives_without_an_exception(self):
        for failure in (
            "not ok 2 - retains caller pause",
            " FAIL  src/process/pipe.test.ts > paused consumer",
            " \u276f FAIL  src/process/pipe.test.ts > resumed consumer",
            "test streams::pause_then_resume ... FAILED",
        ):
            with self.subTest(failure=failure):
                brief = cpu_feedback({"before": {"output": "noise\n" + failure + "\n"}})
                self.assertIn(failure, brief["arms"]["before"]["diagnostic_excerpts"])
                self.assertIsNone(brief["arms"]["before"]["reported_tests_run"])

    def test_zero_test_success_is_explicitly_inconclusive(self):
        brief = cpu_feedback(
            {
                "inconclusive": False,
                "before": {
                    "exit_code": 0,
                    "reported_tests_run": 0,
                    "output": "success",
                },
                "fixed": {"exit_code": 0, "reported_tests_run": 12, "output": "PASS"},
            }
        )
        self.assertTrue(brief["inconclusive"])
        self.assertIn("Zero tests reported in before", brief["inventory_warning"])
        self.assertEqual(brief["arms"]["before"]["reported_tests_run"], 0)
        self.assertEqual(brief["arms"]["fixed"]["reported_tests_run"], 12)

    def test_unknown_inventory_is_not_fabricated_as_zero(self):
        for count in (None, False, "0", 3):
            with self.subTest(count=count):
                brief = cpu_feedback({"before": {"reported_tests_run": count}})
                self.assertFalse(brief["inconclusive"])
                self.assertEqual(brief["inventory_warning"], "")

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

    def test_terminal_cause_is_not_crowded_out_by_failure_labels(self):
        output = "\n".join(f"FAIL: test_{index}" for index in range(40))
        output += "\nAssertionError: expected false to be true\n"
        brief = cpu_feedback({"before": {"output": output}})
        lines = brief["arms"]["before"]["diagnostic_excerpts"]
        self.assertIn("AssertionError: expected false to be true", lines)
        self.assertLessEqual(len(lines), 12)

    def test_native_assertion_diff_and_site_survive_blank_lines(self):
        output = (
            "\x1b[31m FAIL \x1b[0m unit-fast pipe.test.ts > caller pause\n"
            " FAIL  unit-fast pipe.test.ts > resume then pause\n"
            "\x1b[1mAssertionError\x1b[22m: expected false to be true // Object.is equality\n"
            "\n- Expected\n+ Received\n\n- true\n+ false\n\n"
            " \u276f pipe.test.ts:48:42\n"
            "     46|         await written;\n"
            "     47|         await nextTick();\n"
            "     48|         expect(child.stdout!.isPaused()).toBe(true);\n"
        )
        brief = cpu_feedback({"before": {"output": output}})
        lines = brief["arms"]["before"]["diagnostic_excerpts"]
        for value in (
            "- true", "+ false", " \u276f pipe.test.ts:48:42",
            "     48|         expect(child.stdout!.isPaused()).toBe(true);",
        ):
            self.assertIn(value, lines)
        self.assertLessEqual(len(lines), 12)
        self.assertEqual(
            brief["arms"]["before"]["output_sha256"],
            hashlib.sha256(output.encode()).hexdigest(),
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
