"""Real local Git fixtures: enrollment never reads checkout state or runs code."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.scout_repair_draw import draw


@unittest.skipUnless(shutil.which("git"), "Git required")
class RepairDrawTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Fixture")
        self.git("config", "core.autocrlf", "false")
        for name in ("src/a.py", "tests/test_a.py"):
            path = self.root / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b"initial\n")
        self.commit("Initial")

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args], stderr=subprocess.DEVNULL).decode().strip()

    def commit(self, title):
        self.git("add", ".")
        self.git("commit", "-qm", title)
        return self.git("rev-parse", "HEAD")

    def change(self, title, suffix="changed\n"):
        for name in ("src/a.py", "tests/test_a.py"):
            with (self.root / name).open("a") as stream:
                stream.write(suffix)
        return self.commit(title)

    def inspect(self, **kwargs):
        return draw(self.root, "HEAD", production_prefixes=["src/"], test_prefixes=["tests/"], **kwargs)

    def test_newest_eligible_title_not_dirty_checkout_or_newest_arbitrary_change(self):
        fix = self.change("Fix edge case")
        self.change("Refactor")
        (self.root / "src/a.py").write_text("dirty dangerous proposal, not selected")
        result = self.inspect()
        self.assertEqual(result["selected"]["commit"], fix)
        self.assertEqual(result["frame_count"], 3)
        self.assertEqual(result["selected"]["production_paths"], ["src/a.py"])
        self.assertFalse(result["source_semantics_shown"])
        self.assertNotIn("dirty", json.dumps(result))

    def test_security_titled_changes_and_oversized_fixes_are_not_enrolled(self):
        fix = self.change("Correct ordinary input")
        self.change("Fix security boundary")
        self.change("Fix giant refactor", "x\n" * 200)
        result = self.inspect()
        self.assertEqual(result["selected"]["commit"], fix)
        self.assertEqual(result["scanned"][1]["excluded"], "SECURITY_TITLE")

    def test_frozen_frame_excludes_an_older_eligible_repair(self):
        self.change("Fix old input")
        self.change("Refactor recent code")
        result = self.inspect(count=1)
        self.assertIsNone(result["selected"])
        self.assertEqual(result["frame_count"], 1)
        self.assertFalse(result["replacement_on_failure"])

    def test_pinned_revision_and_parameters_survive_newer_commits(self):
        fix = self.change("Fix frozen input")
        self.change("Fix newer input")
        result = draw(self.root, fix, production_prefixes=["src/"],
                      test_prefixes=["tests/"], count=2, max_production_lines=10)
        self.assertEqual(result["head"], fix)
        self.assertEqual(result["selected"]["commit"], fix)
        self.assertEqual(result["production_prefixes"], ["src/"])
        self.assertEqual(result["test_prefixes"], ["tests/"])
        self.assertEqual(result["max_production_lines"], 10)

    def test_invalid_revisions_and_bounds_fail(self):
        for ref in (None, "", "--help", "HEAD\0other"):
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                draw(self.root, ref, production_prefixes=["src/"], test_prefixes=["tests/"])
        for bounds in ({"count": True}, {"count": 1001}, {"max_production_files": 0},
                       {"max_production_lines": False}):
            with self.subTest(bounds=bounds), self.assertRaises(ValueError):
                self.inspect(**bounds)

    def test_shallow_boundary_is_not_misreported_as_no_eligible_fix(self):
        self.change("Fix input")
        with tempfile.TemporaryDirectory() as directory:
            clone = Path(directory) / "shallow"
            subprocess.run(["git", "clone", "--depth=1", "--no-local", self.root.as_uri(), str(clone)],
                           check=True, capture_output=True)
            with self.assertRaisesRegex(ValueError, "shallow"):
                draw(clone, "HEAD", production_prefixes=["src/"], test_prefixes=["tests/"])

    def test_invalid_or_overlapping_scopes_fail_before_history_reads(self):
        for scope in ("../src/", "/src/", "src", "src\\", "src//", "src/../"):
            with self.subTest(scope=scope), self.assertRaises(ValueError):
                draw(self.root, "HEAD", production_prefixes=[scope], test_prefixes=["tests/"])
        with self.assertRaises(ValueError):
            draw(self.root, "HEAD", production_prefixes=["src/"], test_prefixes=["src/tests/"])


if __name__ == "__main__":
    unittest.main()
