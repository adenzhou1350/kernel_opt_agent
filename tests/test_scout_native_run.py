"""Runner controls are synthetic; real native verification is a separate replay."""

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import scout_native_run as runner

PASS = "running 1 test\ntest contract ... ok\ntest result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.01s"
JUNIT_PASS = '<testsuite tests="1" failures="0" errors="0" skipped="0"><testcase classname="tests.test_contract" name="test_case"/></testsuite>'


class InputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "source.rs"
        self.source.write_bytes(b"// reviewed fixture\n")
        self.sha = hashlib.sha256(self.source.read_bytes()).hexdigest()

    def test_relative_content_identity(self):
        self.assertEqual(runner.source_identities(self.root, [("source.rs", self.sha)]),
                         {"source.rs": self.sha})

    def test_mismatch_missing_escape_duplicates_and_empty_rejected(self):
        for sources in ([], [("source.rs", "0" * 64)], [("missing.rs", self.sha)],
                        [("../source.rs", self.sha)], [(str(self.source), self.sha)],
                        [("source.rs", self.sha), ("source.rs", self.sha)]):
            with self.subTest(sources=sources), self.assertRaises((ValueError, OSError)):
                runner.source_identities(self.root, sources)

    def test_assignments_preserve_environment_equals(self):
        self.assertEqual(runner.assignments(["TOKEN=a=b"], environment=True), [("TOKEN", "a=b")])
        self.assertEqual(runner.assignments(["source=name.rs=" + self.sha]), [("source=name.rs", self.sha)])
        with self.assertRaises(ValueError):
            runner.assignments(["broken"])

    @unittest.skipUnless(os.name == "posix", "POSIX source symlinks")
    def test_symlink_even_inside_checkout_rejected(self):
        (self.root / "alias.rs").symlink_to(self.source)
        with self.assertRaises(ValueError):
            runner.source_identities(self.root, [("alias.rs", self.sha)])

    @unittest.skipUnless(os.name == "nt", "Windows worker refusal")
    def test_windows_does_not_start_wsl_or_any_child(self):
        from unittest.mock import patch
        with patch.object(runner.subprocess, "Popen") as child:
            with self.assertRaisesRegex(ValueError, "do not start local WSL"):
                runner.run(cwd=self.root, output=self.root / "output", command=[sys.executable],
                           sources=[("source.rs", self.sha)], format="rust-libtest", expected_tests=["contract"])
            child.assert_not_called()


@unittest.skipUnless(os.name == "posix", "run on the authorized POSIX worker")
class ProcessTests(unittest.TestCase):
    def setUp(self):
        InputTests.setUp(self)

    def execute(self, code, **overrides):
        options = dict(cwd=self.root, output=self.root / "output", command=[sys.executable, "-B", "-c", code],
                       sources=[("source.rs", self.sha)], format="rust-libtest", expected_tests=["contract"], timeout=2)
        options.update(overrides)
        return runner.run(**options)

    def test_complete_terminal_and_private_environment(self):
        result = self.execute("import os; assert os.environ['CUDA_VISIBLE_DEVICES']==''; print(" + repr(PASS) + ")")
        self.assertEqual(result["status"], "TESTS_PASSED")
        self.assertEqual(result["summary"]["executed"], 1)
        self.assertEqual(result["source_before"], result["source_after"])
        self.assertEqual(json.loads((self.root / "output/result.json").read_text()), result)
        self.assertGreaterEqual(result["wall_seconds"], result["command_wall_seconds"])
        with self.assertRaises(FileExistsError):
            self.execute("print('do not execute')")

    def test_exit_zero_without_registered_target_is_inconclusive(self):
        self.assertEqual(self.execute("print('nothing ran')")["status"], "INCONCLUSIVE")

    def execute_junit(self, code, **overrides):
        options = dict(format="pytest-junit", expected_tests=["tests.test_contract::test_case"])
        options.update(overrides)
        return self.execute(code, **options)

    def write_junit(self, text):
        return ("import sys; from pathlib import Path; "
                "Path(sys.argv[-1].split('=',1)[1]).write_text(" + repr(text) + ",encoding='utf-8'); ")

    def test_junit_capture_owns_report_and_preserves_stdout(self):
        result = self.execute_junit(self.write_junit(JUNIT_PASS) + "print('assertion diagnostics')")
        self.assertEqual(result["status"], "TESTS_PASSED")
        self.assertEqual(result["summary"]["expected_test_results"]["tests.test_contract::test_case"]["passed"], 1)
        report = self.root / "output/junit.xml"
        self.assertEqual(result["test_report"], {"path": str(report), "sha256": runner.digest(report)})
        self.assertEqual(result["command"][-1], "--junitxml=" + str(report))
        self.assertIn("assertion diagnostics", (self.root / "output/terminal.log").read_text())
        self.assertEqual(result["terminal_log_sha256"], runner.digest(self.root / "output/terminal.log"))

    def test_junit_assertion_failure_remains_a_test_failure(self):
        text = JUNIT_PASS.replace('failures="0"', 'failures="1"').replace('/>', '><failure message="regression"/></testcase>')
        result = self.execute_junit(self.write_junit(text) + "sys.exit(1)")
        self.assertEqual(result["status"], "TESTS_FAILED")
        self.assertEqual(result["summary"]["failed"], 1)

    def test_junit_missing_truncated_large_or_symlink_has_no_pass(self):
        cases = [
            "print('4 passed')",
            self.write_junit(JUNIT_PASS[:-20]) + "print('4 passed')",
            "import sys; from pathlib import Path; Path(sys.argv[-1].split('=',1)[1]).write_text('x' * (2*1024*1024+1))",
            "import sys; from pathlib import Path; Path(sys.argv[-1].split('=',1)[1]).symlink_to(Path('source.rs').resolve())",
        ]
        for index, code in enumerate(cases):
            with self.subTest(index=index):
                result = self.execute_junit(code, output=self.root / ("output" + str(index)))
                self.assertEqual(result["status"], "INCONCLUSIVE")
                if index == 1:
                    self.assertTrue(result["summary"]["issues"])
                else:
                    self.assertIsNone(result["summary"])

    def test_junit_report_cannot_bypass_timeout_or_source_change(self):
        cases = [
            "import time; time.sleep(30)",
            "Path('source.rs').write_text('changed')",
        ]
        for index, code in enumerate(cases):
            with self.subTest(index=index):
                result = self.execute_junit(self.write_junit(JUNIT_PASS) + code,
                    output=self.root / ("output" + str(index)), timeout=0.3)
                self.assertEqual(result["status"], "INCONCLUSIVE")
                self.assertIsNone(result["summary"])

    def test_preexisting_junit_output_argument_rejected_before_launch(self):
        from unittest.mock import patch
        for flag in ("--junitxml=old.xml", "--junit-xml=old.xml", "--junitxml", "--junit-xml"):
            with self.subTest(flag=flag), patch.object(runner.subprocess, "Popen") as child:
                with self.assertRaisesRegex(ValueError, "runner owns"):
                    self.execute_junit("print('do not run')",
                        command=[sys.executable, "-m", "pytest", flag])
                child.assert_not_called()
            self.assertFalse((self.root / "output").exists())

    def test_failed_test_is_not_process_failure_only(self):
        text = PASS.replace("... ok", "... FAILED").replace("result: ok. 1 passed; 0 failed", "result: FAILED. 0 passed; 1 failed")
        result = self.execute("import sys; print(" + repr(text) + "); sys.exit(1)")
        self.assertEqual(result["status"], "TESTS_FAILED")

    def test_failed_summary_followed_by_signal_is_inconclusive(self):
        text = PASS.replace("... ok", "... FAILED").replace(
            "result: ok. 1 passed; 0 failed", "result: FAILED. 0 passed; 1 failed")
        code = ("import os,signal; print(" + repr(text) + ",flush=True); "
                "os.kill(os.getpid(),signal.SIGTERM)")
        result = self.execute(code)
        self.assertEqual(result["exit_code"], -15)
        self.assertEqual(result["status"], "INCONCLUSIVE")
        self.assertEqual(result["summary"]["failed"], 1)
        self.assertIn("process terminated by signal", result["summary"]["issues"])

    def test_source_mutation_invalidates_pass(self):
        result = self.execute("from pathlib import Path; Path('source.rs').write_text('changed'); print(" + repr(PASS) + ")")
        self.assertEqual(result["status"], "INCONCLUSIVE")
        self.assertIsNone(result["summary"])

    def test_log_limit_stops_without_partial_pass(self):
        result = self.execute("import sys; print(" + repr(PASS) + "); sys.stdout.write('x' * (3 * 1024 * 1024)); sys.stdout.flush()")
        self.assertEqual(result["status"], "INCONCLUSIVE")
        self.assertIsNone(result["summary"])
        self.assertLessEqual((self.root / "output/terminal.log").stat().st_size, runner.native.MAX_BYTES)

    def test_timeout_kills_owned_child_group(self):
        code = "import subprocess,sys,time; from pathlib import Path; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); Path('child.pid').write_text(str(p.pid)); time.sleep(30)"
        result = self.execute(code, timeout=0.3)
        self.assertEqual(result["status"], "INCONCLUSIVE")
        self.assertIsNone(result["summary"])
        pid = int((self.root / "child.pid").read_text())
        self.assert_child_stopped(pid)

    def assert_child_stopped(self, pid):
        # Linux may retain a reparented zombie briefly; it must not be running.
        path = Path(f"/proc/{pid}/stat")
        for _ in range(20):
            if not path.exists() or path.read_text().split()[2] == "Z":
                break
            time.sleep(0.05)
        else:
            self.fail("owned descendant remains running after timeout")

    def test_exited_parent_does_not_hide_descendant_pipe(self):
        code = "import subprocess,sys; from pathlib import Path; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); Path('child.pid').write_text(str(p.pid))"
        result = self.execute(code, timeout=0.3)
        self.assertEqual(result["status"], "INCONCLUSIVE")
        self.assertIsNone(result["summary"])
        self.assert_child_stopped(int((self.root / "child.pid").read_text()))

    def test_closed_descendant_output_does_not_hide_background_process(self):
        import signal

        failure = PASS.replace("... ok", "... FAILED").replace(
            "result: ok. 1 passed; 0 failed", "result: FAILED. 0 passed; 1 failed")
        for exit_code, text in ((0, PASS), (1, failure)):
            with self.subTest(exit_code=exit_code):
                code = (
                    "import subprocess,sys; from pathlib import Path; "
                    "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],"
                    "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
                    "Path('child.pid').write_text(str(p.pid)); print(" + repr(text) + "); "
                    "sys.exit(" + str(exit_code) + ")"
                )
                try:
                    result = self.execute(code, output=self.root / f"output{exit_code}")
                    self.assertEqual(result["status"], "INCONCLUSIVE")
                    self.assertIsNone(result["summary"])
                    self.assert_child_stopped(int((self.root / "child.pid").read_text()))
                finally:
                    # Preserve safe teardown even when replayed against the old runner.
                    pid_file = self.root / "child.pid"
                    if pid_file.exists():
                        try:
                            os.kill(int(pid_file.read_text()), signal.SIGTERM)
                        except ProcessLookupError:
                            pass

    def test_success_does_not_signal_a_process_outside_owned_group(self):
        import subprocess

        other = subprocess.Popen([sys.executable, "-B", "-c", "import time; time.sleep(30)"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            result = self.execute("print(" + repr(PASS) + ")")
            self.assertEqual(result["status"], "TESTS_PASSED")
            self.assertIsNone(other.poll())
        finally:
            other.terminate()
            other.wait(timeout=5)

    def test_non_utf8_log_has_no_verdict(self):
        result = self.execute("import sys; sys.stdout.buffer.write(bytes([255]))")
        self.assertEqual(result["status"], "INCONCLUSIVE")
        self.assertIsNone(result["summary"])

    def test_changed_executable_has_no_verdict(self):
        from unittest.mock import patch
        with patch.object(runner, "digest", side_effect=[self.sha, "a" * 64, self.sha, "b" * 64, "c" * 64]):
            result = self.execute("print(" + repr(PASS) + ")")
        self.assertEqual(result["status"], "INCONCLUSIVE")
        self.assertIsNone(result["summary"])

    def test_pipe_close_does_not_bypass_deadline(self):
        result = self.execute("import os,time; os.close(1); os.close(2); time.sleep(30)", timeout=0.3)
        self.assertEqual(result["status"], "INCONCLUSIVE")

    def test_prelaunch_mismatch_gpu_and_environment_rejected(self):
        for overrides in ({"sources": [("source.rs", "0" * 64)]}, {"environment": {"CUDA_VISIBLE_DEVICES": "0"}},
                          {"environment": {"BAD=KEY": "value"}}, {"command": ["python3"]},
                          {"expected_tests": []}, {"timeout": 0}, {"_gpu_uuid": "0"},
                          {"_gpu_uuid": "GPU-00000000-0000-0000-0000-000000000000"}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.execute("print('should not run')", **overrides)
            self.assertFalse((self.root / "output").exists())


if __name__ == "__main__":
    unittest.main()
