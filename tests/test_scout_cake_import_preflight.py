"""Preflight boundaries only; these tests do not qualify FlashInfer kernels."""

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "cake_import_preflight",
    Path(__file__).resolve().parents[1]
    / "examples/scout-native-flashinfer/check_cake_import.py",
)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions  # noqa: E402


class CakeImportPreflightTests(unittest.TestCase):
    def test_missing_source_advice_keeps_native_boundary(self):
        result = lesson_suggestions(
            "sparse checkout missing source companion shim Git tree"
        )
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        card = result["matches"][0]
        self.assertEqual(card["id"], "sparse-checkout-before-missing-source")
        self.assertLessEqual(len(json.dumps(card).encode()), MAX_CARD_BYTES)
        self.assertIn("native execution", card["avoid_when"])
        self.assertIn("module origin", card["lesson"])
        self.assertNotIn("qualified", result)

    def test_extracted_nullable_case_remains_retrievable_and_scoped(self):
        result = lesson_suggestions(
            "nullable Arrow numeric query physical buffer validity"
        )
        card = result["matches"][0]
        self.assertEqual(card["id"], "nullable-arrow-query-coordinates")
        self.assertIn("all-valid", card["avoid_when"])
        self.assertIn("logical slice", card["avoid_when"])
        self.assertIn("HTTP is mocked", card["evidence"][1]["note"])
        self.assertLessEqual(len(json.dumps(card).encode()), MAX_CARD_BYTES)

    def test_hash_checked_before_process(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "flashinfer/mla/cake_kimi_k3_mla.py"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"# synthetic source\n")
            with patch.object(probe.subprocess, "run") as run:
                with self.assertRaisesRegex(ValueError, "source hash mismatch"):
                    probe.preflight(root, "0" * 64)
                run.assert_not_called()

    def test_valid_file_and_invalid_hash_spelling(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "module.py"
            path.write_bytes(b"test")
            expected = hashlib.sha256(b"test").hexdigest()
            self.assertEqual(probe.verified_file(root, "module.py", expected)[1], path)
            with self.assertRaisesRegex(ValueError, "lowercase hex"):
                probe.verified_file(root, "module.py", expected.upper())

    def test_failure_is_not_gpu_qualification(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "flashinfer/mla/cake_kimi_k3_mla.py"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"# synthetic\n")
            expected = hashlib.sha256(path.read_bytes()).hexdigest()

            def fail(command, **kwargs):
                self.assertEqual(kwargs["env"]["CUDA_VISIBLE_DEVICES"], "-1")
                self.assertEqual(kwargs["env"]["FLASHINFER_DISABLE_JIT"], "1")
                self.assertEqual(kwargs["env"]["PYTHONPATH"], str(Path(root).resolve()))
                kwargs["stderr"].write(b"synthetic missing dependency\n")
                return probe.subprocess.CompletedProcess(command, 1)

            with patch.object(probe.subprocess, "run", side_effect=fail):
                result = probe.preflight(root, expected)
            self.assertEqual(result["status"], "IMPORT_PROCESS_FAILED")
            self.assertEqual(result["exit_code"], 1)
            self.assertIn("no kernel", result["scope"])
            self.assertIn("synthetic missing", result["stderr_tail"])

    def test_partial_pass_does_not_override_timeout(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "flashinfer/mla/cake_kimi_k3_mla.py"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"# synthetic\n")
            expected = hashlib.sha256(path.read_bytes()).hexdigest()

            def timeout(command, **kwargs):
                kwargs["stdout"].write(
                    b'CAKE_IMPORT_RESULT={"status":"CPU_IMPORT_PASS"}\n'
                )
                raise probe.subprocess.TimeoutExpired(command, 1)

            with patch.object(probe.subprocess, "run", side_effect=timeout):
                result = probe.preflight(root, expected)
            self.assertEqual(result["status"], "IMPORT_TIMEOUT")
            self.assertIsNone(result["exit_code"])

    def test_shim_requires_exact_hash_and_output_is_bounded(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "flashinfer/mla/cake_kimi_k3_mla.py"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"# synthetic\n")
            expected = hashlib.sha256(path.read_bytes()).hexdigest()
            with patch.object(probe.subprocess, "run") as run:
                with self.assertRaisesRegex(ValueError, "together"):
                    probe.preflight(root, expected, shim_source=root)
                run.assert_not_called()

            def verbose(command, **kwargs):
                kwargs["stderr"].write(b"x" * 65536)
                return probe.subprocess.CompletedProcess(command, 1)

            with patch.object(probe.subprocess, "run", side_effect=verbose):
                result = probe.preflight(root, expected)
            self.assertEqual(len(result["stderr_tail"]), 8192)
            self.assertEqual(result["status"], "IMPORT_PROCESS_FAILED")


if __name__ == "__main__":
    unittest.main()
