"""The everyday kernel interface works without a Scout checkout or service."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class KernelCoreIndependenceTests(unittest.TestCase):
    def test_core_commands_in_a_scout_free_directory(self):
        with tempfile.TemporaryDirectory(prefix="kernel-core-only-") as directory:
            root = Path(directory)
            scripts = root / "scripts"
            scripts.mkdir()
            for name in ("kernel_opt.py", "worklog.py", "knowledge_notes.py", "hardware_profile.py"):
                (scripts / name).write_bytes((ROOT / "scripts" / name).read_bytes())
            lessons = root / "knowledge" / "lessons"
            lessons.mkdir(parents=True)
            card = ROOT / "knowledge" / "lessons" / "normalized-containment-versus-lexical-traversal.json"
            (lessons / card.name).write_bytes(card.read_bytes())
            env = dict(os.environ, PYTHONPATH="", PYTHONDONTWRITEBYTECODE="1")

            def invoke(*args):
                result = subprocess.run(
                    [sys.executable, "-I", "-B", str(scripts / "kernel_opt.py"), *args],
                    cwd=root, env=env, capture_output=True, text=True,
                    encoding="utf-8", timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                return result.stdout

            for command in ("worklog", "knowledge", "hardware-profile"):
                with self.subTest(command=command):
                    self.assertIn("usage:", invoke(command, "--help"))
            run = root / "private-run"
            invoke("worklog", "init", "--run", str(run), "--objective", "Check a kernel hypothesis")
            state = json.loads(invoke("worklog", "status", "--run", str(run)))
            self.assertEqual(state["status"], "OPEN")
            self.assertEqual(state["objective"], "Check a kernel hypothesis")
            checked = json.loads(invoke("knowledge", "check"))
            self.assertEqual(checked["count"], 1)
            found = json.loads(invoke("knowledge", "search", "lexical ancestor traversal"))
            self.assertIn("normalized-containment-versus-lexical-traversal", json.dumps(found))
            self.assertEqual(
                sorted(path.name for path in scripts.iterdir()),
                ["hardware_profile.py", "kernel_opt.py", "knowledge_notes.py", "worklog.py"],
            )


if __name__ == "__main__":
    unittest.main()
