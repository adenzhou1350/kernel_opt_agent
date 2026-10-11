"""Node TAP accounting controls and optional native Node 24 reporter replay."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import scout_native_results as native


def point(name, number=1, *, outcome="ok", kind="test", failure=None,
          directive="", children=""):
    diagnostic = f"  ---\n  duration_ms: 0.1\n  type: '{kind}'\n"
    if failure:
        diagnostic += f"  failureType: '{failure}'\n"
    nested = "".join("    " + line + "\n" for line in children.splitlines())
    return (f"# Subtest: {name}\n{nested}{outcome} {number} - {name}{directive}\n"
            + diagnostic + "  ...\n")


def tap(points, *, top=1, passed=1, failed=0, skipped=0, todo=0,
        cancelled=0, suites=0):
    return ("TAP version 13\n" + points + f"1..{top}\n"
            f"# tests {passed + failed + skipped + todo + cancelled}\n# suites {suites}\n"
            f"# pass {passed}\n# fail {failed}\n# cancelled {cancelled}\n"
            f"# skipped {skipped}\n# todo {todo}\n# duration_ms 2.0\n")


class NodeAccountingTests(unittest.TestCase):
    def summarize(self, text=None, code=0, names=("control",)):
        return native.summarize(tap(point("control")) if text is None else text,
                                format="node-tap", exit_code=code, expected_tests=names)

    def test_flat_and_escaped_name_are_not_directives(self):
        name = r"a \# SKIP escaped\\name\\nline"
        value = self.summarize(tap(point(name)), names=[name])
        self.assertEqual((value["status"], value["passed"], value["skipped"]),
                         ("TESTS_PASSED", 1, 0))

    def test_nested_suites_excluded_but_parent_tests_count(self):
        inner = point("control") + "1..1\n"
        outer = point("inner", kind="suite", children=inner) + "1..1\n"
        points = point("suite", kind="suite", children=outer)
        points += point("parent", 2, children=point("child") + "1..1\n")
        value = self.summarize(tap(points, top=2, passed=3, suites=2),
                               names=["suite::inner::control", "parent", "parent::child"])
        self.assertEqual((value["status"], value["passed"], value["suites"]),
                         ("TESTS_PASSED", 3, 2))
        self.assertEqual(self.summarize(tap(points, top=2, passed=3, suites=2),
                                        names=["suite"])["status"], "INCONCLUSIVE")

    def test_failed_suite_aggregate_is_not_an_extra_failed_test(self):
        children = point("regression", outcome="not ok", failure="testCodeFailure") + "1..1\n"
        points = point("suite", kind="suite", outcome="not ok", failure="subtestsFailed", children=children)
        value = self.summarize(tap(points, passed=0, failed=1, suites=1), 1,
                               names=["suite::regression"])
        self.assertEqual((value["status"], value["failed"]), ("TESTS_FAILED", 1))

    def test_skip_and_todo_never_prove_expected_execution(self):
        points = point("control")
        points += point("skip", 2, directive=" # SKIP not supported here")
        points += point("todo", 3, outcome="not ok", directive=" # TODO", failure="testCodeFailure")
        text = tap(points, top=3, skipped=1, todo=1)
        value = self.summarize(text)
        self.assertEqual((value["status"], value["skipped"], value["todo"]), ("TESTS_PASSED", 2, 1))
        for name in ("skip", "todo", "missing"):
            self.assertEqual(self.summarize(text, names=[name])["status"], "INCONCLUSIVE")

    def test_cancel_hook_and_other_runner_failures_are_inconclusive(self):
        for failure in ("cancelledByParent", "testTimeoutFailure", "hookFailed", "uncaughtException"):
            cancelled = failure in {"cancelledByParent", "testTimeoutFailure"}
            text = tap(point("control", outcome="not ok", failure=failure),
                       passed=0, failed=not cancelled, cancelled=cancelled)
            value = self.summarize(text, 1)
            self.assertEqual(value["status"], "INCONCLUSIVE")
            self.assertIn("Node cancellation/setup/runner failures are not assertion-failure reproductions",
                          value["issues"])

    def test_empty_and_skipped_suites_cannot_inflate_execution(self):
        text = tap(point("empty", kind="suite") + point("skip", 2, kind="suite", directive=" # SKIP"),
                   top=2, passed=0, suites=2)
        self.assertEqual(self.summarize(text)["executed"], 0)
        self.assertEqual(self.summarize(text)["status"], "INCONCLUSIVE")

    def test_corrupt_or_truncated_structure_never_passes(self):
        valid = tap(point("control"))
        mutations = [
            valid.replace("TAP version 13", "TAP version 14"),
            valid.replace("ok 1 -", "ok 2 -"),
            valid.replace("ok 1 - control", "ok 1 - different"),
            valid.replace("type: 'test'", "type: 'suite'"),
            valid.replace("type: 'test'", "type: 'test'\n  type: 'test'"),
            valid.replace("type: 'test'", ""),
            valid.replace("  ...", ""),
            valid.replace("1..1", "1..2"),
            valid.replace("# tests 1", "# tests 2"),
            valid.replace("# pass 1", "# pass -1"),
            valid.replace("# fail 0", "# fail 1"),
            valid.replace("# cancelled 0", "# cancelled 1"),
            valid.replace("# duration_ms 2.0\n", ""),
            valid + valid,
            valid + "# pass 1\n",
            valid.replace("# Subtest: control", "Bail out!\n# Subtest: control"),
            valid.replace("# Subtest: control", "# tests 1\n# Subtest: control"),
            valid.replace("  duration_ms: 0.1", "  failureType: 'testCodeFailure'"),
            valid.replace("ok 1 -", "not ok 1 -"),
            tap(point("control") + point("control", 2), top=2, passed=2),
            tap(point("a::control")),
        ]
        for index, text in enumerate(mutations):
            with self.subTest(index=index):
                self.assertEqual(self.summarize(text)["status"], "INCONCLUSIVE")
        for end in (0, 16, valid.index("1..1"), len(valid) - 10):
            self.assertEqual(self.summarize(valid[:end])["status"], "INCONCLUSIVE")

    def test_nested_plan_parent_status_and_depth_are_checked(self):
        child = point("control", outcome="not ok", failure="testCodeFailure") + "1..1\n"
        for parent in (point("suite", kind="suite", children=child),
                       point("suite", kind="suite", children=child.replace("1..1", "1..2")),
                       point("control", outcome="not ok", failure="subtestsFailed")):
            self.assertEqual(self.summarize(tap(parent), 1)["status"], "INCONCLUSIVE")
        points = point("control")
        for _ in range(34):
            points = point("parent", children=points + "1..1\n")
        self.assertEqual(self.summarize(tap(points))["status"], "INCONCLUSIVE")

    def test_exits_and_complete_matched_regression(self):
        before = tap(point("regression", outcome="not ok", failure="testCodeFailure")
                     + point("control", 2), top=2, passed=1, failed=1)
        after = tap(point("regression") + point("control", 2), top=2, passed=2)
        args = {"format": "node-tap", "baseline_exit": 1, "candidate_exit": 0,
                "regressions": ["regression"], "controls": ["control"]}
        self.assertEqual(native.compare_regression(before, after, **args)["status"],
                         "MATCHED_REGRESSION_OBSERVED")
        for code in (-9, 2, 137):
            self.assertEqual(self.summarize(before, code, ["regression"])["status"], "INCONCLUSIVE")
        self.assertEqual(self.summarize(before, 0, ["regression"])["status"], "INCONCLUSIVE")
        extra = tap(point("regression") + point("control", 2) + point("extra", 3), top=3, passed=3)
        self.assertEqual(native.compare_regression(before, extra, **args)["status"], "PATTERN_NOT_OBSERVED")

    def test_nested_matched_selection_excludes_suite_aggregate(self):
        before = tap(point("suite", kind="suite", outcome="not ok", failure="subtestsFailed",
                           children=point("regression", outcome="not ok", failure="testCodeFailure")
                           + point("control", 2) + "1..2\n"), passed=1, failed=1, suites=1)
        after = tap(point("suite", kind="suite", children=point("regression")
                          + point("control", 2) + "1..2\n"), passed=2, suites=1)
        result = native.compare_regression(before, after, format="node-tap", baseline_exit=1, candidate_exit=0,
                                           regressions=["suite::regression"], controls=["suite::control"])
        self.assertEqual(result["status"], "MATCHED_REGRESSION_OBSERVED")

    def test_saved_log_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "terminal.log"
            path.write_text(tap(point("control")), encoding="utf-8")
            result = subprocess.run([sys.executable, "-B", native.__file__, "--log", str(path),
                                     "--format", "node-tap", "--exit-code", "0", "--expect-test", "control"],
                                    capture_output=True, text=True, timeout=10, check=False)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout)["passed"], 1)


class NativeNodeReplayTests(unittest.TestCase):
    """Actual reporter behavior; not an upstream regression or model experiment."""

    @classmethod
    def setUpClass(cls):
        cls.node = os.environ.get("SCOUT_TEST_NODE") or shutil.which("node")
        if not cls.node:
            raise unittest.SkipTest("supply an already installed native Node 24 executable")
        version = subprocess.run([cls.node, "--version"], capture_output=True, text=True, timeout=5, check=False)
        if version.returncode or not version.stdout.startswith("v24."):
            raise unittest.SkipTest("this reporter integration is tested against Node 24")

    def run_node(self, code):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.mjs"
            path.write_text("import {test,describe,it,before} from 'node:test';\n"
                            "import assert from 'node:assert/strict';\n" + code, encoding="utf-8")
            return subprocess.run([self.node, "--test", "--test-reporter=tap", str(path)],
                                  capture_output=True, text=True, timeout=10, check=False)

    def test_real_nested_todo_and_failure_reports(self):
        for failed in (False, True):
            code = ("describe('suite',()=>{it('control',()=>{});"
                    "describe('inner',()=>{it('regression',()=>{" + ("assert.fail('regression');" if failed else "")
                    + "});it.skip('skip');it.todo('todo',()=>assert.fail('todo'));});});"
                    "test('parent',async t=>{await t.test('child',()=>{});});")
            result = self.run_node(code)
            summary = native.summarize(result.stdout, format="node-tap", exit_code=result.returncode,
                                       expected_tests=["suite::inner::regression", "parent::child"])
            self.assertEqual(summary["issues"], [])
            self.assertEqual(summary["status"], "TESTS_FAILED" if failed else "TESTS_PASSED")
            self.assertEqual((summary["suites"], summary["todo"], summary["skipped"]), (2, 1, 2))

    def test_real_timeout_and_hook_failures_are_not_regressions(self):
        for code, name in (("test('pending',{timeout:30},()=>new Promise(()=>{}));", "pending"),
                           ("describe('suite',()=>{before(()=>{throw Error('setup');});it('control',()=>{});});",
                            "suite::control")):
            result = self.run_node(code)
            summary = native.summarize(result.stdout, format="node-tap", exit_code=result.returncode,
                                       expected_tests=[name])
            self.assertEqual(summary["status"], "INCONCLUSIVE")
            self.assertEqual(summary["cancelled"], 1)

    @unittest.skipUnless(os.name == "posix", "capture process controls require an authorized POSIX worker")
    def test_real_node_through_capture_runner(self):
        import scout_native_run as runner

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "contract.mjs"
            source.write_text("import {test} from 'node:test';test('control',()=>{});", encoding="utf-8")
            result = runner.run(cwd=root, output=root / "fresh", command=[self.node, "--test", "--test-reporter=tap", str(source)],
                                sources=[("contract.mjs", runner.digest(source))], format="node-tap",
                                expected_tests=["control"], timeout=10)
            self.assertEqual(result["status"], "TESTS_PASSED")
            self.assertEqual(result["source_before"], result["source_after"])
            self.assertEqual(result["summary"]["passed"], 1)


if __name__ == "__main__":
    unittest.main()
