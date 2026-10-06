"""CPU-only controls, not evidence of real CUDA execution or native test quality."""

from contextlib import nullcontext
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import scout_native_gpu_run as runner

UUID = "GPU-9ae40ed5-d1bd-ec2f-4c6a-8253a6407d52"
STATE = dict(uuid=UUID, processes=[], total_mib=32000, memory_mib=1, utilization=0)


class Controls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "subject.py").write_text("VALUE = 42\n", encoding="utf-8")
        self.sha = runner.native.digest(self.root / "subject.py")
        self.options = dict(cwd=self.root, output=self.root / "output", python=sys.executable,
                            gpu_uuid=UUID, lock_dir=self.root / "locks",
                            sources=[("subject.py", self.sha)], modules=["subject"],
                            expected_tests=["tests.test_case::test_case"], pytest_args=["-q"])
        self.record = dict(uuid=UUID[4:], visible_devices=1, memory_limit_mib=4096,
                           imports={"subject": dict(path="subject.py", sha256=self.sha)})

    def test_identity_normalizes_only_prefix_case(self):
        for actual in (UUID, UUID[4:], UUID.upper()):
            self.record["uuid"] = actual
            record = runner.identity(runner.MARKER + json.dumps(self.record), UUID, 4096,
                                     ["subject"], dict(self.options["sources"]))
            self.assertEqual(record["uuid"], actual)

    def test_missing_duplicate_wrong_device_import_and_cap_rejected(self):
        good = runner.MARKER + json.dumps(self.record)
        cases = ["", good + "\n" + good, runner.MARKER + "{}", runner.MARKER + "[]"]
        for key, value in (("uuid", "0"), ("memory_limit_mib", 8192),
                           ("imports", {"subject": {"path": "../subject.py", "sha256": self.sha}}),
                           ("imports", {"subject": {"path": "subject.py", "sha256": "0" * 64}})):
            cases.append(runner.MARKER + json.dumps({**self.record, key: value}))
        for text in cases:
            with self.subTest(text=text), self.assertRaises(ValueError):
                runner.identity(text, UUID, 4096, ["subject"], dict(self.options["sources"]))

    def test_runtime_metadata_is_optional_but_not_arbitrary(self):
        torch = dict(version="2.11.0", path=str(self.root / "torch.py"), sha256=self.sha)
        self.record.update(torch_version="2.11.0", runtime=dict(torch=torch, triton=None))
        valid = runner.identity(runner.MARKER + json.dumps(self.record), UUID, 4096,
                                ["subject"], dict(self.options["sources"]))
        self.assertIsNone(valid["runtime"]["triton"])
        for absolute in ("/opt/runtime/torch/__init__.py", "C:/runtime/torch/__init__.py"):
            self.record["runtime"]["torch"] = {**torch, "path": absolute}
            runner.identity(runner.MARKER + json.dumps(self.record), UUID, 4096,
                            ["subject"], dict(self.options["sources"]))
        invalid = [None, [], {}, dict(torch=None, triton=None),
                   dict(torch={**torch, "version": "2.12.0"}, triton=None),
                   dict(torch={**torch, "path": "relative/torch.py"}, triton=None),
                   dict(torch=torch, triton={**torch, "sha256": "bad"})]
        for runtime in invalid:
            with self.subTest(runtime=runtime), self.assertRaisesRegex(ValueError, "runtime|disagree"):
                runner.identity(runner.MARKER + json.dumps({**self.record, "runtime": runtime}), UUID, 4096,
                                ["subject"], dict(self.options["sources"]))

    def test_invalid_inputs_never_lock_or_execute(self):
        for override in (dict(gpu_uuid="0"), dict(memory_mib=8192), dict(timeout=0),
                         dict(python="python"), dict(modules=[]), dict(modules=["a;code"]),
                         dict(modules=["subject", "subject"]), dict(expected_tests=[]),
                         dict(sources=[("subject.py", "0" * 64)]),
                         dict(environment={"CUDA_VISIBLE_DEVICES": "0"})):
            with self.subTest(override=override), patch.object(runner.sys, "platform", "linux"), \
                    patch.object(runner.gpu, "gpu_lock") as lock, patch.object(runner.native, "run") as child:
                with self.assertRaises(ValueError):
                    runner.run(**{**self.options, **override})
                lock.assert_not_called()
                child.assert_not_called()

    def test_windows_refused_without_wsl(self):
        with patch.object(runner.sys, "platform", "win32"), patch.object(runner.gpu, "gpu_lock") as lock:
            with self.assertRaisesRegex(ValueError, "do not start local WSL"):
                runner.run(**self.options)
            lock.assert_not_called()

    def test_existing_output_not_reused(self):
        self.options["output"].mkdir()
        with patch.object(runner.sys, "platform", "linux"), patch.object(runner.gpu, "gpu_lock") as lock:
            with self.assertRaisesRegex(ValueError, "fresh output"):
                runner.run(**self.options)
            lock.assert_not_called()

    def fake_native(self, **kwargs):
        self.assertEqual(kwargs["_gpu_uuid"], UUID)
        self.assertEqual(kwargs["format"], "pytest-junit")
        self.assertEqual(kwargs["environment"]["PYTHONPATH"], str(self.root.resolve()))
        self.assertTrue(kwargs["environment"]["TRITON_CACHE_DIR"].startswith(str(self.options["output"])))
        self.options["output"].mkdir()
        (self.options["output"] / "terminal.log").write_text(
            runner.MARKER + json.dumps(self.record), encoding="utf-8")
        return dict(status="TESTS_PASSED", issues=[], boundary="CPU control, ", summary={})

    def observed(self, samples=None):
        with patch.object(runner.sys, "platform", "linux"), \
                patch.object(runner.gpu, "gpu_lock", return_value=nullcontext()), \
                patch.object(runner.gpu, "idle_samples", side_effect=samples or [[STATE], [STATE]]), \
                patch.object(runner.native, "run", side_effect=self.fake_native):
            return runner.run(**self.options)

    def test_normal_result_keeps_native_status_and_gpu_observations(self):
        result = self.observed()
        self.assertEqual(result["status"], "TESTS_PASSED")
        self.assertEqual(result["native_status"], "TESTS_PASSED")
        self.assertEqual(result["gpu"]["identity"], self.record)
        self.assertEqual(json.loads((self.options["output"] / "result.json").read_text()), result)

    def test_postflight_inventory_failure_cannot_pass(self):
        result = self.observed([[STATE], ValueError("inventory unavailable")])
        self.assertEqual(result["status"], "INCONCLUSIVE")
        self.assertEqual(result["native_status"], "TESTS_PASSED")

    def test_new_gpu_survivor_not_killed_or_accepted(self):
        result = self.observed([[STATE], [{**STATE, "processes": [[UUID, "123", "other"]]}]])
        self.assertEqual(result["status"], "INCONCLUSIVE")
        self.assertIn("new GPU process", result["issues"][0])

    def test_shared_original_process_preserved(self):
        occupied = {**STATE, "processes": [[UUID, "123", "shared"]]}
        self.assertEqual(self.observed([[occupied], [occupied]])["status"], "TESTS_PASSED")

    def test_wrong_in_process_device_cannot_pass(self):
        self.record["uuid"] = "00000000-0000-0000-0000-000000000000"
        self.assertEqual(self.observed()["status"], "INCONCLUSIVE")

    def test_failed_launch_still_records_postflight_without_tests(self):
        with patch.object(runner.sys, "platform", "linux"), \
                patch.object(runner.gpu, "gpu_lock", return_value=nullcontext()), \
                patch.object(runner.gpu, "idle_samples", side_effect=[[STATE], [STATE]]) as sample, \
                patch.object(runner.native, "run", side_effect=OSError("launch failed")):
            result = runner.run(**self.options)
        self.assertEqual(result["status"], "INCONCLUSIVE")
        self.assertIsNone(result["summary"])
        self.assertEqual(sample.call_count, 2)
        self.assertEqual(result["gpu"]["postflight"], [STATE])

    def test_bootstrap_rejects_wrong_device_before_importing_source(self):
        # A deliberately fake Torch module exercises bootstrap order on CPU.
        (self.root / "torch.py").write_text(
            "class CUDA:\n def device_count(self): return 1\n"
            " def get_device_properties(self,n): return type('P',(),{'uuid':'wrong'})()\n"
            "cuda=CUDA()\n", encoding="utf-8")
        (self.root / "subject.py").write_text("raise RuntimeError('source executed')\n", encoding="utf-8")
        result = subprocess.run([sys.executable, "-B", "-c", runner.BOOTSTRAP, UUID, "4096", '["subject"]'],
                                cwd=self.root, capture_output=True, text=True, timeout=10,
                                env={**os.environ, "CUDA_VISIBLE_DEVICES": ""})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("UUID mismatch", result.stderr)
        self.assertNotIn("source executed", result.stderr)

    def test_bootstrap_observes_loaded_runtime_not_distribution_guess(self):
        # Fake modules prove metadata collection only, not CUDA correctness.
        (self.root / "torch.py").write_text(
            "__version__='2.11.test'\n"
            "version=type('V',(),{'cuda':'13.0'})()\n"
            "class CUDA:\n"
            " def device_count(self): return 1\n"
            " def get_device_properties(self,n): return type('P',(),"
            f"{{'uuid':{UUID!r},'total_memory':32000*1024*1024,'major':12,'minor':0,'name':'fake GPU'}})()\n"
            " def set_device(self,n): pass\n"
            " def set_per_process_memory_fraction(self,f,n): pass\n"
            " def synchronize(self): pass\n"
            "cuda=CUDA()\n", encoding="utf-8")
        (self.root / "triton.py").write_text("__version__='3.7.test'\n", encoding="utf-8")
        (self.root / "subject.py").write_text("import triton\n", encoding="utf-8")
        (self.root / "pytest.py").write_text("def main(args): return 0\n", encoding="utf-8")
        process = subprocess.run([sys.executable, "-B", "-c", runner.BOOTSTRAP, UUID, "4096", '["subject"]'],
                                 cwd=self.root, capture_output=True, text=True, timeout=10,
                                 env={**os.environ, "CUDA_VISIBLE_DEVICES": ""})
        self.assertEqual(process.returncode, 0, process.stderr)
        record = runner.identity(process.stdout, UUID, 4096, ["subject"],
                                 {"subject.py": runner.native.digest(self.root / "subject.py")})
        self.assertEqual(record["runtime"]["torch"]["version"], "2.11.test")
        self.assertEqual(record["runtime"]["triton"]["version"], "3.7.test")
        self.assertEqual(record["runtime"]["triton"]["sha256"], runner.native.digest(self.root / "triton.py"))
        self.assertEqual(Path(record["runtime"]["triton"]["path"]), (self.root / "triton.py").resolve())
        self.assertEqual(record["cuda_runtime"], "13.0")
        self.assertEqual(record["device"]["compute_capability"], [12, 0])


if __name__ == "__main__":
    unittest.main()
