"""Observed native reporter fixtures plus adversarial accounting controls."""
import json
import sys
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import scout_native_results as native

FIXTURE = json.loads((Path(__file__).parent / "fixtures/gtest_xml_observed.json").read_text())


class GoogleTestResultsTests(unittest.TestCase):
    def summarize(self, text=None, code=0, expected=("Report::Pass",)):
        return native.summarize(FIXTURE["cases"]["pass"]["xml"] if text is None else text,
                                format="gtest-xml", exit_code=code, expected_tests=expected)

    def mutate(self, edit, *, label="pass", code=0):
        root = ET.fromstring(FIXTURE["cases"][label]["xml"])
        edit(root)
        return self.summarize(ET.tostring(root, encoding="unicode"), code)

    def test_observed_pass(self):
        result = self.summarize()
        self.assertEqual(result["status"], "TESTS_PASSED")
        self.assertEqual((result["executed"], result["disabled"], result["skipped"]), (1, 0, 0))

    def test_observed_multiple_assertions_skip_and_disabled(self):
        report = FIXTURE["cases"]["mixed"]
        result = self.summarize(report["xml"], report["exit_code"])
        self.assertEqual(result["status"], "TESTS_FAILED")
        self.assertEqual((result["passed"], result["failed"], result["executed"]), (1, 1, 2))
        self.assertEqual((result["skipped"], result["disabled"]), (2, 1))

    def test_observed_suite_and_global_setup_failures_are_inconclusive(self):
        for label, expected in (("suite-setup", "SetupFailure::Body"),
                                ("global-setup", "Report::Pass")):
            with self.subTest(label=label):
                value = FIXTURE["cases"][label]
                result = self.summarize(value["xml"], value["exit_code"], (expected,))
                self.assertEqual(result["status"], "INCONCLUSIVE")
                self.assertEqual(result["missing_expected_tests"], [expected])

    def test_expected_skipped_disabled_and_missing_never_pass(self):
        for name in ("Skip", "DISABLED_NotRun", "Missing"):
            result = self.summarize(FIXTURE["cases"]["mixed"]["xml"], 1, ("Report::" + name,))
            self.assertEqual(result["status"], "INCONCLUSIVE")

    def test_exit_status_and_signals_must_agree(self):
        for code in (1, 2, 137, -9):
            self.assertEqual(self.summarize(code=code)["status"], "INCONCLUSIVE")
        self.assertEqual(self.summarize(FIXTURE["cases"]["mixed"]["xml"])["status"], "INCONCLUSIVE")

    def test_root_and_suite_totals_cannot_hide_failures_or_disabled(self):
        for level in (None, 0):
            for key in ("tests", "failures", "disabled", "errors", "skipped"):
                with self.subTest(level=level, key=key):
                    def edit(root):
                        element = root if level is None else root[0]
                        element.set(key, "100")
                    self.assertEqual(self.mutate(edit)["status"], "INCONCLUSIVE")

    def test_required_totals_and_states_cannot_be_omitted(self):
        for key in ("tests", "failures", "disabled", "errors"):
            self.assertEqual(self.mutate(lambda root: root.attrib.pop(key))["status"], "INCONCLUSIVE")
        for key in ("status", "result", "classname", "name"):
            self.assertEqual(self.mutate(lambda root: root[0][0].attrib.pop(key))["status"], "INCONCLUSIVE")

    def test_unknown_and_contradictory_states_are_not_guessed(self):
        for status, result in (("notrun", "completed"), ("run", "suppressed"),
                               ("run", "skipped"), ("pending", "completed")):
            self.assertEqual(self.mutate(lambda root: root[0][0].attrib.update(
                status=status, result=result))["status"], "INCONCLUSIVE")
        for child in ("skipped", "error", "rerunFailure", "testcase"):
            self.assertEqual(self.mutate(lambda root: ET.SubElement(root[0][0], child))["status"], "INCONCLUSIVE")

    def test_invalid_duplicate_and_cross_suite_identities_are_rejected(self):
        for key, value in (("classname", "Other"), ("classname", ""),
                           ("name", ""), ("name", "a::b"), ("name", "x" * 513)):
            self.assertEqual(self.mutate(lambda root: root[0][0].set(key, value))["status"], "INCONCLUSIVE")
        self.assertEqual(self.mutate(lambda root: root[0].append(root[0][0]))["status"], "INCONCLUSIVE")
        self.assertEqual(self.mutate(lambda root: root.append(root[0]))["status"], "INCONCLUSIVE")

    def test_hidden_and_nested_outcomes_are_rejected(self):
        def hidden(root):
            ET.SubElement(ET.SubElement(root[0], "properties"), "testcase", name="hidden")
        self.assertEqual(self.mutate(hidden)["status"], "INCONCLUSIVE")
        self.assertEqual(self.mutate(lambda root: ET.SubElement(
            ET.SubElement(root[0][0], "failure"), "testcase"), code=1)["status"], "INCONCLUSIVE")
        self.assertEqual(self.mutate(lambda root: ET.SubElement(root, "failure"), code=1)["status"], "INCONCLUSIVE")

    def test_truncation_entities_empty_and_other_xml_are_rejected(self):
        text = FIXTURE["cases"]["pass"]["xml"]
        for bad in ("", text[:-20], text.replace("<testsuites", "<!DOCTYPE testsuites><testsuites", 1),
                    '<testsuites tests="0" failures="0" disabled="0" errors="0"/>',
                    '<testsuite tests="1" failures="0" errors="0" skipped="0"/>'):
            self.assertEqual(self.summarize(bad)["status"], "INCONCLUSIVE")

    def test_pytest_parser_still_refuses_gtest_status_attributes(self):
        result = native.summarize(FIXTURE["cases"]["pass"]["xml"], format="pytest-junit",
                                  exit_code=0, expected_tests=["Report::Pass"])
        self.assertEqual(result["status"], "INCONCLUSIVE")

    def test_complete_regression_pattern_and_extra_case_control(self):
        # Derived accounting fixture: add a named regression beside the actual
        # reporter's passing control. This is not a native community bug claim.
        green = ET.fromstring(FIXTURE["cases"]["pass"]["xml"])
        for element in (green, green[0]):
            element.set("tests", "2")
        ET.SubElement(green[0], "testcase", name="Regression/0", classname="Report",
                      status="run", result="completed")
        red = ET.fromstring(ET.tostring(green))
        for element in (red, red[0]):
            element.set("failures", "1")
        ET.SubElement(red[0][-1], "failure", message="expected regression")
        args = dict(format="gtest-xml", baseline_exit=1, candidate_exit=0,
                    regressions=["Report::Regression/0"], controls=["Report::Pass"])
        result = native.compare_regression(ET.tostring(red, encoding="unicode"),
                                          ET.tostring(green, encoding="unicode"), **args)
        self.assertEqual(result["status"], "MATCHED_REGRESSION_OBSERVED")
        for element in (green, green[0]):
            element.set("tests", "3")
        ET.SubElement(green[0], "testcase", name="Extra", classname="Report",
                      status="run", result="completed")
        result = native.compare_regression(ET.tostring(red, encoding="unicode"),
                                          ET.tostring(green, encoding="unicode"), **args)
        self.assertEqual(result["status"], "PATTERN_NOT_OBSERVED")


if __name__ == "__main__":
    unittest.main()
