"""Synthetic accounting controls; native Catch2 replay is separate evidence."""

import copy
import sys
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import scout_native_results as native


def expression(passed=True):
    node = ET.Element("Expression", success=str(passed).lower(), type="CHECK", filename="contract.cpp", line="3")
    ET.SubElement(node, "Original").text = "value == expected"
    ET.SubElement(node, "Expanded").text = "1 == 1" if passed else "1 == 2"
    return node


def case(name="contract", assertions=(True,)):
    node = ET.Element("TestCase", name=name, filename="contract.cpp", line="1", tags="[contract]")
    node.extend(expression(value) for value in assertions)
    ET.SubElement(node, "OverallResult", success=str(all(assertions)).lower())
    return node


def report(*cases):
    root = ET.Element("Catch", name="contract")
    group = ET.SubElement(root, "Group", name="contract")
    group.extend(copy.deepcopy(cases))
    assertions = [item.get("success") == "true" for item in group.iter("Expression")]
    outcomes = [item.find("OverallResult").get("success") == "true" for item in group.findall("TestCase")]
    for parent in (group, root):
        ET.SubElement(parent, "OverallResults", successes=str(sum(assertions)),
                      failures=str(len(assertions) - sum(assertions)), expectedFailures="0")
        ET.SubElement(parent, "OverallResultsCases", successes=str(sum(outcomes)),
                      failures=str(len(outcomes) - sum(outcomes)), expectedFailures="0")
    return root


class Catch2XMLTests(unittest.TestCase):
    def summarize(self, value, code=0, names=("contract",)):
        text = ET.tostring(value, encoding="unicode") if not isinstance(value, str) else value
        return native.summarize(text, format="catch2-v2-xml", exit_code=code, expected_tests=names)

    def test_assertion_counts_do_not_become_case_counts(self):
        result = self.summarize(report(case(assertions=(True, True, True))))
        self.assertEqual((result["status"], result["passed"], result["executed"]), ("TESTS_PASSED", 1, 1))
        self.assertEqual(result["catch2_xml"]["assertions"], {"passed": 3, "failed": 0})

    def test_failed_assertion_count_drives_v2_exit_but_not_failed_cases(self):
        result = self.summarize(report(case(assertions=(False, False, True))), 2)
        self.assertEqual((result["status"], result["failed"], result["executed"]), ("TESTS_FAILED", 1, 1))
        self.assertEqual(result["catch2_xml"]["assertions"], {"passed": 1, "failed": 2})
        capped = self.summarize(report(case(assertions=(False,) * 256)), 255)
        self.assertEqual(capped["status"], "TESTS_FAILED")

    def test_matched_complete_regression_and_controls(self):
        before = report(case("regression", (False, False)), case("control", (True,)))
        after = report(case("regression", (True, True)), case("control", (True,)))
        result = native.compare_regression(ET.tostring(before, encoding="unicode"),
                                          ET.tostring(after, encoding="unicode"),
                                          format="catch2-v2-xml", baseline_exit=2, candidate_exit=0,
                                          regressions=["regression"], controls=["control"])
        self.assertEqual(result["status"], "MATCHED_REGRESSION_OBSERVED")

    def test_repeated_sections_are_not_extra_cases_or_deduplicated_assertions(self):
        node = case(assertions=())
        for _ in range(2):
            section = ET.Element("Section", name="same", filename="contract.cpp", line="4")
            section.append(expression())
            ET.SubElement(section, "OverallResults", successes="1", failures="0", expectedFailures="0")
            node.insert(0, section)
        value = self.summarize(report(node))
        self.assertEqual((value["status"], value["passed"]), ("TESTS_PASSED", 1))
        self.assertEqual(value["catch2_xml"]["assertions"]["passed"], 2)

    def test_messages_and_randomness_do_not_become_outcomes(self):
        node = case()
        ET.SubElement(node[-1], "StdOut").text = "<Failure>not an XML outcome</Failure>"
        node.insert(0, ET.Element("Info"))
        node.insert(0, ET.Element("Warning"))
        root = report(node)
        root.insert(0, ET.Element("Randomness", seed="4294967295"))
        self.assertEqual(self.summarize(root)["status"], "TESTS_PASSED")

    def test_group_root_case_and_section_counter_mismatches_reject(self):
        for scope in (".", "Group"):
            for terminal in ("OverallResults", "OverallResultsCases"):
                for counter in ("successes", "failures", "expectedFailures"):
                    root = report(case())
                    root.find(scope + "/" + terminal).set(counter, "2")
                    with self.subTest(scope=scope, terminal=terminal, counter=counter):
                        self.assertEqual(self.summarize(root)["status"], "INCONCLUSIVE")
        root = report(case())
        root.find("Group/TestCase/OverallResult").set("success", "false")
        self.assertEqual(self.summarize(root)["status"], "INCONCLUSIVE")

    def test_omitted_successful_assertions_are_not_guessed(self):
        root = report(case(assertions=(True, True)))
        node = root.find("Group/TestCase")
        node.remove(node.find("Expression"))
        result = self.summarize(root)
        self.assertEqual(result["status"], "INCONCLUSIVE")
        self.assertTrue(any("include successful assertions" in message for message in result["issues"]))

    def test_abort_or_selection_missing_declared_cases_is_inconclusive(self):
        result = self.summarize(report(case("first", (False,))), 1, ("first", "second"))
        self.assertEqual(result["status"], "INCONCLUSIVE")
        self.assertEqual(result["executed"], 1)
        self.assertEqual(result["missing_expected_tests"], ["second"])

    def test_duplicate_or_missing_identity_and_location_reject(self):
        roots = [report(case(), case())]
        for key, invalid in (("name", ""), ("name", " leading"), ("name", "x" * 513),
                             ("filename", ""), ("line", "0"), ("line", "-1")):
            root = report(case())
            root.find("Group/TestCase").set(key, invalid)
            roots.append(root)
        for root in roots:
            self.assertEqual(self.summarize(root)["status"], "INCONCLUSIVE")

    def test_nonascii_case_names_remain_exact(self):
        result = self.summarize(report(case("契约 & <value>")), names=("契约 & <value>",))
        self.assertEqual(result["status"], "TESTS_PASSED")

    def test_expected_failure_tags_or_totals_never_become_normal_success(self):
        for tag in ("[!mayfail]", "[!shouldfail]"):
            root = report(case())
            root.find("Group/TestCase").set("tags", tag)
            self.assertEqual(self.summarize(root)["status"], "INCONCLUSIVE")
        root = report(case())
        root.find("OverallResults").set("expectedFailures", "1")
        result = self.summarize(root)
        self.assertEqual(result["status"], "INCONCLUSIVE")
        self.assertEqual(result["catch2_xml"]["reported_assertions"]["expectedFailures"], 1)

    def test_unexpected_exception_fatal_and_benchmark_are_not_regressions(self):
        for tag in ("Exception", "FatalErrorCondition", "BenchmarkResults"):
            root = report(case(assertions=(False,)))
            ET.SubElement(root.find("Group/TestCase/Expression"), tag)
            self.assertEqual(self.summarize(root, 1)["status"], "INCONCLUSIVE")

    def test_terminal_missing_duplicate_or_moved_before_cases_rejects(self):
        for path in ("OverallResults", "OverallResultsCases", "Group/OverallResults",
                     "Group/OverallResultsCases", "Group/TestCase/OverallResult"):
            for action in ("remove", "duplicate", "move"):
                root = report(case())
                parent_path, _, name = path.rpartition("/")
                parent = root.find(parent_path) if parent_path else root
                node = parent.find(name)
                if action in {"remove", "move"}:
                    parent.remove(node)
                if action == "duplicate":
                    parent.append(copy.deepcopy(node))
                elif action == "move":
                    parent.insert(0, node)
                with self.subTest(path=path, action=action):
                    self.assertEqual(self.summarize(root)["status"], "INCONCLUSIVE")

    def test_unsupported_version_junit_truncated_and_entity_reports_reject(self):
        for text in ("<Catch2TestRun/>", "<testsuites/>", "<Catch>",
                     '<!DOCTYPE Catch [<!ENTITY data "value">]><Catch/>'):
            self.assertEqual(self.summarize(text)["status"], "INCONCLUSIVE")

    def test_malformed_counter_does_not_echo_arbitrary_payload(self):
        root = report(case())
        root.find("OverallResults").set("successes", "PRIVATE_PAYLOAD" * 100)
        result = self.summarize(root)
        self.assertEqual(result["status"], "INCONCLUSIVE")
        self.assertNotIn("PRIVATE_PAYLOAD", str(result))

    def test_unknown_content_and_conflicting_expression_outcomes_reject(self):
        for path in (".", "Group", "Group/TestCase", "Group/TestCase/Expression"):
            root = report(case())
            ET.SubElement(root.find(path), "Unexpected")
            self.assertEqual(self.summarize(root)["status"], "INCONCLUSIVE")
        root = report(case())
        root.find("Group/TestCase/Expression").set("success", "maybe")
        self.assertEqual(self.summarize(root)["status"], "INCONCLUSIVE")

    def test_exit_mismatch_or_no_cases_cannot_pass(self):
        for root, code in ((report(case()), 1), (report(case(assertions=(False, False))), 1),
                           (report(case(assertions=(False,))), -9), (report(), 0)):
            self.assertEqual(self.summarize(root, code)["status"], "INCONCLUSIVE")


if __name__ == "__main__":
    unittest.main()
