"""Real native Git fixtures for the read-only packet entrance; no model calls."""
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout as scout  # noqa: E402 - local script module path above
import kimi_scout_delivery_source as delivery  # noqa: E402
import qualification_source_bundle as bundle  # noqa: E402
import scout_git_source as source  # noqa: E402


class GitSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Source Test")
        self.git("config", "user.email", "source@example.invalid")
        self.git("config", "core.autocrlf", "false")
        self.git("config", "commit.gpgsign", "false")
        self.raw = b"# public fixture\nclass A:\n    @property\n    def ready(self):\n        return False\n\nclass B:\n    def ready(self):\n        return True\n"
        (self.repo / "main.py").write_bytes(self.raw)
        (self.repo / "other.go").write_bytes(b"package example\n")
        (self.repo / "empty.py").write_bytes(b"")
        (self.repo / "binary.py").write_bytes(b"\xff")
        (self.repo / "null_byte.py").write_bytes(b"x\0y")
        (self.repo / "big.py").write_bytes(b"x" * (source.MAX_BLOB_BYTES + 1))
        (self.repo / "medium.py").write_bytes(b"#" * scout.MAX_INPUT_BYTES)
        (self.repo / "sub").mkdir()
        (self.repo / "sub/nested.py").write_bytes(b"pass\n")
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        self.commit = self.git("rev-parse", "HEAD")
        self.spec = dict(name="public-fixture", repo="owner/project", commit=self.commit,
                         question="Inspect supported behavior or abstain.", files=[dict(path="main.py")])

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], text=True).strip()

    def packet(self, files=None):
        spec = copy.deepcopy(self.spec)
        if files is not None:
            spec["files"] = files
        return source.build_packet(self.repo, spec)

    def test_raw_bytes_ignore_dirty_crlf_checkout_and_use_one_batch(self):
        (self.repo / "main.py").write_bytes(b"changed\r\n")
        self.git("config", "core.autocrlf", "true")
        status = self.git("status", "--porcelain")
        calls = []
        original = subprocess.Popen

        def traced(argv, *args, **kwargs):
            calls.append(argv)
            self.assertEqual(kwargs["env"]["GIT_NO_LAZY_FETCH"], "1")
            self.assertEqual(kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")
            return original(argv, *args, **kwargs)

        with patch.object(bundle.subprocess, "Popen", side_effect=traced):
            packet = self.packet([dict(path="other.go"), dict(path="main.py")])
        self.assertEqual(sum("cat-file" in call for call in calls), 1)
        self.assertEqual(len(calls), 3)  # commit check, ls-tree, one cat-file batch
        self.assertFalse(any("show" in call or "fetch" in call for call in calls))
        self.assertTrue(packet["sources"][0]["url"].endswith("other.go"))
        actual = next(s for s in packet["sources"] if s["url"].endswith("main.py"))
        self.assertEqual(actual["text"].encode(), self.raw)
        self.assertEqual(actual["full_file_sha256"], hashlib.sha256(self.raw).hexdigest())
        self.assertEqual(actual["git_blob_sha1"], self.git("rev-parse", self.commit + ":main.py"))
        self.assertEqual(actual["supplied_ranges"], [[1, 9]])
        self.assertFalse(actual["truncated"])
        self.assertNotIn(str(self.repo), json.dumps(packet))
        self.assertEqual(self.git("status", "--porcelain"), status)

    def test_native_queue_and_delivery_accept_raw_url_without_repairs(self):
        packet = self.packet()
        url = packet["sources"][0]["url"]
        routed = delivery.candidate_code_source(packet, self.spec["repo"], dict(evidence=[dict(url=url)]))
        self.assertEqual(routed["path"], "main.py")
        self.assertEqual(routed["commit"], self.commit)
        queue = self.root / "disposable-queue"
        scout.initialize(queue)
        self.assertTrue(scout.enqueue(queue, packet))
        self.assertFalse(packet["duplicate_search_complete"])

    def test_unseen_blob_drift_is_not_a_new_paid_excerpt_but_visible_drift_is(self):
        files = [dict(path="main.py", definitions=["A.ready"])]
        first = self.packet(files)
        # Only an omitted body changes at the second exact commit.
        (self.repo / "main.py").write_bytes(self.raw + b"\n# unseen tail changed\n")
        self.git("add", "main.py")
        self.git("commit", "-qm", "unseen change")
        self.spec["commit"] = self.git("rev-parse", "HEAD")
        second = self.packet(files)
        self.assertEqual(first["sources"][0]["text"], second["sources"][0]["text"])
        self.assertNotEqual(first["sources"][0]["full_file_sha256"], second["sources"][0]["full_file_sha256"])
        self.assertNotEqual(first["sources"][0]["git_blob_sha1"], second["sources"][0]["git_blob_sha1"])
        queue = self.root / "disposable-queue"
        scout.initialize(queue)
        ident = scout.enqueue(queue, first)
        self.assertEqual(ident, scout.enqueue(queue, second))
        with scout.connect(queue) as db:
            stored = json.loads(db.execute("SELECT packet FROM jobs WHERE id=?", (ident,)).fetchone()[0])
        self.assertEqual(stored["sources"], first["sources"])
        # A changed visible assertion/return must still reach a new queue slot.
        (self.repo / "main.py").write_bytes(self.raw.replace(b"return False", b"return None"))
        self.git("add", "main.py")
        self.git("commit", "-qm", "visible change")
        self.spec["commit"] = self.git("rev-parse", "HEAD")
        self.assertNotEqual(ident, scout.enqueue(queue, self.packet(files)))

    def test_python_definition_retains_decorator_and_explicit_gaps(self):
        packet = self.packet([dict(path="main.py", definitions=["A.ready"], ranges=[dict(start=1, end=1)])])
        entry = packet["sources"][0]
        self.assertEqual(entry["supplied_ranges"], [[1, 1], [3, 5]])
        self.assertIn("3:     @property\n4:     def ready", entry["text"])
        self.assertNotIn("class B", entry["text"])
        self.assertTrue(entry["truncated"])
        # Neither input nor old failed model records are modified by preparation.
        self.assertEqual(self.spec["files"], [dict(path="main.py")])

    def test_full_range_and_empty_file_are_not_claimed_truncated(self):
        entry = self.packet([dict(path="main.py", ranges=[dict(start=1, end=9)])])["sources"][0]
        self.assertFalse(entry["truncated"])
        entry = self.packet([dict(path="empty.py")])["sources"][0]
        self.assertEqual(entry["text"], "")
        self.assertEqual(entry["supplied_ranges"], [])
        self.assertFalse(entry["truncated"])

    def test_missing_ambiguous_definition_and_invalid_ranges_reject(self):
        for fields in [dict(definitions=["ready"]), dict(definitions=["Missing.ready"]),
                       dict(definitions=["A.ready) trailing"]), dict(definitions="A.ready"),
                       dict(ranges=[dict(start=True, end=2)]), dict(ranges=[dict(start=1, end=10)]),
                       dict(ranges=[dict(start=3, end=2)]), dict(ranges=[dict(start=1, count=2)])]:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.packet([dict(path="main.py", **fields)])
        with self.assertRaisesRegex(ValueError, "Python"):
            self.packet([dict(path="other.go", definitions=["ready"])])

    def test_paths_and_source_types_reject_without_silent_selection(self):
        for path in ["../main.py", "main.py/..", ":(glob)*", "*.py", "sub", "absent.py", "main.py?x"]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.packet([dict(path=path)])
        for path, message in [("big.py", "read budget"), ("medium.py", "input budget"),
                              ("binary.py", "UTF-8"), ("null_byte.py", "NUL")]:
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, message):
                self.packet([dict(path=path)])
        for files in [[], [dict(path="main.py")] * 2, [dict(path="main.py")] * 9]:
            with self.subTest(files=files), self.assertRaises(ValueError):
                self.packet(files)

    def test_git_symlink_rejects_without_following(self):
        # Index-only mode works on Windows without symlink privileges.
        oid = self.git("rev-parse", self.commit + ":other.go")
        self.git("update-index", "--add", "--cacheinfo", f"120000,{oid},link.py")
        self.git("commit", "-qm", "link fixture")
        self.spec["commit"] = self.git("rev-parse", "HEAD")
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.packet([dict(path="link.py")])

    def test_floating_revision_and_noncommit_object_reject(self):
        for value in ["HEAD", self.commit[:8], self.git("rev-parse", "HEAD^{tree}")]:
            self.spec["commit"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.packet()

    def test_rejected_consumer_reaps_batch_reader(self):
        children = []
        original = subprocess.Popen

        def traced(argv, *args, **kwargs):
            child = original(argv, *args, **kwargs)
            if "cat-file" in argv:
                children.append(child)
            return child

        with patch.object(bundle.subprocess, "Popen", side_effect=traced):
            with self.assertRaisesRegex(ValueError, "UTF-8"):
                self.packet([dict(path="binary.py"), dict(path="main.py")])
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())
        self.assertTrue(children[0].stdout.closed)

    def test_optional_lessons_use_existing_budget_without_displacing_source(self):
        spec_before = copy.deepcopy(self.spec)
        huge_advice = dict(status="ADVISORY_MATCH", matches=["x" * scout.MAX_INPUT_BYTES])
        with patch.object(scout, "lesson_suggestions", return_value=huge_advice) as lookup:
            packet = source.build_packet(self.repo, self.spec, with_lessons=True)
        lookup.assert_called_once()
        self.assertNotIn("lesson_suggestions", packet)
        self.assertEqual(packet["sources"][0]["text"].encode(), self.raw)
        self.assertEqual(self.spec, spec_before)

    def test_cli_writes_only_fresh_output_and_no_queue(self):
        spec_path, output = self.root / "spec.json", self.root / "packet.json"
        spec_path.write_text(json.dumps(self.spec), encoding="utf-8")
        argv = ["--repo", str(self.repo), "--spec", str(spec_path), "--output", str(output)]
        self.assertEqual(source.main(argv), 0)
        self.assertEqual(json.loads(output.read_text())["commit"], self.commit)
        with self.assertRaises(FileExistsError):
            source.main(argv)
        self.assertFalse(list(self.root.rglob("*.sqlite*")))


if __name__ == "__main__":
    unittest.main()
