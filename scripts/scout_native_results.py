"""Summarize saved native test observations; never run code or qualify a PR.

Logs can be forged. This is a bounded accounting check on controller-captured
output, not an execution attestation, sandbox or semantic test-quality judgment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from xml.etree import ElementTree

try:
    from .scout_bun_junit import summarize as summarize_bun_junit
except ImportError:
    from scout_bun_junit import summarize as summarize_bun_junit

MAX_BYTES = 2 * 1024 * 1024
FORMATS = ("go-json", "rust-libtest", "pytest-junit", "gtest-xml", "node-tap", "vitest-json", "bun-junit")
RUST_SUMMARY = re.compile(
    r"test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; "
    r"(\d+) measured; (\d+) filtered out; finished in [0-9.]+s"
)


def _node_tap(text, exit_code, expected_results, issue):
    """Node's built-in TAP reporter, not arbitrary TAP or YAML.

    Node 24 emits a typed diagnostic for every point. Suites are containers;
    ordinary parent tests count as tests as well as their children. Identities
    use emitted (TAP-escaped) names joined with ::, never lossy name decoding.
    """
    counts = {"passed": 0, "failed": 0, "skipped": 0, "todo": 0,
              "cancelled": 0, "suites": 0}
    seen, identities = set(), set()
    lines = [line for line in text.splitlines() if line.strip()]
    position = 0

    def fail(message):
        raise ValueError(message)

    def peek():
        return lines[position] if position < len(lines) else ""

    def block(depth, path):
        nonlocal position
        if depth > 32:
            fail("Node TAP nesting exceeds 32 levels")
        prefix, points, any_failed = " " * (depth * 4), 0, False
        while True:
            line = peek()
            plan = re.fullmatch(re.escape(prefix) + r"1\.\.([0-9]{1,8})", line)
            if plan:
                position += 1
                if int(plan[1]) != points:
                    fail("Node TAP plan/point cardinality mismatch")
                return any_failed
            declaration = prefix + "# Subtest: "
            if not line.startswith(declaration):
                # Reporter diagnostics are comments, not case outcomes. Reserved
                # terminal fields cannot occur before the root plan.
                if line.startswith(prefix + "# ") and not re.match(
                    re.escape(prefix) + r"# (?:Subtest:|tests\b|suites\b|pass\b|fail\b|"
                    r"cancelled\b|skipped\b|todo\b|duration_ms\b)", line
                ):
                    position += 1
                    continue
                fail("missing or unsupported Node TAP declaration/plan")
            name = line[len(declaration):]
            if not name or "::" in name:
                fail("ambiguous Node TAP case identity")
            qualified = "::".join((*path, name))
            if len(qualified) > 512 or qualified in identities:
                fail("overlong or duplicate Node TAP case identity")
            identities.add(qualified)
            position += 1
            child_prefix = prefix + "    "
            children = peek().startswith((child_prefix + "# Subtest: ", child_prefix + "1.."))
            child_failed = block(depth + 1, (*path, name)) if children else False
            point = re.fullmatch(re.escape(prefix) + r"(ok|not ok) ([0-9]{1,8}) - (.*)", peek())
            if not point or int(point[2]) != points + 1:
                fail("missing or nonconsecutive Node TAP point")
            if not point[3].startswith(name):
                fail("Node TAP declaration/point name mismatch")
            suffix = point[3][len(name):]
            directive = re.fullmatch(r" # (SKIP|TODO)(?: .*)?", suffix) if suffix else None
            if suffix and not directive:
                fail("unsupported Node TAP name/directive")
            position += 1
            diagnostic_prefix = prefix + "  "
            if peek() != diagnostic_prefix + "---":
                fail("missing Node TAP typed diagnostic")
            position += 1
            fields = {}
            while peek() != diagnostic_prefix + "...":
                line = peek()
                if not line or not line.startswith(diagnostic_prefix):
                    fail("truncated Node TAP diagnostic")
                for field in ("type", "failureType"):
                    if line.startswith(diagnostic_prefix + field + ":"):
                        match = re.fullmatch(
                            re.escape(diagnostic_prefix + field) + r": (?:'([A-Za-z]+)'|([A-Za-z]+))", line)
                        if not match or field in fields:
                            fail("unsupported or duplicate Node TAP diagnostic field")
                        fields[field] = match[1] or match[2]
                position += 1
            position += 1
            kind, failure = fields.get("type"), fields.get("failureType")
            if kind not in {"test", "suite"}:
                fail("unsupported or missing Node TAP point type")
            failed = point[1] == "not ok"
            if failed != bool(failure):
                fail("Node TAP point/failure diagnostic mismatch")
            if child_failed and not failed:
                fail("Node TAP parent passed despite a failed child")
            if failure == "subtestsFailed" and not child_failed:
                fail("Node TAP subtestsFailed without an observed failing child")
            cancelled = failure in {"cancelledByParent", "testTimeoutFailure"}
            if cancelled or (failure and failure not in {"testCodeFailure", "subtestsFailed"}):
                issue("Node cancellation/setup/runner failures are not assertion-failure reproductions")
            if kind == "suite":
                counts["suites"] += 1
                if failed and failure != "subtestsFailed":
                    issue("Node suite failed outside its reported tests")
            else:
                if directive:
                    outcome = "skipped"
                    counts["todo"] += directive[1] == "TODO"
                elif cancelled:
                    outcome = None
                    counts["cancelled"] += 1
                else:
                    outcome = "failed" if failed else "passed"
                if outcome:
                    counts[outcome] += 1
                    if qualified in expected_results:
                        expected_results[qualified][outcome] += 1
                    if outcome != "skipped":
                        seen.add(qualified)
            points += 1
            any_failed |= failed and not directive

    terminal, batches = None, 0
    try:
        if peek() != "TAP version 13":
            fail("missing Node TAP version header")
        position += 1
        failed = block(0, ())
        summary = {}
        for field in ("tests", "suites", "pass", "fail", "cancelled", "skipped", "todo", "duration_ms"):
            pattern = r"[0-9]+(?:\.[0-9]+)?" if field == "duration_ms" else r"[0-9]{1,8}"
            match = re.fullmatch(r"# " + field + " (" + pattern + r")", peek())
            if not match:
                fail("missing, reordered or invalid Node TAP terminal summary")
            summary[field] = float(match[1]) if field == "duration_ms" else int(match[1])
            position += 1
        if position != len(lines):
            fail("unexpected output after Node TAP terminal summary")
        expected = {"tests": counts["passed"] + counts["failed"] + counts["skipped"] + counts["cancelled"],
                    "suites": counts["suites"], "pass": counts["passed"], "fail": counts["failed"],
                    "cancelled": counts["cancelled"], "skipped": counts["skipped"] - counts["todo"],
                    "todo": counts["todo"]}
        if any(summary[key] != value for key, value in expected.items()):
            fail("Node TAP case/summary cardinality mismatch")
        terminal, batches = ("fail" if failed else "pass"), 1
    except ValueError as error:
        issue(str(error))
    if exit_code not in {0, 1}:
        issue("Node did not exit normally with pass or test-failure status")
    return counts, seen, batches, terminal


def _junit(text, exit_code, expected_results, issue, inventory=None):
    """Conservative flat pytest JUnit accounting, with qualified case names."""
    counts = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0}
    seen, names = set(), set()
    suites = []
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", text, re.IGNORECASE):
        issue("JUnit DTD/entity declarations are unsupported")
        return counts, seen, 0, None
    try:
        root = ElementTree.fromstring(text)
    except (ElementTree.ParseError, ValueError, RecursionError):
        issue("malformed or truncated JUnit XML")
        return counts, seen, 0, None
    if root.tag == "testsuite":
        suites = [root]
    elif root.tag == "testsuites" and all(child.tag == "testsuite" for child in root):
        suites = list(root)
    else:
        issue("unsupported JUnit root or nested suites")

    def check_totals(element, actual):
        for attribute, key in (("tests", None), ("failures", "failed"),
                               ("errors", "errors"), ("skipped", "skipped")):
            value = element.get(attribute, "")
            total = sum(actual.values()) if key is None else actual[key]
            valid = re.fullmatch(r"[0-9]{1,8}", value)
            if not valid or int(value) != total:
                declared = int(value) if valid else "invalid"
                issue(
                    "JUnit case/summary cardinality mismatch "
                    f"({element.tag}.{attribute}: declared {declared}, observed {total})"
                )

    for suite in suites:
        observed = dict.fromkeys(counts, 0)
        for case in suite:
            if case.tag in {"properties", "system-out", "system-err"}:
                continue
            if case.tag != "testcase":
                issue("unsupported JUnit suite child")
                continue
            classname, name = case.get("classname", ""), case.get("name", "")
            outcomes = [child.tag for child in case if child.tag in {"failure", "error", "skipped"}]
            # pytest emits one classless record for a module-level skip. It is
            # a skipped collection event, never an executed test identity.
            collection_skip = (
                not classname and outcomes == ["skipped"]
                and case.find("skipped").get("message") == "collection skipped"
                and re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", name)
            )
            qualified = f"@collection::{name}" if collection_skip else f"{classname}::{name}"
            if not (classname or collection_skip) or not name or len(qualified) > 512 or qualified in names:
                issue("missing, overlong or duplicate JUnit case identity")
            if "status" in case.attrib:
                issue("non-pytest JUnit status attributes are unsupported")
            names.add(qualified)
            if len(outcomes) > 1 or any(child.tag not in {
                "failure", "error", "skipped", "properties", "system-out", "system-err"
            } for child in case):
                issue("unsupported or contradictory JUnit case outcomes")
            outcome = {"failure": "failed", "error": "errors", "skipped": "skipped"}.get(
                outcomes[0] if outcomes else None, "passed")
            if inventory is not None:
                inventory[qualified] = {"outcome": outcome}
                if outcome == "skipped":
                    skipped = case.find("skipped")
                    if list(skipped):
                        issue("nested JUnit skip content is unsupported")
                    inventory[qualified]["skip_attributes"] = dict(skipped.attrib)
                    inventory[qualified]["skip_text"] = skipped.text or ""
            observed[outcome] += 1
            if outcome in {"passed", "failed"}:
                seen.add(qualified)
            if qualified in expected_results and outcome != "errors":
                expected_results[qualified][outcome] += 1
        check_totals(suite, observed)
        for key in counts:
            counts[key] += observed[key]
    if sum(1 for _ in root.iter("testcase")) != sum(counts.values()):
        issue("JUnit contains cases outside supported suite structure")
    if root.tag == "testsuites" and any(key in root.attrib for key in ("tests", "failures", "errors", "skipped")):
        check_totals(root, counts)
    if counts["errors"]:
        issue("JUnit setup/collection/teardown errors are not assertion-failure reproductions")
    if exit_code not in {0, 1}:
        issue("pytest did not exit normally with pass or test-failure status")
    terminal = "fail" if counts["failed"] or counts["errors"] else "pass"
    return counts, seen, len(suites), terminal


def _gtest_xml(text, exit_code, expected_results, issue):
    """GoogleTest 1.17 XML, not interchangeable with pytest JUnit.

    Multiple assertion failures count as one failed test. Disabled/suppressed
    and runtime-skipped tests never count as executed. Unnamed ad-hoc suite or
    global failures are inconclusive, not reproductions of named assertions.
    """
    counts = {"passed": 0, "failed": 0, "skipped": 0, "disabled": 0}
    seen, names = set(), set()
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", text, re.IGNORECASE):
        issue("GoogleTest DTD/entity declarations are unsupported")
        return counts, seen, 0, None
    try:
        root = ElementTree.fromstring(text)
    except (ElementTree.ParseError, ValueError, RecursionError):
        issue("malformed or truncated GoogleTest XML")
        return counts, seen, 0, None
    if root.tag != "testsuites" or any(s.tag != "testsuite" for s in root):
        issue("unsupported GoogleTest root or suite structure")
        return counts, seen, 0, None

    def totals(element, actual, *, root=False):
        expected = {"tests": actual["passed"] + actual["failed"] + actual["skipped"],
                    "failures": actual["failed"], "disabled": actual["disabled"],
                    "errors": 0, "skipped": actual["skipped"] - actual["disabled"]}
        for field, value in expected.items():
            if root and field == "skipped" and field not in element.attrib:
                continue  # The observed reporter omits the root skipped total.
            reported = element.get(field, "")
            if not re.fullmatch(r"[0-9]{1,8}", reported) or int(reported) != value:
                issue("GoogleTest case/summary cardinality mismatch")

    suite_names = set()
    for suite in root:
        suite_name = suite.get("name", "")
        if not suite_name or suite_name in suite_names or "::" in suite_name:
            issue("missing, ambiguous or duplicate GoogleTest suite identity")
        suite_names.add(suite_name)
        observed = dict.fromkeys(counts, 0)
        for case in suite:
            if case.tag != "testcase":
                issue("unsupported GoogleTest suite child")
                continue
            classname, name = case.get("classname", ""), case.get("name", "")
            qualified = f"{classname}::{name}"
            if (not classname or not name or classname != suite_name or "::" in name
                    or len(qualified) > 512 or qualified in names):
                issue("missing, ambiguous or duplicate GoogleTest case identity; possible setup failure")
            names.add(qualified)
            children = [child.tag for child in case]
            if any(child not in {"failure", "skipped"} for child in children) or any(
                len(child) for child in case
            ):
                issue("unsupported or nested GoogleTest case outcome")
            failures, skips = children.count("failure"), children.count("skipped")
            state = (case.get("status"), case.get("result"))
            if state == ("run", "completed") and not skips:
                outcome = "failed" if failures else "passed"
            elif state == ("run", "skipped") and skips == 1 and not failures:
                outcome = "skipped"
            elif state == ("notrun", "suppressed") and not children:
                outcome = "skipped"
                observed["disabled"] += 1
            else:
                issue("unsupported or contradictory GoogleTest execution state")
                continue
            observed[outcome] += 1
            if outcome != "skipped":
                seen.add(qualified)
            if qualified in expected_results:
                expected_results[qualified][outcome] += 1
        totals(suite, observed)
        for key in counts:
            counts[key] += observed[key]
    totals(root, counts, root=True)
    if sum(1 for _ in root.iter("testcase")) != counts["passed"] + counts["failed"] + counts["skipped"]:
        issue("GoogleTest contains cases outside supported suite structure")
    if exit_code not in {0, 1}:
        issue("GoogleTest did not exit normally with pass or test-failure status")
    return counts, seen, len(root), "fail" if counts["failed"] else "pass"


def _vitest(text, exit_code, expected_results, issue):
    """Observed Vitest 4 JSON, not arbitrary Jest output or a test oracle.

    Skipped and filtered-out cases share a status in this reporter. Retain them
    all, require named targets to execute, and bind the complete name inventory
    when comparing arms. Pending/run/queued observations are not terminal tests.
    """
    counts = {"passed": 0, "failed": 0, "skipped": 0}
    seen, names, files = set(), set(), set()
    observed = dict.fromkeys(("passed", "failed", "skipped", "todo"), 0)
    metadata = {"unselected_unexecuted": 0, "reported_total_tests": 0,
                "case_inventory_sha256": None}

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError(value)

    try:
        report = json.loads(text, object_pairs_hook=pairs, parse_constant=reject_constant)
    except (ValueError, RecursionError):
        issue("malformed or truncated Vitest JSON")
        return counts, seen, 0, None, metadata
    if not isinstance(report, dict) or not isinstance(report.get("testResults"), list):
        issue("invalid Vitest report root")
        return counts, seen, 0, None, metadata
    suites = report["testResults"]
    fields = ("numTotalTests", "numPassedTests", "numFailedTests", "numPendingTests",
              "numTodoTests", "numTotalTestSuites", "numPassedTestSuites",
              "numFailedTestSuites", "numPendingTestSuites")
    if any(type(report.get(key)) is not int or not 0 <= report[key] <= 100000
           for key in fields) or type(report.get("success")) is not bool:
        issue("invalid or missing Vitest terminal totals")
        return counts, seen, 0, None, metadata
    for suite in suites:
        if not isinstance(suite, dict):
            issue("invalid Vitest test file")
            continue
        filename = suite.get("name")
        if not isinstance(filename, str) or not filename or filename in files:
            issue("missing or duplicate Vitest test-file identity")
        else:
            files.add(filename)
        cases = suite.get("assertionResults")
        if not isinstance(cases, list):
            issue("missing Vitest assertion results")
            continue
        file_failed = False
        for case in cases:
            if not isinstance(case, dict):
                issue("invalid Vitest assertion result")
                continue
            name, title, ancestors = case.get("fullName"), case.get("title"), case.get("ancestorTitles")
            if (not isinstance(name, str) or not name or len(name) > 4096 or name in names
                    or not isinstance(title, str) or not isinstance(ancestors, list)
                    or any(not isinstance(part, str) for part in ancestors)
                    or name != " ".join([*ancestors, *([title] if title else [])])):
                issue("missing, ambiguous or duplicate Vitest case identity")
                continue
            names.add(name)
            status, failures = case.get("status"), case.get("failureMessages")
            if (not isinstance(status, str) or status not in observed or not isinstance(failures, list)
                    or any(not isinstance(message, str) for message in failures)):
                issue("unsupported, pending or malformed Vitest case outcome")
                continue
            if (status == "failed") != any(message.strip() for message in failures):
                issue("Vitest case/failure diagnostics disagree")
            observed[status] += 1
            file_failed |= status == "failed"
            outcome = status if status in {"passed", "failed"} else "skipped"
            counts[outcome] += 1
            if outcome != "skipped":
                seen.add(name)
            elif name not in expected_results:
                metadata["unselected_unexecuted"] += 1
            if name in expected_results:
                expected_results[name][outcome] += 1
        if suite.get("message") != "" or suite.get("status") != ("failed" if file_failed else "passed"):
            issue("Vitest file setup/collection/hook failure or contradictory status")
    totals = {"numTotalTests": sum(observed.values()), "numPassedTests": observed["passed"],
              "numFailedTests": observed["failed"], "numPendingTests": observed["skipped"],
              "numTodoTests": observed["todo"]}
    if any(report[key] != value for key, value in totals.items()):
        issue("Vitest case/summary cardinality mismatch")
    if (report["numTotalTestSuites"] != sum(report[key] for key in (
            "numPassedTestSuites", "numFailedTestSuites", "numPendingTestSuites"))
            or report["numTotalTestSuites"] < len(suites)
            or report["numPendingTestSuites"]
            or bool(report["numFailedTestSuites"]) != bool(observed["failed"])):
        issue("Vitest suite totals are incomplete or contradict test outcomes")
    terminal = "fail" if observed["failed"] else "pass"
    if report["success"] != (terminal == "pass") or exit_code not in {0, 1}:
        issue("Vitest did not terminate consistently with pass or test-failure status")
    metadata.update(reported_total_tests=report["numTotalTests"],
                    case_inventory_sha256=hashlib.sha256(json.dumps(sorted(names), ensure_ascii=False).encode()).hexdigest())
    return counts, seen, len(suites), terminal, metadata


def summarize(text, *, format, exit_code, expected_tests, package=None, include_inventory=False):
    """Count Go/Rust/pytest/GoogleTest/Node observations or observed Vitest 4 JSON.

    Go counts include parent tests/subtests and repeats, not assertion counts.
    Rust compact/JSON/bench/custom harness formats are deliberately unsupported.
    Missing/truncated/contradictory observations must never produce PASS.
    A negative subprocess return code denotes signal termination, not a normal
    test failure. Preserve observed assertions but classify the run inconclusive.
    Shell-normalized positive codes do not reliably identify a signal.
    Optional pytest-only inventory retains case outcomes and raw skip details;
    the default result shape does not change.
    """
    if format not in FORMATS:
        raise ValueError("unsupported native test format")
    if type(include_inventory) is not bool or (include_inventory and format != "pytest-junit"):
        raise ValueError("case inventory is supported only for pytest JUnit")
    if type(exit_code) is not int:
        raise ValueError("exit code must be an observed integer")
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_BYTES:
        raise ValueError("log exceeds 2 MiB")
    if not isinstance(expected_tests, (list, tuple)) or not 1 <= len(expected_tests) <= 64:
        raise ValueError("supply 1..64 exact expected test names")
    if any(not isinstance(name, str) or not name or len(name) > 512 for name in expected_tests):
        raise ValueError("invalid expected test name")
    if format == "go-json" and (not isinstance(package, str) or not package or len(package) > 512):
        raise ValueError("Go requires an exact expected package")
    issues, seen, active = [], set(), set()
    counts = {"passed": 0, "failed": 0, "skipped": 0}
    expected_results = {
        name: {"passed": 0, "failed": 0, "skipped": 0}
        for name in sorted(set(expected_tests))
    }
    batches, terminal, started = 0, None, False
    filtered = 0
    rust_running = None
    rust_cases = {}
    vitest = None
    bun_junit = None
    inventory = {} if include_inventory else None

    def issue(message):
        if message not in issues and len(issues) < 16:
            issues.append(message)

    if exit_code < 0:
        issue("process terminated by signal")

    if format == "pytest-junit":
        counts, seen, batches, terminal = _junit(text, exit_code, expected_results, issue, inventory)
    elif format == "gtest-xml":
        counts, seen, batches, terminal = _gtest_xml(text, exit_code, expected_results, issue)
    elif format == "node-tap":
        counts, seen, batches, terminal = _node_tap(text, exit_code, expected_results, issue)
    elif format == "vitest-json":
        counts, seen, batches, terminal, vitest = _vitest(text, exit_code, expected_results, issue)
    elif format == "bun-junit":
        counts, seen, batches, terminal, bun_junit = summarize_bun_junit(text, exit_code, expected_results, issue)

    for line in text.splitlines() if format in {"go-json", "rust-libtest"} else ():
        if format == "go-json":
            if not line.lstrip().startswith("{"):
                continue  # compiler/SSH diagnostics are not test events
            try:
                event = json.loads(line)
            except (ValueError, RecursionError):
                issue("malformed JSON event")
                continue
            if not isinstance(event, dict):
                issue("invalid JSON event")
                continue
            if event.get("Package") != package:
                continue
            action, name = event.get("Action"), event.get("Test")
            if not isinstance(action, str):
                issue("invalid event action")
                continue
            if action == "output" and re.search(r"(?m)^ok\s+.*\(cached\)", str(event.get("Output", ""))):
                issue("cached Go result is not a fresh execution")
            if action == "start" and not name:
                if started:
                    issue("multiple package starts")
                started = True
            elif action in {"run", "pass", "fail", "skip"} and name:
                if not isinstance(name, str) or not started or terminal:
                    issue("test event outside active package")
                    continue
                if action == "run":
                    if name in active:
                        issue("duplicate test start")
                    active.add(name)
                else:
                    if name not in active:
                        issue("test terminal without start")
                        continue
                    active.remove(name)
                    outcome = {"pass": "passed", "fail": "failed", "skip": "skipped"}[action]
                    counts[outcome] += 1
                    if name in expected_results:
                        expected_results[name][outcome] += 1
                    if action != "skip":
                        seen.add(name)
            elif action in {"pass", "fail", "skip"} and not name:
                if not started or terminal or active:
                    issue("invalid package terminal")
                terminal = action
                batches += 1
        else:
            running = re.fullmatch(r"running (\d+) tests?", line)
            case = re.fullmatch(r"test (.+?) \.\.\. (ok|FAILED|ignored)(?:, .*)?", line)
            summary = RUST_SUMMARY.fullmatch(line)
            if running:
                if rust_running is not None:
                    issue("unfinished Rust batch")
                rust_running, rust_cases = int(running[1]), {}
            elif case:
                if rust_running is None or case[1] in rust_cases:
                    issue("Rust case outside batch or duplicated")
                rust_cases[case[1]] = case[2]
            elif summary:
                passed, failed, ignored, measured = map(int, summary.group(2, 3, 4, 5))
                if rust_running is None or passed + failed + ignored + measured != rust_running:
                    issue("Rust batch cardinality mismatch")
                if measured or any(
                    sum(value == status for value in rust_cases.values()) != count
                    for status, count in (("ok", passed), ("FAILED", failed), ("ignored", ignored))
                ):
                    issue("Rust case/summary mismatch or benchmark batch")
                if (summary[1] == "ok") != (failed == 0):
                    issue("Rust summary status mismatch")
                for key, count in (("passed", passed), ("failed", failed), ("skipped", ignored)):
                    counts[key] += count
                filtered += int(summary[6])
                seen.update(name for name, status in rust_cases.items() if status != "ignored")
                for name, result in rust_cases.items():
                    if name in expected_results:
                        outcome = {"ok": "passed", "FAILED": "failed", "ignored": "skipped"}[result]
                        expected_results[name][outcome] += 1
                batches += 1
                rust_running, rust_cases = None, {}
                terminal = "fail" if failed or terminal == "fail" else "pass"
    if not batches or active or rust_running is not None:
        issue("missing or incomplete test terminal")
    missing = sorted(set(expected_tests) - seen)
    if missing:
        issue("expected test did not execute")
    executed = counts["passed"] + counts["failed"]
    if not executed:
        issue("no non-skipped tests executed")
    if bool(exit_code) != (terminal == "fail"):
        issue("process exit and test terminal disagree")
    if format == "go-json" and counts["failed"] and terminal == "pass":
        issue("package passed despite reported test failures")
    status = "INCONCLUSIVE" if issues else ("TESTS_FAILED" if counts["failed"] else "TESTS_PASSED")
    if not issues and terminal != "pass" and status == "TESTS_PASSED":
        status = "INCONCLUSIVE"
        issue("package failed outside reported test cases")
    result = {"status": status, "format": format, "exit_code": exit_code,
            "package": package if format == "go-json" else None,
            **counts, "executed": executed, "batches": batches,
            "filtered": filtered if format == "rust-libtest" else None,
            "expected_test_results": expected_results,
            "missing_expected_tests": missing, "issues": issues,
            "log_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "boundary": "Observed log accounting only; not authenticity, test quality, "
                        "source/runtime identity, caller reachability, performance or PR qualification."}
    if vitest is not None:
        result["vitest"] = vitest
    if bun_junit is not None:
        result["bun_junit"] = bun_junit
    if format == "gtest-xml":
        result["disabled"] = counts["disabled"]  # subset of skipped, not additive
    if inventory is not None:
        result["case_inventory"] = inventory
    return result


def compare_pytest_suite_regression(baseline_text, candidate_text, *, baseline_exit,
                                    candidate_exit, regressions, controls):
    """Compare complete pytest inventories, permitting only stable skipped cases.

    Freeze the suite command, regression names and passing controls before either
    run. All other cases must retain their outcome; skip attributes must match.
    With a nonempty skip message, the body is retained as diagnostic text but
    not compared (pytest includes source locations). Otherwise text must match.
    A changed coverage cohort is not a matched comparison.
    This is captured-report accounting, not source/test authenticity or PR policy.
    The stricter existing compare_regression API remains unchanged.
    """
    if any(not isinstance(group, (list, tuple)) or not group for group in (regressions, controls)):
        raise ValueError("declare regressions and passing controls")
    names = list(regressions) + list(controls)
    if any(not isinstance(name, str) or not name for name in names) or len(set(names)) != len(names):
        raise ValueError("declarations must be distinct nonempty test names")
    arms = [summarize(text, format="pytest-junit", exit_code=code,
                      expected_tests=names, include_inventory=True)
            for text, code in ((baseline_text, baseline_exit), (candidate_text, candidate_exit))]
    before, after = arms
    issues = []

    def comparable(case):
        if case["outcome"] == "skipped" and case["skip_attributes"].get("message"):
            return {key: value for key, value in case.items() if key != "skip_text"}
        return case

    if any(arm["issues"] for arm in arms):
        issues.append("incomplete or contradictory arm accounting")
    else:
        old, new = before["case_inventory"], after["case_inventory"]
        if old.keys() != new.keys():
            issues.append("complete pytest case inventories differ")
        for name in old.keys() & new.keys():
            if name in regressions:
                if old[name]["outcome"] != "failed" or new[name]["outcome"] != "passed":
                    issues.append(f"declared regression pattern not observed: {name}")
            elif comparable(old[name]) != comparable(new[name]):
                issues.append(f"undeclared case outcome or skip detail changed: {name}")
        if any(old[name]["outcome"] != "passed" or new[name]["outcome"] != "passed"
               for name in controls):
            issues.append("declared controls did not pass in both arms")
        if after["failed"] or after["errors"]:
            issues.append("candidate suite contains failures or errors")
        if before["failed"] != len(regressions):
            issues.append("baseline failure count differs from declared regressions")
    return {"status": "INCONCLUSIVE" if any(arm["issues"] for arm in arms)
            else "PATTERN_NOT_OBSERVED" if issues else "MATCHED_SUITE_REGRESSION_OBSERVED",
            "issues": sorted(set(issues))[:16], "baseline": before, "candidate": after,
            "regressions": list(regressions), "controls": list(controls),
            "boundary": "Complete captured pytest inventory only; stable skips are not executed "
                        "coverage. Not source/runtime identity, authenticity, test quality or PR readiness."}


def compare_regression(baseline_text, candidate_text, *, format, baseline_exit,
                       candidate_exit, regressions, controls, package=None):
    """Check a declared red/green pattern on the same complete selected suite.

    This consumes captured logs, not model verdicts. The selection must be fixed
    before inspecting outcomes. It establishes neither authenticity nor whether
    the declared assertions represent the supported production contract.
    """
    if not isinstance(regressions, (list, tuple)) or not regressions:
        raise ValueError("declare at least one exact regression case")
    if not isinstance(controls, (list, tuple)) or not controls:
        raise ValueError("declare at least one exact passing control")
    names = list(regressions) + list(controls)
    if any(not isinstance(name, str) or not name for name in names):
        raise ValueError("case names must be nonempty strings")
    if len(set(names)) != len(names):
        raise ValueError("regression and control cases must be distinct")
    baseline = summarize(baseline_text, format=format, exit_code=baseline_exit,
                         expected_tests=names, package=package)
    candidate = summarize(candidate_text, format=format, exit_code=candidate_exit,
                          expected_tests=names, package=package)
    issues = []
    if any(arm["issues"] for arm in (baseline, candidate)):
        issues.append("incomplete or contradictory arm accounting")
    else:
        for arm in (baseline, candidate):
            selected = arm["expected_test_results"]
            totals = {key: sum(case[key] for case in selected.values())
                      for key in ("passed", "failed", "skipped")}
            observed = {key: arm[key] for key in totals}
            if format == "vitest-json":
                observed["skipped"] -= arm["vitest"]["unselected_unexecuted"]
            if totals != observed:
                issues.append("observed cases differ from the declared complete selection")
                break
        if format == "vitest-json" and any(
            baseline["vitest"][key] != candidate["vitest"][key]
            for key in ("case_inventory_sha256", "reported_total_tests", "unselected_unexecuted")
        ):
            issues.append("Vitest report inventories or unexecuted cohorts differ")
        if format == "bun-junit" and any(
            baseline["bun_junit"][key] != candidate["bun_junit"][key]
            for key in ("grouped_case_inventory_sha256", "reported_total_tests")
        ):
            issues.append("Bun grouped test inventories or multiplicities differ")
        for name in names:
            before = baseline["expected_test_results"][name]
            after = candidate["expected_test_results"][name]
            repeats = sum(before.values())
            expected_before = "failed" if name in regressions else "passed"
            if (not repeats or before[expected_before] != repeats
                    or after["passed"] != repeats or sum(after.values()) != repeats):
                issues.append(f"declared matched outcome pattern not observed: {name}")
    status = ("INCONCLUSIVE" if baseline["issues"] or candidate["issues"]
              else "PATTERN_NOT_OBSERVED" if issues else "MATCHED_REGRESSION_OBSERVED")
    return {"status": status, "issues": issues, "baseline": baseline,
            "candidate": candidate, "regressions": list(regressions),
            "controls": list(controls),
            "boundary": "Captured-log discrimination only; not source/runtime identity, "
                        "production correctness, performance, PR readiness or execution authority."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--format", choices=FORMATS, required=True)
    parser.add_argument("--exit-code", type=int, required=True)
    parser.add_argument("--package")
    parser.add_argument("--expect-test", action="append", required=True)
    args = parser.parse_args()
    with args.log.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        parser.error("log exceeds 2 MiB; no partial-log verdict")
    try:
        result = summarize(raw.decode("utf-8"), format=args.format, exit_code=args.exit_code,
                           package=args.package, expected_tests=args.expect_test)
    except (ValueError, UnicodeError) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False))
    return {"TESTS_PASSED": 0, "TESTS_FAILED": 1, "INCONCLUSIVE": 2}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
