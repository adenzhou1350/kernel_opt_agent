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

MAX_BYTES = 2 * 1024 * 1024
RUST_SUMMARY = re.compile(
    r"test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; "
    r"(\d+) measured; (\d+) filtered out; finished in [0-9.]+s"
)


def _junit(text, exit_code, expected_results, issue):
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
            if not re.fullmatch(r"[0-9]{1,8}", value) or int(value) != total:
                issue("JUnit case/summary cardinality mismatch")

    for suite in suites:
        observed = dict.fromkeys(counts, 0)
        for case in suite:
            if case.tag in {"properties", "system-out", "system-err"}:
                continue
            if case.tag != "testcase":
                issue("unsupported JUnit suite child")
                continue
            classname, name = case.get("classname", ""), case.get("name", "")
            qualified = f"{classname}::{name}"
            if not classname or not name or len(qualified) > 512 or qualified in names:
                issue("missing, overlong or duplicate JUnit case identity")
            if "status" in case.attrib:
                issue("non-pytest JUnit status attributes are unsupported")
            names.add(qualified)
            outcomes = [child.tag for child in case if child.tag in {"failure", "error", "skipped"}]
            if len(outcomes) > 1 or any(child.tag not in {
                "failure", "error", "skipped", "properties", "system-out", "system-err"
            } for child in case):
                issue("unsupported or contradictory JUnit case outcomes")
            outcome = {"failure": "failed", "error": "errors", "skipped": "skipped"}.get(
                outcomes[0] if outcomes else None, "passed")
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


def summarize(text, *, format, exit_code, expected_tests, package=None):
    """Count Go events, Rust verbose batches or saved flat pytest JUnit reports.

    Go counts include parent tests/subtests and repeats, not assertion counts.
    Rust compact/JSON/bench/custom harness formats are deliberately unsupported.
    Missing/truncated/contradictory observations must never produce PASS.
    """
    if format not in {"go-json", "rust-libtest", "pytest-junit"}:
        raise ValueError("unsupported native test format")
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

    def issue(message):
        if message not in issues and len(issues) < 16:
            issues.append(message)

    if format == "pytest-junit":
        counts, seen, batches, terminal = _junit(text, exit_code, expected_results, issue)

    for line in text.splitlines() if format != "pytest-junit" else ():
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
    return {"status": status, "format": format, "exit_code": exit_code,
            "package": package if format == "go-json" else None,
            **counts, "executed": executed, "batches": batches,
            "filtered": filtered if format == "rust-libtest" else None,
            "expected_test_results": expected_results,
            "missing_expected_tests": missing, "issues": issues,
            "log_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "boundary": "Observed log accounting only; not authenticity, test quality, "
                        "source/runtime identity, caller reachability, performance or PR qualification."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--format", choices=("go-json", "rust-libtest", "pytest-junit"), required=True)
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
