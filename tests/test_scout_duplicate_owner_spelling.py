"""Bounded related-work hints must tolerate prose spelling without verdicts."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from kimi_scout_context import PublicContext  # noqa: E402


class DuplicateOwnerSpellingTests(unittest.TestCase):
    repo = "public/project"

    def hit(self, number, *, pull=True, **extra):
        return {
            "number": number,
            "title": "Related work",
            "body": "Evidence, not a duplicate verdict.",
            "repository_url": f"https://api.github.com/repos/{self.repo}",
            **({"pull_request": {}} if pull else {}),
            **extra,
        }

    def search(self, title, respond):
        queries = []

        def fetch(url):
            query = parse_qs(urlsplit(url).query)
            self.assertEqual(query["per_page"], ["5"])
            self.assertNotIn("sort", query)
            queries.append(query["q"][0])
            return {"items": respond(queries[-1], len(queries))}

        with tempfile.TemporaryDirectory() as root:
            ctx = PublicContext(Path(root))
            with (
                patch.object(ctx, "_public"),
                patch.object(ctx, "_json", side_effect=fetch),
            ):
                return ctx.duplicate_sources(self.repo, title), queries

    def test_spaced_owner_can_retrieve_differently_worded_fix(self):
        def respond(query, count):
            if count == 1:
                return []
            if '("UNIXSocketListener" OR "UNIX Socket Listener")' in query:
                return [self.hit(1398)]
            return [self.hit(1133)]

        sources, queries = self.search("UNIXSocketListener.aclose", respond)
        self.assertEqual(len(queries), 2)
        self.assertEqual(
            queries[0], f'repo:{self.repo} in:title,body "UNIXSocketListener" "aclose"'
        )
        self.assertEqual(
            queries[1],
            f'repo:{self.repo} in:title,body ("UNIXSocketListener" OR "UNIX Socket Listener")',
        )
        self.assertEqual(sources[0]["url"], f"https://github.com/{self.repo}/pull/1398")
        self.assertFalse(sources[0]["search_exhaustive"])
        self.assertNotIn("duplicate", sources[0])

    def test_issue_self_hit_retained_with_scoped_pr_fallback(self):
        def respond(query, count):
            return (
                [self.hit(1, pull=False)]
                if count == 1
                else [
                    self.hit(2),
                    self.hit(3, pull=False),
                    self.hit(
                        4, repository_url="https://api.github.com/repos/other/project"
                    ),
                ]
            )

        sources, queries = self.search("HTTPRequest.close fails", respond)
        self.assertEqual(
            queries[1],
            f'repo:{self.repo} is:pr in:title,body ("HTTPRequest" OR "HTTP Request")',
        )
        self.assertEqual(
            [s["url"] for s in sources],
            [
                f"https://github.com/{self.repo}/pull/2",
                f"https://github.com/{self.repo}/issues/1",
            ],
        )

    def test_first_query_pr_keeps_one_request(self):
        sources, queries = self.search("DummyFile.close", lambda q, n: [self.hit(3)])
        self.assertEqual(len(queries), 1)
        self.assertEqual(len(sources), 1)

    def test_all_caps_snake_case_numeric_and_lowercase_keep_existing_query(self):
        for title, fallback in (
            ("fix HTTP close", '"fix" "HTTP"'),
            ("fix socket_close", '"socket_close"'),
            ("fix H2Connection.close", '"H2Connection"'),
            ("fix readBlock", '"readBlock"'),
        ):
            with self.subTest(title=title):
                sources, queries = self.search(title, lambda q, n: [])
                self.assertEqual(sources, [])
                self.assertEqual(
                    queries[-1], f"repo:{self.repo} in:title,body {fallback}"
                )
                self.assertLessEqual(len(queries), 2)

    def test_alias_cannot_embed_query_operators_or_change_repo(self):
        _, queries = self.search(
            'HTTPRequest.close repo:other/project OR "bad"', lambda q, n: []
        )
        self.assertEqual(
            queries[-1],
            f'repo:{self.repo} in:title,body ("HTTPRequest" OR "HTTP Request")',
        )
        self.assertTrue(
            all(q.startswith(f"repo:{self.repo} in:title,body ") for q in queries)
        )
        self.assertTrue(all("repo:other" not in q for q in queries))


if __name__ == "__main__":
    unittest.main()
