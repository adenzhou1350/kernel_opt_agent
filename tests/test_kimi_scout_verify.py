"""Offline verifier controls; no Docker daemon, model, or untrusted code runs."""

import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout_verify as verify


class Process:
    def __init__(self, output=b"KIMI_VERIFY_TEST_COUNT=1\n", *, timeout=False, code=0):
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

            def run(subject, test, timeout):
                calls.append((subject.read_bytes(), test.read_bytes(), subject, test))
                self.assertNotIn(subject, paths)
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
            self.assertEqual(result["before"]["exit_code"], 1)
            self.assertEqual(result["fixed"]["exit_code"], 0)
            self.assertEqual(
                set(result["input_sha256"]), {"baseline", "candidate", "test"}
            )

    def test_zero_tests_are_rejected_by_fixed_harness(self):
        self.assertIn("count = suite.countTestCases()", verify.HARNESS)
        self.assertIn("if not count:", verify.HARNESS)
        self.assertIn("sys.exit(5)", verify.HARNESS)


if __name__ == "__main__":
    unittest.main()
