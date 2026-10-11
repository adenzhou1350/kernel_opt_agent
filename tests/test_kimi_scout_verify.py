"""Offline verifier controls; no Docker daemon, model, or untrusted code runs."""

import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout_verify as verify


class Process:
    def __init__(self, output=None, *, timeout=False, code=0):
        if output is None:
            output = (
                verify.SUMMARY_MARKER
                + json.dumps(
                    {
                        "tests_run": 1,
                        "failures": 0,
                        "errors": 0,
                        "skipped": 0,
                        "expected_failures": 0,
                        "unexpected_successes": 0,
                    }
                )
                + "\nKIMI_VERIFY_TEST_COUNT=1\n"
            ).encode()
        self.stdout = io.BytesIO(output)
        self.timeout = timeout
        self.returncode = None if timeout else code
        self.killed = False

    def wait(self, timeout):
        if self.timeout and not self.killed:
            raise subprocess.TimeoutExpired("fixed docker command", timeout)
        return self.returncode

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


class VerifyTests(unittest.TestCase):
    def test_only_executed_assertion_discrimination_reaches_review(self):
        import kimi_scout_delivery as delivery

        for mode, expected in (
            ("assertion", "REVIEWING"),
            ("skip", "INCONCLUSIVE"),
            ("error", "REVIEWING"),
            ("expected_failure", "INCONCLUSIVE"),
        ):
            observed = {"inconclusive": False}
            for arm in ("before", "fixed"):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    (root / "subject.py").write_text(
                        f"fixed = {arm == 'fixed'}\n", encoding="utf-8"
                    )
                    # Identical test bytes in both arms. These are trusted local
                    # fixtures, not execution of model-generated code.
                    decorator = (
                        "    @unittest.expectedFailure\n"
                        if mode == "expected_failure"
                        else ""
                    )
                    (root / "test_subject.py").write_text(
                        "import unittest, subject\n"
                        "class Probe(unittest.TestCase):\n"
                        + decorator
                        + "    def test_regression(self):\n"
                        + (
                            "        if subject.fixed: self.skipTest('not exercised')\n"
                            if mode == "skip"
                            else ""
                        )
                        + (
                            "        if not subject.fixed: raise RuntimeError('setup failed')\n"
                            if mode == "error"
                            else ""
                        )
                        + (
                            "        self.fail('known failure')\n"
                            if mode == "expected_failure"
                            else "        self.assertTrue(subject.fixed)\n"
                        )
                        + "    def test_control(self): self.assertIsInstance(subject.fixed, bool)\n",
                        encoding="utf-8",
                    )
                    completed = subprocess.run(
                        [
                            sys.executable,
                            "-I",
                            "-B",
                            "-c",
                            verify.HARNESS.replace("'/input'", repr(str(root))),
                        ],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        timeout=10,
                        check=False,
                    )
                with (
                    patch.object(
                        verify.subprocess,
                        "Popen",
                        return_value=Process(
                            completed.stdout.replace(b"\r\n", b"\n"),
                            code=completed.returncode,
                        ),
                    ),
                    patch.object(
                        verify.subprocess,
                        "run",
                        return_value=type("Done", (), {"returncode": 0})(),
                    ),
                ):
                    observed[arm] = verify.run_case("/subject.py", "/test.py", 1)
            with self.subTest(mode=mode):
                self.assertEqual(delivery.classify(observed)[0], expected)
                if mode == "error":
                    self.assertIn("traceback", delivery.classify(observed)[1])

    def test_missing_duplicate_or_invalid_outcomes_are_inconclusive(self):
        valid = Process().stdout.getvalue()
        summary = {
            "tests_run": 1,
            "failures": 0,
            "errors": 0,
            "skipped": 0,
            "expected_failures": 0,
            "unexpected_successes": 0,
        }
        invalid = [
            None,
            [],
            {},
            {**summary, "tests_run": 2},
            {**summary, "errors": True},
            {**summary, "skipped": -1},
            {**summary, "expected_failures": 2},
        ]
        outputs = [
            b"KIMI_VERIFY_TEST_COUNT=1\n",
            valid + valid,
            valid + b"KIMI_VERIFY_TEST_SUMMARY=bad json\n",
        ]
        outputs.extend(
            (
                verify.SUMMARY_MARKER
                + json.dumps(value)
                + "\nKIMI_VERIFY_TEST_COUNT=1\n"
            ).encode()
            for value in invalid
        )
        for output in outputs:
            with (
                self.subTest(output=output),
                patch.object(verify.subprocess, "Popen", return_value=Process(output)),
                patch.object(
                    verify.subprocess,
                    "run",
                    return_value=type("Done", (), {"returncode": 0})(),
                ),
            ):
                self.assertTrue(
                    verify.run_case("/subject.py", "/test.py", 1)["inconclusive"]
                )

    def test_harness_writes_result_and_count_to_one_stream(self):
        self.assertIn(
            "unittest.TextTestRunner(verbosity=2, stream=sys.stdout)", verify.HARNESS
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "test_subject.py").write_text(
                "import unittest\n"
                "class Probe(unittest.TestCase):\n"
                "    def test_pass(self):\n"
                "        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            harness = verify.HARNESS.replace("'/input'", repr(str(root)))
            result = subprocess.run(
                [sys.executable, "-I", "-B", "-c", harness],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=10,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(result.stdout.splitlines()[-1], "KIMI_VERIFY_TEST_COUNT=1")

    def test_command_has_only_selected_readonly_files_and_fixed_isolation(self):
        name = "kimi-verify-" + "a" * 32
        args = verify.command("/private/baseline.py", "/private/test.py", name)
        for flag, value in (
            ("--pull", "never"),
            ("--runtime", "runc"),
            ("--log-driver", "none"),
            ("--network", "none"),
            ("--user", "65534:65534"),
            ("--cap-drop", "ALL"),
            ("--security-opt", "no-new-privileges=true"),
            ("--memory", "512m"),
            ("--memory-swap", "512m"),
            ("--cpus", "1"),
            ("--pids-limit", "64"),
        ):
            self.assertEqual(args[args.index(flag) + 1], value)
        self.assertIn("--read-only", args)
        mounts = [args[i + 1] for i, value in enumerate(args) if value == "--mount"]
        self.assertEqual(
            mounts,
            [
                "type=bind,src=/private/baseline.py,dst=/input/subject.py,readonly",
                "type=bind,src=/private/test.py,dst=/input/test_subject.py,readonly",
            ],
        )
        self.assertEqual(args[-5:], [verify.IMAGE, "-I", "-B", "-c", verify.HARNESS])
        self.assertNotIn("--privileged", args)
        self.assertNotIn("--gpus", args)
        self.assertIn("noexec", args[args.index("--tmpfs") + 1])
        with self.assertRaises(ValueError):
            verify.command("/a.py", "/b.py", "other-container")

    def test_torch_cpu_profile_is_pinned_with_same_isolation(self):
        name = "kimi-verify-" + "b" * 32
        default = verify.command("/a.py", "/b.py", name)
        args = verify.command("/a.py", "/b.py", name, profile="torch-cpu")
        self.assertEqual(args[args.index("--entrypoint") + 1], "/opt/venv/bin/python")
        self.assertEqual(args[-5], verify.TORCH_CPU_IMAGE)
        self.assertEqual(args[args.index("--memory") + 1], "2g")
        self.assertEqual(args[args.index("--memory-swap") + 1], "2g")
        for original, actual in zip(default, args):
            if original not in (verify.IMAGE, "/usr/local/bin/python3", "512m"):
                self.assertEqual(original, actual)
        self.assertIn("CUDA_VISIBLE_DEVICES=", args)
        self.assertIn("LD_PRELOAD=", args)
        self.assertNotIn("--gpus", args)
        with self.assertRaises(ValueError):
            verify.command("/a.py", "/b.py", name, profile="arbitrary-image")

    def test_run_case_threads_profile_without_changing_result_trust(self):
        with (
            patch.object(verify.subprocess, "Popen", return_value=Process()) as start,
            patch.object(
                verify.subprocess,
                "run",
                return_value=type("Done", (), {"returncode": 0})(),
            ),
        ):
            result = verify.run_case("/baseline.py", "/test.py", 1, profile="torch-cpu")
        self.assertIn(verify.TORCH_CPU_IMAGE, start.call_args.args[0])
        self.assertEqual(result["profile"], "torch-cpu")
        self.assertEqual(result["claim_scope"], verify.CLAIM_SCOPE)

    def test_timeout_kills_only_owned_client_and_uuid_container(self):
        process = Process(timeout=True)
        with (
            patch.object(verify.subprocess, "Popen", return_value=process) as start,
            patch.object(
                verify.subprocess,
                "run",
                return_value=type("Done", (), {"returncode": 0})(),
            ) as cleanup,
        ):
            result = verify.run_case("/baseline.py", "/test.py", 1)
        name = start.call_args.args[0][start.call_args.args[0].index("--name") + 1]
        self.assertRegex(name, r"^kimi-verify-[0-9a-f]{32}$")
        self.assertTrue(process.killed)
        self.assertTrue(result["timed_out"])
        self.assertTrue(result["inconclusive"])
        self.assertIsNone(result["exit_code"])
        self.assertEqual(
            cleanup.call_args.args[0], verify.DOCKER + ["rm", "--force", name]
        )
        self.assertEqual(start.call_args.kwargs["env"], verify.ENV)

    def test_bounded_output_and_zero_or_missing_tests_are_inconclusive(self):
        for output in (
            b"x" * (verify.MAX_OUTPUT_BYTES + 1),
            b"KIMI_VERIFY_TEST_COUNT=0\n",
            b"exited before harness\n",
        ):
            with (
                self.subTest(output_size=len(output)),
                patch.object(verify.subprocess, "Popen", return_value=Process(output)),
                patch.object(
                    verify.subprocess,
                    "run",
                    return_value=type("Done", (), {"returncode": 0})(),
                ),
            ):
                result = verify.run_case("/baseline.py", "/test.py", 1)
            self.assertTrue(result["inconclusive"])
            self.assertLessEqual(len(result["output"]), verify.MAX_OUTPUT_BYTES)
            if output == b"KIMI_VERIFY_TEST_COUNT=0\n":
                self.assertEqual(result["reported_tests_run"], 0)

    def test_reject_directory_oversize_and_symlink_without_docker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "folder.py"
            folder.mkdir()
            large = root / "large.py"
            large.write_bytes(b"x" * (verify.MAX_FILE_BYTES + 1))
            for target in (folder, large, root / "private.txt"):
                with self.assertRaises(ValueError):
                    verify.read_input(target)
            with (
                patch.object(Path, "is_symlink", return_value=True),
                self.assertRaises(ValueError),
            ):
                verify.read_input(root / "linked.py")

    def test_two_sequential_snapshots_hash_same_test_and_record_exit_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [
                root / (name + ".py") for name in ("baseline", "candidate", "test")
            ]
            for i, path in enumerate(paths):
                path.write_text(f"# public fixture {i}\n", encoding="utf-8")
            calls = []

            def run(subject, test, timeout, *, profile="stdlib"):
                calls.append((subject.read_bytes(), test.read_bytes(), subject, test))
                self.assertNotIn(subject, paths)
                self.assertEqual(profile, "stdlib")
                return {
                    "exit_code": 1 if len(calls) == 1 else 0,
                    "inconclusive": False,
                    "cleanup_ok": True,
                }

            with (
                patch.object(verify.sys, "platform", "linux"),
                patch.object(verify, "run_case", side_effect=run),
            ):
                result = verify.verify(*paths)
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0][1], calls[1][1])
            self.assertFalse(calls[0][2].exists())
            self.assertEqual(result["label"], "TEST_RESULT_NOT_PR_READY")
            self.assertEqual(result["profile"], "stdlib")
            self.assertEqual(result["image"], verify.IMAGE)
            self.assertEqual(result["claim_scope"], verify.CLAIM_SCOPE)
            self.assertEqual(result["before"]["exit_code"], 1)
            self.assertEqual(result["fixed"]["exit_code"], 0)
            self.assertEqual(
                set(result["input_sha256"]), {"baseline", "candidate", "test"}
            )

    def test_verify_and_cli_thread_only_selected_profile(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(verify.sys, "platform", "linux"),
            patch.object(verify, "read_input", return_value=b"# public fixture\n"),
            patch.object(
                verify,
                "run_case",
                return_value={
                    "exit_code": 0,
                    "inconclusive": False,
                    "cleanup_ok": True,
                },
            ) as run,
        ):
            paths = [Path(directory) / name for name in ("a.py", "b.py", "test.py")]
            result = verify.verify(*paths, profile="torch-cpu")
            self.assertEqual(result["image"], verify.TORCH_CPU_IMAGE)
            self.assertEqual(result["profile"], "torch-cpu")
            self.assertEqual(result["label"], "TEST_RESULT_NOT_PR_READY")
            self.assertEqual(run.call_count, 2)
            self.assertTrue(
                all(c.kwargs == {"profile": "torch-cpu"} for c in run.call_args_list)
            )
            with self.assertRaises(ValueError):
                verify.verify(*paths, profile="arbitrary-image")
        with (
            patch.object(verify, "verify", return_value={"inconclusive": False}) as run,
            patch("sys.stdout", new_callable=io.StringIO),
        ):
            self.assertEqual(
                verify.main(
                    [
                        "--baseline",
                        "a.py",
                        "--candidate",
                        "b.py",
                        "--test",
                        "test.py",
                        "--profile",
                        "torch-cpu",
                    ]
                ),
                0,
            )
        self.assertEqual(run.call_args.kwargs["profile"], "torch-cpu")

    def test_zero_tests_are_rejected_by_fixed_harness(self):
        self.assertIn("count = suite.countTestCases()", verify.HARNESS)
        self.assertIn("if not count:", verify.HARNESS)
        self.assertIn("sys.exit(5)", verify.HARNESS)


if __name__ == "__main__":
    unittest.main()
