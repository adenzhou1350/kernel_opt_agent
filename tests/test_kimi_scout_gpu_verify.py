"""Offline tests: never probe a real GPU or execute reviewed subject code."""

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout_gpu_verify as verify

GPU = "GPU-affdb123-1234-5678-90ab-123456789abc"


def arm_result(**changes):
    result = {
        "exit_code": 1,
        "timed_out": False,
        "cleanup": True,
        "truncated": {"stdout": False, "stderr": False},
        "tests": {
            "uuid": GPU,
            "tests_run": 2,
            "skipped": 0,
            "failures": 1,
            "errors": 0,
        },
    }
    result.update(changes)
    return result


class ReviewedInputsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.paths, self.hashes = {}, {}
        for name in ("baseline", "candidate", "test"):
            data = ("# " + name + "\n").encode()
            path = self.root / (name + ".py")
            path.write_bytes(data)
            self.paths[name] = str(path)
            self.hashes[name] = hashlib.sha256(data).hexdigest()
        self.manifest = self.root / "reviewed.json"
        self.manifest.write_text(json.dumps(self.hashes))

    def test_exact_bytes_and_manifest_keys(self):
        data, hashes = verify.reviewed_inputs(self.paths, self.manifest)
        self.assertEqual(hashes, self.hashes)
        self.assertEqual(data["baseline"], b"# baseline\n")
        self.manifest.write_text(json.dumps({**self.hashes, "other": "x"}))
        with self.assertRaisesRegex(ValueError, "exactly"):
            verify.reviewed_inputs(self.paths, self.manifest)

    def test_tamper_rejected_before_lock_or_gpu_inventory(self):
        Path(self.paths["candidate"]).write_bytes(b"changed\n")
        args = types.SimpleNamespace(
            **self.paths,
            reviewed_sha256=str(self.manifest),
            gpu_uuid=GPU,
            lock_dir="unused",
        )
        with (
            mock.patch.object(sys, "platform", "linux"),
            mock.patch.object(verify, "gpu_lock") as lock,
            mock.patch.object(verify, "snapshot") as probe,
        ):
            with self.assertRaisesRegex(ValueError, "SHA256 mismatch: candidate"):
                verify.verify(args)
            lock.assert_not_called()
            probe.assert_not_called()

    def test_nonregular_and_oversized_inputs_rejected(self):
        with self.assertRaisesRegex(ValueError, "regular"):
            verify.read_regular(self.root)
        large = self.root / "large.py"
        large.write_bytes(b"x" * (verify.MAX_FILE + 1))
        with self.assertRaisesRegex(ValueError, "256 KiB"):
            verify.read_regular(large)


class InventoryTests(unittest.TestCase):
    def test_exact_uuid_inventory_and_foreign_gpu_process(self):
        outputs = [
            f"{GPU}, 2, 0, 0\n",
            "GPU-ffffffff-1111-2222-3333-444444444444, 101, busy\n",
        ]
        with mock.patch.object(
            subprocess,
            "run",
            side_effect=[types.SimpleNamespace(stdout=s) for s in outputs],
        ) as call:
            result = verify.snapshot(GPU)
        self.assertEqual(result["index"], 2)
        self.assertEqual(result["processes"], [])
        self.assertIn("--id=" + GPU, call.call_args_list[0].args[0])
        self.assertEqual(call.call_args_list[0].args[0][0], "/usr/bin/nvidia-smi")

    def test_unknown_metrics_and_uuid_mismatch_rejected(self):
        for text in (f"{GPU}, 0, N/A, 0\n", "GPU-other, 0, 0, 0\n"):
            with (
                self.subTest(text=text),
                mock.patch.object(
                    subprocess, "run", return_value=types.SimpleNamespace(stdout=text)
                ),
                self.assertRaises(ValueError),
            ):
                verify.snapshot(GPU)

    def test_three_samples_and_rejection_of_busy_device(self):
        idle = {
            "uuid": GPU,
            "index": 0,
            "memory_mib": 64,
            "utilization": 1,
            "processes": [],
        }
        with (
            mock.patch.object(verify, "snapshot", return_value=idle) as probe,
            mock.patch.object(verify.time, "sleep") as sleep,
        ):
            self.assertEqual(len(verify.idle_samples(GPU)), 3)
            self.assertEqual(probe.call_count, 3)
            self.assertEqual(sleep.call_args_list, [mock.call(1), mock.call(1)])
        for change in (
            {"memory_mib": 65},
            {"utilization": 2},
            {"processes": [[GPU, "77", "other"]]},
        ):
            with (
                self.subTest(change=change),
                mock.patch.object(verify, "snapshot", return_value={**idle, **change}),
                self.assertRaisesRegex(RuntimeError, "not idle"),
            ):
                verify.idle_samples(GPU)


class ProcessTests(unittest.TestCase):
    def test_bounded_output_timeout_and_nonroot_child(self):
        process = mock.Mock(
            pid=789,
            returncode=-9,
            stdout=io.BytesIO(b"x" * 40000),
            stderr=io.BytesIO(b"y" * 40000),
        )
        process.wait.side_effect = subprocess.TimeoutExpired("python", 30)
        with (
            mock.patch.object(verify.os, "geteuid", return_value=0, create=True),
            mock.patch.object(subprocess, "Popen", return_value=process) as start,
            mock.patch.object(verify, "clean_group", return_value=True),
        ):
            result = verify.run_process(
                [sys.executable, "-I", "harness.py"], "/private", {}
            )
        self.assertTrue(result["timed_out"])
        self.assertTrue(result["cleanup"])
        self.assertEqual(len(result["stderr"]), verify.MAX_OUTPUT)
        self.assertEqual(len(result["stdout"]), verify.MAX_OUTPUT)
        self.assertTrue(all(result["truncated"].values()))
        self.assertEqual(start.call_args.kwargs["user"], 65534)
        self.assertEqual(start.call_args.kwargs["extra_groups"], [])
        self.assertTrue(start.call_args.kwargs["start_new_session"])

    def test_cleanup_signals_only_the_owned_process_group(self):
        process = mock.Mock(pid=789)
        with (
            mock.patch.object(verify.os, "killpg", create=True) as kill,
            mock.patch.object(verify.signal, "SIGKILL", 9, create=True),
            mock.patch.object(verify, "group_exists", side_effect=[True, False, False]),
            mock.patch.object(verify.time, "sleep"),
        ):
            self.assertTrue(verify.clean_group(process))
        self.assertEqual([call.args[0] for call in kill.call_args_list], [789, 789])

    def test_nonblocking_lock_uses_canonical_uuid_and_closes_on_contention(self):
        fake = types.SimpleNamespace(
            LOCK_EX=2, LOCK_NB=4, flock=mock.Mock(side_effect=BlockingIOError("busy"))
        )
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.dict(sys.modules, {"fcntl": fake}),
            mock.patch.object(verify.os, "O_NOFOLLOW", 0, create=True),
            mock.patch.object(verify.os, "open", return_value=77) as opened,
            mock.patch.object(
                verify.os, "fstat", return_value=types.SimpleNamespace(st_mode=0o100600)
            ),
            mock.patch.object(verify.os, "close") as closed,
            self.assertRaises(BlockingIOError),
            verify.gpu_lock(directory, GPU.upper()),
        ):
            self.fail("contended lock must not enter")
        self.assertEqual(opened.call_args.args[0].name, GPU + ".lock")
        fake.flock.assert_called_once_with(77, 6)
        closed.assert_called_once_with(77)

    def test_private_exact_copies_clean_environment_and_fixed_interpreter(self):
        def inspect(command, cwd, environment):
            inputs = Path(command[-1])
            self.assertEqual(command[:3], [sys.executable, "-I", "-B"])
            self.assertEqual((inputs / "subject.py").read_bytes(), b"reviewed source\n")
            self.assertEqual(
                (inputs / "test_subject.py").read_bytes(), b"reviewed test\n"
            )
            self.assertEqual(environment["CUDA_VISIBLE_DEVICES"], GPU)
            self.assertNotIn("SECRET_TOKEN", environment)
            self.assertNotIn("LD_PRELOAD", environment)
            self.assertNotIn("PYTHONPATH", environment)
            self.assertEqual(environment["HOME"], str(cwd))
            return arm_result()

        with (
            mock.patch.dict(os.environ, {"SECRET_TOKEN": "do-not-inherit"}),
            mock.patch.object(verify.os, "geteuid", return_value=1000, create=True),
            mock.patch.object(verify, "run_process", side_effect=inspect),
        ):
            verify.run_arm(b"reviewed source\n", b"reviewed test\n", GPU)


class HarnessTests(unittest.TestCase):
    def fake_torch(self, uuid=GPU, count=1):
        cuda = types.SimpleNamespace(
            device_count=mock.Mock(return_value=count),
            get_device_properties=mock.Mock(
                return_value=types.SimpleNamespace(uuid=uuid)
            ),
            set_device=mock.Mock(),
            set_per_process_memory_fraction=mock.Mock(),
            synchronize=mock.Mock(),
        )
        return types.SimpleNamespace(cuda=cuda, set_num_threads=mock.Mock())

    def test_mapping_rejected_before_test_import(self):
        for torch in (self.fake_torch(uuid="GPU-wrong"), self.fake_torch(count=2)):
            with (
                mock.patch.dict(sys.modules, {"torch": torch}),
                mock.patch.object(sys, "argv", ["harness", GPU, "/input"]),
                mock.patch.object(unittest.defaultTestLoader, "discover") as discover,
            ):
                with self.assertRaises(RuntimeError):
                    exec(verify.HARNESS, {})  # noqa: S102 - Execute only our constant harness with mocked Torch.
                discover.assert_not_called()
                torch.cuda.set_per_process_memory_fraction.assert_not_called()

    def test_allocator_cap_precedes_discovery_and_counts_are_reported(self):
        torch = self.fake_torch()
        result = types.SimpleNamespace(
            testsRun=2, skipped=[], failures=[], errors=[], wasSuccessful=lambda: True
        )

        def discovery(*args, **kwargs):
            torch.cuda.set_per_process_memory_fraction.assert_called_once_with(0.25, 0)
            return unittest.TestSuite()

        output = io.StringIO()
        with (
            mock.patch.dict(sys.modules, {"torch": torch}),
            mock.patch.object(sys, "argv", ["harness", GPU, "/input"]),
            mock.patch.object(sys, "path", sys.path.copy()),
            mock.patch.object(sys, "stdout", output),
            mock.patch.object(
                unittest.defaultTestLoader, "discover", side_effect=discovery
            ),
            mock.patch.object(unittest.TextTestRunner, "run", return_value=result),
            self.assertRaises(SystemExit) as stopped,
        ):
            exec(verify.HARNESS, {})  # noqa: S102 - Execute only our constant harness with mocked Torch.
        self.assertEqual(stopped.exception.code, 0)
        self.assertEqual(
            json.loads(output.getvalue().split(verify.MARKER)[1])["tests_run"], 2
        )


class SequenceTests(unittest.TestCase):
    def execute(self, arm, inventory=None):
        args = types.SimpleNamespace(
            gpu_uuid=GPU,
            lock_dir="unused",
            reviewed_sha256="unused",
            baseline="before.py",
            candidate="after.py",
            test="test.py",
        )
        with (
            mock.patch.object(sys, "platform", "linux"),
            mock.patch.object(
                verify,
                "reviewed_inputs",
                return_value=(
                    {"baseline": b"before", "candidate": b"after", "test": b"same"},
                    {},
                ),
            ),
            mock.patch.object(verify, "gpu_lock", return_value=nullcontext()),
            mock.patch.object(
                verify, "idle_samples", side_effect=inventory or [[], [], []]
            ) as idle,
            mock.patch.object(verify, "run_arm", side_effect=arm) as run,
        ):
            report = verify.verify(args)
        return report, run, idle

    def test_fresh_arms_same_test_and_post_checks(self):
        report, run, idle = self.execute([arm_result(), arm_result(exit_code=0)])
        self.assertTrue(report["matched_test_count"])
        self.assertFalse(report["qualified"])
        self.assertEqual(
            run.call_args_list,
            [mock.call(b"before", b"same", GPU), mock.call(b"after", b"same", GPU)],
        )
        self.assertEqual(idle.call_count, 3)

    def test_uncertain_before_never_launches_candidate(self):
        for changed in (
            {"timed_out": True},
            {"cleanup": False},
            {"tests": None},
            {"truncated": {"stdout": False, "stderr": True}},
            {"exit_code": -9},
            {"tests": {**arm_result()["tests"], "tests_run": 1}},
            {"tests": {**arm_result()["tests"], "skipped": 1}},
            {"tests": {**arm_result()["tests"], "uuid": "GPU-wrong"}},
        ):
            with self.subTest(changed=changed):
                report, run, _ = self.execute([arm_result(**changed)])
                self.assertEqual(run.call_count, 1)
                self.assertIn("stopped", report)
        report, run, _ = self.execute(
            [arm_result()], [[], RuntimeError("GPU still busy")]
        )
        self.assertEqual(run.call_count, 1)
        self.assertIn("post-run", report["stopped"])


if __name__ == "__main__":
    unittest.main()
