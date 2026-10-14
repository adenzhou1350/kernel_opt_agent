"""Conservative Vitest 4 JSON accounting, not a community bug oracle."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import scout_native_results as native


def report(*cases):
    """Reporter-shaped fixture; actual native replay is a separate check."""
    statuses = [status for _, status in cases]
    failed = statuses.count("failed")
    return {
        "numTotalTests": len(cases), "numPassedTests": statuses.count("passed"),
        "numFailedTests": failed, "numPendingTests": statuses.count("skipped"),
        "numTodoTests": statuses.count("todo"), "numTotalTestSuites": 1,
        "numPassedTestSuites": int(not failed), "numFailedTestSuites": int(bool(failed)),
        "numPendingTestSuites": 0, "success": not failed,
        "testResults": [{"name": "/private/contract.test.ts", "message": "",
                         "status": "failed" if failed else "passed",
                         "assertionResults": [
                             {"fullName": "contract " + name, "ancestorTitles": ["contract"],
                              "title": name, "status": status,
                              "failureMessages": ["AssertionError: regression"] if status == "failed" else []}
                             for name, status in cases]}],
    }


class VitestResultsTests(unittest.TestCase):
    def summarize(self, value=None, *, exit_code=0, expected=("contract regression",)):
        if value is None:
            value = report(("regression", "passed"))
        return native.summarize(value if isinstance(value, str) else json.dumps(value),
                                format="vitest-json", exit_code=exit_code, expected_tests=expected)

    def test_observed_outcomes_not_reported_total_are_executed(self):
        value = self.summarize(report(("regression", "failed"), ("control", "passed"),
                                      ("unselected", "skipped"), ("future", "todo")), exit_code=1)
        self.assertEqual(value["status"], "TESTS_FAILED")
        self.assertEqual((value["executed"], value["passed"], value["failed"], value["skipped"]), (2, 1, 1, 2))
        self.assertEqual(value["vitest"]["unselected_unexecuted"], 2)
        self.assertEqual(value["vitest"]["reported_total_tests"], 4)

    def test_expected_skipped_todo_missing_and_unfinished_are_inconclusive(self):
        for status in ("skipped", "todo", "pending", "disabled", "queued", "run", None, []):
            value = report(("regression", "passed"))
            value["testResults"][0]["assertionResults"][0]["status"] = status
            with self.subTest(status=status):
                self.assertEqual(self.summarize(value)["status"], "INCONCLUSIVE")
        self.assertEqual(self.summarize(report(("other", "passed")))["status"], "INCONCLUSIVE")
        self.assertEqual(self.summarize(report())["status"], "INCONCLUSIVE")

    def test_malformed_duplicate_keys_constants_and_truncation(self):
        valid = json.dumps(report(("regression", "passed")))
        for value in ("", "[]", "null", valid[:-4], valid + "junk",
                      valid.replace('"success": true', '"success": true, "success": false'),
                      valid.replace('"numPassedTests": 1', '"numPassedTests": NaN'),
                      valid.replace('"numPassedTests": 1', '"numPassedTests": Infinity')):
            with self.subTest(value=value[:70]):
                self.assertEqual(self.summarize(value)["status"], "INCONCLUSIVE")

    def test_totals_must_be_nonnegative_integers_and_match(self):
        valid = report(("regression", "passed"))
        for field in (key for key in valid if key.startswith("num")):
            for bad in (True, -1, 0.5, "1", None, 100001):
                value = copy.deepcopy(valid)
                value[field] = bad
                with self.subTest(field=field, bad=bad):
                    self.assertEqual(self.summarize(value)["status"], "INCONCLUSIVE")
        for key in ("numTotalTests", "numPassedTests", "numFailedTests", "numPendingTests", "numTodoTests"):
            value = copy.deepcopy(valid)
            value[key] += 1
            self.assertEqual(self.summarize(value)["status"], "INCONCLUSIVE")

    def test_suite_failure_pending_and_diagnostics_are_not_assertion_pass(self):
        valid = report(("regression", "passed"))
        mutations = [
            lambda v: v["testResults"][0].update(message="beforeAll crashed"),
            lambda v: v["testResults"][0].update(status="failed"),
            lambda v: v.update(numPendingTestSuites=1, numPassedTestSuites=0),
            lambda v: v.update(numFailedTestSuites=1, numPassedTestSuites=0),
            lambda v: v.update(numTotalTestSuites=0, numPassedTestSuites=0),
            lambda v: v.update(success=False),
            lambda v: v.update(success=1),
        ]
        for mutate in mutations:
            value = copy.deepcopy(valid)
            mutate(value)
            self.assertEqual(self.summarize(value)["status"], "INCONCLUSIVE")

    def test_nested_suite_totals_are_not_file_counts(self):
        value = report(("regression", "passed"))
        value.update(numTotalTestSuites=8, numPassedTestSuites=8)
        self.assertEqual(self.summarize(value)["status"], "TESTS_PASSED")

    def test_ambiguous_identity_duplicates_and_bad_case_payload(self):
        valid = report(("regression", "passed"))
        for field, bad in (("fullName", "other"), ("fullName", ""), ("ancestorTitles", "contract"),
                           ("ancestorTitles", [[]]), ("title", None),
                           ("failureMessages", None), ("failureMessages", [5]),
                           ("failureMessages", ["hidden failure"])):
            value = copy.deepcopy(valid)
            value["testResults"][0]["assertionResults"][0][field] = bad
            self.assertEqual(self.summarize(value)["status"], "INCONCLUSIVE")
        for duplicate_file in (True, False):
            value = copy.deepcopy(valid)
            duplicate = copy.deepcopy(value["testResults"][0])
            if not duplicate_file:
                duplicate["name"] = "/private/other.test.ts"
            value["testResults"].append(duplicate)
            self.assertEqual(self.summarize(value)["status"], "INCONCLUSIVE")
        failed = report(("regression", "failed"))
        failed["testResults"][0]["assertionResults"][0]["failureMessages"] = [" "]
        self.assertEqual(self.summarize(failed, exit_code=1)["status"], "INCONCLUSIVE")

    def test_exit_signal_and_report_mismatch_preserve_observations(self):
        for value, code in ((report(("regression", "passed")), 1),
                            (report(("regression", "failed")), 0),
                            (report(("regression", "failed")), -9),
                            (report(("regression", "failed")), 2)):
            self.assertEqual(self.summarize(value, exit_code=code)["status"], "INCONCLUSIVE")

    def compare(self, before=None, after=None):
        return native.compare_regression(
            json.dumps(before or report(("regression", "failed"), ("control", "passed"), ("unused", "skipped"))),
            json.dumps(after or report(("regression", "passed"), ("control", "passed"), ("unused", "skipped"))),
            format="vitest-json", baseline_exit=1, candidate_exit=0,
            regressions=["contract regression"], controls=["contract control"])

    def test_matched_selection_preserves_unexecuted_inventory(self):
        result = self.compare()
        self.assertEqual(result["status"], "MATCHED_REGRESSION_OBSERVED")
        self.assertEqual(result["baseline"]["skipped"], 1)
        for cases in ((("regression", "passed"), ("control", "passed")),
                      (("regression", "passed"), ("control", "passed"), ("renamed", "skipped")),
                      (("regression", "passed"), ("control", "passed"), ("unused", "passed")),
                      (("regression", "passed"), ("control", "skipped"), ("unused", "skipped"))):
            with self.subTest(cases=cases):
                self.assertNotEqual(self.compare(after=report(*cases))["status"], "MATCHED_REGRESSION_OBSERVED")

    def test_cli_saved_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            path.write_text(json.dumps(report(("regression", "passed"))), encoding="utf-8")
            result = subprocess.run([sys.executable, "-B", native.__file__, "--log", str(path),
                                     "--format", "vitest-json", "--exit-code", "0",
                                     "--expect-test", "contract regression"],
                                    capture_output=True, text=True, timeout=10, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["executed"], 1)


if __name__ == "__main__":
    unittest.main()
