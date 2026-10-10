"""Bounded PR reads: revision drift, hostile refs, omissions and follow-up use."""

from copy import deepcopy
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
from kimi_scout_context import PublicContext  # noqa: E402
from scout_pr_revision import pr_revision_sources, requested_pr_number  # noqa: E402
from tests.test_kimi_scout_research import Context  # noqa: E402

REPO = "a/b"
API = "https://api.github.com/repos/a/b"
URL = "https://github.com/a/b/pull/42"
BASE, HEAD, MERGE = "a" * 40, "b" * 40, "c" * 40
SOURCE = {
    "url": f"https://raw.githubusercontent.com/a/b/{BASE}/src/core.py",
    "text": "old",
}
DISPLAYED = [SOURCE, {"url": URL, "text": "Existing PR description"}]


def fixtures():
    pr = {
        "number": 42,
        "html_url": URL,
        "base": {"sha": BASE, "repo": {"full_name": REPO}},
        "head": {
            "sha": HEAD,
            "repo": {
                "full_name": "author/b",
                "private": False,
                "visibility": "public",
            },
        },
    }
    comparison = {
        "url": f"{API}/compare/{BASE}...{HEAD}",
        "base_commit": {"sha": BASE},
        "merge_base_commit": {"sha": MERGE},
        "files": [{"filename": "src/core.py", "patch": "@@ -1 +1 @@\n-old\n+new"}],
    }
    return pr, comparison


class SelectionTests(unittest.TestCase):
    def test_explicit_displayed_request_not_incidental_risk(self):
        for request in ("Inspect #42's actual diff", f"Read {URL}."):
            self.assertEqual(
                requested_pr_number(REPO, DISPLAYED, {"next_check": request}), 42
            )
        self.assertIsNone(
            requested_pr_number(REPO, DISPLAYED, {"duplicate_risk": "#42"})
        )
        self.assertIsNone(requested_pr_number(REPO, [], {"next_check": "Read #42"}))

    def test_first_requested_not_first_search_result_and_number_boundaries(self):
        sources = DISPLAYED + [{"url": URL.replace("42", "43"), "text": "Other"}]
        self.assertEqual(
            requested_pr_number(REPO, sources, {"next_check": "#43 then #42"}), 43
        )
        for value in (
            "#420",
            "#42extra",
            "x#42",
            "https://github.com/foreign/repo/pull/42",
            URL + "#issuecomment-1",
            URL + "?private=1",
            "x" * 2000 + " #42",
        ):
            self.assertIsNone(
                requested_pr_number(REPO, sources, {"next_check": value}), value
            )

    def test_malformed_and_unshown_refs_abstain(self):
        for sources, analysis in (
            (None, {}),
            ([None], {"next_check": "#42"}),
            (DISPLAYED, None),
            (DISPLAYED, {"next_check": []}),
        ):
            self.assertIsNone(requested_pr_number(REPO, sources, analysis))
        self.assertIsNone(
            requested_pr_number("a/b private", DISPLAYED, {"next_check": "#42"})
        )
        self.assertIsNone(
            requested_pr_number(REPO, [{}] * 25 + DISPLAYED, {"next_check": "#42"})
        )


class ReadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.context = PublicContext(self.tmp.name)
        self.pr, self.comparison = fixtures()
        self.calls = []

    def fetch(self, url, limit, github_auth):
        self.calls.append((url, limit))
        if url in (API, "https://api.github.com/repos/author/b"):
            return json.dumps(
                {
                    "private": False,
                    "visibility": "public",
                    "full_name": url.split("/repos/")[1],
                }
            )
        if url == API + "/pulls/42":
            return json.dumps(self.pr)
        if "/compare/" in url:
            return json.dumps(self.comparison)
        self.fail("Unexpected request: " + url)

    def read(self):
        with patch.object(scout, "fetch", self.fetch):
            return pr_revision_sources(self.context, REPO, 42, DISPLAYED)[0]

    def test_immutable_compare_not_mutable_pr_files_or_returned_urls(self):
        self.pr["diff_url"] = "https://foreign.invalid/do-not-fetch"
        result = self.read()
        self.assertEqual(result["base_commit"], BASE)
        self.assertEqual(result["head_commit"], HEAD)
        self.assertEqual(result["merge_base_commit"], MERGE)
        self.assertFalse(result["patch_exhaustive"])
        self.assertTrue(result["truncated"])
        self.assertIn("+new", result["text"])
        self.assertEqual(
            self.calls[-1],
            (f"{API}/compare/{BASE}...{HEAD}?per_page=1&page=1", 300_000),
        )
        self.assertEqual(len(self.calls), 4)
        self.assertNotIn("/files", " ".join(url for url, _ in self.calls))

    def test_force_push_refreshed_without_claiming_latest_after_observation(self):
        first = self.read()
        self.pr["head"]["sha"] = "d" * 40
        self.comparison["url"] = f"{API}/compare/{BASE}...{'d' * 40}"
        second = self.read()
        self.assertNotEqual(
            research.retrieval_identity(first), research.retrieval_identity(second)
        )
        self.assertEqual(second["head_commit"], "d" * 40)
        self.assertEqual(
            len(self.calls), 6
        )  # visibility reused, PR identity not cached

    def test_force_push_between_metadata_and_compare_keeps_observed_head(self):
        def drifting_fetch(url, limit, github_auth):
            response = self.fetch(url, limit, github_auth)
            if url.endswith("/pulls/42"):
                self.pr["head"]["sha"] = "d" * 40
            return response

        with patch.object(scout, "fetch", drifting_fetch):
            result = pr_revision_sources(self.context, REPO, 42, DISPLAYED)[0]
        self.assertEqual(result["head_commit"], HEAD)
        self.assertIn(f"{BASE}...{HEAD}?", self.calls[-1][0])

    def test_file_and_patch_limits_and_preferred_primary_path(self):
        self.comparison["files"] = [
            {"filename": f"docs/{i}.md", "patch": "p" * (10000 if i < 2 else 1)}
            for i in range(299)
        ] + [{"filename": "src/core.py"}]
        result = self.read()
        self.assertEqual(result["observed_files"], 300)
        self.assertEqual(len(result["displayed_files"]), 3)
        self.assertEqual(result["displayed_files"][0], "src/core.py")
        self.assertIn("API supplied no patch", result["text"])
        self.assertIn("patch excerpt truncated", result["text"])
        self.assertLess(len(result["text"]), 6500)
        self.assertEqual(len(list(Path(self.tmp.name).rglob("*.json"))), 0)

    def test_empty_list_is_partial_not_no_change_or_coverage(self):
        self.comparison["files"] = []
        result = self.read()
        self.assertFalse(result["patch_exhaustive"])
        self.assertIn("absent/short patches", result["text"])

    def test_private_or_wrong_repo_and_malformed_revisions_fail_before_compare(self):
        original = deepcopy(self.pr)
        cases = [("number", True), ("number", 43), ("html_url", URL + "?x=1")]
        for key, value in cases:
            self.pr = deepcopy(original)
            self.pr[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.read()
        for part, key, value in (
            ("base", "sha", "main"),
            ("head", "sha", "f" * 39),
            ("head", "repo", None),
            ("base", "repo", {"full_name": "x/y"}),
            ("head", "repo", {"full_name": "x/y", "private": True}),
        ):
            self.pr = deepcopy(original)
            self.pr[part][key] = value
            with self.subTest(part=part, key=key), self.assertRaises(ValueError):
                self.read()
        self.assertFalse(any("/compare/" in url for url, _ in self.calls))

    def test_visibility_rechecked_by_new_context_even_with_auth(self):
        with patch.object(
            scout,
            "fetch",
            return_value=json.dumps({"private": True, "visibility": "private"}),
        ) as fetch:
            with self.assertRaises(ValueError):
                pr_revision_sources(
                    PublicContext(self.tmp.name, True), REPO, 42, DISPLAYED
                )
        self.assertEqual(fetch.call_count, 1)

    def test_mismatched_response_oversize_or_unsafe_files_rejected(self):
        original = deepcopy(self.comparison)
        for key, value in (
            ("url", API + "/compare/main...main"),
            ("base_commit", {"sha": HEAD}),
            ("merge_base_commit", {"sha": "bad"}),
            ("files", None),
            ("files", [None]),
            ("files", [{"filename": "../secret"}]),
            ("files", [{"filename": "x"}, {"filename": "x"}]),
            ("files", [{"filename": "x", "previous_filename": "C:/secret"}]),
        ):
            self.comparison = deepcopy(original)
            self.comparison[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.read()
        self.comparison = original
        self.comparison["files"][0]["patch"] = "界" * 100001
        with self.assertRaisesRegex(ValueError, "read budget"):
            self.read()


class FollowupTests(unittest.TestCase):
    def test_opt_in_acquires_patch_instead_of_another_search_and_keeps_primary(self):
        for enabled, failure in ((False, None), (True, None), (True, OSError)):
            with (
                self.subTest(enabled=enabled, failure=failure),
                tempfile.TemporaryDirectory() as tmp,
            ):
                root = Path(tmp)
                scout.initialize(root)
                spec = {
                    "repo": REPO,
                    "source_prefixes": ["src/"],
                    "question": "Check boundaries",
                    "followup_pr_revision_context": enabled,
                }
                config = root / "config.json"
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
                primary = context.source(REPO, BASE, "src/kernel.py")
                producer.emit("root", spec, [primary, DISPLAYED[1]], "source_audit")
                with scout.connect(root) as db:
                    parent = db.execute("SELECT id FROM jobs").fetchone()[0]
                    db.execute(
                        "UPDATE jobs SET state='NEEDS_CONTEXT',result=?,finished=? WHERE id=?",
                        (
                            json.dumps(
                                {
                                    "analysis": {
                                        "title": "kernel boundary",
                                        "next_check": "Inspect #42 diff",
                                        "decision": "needs_context",
                                    }
                                }
                            ),
                            time.time(),
                            parent,
                        ),
                    )
                revision = {
                    "url": f"https://github.com/a/b/compare/{BASE}...{HEAD}",
                    "text": "Pinned patch",
                }
                with (
                    patch.object(
                        research,
                        "pr_revision_sources",
                        return_value=[revision],
                        side_effect=failure("untrusted transport details")
                        if failure
                        else None,
                    ) as read,
                    patch.object(
                        context, "duplicate_sources", wraps=context.duplicate_sources
                    ) as search,
                ):
                    progress = {}
                    self.assertTrue(producer.followup(spec, progress))
                self.assertEqual(read.call_count, int(enabled))
                self.assertEqual(
                    search.call_count, int(not enabled or failure is not None)
                )
                if failure:
                    self.assertEqual(progress["pr_revision_context_error"], "OSError")
                    self.assertNotIn("untrusted transport", json.dumps(progress))
                with scout.connect(root) as db:
                    child = json.loads(
                        db.execute(
                            "SELECT packet FROM jobs ORDER BY created DESC LIMIT 1"
                        ).fetchone()[0]
                    )
                self.assertEqual(child["sources"][0], primary)
                self.assertNotIn("focus_issue", child)
                self.assertEqual(child["research"]["root_job_id"], parent)
                self.assertEqual(child["research"]["depth"], 1)
                if enabled and not failure:
                    self.assertIn(revision, child["sources"])
                else:
                    self.assertNotIn(revision, child["sources"])


if __name__ == "__main__":
    unittest.main()
