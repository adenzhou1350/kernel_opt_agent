"""The optional native witness must reject unsafe inputs before dependency imports."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


EXAMPLE = Path(__file__).resolve().parents[1] / "examples/native-cutedsl-truncdiv/check.py"


class NativeCuTeDSLExampleTests(unittest.TestCase):
    def invoke(self, *args, hidden=False):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        env.pop("CUDA_VISIBLE_DEVICES", None)
        if hidden:
            env["CUDA_VISIBLE_DEVICES"] = ""
        return subprocess.run([sys.executable, "-B", str(EXAMPLE), *args],
                              env=env, capture_output=True, text=True, timeout=10)

    def test_help_does_not_require_cutlass_or_torch(self):
        result = self.invoke("--help")
        self.assertEqual(result.returncode, 0)
        help_text = " ".join(result.stdout.casefold().split())
        self.assertIn("not a sandbox", help_text)
        self.assertIn("or new discovery benchmark", help_text)

    def test_visibility_is_explicit_before_source_or_dependency_loading(self):
        result = self.invoke("--reviewed-source", "not-present.py", "--sha256", "0" * 64)
        self.assertEqual(result.returncode, 2)
        self.assertIn("CUDA_VISIBLE_DEVICES='' before imports", result.stderr)
        self.assertNotIn("FileNotFoundError", result.stderr)

    def test_wrong_hash_does_not_execute_source(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "unreviewed.py"
            source.write_text("raise RuntimeError('MUST_NOT_EXECUTE')\n", encoding="utf-8")
            result = self.invoke("--reviewed-source", str(source), "--sha256", "0" * 64, hidden=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("reviewed source SHA256 mismatch", result.stderr)
        self.assertNotIn("MUST_NOT_EXECUTE", result.stderr)
        self.assertNotIn("ModuleNotFoundError", result.stderr)


if __name__ == "__main__":
    unittest.main()
