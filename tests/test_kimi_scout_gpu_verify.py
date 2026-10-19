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
            f"{GPU}, 2, 32768, 1024, 0\n",
            "GPU-ffffffff-1111-2222-3333-444444444444, 101, busy\n",
        ]
        with mock.patch.object(
            subprocess,
            "run",
            side_effect=[types.SimpleNamespace(stdout=s) for s in outputs],
        ) as call:
            result = verify.snapshot(GPU)
        self.assertEqual(result["index"], 2)
        self.assertEqual(result["total_mib"], 32768)
        self.assertEqual(result["memory_mib"], 1024)
        self.assertEqual(result["processes"], [])
        self.assertIn("--id=" + GPU, call.call_args_list[0].args[0])
        self.assertEqual(call.call_args_list[0].args[0][0], "/usr/bin/nvidia-smi")

    def test_unknown_metrics_and_uuid_mismatch_rejected(self):
        for text in (
            f"{GPU}, 0, 32768, N/A, 0\n",
            "GPU-other, 0, 32768, 0, 0\n",
        ):
            with (
                self.subTest(text=text),
                mock.patch.object(
                    subprocess, "run", return_value=types.SimpleNamespace(stdout=text)
                ),
                self.assertRaises(ValueError),
            ):
                verify.snapshot(GPU)

    def test_three_samples_allow_other_processes_but_require_bounded_headroom(self):
        idle = {
            "uuid": GPU,
            "index": 0,
            "total_mib": 8192,
            "memory_mib": 1024,
            "utilization": 35,
            "processes": [[GPU, "77", "other"]],
        }
        with (
            mock.patch.object(verify, "snapshot", return_value=idle) as probe,
            mock.patch.object(verify.time, "sleep") as sleep,
        ):
            self.assertEqual(len(verify.idle_samples(GPU)), 3)
            self.assertEqual(probe.call_count, 3)
            self.assertEqual(sleep.call_args_list, [mock.call(1), mock.call(1)])
        for change in (
            {"memory_mib": 2049},
            {"utilization": 81},
        ):
            with (
                self.subTest(change=change),
                mock.patch.object(verify, "snapshot", return_value={**idle, **change}),
                self.assertRaisesRegex(RuntimeError, "bounded headroom"),
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


class NativeGuardTests(unittest.TestCase):
    def test_device_set_keeps_mapping_order_but_locks_in_global_order(self):
        import scout_native_run
        from contextlib import contextmanager
        other = "GPU-00000000-0000-0000-0000-000000000000"
        active, entered = [], []
        @contextmanager
        def lock(_, uuid):
            entered.append(uuid)
            active.append(uuid)
            try:
                yield
            finally:
                active.remove(uuid)
        def capture(**options):
            self.assertEqual(active, [other, GPU])
            self.assertEqual(options["_gpu_uuid"], GPU + "," + other)
            guard = options["_execution_guard"]
            def sample(uuid):
                return {**self.sample(), "uuid": uuid}
            with (mock.patch.object(verify, "snapshot", side_effect=sample),
                  mock.patch.object(verify.time, "sleep")):
                self.assertIsNone(guard("admission"))
                self.assertIsNone(guard("postflight"))
            self.assertEqual(list(guard.evidence["devices"]), [GPU, other])
            for observation in guard.evidence["devices"].values():
                self.assertEqual(len(observation["preflight"]), 3)
                self.assertIsNotNone(observation["postflight"])
            return {"status": "TESTS_PASSED"}
        with (mock.patch.object(sys, "platform", "linux"),
              mock.patch.object(verify, "gpu_lock", side_effect=lock),
              mock.patch.object(scout_native_run, "run", side_effect=capture)):
            verify.run_native(gpu_uuids=[GPU, other], format="pytest-junit")
        self.assertEqual(entered, [other, GPU])
        self.assertEqual(active, [])

    def test_partial_set_contention_releases_locks_without_probe_or_launch(self):
        import scout_native_run
        from contextlib import contextmanager
        other = "GPU-ffffffff-ffff-ffff-ffff-ffffffffffff"
        active = []
        @contextmanager
        def lock(_, uuid):
            if uuid == other:
                raise BlockingIOError("busy")
            active.append(uuid)
            try:
                yield
            finally:
                active.remove(uuid)
        with (mock.patch.object(sys, "platform", "linux"),
              mock.patch.object(verify, "gpu_lock", side_effect=lock),
              mock.patch.object(verify, "snapshot") as probe,
              mock.patch.object(scout_native_run, "run") as run):
            for devices in ([], [GPU, GPU.upper()], [GPU]*9,
                            [GPU, "0"], [None], "not-a-device-list"):
                with self.subTest(devices=devices), self.assertRaises(ValueError):
                    verify.run_native(gpu_uuids=devices, format="pytest-junit")
            with self.assertRaises(ValueError):
                verify.run_native(gpu_uuid=GPU, gpu_uuids=[other], format="pytest-junit")
            with self.assertRaises(BlockingIOError):
                verify.run_native(gpu_uuids=[other, GPU], format="pytest-junit")
            self.assertEqual(active, [])
            probe.assert_not_called()
            run.assert_not_called()

    def test_group_guard_rejects_one_device_but_observes_all_postflights(self):
        other = "GPU-00000000-0000-0000-0000-000000000000"
        guard = verify.NativeGpuGroupGuard([GPU, other], 6144)
        def sample(uuid):
            return {**self.sample(), "uuid": uuid,
                    "memory_mib": 32000 if uuid == other else 0}
        with mock.patch.object(verify, "snapshot", side_effect=sample):
            self.assertIsNotNone(guard("postflight"))
        self.assertTrue(all(g.evidence["postflight"] is not None for g in guard.guards))

    def sample(self):
        return dict(uuid=GPU, index=0, total_mib=32768, memory_mib=1024,
                    utilization=0, processes=[[GPU, "123", "existing-user-task"]])

    def test_three_admission_samples_record_shared_processes_and_throttle_running(self):
        value = self.sample()
        guard = verify.NativeGpuGuard(GPU)
        with (mock.patch.object(verify, "snapshot", return_value=value) as probe,
              mock.patch.object(verify.time, "sleep") as sleep,
              mock.patch.object(verify.time, "monotonic", return_value=100)):
            self.assertIsNone(guard("admission"))
            self.assertEqual(sleep.call_count, 2)
            self.assertEqual(len(guard.evidence["preflight"]), 3)
            self.assertEqual(guard.evidence["preflight"][0]["processes"], value["processes"])
            for _ in range(100):
                self.assertIsNone(guard("running"))
            self.assertEqual(probe.call_count, 3)
            self.assertIsNone(guard("postflight"))  # Must not reuse a throttled sample.
            self.assertEqual(probe.call_count, 4)
        self.assertEqual(guard.evidence["minimum_free_mib"], 31744)

    def test_own_gpu_utilization_is_not_a_running_or_postflight_stop(self):
        guard = verify.NativeGpuGuard(GPU)
        busy = self.sample()
        busy["utilization"] = 100
        busy["processes"][0][2] = "x" * 10000
        busy["processes"] *= 100
        with (mock.patch.object(verify, "snapshot", return_value=busy),
              mock.patch.object(verify.time, "monotonic", side_effect=range(1000))):
            for _ in range(100):
                self.assertIsNone(guard("running"))
            self.assertIsNone(guard("postflight"))
        self.assertEqual(guard.evidence["running_samples"], 100)
        self.assertNotIn("running_history", guard.evidence)
        self.assertEqual(len(guard.evidence["latest_running"]["processes"]), 64)
        self.assertTrue(guard.evidence["latest_running"]["processes_truncated"])
        self.assertTrue(guard.evidence["latest_running"]["process_names_truncated"])
        self.assertEqual(len(guard.evidence["latest_running"]["processes"][0][2]), 256)
        self.assertEqual(guard.evidence["maximum_utilization"], 100)

    def test_busy_admission_and_lost_reserve_return_a_stop_reason(self):
        for phase, changes in (("admission", {"utilization": 81}),
                               ("running", {"memory_mib": 32768}),
                               ("postflight", {"memory_mib": 32768})):
            value = self.sample()
            value.update(changes)
            guard = verify.NativeGpuGuard(GPU)
            with self.subTest(phase=phase), mock.patch.object(verify, "snapshot", return_value=value):
                self.assertIsInstance(guard(phase), str)
                self.assertEqual(guard.evidence["failure"]["phase"], phase)

    def test_invalid_identity_telemetry_or_weaker_reserve_cannot_be_accepted(self):
        for field, value in (("uuid", "GPU-other"), ("total_mib", 0),
                             ("memory_mib", -1), ("memory_mib", 32769),
                             ("utilization", 101), ("total_mib", True)):
            sample = self.sample()
            sample[field] = value
            guard = verify.NativeGpuGuard(GPU)
            with self.subTest(field=field, value=value), mock.patch.object(verify, "snapshot", return_value=sample):
                with self.assertRaises(ValueError):
                    guard("postflight")
            self.assertEqual(guard.evidence["failure"]["error"], "ValueError")
        for reserve in (0, 6143, True, 8192.0):
            with self.subTest(reserve=reserve), self.assertRaises(ValueError):
                verify.NativeGpuGuard(GPU, reserve)
        guard = verify.NativeGpuGuard(GPU)
        with mock.patch.object(verify, "snapshot", side_effect=OSError("private detail")):
            with self.assertRaises(OSError):
                guard("admission")
        self.assertNotIn("private detail", json.dumps(guard.evidence))

    def test_native_wrapper_keeps_one_lock_through_postflight_and_cannot_override_guard(self):
        import scout_native_run
        active = []
        from contextlib import contextmanager
        @contextmanager
        def lock(*_):
            active.append(True)
            try:
                yield
            finally:
                active.pop()
        def capture(**options):
            self.assertEqual(active, [True])
            self.assertEqual(options["_gpu_uuid"], GPU)
            self.assertIsInstance(options["_execution_guard"], verify.NativeGpuGuard)
            with mock.patch.object(verify, "snapshot", return_value=self.sample()):
                self.assertIsNone(options["_execution_guard"]("postflight"))
            self.assertEqual(active, [True])
            return {"status": "INCONCLUSIVE"}
        with (mock.patch.object(sys, "platform", "linux"),
              mock.patch.object(verify, "gpu_lock", side_effect=lock) as locking,
              mock.patch.object(scout_native_run, "run", side_effect=capture) as run):
            self.assertEqual(verify.run_native(gpu_uuid=GPU, format="pytest-junit"),
                             {"status": "INCONCLUSIVE"})
            locking.assert_called_once()
            self.assertEqual(active, [])
            for arguments in ({"_gpu_uuid": GPU}, {"_execution_guard": object()},
                              {"format": "go-json"}, {"min_free_mib": 1}):
                options = dict(gpu_uuid=GPU, format="pytest-junit")
                options.update(arguments)
                with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                    verify.run_native(**options)
            self.assertEqual(run.call_count, 1)

    def test_contended_native_lock_does_not_probe_or_launch(self):
        import scout_native_run
        with (mock.patch.object(sys, "platform", "linux"),
              mock.patch.object(verify, "gpu_lock", side_effect=BlockingIOError("busy")),
              mock.patch.object(verify, "snapshot") as probe,
              mock.patch.object(scout_native_run, "run") as run):
            with self.assertRaises(BlockingIOError):
                verify.run_native(gpu_uuid=GPU, format="pytest-junit")
            probe.assert_not_called()
            run.assert_not_called()


class HarnessTests(unittest.TestCase):
    def fake_torch(self, uuid=GPU, count=1):
        cuda = types.SimpleNamespace(
            device_count=mock.Mock(return_value=count),
            get_device_properties=mock.Mock(
                return_value=types.SimpleNamespace(
                    uuid=uuid, total_memory=32768 * 1024 * 1024
                )
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
            torch.cuda.set_per_process_memory_fraction.assert_called_once_with(0.125, 0)
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
        clean = arm_result(
            exit_code=0,
            tests={**arm_result()["tests"], "failures": 0},
        )
        report, run, idle = self.execute([arm_result(), clean])
        self.assertTrue(report["matched_test_count"])
        self.assertTrue(report["screen_passed"])
        self.assertFalse(report["qualified"])
        self.assertEqual(
            run.call_args_list,
            [mock.call(b"before", b"same", GPU), mock.call(b"after", b"same", GPU)],
        )
        self.assertEqual(idle.call_count, 3)

    def test_matching_test_counts_do_not_hide_candidate_failures(self):
        report, _, _ = self.execute([arm_result(), arm_result(exit_code=0)])
        self.assertTrue(report["matched_test_count"])
        self.assertFalse(report["screen_passed"])
        report, _, _ = self.execute(
            [arm_result(), arm_result(tests={**arm_result()["tests"], "errors": 1})]
        )
        self.assertFalse(report["screen_passed"])

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
