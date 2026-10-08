"""One public PR can cover multiple files without becoming a quality verdict."""

import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import scout_publication_context as memory


class MultifilePublicationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = "public/project"
        self.url = f"https://github.com/{self.repo}/pull/1"
        self.notes = self.root / "owner-publication-notes.json"

    def source(self, name):
        return {
            "url": f"https://raw.githubusercontent.com/{self.repo}/{'a' * 40}/src/{name}.ts"
        }

    def note(self, name, number=1):
        return {
            "repo": self.repo,
            "prior_hypothesis": f"Recorded scope {name}",
            "source_url": self.source(name)["url"],
            "pr_url": f"https://github.com/{self.repo}/pull/{number}",
        }

    def read(self, name):
        return memory.publication_context(self.root, self.repo, [self.source(name)])

    def test_owner_notes_preserve_two_files_and_newest_summary(self):
        self.notes.write_text(json.dumps([self.note("connection"), self.note("index")]))
        before = self.notes.read_bytes()
        item = self.read("connection")["items"][0]
        self.assertEqual(item["source_paths"], ["src/connection.ts", "src/index.ts"])
        self.assertEqual(item["prior_hypothesis"], "Recorded scope index")
        self.assertEqual(self.notes.read_bytes(), before)
        self.assertIn("Never reject", self.read("index")["caution"])

    def test_owner_and_delivery_duplicate_merge_paths_not_private_logs(self):
        self.notes.write_text(json.dumps([self.note("index")]))
        path = self.root / "delivery/delivery.sqlite"
        path.parent.mkdir()
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(
                "CREATE TABLE delivery(id,repo,title,state,updated_at,result,payload)"
            )
            db.execute(
                "INSERT INTO delivery VALUES(?,?,?,?,?,?,?)",
                (
                    1,
                    self.repo,
                    "older queue summary",
                    "PR_OPEN",
                    1,
                    json.dumps({"pr": {"url": self.url}, "private_log": "not public"}),
                    json.dumps({"packet": {"sources": [self.source("connection")]}}),
                ),
            )
        before = path.read_bytes()
        result = self.read("connection")
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(
            result["items"][0]["source_paths"], ["src/connection.ts", "src/index.ts"]
        )
        self.assertEqual(result["items"][0]["prior_hypothesis"], "Recorded scope index")
        self.assertNotIn("private_log", json.dumps(result))
        self.assertEqual(path.read_bytes(), before)

    def test_late_path_matches_before_display_cap_and_other_repositories(self):
        notes = [
            self.note("z-wanted"),
            self.note("b"),
            self.note("a"),
            self.note("other", 2),
        ]
        foreign = {**self.note("foreign"), "repo": "other/project"}
        self.notes.write_text(json.dumps(notes + [foreign]))
        result = self.read("z-wanted")
        self.assertEqual(result["items"][0]["url"], self.url)
        self.assertEqual(result["items"][0]["source_paths"], ["src/a.ts", "src/b.ts"])
        self.assertEqual(len(result["items"]), 2)
        self.assertNotIn("quality", result["items"][0])

    def test_recent_distinct_pr_cap_still_merges_older_paths(self):
        notes = [self.note("older-covered", 26)]
        notes += [self.note(f"p{number}", number) for number in range(1, 27)]
        self.notes.write_text(json.dumps(notes), encoding="utf-8")
        before = self.notes.read_bytes()
        rows = memory.owner_publication_rows(self.root, self.repo)
        self.assertEqual(len(rows), 24)
        self.assertEqual(
            [
                json.loads(result)["pr"]["url"].rsplit("/", 1)[1]
                for _, result, _ in rows
            ],
            [str(number) for number in range(26, 2, -1)],
        )
        context = self.read("older-covered")
        self.assertEqual(len(context["items"]), 3)
        self.assertEqual(
            context["items"][0]["source_paths"], ["src/older-covered.ts", "src/p26.ts"]
        )
        self.assertEqual(self.notes.read_bytes(), before)

    def test_invalid_and_foreign_notes_cannot_evict_valid_prs(self):
        notes = [self.note("wanted")]
        notes += [
            {**self.note("invalid", number), "source_url": None}
            for number in range(2, 32)
        ]
        notes += [
            {**self.note("foreign", number), "repo": "other/project"}
            for number in range(32, 62)
        ]
        self.notes.write_text(json.dumps(notes), encoding="utf-8")
        self.assertEqual(len(memory.owner_publication_rows(self.root, self.repo)), 1)
        self.assertEqual(self.read("wanted")["items"][0]["url"], self.url)

    def test_duplicate_file_uses_newest_source_commit(self):
        old = self.note("same")
        new = {
            **old,
            "source_url": old["source_url"].replace("a" * 40, "b" * 40),
            "prior_hypothesis": "newest source summary",
        }
        self.notes.write_text(json.dumps([old, new]), encoding="utf-8")
        rows = memory.owner_publication_rows(self.root, self.repo)
        self.assertEqual(len(rows), 1)
        sources = json.loads(rows[0][2])["packet"]["sources"]
        self.assertEqual(sources, [{"url": new["source_url"]}])
        self.assertEqual(rows[0][0], new["prior_hypothesis"])


if __name__ == "__main__":
    unittest.main()
