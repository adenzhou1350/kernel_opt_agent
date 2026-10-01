"""Bounded related-work retrieval, not a semantic duplicate classifier."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from kimi_scout_context import PublicContext


class DuplicateFallbackTests(unittest.TestCase):
    def search(self, title, *, first_items=(), last_items=()):
        queries = []

        def fetch(url, **kwargs):
            if url == "https://api.github.com/repos/owner/project":
                return json.dumps({"private": False, "visibility": "public"})
            query = parse_qs(urlsplit(url).query)
            self.assertEqual(query["per_page"], ["5"])
            queries.append(query["q"][0])
            return json.dumps({"items": list(first_items if len(queries) == 1 else last_items)})

        with tempfile.TemporaryDirectory() as directory, patch(
            "kimi_scout_context.scout.fetch", side_effect=fetch
        ):
            sources = PublicContext(Path(directory)).duplicate_sources("owner/project", title)
        return queries, sources

    def test_empty_conjunction_uses_code_identifier_and_carries_query(self):
        for title, anchor in (
            ("ADLogger env set_level verbose silently uses INFO", "ADLogger"),
            ("gemma4_utils suffix sentinel order leaks turn marker", "gemma4_utils"),
            ("Fix _clean_answer stripping tags in wrong order", "_clean_answer"),
        ):
            with self.subTest(title=title):
                queries, sources = self.search(title, last_items=[
                    {"number": 12, "title": "existing fix", "body": "different prose",
                     "pull_request": {}}
                ])
                self.assertEqual(len(queries), 2)
                self.assertEqual(queries[-1], f'repo:owner/project in:title,body "{anchor}"')
                self.assertEqual(sources[0]["search_query"], queries[-1])
                self.assertFalse(sources[0]["search_exhaustive"])

    def test_nonempty_first_sample_does_not_spend_second_request(self):
        queries, sources = self.search("ADLogger env set_level verbose mapping fix",
                                      first_items=[{"number": 1, "title": "fix"}])
        self.assertEqual(len(queries), 1)
        self.assertEqual(len(sources), 1)

    def test_empty_short_query_not_repeated(self):
        queries, sources = self.search("clean answer")
        self.assertEqual(len(queries), 1)
        self.assertEqual(sources, [])

    def test_fallback_remains_scoped_capped_and_untrusted(self):
        queries, sources = self.search(
            'ADLogger repo:secret/data OR "is:pr" many words',
            last_items=[{"number": i, "title": "sample", "html_url": "https://evil/",
                         "repository_url": "https://api.github.com/repos/owner/project"}
                        for i in range(1, 9)]
        )
        self.assertEqual(len(queries), 2)
        self.assertEqual(len(sources), 5)
        self.assertTrue(all(q.startswith("repo:owner/project in:title,body ") for q in queries))
        self.assertTrue(all("repo:secret" not in q for q in queries))
        self.assertTrue(all(s["url"].startswith("https://github.com/owner/project/") for s in sources))


if __name__ == "__main__":
    unittest.main()
