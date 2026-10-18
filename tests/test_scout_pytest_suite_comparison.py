"""Offline full-cohort regression checks; no target code or model execution."""
import sys
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import scout_native_results as native


def report(*cases):
    suite = ET.Element("testsuite", tests=str(len(cases)),
                       failures=str(sum(outcome == "failure" for _, outcome in cases)),
                       errors=str(sum(outcome == "error" for _, outcome in cases)),
                       skipped=str(sum(outcome == "skipped" for _, outcome in cases)))
    for name, outcome in cases:
        case = ET.SubElement(suite, "testcase", classname="tests.contract", name=name)
        if outcome:
            ET.SubElement(case, outcome)
    return ET.tostring(suite, encoding="unicode")


class PytestSuiteComparisonTests(unittest.TestCase):
    def compare(self, before=None, after=None, **changes):
        args = dict(baseline_exit=1, candidate_exit=0,
                    regressions=["tests.contract::regression"], controls=["tests.contract::control"])
        args.update(changes)
        return native.compare_pytest_suite_regression(
            before if before is not None else report(("regression", "failure"), ("control", None), ("optional", "skipped")),
            after if after is not None else report(("regression", None), ("control", None), ("optional", "skipped")),
            **args)

    def test_identical_skipped_cohort_is_not_counted_as_execution(self):
        result = self.compare()
        self.assertEqual(result["status"], "MATCHED_SUITE_REGRESSION_OBSERVED")
        self.assertEqual(result["candidate"]["executed"], 2)
        self.assertEqual(result["candidate"]["skipped"], 1)

    def test_order_does_not_change_inventory(self):
        value = self.compare(after=report(("optional", "skipped"), ("control", None), ("regression", None)))
        self.assertEqual(value["status"], "MATCHED_SUITE_REGRESSION_OBSERVED")

    def test_collection_skip_is_stable_not_executed_coverage(self):
        def add_collection(xml):
            suite = ET.fromstring(xml)
            suite.set("tests", "4")
            suite.set("skipped", "2")
            case = ET.SubElement(suite, "testcase", name="optional_backend")
            ET.SubElement(case, "skipped", message="collection skipped").text = "package unavailable"
            return ET.tostring(suite, encoding="unicode")
        before = add_collection(report(("regression", "failure"), ("control", None), ("optional", "skipped")))
        after = add_collection(report(("regression", None), ("control", None), ("optional", "skipped")))
        result = self.compare(before, after)
        self.assertEqual(result["status"], "MATCHED_SUITE_REGRESSION_OBSERVED")
        self.assertEqual(result["candidate"]["executed"], 2)
        self.assertEqual(result["candidate"]["case_inventory"]["@collection::optional_backend"]["outcome"], "skipped")

    def test_nested_skip_content_is_not_silently_ignored(self):
        after = report(("regression", None), ("control", None), ("optional", "skipped"))
        after = after.replace("<skipped />", "<skipped><extra /></skipped>")
        self.assertEqual(self.compare(after=after)["status"], "INCONCLUSIVE")

    def test_identically_merged_collection_events_cannot_qualify_a_fix(self):
        def merged_collection(xml):
            suite = ET.fromstring(xml)
            suite.set("tests", "4")
            suite.set("skipped", "2")
            case = ET.SubElement(suite, "testcase", name="sample")
            for _ in range(2):
                ET.SubElement(case, "skipped", message="collection skipped")
            return ET.tostring(suite, encoding="unicode")

        before = merged_collection(report(("regression", "failure"), ("control", None)))
        after = merged_collection(report(("regression", None), ("control", None)))
        self.assertEqual(self.compare(before, after)["status"], "INCONCLUSIVE")

    def test_missing_or_extra_case_is_not_a_matched_suite(self):
        for after in (report(("regression", None), ("control", None)),
                      report(("regression", None), ("control", None), ("optional", "skipped"), ("extra", None))):
            with self.subTest(after=after):
                self.assertEqual(self.compare(after=after)["status"], "PATTERN_NOT_OBSERVED")

    def test_undeclared_skip_and_execution_transitions_rejected(self):
        for before, after in ((report(("regression", "failure"), ("control", None), ("optional", None)), None),
                              (None, report(("regression", None), ("control", None), ("optional", None)))):
            with self.subTest(before=before):
                self.assertEqual(self.compare(before=before, after=after)["status"], "PATTERN_NOT_OBSERVED")

    def test_skip_reason_and_xfail_type_must_match(self):
        original = report(("regression", "failure"), ("control", None), ("optional", "skipped"))
        candidate = report(("regression", None), ("control", None), ("optional", "skipped"))
        for attributes in ('message="different platform"', 'type="pytest.xfail"'):
            with self.subTest(attributes=attributes):
                changed = candidate.replace("<skipped", "<skipped " + attributes)
                self.assertEqual(self.compare(original, changed)["status"], "PATTERN_NOT_OBSERVED")
        changed = candidate.replace("<skipped />", "<skipped>new reason</skipped>")
        self.assertEqual(self.compare(original, changed)["status"], "PATTERN_NOT_OBSERVED")
        empty = original.replace("<skipped />", '<skipped message="">old reason</skipped>')
        changed = candidate.replace("<skipped />", '<skipped message="">new reason</skipped>')
        self.assertEqual(self.compare(empty, changed)["status"], "PATTERN_NOT_OBSERVED")

    def test_explicit_skip_reason_not_volatile_source_location_is_compared(self):
        before = report(("regression", "failure"), ("control", None), ("optional", "skipped"))
        after = report(("regression", None), ("control", None), ("optional", "skipped"))
        before = before.replace("<skipped />", '<skipped type="pytest.skip" message="Windows only">/baseline/tests.py:8</skipped>')
        after = after.replace("<skipped />", '<skipped type="pytest.skip" message="Windows only">/candidate/tests.py:8</skipped>')
        result = self.compare(before, after)
        self.assertEqual(result["status"], "MATCHED_SUITE_REGRESSION_OBSERVED")
        self.assertIn("/baseline/", result["baseline"]["case_inventory"]["tests.contract::optional"]["skip_text"])
        self.assertEqual(self.compare(before, after.replace("Windows only", "package missing"))["status"], "PATTERN_NOT_OBSERVED")

    def test_skipped_regression_or_control_is_inconclusive(self):
        for name in ("regression", "control"):
            after = report(("regression", "skipped" if name == "regression" else None),
                           ("control", "skipped" if name == "control" else None), ("optional", "skipped"))
            self.assertEqual(self.compare(after=after)["status"], "INCONCLUSIVE")

    def test_additional_baseline_failure_is_not_hidden(self):
        for after_outcome, candidate_exit in ((None, 0), ("failure", 1)):
            value = self.compare(
                before=report(("regression", "failure"), ("control", None), ("optional", "failure")),
                after=report(("regression", None), ("control", None), ("optional", after_outcome)),
                candidate_exit=candidate_exit)
            self.assertEqual(value["status"], "PATTERN_NOT_OBSERVED")

    def test_no_baseline_reproduction_or_new_candidate_failure_rejected(self):
        self.assertEqual(self.compare(before=report(("regression", None), ("control", None), ("optional", "skipped")),
                                      baseline_exit=0)["status"], "PATTERN_NOT_OBSERVED")
        self.assertEqual(self.compare(after=report(("regression", None), ("control", "failure"), ("optional", "skipped")),
                                      candidate_exit=1)["status"], "PATTERN_NOT_OBSERVED")

    def test_invalid_reports_and_abnormal_exits_abstain(self):
        for after in ("<testsuite>", report(("regression", None), ("control", None), ("control", None)),
                      report(("regression", None), ("control", None)).replace('tests="2"', 'tests="3"'),
                      report(("regression", None), ("control", None), ("setup", "error"))):
            self.assertEqual(self.compare(after=after)["status"], "INCONCLUSIVE")
        self.assertEqual(self.compare(candidate_exit=-9)["status"], "INCONCLUSIVE")
        self.assertEqual(self.compare(candidate_exit=2)["status"], "INCONCLUSIVE")

    def test_existing_strict_api_and_summary_default_unchanged(self):
        before = report(("regression", "failure"), ("control", None), ("optional", "skipped"))
        after = report(("regression", None), ("control", None), ("optional", "skipped"))
        old = native.compare_regression(before, after, format="pytest-junit", baseline_exit=1, candidate_exit=0,
                                        regressions=["tests.contract::regression"], controls=["tests.contract::control"])
        self.assertEqual(old["status"], "PATTERN_NOT_OBSERVED")
        plain = native.summarize(after, format="pytest-junit", exit_code=0, expected_tests=["tests.contract::control"])
        self.assertNotIn("case_inventory", plain)

    def test_invalid_declarations_and_nonpytest_inventory_rejected(self):
        for changes in ({"regressions": []}, {"controls": []}, {"controls": ["tests.contract::regression"]},
                        {"regressions": "regression"}, {"controls": [True]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.compare(**changes)
        with self.assertRaises(ValueError):
            native.summarize("", format="node-tap", exit_code=0, expected_tests=["test"], include_inventory=True)


if __name__ == "__main__":
    unittest.main()
