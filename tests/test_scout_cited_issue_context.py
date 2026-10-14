"""One related-work query must not transfer source-chain ownership."""

import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout as scout  # noqa: E402
import kimi_scout_research as research  # noqa: E402
from scout_cited_issue import cited_issue_number, related_issue_body, requested_issue_number  # noqa: E402
from tests.test_kimi_scout_research import Context  # noqa: E402

URL = "https://github.com/a/b/issues/42"
QUOTE = "FULL graph captures unsupported prefill rows"
SOURCE = {"url": URL, "text": "Report: " + QUOTE}
ANALYSIS = {"evidence": [{"url": URL, "quote": QUOTE}]}


class CitationTests(unittest.TestCase):
    def test_explicit_body_request_must_name_an_already_displayed_issue(self):
        for request, expected in (
            ('Read #42 body', 42), (URL, 42), ('Read #43 then #42', 42),
            (URL + '#issuecomment-1', None), (URL + '?token=x', None),
            (URL.replace('a/b', 'foreign/repo'), None),
            ('#43', None), ('x' * 2000 + ' #42', None),
        ):
            with self.subTest(request=request):
                self.assertEqual(requested_issue_number('a/b', [SOURCE], {'next_check': request}), expected)
        self.assertIsNone(requested_issue_number('a/b', [SOURCE], {'title': '#42'}))
        self.assertIsNone(requested_issue_number('a/b', [{'url': URL.replace('issues', 'pull')}], {'next_check': '#42'}))

    def test_body_read_is_bounded_and_identity_checked_without_recursive_lookups(self):
        from unittest.mock import Mock
        context = Mock()
        context._public.return_value = 'a/b'
        item = {'number': 42, 'html_url': URL, 'title': 'RFC', 'body': 'a' * 7000 + 'END'}
        context._json.return_value = item
        source = related_issue_body(context, 'a/b', 42)
        context._json.assert_called_once_with('https://api.github.com/repos/a/b/issues/42')
        self.assertLessEqual(len(source['text']), 5000)
        self.assertTrue(source['text'].endswith('END'))
        self.assertTrue(source['truncated'])
        self.assertFalse(source['related_issue_expansion']['candidate_focus_adopted'])
        for mutation in ({'number': True}, {'number': 43}, {'html_url': 'https://github.com/other/repo/issues/42'}, {'pull_request': {}}, {'body': None}):
            with self.subTest(mutation=mutation):
                context._json.return_value = item | mutation
                with self.assertRaises(ValueError):
                    related_issue_body(context, 'a/b', 42)

    def test_exact_displayed_issue_quote_is_a_number_not_a_url_request(self):
        self.assertEqual(cited_issue_number("a/b", [SOURCE], ANALYSIS), 42)

    def test_unshown_invented_cross_repo_comment_or_pr_references_abstain(self):
        for url, quote in [
            (URL, "invented quote that was never displayed"),
            (URL + "#issuecomment-1", QUOTE),
            (URL.replace("a/b", "other/repo"), QUOTE),
            (URL.replace("issues", "pull"), QUOTE),
            (URL + "?q=private", QUOTE),
            (URL, "FULL"),
        ]:
            value = {"evidence": [{"url": url, "quote": quote}]}
            with self.subTest(url=url, quote=quote):
                self.assertIsNone(cited_issue_number("a/b", [SOURCE], value))
        self.assertIsNone(cited_issue_number("a/b", [], ANALYSIS))

    def test_ambiguous_references_do_not_pick_an_arbitrary_issue(self):
        source = {"url": URL.replace("42", "43"), "text": QUOTE}
        value = {"evidence": ANALYSIS["evidence"] + [source | {"quote": QUOTE}]}
        self.assertIsNone(cited_issue_number("a/b", [SOURCE, source], value))

    def test_budget_and_malformed_input_abstain(self):
        self.assertIsNone(cited_issue_number("a/b", [None], ANALYSIS))
        self.assertIsNone(cited_issue_number("a/b", [SOURCE], {"evidence": None}))
        self.assertIsNone(cited_issue_number("a/b is:private", [SOURCE], ANALYSIS))
        self.assertIsNone(
            cited_issue_number(
                "a/b", [SOURCE | {"text": "x" * 10001 + QUOTE}], ANALYSIS
            )
        )
        self.assertIsNone(
            cited_issue_number(
                "a/b", [SOURCE], {"evidence": [{}] * 5 + ANALYSIS["evidence"]}
            )
        )


class FollowupTests(unittest.TestCase):
    def test_requested_related_body_replaces_other_lookups_without_adopting_focus(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scout.initialize(root)
            config = root / 'config.json'
            spec = {'repo': 'a/b', 'source_prefixes': ['src/'], 'question': 'Check',
                    'followup_issue_body_context': True, 'followup_discussion_context': True,
                    'followup_pr_revision_context': True}
            config.write_text(json.dumps({'objective': 'Evidence', 'queue_target': 4, 'repos': [spec]}))
            context = Context()
            producer = research.ResearchProducer(root, config, context=context)
            primary = context.source('a/b', 'a' * 40, 'src/kernel.py')
            producer.emit('source-root', spec, [primary, SOURCE], 'source_audit')
            with scout.connect(root) as db:
                row = db.execute('SELECT id FROM jobs').fetchone()
                db.execute("UPDATE jobs SET state='REVIEW',result=?,finished=? WHERE id=?", (
                    json.dumps({'analysis': {'title': 'kernel boundary', 'next_check': 'Read #42 body and #81 patch'}}), time.time(), row[0]))
            item = {'number': 42, 'html_url': URL, 'title': 'Existing RFC', 'body': 'Explicit scope safety contract'}
            with (patch.object(context, '_public', create=True, return_value='a/b'),
                  patch.object(context, '_json', create=True, return_value=item) as fetch,
                  patch.object(context, 'issue_sources') as issue,
                  patch.object(context, 'duplicate_sources') as duplicate,
                  patch.object(research, 'discussion_sources') as discussions,
                  patch.object(research, 'pr_revision_sources') as revisions):
                self.assertTrue(producer.followup(spec, {}))
            fetch.assert_called_once_with('https://api.github.com/repos/a/b/issues/42')
            for lookup in (issue, duplicate, discussions, revisions):
                lookup.assert_not_called()
            with scout.connect(root) as db:
                child = json.loads(db.execute('SELECT packet FROM jobs ORDER BY created DESC LIMIT 1').fetchone()[0])
            self.assertNotIn('focus_issue', child)
            self.assertEqual(child['research']['root_job_id'], row[0])
            self.assertEqual(child['sources'][0], primary)
            bodies = [s for s in child['sources'] if s['url'] == URL]
            self.assertEqual(len(bodies), 1)
            self.assertIn('Explicit scope safety contract', bodies[0]['text'])
            self.assertNotIn('search_exhaustive', bodies[0])
            self.assertFalse(bodies[0]['related_issue_expansion']['candidate_focus_adopted'])

    def test_optional_lookup_error_is_visible_not_a_successful_empty_search(self):
        producer = object.__new__(research.ResearchProducer)
        producer.context = Context()
        with patch.object(
            producer.context,
            "issue_pr_context",
            create=True,
            side_effect=OSError("untrusted transport details"),
        ):
            result = producer.issue_pr_context("a/b", 42)
        self.assertEqual(
            result,
            {
                "sources": [],
                "status": "ERROR",
                "error": "OSError",
                "search_exhaustive": False,
            },
        )
        self.assertNotIn("untrusted transport", json.dumps(result))

    def test_cited_related_query_does_not_adopt_issue_focus_or_refresh_issue_body(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scout.initialize(root)
            config = root / "config.json"
            spec = {
                "repo": "a/b",
                "source_prefixes": ["src/"],
                "question": "Check boundaries",
            }
            config.write_text(
                json.dumps(
                    {
                        "objective": "Falsifiable leads",
                        "queue_target": 4,
                        "repos": [spec],
                    }
                )
            )
            context = Context()
            producer = research.ResearchProducer(root, config, context=context)
            primary = context.source("a/b", "a" * 40, "src/kernel.py")
            producer.emit("source-root", spec, [primary, SOURCE], "source_audit")
            with scout.connect(root) as db:
                row = db.execute("SELECT id FROM jobs").fetchone()
                db.execute(
                    "UPDATE jobs SET state='REVIEW', result=?, finished=? WHERE id=?",
                    (
                        json.dumps(
                            {
                                "analysis": ANALYSIS
                                | {
                                    "title": "kernel.py graph",
                                    "next_check": "src/kernel.py",
                                }
                            }
                        ),
                        time.time(),
                        row[0],
                    ),
                )
            related = {
                "sources": [
                    {"url": "https://github.com/a/b/pull/81", "text": "Fixes #42"}
                ],
                "status": "PARTIAL_SEARCH",
                "search_exhaustive": False,
            }
            with (
                patch.object(
                    context, "issue_pr_context", create=True, return_value=related
                ) as lookup,
                patch.object(context, "issue_sources") as issues,
                patch.object(context, "duplicate_sources") as titles,
            ):
                self.assertTrue(producer.followup(spec, {}))
            lookup.assert_called_once_with("a/b", 42)
            issues.assert_not_called()
            titles.assert_not_called()
            with scout.connect(root) as db:
                child = json.loads(
                    db.execute(
                        "SELECT packet FROM jobs ORDER BY created DESC LIMIT 1"
                    ).fetchone()[0]
                )
            self.assertNotIn("focus_issue", child)
            self.assertEqual(child["research"]["root_job_id"], row[0])
            self.assertFalse(child["issue_pr_lookup"]["candidate_focus_adopted"])
            self.assertEqual(child["sources"][0], primary)
            self.assertIn(related["sources"][0], child["sources"])


if __name__ == "__main__":
    unittest.main()
