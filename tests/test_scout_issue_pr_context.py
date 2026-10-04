"""Bounded issue-reference retrieval, not automatic duplicate classification."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout_context as context

REPO = "owner/project"
API = f"https://api.github.com/repos/{REPO}"


def pr(number=9, body="Fixes #42"):
    return {
        "number": number,
        "body": body,
        "title": "Different title",
        "state": "open",
        "repository_url": API,
        "pull_request": {"url": f"{API}/pulls/{number}"},
        "html_url": f"https://github.com/{REPO}/pull/{number}",
    }


class IssuePrContextTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.context = context.PublicContext(self.root, github_auth=True)
        self.calls = []
        self.metadata = {"private": False, "visibility": "public", "full_name": REPO}
        self.found = {"items": [pr()], "total_count": 1, "incomplete_results": False}
        fetch = patch.object(context.scout, "fetch", side_effect=self.fetch)
        fetch.start()
        self.addCleanup(fetch.stop)

    def fetch(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url == API:
            return json.dumps(self.metadata)
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(
            query,
            {
                "q": [f"repo:{REPO} is:pr in:body 42"],
                "sort": ["updated"],
                "per_page": ["5"],
            },
        )
        self.assertEqual(kwargs["limit"], 300_000)
        return json.dumps(self.found)

    def test_explicit_reference_is_partial_related_evidence(self):
        result = self.context.issue_pr_context(REPO, 42)
        self.assertEqual(
            result["sources"][0]["url"], f"https://github.com/{REPO}/pull/9"
        )
        self.assertEqual(result["sources"][0]["reference_literal"], "#42")
        self.assertEqual(result["sources"][0]["observed_pr_state"], "open")
        self.assertEqual(result["status"], "PARTIAL_SEARCH")
        self.assertFalse(result["search_exhaustive"])
        self.assertEqual(len(self.calls), 2)
        self.assertTrue(all(kwargs["github_auth"] for _, kwargs in self.calls))

    def test_only_exact_issue_references_and_verified_repo_urls(self):
        bodies = [
            "42",
            "#420",
            "other/repo#42",
            "https://github.com/other/repo/issues/42",
            "#42_suffix",
            f"https://github.com/{REPO}/issues/420",
        ]
        for body in bodies:
            with self.subTest(body=body):
                self.found["items"] = [pr(body=body)]
                self.context._cache_path("issue-pr", [REPO, 42]).unlink(missing_ok=True)
                self.assertEqual(self.context.issue_pr_context(REPO, 42)["sources"], [])
        self.found["items"] = [
            pr(body=f"Related: https://github.com/{REPO}/issues/42#issuecomment-1")
        ]
        self.context._cache_path("issue-pr", [REPO, 42]).unlink()
        self.assertEqual(len(self.context.issue_pr_context(REPO, 42)["sources"]), 1)

    def test_wrong_repository_or_non_pr_hits_are_discarded(self):
        items = [pr(i) for i in range(1, 6)]
        items[0]["repository_url"] = "https://api.github.com/repos/private/secret"
        items[1]["html_url"] = "https://github.com/other/repo/pull/2"
        items[2]["pull_request"]["url"] = (
            "https://api.github.com/repos/other/repo/pulls/3"
        )
        items[3].pop("pull_request")
        items[4]["number"] = True
        self.found.update(items=items, total_count=5)
        self.assertEqual(self.context.issue_pr_context(REPO, 42)["sources"], [])

    def test_invalid_numbers_do_not_fetch(self):
        for number in [True, -1, 0, 1_000_000_001, "42 is:closed"]:
            with self.assertRaises(ValueError):
                self.context.issue_pr_context(REPO, number)
        self.assertEqual(self.calls, [])

    def test_private_repository_blocks_search(self):
        self.metadata["private"] = True
        with self.assertRaisesRegex(ValueError, "non-public"):
            self.context.issue_pr_context(REPO, 42)
        self.assertEqual(len(self.calls), 1)

    def test_cache_ttl_and_future_timestamp(self):
        with patch.object(context.time, "time", return_value=1000):
            first = self.context.issue_pr_context(REPO, 42)
            self.assertEqual(self.context.issue_pr_context(REPO, 42), first)
        self.assertEqual(len(self.calls), 2)
        with patch.object(context.time, "time", return_value=999):
            self.context.issue_pr_context(REPO, 42)
        self.assertEqual(len(self.calls), 3)
        with patch.object(context.time, "time", return_value=1901):
            self.context.issue_pr_context(REPO, 42)
        self.assertEqual(len(self.calls), 5)

    def test_invalid_cache_is_refetched(self):
        cache = self.context._cache_path("issue-pr", [REPO, 42])
        context.scout.write_json(
            cache,
            {
                "at": context.time.time(),
                "found": {
                    "items": [],
                    "total_count": False,
                    "incomplete_results": False,
                },
            },
        )
        self.assertEqual(len(self.context.issue_pr_context(REPO, 42)["sources"]), 1)
        self.assertEqual(len(self.calls), 2)

    def test_malformed_or_oversize_response_is_not_empty_search(self):
        for found in [
            {},
            {"items": [], "total_count": False, "incomplete_results": False},
            {"items": [pr()], "total_count": 0, "incomplete_results": False},
            {"items": [], "total_count": 0, "incomplete_results": "false"},
            {
                "items": [],
                "total_count": 0,
                "incomplete_results": False,
                "padding": "x" * 300_000,
            },
        ]:
            self.found = found
            with self.subTest(found=list(found)):
                with self.assertRaises(ValueError):
                    self.context.issue_pr_context(REPO, 42)

    def test_first_five_excerpts_are_bounded_and_keep_reference(self):
        self.found.update(
            items=[pr(i, "x" * 4000 + " Fixes #42 " + "y" * 4000) for i in range(1, 7)],
            total_count=100,
            incomplete_results=True,
        )
        result = self.context.issue_pr_context(REPO, 42)
        self.assertEqual(len(result["sources"]), 5)
        self.assertEqual(result["returned_items"], 5)
        self.assertTrue(result["incomplete_results"])
        for source in result["sources"]:
            self.assertLessEqual(len(source["text"]), 2200)
            self.assertTrue(source["truncated"])
            self.assertEqual(source["reference_literal"], "#42")

    def test_empty_search_is_not_absence_proof(self):
        self.found.update(items=[], total_count=0)
        result = self.context.issue_pr_context(REPO, 42)
        self.assertEqual(result["sources"], [])
        self.assertEqual(result["status"], "PARTIAL_SEARCH")
        self.assertFalse(result["search_exhaustive"])


if __name__ == "__main__":
    unittest.main()
