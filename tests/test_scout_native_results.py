"""Offline accounting controls; never invoke native tools or model code."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import scout_native_results as native

PACKAGE = "example.org/repo/pkg/sync"


def event(action, name=None, package=PACKAGE, **extra):
    value = {"Action": action, "Package": package, **extra}
    if name is not None:
        value["Test"] = name
    return json.dumps(value)


def go_test(name="TestSync", terminal="pass", package=PACKAGE):
    return [event("run", name, package), event(terminal, name, package)]


def go_log(*tests, terminal="pass"):
    return "\n".join([event("start"), *[line for test in tests for line in test], event(terminal)])


def rust_log(*cases, status="ok", passed=None, failed=0, ignored=0, filtered=19):
    if passed is None:
        passed = len(cases) - failed - ignored
    return "\n".join([f"running {len(cases)} tests", *cases,
        (f"test result: {status}. {passed} passed; {failed} failed; {ignored} ignored; "
         f"0 measured; {filtered} filtered out; finished in 0.01s")])


def junit(*cases):
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite", name="pytest", tests=str(len(cases)),
                          failures=str(sum(outcome == "failure" for _, outcome in cases)),
                          errors=str(sum(outcome == "error" for _, outcome in cases)),
                          skipped=str(sum(outcome == "skipped" for _, outcome in cases)))
    for name, outcome in cases:
        case = ET.SubElement(suite, "testcase", classname="tests.test_contract", name=name)
        if outcome:
            ET.SubElement(case, outcome)
    return ET.tostring(root, encoding="unicode")


class NativeResultsTests(unittest.TestCase):
    def go(self, text, exit_code=0, expected_tests=("TestSync",)):
        return native.summarize(text, format="go-json", exit_code=exit_code,
                                package=PACKAGE, expected_tests=expected_tests)

    def rust(self, text, exit_code=0, expected_tests=("table::query",)):
        return native.summarize(text, format="rust-libtest", exit_code=exit_code,
                                expected_tests=expected_tests)

    def junit(self, text, exit_code=0, expected_tests=("tests.test_contract::test_case",)):
        return native.summarize(text, format="pytest-junit", exit_code=exit_code,
                                expected_tests=expected_tests)

    def test_junit_matched_baseline_failure_and_candidate_pass(self):
        before = self.junit(junit(("test_case", "failure"), ("test_other", None)), 1)
        after = self.junit(junit(("test_case", None), ("test_other", None)))
        self.assertEqual(before["status"], "TESTS_FAILED")
        self.assertEqual((before["passed"], before["failed"], before["errors"]), (1, 1, 0))
        self.assertEqual(after["status"], "TESTS_PASSED")
        self.assertEqual(after["executed"], 2)
        self.assertEqual(before["expected_test_results"]["tests.test_contract::test_case"]["failed"], 1)
        self.assertEqual(after["expected_test_results"]["tests.test_contract::test_case"]["passed"], 1)

    def test_junit_single_suite_and_parameterized_names(self):
        text = junit(("test_case[a&b]", None), ("test_other", "skipped"))
        suite = ET.fromstring(text)[0]
        value = self.junit(ET.tostring(suite, encoding="unicode"),
                           expected_tests=("tests.test_contract::test_case[a&b]",))
        self.assertEqual(value["status"], "TESTS_PASSED")
        self.assertEqual((value["passed"], value["skipped"], value["batches"]), (1, 1, 1))

    def test_junit_multiple_flat_suites_without_name_collision(self):
        root = ET.fromstring(junit(("test_case", None)))
        second = ET.fromstring(junit(("test_case", None)))[0]
        second[0].set("classname", "tests.second")
        root.append(second)
        value = self.junit(ET.tostring(root, encoding="unicode"))
        self.assertEqual((value["status"], value["passed"], value["batches"]), ("TESTS_PASSED", 2, 2))

    def test_junit_optional_root_totals_are_checked(self):
        root = ET.fromstring(junit(("test_case", None)))
        root.attrib.update(tests="1", failures="0", errors="0", skipped="0")
        self.assertEqual(self.junit(ET.tostring(root, encoding="unicode"))["status"], "TESTS_PASSED")
        root.set("tests", "2")
        self.assertEqual(self.junit(ET.tostring(root, encoding="unicode"))["status"], "INCONCLUSIVE")

    def test_junit_cardinality_diagnostic_does_not_accept_missing_cases(self):
        root = ET.fromstring(junit(("test_case", None)))
        root[0].set("tests", "13")
        value = self.junit(ET.tostring(root, encoding="unicode"))
        self.assertEqual(value["status"], "INCONCLUSIVE")
        self.assertEqual(value["passed"], 1)
        self.assertIn(
            "JUnit case/summary cardinality mismatch "
            "(testsuite.tests: declared 13, observed 1)",
            value["issues"],
        )

    def test_junit_malformed_counter_is_not_echoed_into_diagnostics(self):
        root = ET.fromstring(junit(("test_case", None)))
        root[0].set("tests", "PRIVATE_COUNTER_TEXT" * 1000)
        value = self.junit(ET.tostring(root, encoding="unicode"))
        self.assertEqual(value["status"], "INCONCLUSIVE")
        self.assertIn(
            "JUnit case/summary cardinality mismatch "
            "(testsuite.tests: declared invalid, observed 1)",
            value["issues"],
        )
        self.assertNotIn("PRIVATE_COUNTER_TEXT", json.dumps(value["issues"]))

    def test_junit_setup_errors_do_not_reproduce_an_assertion_failure(self):
        value = self.junit(junit(("test_case", "error")), 1)
        self.assertEqual(value["status"], "INCONCLUSIVE")
        self.assertEqual((value["errors"], value["failed"], value["executed"]), (1, 0, 0))
        self.assertEqual(value["missing_expected_tests"], ["tests.test_contract::test_case"])

    def test_junit_expected_skip_missing_or_wrong_module_is_not_pass(self):
        for text in (junit(), junit(("test_case", "skipped")), junit(("test_other", None)),
                     junit(("test_case", None)).replace("tests.test_contract", "tests.other")):
            self.assertEqual(self.junit(text)["status"], "INCONCLUSIVE")

    def test_junit_exit_consistency_and_pytest_abnormal_exit(self):
        for text, code in ((junit(("test_case", None)), 1),
                           (junit(("test_case", "failure")), 0),
                           (junit(("test_case", "failure")), 2),
                           (junit(("test_case", "failure")), -9)):
            self.assertEqual(self.junit(text, code)["status"], "INCONCLUSIVE")

    def test_junit_summary_cannot_hide_or_invent_failures(self):
        text = junit(("test_case", None))
        for changed in (text.replace('tests="1"', 'tests="2"'),
                        text.replace('failures="0"', 'failures="1"'),
                        text.replace('errors="0"', 'errors="-1"'),
                        text.replace('skipped="0"', 'skipped="0.0"'),
                        text.replace('tests="1"', ''),
                        junit(("test_case", "failure")).replace('failures="1"', 'failures="0"')):
            self.assertEqual(self.junit(changed)["status"], "INCONCLUSIVE")

    def test_junit_duplicate_or_missing_identity_is_not_pass(self):
        valid = junit(("test_case", None))
        for text in (junit(("test_case", None), ("test_case", None)),
                     valid.replace('classname="tests.test_contract"', ''),
                     valid.replace('name="test_case"', 'name=""')):
            self.assertEqual(self.junit(text)["status"], "INCONCLUSIVE")

    def test_pytest_collection_skip_is_retained_but_never_executed(self):
        root = ET.fromstring(junit(("test_case", None), ("tests.test_optional", "skipped")))
        collection = root[0][1]
        collection.set("classname", "")
        collection[0].set("message", "collection skipped")
        text = ET.tostring(root, encoding="unicode")
        value = self.junit(text)
        self.assertEqual((value["status"], value["passed"], value["skipped"], value["executed"]),
                         ("TESTS_PASSED", 1, 1, 1))
        # A skipped module must not satisfy any declared regression/control.
        missing = self.junit(text, expected_tests=("@collection::tests.test_optional",))
        self.assertEqual(missing["status"], "INCONCLUSIVE")
        self.assertEqual(missing["missing_expected_tests"], ["@collection::tests.test_optional"])

    def test_collection_skip_does_not_relax_other_identity_checks(self):
        for name, message, outcome in (
            ("tests.test_optional", "ordinary skip", "skipped"),
            ("", "collection skipped", "skipped"),
            ("tests::test_optional", "collection skipped", "skipped"),
            ("tests.test_optional", "collection skipped", "failure"),
            ("tests.test_optional", "collection skipped", None),
        ):
            root = ET.fromstring(junit(("test_case", None), (name, outcome)))
            case = root[0][1]
            case.set("classname", "")
            if outcome:
                case[0].set("message", message)
            with self.subTest(name=name, message=message, outcome=outcome):
                self.assertEqual(self.junit(ET.tostring(root, encoding="unicode"),
                                           1 if outcome == "failure" else 0)["status"],
                                 "INCONCLUSIVE")
        root = ET.fromstring(junit(("test_case", None),
                                   ("tests.test_optional", "skipped"),
                                   ("tests.test_optional", "skipped")))
        for case in list(root[0])[1:]:
            case.set("classname", "")
            case[0].set("message", "collection skipped")
        self.assertEqual(self.junit(ET.tostring(root, encoding="unicode"))["status"],
                         "INCONCLUSIVE")

    def test_junit_non_pytest_notrun_status_cannot_be_counted_as_pass(self):
        root = ET.fromstring(junit(("test_case", None)))
        root[0][0].set("status", "notrun")
        self.assertEqual(self.junit(ET.tostring(root, encoding="unicode"))["status"], "INCONCLUSIVE")

    def test_junit_contradictory_outcomes_and_unknown_elements_are_rejected(self):
        for child in ("failure", "error", "skipped", "rerunFailure", "testsuite"):
            root = ET.fromstring(junit(("test_case", "failure")))
            ET.SubElement(root[0][0], child)
            self.assertEqual(self.junit(ET.tostring(root, encoding="unicode"), 1)["status"], "INCONCLUSIVE")

    def test_junit_nested_or_hidden_cases_are_rejected(self):
        valid = junit(("test_case", None))
        root = ET.fromstring(valid)
        properties = ET.SubElement(root[0], "properties")
        ET.SubElement(properties, "testcase", name="test_hidden", classname="tests.hidden")
        hidden = ET.tostring(root, encoding="unicode")
        nested = f'<testsuites><testsuite tests="1" failures="0" errors="0" skipped="0">{valid}</testsuite></testsuites>'
        for text in (hidden, nested, '<unknown/>'):
            self.assertEqual(self.junit(text)["status"], "INCONCLUSIVE")

    def test_junit_malformed_and_entities_are_rejected(self):
        valid = junit(("test_case", None))
        for text in (valid[:-12], "", valid + "junk",
                     '<!DOCTYPE testsuites [<!ENTITY data "expanded">]>' + valid,
                     '<!DOCTYPE testsuites SYSTEM "file:///private">' + valid):
            self.assertEqual(self.junit(text)["status"], "INCONCLUSIVE")

    def test_junit_cli_reads_saved_xml(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.xml"
            path.write_text(junit(("test_case", "failure")), encoding="utf-8")
            result = subprocess.run([sys.executable, "-B", str(Path(native.__file__)), "--log", str(path),
                                     "--format", "pytest-junit", "--exit-code", "1",
                                     "--expect-test", "tests.test_contract::test_case"],
                                    capture_output=True, text=True, timeout=10, check=False)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)["failed"], 1)

    def test_go_real_events_not_output_pass_text(self):
        text = go_log(go_test())
        text += "\n" + event("output", Output="Ran 999 tests; PASS")
        value = self.go(text)
        self.assertEqual(value["status"], "TESTS_PASSED")
        self.assertEqual(value["executed"], 1)

    def test_go_repeats_and_subtests_are_counted_explicitly(self):
        text = go_log([event("run", "TestSync"), *go_test("TestSync/a"), event("pass", "TestSync")], go_test())
        self.assertEqual(self.go(text)["passed"], 3)

    def test_expected_details_do_not_count_parent_or_unrequested_tests(self):
        text = go_log([event("run", "TestSync"), *go_test("TestSync/a"),
                       *go_test("TestSync/b", terminal="skip"), event("pass", "TestSync")],
                      go_test("TestSync/a"), go_test("TestOther"))
        value = self.go(text, expected_tests=("TestSync/a", "TestSync/b", "TestMissing"))
        self.assertEqual(value["status"], "INCONCLUSIVE")
        self.assertEqual(value["passed"], 4)
        self.assertEqual(value["expected_test_results"], {
            "TestSync/a": {"passed": 2, "failed": 0, "skipped": 0},
            "TestSync/b": {"passed": 0, "failed": 0, "skipped": 1},
            "TestMissing": {"passed": 0, "failed": 0, "skipped": 0},
        })

    def test_go_failed_case_in_passing_package_is_contradictory(self):
        value = self.go(go_log(go_test(terminal="fail")))
        self.assertEqual(value["status"], "INCONCLUSIVE")
        self.assertIn("package passed despite reported test failures", value["issues"])
        self.assertEqual(value["expected_test_results"]["TestSync"]["failed"], 1)

    def test_go_unstarted_terminal_does_not_inflate_expected_counts(self):
        value = self.go(go_log(go_test()) + "\n" + event("pass", "TestSync"))
        self.assertEqual(value["status"], "INCONCLUSIVE")
        self.assertEqual(value["expected_test_results"]["TestSync"]["passed"], 1)

    def test_go_paused_parallel_test(self):
        text = go_log([event("run", "TestSync"), event("pause", "TestSync"),
                       event("cont", "TestSync"), event("pass", "TestSync")])
        self.assertEqual(self.go(text)["status"], "TESTS_PASSED")

    def test_go_failure_observed_not_exit_alone(self):
        value = self.go(go_log(go_test(terminal="fail"), terminal="fail"), 1)
        self.assertEqual(value["status"], "TESTS_FAILED")
        self.assertEqual(value["failed"], 1)

    def test_signal_termination_preserves_counts_but_is_inconclusive(self):
        go = go_log(go_test(terminal="fail"), terminal="fail")
        rust = rust_log("test table::query ... FAILED", status="FAILED", failed=1)
        for format, text, target, package in (
            ("go-json", go, "TestSync", PACKAGE),
            ("rust-libtest", rust, "table::query", None),
            ("pytest-junit", junit(("test_case", "failure")),
             "tests.test_contract::test_case", None),
        ):
            for code in (-1, -9, -15):
                with self.subTest(format=format, exit_code=code):
                    value = native.summarize(text, format=format, exit_code=code,
                                             expected_tests=[target], package=package)
                    self.assertEqual(value["status"], "INCONCLUSIVE")
                    self.assertEqual(value["failed"], 1)
                    self.assertEqual(value["expected_test_results"][target]["failed"], 1)
                    self.assertIn("process terminated by signal", value["issues"])

    def test_go_filtered_or_all_skipped_not_pass(self):
        for text in (go_log(), go_log(go_test(terminal="skip"), terminal="skip")):
            self.assertEqual(self.go(text)["status"], "INCONCLUSIVE")

    def test_go_requires_exact_target_package_and_name(self):
        for text in (go_log(go_test("TestOther")), go_log(go_test(package="other/pkg"))):
            self.assertEqual(self.go(text)["status"], "INCONCLUSIVE")

    def test_go_truncated_missing_start_or_final_event(self):
        valid = go_log(go_test()).splitlines()
        for lines in (valid[:-1], valid[1:], [valid[0], valid[1], valid[-1]]):
            self.assertEqual(self.go("\n".join(lines))["status"], "INCONCLUSIVE")

    def test_go_exit_zero_cannot_hide_package_failure(self):
        for text, code in ((go_log(go_test()), 1), (go_log(go_test(terminal="fail"), terminal="fail"), 0),
                           (go_log(go_test(), terminal="fail"), 1)):
            self.assertEqual(self.go(text, code)["status"], "INCONCLUSIVE")

    def test_go_duplicate_and_malformed_events_rejected(self):
        text = go_log(go_test())
        for changed in (text + "\n{broken", text.replace(event("pass", "TestSync"),
                         event("pass", "TestSync") + "\n" + event("pass", "TestSync")), text + "\n" + event("start")):
            self.assertEqual(self.go(changed)["status"], "INCONCLUSIVE")

    def test_go_cached_replayed_result_not_fresh_execution(self):
        text = go_log(go_test()) + "\n" + event("output", Output="ok  example.org/repo/pkg/sync (cached)\n")
        self.assertEqual(self.go(text)["status"], "INCONCLUSIVE")

    def test_go_invalid_action_type_does_not_crash(self):
        text = go_log(go_test()) + "\n" + event([])
        self.assertEqual(self.go(text)["status"], "INCONCLUSIVE")

    def test_rust_pass_ignored_and_multiple_batches(self):
        first = rust_log("test table::query ... ok", "test table::ignored ... ignored, needs a server", ignored=1)
        second = rust_log("test second::case ... ok")
        value = self.rust(first + "\n" + second)
        self.assertEqual(value["status"], "TESTS_PASSED")
        self.assertEqual((value["passed"], value["skipped"], value["batches"]), (2, 1, 2))

    def test_rust_failure_and_exit_mismatch(self):
        text = rust_log("test table::query ... FAILED", status="FAILED", failed=1)
        self.assertEqual(self.rust(text, 101)["status"], "TESTS_FAILED")
        self.assertEqual(self.rust(text)["status"], "INCONCLUSIVE")

    def test_rust_expected_details_across_failed_and_passing_batches(self):
        text = rust_log("test table::query ... FAILED", status="FAILED", failed=1)
        text += "\n" + rust_log("test table::query ... ok", "test table::ignored ... ignored", ignored=1)
        value = self.rust(text, 101, expected_tests=("table::query", "table::ignored"))
        self.assertEqual(value["status"], "INCONCLUSIVE")  # ignored expected target
        self.assertEqual(value["expected_test_results"], {
            "table::query": {"passed": 1, "failed": 1, "skipped": 0},
            "table::ignored": {"passed": 0, "failed": 0, "skipped": 1},
        })

    def test_rust_zero_filtered_or_only_ignored(self):
        for text in (rust_log(), rust_log("test table::query ... ignored", ignored=1)):
            self.assertEqual(self.rust(text)["status"], "INCONCLUSIVE")

    def test_rust_wrong_test_summary_mismatch_or_truncated(self):
        valid = rust_log("test table::query ... ok")
        for text in (valid.replace("table::query", "table::other"), valid.replace("1 passed", "2 passed"),
                     valid.split("test result:")[0], valid.split("\n", 1)[1],
                     valid + "\nrunning 1 test", valid + "\ntest result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s"):
            self.assertEqual(self.rust(text)["status"], "INCONCLUSIVE")

    def test_rust_duplicate_case_or_status_contradiction(self):
        for text in (rust_log("test table::query ... ok", "test table::query ... ok"),
                     rust_log("test table::query ... FAILED", failed=1, status="ok")):
            self.assertEqual(self.rust(text)["status"], "INCONCLUSIVE")

    def test_budget_and_parameter_validation(self):
        text = go_log(go_test())
        for changes in ({"exit_code": True}, {"format": "custom"}, {"expected_tests": []},
                        {"expected_tests": "TestSync"}, {"expected_tests": [True]}, {"package": None},
                        {"text": "x" * (native.MAX_BYTES + 1)}):
            args = {"text": text, "format": "go-json", "exit_code": 0,
                    "package": PACKAGE, "expected_tests": ["TestSync"]}
            args.update(changes)
            with self.assertRaises(ValueError):
                native.summarize(**args)

    def test_cli_reads_only_saved_log_and_returns_inconclusive(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.log"
            path.write_text(rust_log(), encoding="utf-8")
            result = subprocess.run([sys.executable, "-B", str(Path(native.__file__)), "--log", str(path),
                                     "--format", "rust-libtest", "--exit-code", "0", "--expect-test", "table::query"],
                                    capture_output=True, text=True, timeout=10, check=False)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stdout)["executed"], 0)


class RegressionComparisonTests(unittest.TestCase):
    def compare(self, before=None, after=None, **overrides):
        options = {"format": "pytest-junit", "baseline_exit": 1, "candidate_exit": 0,
                   "regressions": ["tests.test_contract::test_case"],
                   "controls": ["tests.test_contract::test_control"]}
        options.update(overrides)
        return native.compare_regression(
            before if before is not None else junit(("test_case", "failure"), ("test_control", None)),
            after if after is not None else junit(("test_case", None), ("test_control", None)),
            **options)

    def test_complete_junit_regression_and_control(self):
        self.assertEqual(self.compare()["status"], "MATCHED_REGRESSION_OBSERVED")

    def test_already_passing_baseline_is_not_a_reproduction(self):
        value = self.compare(before=junit(("test_case", None), ("test_control", None)), baseline_exit=0)
        self.assertEqual(value["status"], "PATTERN_NOT_OBSERVED")

    def test_extra_cases_and_skipped_controls_do_not_match(self):
        for after in (junit(("test_case", None), ("test_control", None), ("test_extra", None)),
                      junit(("test_case", None), ("test_control", "skipped")),
                      junit(("test_case", None))):
            with self.subTest(after=after):
                self.assertNotEqual(self.compare(after=after)["status"], "MATCHED_REGRESSION_OBSERVED")

    def test_failing_control_or_candidate_is_not_a_fix(self):
        value = self.compare(before=junit(("test_case", "failure"), ("test_control", "failure")))
        self.assertEqual(value["status"], "PATTERN_NOT_OBSERVED")
        value = self.compare(after=junit(("test_case", "failure"), ("test_control", None)), candidate_exit=1)
        self.assertEqual(value["status"], "PATTERN_NOT_OBSERVED")

    def test_process_error_or_truncated_report_is_inconclusive(self):
        self.assertEqual(self.compare(candidate_exit=-9)["status"], "INCONCLUSIVE")
        self.assertEqual(self.compare(after="<testsuites>")["status"], "INCONCLUSIVE")

    def test_go_matched_repeats_and_repeat_mismatch(self):
        before = go_log(go_test("TestRegression", terminal="fail"), go_test("TestControl"),
                        go_test("TestRegression", terminal="fail"), go_test("TestControl"), terminal="fail")
        after = go_log(go_test("TestRegression"), go_test("TestControl"),
                       go_test("TestRegression"), go_test("TestControl"))
        options = {"format": "go-json", "package": PACKAGE,
                   "regressions": ["TestRegression"], "controls": ["TestControl"]}
        self.assertEqual(self.compare(before, after, **options)["status"], "MATCHED_REGRESSION_OBSERVED")
        once = go_log(go_test("TestRegression"), go_test("TestControl"))
        self.assertEqual(self.compare(before, once, **options)["status"], "PATTERN_NOT_OBSERVED")

    def test_rust_matched_selection(self):
        before = rust_log("test table::query ... FAILED", "test table::control ... ok", failed=1, status="FAILED")
        after = rust_log("test table::query ... ok", "test table::control ... ok")
        value = self.compare(before, after, format="rust-libtest", baseline_exit=101,
                             regressions=["table::query"], controls=["table::control"])
        self.assertEqual(value["status"], "MATCHED_REGRESSION_OBSERVED")

    def test_missing_duplicate_or_invalid_declarations_rejected(self):
        for options in ({"regressions": []}, {"controls": []}, {"controls": ["tests.test_contract::test_case"]},
                        {"regressions": [""]}, {"controls": [True]}, {"regressions": "case"}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.compare(**options)


if __name__ == "__main__":
    unittest.main()
