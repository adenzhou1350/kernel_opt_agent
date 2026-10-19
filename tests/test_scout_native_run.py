"""Runner controls are synthetic; real native verification is a separate replay."""

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from unittest.mock import patch
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import scout_native_run as runner

PASS = "running 1 test\ntest contract ... ok\ntest result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.01s"
JUNIT_PASS = '<testsuite tests="1" failures="0" errors="0" skipped="0"><testcase classname="tests.test_contract" name="test_case"/></testsuite>'


class CLIHelpTests(unittest.TestCase):
    def test_help_explains_required_source_and_test_identity_without_launch(self):
        output = io.StringIO()
        with patch.object(runner.subprocess, "Popen") as child:
            with redirect_stdout(output), self.assertRaises(SystemExit) as stopped:
                runner.main(["--help"])
        self.assertEqual(stopped.exception.code, 0)
        child.assert_not_called()
        help_text = " ".join(output.getvalue().split())
        self.assertIn("--source RELATIVE_PATH=SHA256", help_text)
        self.assertIn("paths relative to --cwd", help_text)
        self.assertIn("--expect-test TEST_ID", help_text)
        self.assertIn("pytest: CLASSNAME::NAME", help_text)
        self.assertGreaterEqual(help_text.count("required for execution"), 5)
        self.assertIn("--env NAME=VALUE", help_text)


class RuntimeExportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def test_fresh_export_is_exact_and_has_all_sibling_tools(self):
        output = self.root / "tools"
        with patch.object(runner.subprocess, "Popen") as child:
            result = runner.export_runtime(output)
        child.assert_not_called()
        self.assertEqual(result["status"], "EXPORTED")
        self.assertEqual(set(result["files"]), set(runner.RUNTIME_FILES))
        self.assertEqual(set(p.name for p in output.iterdir()), set(runner.RUNTIME_FILES))
        for name, record in result["files"].items():
            body = (output / name).read_bytes()
            self.assertEqual(body, (Path(runner.__file__).parent / name).read_bytes())
            self.assertEqual(record, {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()})

    def test_cli_export_runs_from_an_unrelated_directory_without_pythonpath(self):
        output = self.root / "tools"
        env = dict(os.environ, PYTHONPATH="", PYTHONDONTWRITEBYTECODE="1")
        command = [sys.executable, "-B", str(Path(runner.__file__).resolve())]
        result = subprocess.run([*command, "--export-runtime", str(output)],
                                cwd=self.root, env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "EXPORTED")
        for name in ("scout_native_run.py", "qualification_source_bundle.py", "scout_dependency_tree.py"):
            help_result = subprocess.run([sys.executable, "-B", str(output / name), "--help"],
                                         cwd=self.root, env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(help_result.returncode, 0, help_result.stderr)
        nested = self.root / "second-copy"
        reexport = subprocess.run([sys.executable, "-B", str(output / "scout_native_run.py"),
                                  "--export-runtime", str(nested)], cwd=self.root, env=env,
                                 capture_output=True, text=True, timeout=10)
        self.assertEqual(reexport.returncode, 0, reexport.stderr)
        self.assertEqual(json.loads(reexport.stdout)["files"], json.loads(result.stdout)["files"])

    def test_existing_destination_is_preserved(self):
        output = self.root / "tools"
        output.mkdir()
        sentinel = output / "keep.txt"
        sentinel.write_text("existing user data")
        with self.assertRaises(FileExistsError):
            runner.export_runtime(output)
        self.assertEqual(sentinel.read_text(), "existing user data")
        self.assertEqual(list(output.iterdir()), [sentinel])

    def test_missing_sibling_fails_before_creating_destination(self):
        library = self.root / "incomplete"
        library.mkdir()
        (library / "scout_native_run.py").write_text("# fixture\n")
        with patch.object(runner, "__file__", str(library / "scout_native_run.py")):
            with self.assertRaisesRegex(ValueError, "scout_native_results.py"):
                runner.export_runtime(self.root / "output")
        self.assertFalse((self.root / "output").exists())

    def test_invalid_source_fails_before_creating_destination(self):
        library = self.root / "invalid"
        library.mkdir()
        for name in runner.RUNTIME_FILES:
            (library / name).write_text("invalid Python source !!!")
        with patch.object(runner, "__file__", str(library / "scout_native_run.py")):
            with self.assertRaises(SyntaxError):
                runner.export_runtime(self.root / "output")
        self.assertFalse((self.root / "output").exists())

    def test_oversized_source_fails_before_creating_destination(self):
        library = self.root / "large"
        library.mkdir()
        (library / "scout_native_run.py").write_bytes(b"#" * (512 * 1024 + 1))
        with patch.object(runner, "__file__", str(library / "scout_native_run.py")):
            with self.assertRaisesRegex(ValueError, "export budget"):
                runner.export_runtime(self.root / "output")
        self.assertFalse((self.root / "output").exists())

    @unittest.skipUnless(os.name == "posix", "POSIX source symlink")
    def test_symlinked_source_is_not_exported(self):
        library = self.root / "links"
        library.mkdir()
        (library / "scout_native_run.py").symlink_to(Path(runner.__file__).resolve())
        with patch.object(runner, "__file__", str(library / "scout_native_run.py")):
            with self.assertRaisesRegex(ValueError, "non-regular"):
                runner.export_runtime(self.root / "output")
        self.assertFalse((self.root / "output").exists())

    def test_export_and_execution_options_cannot_mix(self):
        with patch.object(runner, "export_runtime") as export, \
                patch.object(runner, "run") as execute, redirect_stderr(io.StringIO()) as errors:
            for tail in (["--cwd", str(self.root)], ["--env", "A=B"], ["--timeout", "1"],
                         ["--native-windows"], ["--", sys.executable]):
                with self.subTest(tail=tail), self.assertRaises(SystemExit) as exit:
                    runner.main(["--export-runtime", str(self.root / "tools"), *tail])
                self.assertEqual(exit.exception.code, 2)
            export.assert_not_called()
            execute.assert_not_called()
        self.assertIn("cannot be combined", errors.getvalue())

    def test_execution_still_requires_explicit_inputs(self):
        with patch.object(runner, "run") as execute, redirect_stderr(io.StringIO()) as errors, \
                self.assertRaises(SystemExit) as exit:
            runner.main([])
        self.assertEqual(exit.exception.code, 2)
        execute.assert_not_called()
        self.assertIn("required for execution", errors.getvalue())


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

    def test_guard_errors_and_invalid_decisions_are_bounded_and_fail_closed(self):
        for value in (False, True, {}, "", "   "):
            with self.subTest(value=value):
                self.assertIn("invalid decision", runner.check_execution_guard(lambda _: value, "running"))
        self.assertIsNone(runner.check_execution_guard(None, "running"))
        self.assertIsNone(runner.check_execution_guard(lambda _: None, "running"))
        self.assertLess(len(runner.check_execution_guard(lambda _: "x" * 10000, "running")), 320)
        with patch.object(runner, "source_identities") as sources:
            def fail(_):
                raise OSError("PRIVATE_ERROR_DETAIL")
            self.assertEqual(runner.check_execution_guard(fail, "running"),
                             "execution guard running failed (OSError)")
            sources.assert_not_called()

    def test_cpu_deltas_keep_failed_work_and_unknown_counters_distinct(self):
        observed = runner.reaped_child_cpu_delta((1.25, 0.5), (2.0, 0.75))
        self.assertEqual(observed["user_seconds"], 0.75)
        self.assertEqual(observed["system_seconds"], 0.25)
        self.assertEqual(runner.reaped_child_cpu_delta((1, 1), (1, 1))["user_seconds"], 0)
        for before, after in ((None, (1, 1)), ((1, 1), None),
                              ((2, 1), (1, 1)), ((1, 1), (float("nan"), 2)),
                              ((True, 1), (2, 2)), ((1,), (2, 2))):
            with self.subTest(before=before, after=after):
                value = runner.reaped_child_cpu_delta(before, after)
                self.assertIsNone(value["user_seconds"])
                self.assertIsNone(value["system_seconds"])

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


class OwnedGroupObservationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.proc = Path(temporary.name)

    def stat(self, pid, *, group=123, session=123, state="S", name="python", ppid=1):
        directory = self.proc / str(pid)
        directory.mkdir()
        fields = [state, str(ppid), str(group), str(session)] + ["0"] * 15 + ["98765"]
        (directory / "stat").write_text(f"{pid} ({name}) " + " ".join(fields))

    def test_records_only_owned_group_and_session_without_args_or_environment(self):
        self.stat(21, name="worker ) name")
        self.stat(22, state="Z")
        self.stat(23, group=999)
        self.stat(24, session=999)
        # Never read these files, even for a selected member.
        (self.proc / "21/cmdline").write_text("PRIVATE_COMMAND_TOKEN")
        (self.proc / "21/environ").write_text("PRIVATE_ENV_TOKEN")
        value = runner.observe_owned_group(123, proc_root=self.proc)
        self.assertTrue(value["available"])
        self.assertEqual([item["pid"] for item in value["members"]], [21, 22])
        self.assertEqual(value["members"][0]["name"], "worker ) name")
        self.assertEqual(value["members"][1]["state"], "Z")
        self.assertEqual(value["members"][0]["start_ticks"], 98765)
        self.assertNotIn("PRIVATE_", json.dumps(value))
        self.assertNotIn("cleanup_ok", value)

    def test_missing_or_malformed_stats_are_unknown_not_proof_of_exit(self):
        (self.proc / "21").mkdir()
        (self.proc / "22").mkdir()
        (self.proc / "22/stat").write_text("malformed")
        (self.proc / "23").mkdir()
        (self.proc / "23/stat").write_bytes(b"x" * 4097)
        (self.proc / "self").mkdir()
        value = runner.observe_owned_group(123, proc_root=self.proc)
        self.assertEqual(value["scanned"], 3)
        self.assertEqual(value["unreadable"], 3)
        self.assertEqual(value["members"], [])
        missing = runner.observe_owned_group(123, proc_root=self.proc / "absent")
        self.assertFalse(missing["available"])
        self.assertEqual(missing["error"], "FileNotFoundError")

    def test_scan_and_member_budgets_report_truncation(self):
        for pid in (21, 22, 23):
            self.stat(pid)
        value = runner.observe_owned_group(123, proc_root=self.proc, scan_limit=2, member_limit=1)
        self.assertEqual(value["scanned"], 2)
        self.assertEqual(len(value["members"]), 1)
        self.assertTrue(value["scan_truncated"])
        self.assertTrue(value["members_truncated"])

    def test_invalid_bounds_do_not_read_proc(self):
        for group, kwargs in ((True, {}), (0, {}), (-1, {}),
                              (123, {"scan_limit": 0}), (123, {"member_limit": 33})):
            with self.subTest(group=group, kwargs=kwargs), patch.object(runner.os, "scandir") as read:
                with self.assertRaises(ValueError):
                    runner.observe_owned_group(group, proc_root=self.proc, **kwargs)
                read.assert_not_called()


@unittest.skipUnless(os.name == "posix", "run on the authorized POSIX worker")
class ProcessTests(unittest.TestCase):
    def setUp(self):
        InputTests.setUp(self)

    def test_cpu_accounting_survives_an_assertion_failure(self):
        failure = PASS.replace("... ok", "... FAILED").replace(
            "result: ok. 1 passed; 0 failed", "result: FAILED. 0 passed; 1 failed")
        busy = ("import time; until=time.process_time()+0.1; "
                "exec('while time.process_time()<until: pass')")
        code = ("import subprocess,sys; subprocess.run([sys.executable,'-I','-S','-c',"
                + repr(busy) + "],check=True); print(" + repr(failure)
                + "); sys.exit(1)")
        result = self.execute(code)
        self.assertEqual(result["status"], "TESTS_FAILED")
        cpu = result["cpu_accounting"]
        self.assertGreater(cpu["user_seconds"] + cpu["system_seconds"], 0)
        if os.name == "nt":
            self.assertEqual(cpu["active_processes"], 0)
        self.assertEqual(cpu["method"], "windows_private_job_including_launcher"
                         if os.name == "nt" else "posix_process_reaped_children_delta")
        saved = json.loads((self.root / "output/result.json").read_text())
        self.assertEqual(saved["cpu_accounting"], cpu)

    def test_missing_cpu_observation_does_not_change_native_verdict(self):
        if os.name == "nt":
            from scout_native_windows import JobAPI
            missing = patch.object(JobAPI, "cpu_accounting", side_effect=OSError("unavailable"))
        else:
            missing = patch.object(runner, "reaped_child_cpu", return_value=None)
        with missing:
            result = self.execute("print(" + repr(PASS) + ")")
        self.assertEqual(result["status"], "TESTS_PASSED")
        self.assertIsNone(result["cpu_accounting"]["user_seconds"])
        self.assertIsNone(result["cpu_accounting"]["system_seconds"])
        if os.name == "nt":
            self.assertIsNone(result["cpu_accounting"]["active_processes"])

    def execute(self, code, **overrides):
        options = {"cwd": self.root, "output": self.root / "output",
                   "command": [sys.executable, "-B", "-c", code],
                   "sources": [("source.rs", self.sha)], "format": "rust-libtest",
                   "expected_tests": ["contract"], "timeout": 2}
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
        options = {"format": "pytest-junit", "expected_tests": ["tests.test_contract::test_case"]}
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

    def execute_vitest(self, code, **overrides):
        options = {"format": "vitest-json", "expected_tests": ["contract regression"]}
        options.update(overrides)
        return self.execute(code, **options)

    def test_gtest_capture_owns_report_and_keeps_terminal_log(self):
        from test_scout_native_gtest import FIXTURE

        text = FIXTURE["cases"]["pass"]["xml"]
        code = ("import sys; from pathlib import Path; "
                "assert sys.argv[-1].startswith('--gtest_output=xml:'); "
                "Path(sys.argv[-1].split('xml:',1)[1]).write_text(" + repr(text) + "); "
                "print('native assertion diagnostics')")
        result = self.execute(code, format="gtest-xml", expected_tests=["Report::Pass"])
        self.assertEqual(result["status"], "TESTS_PASSED")
        report = self.root / "output/gtest.xml"
        self.assertEqual(result["test_report"], {"path": str(report), "sha256": runner.digest(report)})
        self.assertIn("native assertion diagnostics", (self.root / "output/terminal.log").read_text())

    def test_catch2_capture_owns_xml_and_success_options(self):
        from test_scout_catch2_xml import case, report
        from xml.etree import ElementTree as ET

        text = ET.tostring(report(case(assertions=(True, True))), encoding="unicode")
        script = self.root / "fake_catch.py"
        script.write_text("import sys; from pathlib import Path; "
                          "assert sys.argv[-5:-1]==['--reporter','xml','--success','--out']; "
                          "Path(sys.argv[-1]).write_text(" + repr(text) + ",encoding='utf-8'); "
                          "print('retained native diagnostics')", encoding="utf-8")
        result = self.execute("", command=[sys.executable, str(script)], format="catch2-v2-xml")
        self.assertEqual(result["status"], "TESTS_PASSED")
        self.assertEqual(result["summary"]["passed"], 1)
        self.assertEqual(result["summary"]["catch2_xml"]["assertions"]["passed"], 2)
        path = self.root / "output/catch2.xml"
        self.assertEqual(result["test_report"], {"path": str(path), "sha256": runner.digest(path)})
        self.assertIn("retained native diagnostics", (self.root / "output/terminal.log").read_text())

    def test_catch2_assertions_failed_is_a_test_failure_not_an_abnormal_exit(self):
        from test_scout_catch2_xml import case, report
        from xml.etree import ElementTree as ET

        text = ET.tostring(report(case(assertions=(False, False))), encoding="unicode")
        script = self.root / "fake_catch.py"
        script.write_text("import sys; from pathlib import Path; "
                          "Path(sys.argv[-1]).write_text(" + repr(text) + ",encoding='utf-8'); "
                          "sys.exit(2)", encoding="utf-8")
        result = self.execute("", command=[sys.executable, str(script)], format="catch2-v2-xml")
        self.assertEqual(result["status"], "TESTS_FAILED")
        self.assertEqual(result["summary"]["failed"], 1)
        self.assertEqual(result["summary"]["catch2_xml"]["assertions"]["failed"], 2)

    def test_catch2_unknown_outcomes_are_not_zero_execution(self):
        from test_scout_catch2_xml import case, report
        from xml.etree import ElementTree as ET

        root = report(case(assertions=(False,)))
        ET.SubElement(root.find("Group/TestCase/Expression"), "Exception")
        text = ET.tostring(root, encoding="unicode")
        script = self.root / "fake_catch.py"
        script.write_text("import sys; from pathlib import Path; "
                          "Path(sys.argv[-1]).write_text(" + repr(text) + ",encoding='utf-8'); "
                          "sys.exit(1)", encoding="utf-8")
        result = self.execute("", command=[sys.executable, str(script)], format="catch2-v2-xml")
        self.assertEqual(result["status"], "INCONCLUSIVE")
        self.assertIsNone(result["summary"]["executed"])
        self.assertIsNone(result["summary"]["failed"])
        self.assertFalse(result["summary"]["catch2_xml"]["accounting_complete"])
        self.assertEqual(result["summary"]["catch2_xml"]["reported_test_cases"]["failures"], 1)

    def test_catch2_report_success_short_clusters_and_separator_rejected_before_launch(self):
        for flag in ("--reporter", "--reporter=junit", "--out=old.xml", "--out", "--success=false",
                     "--success", "-rxml", "-oold.xml", "-s", "-srxml", "--"):
            with self.subTest(flag=flag), patch.object(runner.subprocess, "Popen") as child:
                with self.assertRaisesRegex(ValueError, "runner owns"):
                    self.execute("", command=[sys.executable, flag], format="catch2-v2-xml")
                child.assert_not_called()
            self.assertFalse((self.root / "output").exists())

    def test_gtest_output_repeat_flags_and_environment_rejected_before_launch(self):
        from unittest.mock import patch

        overrides = [{"command": [sys.executable, flag]} for flag in (
            "--gtest_output=xml:old.xml", "--gtest_output", "--gtest_repeat=2")]
        overrides += [{"environment": {key: value}} for key, value in (
            ("GTEST_OUTPUT", "xml:old.xml"), ("GTEST_REPEAT", "2"))]
        for options in overrides:
            with self.subTest(options=options), patch.object(runner.subprocess, "Popen") as child:
                with self.assertRaises(ValueError):
                    self.execute("", format="gtest-xml", expected_tests=["Report::Pass"], **options)
                child.assert_not_called()
            self.assertFalse((self.root / "output").exists())

    def test_gtest_missing_truncated_large_or_symlink_report_is_inconclusive(self):
        from test_scout_native_gtest import FIXTURE

        text = FIXTURE["cases"]["pass"]["xml"]
        prefix = ("import sys; from pathlib import Path; "
                  "report=Path(sys.argv[-1].split('xml:',1)[1]); ")
        for index, code in enumerate(("print('1 passed')", prefix + "report.write_text(" + repr(text[:-15]) + ")",
                                     prefix + "report.write_text('x'*(2*1024*1024+1))",
                                     prefix + "report.symlink_to(Path('source.rs').resolve())")):
            with self.subTest(index=index):
                result = self.execute(code, format="gtest-xml", expected_tests=["Report::Pass"],
                                      output=self.root / ("output" + str(index)))
                self.assertEqual(result["status"], "INCONCLUSIVE")

    def test_gtest_inherited_repeat_environment_is_rejected(self):
        from unittest.mock import patch

        with patch.dict(os.environ, {"GTEST_REPEAT": "2"}), patch.object(runner.subprocess, "Popen") as child:
            with self.assertRaises(ValueError):
                self.execute("", format="gtest-xml", expected_tests=["Report::Pass"])
            child.assert_not_called()

    def write_vitest(self, failed=False):
        from test_scout_native_vitest import report

        text = json.dumps(report(("regression", "failed" if failed else "passed")))
        return ("import sys; from pathlib import Path; assert sys.argv[-2]=='--reporter=json'; "
                "assert sys.argv[-1].startswith('--outputFile='); "
                "Path(sys.argv[-1].split('=',1)[1]).write_text(" + repr(text) + ",encoding='utf-8'); ")

    def test_vitest_capture_owns_json_and_keeps_terminal_log(self):
        result = self.execute_vitest(self.write_vitest() + "print('native diagnostics')")
        self.assertEqual(result["status"], "TESTS_PASSED")
        report_path = self.root / "output/vitest.json"
        self.assertEqual(result["test_report"], {"path": str(report_path), "sha256": runner.digest(report_path)})
        self.assertIn("native diagnostics", (self.root / "output/terminal.log").read_text())
        self.assertEqual(result["summary"]["executed"], 1)

    def test_vitest_case_failure_and_abnormal_signal_are_distinct(self):
        result = self.execute_vitest(self.write_vitest(failed=True) + "sys.exit(1)")
        self.assertEqual(result["status"], "TESTS_FAILED")
        result = self.execute_vitest(self.write_vitest(failed=True) +
            "import os,signal; os.kill(os.getpid(),signal.SIGTERM)", output=self.root / "signal-output")
        self.assertEqual(result["status"], "INCONCLUSIVE")
        self.assertEqual(result["summary"]["failed"], 1)

    def test_vitest_missing_large_symlink_or_non_utf8_report_has_no_pass(self):
        prefix = "import sys; from pathlib import Path; p=Path(sys.argv[-1].split('=',1)[1]); "
        codes = ["print('all passed')", prefix + "p.write_bytes(b'x'*(2*1024*1024+1))",
                 prefix + "p.symlink_to(Path('source.rs').resolve())", prefix + "p.write_bytes(bytes([255]))"]
        for index, code in enumerate(codes):
            with self.subTest(index=index):
                result = self.execute_vitest(code, output=self.root / f"invalid-{index}")
                self.assertEqual(result["status"], "INCONCLUSIVE")
                self.assertIsNone(result["summary"])

    def test_vitest_report_cannot_bypass_timeout_or_source_change(self):
        for index, code in enumerate(("import time; time.sleep(30)", "Path('source.rs').write_text('changed')")):
            result = self.execute_vitest(self.write_vitest() + code,
                output=self.root / f"interrupted-{index}", timeout=0.3)
            self.assertEqual(result["status"], "INCONCLUSIVE")
            self.assertIsNone(result["summary"])

    def test_vitest_existing_reporter_arguments_rejected_before_child(self):
        from unittest.mock import patch

        for flag in ("--reporter", "--reporter=json", "--outputFile", "--outputFile=old.json",
                     "--output-file=old.json", "--outputFile.json=old.json"):
            with self.subTest(flag=flag), patch.object(runner.subprocess, "Popen") as child:
                with self.assertRaisesRegex(ValueError, "runner owns"):
                    self.execute_vitest("print('not run')", command=[sys.executable, "unused", flag])
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
        self.assertIsNotNone(result["cpu_accounting"]["user_seconds"])
        self.assertIsNotNone(result["cpu_accounting"]["system_seconds"])
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
                    self.assertTrue(result["post_exit_group_cleanup_required"])
                    observation = result["post_exit_group_observation"]
                    if sys.platform.startswith("linux"):
                        self.assertTrue(observation["available"])
                        self.assertIn(int((self.root / "child.pid").read_text()),
                                      [member["pid"] for member in observation["members"]])
                    self.assert_child_stopped(int((self.root / "child.pid").read_text()))
                finally:
                    # Preserve safe teardown even when replayed against the old runner.
                    pid_file = self.root / "child.pid"
                    if pid_file.exists():
                        try:
                            os.kill(int(pid_file.read_text()), signal.SIGTERM)
                        except ProcessLookupError:
                            pass

    def test_naturally_exiting_descendant_is_awaited_without_signals(self):
        from unittest.mock import patch

        child = (
            "import sys,time; from pathlib import Path; "
            "Path('child.ready').touch(); sys.stdin.buffer.read(); time.sleep(0.05)"
        )
        code = (
            "import subprocess,sys,time; from pathlib import Path; "
            "p=subprocess.Popen([sys.executable,'-B','-c'," + repr(child) + "],"
            "stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
            "Path('child.pid').write_text(str(p.pid)); "
            "exec(\"while not Path('child.ready').exists(): time.sleep(0.01)\"); "
            "print(" + repr(PASS) + ")"
        )
        with patch.object(runner, "stop_group", wraps=runner.stop_group) as stop:
            result = self.execute(code)
        self.assertEqual(result["status"], "TESTS_PASSED")
        self.assertFalse(result["post_exit_group_cleanup_required"])
        self.assertGreater(result["post_exit_group_wait_seconds"], 0.01)
        stop.assert_not_called()
        self.assert_child_stopped(int((self.root / "child.pid").read_text()))

    def test_failed_diagnostic_cannot_prevent_owned_group_cleanup(self):
        code = (
            "import subprocess,sys; from pathlib import Path; "
            "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],"
            "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
            "Path('child.pid').write_text(str(p.pid)); print(" + repr(PASS) + ")"
        )
        with patch.object(runner, "observe_owned_group", side_effect=RuntimeError("PRIVATE_DETAIL")):
            result = self.execute(code)
        self.assertEqual(result["status"], "INCONCLUSIVE")
        self.assertTrue(result["post_exit_group_cleanup_required"])
        self.assertEqual(result["post_exit_group_observation"]["error"], "RuntimeError")
        self.assertNotIn("PRIVATE_DETAIL", json.dumps(result))
        self.assert_child_stopped(int((self.root / "child.pid").read_text()))

    def test_natural_group_wait_never_extends_the_command_deadline(self):
        from unittest.mock import patch

        with patch.object(runner.os, "killpg") as probe, \
                patch.object(runner.time, "monotonic", return_value=20.0), \
                patch.object(runner.time, "sleep") as sleep:
            self.assertFalse(runner.wait_for_group_exit(123, 19.0))
        probe.assert_called_once_with(123, 0)
        sleep.assert_not_called()

    def test_group_disappearance_must_be_observed(self):
        from unittest.mock import patch

        with patch.object(runner.os, "killpg", side_effect=[None, ProcessLookupError]), \
                patch.object(runner.time, "monotonic", return_value=20.0), \
                patch.object(runner.time, "sleep") as sleep:
            self.assertTrue(runner.wait_for_group_exit(123, 20.005))
        self.assertAlmostEqual(sleep.call_args.args[0], 0.005)

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
                          {"expected_tests": []}, {"timeout": 0}, {"_execution_guard": object()}, {"_gpu_uuid": "0"},
                          {"_gpu_uuid": "GPU-00000000-0000-0000-0000-000000000000"}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.execute("print('should not run')", **overrides)
            self.assertFalse((self.root / "output").exists())


@unittest.skipUnless(os.name == "posix", "real POSIX control flow; no GPU code")
class GuardedProcessTests(unittest.TestCase):
    setUp = ProcessTests.setUp
    execute = ProcessTests.execute
    execute_junit = ProcessTests.execute_junit
    write_junit = ProcessTests.write_junit

    def guarded(self, code, guard, **arguments):
        guard.evidence = {"control_test": True}
        return self.execute_junit(code, _gpu_uuid="GPU-00000000-0000-0000-0000-000000000000",
                                  _execution_guard=guard, **arguments)

    def test_rejected_admission_never_starts_a_child(self):
        def guard(phase):
            return "reserve unavailable" if phase == "admission" else None
        with patch.object(runner.subprocess, "Popen") as child:
            result = self.guarded("raise RuntimeError('must not execute')", guard)
        child.assert_not_called()
        self.assertEqual(result["status"], "INCONCLUSIVE")
        self.assertIsNone(result["exit_code"])
        self.assertIsNone(result["summary"])
        self.assertEqual((self.root / "output/terminal.log").read_bytes(), b"")
        self.assertEqual(json.loads((self.root / "output/result.json").read_text()), result)

    def test_admission_time_is_included_in_the_launch_deadline(self):
        def guard(phase):
            if phase == "admission":
                time.sleep(.03)
        with patch.object(runner.subprocess, "Popen") as child:
            result = self.guarded("raise RuntimeError('must not execute')", guard, timeout=.01)
        child.assert_not_called()
        self.assertIn("before command launch", result["issues"][0])

    def test_running_guard_stops_only_owned_child_even_after_a_valid_report(self):
        other = subprocess.Popen([sys.executable, "-I", "-S", "-c", "import time; time.sleep(30)"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            phases = []
            marker = self.root / "ready"
            def guard(phase):
                phases.append(phase)
                if phase == "running" and marker.exists():
                    raise OSError("PRIVATE_TELEMETRY_ERROR")
            code = self.write_junit(JUNIT_PASS) + (
                "import os,time; Path('ready').write_text(str(os.getpid())); time.sleep(30)")
            result = self.guarded(code, guard, timeout=3)
            self.assertEqual(result["status"], "INCONCLUSIVE")
            self.assertIsNone(result["summary"])
            self.assertIn("guard running failed (OSError)", result["issues"][0])
            self.assertNotIn("PRIVATE", str(result))
            self.assertIn("postflight", phases)
            self.assertNotEqual(result["exit_code"], 0)
            with self.assertRaises(ProcessLookupError):
                os.kill(int(marker.read_text()), 0)
            self.assertIsNone(other.poll())
        finally:
            other.terminate()
            other.wait(timeout=5)

    def test_pipe_eof_does_not_disable_running_guard(self):
        pipe_closed = []
        original = runner.selectors.DefaultSelector
        @contextmanager
        def observed_selector():
            with original() as selector:
                yield selector
            pipe_closed.append(True)
        def guard(phase):
            if phase == "running" and pipe_closed:
                return "reserve lost after output closure"
        code = self.write_junit(JUNIT_PASS) + "import os,time; os.close(1); os.close(2); time.sleep(30)"
        with patch.object(runner.selectors, "DefaultSelector", observed_selector):
            result = self.guarded(code, guard, timeout=3)
        self.assertEqual(result["status"], "INCONCLUSIVE")
        self.assertIn("reserve lost after output closure", result["issues"][0])
        self.assertIsNone(result["summary"])

    def test_postflight_failure_overrides_exit_zero_and_junit_pass(self):
        def guard(phase):
            return "postflight telemetry missing" if phase == "postflight" else None
        result = self.guarded(self.write_junit(JUNIT_PASS), guard)
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["status"], "INCONCLUSIVE")
        self.assertIsNone(result["summary"])
        self.assertIn("guard postflight", result["issues"][0])
        self.assertTrue((self.root / "output/junit.xml").exists())

    def test_guarded_pass_keeps_exact_selected_uuid_and_observations(self):
        phases = []
        def guard(phase):
            phases.append(phase)
            guard.evidence[phase] = True
        code = self.write_junit(JUNIT_PASS) + (
            "import os; assert os.environ['CUDA_VISIBLE_DEVICES']=='GPU-00000000-0000-0000-0000-000000000000'")
        result = self.guarded(code, guard)
        self.assertEqual(result["status"], "TESTS_PASSED")
        self.assertEqual(phases[0], "admission")
        self.assertEqual(phases[-1], "postflight")
        self.assertIn("running", phases)
        self.assertTrue(result["execution_guard"]["postflight"])
        self.assertEqual(json.loads((self.root / "output/result.json").read_text()), result)


@unittest.skipUnless(os.name == "nt", "native Windows Job Object controls")
class WindowsProcessTests(unittest.TestCase):
    setUp = ProcessTests.setUp
    execute_junit = ProcessTests.execute_junit
    write_junit = ProcessTests.write_junit
    execute_vitest = ProcessTests.execute_vitest
    write_vitest = ProcessTests.write_vitest

    def execute(self, code, **overrides):
        overrides.setdefault("native_windows", True)
        overrides.setdefault("timeout", 3)
        return ProcessTests.execute(self, code, **overrides)

    test_complete_terminal_and_private_environment = ProcessTests.test_complete_terminal_and_private_environment
    test_exit_zero_without_registered_target_is_inconclusive = ProcessTests.test_exit_zero_without_registered_target_is_inconclusive
    test_junit_capture_owns_report_and_preserves_stdout = ProcessTests.test_junit_capture_owns_report_and_preserves_stdout
    test_junit_assertion_failure_remains_a_test_failure = ProcessTests.test_junit_assertion_failure_remains_a_test_failure
    test_preexisting_junit_output_argument_rejected_before_launch = ProcessTests.test_preexisting_junit_output_argument_rejected_before_launch
    test_gtest_capture_owns_report_and_keeps_terminal_log = ProcessTests.test_gtest_capture_owns_report_and_keeps_terminal_log
    test_gtest_output_repeat_flags_and_environment_rejected_before_launch = ProcessTests.test_gtest_output_repeat_flags_and_environment_rejected_before_launch
    test_catch2_capture_owns_xml_and_success_options = ProcessTests.test_catch2_capture_owns_xml_and_success_options
    test_catch2_assertions_failed_is_a_test_failure_not_an_abnormal_exit = ProcessTests.test_catch2_assertions_failed_is_a_test_failure_not_an_abnormal_exit
    test_catch2_unknown_outcomes_are_not_zero_execution = ProcessTests.test_catch2_unknown_outcomes_are_not_zero_execution
    test_catch2_report_success_short_clusters_and_separator_rejected_before_launch = ProcessTests.test_catch2_report_success_short_clusters_and_separator_rejected_before_launch
    test_vitest_capture_owns_json_and_keeps_terminal_log = ProcessTests.test_vitest_capture_owns_json_and_keeps_terminal_log
    test_failed_test_is_not_process_failure_only = ProcessTests.test_failed_test_is_not_process_failure_only
    test_cpu_accounting_survives_an_assertion_failure = ProcessTests.test_cpu_accounting_survives_an_assertion_failure
    test_missing_cpu_observation_does_not_change_native_verdict = ProcessTests.test_missing_cpu_observation_does_not_change_native_verdict
    test_source_mutation_invalidates_pass = ProcessTests.test_source_mutation_invalidates_pass
    test_log_limit_stops_without_partial_pass = ProcessTests.test_log_limit_stops_without_partial_pass
    test_non_utf8_log_has_no_verdict = ProcessTests.test_non_utf8_log_has_no_verdict

    def assert_pid_stopped(self, pid):
        import ctypes
        dll = ctypes.WinDLL("kernel32", use_last_error=True)
        dll.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        dll.OpenProcess.restype = ctypes.c_void_p
        dll.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        dll.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = dll.OpenProcess(0x100000, False, pid)  # SYNCHRONIZE only.
        if not handle:
            self.assertEqual(ctypes.get_last_error(), 87)  # No process with this PID.
            return
        try:
            self.assertEqual(dll.WaitForSingleObject(handle, 5000), 0)
        finally:
            dll.CloseHandle(handle)

    def test_timeout_and_leader_exit_kill_only_owned_job(self):
        other = subprocess.Popen([sys.executable, "-I", "-S", "-c", "import time; time.sleep(30)"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for index, leader_wait in enumerate((True, False)):
                code = (
                    "import subprocess,sys,time; from pathlib import Path; "
                    "p=subprocess.Popen([sys.executable,'-I','-S','-c','import time; time.sleep(30)']); "
                    "Path('child.pid').write_text(str(p.pid)); "
                    + ("time.sleep(30)" if leader_wait else "print(" + repr(PASS) + ")")
                )
                result = self.execute(code, output=self.root / f"timeout-{index}", timeout=1)
                self.assertEqual(result["status"], "INCONCLUSIVE", result)
                self.assertTrue(result["windows_job_cleanup_verified"], result)
                self.assertIsNotNone(result["cpu_accounting"]["user_seconds"])
                self.assertIsNotNone(result["cpu_accounting"]["system_seconds"])
                self.assert_pid_stopped(int((self.root / "child.pid").read_text()))
                self.assertIsNone(other.poll(), "unrelated process was touched")
        finally:
            other.terminate()
            other.wait(timeout=5)

    def test_redirected_background_child_cannot_hide_behind_pass_report(self):
        code = (
            "import subprocess,sys; from pathlib import Path; "
            "p=subprocess.Popen([sys.executable,'-I','-S','-c','import time; time.sleep(30)'],"
            "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
            "Path('child.pid').write_text(str(p.pid)); print(" + repr(PASS) + ")"
        )
        result = self.execute(code)
        self.assertEqual(result["status"], "INCONCLUSIVE", result)
        self.assertTrue(result["post_exit_group_cleanup_required"])
        self.assertTrue(result["windows_job_cleanup_verified"])
        self.assert_pid_stopped(int((self.root / "child.pid").read_text()))

    def test_natural_background_shutdown_is_awaited(self):
        child = "import sys,time; from pathlib import Path; Path('ready').touch(); sys.stdin.read(); time.sleep(.1)"
        code = (
            "import subprocess,sys,time; from pathlib import Path; "
            "p=subprocess.Popen([sys.executable,'-I','-S','-c'," + repr(child) + "],"
            "stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
            "\nwhile not Path('ready').exists(): time.sleep(.01)\n"
            "print(" + repr(PASS) + ")"
        )
        result = self.execute(code)
        self.assertEqual(result["status"], "TESTS_PASSED", result)
        self.assertFalse(result["post_exit_group_cleanup_required"])
        self.assertTrue(result["windows_job_cleanup_verified"])
        self.assertGreater(result["post_exit_group_wait_seconds"], 0.01)

    def test_native_exit_code_not_launcher_success_is_parsed(self):
        result = self.execute("import os; print(" + repr(PASS) + ",flush=True); os._exit(7)")
        self.assertEqual(result["exit_code"], 7)
        self.assertEqual(result["status"], "INCONCLUSIVE")

    def test_base_launcher_preserves_reviewed_venv_target(self):
        import scout_native_windows
        original = subprocess.Popen
        observed = []

        def launch(command, *args, **kwargs):
            if len(command) > 4 and command[1:4] == ["-I", "-S", "-B"] and command[4] == scout_native_windows.__file__:
                observed.append(list(command))
            return original(command, *args, **kwargs)

        with patch.object(subprocess, "Popen", side_effect=launch):
            result = self.execute("print(" + repr(PASS) + ")")
        self.assertEqual(result["status"], "TESTS_PASSED", result)
        expected = str(Path(getattr(sys, "_base_executable", None) or sys.executable).resolve())
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0][0], expected)
        self.assertEqual(result["windows_launcher_python"], expected)
        self.assertEqual(result["command"][0], sys.executable)

    def test_missing_and_oversized_junit_are_not_passes(self):
        large = ("import sys; from pathlib import Path; "
                 "Path(sys.argv[-1].split('=',1)[1]).write_text('x' * (2*1024*1024+1))")
        for index, code in enumerate(("print('all passed')", large)):
            result = self.execute_junit(code, output=self.root / f"report-{index}")
            self.assertEqual(result["status"], "INCONCLUSIVE")
            self.assertIsNone(result["summary"])

    def test_invalid_expected_names_and_gpu_rejected_before_launch(self):
        for overrides in ({"expected_tests": []}, {"_gpu_uuid": "GPU-00000000-0000-0000-0000-000000000000"},
                          {"environment": {"cuda_visible_devices": "0"}},
                          {"environment": {"PATH": "x", "Path": "y"}}):
            with patch.object(runner.subprocess, "Popen") as child, self.assertRaises(ValueError):
                self.execute("raise RuntimeError('must not run')", **overrides)
            child.assert_not_called()
        self.assertFalse((self.root / "output").exists())

    def test_isolated_launcher_does_not_load_ambient_sitecustomize(self):
        (self.root / "sitecustomize.py").write_text("raise RuntimeError('ambient code')")
        result = self.execute("print(" + repr(PASS) + ")", environment={"PYTHONPATH": str(self.root)})
        # The reviewed target may load its own sitecustomize; the -I -S launcher must not.
        self.assertEqual(result["status"], "TESTS_PASSED", result)
        self.assertEqual((self.root / "output/terminal.log").read_text().count("ambient code"), 1)

    def test_failed_assignment_does_not_launch_reviewed_target(self):
        import scout_native_windows
        config = self.root / "config.json"
        sentinel = self.root / "must-not-exist"
        config.write_text(json.dumps({"job": 0, "nonce": "control",
            "status": str(self.root / "status.json"),
            "command": [sys.executable, "-c", "from pathlib import Path; Path(" + repr(str(sentinel)) + ").touch()"]}))
        child = subprocess.run([sys.executable, "-I", "-S", "-B", scout_native_windows.__file__, str(config)],
                               capture_output=True, timeout=5)
        self.assertNotEqual(child.returncode, 0)
        self.assertFalse(sentinel.exists())
        self.assertFalse((self.root / "status.json").exists())

    def test_controller_exit_closes_job_and_stops_owned_descendants(self):
        target = (
            "import os,subprocess,sys,time; from pathlib import Path; "
            "p=subprocess.Popen([sys.executable,'-I','-S','-c','import time; time.sleep(30)']); "
            "Path('owned.pids').write_text(str(os.getpid())+' '+str(p.pid)); time.sleep(30)"
        )
        options = dict(cwd=str(self.root), output=str(self.root / "controller-output"),
                       command=[sys.executable, "-I", "-S", "-c", target],
                       sources=[("source.rs", self.sha)], format="rust-libtest",
                       expected_tests=["contract"], native_windows=True, timeout=30)
        code = ("import sys; sys.path.insert(0," + repr(str(Path(runner.__file__).parent)) + "); "
                "import scout_native_run; scout_native_run.run(**" + repr(options) + ")")
        controller = subprocess.Popen([sys.executable, "-I", "-S", "-B", "-c", code],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 5
            while not (self.root / "owned.pids").exists() and time.monotonic() < deadline:
                self.assertIsNone(controller.poll())
                time.sleep(.01)
            self.assertTrue((self.root / "owned.pids").exists())
            pids = [int(pid) for pid in (self.root / "owned.pids").read_text().split()]
            self.assertEqual(len(pids), 2)
            controller.terminate()
            controller.wait(timeout=5)
            for pid in pids:
                self.assert_pid_stopped(pid)
        finally:
            if controller.poll() is None:
                controller.terminate()
                controller.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
