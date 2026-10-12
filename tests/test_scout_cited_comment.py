"""Displayed issue comments can anchor related work, not transfer candidate focus."""
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout as scout
import kimi_scout_research as research
from scout_cited_issue import cited_issue_number
from tests.test_kimi_scout_research import Context

URL = "https://github.com/a/b/issues/42"
QUOTE = "Review the underlying transport's supported header character range."
BODY = {"url": URL, "text": "Invalid header error context"}
COMMENT = {"url": URL + "#issuecomment-2470754622", "text": QUOTE}
ANALYSIS = {"evidence": [{"url": COMMENT["url"], "quote": QUOTE}]}


class CitationTests(unittest.TestCase):
    def test_displayed_comment_requires_its_displayed_parent(self):
        self.assertEqual(cited_issue_number("a/b", [BODY, COMMENT], ANALYSIS), 42)
        self.assertIsNone(cited_issue_number("a/b", [COMMENT], ANALYSIS))
        self.assertIsNone(cited_issue_number("a/b", [BODY], ANALYSIS))
        direct = {"evidence": [{"url": URL, "quote": QUOTE}]}
        self.assertEqual(cited_issue_number("a/b", [{"url": URL, "text": QUOTE}], direct), 42)

    def test_comment_rejects_unshown_quote_url_variants_and_cross_repository(self):
        for url, quote in (
            (COMMENT["url"], "A fabricated quotation that is long enough."),
            (URL + "#issuecomment-0", QUOTE),
            (URL + "#issuecomment-1000000000000000001", QUOTE),
            (COMMENT["url"] + "?q=private", QUOTE),
            (COMMENT["url"].replace("/a/b/", "/other/repo/"), QUOTE),
            (COMMENT["url"].replace("/issues/", "/pull/"), QUOTE),
        ):
            with self.subTest(url=url, quote=quote):
                shown = {"url": url, "text": QUOTE}
                analysis = {"evidence": [{"url": url, "quote": quote}]}
                self.assertIsNone(cited_issue_number("a/b", [BODY, shown], analysis))

    def test_conflicting_displayed_parents_abstain(self):
        other_body = {"url": URL.replace("42", "43"), "text": QUOTE}
        other_comment = {"url": other_body["url"] + "#issuecomment-2", "text": QUOTE}
        analysis = {"evidence": ANALYSIS["evidence"] + [{"url": other_comment["url"], "quote": QUOTE}]}
        self.assertIsNone(cited_issue_number("a/b", [BODY, COMMENT, other_body, other_comment], analysis))

    def test_comment_and_parent_must_fit_existing_evidence_budgets(self):
        self.assertIsNone(cited_issue_number("a/b", [COMMENT] + [{}] * 24 + [BODY], ANALYSIS))
        self.assertIsNone(cited_issue_number("a/b", [BODY] + [{}] * 24 + [COMMENT], ANALYSIS))
        self.assertIsNone(cited_issue_number("a/b", [BODY, COMMENT], {
            "evidence": [{}] * 5 + ANALYSIS["evidence"],
        }))
        self.assertIsNone(cited_issue_number("a/b", [BODY | {"text": "x" * 10001}, COMMENT], ANALYSIS))

    def test_followup_query_does_not_adopt_issue_focus_or_change_lineage(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scout.initialize(root)
            spec = {"repo": "a/b", "source_prefixes": ["src/"], "question": "Check boundaries"}
            config = root / "config.json"
            config.write_text(json.dumps({"objective": "Falsifiable leads", "queue_target": 4, "repos": [spec]}))
            context = Context()
            producer = research.ResearchProducer(root, config, context=context)
            primary = context.source("a/b", "a" * 40, "src/kernel.py")
            producer.emit("source-root", spec, [primary, BODY, COMMENT], "source_audit")
            with scout.connect(root) as db:
                row = db.execute("SELECT id FROM jobs").fetchone()
                db.execute("UPDATE jobs SET state='REVIEW', result=?, finished=? WHERE id=?",
                           (json.dumps({"analysis": ANALYSIS | {"title": "Header validation context", "next_check": "src/kernel.py"}}), time.time(), row[0]))
            related = {"url": "https://github.com/a/b/pull/81", "text": "Fixes #42"}
            with (
                patch.object(context, "issue_pr_context", create=True, return_value={
                    "sources": [related], "status": "PARTIAL_SEARCH",
                    "search_exhaustive": False,
                }) as lookup,
                patch.object(context, "duplicate_sources") as titles,
                patch.object(context, "issue_sources") as refresh,
            ):
                self.assertTrue(producer.followup(spec, {}))
            lookup.assert_called_once_with("a/b", 42)
            titles.assert_not_called()
            refresh.assert_not_called()
            with scout.connect(root) as db:
                child = json.loads(db.execute("SELECT packet FROM jobs ORDER BY created DESC LIMIT 1").fetchone()[0])
            self.assertNotIn("focus_issue", child)
            self.assertEqual(child["research"]["root_job_id"], row[0])
            self.assertEqual(child["sources"][0], primary)
            self.assertIn(related, child["sources"])
            self.assertFalse(child["issue_pr_lookup"]["candidate_focus_adopted"])


if __name__ == "__main__":
    unittest.main()
