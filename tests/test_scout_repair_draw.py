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
        result = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True)
        if result.returncode:
            self.fail(f"Git fixture {args!r} failed: {result.stderr.decode(errors='replace')}")
        return result.stdout.decode().strip()

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

    def merged_fix(self, title="Fix side-branch input"):
        original = self.git("branch", "--show-current")
        self.git("checkout", "-qb", "repair-side")
        fix = self.change(title)
        self.git("checkout", "-q", original)
        (self.root / "README").write_text("Maintenance only\n")
        self.commit("Update README")
        self.git("merge", "--no-ff", "-qm", "Merge branch 'repair-side'", "repair-side")
        return fix

    def test_reachable_opt_in_sees_merged_side_fix_without_enrolling_merge(self):
        fix = self.merged_fix()
        default = self.inspect()
        self.assertEqual(default["history_scope"], "first-parent")
        self.assertIsNone(default["selected"])
        result = self.inspect(history_scope="reachable")
        self.assertEqual(result["history_scope"], "reachable")
        self.assertEqual(result["selected"]["commit"], fix)
        self.assertNotEqual(result["selected"]["commit"], result["head"])
        self.assertTrue(all(len(row["parents"]) <= 1 for row in result["scanned"]))
        self.assertEqual(result["selected"]["parent"], self.git("rev-parse", fix + "^"))
        self.assertFalse(result["source_semantics_shown"])

    def test_reachable_still_excludes_security_and_preserves_empty_draw(self):
        self.merged_fix("Fix security boundary")
        result = self.inspect(history_scope="reachable")
        self.assertIsNone(result["selected"])
        self.assertTrue(any(row.get("excluded") == "SECURITY_TITLE" for row in result["scanned"]))
        self.assertFalse(result["replacement_on_failure"])

    def test_reachable_does_not_look_outside_pinned_ancestor(self):
        before = self.git("rev-parse", "HEAD")
        self.merged_fix()
        result = draw(self.root, before, production_prefixes=["src/"],
                      test_prefixes=["tests/"], history_scope="reachable")
        self.assertEqual(result["head"], before)
        self.assertIsNone(result["selected"])
        self.assertEqual(result["frame_count"], 1)

    def test_reachable_cap_counts_commits_not_eligible_repairs(self):
        self.merged_fix()
        self.change("Refactor most recent input")
        result = self.inspect(count=1, history_scope="reachable")
        self.assertIsNone(result["selected"])
        self.assertEqual(result["frame_count"], 1)

    def test_cli_preserves_explicit_history_scope(self):
        self.merged_fix()
        import sys
        command = [sys.executable, "-B", str(Path(__file__).resolve().parents[1] / "scripts/scout_repair_draw.py"),
                   "--repo", str(self.root), "--production-prefix", "src/", "--test-prefix", "tests/",
                   "--history-scope", "reachable"]
        result = json.loads(subprocess.check_output(command))
        self.assertEqual(result["history_scope"], "reachable")
        self.assertIsNotNone(result["selected"])

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
                       {"max_production_lines": False}, {"history_scope": "all"},
                       {"history_scope": None}):
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

    def go_change(self, paths, title="Fix ordinary Go input"):
        for name in paths:
            path = self.root / name
            path.parent.mkdir(exist_ok=True, parents=True)
            path.write_bytes(b"package sample\nvar Value = 1\n")
        return self.commit(title)

    def test_go_opt_in_classifies_colocated_tests_by_suffix(self):
        fix = self.go_change(["src/a.go", "src/a_test.go"])
        self.assertIsNone(self.inspect()["selected"])
        result = draw(self.root, "HEAD", production_prefixes=["src/"],
                      test_prefixes=["src/"], language="go")
        self.assertEqual("go", result["language"])
        self.assertEqual(fix, result["selected"]["commit"])
        self.assertEqual(["src/a.go"], result["selected"]["production_paths"])
        self.assertEqual(["src/a_test.go"], result["selected"]["test_paths"])
        self.assertEqual(2, result["selected"]["changed_production_lines"])

    def test_go_explicit_root_scope_and_normal_filename_not_test_prefix(self):
        fix = self.go_change(["retry.go", "retry_test.go", "test_helper.go", "sub/b_test.go"])
        result = draw(self.root, "HEAD", production_prefixes=["./"],
                      test_prefixes=["./"], language="go")
        self.assertEqual(fix, result["selected"]["commit"])
        self.assertEqual(["retry.go", "test_helper.go"], result["selected"]["production_paths"])
        self.assertEqual(["retry_test.go", "sub/b_test.go"], result["selected"]["test_paths"])
        with self.assertRaises(ValueError):
            draw(self.root, "HEAD", production_prefixes=["./"], test_prefixes=["tests/"])

    def test_go_prefixes_do_not_admit_foreign_tests_or_python_repairs(self):
        self.go_change(["src/a.go", "other/a_test.go"])
        self.change("Fix Python-only input")
        result = draw(self.root, "HEAD", production_prefixes=["src/"],
                      test_prefixes=["tests/"], language="go")
        self.assertIsNone(result["selected"])

    def test_go_test_only_change_is_not_production_repair(self):
        self.go_change(["src/a_test.go"])
        result = draw(self.root, "HEAD", production_prefixes=["./"],
                      test_prefixes=["./"], language="go")
        self.assertIsNone(result["selected"])
        self.assertFalse(result["replacement_on_failure"])

    def test_go_retains_frame_bounds_and_security_exclusion(self):
        fix = self.go_change(["src/a.go", "src/a_test.go"])
        self.go_change(["src/b.go", "src/b_test.go"], "Fix security input")
        options = dict(production_prefixes=["./"], test_prefixes=["./"], language="go")
        self.assertIsNone(draw(self.root, "HEAD", count=1, **options)["selected"])
        self.assertIsNone(draw(self.root, "HEAD", max_production_lines=1, **options)["selected"])
        result = draw(self.root, "HEAD", **options)
        self.assertEqual(fix, result["selected"]["commit"])
        self.assertEqual("SECURITY_TITLE", result["scanned"][0]["excluded"])

    def test_go_cli_declares_language_and_root_scope(self):
        self.go_change(["retry.go", "retry_test.go"])
        import sys
        command = [sys.executable, "-B", str(Path(__file__).resolve().parents[1] / "scripts/scout_repair_draw.py"),
                   "--repo", str(self.root), "--production-prefix", "./", "--test-prefix", "./",
                   "--language", "go"]
        result = json.loads(subprocess.check_output(command))
        self.assertEqual("go", result["language"])
        self.assertIsNotNone(result["selected"])

    def test_go_still_rejects_unsafe_prefixes_and_unknown_language(self):
        for prefix in ("../", "src/../", "./src/", "/", "src\\", ""):
            with self.subTest(prefix=prefix), self.assertRaises(ValueError):
                draw(self.root, "HEAD", production_prefixes=[prefix], test_prefixes=["./"], language="go")
        for language in (None, "rust", "Go"):
            with self.subTest(language=language), self.assertRaises(ValueError):
                self.inspect(language=language)


if __name__ == "__main__":
    unittest.main()
