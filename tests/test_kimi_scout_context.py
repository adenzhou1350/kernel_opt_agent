"""Offline public-context boundaries: no credentials, network, models or GPUs."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout_context as context

COMMIT = "a" * 40
TREE = "b" * 40
BLOB = "c" * 40
REPO = "owner/project"
API = f"https://api.github.com/repos/{REPO}"
RAW = f"https://raw.githubusercontent.com/{REPO}/{COMMIT}/src/kernel.py"


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.context = context.PublicContext(self.root, github_auth=True)
        self.calls = []
        self.metadata = {"private": False, "visibility": "public", "full_name": REPO}
        self.tree = {
            "tree": [
                {"path": "src/kernel.py", "type": "blob", "mode": "100644", "sha": BLOB}
            ],
            "truncated": False,
        }
        self.raw = "\n".join(f"value_{i} = {i}" for i in range(1, 301))
        self.routes = {}
        self.fetch = patch.object(context.scout, "fetch", side_effect=self.fake_fetch)
        self.fetch.start()
        self.addCleanup(self.fetch.stop)

    def fake_fetch(self, url, limit=1_000_000, github_auth=False):
        self.calls.append((url, limit, github_auth))
        if url == API:
            return json.dumps(self.metadata)
        if url in {API + "/commits/main", API + "/commits/" + COMMIT}:
            return json.dumps({"sha": COMMIT, "commit": {"tree": {"sha": TREE}}})
        if url == API + f"/git/trees/{TREE}?recursive=1":
            return json.dumps(self.tree)
        if url == RAW:
            return self.raw
        if url in self.routes:
            value = self.routes[url]
            return value if isinstance(value, str) else json.dumps(value)
        raise AssertionError(f"unexpected fetch: {url}")

    def issue_route(self, page=1):
        return (
            API
            + f"/issues?state=open&sort=updated&direction=desc&per_page=30&page={page}"
        )

    def test_private_metadata_blocks_context_even_with_configured_auth(self):
        self.metadata["private"] = True
        for operation in (
            lambda: self.context.snapshot(REPO),
            lambda: self.context.source(REPO, COMMIT, "src/kernel.py"),
            lambda: self.context.issue_page(REPO),
            lambda: self.context.issue_sources(REPO, 1),
            lambda: self.context.duplicate_sources(REPO, "candidate fix"),
        ):
            with self.assertRaisesRegex(ValueError, "non-public"):
                operation()
        self.assertTrue(all(url == API and auth is True for url, _, auth in self.calls))
        self.assertFalse(list((self.root / "public-cache").iterdir()))

    def test_visibility_must_be_explicitly_public_before_authenticated_context(self):
        for metadata in (
            {"private": False},
            {"private": False, "visibility": "internal"},
            {"visibility": "public"},
        ):
            self.metadata = metadata
            with self.assertRaisesRegex(ValueError, "non-public"):
                self.context.snapshot(REPO)
        self.assertTrue(all(url == API for url, _, _ in self.calls))

    def test_metadata_and_context_auth_remain_opt_in(self):
        unauthenticated = context.PublicContext(self.root)
        unauthenticated.source(REPO, COMMIT, "src/kernel.py")
        self.assertTrue(all(auth is False for _, _, auth in self.calls))

    def test_snapshot_is_bounded_and_skips_unsafe_paths_and_symlinks(self):
        for name in (
            "../escape",
            "/root",
            "a//b",
            "a/./b",
            "a\\b",
            "https://evil/x",
            "a\x00b",
        ):
            self.tree["tree"].append({"path": name, "type": "blob", "sha": BLOB})
        self.tree["tree"].append(
            {"path": "link", "type": "blob", "mode": "120000", "sha": BLOB}
        )
        self.tree["truncated"] = True
        snapshot = self.context.snapshot(REPO)
        self.assertEqual(snapshot["files"], ["src/kernel.py"])
        self.assertEqual(snapshot["blobs"], {"src/kernel.py": BLOB})
        self.assertEqual(snapshot["skipped_paths"], 8)
        self.assertTrue(snapshot["truncated"])
        self.assertLessEqual(
            sum(limit for _, limit, _ in self.calls),
            context.TREE_LIMIT + 2 * context.API_LIMIT,
        )
        self.assertEqual([auth for _, _, auth in self.calls], [True, True, True])

    def test_snapshot_cache_ttl_and_immutable_alias(self):
        with patch.object(context.time, "time", return_value=1000):
            first = self.context.snapshot(REPO)
            self.assertEqual(self.context.snapshot(REPO), first)
            self.assertEqual(self.context.snapshot(REPO, COMMIT), first)
        self.assertEqual(len(self.calls), 3)
        with patch.object(context.time, "time", return_value=1901):
            self.assertEqual(self.context.snapshot(REPO), first)
        self.assertEqual(len(self.calls), 6)
        with patch.object(context.time, "time", return_value=1902):
            self.assertEqual(self.context.snapshot(REPO, COMMIT), first)
        self.assertEqual(len(self.calls), 6)

    def test_scoped_tree_skips_large_unselected_subtrees_and_keeps_identity(self):
        subtree = "d" * 40
        top_url = API + f"/git/trees/{TREE}"
        sub_url = API + f"/git/trees/{subtree}?recursive=1"
        self.routes[top_url] = {
            "tree": [
                {"path": "src", "type": "tree", "mode": "040000", "sha": subtree},
                {"path": "vendor", "type": "tree", "mode": "040000", "sha": "e" * 40},
                {"path": "AGENTS.md", "type": "blob", "mode": "100644", "sha": BLOB},
            ]
        }
        self.routes[sub_url] = {
            "tree": [
                {"path": "kernel.py", "type": "blob", "mode": "100644", "sha": BLOB},
                {"path": "../escape.py", "type": "blob", "mode": "100644", "sha": BLOB},
            ]
        }
        scoped = context.PublicContext(self.root, True, {REPO: ["src"]})
        first = scoped.snapshot(REPO)
        self.assertEqual(first["files"], ["AGENTS.md", "src/kernel.py"])
        self.assertTrue(first["truncated"])
        self.assertEqual(first["tree_roots"], ["src"])
        self.assertEqual(scoped.snapshot(REPO, COMMIT), first)
        self.assertEqual(len(self.calls), 4)
        self.assertFalse(
            any(url.endswith(TREE + "?recursive=1") for url, _, _ in self.calls)
        )
        self.assertEqual(scoped.source(REPO, COMMIT, "src/kernel.py")["url"], RAW)
        # Unscoped cache does not alias a scoped snapshot.
        self.assertEqual(self.context.snapshot(REPO)["tree_roots"], [])

    def test_scoped_tree_rejects_unobserved_or_unsafe_roots(self):
        for roots in [["../src"], ["src/nested"], [], ["src"] * 9]:
            with self.assertRaises(ValueError):
                context.PublicContext(self.root, True, {REPO: roots})
        scoped = context.PublicContext(self.root, True, {REPO: ["src"]})
        self.routes[API + f"/git/trees/{TREE}"] = {"tree": []}
        with self.assertRaisesRegex(ValueError, "absent"):
            scoped.snapshot(REPO)
        self.routes[API + f"/git/trees/{TREE}"] = {"tree": [], "truncated": True}
        with self.assertRaisesRegex(ValueError, "truncated"):
            scoped.snapshot(REPO)

    def test_tree_metadata_stays_bounded(self):
        with patch.object(
            context.scout, "fetch", return_value="x" * (context.TREE_LIMIT + 1)
        ):
            with self.assertRaisesRegex(ValueError, "read budget"):
                self.context._read(API, context.TREE_LIMIT)

    def test_public_metadata_is_reused_for_fifteen_minutes(self):
        self.routes[self.issue_route()] = []
        with patch.object(context.time, "time", return_value=1000):
            self.context.issue_page(REPO)
        with patch.object(context.time, "time", return_value=1899):
            self.context.issue_page(REPO)
        self.assertEqual(sum(url == API for url, _, _ in self.calls), 1)
        with patch.object(context.time, "time", return_value=1900):
            self.context.issue_page(REPO)
        self.assertEqual(sum(url == API for url, _, _ in self.calls), 2)

    def test_new_context_rechecks_visibility_before_using_disk_cache(self):
        self.context.source(REPO, COMMIT, "src/kernel.py")
        self.metadata["private"] = True
        self.calls.clear()
        second = context.PublicContext(self.root, github_auth=True)
        with self.assertRaisesRegex(ValueError, "non-public"):
            second.source(REPO, COMMIT, "src/kernel.py")
        self.assertEqual(self.calls, [(API, context.API_LIMIT, True)])

    def test_raw_cache_survives_snapshot_expiry_and_visibility_is_rechecked(self):
        with patch.object(context.time, "time", return_value=1000):
            first = self.context.source(REPO, COMMIT, "src/kernel.py")
        with patch.object(context.time, "time", return_value=1901):
            second = context.PublicContext(self.root, github_auth=True)
            self.assertEqual(second.source(REPO, COMMIT, "src/kernel.py"), first)
        self.assertEqual(sum(url == RAW for url, _, _ in self.calls), 1)
        self.assertEqual(sum(url == API for url, _, _ in self.calls), 2)

    def test_input_paths_revisions_and_urls_fail_before_network(self):
        for path in (
            "../secret",
            "/secret",
            "a/../b",
            "a\\b",
            "a//b",
            "https://evil/x",
            "C:/file",
        ):
            with self.assertRaises(ValueError):
                self.context.source(REPO, COMMIT, path)
        for ref in ("../main", "/main", "main?x", "https://evil/x", "main#fragment"):
            with self.assertRaises(ValueError):
                self.context.snapshot(REPO, ref)
        for repo in ("../project", "owner/..", "https://evil/x", "owner/project?x"):
            with self.assertRaises(ValueError):
                self.context.snapshot(repo)
        self.assertEqual(self.calls, [])

    def test_nonexistent_path_and_mismatched_commit_never_fetch_raw(self):
        with self.assertRaisesRegex(ValueError, "absent"):
            self.context.source(REPO, COMMIT, "src/missing.py")
        self.assertFalse(
            any(url.startswith("https://raw.") for url, _, _ in self.calls)
        )
        other = "d" * 40
        self.routes[API + "/commits/" + other] = {"sha": COMMIT}
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.context.source(REPO, other, "src/kernel.py")

    def test_relevant_window_is_numbered_citable_and_cached(self):
        first = self.context.source(REPO, COMMIT, "src/kernel.py", hints="value_240")
        self.assertEqual(first["url"], RAW)
        self.assertIn("240: value_240 = 240", first["text"])
        self.assertLessEqual(len(first["text"].splitlines()), 120)
        self.assertEqual(first["total_lines"], 300)
        self.assertTrue(first["truncated"])
        self.assertIn(
            "value_240 = 240", context.scout.normalized_excerpt(first["text"])
        )
        second = self.context.source(
            REPO, COMMIT, "src/kernel.py", start=250, max_lines=20
        )
        self.assertTrue(second["text"].startswith("250: value_250 = 250"))
        self.assertEqual((second["start_line"], second["end_line"]), (250, 269))
        self.assertEqual(sum(url == RAW for url, _, _ in self.calls), 1)
        self.assertFalse(next(auth for url, _, auth in self.calls if url == RAW))

    def test_definition_hint_fetches_masked_store_not_later_kernel_call(self):
        lines = [f"other_{i} = {i}" for i in range(1, 251)]
        lines[29] = "def grpo_fwd_kernel():"
        lines[94] = "    tl.store(loss_ptr + M, 0.0)"
        lines[189] = "grpo_fwd_kernel[(row_len,)]()"
        self.raw = "\n".join(lines)
        evidence = self.context.source(
            REPO, COMMIT, "src/kernel.py", hints="def grpo_fwd_kernel(", max_lines=100
        )
        self.assertIn("30: def grpo_fwd_kernel():", evidence["text"])
        self.assertIn("95:     tl.store(loss_ptr + M, 0.0)", evidence["text"])
        self.assertNotIn("190: grpo_fwd_kernel[(row_len,)]()", evidence["text"])

    def test_exact_literal_targets_registration_not_earlier_module_record(self):
        lines = self.raw.splitlines()
        lines[9] = '"pack_01234567": {"arch": "sm_103a"},'
        lines[229] = '"quant:k8192_bf16": "pack_01234567",'
        self.raw = "\n".join(lines)
        evidence = self.context.source(
            REPO,
            COMMIT,
            "src/kernel.py",
            hints="pack_01234567",
            exact_hint=': "pack_01234567"',
            max_lines=80,
        )
        self.assertIn('230: "quant:k8192_bf16"', evidence["text"])
        self.assertNotIn('10: "pack_01234567"', evidence["text"])
        self.assertTrue(evidence["exact_hint_matched"])
        self.assertTrue(evidence["truncated"])

    def test_missing_or_clipped_literal_is_not_reported_as_matched(self):
        evidence = self.context.source(
            REPO, COMMIT, "src/kernel.py", hints="value_200", exact_hint="MISSING"
        )
        self.assertIn("200: value_200", evidence["text"])
        self.assertFalse(evidence["exact_hint_matched"])
        self.raw = "x" * 9500 + "HIDDEN"
        fresh = context.PublicContext(self.root / "long-line")
        evidence = fresh.source(REPO, COMMIT, "src/kernel.py", exact_hint="HIDDEN")
        self.assertTrue(evidence["truncated"])
        self.assertFalse(evidence["exact_hint_matched"])

    def test_invalid_exact_literal_is_rejected_before_fetch(self):
        for value in ("", "x" * 513, "a\nb", "a\x00b", 3):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.context.source(REPO, COMMIT, "src/kernel.py", exact_hint=value)
        with self.assertRaises(ValueError):
            self.context.source(REPO, COMMIT, "src/kernel.py", exact_hint="x", start=1)
        self.assertEqual(self.calls, [])

    def test_python_qualified_method_hint_prefers_definition_over_header_mentions(self):
        lines = [f"other_{i} = {i}" for i in range(1, 301)]
        lines[0] = "# Mxfp4LinearMethod process_weights_after_loading guard missing?"
        lines[149] = "class Mxfp4LinearMethod(LinearMethodBase):"
        lines[199] = "    def process_weights_after_loading(self, layer):"
        lines[219] = "        if any(fn is None for fn in kernels):"
        lines[220] = "            raise RuntimeError('kernels unavailable')"
        self.raw = "\n".join(lines)
        evidence = self.context.source(
            REPO,
            COMMIT,
            "src/kernel.py",
            hints="Check Mxfp4LinearMethod.process_weights_after_loading for a guard",
        )
        self.assertIn("200:     def process_weights_after_loading", evidence["text"])
        self.assertIn("221:             raise RuntimeError", evidence["text"])
        self.assertNotIn("1: # Mxfp4LinearMethod", evidence["text"])

    def test_typescript_constant_hint_prefers_declaration_over_comment_mentions(self):
        lines = [f"// unrelated line {i}" for i in range(1, 301)]
        lines[0] = "// SAFE_NETWORK_CODES CHROMIUM_NETWORK_MESSAGE_RE classify retries"
        lines[189] = "export const SAFE_NETWORK_CODES = new Set(['ECONNRESET']);"
        lines[194] = "const CHROMIUM_NETWORK_MESSAGE_RE = /net::ERR_CONNECTION_RESET/;"
        self.raw = "\n".join(lines)
        evidence = self.context.source(
            REPO,
            COMMIT,
            "src/kernel.py",
            hints="Inspect SAFE_NETWORK_CODES and CHROMIUM_NETWORK_MESSAGE_RE retry handling",
        )
        self.assertIn("190: export const SAFE_NETWORK_CODES", evidence["text"])
        self.assertIn("195: const CHROMIUM_NETWORK_MESSAGE_RE", evidence["text"])
        self.assertNotIn("1: // SAFE_NETWORK_CODES", evidence["text"])

    def test_exact_hint_and_explicit_start_override_named_definition(self):
        lines = [f"other_{i} = {i}" for i in range(1, 301)]
        lines[39] = "async def target_method():"
        lines[199] = "# requested explicit anchor"
        self.raw = "\n".join(lines)
        explicit = self.context.source(
            REPO,
            COMMIT,
            "src/kernel.py",
            hints="target_method",
            start=200,
            max_lines=20,
        )
        self.assertEqual(explicit["start_line"], 200)
        literal = self.context.source(
            REPO,
            COMMIT,
            "src/kernel.py",
            hints="target_method",
            exact_hint="requested explicit anchor",
            max_lines=20,
        )
        self.assertIn("200: # requested explicit anchor", literal["text"])
        self.assertNotIn("40: async def target_method", literal["text"])

    def test_unmatched_or_empty_definition_hint_keeps_keyword_fallback(self):
        for hints in ("value_240", ""):
            with self.subTest(hints=hints):
                ordinary = self.context.source(
                    REPO, COMMIT, "src/kernel.py", hints=hints
                )
                with patch.object(context, "_definition_line", return_value=None):
                    fallback = self.context.source(
                        REPO, COMMIT, "src/kernel.py", hints=hints
                    )
                self.assertEqual(ordinary, fallback)

    def test_source_window_bounds_and_truncation_are_explicit(self):
        for kwargs in (
            {"start": 0},
            {"start": True},
            {"max_lines": 161},
            {"max_lines": 0},
        ):
            with self.assertRaises(ValueError):
                self.context.source(REPO, COMMIT, "src/kernel.py", **kwargs)
        self.assertEqual(self.calls, [])
        with self.assertRaisesRegex(ValueError, "beyond end"):
            self.context.source(REPO, COMMIT, "src/kernel.py", start=301)
        self.raw = "x" * 9500
        fresh = context.PublicContext(self.root / "fresh")
        evidence = fresh.source(REPO, COMMIT, "src/kernel.py")
        self.assertEqual(len(evidence["text"]), 9000)
        self.assertTrue(evidence["truncated"])
        self.assertEqual(evidence["end_line"], 1)

    def test_member_path_punctuation_is_quoted_in_immutable_raw_url(self):
        path = "src/file ?#%.py"
        self.tree["tree"].append({"path": path, "type": "blob", "sha": BLOB})
        url = (
            f"https://raw.githubusercontent.com/{REPO}/{COMMIT}/src/file%20%3F%23%25.py"
        )
        self.routes[url] = "print('public data only')\n"
        source = self.context.source(REPO, COMMIT, path)
        self.assertEqual(source["url"], url)
        self.assertEqual(source["text"], "1: print('public data only')")
        self.assertFalse(source["truncated"])
        self.assertEqual(source["end_line"], 1)

    def test_oversized_mock_response_is_rejected(self):
        self.raw = "x" * (context.RAW_LIMIT + 1)
        with self.assertRaisesRegex(ValueError, "read budget"):
            self.context.source(REPO, COMMIT, "src/kernel.py")
        self.assertFalse(list((self.root / "public-cache").glob("raw-*")))

    def test_issue_page_excludes_prs_and_never_uses_returned_urls(self):
        self.routes[self.issue_route(2)] = [
            {
                "number": 12,
                "title": "bug",
                "body": "details",
                "labels": [
                    {"name": "clawsweeper:no-new-fix-pr"},
                    {"name": 9},
                    "untrusted label shape",
                ],
                "html_url": "https://evil/x",
                "comments_url": "https://evil/comments",
            },
            {"number": 13, "title": "PR", "pull_request": {}},
            {"number": 14, "title": "closed", "state": "closed"},
        ]
        items = self.context.issue_page(REPO, 2)
        self.assertEqual([item["number"] for item in items], [12])
        self.assertEqual(items[0]["html_url"], f"https://github.com/{REPO}/issues/12")
        self.assertEqual(items[0]["labels"], ["clawsweeper:no-new-fix-pr"])
        self.assertEqual(len(self.calls), 2)
        with self.assertRaises(ValueError):
            self.context.issue_page(REPO, "https://evil")

    def test_pr_only_issue_page_does_not_exhaust_later_issues(self):
        self.routes[self.issue_route(1)] = [
            {"number": number, "title": "PR", "pull_request": {}}
            for number in range(1, 31)
        ]
        self.routes[self.issue_route(2)] = [
            {"number": 31, "title": "real issue", "body": "details"}
        ]
        self.routes[self.issue_route(3)] = []

        first = self.context.issue_page(REPO, 1)
        self.assertIsInstance(first, list)
        self.assertEqual(first, [])
        self.assertFalse(first.exhausted)
        second = self.context.issue_page(REPO, 2)
        self.assertEqual([item["number"] for item in second], [31])
        self.assertFalse(second.exhausted)
        last = self.context.issue_page(REPO, 3)
        self.assertEqual(last, [])
        self.assertTrue(last.exhausted)

    def test_short_filtered_issue_page_is_not_raw_exhaustion(self):
        self.routes[self.issue_route()] = [
            {"number": 1, "title": "PR", "pull_request": {}},
            {"number": 2, "title": "closed", "state": "closed"},
        ]
        page = self.context.issue_page(REPO)
        self.assertEqual(page, [])
        self.assertFalse(page.exhausted)
        self.assertEqual(json.loads(json.dumps(page)), [])

    def test_issue_evidence_bounds_full_issue_and_three_comments(self):
        self.routes[API + "/issues/12"] = {
            "number": 12,
            "title": "bug",
            "body": "b" * 6000,
            "comments": 5,
            "comments_url": "https://evil/comments",
            "html_url": "https://evil/x",
        }
        self.routes[API + "/issues/12/comments?per_page=3&page=2"] = [
            {"id": i, "body": "c" * 1500, "html_url": "https://evil/x"}
            for i in range(1, 5)
        ]
        sources = self.context.issue_sources(REPO, 12)
        self.assertEqual(
            [len(item["text"]) for item in sources], [5000, 1200, 1200, 1200]
        )
        self.assertTrue(all(item["truncated"] for item in sources))
        self.assertTrue(sources[0]["comments_truncated"])
        self.assertTrue(sources[-1]["url"].endswith("/issues/12#issuecomment-3"))
        self.assertTrue(all("evil" not in url for url, _, _ in self.calls))

    def test_issue_sample_reads_later_decision_without_an_extra_get(self):
        self.routes[API + "/issues/12"] = {
            "number": 12, "title": "reported defect", "body": "report",
            "comments": 9,
        }
        route = API + "/issues/12/comments?per_page=3&page=3"
        self.routes[route] = [
            {"id": 7, "body": "This use is unsupported."},
            {"id": 8, "body": "I am implementing the documentation change."},
            {"id": 9, "body": "Please keep it scoped to model documentation."},
        ]
        sources = self.context.issue_sources(REPO, 12)
        self.assertIn("unsupported", sources[1]["text"])
        self.assertIn("implementing", sources[2]["text"])
        self.assertEqual(sources[0]["comments_page"], 3)
        self.assertTrue(sources[0]["comments_truncated"])
        self.assertEqual(
            sum("/comments?" in url for url, _, _ in self.calls), 1
        )
        self.assertIn((route, 300_000, True), self.calls)
        self.assertEqual(len(sources), 4)

    def test_issue_partial_last_page_does_not_repair_or_retry_the_sample(self):
        self.routes[API + "/issues/12"] = {
            "number": 12, "title": "report", "body": "", "comments": 7,
        }
        self.routes[API + "/issues/12/comments?per_page=3&page=3"] = [
            {"id": 7, "body": "Latest observed ownership."},
        ]
        sources = self.context.issue_sources(REPO, 12)
        self.assertEqual(len(sources), 2)
        self.assertTrue(sources[0]["comments_truncated"])
        self.assertEqual(sum("/comments?" in u for u, _, _ in self.calls), 1)

    def test_issue_zero_or_unknown_comment_counts_stay_explicit(self):
        self.routes[API + "/issues/12"] = {
            "number": 12, "title": "report", "body": "", "comments": 0,
        }
        sources = self.context.issue_sources(REPO, 12)
        self.assertFalse(sources[0]["comments_truncated"])
        self.assertFalse(any("/comments?" in u for u, _, _ in self.calls))
        self.routes[API + "/issues/13"] = {
            "number": 13, "title": "report", "body": "", "comments": True,
        }
        self.routes[API + "/issues/13/comments?per_page=3&page=1"] = []
        sources = self.context.issue_sources(REPO, 13)
        self.assertTrue(sources[0]["comments_truncated"])
        self.assertEqual(sources[0]["comments_page"], 1)

    def test_duplicate_query_cannot_escape_repo_or_claim_exhaustive_search(self):
        title = 'fix repo:secret/data OR https://evil.example "' + "x" * 1000
        self.routes = {}
        original = self.fake_fetch

        def search_fetch(url, limit=1_000_000, github_auth=False):
            if url.startswith("https://api.github.com/search/issues?"):
                self.calls.append((url, limit, github_auth))
                return json.dumps(
                    {
                        "items": [
                            {
                                "number": i,
                                "title": "existing fix",
                                "body": "details",
                                "pull_request": {},
                                "html_url": "https://evil/x",
                            }
                            for i in range(1, 8)
                        ],
                        "incomplete_results": False,
                    }
                )
            return original(url, limit, github_auth)

        with patch.object(context.scout, "fetch", side_effect=search_fetch):
            sources = self.context.duplicate_sources(REPO, title)
        self.assertEqual(len(sources), 5)
        self.assertTrue(all(item["search_exhaustive"] is False for item in sources))
        self.assertTrue(
            all(
                item["url"].startswith(f"https://github.com/{REPO}/pull/")
                for item in sources
            )
        )
        query = parse_qs(urlsplit(self.calls[-1][0]).query)
        self.assertEqual(query["per_page"], ["5"])
        self.assertTrue(query["q"][0].startswith(f"repo:{REPO} in:title,body "))
        self.assertNotIn("repo:secret", query["q"][0])
        self.assertLess(len(query["q"][0]), 500)


    def duplicate_search(self, title, responses):
        queries = []
        original = self.fake_fetch

        def search_fetch(url, limit=1_000_000, github_auth=False):
            if url.startswith("https://api.github.com/search/issues?"):
                query = parse_qs(urlsplit(url).query)
                queries.append(query)
                return json.dumps({"items": responses[len(queries) - 1]})
            return original(url, limit, github_auth)

        with patch.object(context.scout, "fetch", side_effect=search_fetch):
            sources = self.context.duplicate_sources(REPO, title)
        self.assertTrue(all(q["per_page"] == ["5"] for q in queries))
        self.assertLessEqual(len(queries), 2)
        self.assertLessEqual(len(sources), 5)
        return sources, [q["q"][0] for q in queries]

    def test_duplicate_fallback_preserves_title_modes(self):
        cases = (
            ("多物品分类打分(MIS融合)路径忽略temperature", '"MIS" "temperature"'),
            ("fix a score temperature bug", '"fix" "a"'),
            ("修复 温度 评分 路径", '"修复" "温度"'),
            ("修复 MIS 中 _multi_position_score_rows 温度", '"_multi_position_score_rows"'),
        )
        for title, fallback in cases:
            with self.subTest(title=title):
                sources, queries = self.duplicate_search(title, [[], []])
                self.assertEqual(sources, [])
                self.assertEqual(len(queries), 2)
                self.assertEqual(queries[-1], f"repo:{REPO} in:title,body {fallback}")

    def test_mixed_title_can_retrieve_differently_worded_fix(self):
        title = "JIT object 命名仅用源文件 basename，同名源文件产物互相覆盖"
        pr = {"number": 3, "title": "fix(jit): unify object naming", "pull_request": {}}
        sources, queries = self.duplicate_search(title, [[], [pr]])
        self.assertEqual(queries[-1], f'repo:{REPO} in:title,body "JIT" "object"')
        self.assertEqual(sources[0]["url"], f"https://github.com/{REPO}/pull/3")
        self.assertEqual(sources[0]["search_query"], queries[-1])
        self.assertFalse(sources[0]["search_exhaustive"])

    def test_duplicate_issue_only_sample_retains_report_and_searches_prs(self):
        issue = {"number": 1, "title": "flag_name report"}
        pr = {"number": 2, "title": "existing fix", "pull_request": {}}
        sources, queries = self.duplicate_search(issue["title"], [[issue], [pr]])
        self.assertEqual(queries[-1], f'repo:{REPO} is:pr in:title,body "flag_name"')
        self.assertEqual([s["is_pr"] for s in sources], [True, False])
        self.assertEqual(sources[1]["search_query"], queries[0])

    def test_duplicate_pr_hit_stops_and_identical_empty_query_is_not_repeated(self):
        pr = {"number": 2, "title": "existing fix", "pull_request": {}}
        sources, queries = self.duplicate_search("flag_name report", [[pr]])
        self.assertEqual(len(queries), 1)
        self.assertEqual(len(sources), 1)
        sources, queries = self.duplicate_search("flag_name", [[]])
        self.assertEqual(sources, [])
        self.assertEqual(len(queries), 1)

    def test_duplicate_pr_fallback_filters_foreign_issue_and_repeated_hits(self):
        issue = {"number": 1, "title": "report"}
        pr = {"number": 2, "title": "existing fix", "pull_request": {}}
        foreign = dict(pr, repository_url="https://api.github.com/repos/other/repo")
        sources, queries = self.duplicate_search(
            "flag_name report", [[issue], [foreign, issue, pr, pr]]
        )
        self.assertEqual(len(queries), 2)
        self.assertEqual([s["url"].rsplit("/", 1)[-1] for s in sources], ["2", "1"])
        sources, queries = self.duplicate_search("flag_name report", [[foreign], []])
        self.assertEqual(sources, [])
        self.assertEqual(len(queries), 2)


if __name__ == "__main__":
    unittest.main()
