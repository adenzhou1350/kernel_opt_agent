"""Fixed-revision reuse must not freeze branches or public visibility."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout_context as context

REPO = "owner/project"
COMMIT = "a" * 40
NEXT = "d" * 40
TREE = "b" * 40
BLOB = "c" * 40
API = f"https://api.github.com/repos/{REPO}"


class ImmutableSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.calls = []
        self.public = True
        self.branch = COMMIT
        self.fetch = patch.object(context.scout, "fetch", side_effect=self.read)
        self.fetch.start()
        self.addCleanup(self.fetch.stop)

    def read(self, url, **kwargs):
        self.calls.append(url)
        if url == API:
            return json.dumps({"private": not self.public,
                               "visibility": "public" if self.public else "private",
                               "full_name": REPO})
        if url.startswith(API + "/commits/"):
            ref = url.rsplit("/", 1)[1]
            return json.dumps({"sha": self.branch if ref == "main" else ref,
                               "commit": {"tree": {"sha": TREE}}})
        if url == API + f"/git/trees/{TREE}?recursive=1":
            return json.dumps({"tree": [{"type": "blob", "path": "src/test.py",
                                         "sha": BLOB, "mode": "100644"}],
                               "truncated": False})
        raise AssertionError(f"unexpected request: {url}")

    def seed(self):
        self.reader = context.PublicContext(self.root, github_auth=True)
        with patch.object(context.time, "time", return_value=1000):
            self.snapshot = self.reader.snapshot(REPO)
        self.calls.clear()

    def test_expired_fixed_revision_reuses_tree_after_visibility_recheck(self):
        self.seed()
        second = context.PublicContext(self.root, github_auth=True)
        with patch.object(context.time, "time", return_value=100_000):
            self.assertEqual(second.snapshot(REPO, COMMIT), self.snapshot)
        self.assertEqual(self.calls, [API])

    def test_branch_expiry_resolves_new_commit_not_stale_alias(self):
        self.seed()
        self.branch = NEXT
        with patch.object(context.time, "time", return_value=1901):
            current = self.reader.snapshot(REPO)
        self.assertEqual(current["commit"], NEXT)
        self.assertIn(API + "/commits/main", self.calls)

    def test_private_repository_cannot_use_expired_fixed_revision(self):
        self.seed()
        self.public = False
        second = context.PublicContext(self.root, github_auth=True)
        with (
            patch.object(context.time, "time", return_value=100_000),
            self.assertRaisesRegex(ValueError, "non-public"),
        ):
            second.snapshot(REPO, COMMIT)
        self.assertEqual(self.calls, [API])

    def test_old_cache_still_rejects_mismatched_commit(self):
        self.seed()
        path = self.reader._cache_path("snapshot", [REPO, COMMIT])
        record = json.loads(path.read_text(encoding="utf-8"))
        record["snapshot"]["commit"] = NEXT
        context.scout.write_json(path, record)
        with (
            patch.object(context.time, "time", return_value=100_000),
            self.assertRaisesRegex(ValueError, "cached revision"),
        ):
            self.reader.snapshot(REPO, COMMIT)
        self.assertEqual(self.calls, [API])

    def test_old_cache_still_validates_paths_and_blob_ids(self):
        self.seed()
        path = self.reader._cache_path("snapshot", [REPO, COMMIT])
        original = json.loads(path.read_text(encoding="utf-8"))
        for name, blob in [("../escape", BLOB), ("src/test.py", "invalid")]:
            with self.subTest(name=name, blob=blob):
                record = dict(original)
                record["snapshot"] = dict(original["snapshot"], files=[name], blobs={name: blob})
                context.scout.write_json(path, record)
                with (
                    patch.object(context.time, "time", return_value=100_000),
                    self.assertRaises(ValueError),
                ):
                    self.reader.snapshot(REPO, COMMIT)


if __name__ == "__main__":
    unittest.main()
