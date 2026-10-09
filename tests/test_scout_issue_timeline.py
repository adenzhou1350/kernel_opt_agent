"""Offline linked-work retrieval boundaries; no model, network or code execution."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout_context as ctx
from scout_issue_timeline import linked_pr_context

REPO = "owner/project"
API = f"https://api.github.com/repos/{REPO}"
TIMELINE = f"{API}/issues/42/timeline?per_page=50&page=1"


def event(number=7):
    return {"event": "cross-referenced", "source": {"type": "issue", "issue": {
        "number": number, "title": "Different title", "body": "No issue number in body",
        "state": "open", "url": f"{API}/issues/{number}", "repository_url": API,
        "html_url": f"https://github.com/{REPO}/pull/{number}",
        "pull_request": {"url": f"{API}/pulls/{number}"},
    }}}


class TimelineTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.context = ctx.PublicContext(Path(temp.name), github_auth=True)
        self.events = [event()]
        self.calls = []
        self.private = False
        mocked = patch.object(ctx.scout, "fetch", side_effect=self.fetch)
        mocked.start()
        self.addCleanup(mocked.stop)

    def fetch(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url == API:
            return json.dumps({"private": self.private, "visibility": "public", "full_name": REPO})
        if url == f"{API}/issues/42":
            return json.dumps({"number": 42, "title": "Report", "body": "bug", "comments": 0})
        self.assertEqual(url, TIMELINE)
        self.assertEqual(kwargs["limit"], 300_000)
        self.assertTrue(kwargs["github_auth"])
        if isinstance(self.events, Exception):
            raise self.events
        return json.dumps(self.events)

    def lookup(self):
        return linked_pr_context(self.context, REPO, 42)

    def clear_cache(self):
        self.context._cache_path("issue-linked-pr", [REPO, 42]).unlink(missing_ok=True)

    def test_issue_integration_recovers_pr_without_body_reference(self):
        sources = self.context.issue_sources(REPO, 42)
        self.assertEqual(len(sources), 2)
        self.assertEqual(sources[1]["url"], f"https://github.com/{REPO}/pull/7")
        self.assertEqual(sources[1]["relationship"], "issue_timeline_cross_reference")
        self.assertEqual(sources[1]["referenced_issue"], 42)
        self.assertFalse(sources[0]["linked_pr_lookup"]["search_exhaustive"])
        self.assertFalse(sources[0]["comments_truncated"])
        self.assertEqual([url for url, _ in self.calls], [API, f"{API}/issues/42", TIMELINE])

    def test_deduplicated_first_three_prs_and_bounded_text(self):
        self.events = [event(), event(), event(8), event(9), event(10)]
        self.events[0]["source"]["issue"]["body"] = "x" * 10000
        result = self.lookup()
        self.assertEqual(len(result["sources"]), 3)
        self.assertEqual(result["events_observed"], 5)
        self.assertTrue(result["sources"][0]["truncated"])
        self.assertTrue(all(len(s["text"]) <= 1800 for s in result["sources"]))
        cache = self.context._cache_path("issue-linked-pr", [REPO, 42])
        self.assertLess(cache.stat().st_size, 12_000)
        self.assertEqual(self.lookup(), result)

    def test_bad_source_event_and_foreign_or_forged_links_are_not_followed(self):
        mutations = [
            lambda x: x.update(event="referenced"),
            lambda x: x.update(source="bad"),
            lambda x: x["source"].update(type="commit"),
            lambda x: x["source"].update(issue=[]),
            lambda x: x["source"]["issue"].update(number=True),
            lambda x: x["source"]["issue"].update(number=-1),
            lambda x: x["source"]["issue"].update(repository_url=API + "-other"),
            lambda x: x["source"]["issue"].update(url=f"{API}/issues/700"),
            lambda x: x["source"]["issue"].update(html_url="https://github.com/private/repo/pull/7"),
            lambda x: x["source"]["issue"]["pull_request"].update(url="https://evil/pulls/7"),
            lambda x: x["source"]["issue"].pop("pull_request"),
            lambda x: x["source"]["issue"].update(state="merged"),
            lambda x: x["source"]["issue"].update(body={}),
        ]
        for change in mutations:
            with self.subTest(change=change):
                self.clear_cache()
                item = event()
                change(item)
                self.events = [item]
                self.assertEqual(self.lookup()["sources"], [])
        self.assertTrue(all(url in (API, TIMELINE) for url, _ in self.calls))

    def test_empty_null_body_and_closed_pr_are_only_partial_observations(self):
        self.events = []
        self.assertEqual(self.lookup()["status"], "PARTIAL_TIMELINE")
        self.clear_cache()
        self.events = [event()]
        self.events[0]["source"]["issue"].update(body=None, state="closed")
        source = self.lookup()["sources"][0]
        self.assertEqual(source["observed_pr_state"], "closed")
        self.assertIn("Not a coverage, fix, merge", source["relationship_scope"])
        self.assertFalse(source["search_exhaustive"])

    def test_ttl_future_and_invalid_cache_refetch(self):
        with patch("scout_issue_timeline.time.time", return_value=1000):
            self.lookup()
            self.lookup()
        self.assertEqual(sum(url == TIMELINE for url, _ in self.calls), 1)
        with patch("scout_issue_timeline.time.time", return_value=999):
            self.lookup()
        with patch("scout_issue_timeline.time.time", return_value=1900):
            self.lookup()
        self.assertEqual(sum(url == TIMELINE for url, _ in self.calls), 3)
        ctx.scout.write_json(self.context._cache_path("issue-linked-pr", [REPO, 42]),
                             {"at": 1900, "events": {}})
        with patch("scout_issue_timeline.time.time", return_value=1901):
            self.lookup()
        self.assertEqual(sum(url == TIMELINE for url, _ in self.calls), 4)

    def test_unavailable_or_malformed_is_not_empty_success(self):
        for value in [OSError("unavailable"), {}, [event()] * 51, [{"padding": "x" * 300000}]]:
            with self.subTest(value=type(value)):
                self.clear_cache()
                self.events = value
                result = self.lookup()
                self.assertEqual(result["status"], "TIMELINE_UNAVAILABLE")
                self.assertFalse(result["search_exhaustive"])
                self.assertEqual(result["sources"], [])

    def test_private_and_invalid_issue_rejected_before_timeline(self):
        self.private = True
        with self.assertRaisesRegex(ValueError, "non-public"):
            self.lookup()
        self.assertEqual(len(self.calls), 1)
        self.calls.clear()
        for number in [True, 0, -1, "42 is:pr", 1_000_000_001]:
            with self.assertRaises(ValueError):
                linked_pr_context(self.context, REPO, number)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
