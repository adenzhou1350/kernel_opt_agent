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

    def work_body(self):
        return ("Environment and observed failure\n" + "startup diagnostics\n" * 350
                + "## Minimal workaround tested locally\n```diff\n"
                + "- assert boundary <= maximum\n+ if boundary > maximum: continue\n```\n"
                + "## Additional logs\n" + "shutdown diagnostics\n" * 300 + OWNER_TEXT)

    def test_middle_workaround_is_literal_and_keeps_head_tail_and_budget(self):
        result = issue_evidence("https://github.com/owner/project/issues/1", "Report", self.work_body())
        self.assertTrue(result["text"].startswith("Report\nEnvironment"))
        self.assertTrue(result["text"].endswith(OWNER_TEXT))
        self.assertIn("## Minimal workaround tested locally", result["text"])
        self.assertIn("+ if boundary > maximum: continue", result["text"])
        self.assertEqual(len(result["text"]), 5000)
        self.assertTrue(result["truncated"])
        self.assertEqual(set(result), {"url", "text", "truncated", "issue_excerpt"})

    def test_fenced_heading_is_not_selected_instead_of_real_workaround(self):
        text = ("Environment\n" + "x" * 6500 + "\n```markdown\n## Patch\n"
                + "this is a quoted example, not the report section\n```\n"
                + "## Suggested fix\nACTUAL_SECTION\n## Logs\n" + "y" * 6500 + OWNER_TEXT)
        result = issue_text_excerpt(text, 5000)
        self.assertIn("ACTUAL_SECTION", result)
        self.assertNotIn("quoted example", result)
        self.assertTrue(result.endswith(OWNER_TEXT))

    def test_unrecognized_middle_heading_retains_existing_policy(self):
        text = "HEAD\n" + "x" * 6500 + "\n## Environment\n" + "y" * 6500 + OWNER_TEXT
        available = 5000 - len(OMISSION)
        tail = available // 3
        self.assertEqual(issue_text_excerpt(text, 5000), text[:available-tail] + OMISSION + text[-tail:])

    def test_small_budgets_and_already_visible_work_keep_existing_policy(self):
        texts = [self.work_body(), "## Proposed fix\nAlready in the prefix\n" + "x" * 8000 + OWNER_TEXT]
        for text, limit in ((texts[0], 128), (texts[0], 511), (texts[1], 5000)):
            with self.subTest(limit=limit):
                available = limit - len(OMISSION)
                tail = available // 3
                self.assertEqual(issue_text_excerpt(text, limit), text[:available-tail] + OMISSION + text[-tail:])

    def test_repeated_shrinks_remain_bounded_and_keep_untrusted_literal_work(self):
        text = self.work_body().replace("Minimal workaround tested locally", "Proposed fix (not yet tested)")
        for limit in (5000, 3750, 2200, 1000, 512):
            text = issue_text_excerpt(text, limit)
            self.assertLessEqual(len(text), limit)
            self.assertIn("Proposed fix (not yet tested)", text)
            self.assertIn("+ if boundary > maximum: continue", text)
            self.assertTrue(text.endswith(OWNER_TEXT))

    def test_workaround_survives_actual_packet_shrink_without_more_requests(self):
        self.body = self.work_body()
        self.test_actual_packet_budget_shrink_keeps_issue_tail_and_partial_marker()
        with scout.connect(self.root / "second") as db:
            packet = json.loads(db.execute("SELECT packet FROM jobs").fetchone()[0])
        self.assertIn("+ if boundary > maximum: continue", packet["sources"][0]["text"])

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

    def test_prior_citations_keep_current_complete_lines_under_same_budget(self):
        policy = "Not a correctness promise: this is a proposed progress policy."
        owned = "I have not opened a repair PR yet; this work is still preliminary."
        text = "HEAD\n" + "x"*2900 + "\n"+policy+"\n" + "y"*1000 + "\n"+owned+"\n" + "z"*900+"TAIL"
        quotes = ["this is a proposed progress policy", "I have not opened a repair PR yet"]
        self.assertTrue(all(q not in issue_text_excerpt(text, 2109) for q in quotes))
        for limit in (2109, 1581, 1000):
            text = issue_text_excerpt(text, limit, quotes=quotes)
            self.assertLessEqual(len(text), limit)
            self.assertIn(policy, text)  # The negation/qualification is not removed.
            self.assertIn(owned, text)
            self.assertTrue(text.startswith("HEAD"))
            self.assertTrue(text.endswith("TAIL"))

    def test_missing_ambiguous_and_long_line_hints_do_not_invent_source(self):
        for text, quotes in (
            (self.body, ["a deleted author statement"]),
            (self.body+"\nrepeat\nrepeat\n", ["repeat"]),
            ("HEAD\n"+"x"*4000+"target"+"y"*4000+"\nTAIL", ["target"]),
            (self.body, [OMISSION.strip()]),
        ):
            with self.subTest(quotes=quotes):
                self.assertEqual(issue_text_excerpt(text, 1000, quotes=quotes),
                                 issue_text_excerpt(text, 1000))
        with self.assertRaises(ValueError): issue_text_excerpt(self.body, 1000, quotes="target")
        with self.assertRaises(ValueError): issue_text_excerpt(self.body, 1000, quotes=["x"]*6)

    def test_emit_only_preserves_citations_verified_in_both_parent_and_current_source(self):
        quote = "Current literal policy is not a correctness guarantee."
        body = "HEAD\n" + "x"*2900 + "\n"+quote+"\n" + "y"*1000 + "\nTAIL"
        source = issue_evidence(f"https://github.com/{REPO}/issues/1", "Report", body)
        parent = dict(id="root", root="root", depth=0, sources=[source],
                      analysis=json.dumps({"title":"policy", "evidence":[
                          {"url":source["url"],"quote":quote}]}))
        for index, current in enumerate((source, {**source,"text":source["text"].replace(quote,"DELETED")}, source)):
            root = self.root / str(index)
            producer = self.producer(root)
            # Force the actual emitter to shrink this report; retain the same
            # input cap and no Context/API reads or model call.
            packet = dict(name="",repo=REPO,question="",sources=[current])
            budget = len((scout.SYSTEM+scout.dumps(packet)).encode())+100
            with patch.object(scout,"MAX_INPUT_BYTES",budget), patch.object(
                research,"lesson_suggestions",return_value={"status":"NO_MATCH"}):
                actual_parent = parent if index < 2 else {
                    **parent, "sources":[{**source,"text":"No observed citation here."}]}
                self.assertTrue(producer.emit("child",producer.config["repos"][0],
                                             [current],"source_followup",parent=actual_parent))
            with scout.connect(root) as db:
                child=json.loads(db.execute("SELECT packet FROM jobs").fetchone()[0])
            self.assertLessEqual(len((scout.SYSTEM+scout.dumps(child)).encode()),budget)
            self.assertEqual(quote in child["sources"][0]["text"], index==0)
            self.assertTrue(child["sources"][0]["truncated"])

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
            if url == API + "/issues/1/timeline?per_page=50&page=1":
                return "[]"
            raise AssertionError(url)
        ctx = context.PublicContext(self.root / "context")
        with patch.object(context.scout, "fetch", side_effect=fetch):
            page = ctx.issue_page(REPO)
            source = ctx.issue_sources(REPO, 1)[0]
        self.assertTrue(page[0]["body"].endswith(OWNER_TEXT))
        self.assertTrue(page[0]["truncated"])
        self.assertTrue(source["text"].endswith(OWNER_TEXT))
        self.assertTrue(source["truncated"])
        self.assertEqual(len(calls), 4)  # Visibility, page, issue and bounded linked-work lookup.
        self.assertEqual(sum("/timeline?" in url for url in calls), 1)

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
