"""Real stdlib executions, not fabricated test result strings."""

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import scout_unittest as observer  # noqa: E402 -- explicit sibling tool path


class ObserverTests(unittest.TestCase):
    def run_suite(self, suite, **kwargs):
        runner = observer.ObservedRunner(stream=io.StringIO(), **kwargs)
        result = runner.run(suite)
        return result, runner.observation

    def test_complete_parent_and_subtest_observations(self):
        class Subject(unittest.TestCase):
            def test_subtests(self):
                for n in (0, 1):
                    with self.subTest(n=n):
                        self.assertEqual(n, 0)

            def test_control(self):
                pass

        result, report = self.run_suite(unittest.defaultTestLoader.loadTestsFromTestCase(Subject))
        self.assertFalse(result.wasSuccessful())
        self.assertEqual(report["tests_run"], 2)
        self.assertFalse(report["was_successful"])
        self.assertEqual(len(report["failures"]), 1)
        self.assertEqual([e["outcome"] for e in report["events"] if e["action"] == "subtest"],
                         ["success", "failure"])
        self.assertEqual(sum(e["action"] == "start" for e in report["events"]), 2)
        self.assertEqual(sum(e["action"] == "stop" for e in report["events"]), 2)

    def test_fixture_error_has_no_invented_test_execution(self):
        class Subject(unittest.TestCase):
            @classmethod
            def setUpClass(cls):
                raise RuntimeError("fixture failed")

            def test_unreached(self):
                raise AssertionError("must not execute")

        _, report = self.run_suite(unittest.defaultTestLoader.loadTestsFromTestCase(Subject))
        self.assertEqual(report["tests_run"], 0)
        self.assertFalse(report["was_successful"])
        self.assertEqual(len(report["errors"]), 1)
        self.assertEqual([e["action"] for e in report["events"]], ["error"])

    def test_skips_expected_failure_and_unexpected_success_are_retained(self):
        class Subject(unittest.TestCase):
            @unittest.skip("optional dependency absent")
            def test_skip(self):
                pass

            @unittest.expectedFailure
            def test_expected(self):
                self.fail("known")

            @unittest.expectedFailure
            def test_unexpected(self):
                pass

        _, report = self.run_suite(unittest.defaultTestLoader.loadTestsFromTestCase(Subject))
        self.assertEqual(report["tests_run"], 3)
        self.assertFalse(report["was_successful"])
        self.assertEqual(len(report["expected_failures"]), 1)
        self.assertEqual(len(report["unexpected_successes"]), 1)
        self.assertEqual(report["skips"][0]["reason"], "optional dependency absent")

    def test_duplicate_executions_are_not_deduplicated(self):
        class Subject(unittest.TestCase):
            def test_control(self):
                pass

        _, report = self.run_suite(unittest.TestSuite([Subject("test_control"), Subject("test_control")]))
        self.assertEqual(report["tests_run"], 2)
        self.assertEqual(sum(e["action"] == "success" for e in report["events"]), 2)

    def test_failfast_preserves_early_stop(self):
        class Subject(unittest.TestCase):
            def test_failed(self):
                self.fail("expected")

            def test_unreached(self):
                pass

        _, report = self.run_suite(unittest.defaultTestLoader.loadTestsFromTestCase(Subject), failfast=True)
        self.assertEqual(report["tests_run"], 1)
        self.assertTrue(report["stopped_early"])

    def test_keyboard_interrupt_does_not_produce_complete_observation(self):
        class Subject(unittest.TestCase):
            def test_interrupt(self):
                raise KeyboardInterrupt()

        runner = observer.ObservedRunner(stream=io.StringIO())
        runner.run(unittest.TestSuite())
        self.assertTrue(hasattr(runner, "observation"))
        with self.assertRaises(KeyboardInterrupt):
            runner.run(unittest.defaultTestLoader.loadTestsFromTestCase(Subject))
        self.assertFalse(hasattr(runner, "observation"))

    def test_cli_discovery_and_existing_report_protection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "test_contract.py").write_text(
                "import unittest\nclass Contract(unittest.TestCase):\n"
                "    def test_ok(self): self.assertEqual(2 + 2, 4)\n", encoding="utf-8")
            report = root / "observation.json"
            command = [sys.executable, "-B", observer.__file__, "--report", str(report),
                       "discover", "-s", str(root)]
            env = dict(os.environ, CUDA_VISIBLE_DEVICES="", PYTHONDONTWRITEBYTECODE="1")
            first = subprocess.run(command, capture_output=True, text=True, timeout=10, env=env)
            self.assertEqual(first.returncode, 0, first.stderr)
            body = report.read_bytes()
            data = json.loads(body)
            self.assertEqual(data["tests_run"], 1)
            self.assertTrue(data["was_successful"])
            self.assertIn("Ran 1 test", first.stderr)
            second = subprocess.run(command, capture_output=True, text=True, timeout=10, env=env)
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual(report.read_bytes(), body)

    def test_cli_keeps_standard_failfast_and_buffer_flags(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "test_contract.py").write_text(
                "import unittest\nclass Contract(unittest.TestCase):\n"
                "    def test_a(self): print('captured-only'); self.fail('real assertion')\n"
                "    def test_b(self): print('must not execute')\n", encoding="utf-8")
            report = root / "observation.json"
            command = [sys.executable, "-B", observer.__file__, "--report", str(report),
                       "discover", "-s", str(root), "-f", "-b"]
            child = subprocess.run(command, capture_output=True, text=True, timeout=10)
            self.assertEqual(child.returncode, 1, child.stderr)
            data = json.loads(report.read_bytes())
            self.assertEqual(data["tests_run"], 1)
            self.assertTrue(data["stopped_early"])
            self.assertEqual(len(data["failures"]), 1)
            native = subprocess.run(
                [sys.executable, "-B", "-m", "unittest", "discover", "-s", str(root), "-f", "-b"],
                capture_output=True, text=True, timeout=10)
            self.assertEqual(native.returncode, 1)
            # Standard unittest mirrors buffered output on failure; it does not
            # discard it. Compare the real entry point, not an invented rule.
            self.assertEqual(child.stdout, native.stdout)
            self.assertIn("Stdout:\ncaptured-only", child.stdout)
            self.assertIn("captured-only", child.stderr)
            self.assertNotIn("must not execute", child.stdout + child.stderr)


if __name__ == "__main__":
    unittest.main()
