"""Public-only read boundaries and actual producer follow-up integration."""

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout as scout
import kimi_scout_research as research
import scout_discussion_context as discussion
from kimi_scout_context import PublicContext


class DiscussionContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.context = PublicContext(self.root, github_auth=True)
        self.repo = "encode/httpx"
        self.title = 'FileField headers bug repo:private/repo "in:body"'
        self.url = f"https://github.com/{self.repo}/discussions/3789"
        self.row = {
            "number": 3789,
            "title": "FileField writes to a Mapping",
            "body": "Tested fix ready; author offers a PR.",
            "url": self.url,
            "repository": {"nameWithOwner": self.repo, "isPrivate": False},
            "comments": {
                "nodes": [
                    {
                        "url": self.url + "#discussioncomment-1",
                        "body": "Independent comparison.",
                    }
                ],
                "pageInfo": {"hasNextPage": False},
            },
        }
        self.metadata = {
            "private": False,
            "visibility": "public",
            "full_name": self.repo,
        }
        self.fetch = patch.object(
            scout, "fetch", side_effect=lambda *a, **k: json.dumps(self.metadata)
        )
        self.fetch.start()
        self.addCleanup(self.fetch.stop)

    def read(self):
        return discussion.discussion_sources(self.context, self.repo, self.title)

    def test_scoped_query_cached_and_author_offer_retained_as_untrusted_evidence(self):
        with patch.object(discussion, "_query", return_value=[self.row]) as query:
            first = self.read()
            self.assertEqual(self.read(), first)
            query.assert_called_once_with(self.context, 'repo:encode/httpx "FileField"')
        self.assertEqual(first[0]["url"], self.url)
        self.assertIn("author offers a PR", first[0]["text"])
        self.assertIn("Independent comparison", first[0]["text"])
        self.assertIs(first[0]["search_exhaustive"], False)
        self.assertIs(first[0]["comments_truncated"], False)
        self.assertNotIn("duplicate", first[0])
        with (
            patch.object(discussion.time, "time", return_value=0),
            patch.object(discussion, "_query", return_value=[]) as query,
        ):
            self.assertEqual(self.read(), [])
            query.assert_called_once()  # Future/invalid cache time cannot suppress a read.

    def test_private_visibility_and_missing_auth_fail_before_graphql(self):
        self.metadata["private"] = True
        with patch.object(discussion, "_query") as query:
            with self.assertRaisesRegex(ValueError, "non-public"):
                self.read()
            query.assert_not_called()
        self.metadata["private"] = False
        self.context.github_auth = False
        with patch.object(discussion, "_query") as query:
            with self.assertRaisesRegex(ValueError, "configured GitHub auth"):
                self.read()
            query.assert_not_called()

    def test_cross_repo_private_url_and_malformed_nodes_never_enter_context(self):
        bad = [
            None,
            {
                **self.row,
                "repository": {"nameWithOwner": "other/repo", "isPrivate": False},
            },
            {**self.row, "repository": {"nameWithOwner": self.repo, "isPrivate": True}},
            {**self.row, "url": "https://elsewhere/secret"},
            {**self.row, "number": True},
        ]
        for row in bad:
            with (
                self.subTest(row=row),
                patch.object(discussion, "_query", return_value=[row]),
            ):
                # Use a distinct query/cache for each independent bad response.
                self.context._load = lambda p: None
                self.assertEqual(self.read(), [])

    def test_text_result_comment_limits_and_missing_page_metadata_are_explicit(self):
        row = {
            **self.row,
            "body": "x" * 10000,
            "comments": {
                "nodes": [
                    {"url": self.url + f"#discussioncomment-{i}", "body": "y" * 2000}
                    for i in range(1, 8)
                ]
            },
        }
        with patch.object(discussion, "_query", return_value=[row] * 8):
            rows = self.read()
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r["truncated"] and r["comments_truncated"] for r in rows))
        self.assertTrue(all(len(r["text"]) <= 5500 for r in rows))
        self.assertNotIn("discussioncomment-4", rows[0]["text"])
        self.assertEqual(
            discussion.discussion_sources(self.context, self.repo, "纯中文"), []
        )
        with self.assertRaises(ValueError):
            discussion.discussion_sources(self.context, "../unsafe", "FileField")

    def test_real_request_is_query_only_fixed_host_bounded_and_no_redirect(self):
        opener = Mock()
        opener.open.return_value = io.BytesIO(
            json.dumps({"data": {"search": {"nodes": [self.row]}}}).encode()
        )
        with (
            patch.object(
                discussion.urllib.request, "build_opener", return_value=opener
            ),
            patch.object(
                scout, "github_auth_header", return_value="Bearer test-fixture"
            ),
        ):
            self.assertEqual(
                discussion._query(self.context, "repo:encode/httpx FileField"),
                [self.row],
            )
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.github.com/graphql")
        self.assertEqual(request.get_method(), "POST")
        body = json.loads(request.data)
        self.assertTrue(body["query"].startswith("query("))
        self.assertNotIn("mutation", body["query"])
        self.assertEqual(body["variables"], {"q": "repo:encode/httpx FileField"})
        self.assertEqual(opener.open.call_args.kwargs, {"timeout": 20})

    def test_api_errors_bad_shape_and_oversize_do_not_mean_zero_discussions(self):
        values = [
            {"errors": ["unavailable"]},
            {"data": None},
            {"data": {"search": {"nodes": None}}},
        ]
        for value in values:
            opener = Mock()
            opener.open.return_value = io.BytesIO(json.dumps(value).encode())
            with (
                self.subTest(value=value),
                patch.object(
                    discussion.urllib.request, "build_opener", return_value=opener
                ),
                patch.object(
                    scout, "github_auth_header", return_value="Bearer test-fixture"
                ),
                self.assertRaises((ValueError, TypeError)),
            ):
                discussion._query(self.context, "repo:encode/httpx FileField")
        opener.open.return_value = io.BytesIO(b"x" * (discussion.API_LIMIT + 1))
        with (
            patch.object(
                discussion.urllib.request, "build_opener", return_value=opener
            ),
            patch.object(
                scout, "github_auth_header", return_value="Bearer test-fixture"
            ),
            self.assertRaisesRegex(ValueError, "budget"),
        ):
            discussion._query(self.context, "repo:encode/httpx FileField")

    def test_producer_default_off_opt_in_adds_real_evidence_without_executing_it(self):
        scout.initialize(self.root)
        spec = {
            "repo": self.repo,
            "source_prefixes": ["httpx/"],
            "question": "Find supported bugs",
        }
        config = self.root / "research.json"
        config.write_text(
            json.dumps({"objective": "test", "queue_target": 4, "repos": [spec]}),
            encoding="utf-8",
        )
        context = Mock()
        context.snapshot.return_value = {
            "commit": "a" * 40,
            "files": ["httpx/_multipart.py"],
        }
        source = {
            "url": f"https://raw.githubusercontent.com/{self.repo}/{'a' * 40}/httpx/_multipart.py",
            "text": "1: FileField headers",
        }
        context.source.return_value = source
        context.duplicate_sources.return_value = []
        producer = research.ResearchProducer(self.root, config, context=context)
        producer.emit("initial", spec, [source], "source_audit")
        with scout.connect(self.root) as db:
            db.execute(
                "UPDATE jobs SET state='NEEDS_CONTEXT',finished=1,result=?",
                (
                    json.dumps(
                        {
                            "analysis": {
                                "decision": "lead",
                                "title": "FileField headers",
                                "next_check": "httpx/_multipart.py",
                            }
                        }
                    ),
                ),
            )
        with patch.object(
            research,
            "discussion_sources",
            return_value=[
                scout.evidence(self.url, "Author tested fix and offers a PR")
            ],
        ) as lookup:
            self.assertFalse(producer.followup(spec, {}))  # No new evidence by default.
            lookup.assert_not_called()
            # Reset only the controlled fixture's exhausted follow-up cursor.
            with scout.connect(self.root) as db:
                db.execute("DELETE FROM research_seen WHERE key LIKE 'followup:%'")
            spec["followup_discussion_context"] = True
            self.assertTrue(producer.followup(spec, {}))
            lookup.assert_called_once_with(context, self.repo, "FileField headers")
        with scout.connect(self.root) as db:
            row = db.execute(
                "SELECT state,packet FROM jobs WHERE state='PENDING'"
            ).fetchone()
        self.assertEqual(row["state"], "PENDING")
        packet = json.loads(row["packet"])
        self.assertEqual(
            packet["sources"],
            [source, scout.evidence(self.url, "Author tested fix and offers a PR")],
        )
        self.assertIn("discussion author", packet["question"])
        spec["followup_discussion_context"] = "yes"
        config.write_text(
            json.dumps({"objective": "test", "queue_target": 4, "repos": [spec]}),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "boolean"):
            research.configuration(config)


if __name__ == "__main__":
    unittest.main()
