"""Conservative Catch2 v2 XML accounting, qualified with v2.13.10.

Use the native XML reporter with successful assertions included. This is not
JUnit, discovery, executable provenance or test-quality verification. V3 and
expected-failure/exception/fatal/benchmark semantics are not qualified here.
"""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET


def summarize(text, exit_code, expected_results, issue):
    counts = dict(passed=0, failed=0, skipped=0, errors=0)
    metadata = {"producer_scope": "Catch2 v2 XML; native replay on 2.13.10",
                "accounting_complete": False,
                "reported_assertions": None, "reported_test_cases": None}

    def require(condition, message):
        if not condition:
            raise ValueError(message)

    def attributes(node, allowed, required=()):
        require(set(node.attrib) <= set(allowed) and set(required) <= set(node.attrib),
                "unsupported Catch2 v2 attributes")

    def single(parent, tag):
        nodes = parent.findall(tag)
        require(len(nodes) == 1, "missing or duplicate Catch2 v2 terminal")
        return nodes[0]

    def counter(node):
        attributes(node, ("successes", "failures", "expectedFailures", "durationInSeconds"),
                   ("successes", "failures", "expectedFailures"))
        require(not list(node), "nested Catch2 v2 counter content")
        values = {}
        for key in ("successes", "failures", "expectedFailures"):
            raw = node.get(key, "")
            require(re.fullmatch(r"[0-9]{1,8}", raw) is not None, "invalid Catch2 v2 counter")
            values[key] = int(raw)
        return values

    def plain(node):
        require(not list(node), "unsupported nested Catch2 v2 message")

    def location(node):
        require(bool(node.get("filename"))
                and re.fullmatch(r"[1-9][0-9]{0,7}", node.get("line", "")) is not None,
                "missing or invalid Catch2 v2 source location")

    def body(node, depth=0):
        require(depth <= 32, "Catch2 v2 section nesting exceeds 32 levels")
        passed, failed = 0, 0
        for child in node:
            if child.tag == "Section":
                attributes(child, ("name", "filename", "line"), ("name", "filename", "line"))
                require(bool(child.get("name")), "missing Catch2 v2 section name")
                location(child)
                subpass, subfail = body(child, depth + 1)
                terminal = single(child, "OverallResults")
                require(child[-1] is terminal, "Catch2 v2 section terminal is not last")
                declared = counter(terminal)
                require(declared["expectedFailures"] == 0,
                        "Catch2 v2 expected-failure semantics are not qualified")
                require((declared["successes"], declared["failures"]) == (subpass, subfail),
                        "Catch2 v2 section/assertion cardinality mismatch")
                passed += subpass
                failed += subfail
            elif child.tag == "Expression":
                attributes(child, ("success", "type", "filename", "line"),
                           ("success", "type", "filename", "line"))
                require(child.get("success") in {"true", "false"},
                        "invalid Catch2 v2 expression outcome")
                location(child)
                require(all(part.tag in {"Original", "Expanded"} for part in child),
                        "Catch2 v2 exception/fatal or other assertion semantics are not qualified")
                for tag in ("Original", "Expanded"):
                    part = single(child, tag)
                    attributes(part, ())
                    plain(part)
                passed += child.get("success") == "true"
                failed += child.get("success") == "false"
            elif child.tag == "Failure":
                attributes(child, ("filename", "line"), ("filename", "line"))
                location(child)
                plain(child)
                failed += 1
            elif child.tag in {"Info", "Warning"}:
                attributes(child, ())
                plain(child)
            elif child.tag in {"OverallResults", "OverallResult"}:
                # Only the direct container terminal is allowed, not both kinds.
                require(child.tag == ("OverallResults" if node.tag == "Section" else "OverallResult"),
                        "unexpected Catch2 v2 body terminal")
            else:
                raise ValueError("unsupported Catch2 v2 body or exception/fatal/benchmark semantics")
        return passed, failed

    def totals(parent, observed_cases, observed_assertions):
        reported_cases = counter(single(parent, "OverallResultsCases"))
        reported_assertions = counter(single(parent, "OverallResults"))
        require([child.tag for child in parent][-2:] == ["OverallResults", "OverallResultsCases"],
                "Catch2 v2 terminal is not last")
        require(reported_cases["expectedFailures"] == reported_assertions["expectedFailures"] == 0,
                "Catch2 v2 expected-failure semantics are not qualified")
        require((reported_cases["successes"], reported_cases["failures"]) == observed_cases,
                "Catch2 v2 case/terminal cardinality mismatch")
        require((reported_assertions["successes"], reported_assertions["failures"]) == observed_assertions,
                "Catch2 v2 assertion/terminal cardinality mismatch; include successful assertions")

    seen = set()
    outcomes = {}
    try:
        require(re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", text, re.IGNORECASE) is None,
                "Catch2 v2 DTD/entity declarations are unsupported")
        root = ET.fromstring(text)
        require(root.tag == "Catch", "unsupported Catch2 XML root/version")
        attributes(root, ("name", "filters"))
        # Retain declared units even if an unsupported outcome later rejects.
        root_assertions = counter(single(root, "OverallResults"))
        root_cases = counter(single(root, "OverallResultsCases"))
        metadata["reported_assertions"] = root_assertions
        metadata["reported_test_cases"] = root_cases
        require(root_assertions["expectedFailures"] == root_cases["expectedFailures"] == 0,
                "Catch2 v2 expected-failure semantics are not qualified")
        groups = root.findall("Group")
        require(bool(groups), "missing Catch2 v2 group")
        require(all(child.tag in {"Group", "Randomness", "OverallResults", "OverallResultsCases"}
                    for child in root), "unsupported Catch2 v2 root content")
        random = root.findall("Randomness")
        require(len(random) <= 1, "duplicate Catch2 v2 randomness")
        for node in random:
            attributes(node, ("seed",), ("seed",))
            require(re.fullmatch(r"[0-9]{1,10}", node.get("seed", "")) is not None
                    and int(node.get("seed")) < 2 ** 32 and not list(node),
                    "invalid Catch2 v2 randomness")
        total_passed, total_failed = 0, 0
        for group in groups:
            attributes(group, ("name",))
            require(all(child.tag in {"TestCase", "OverallResults", "OverallResultsCases"}
                        for child in group), "unsupported Catch2 v2 group content")
            group_passed, group_failed, assertion_passed, assertion_failed = 0, 0, 0, 0
            for case in group.findall("TestCase"):
                attributes(case, ("name", "description", "tags", "filename", "line"),
                           ("name", "filename", "line"))
                name = case.get("name", "")
                require(bool(name) and name == name.strip() and len(name) <= 512 and name not in outcomes,
                        "missing, overlong or duplicate Catch2 v2 case identity")
                require(not re.search(r"\[!(?:mayfail|shouldfail)\]", case.get("tags", "")),
                        "Catch2 v2 expected-failure tags are not qualified")
                location(case)
                passed, failed = body(case)
                terminal = single(case, "OverallResult")
                require(case[-1] is terminal, "Catch2 v2 case terminal is not last")
                attributes(terminal, ("success", "durationInSeconds"), ("success",))
                require(terminal.get("success") in {"true", "false"}
                        and (terminal.get("success") == "true") == (failed == 0),
                        "Catch2 v2 case/assertion outcome mismatch")
                require(all(child.tag in {"StdOut", "StdErr"} for child in terminal),
                        "unsupported Catch2 v2 terminal content")
                for child in terminal:
                    attributes(child, ())
                    plain(child)
                outcome = "failed" if failed else "passed"
                outcomes[name] = outcome
                group_passed += not failed
                group_failed += bool(failed)
                assertion_passed += passed
                assertion_failed += failed
            totals(group, (group_passed, group_failed), (assertion_passed, assertion_failed))
            total_passed += assertion_passed
            total_failed += assertion_failed
        passed_cases = sum(outcome == "passed" for outcome in outcomes.values())
        failed_cases = sum(outcome == "failed" for outcome in outcomes.values())
        totals(root, (passed_cases, failed_cases), (total_passed, total_failed))
        require(exit_code == min(root_assertions["failures"], 255),
                "Catch2 v2 exit/failed-assertion count mismatch")
        counts.update(passed=passed_cases, failed=failed_cases)
        seen = set(outcomes)
        for name, outcome in outcomes.items():
            if name in expected_results:
                expected_results[name][outcome] += 1
        metadata["assertions"] = {"passed": total_passed, "failed": total_failed}
        metadata["accounting_complete"] = True
        return counts, seen, len(groups), "fail" if failed_cases else "pass", metadata
    except (ValueError, ET.ParseError, RecursionError) as error:
        issue(str(error) if isinstance(error, ValueError) and not isinstance(error, ET.ParseError)
              else "malformed or truncated Catch2 v2 XML")
        return counts, seen, 0, None, metadata
