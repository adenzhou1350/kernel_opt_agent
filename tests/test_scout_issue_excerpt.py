"""Literal issue ends survive both ingestion paths and emitted-packet budgets."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout as scout
import kimi_scout_context as context
import kimi_scout_research as research
from scout_issue_excerpt import OMISSION, issue_evidence, issue_text_excerpt
from tests.test_kimi_scout_research import Context

REPO = "owner/project"
API = f"https://api.github.com/repos/{REPO}"
OWNER_TEXT = "I can submit a PR with the fix and regression tests."


class IssueExcerptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.body = "Failure reproduction\n" + "x" * 7000 + "\n" + OWNER_TEXT

    def producer(self, root, ctx=None):
        scout.initialize(root)
        config = root / "config.json"
        config.write_text(json.dumps({"objective": "Offline context check", "queue_target": 4,
                          "repos": [{"repo": REPO, "source_prefixes": ["src/"], "question": "Check boundary"}]}), encoding="utf-8")
        producer = research.ResearchProducer(root, config, context=ctx or Context())
        producer.lessons = []
        return producer

    def test_short_text_is_unchanged_and_claims_are_not_classified(self):
        text = "I do not plan to submit a PR."
        result = issue_evidence("https://github.com/owner/project/issues/1", "Report", text)
        self.assertEqual(result["text"], "Report\n" + text)
        self.assertFalse(result["truncated"])
        self.assertEqual(set(result), {"url", "text", "truncated", "issue_excerpt"})
        self.assertTrue(issue_evidence(result["url"], "Report", text, already_truncated=True)["truncated"])

    def test_long_unicode_text_keeps_both_ends_within_same_character_limit(self):
        text = "HEAD" + "界" * 8000 + OWNER_TEXT
        result = issue_text_excerpt(text, 5000)
        self.assertEqual(len(result), 5000)
        self.assertTrue(result.startswith("HEAD"))
        self.assertTrue(result.endswith(OWNER_TEXT))
        self.assertIn(OMISSION, result)
        for limit in (True, 0, 127, "5000"):
            with self.assertRaises(ValueError):
                issue_text_excerpt(text, limit)

    def test_page_and_full_issue_ingestion_keep_literal_tail_without_extra_fetch(self):
        item = {"number": 1, "title": "Report", "body": self.body, "comments": 0}
        calls = []
        def fetch(url, **kwargs):
            calls.append(url)
            if url == API:
                return json.dumps({"private": False, "visibility": "public", "full_name": REPO})
            if "/issues?" in url:
                return json.dumps([item])
            if url == API + "/issues/1":
                return json.dumps(item)
            raise AssertionError(url)
        ctx = context.PublicContext(self.root / "context")
        with patch.object(context.scout, "fetch", side_effect=fetch):
            page = ctx.issue_page(REPO)
            source = ctx.issue_sources(REPO, 1)[0]
        self.assertTrue(page[0]["body"].endswith(OWNER_TEXT))
        self.assertTrue(page[0]["truncated"])
        self.assertTrue(source["text"].endswith(OWNER_TEXT))
        self.assertTrue(source["truncated"])
        self.assertEqual(len(calls), 3)  # One visibility check, one page, one issue.

    def test_initial_issue_packet_preserves_page_truncation_and_tail(self):
        ctx = Context()
        ctx.issue_page = lambda *a: [{"number": 1, "title": "Report", "body": issue_text_excerpt(self.body, 5000),
                                    "truncated": True, "html_url": f"https://github.com/{REPO}/issues/1"}]
        producer = self.producer(self.root / "queue", ctx)
        with patch.object(research, "lesson_suggestions", return_value={"status": "NO_MATCH"}, create=True):
            self.assertTrue(producer.issue(producer.config["repos"][0], {}))
        with scout.connect(producer.root) as db:
            packet = json.loads(db.execute("SELECT packet FROM jobs").fetchone()[0])
        self.assertTrue(packet["sources"][0]["text"].endswith(OWNER_TEXT))
        self.assertTrue(packet["sources"][0]["truncated"])

    def test_actual_packet_budget_shrink_keeps_issue_tail_and_partial_marker(self):
        source = issue_evidence(f"https://github.com/{REPO}/issues/1", "Report", self.body)
        first = self.producer(self.root / "first")
        advice = patch.object(research, "lesson_suggestions", return_value={"status": "NO_MATCH"}, create=True)
        with advice:
            self.assertTrue(first.emit("first", first.config["repos"][0], [source], "issue_triage"))
        with scout.connect(first.root) as db:
            packet = json.loads(db.execute("SELECT packet FROM jobs").fetchone()[0])
        budget = len((scout.SYSTEM + scout.dumps(packet)).encode("utf-8")) - 1800
        second = self.producer(self.root / "second")
        with patch.object(scout, "MAX_INPUT_BYTES", budget), patch.object(research, "lesson_suggestions", return_value={"status": "NO_MATCH"}, create=True):
            self.assertTrue(second.emit("second", second.config["repos"][0], [source], "issue_triage"))
        with scout.connect(second.root) as db:
            actual = json.loads(db.execute("SELECT packet FROM jobs").fetchone()[0])
        self.assertLessEqual(len((scout.SYSTEM + scout.dumps(actual)).encode("utf-8")), budget)
        self.assertTrue(actual["sources"][0]["text"].endswith(OWNER_TEXT))
        self.assertIn(OMISSION, actual["sources"][0]["text"])
        self.assertTrue(actual["sources"][0]["truncated"])


if __name__ == "__main__":
    unittest.main()
