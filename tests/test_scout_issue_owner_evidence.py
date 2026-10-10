"""Discussion ownership hints are not PR records or suppression decisions."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout as scout
import kimi_scout_delivery as delivery
import kimi_scout_research as research
import scout_publication_context as memory


class IssueOwnerEvidenceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.repo = "public/project"
        self.source = {
            "url": f"https://raw.githubusercontent.com/{self.repo}/{'a' * 40}/src/subject.py",
            "text": "1: def subject(): pass",
        }
        self.path = self.root / "owner-source-notes.json"

    def note(self, url, **changes):
        return {
            "repo": self.repo,
            "prior_hypothesis": "subject has an existing contributor",
            "source_url": self.source["url"],
            "reason": "The linked discussion has an author investigating this path",
            "reopen_when": "Recheck the author or a distinct uncovered failure",
            "evidence_url": url,
            **changes,
        }

    def read(self, url, **changes):
        self.path.write_text(json.dumps([self.note(url, **changes)]), encoding="utf-8")
        return memory.owner_deferral_context(self.root, self.repo, [self.source])

    def test_same_repo_issue_or_pr_is_read_only_advice(self):
        for kind in ("issues", "pull"):
            with self.subTest(kind=kind):
                url = f"https://github.com/{self.repo}/{kind}/1402"
                result = self.read(url)
                self.assertIsNotNone(result)
                self.assertEqual(result["items"][0]["evidence_url"], url)
                self.assertIn("Never reject", result["caution"])
                self.assertIn("current", result["caution"])
                self.assertFalse((self.root / "delivery").exists())
                self.assertEqual(json.loads(self.path.read_text()), [self.note(url)])

    def test_issue_hint_still_requires_same_pinned_source_and_public_exact_url(self):
        good = f"https://github.com/{self.repo}/issues/1402"
        for url, changes in (
            ("https://github.com/other/project/issues/1402", {}),
            (good + "?token=private", {}),
            (good + "#issuecomment-123", {}),
            (good + "/", {}),
            (good.replace("1402", "0"), {}),
            (good.replace("github.com", "github.com.evil.test"), {}),
            (good.replace("https:", "http:"), {}),
            (good, {"source_url": self.source["url"].replace("a" * 40, "main")}),
            (
                good,
                {"source_url": self.source["url"].replace("subject.py", "other.py")},
            ),
            (good, {"reason": "Read D:/private/state.json"}),
        ):
            with self.subTest(url=url, changes=changes):
                self.assertIsNone(self.read(url, **changes))

    def test_issue_is_neither_a_publication_nor_owner_parking_authority(self):
        url = f"https://github.com/{self.repo}/issues/1402"
        (self.root / "owner-publication-notes.json").write_text(
            json.dumps(
                [
                    {
                        "repo": self.repo,
                        "prior_hypothesis": "subject",
                        "source_url": self.source["url"],
                        "pr_url": url,
                    }
                ]
            ),
            encoding="utf-8",
        )
        self.assertIsNone(
            memory.publication_context(self.root, self.repo, [self.source])
        )
        with self.assertRaisesRegex(ValueError, "commit-pinned"):
            delivery.park_owner_candidate(
                self.root, "b" * 24, "Existing discussion", url, "Recheck discussion"
            )
        self.assertFalse((self.root / "delivery").exists())

    def test_emitter_keeps_new_work_and_primary_source_with_issue_hint(self):
        url = f"https://github.com/{self.repo}/issues/1402"
        self.read(url)
        scout.initialize(self.root)
        spec = {"repo": self.repo, "question": "test", "source_prefixes": ["src/"]}
        config = self.root / "config.json"
        config.write_text(
            json.dumps(
                {
                    "objective": "test",
                    "queue_target": 8,
                    "source_windows": 2,
                    "repos": [spec],
                }
            ),
            encoding="utf-8",
        )
        producer = research.ResearchProducer(self.root, config, context=object())
        self.assertTrue(producer.emit("first", spec, [self.source], "source_audit"))
        with scout.connect(self.root) as db:
            row = db.execute("SELECT state,packet FROM jobs").fetchone()
        packet = json.loads(row["packet"])
        self.assertEqual(row["state"], "PENDING")
        self.assertEqual(packet["sources"], [self.source])
        self.assertEqual(packet["owner_deferrals"]["items"][0]["evidence_url"], url)
        self.assertNotIn("owner_publications", packet)
        self.assertFalse((self.root / "delivery").exists())


if __name__ == "__main__":
    unittest.main()
