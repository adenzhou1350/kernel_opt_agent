"""Indexed-path discovery controls; no external network, credentials or model."""

import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout as scout
import kimi_scout_context as context
import kimi_scout_research as research
from scout_requested_definition import (
    cached_reference_binding_symbol, requested_code_search_symbols,
)

REPO = "owner/project"
COMMIT = "a" * 40
PATH = "src/cuda/transform/lower_ldg_stg.cc"
SYMBOL = "LowerToSTGPredicated"


def item(path, repo=REPO, private=False):
    return {
        "path": path,
        "repository": {"full_name": repo, "private": private},
        "url": "https://evil.invalid/not-a-source",
    }


class CodeSearchTests(unittest.TestCase):
    def test_explicit_instance_binding_is_a_hint_not_an_invented_target(self):
        path = "src/engine.py"
        packet = {
            "repo": REPO,
            "sources": [
                {"url": f"https://raw.githubusercontent.com/{REPO}/{COMMIT}/{path}"}
            ],
        }
        snapshot = {"commit": COMMIT, "files": [path]}
        analysis = {
            "next_check": "references(EngineFactory) references(_SHARED_ENGINE)"
        }
        raw = "class EngineFactory:\n    pass\n_SHARED_ENGINE = EngineFactory()\n"
        self.assertEqual(
            cached_reference_binding_symbol(packet, snapshot, analysis, lambda *a: raw),
            "_SHARED_ENGINE",
        )
        for extra in (
            "_SHARED_ENGINE = None\n",
            "EngineFactory = other\n",
            "from elsewhere import _SHARED_ENGINE\n",
            "def EngineFactory(): pass\n",
        ):
            self.assertIsNone(
                cached_reference_binding_symbol(
                    packet, snapshot, analysis, lambda *a: raw + extra
                )
            )
        for changed in ({**snapshot, "commit": "b" * 40}, {**snapshot, "files": []}):
            self.assertIsNone(
                cached_reference_binding_symbol(
                    packet, changed, analysis, lambda *a: raw
                )
            )
        self.assertIsNone(
            cached_reference_binding_symbol(
                packet,
                snapshot,
                {"next_check": "definition(EngineFactory) references(_SHARED_ENGINE)"},
                lambda *a: raw,
            )
        )
        for invalid in ("class Broken(:", None, "x" * 100001):
            self.assertIsNone(
                cached_reference_binding_symbol(
                    packet, snapshot, analysis, lambda *a: invalid
                )
            )

    def test_search_keys_keep_unqualified_targets_and_fold_one_qualified_owner(self):
        cases = {
            "references(build_cache) definition(load_cache)": [
                "build_cache",
                "load_cache",
            ],
            "definition ( AgentRegistry.register )": ["AgentRegistry"],
            "definition(AgentRegistry.register) definition(AgentRegistry.resolve)": [
                "AgentRegistry"
            ],
            "definition(AgentRegistry.register) definition(AgentRegistry.register)": [
                "AgentRegistry"
            ],
        }
        for request, expected in cases.items():
            with self.subTest(request=request):
                self.assertEqual(requested_code_search_symbols(request), expected)

    def test_qualified_keys_abstain_on_receiver_guessing_and_ambiguous_requests(self):
        for request in (
            'definition(registry.register)',
            'references(AgentRegistry.register)',
            'definition(AgentRegistry.register) definition(OtherRegistry.resolve)',
            'definition(AgentRegistry.register) definition(resolve)',
            'definition(AgentRegistry..register)',
            'definition(AgentRegistry.register.more)',
            'definition(AgentRegistry.register) definition(AgentRegistry.resolve) definition(AgentRegistry.list)',
            'definition(AgentRegistry.register repo:foreign/repo)',
            'definition(https://other.invalid/register)',
            'definition(AgentRegistry.register) definition(bad target)',
            'x' * 2000 + ' definition(AgentRegistry.register)',
        ):
            with self.subTest(request=request):
                self.assertEqual(requested_code_search_symbols(request), [])
        self.assertEqual(requested_code_search_symbols(None), [])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.reader = context.PublicContext(Path(self.temp.name))
        self.snapshot = {"commit": COMMIT, "files": [PATH, "tests/lower.test.cc"]}
        self.public = patch.object(self.reader, "_public", return_value=REPO)
        self.public.start()
        self.addCleanup(self.public.stop)

    def search(self, response, symbol=SYMBOL):
        with patch.object(self.reader, "_json", return_value=response) as api:
            result = self.reader.code_search_paths(REPO, self.snapshot, symbol)
        return result, api

    def test_query_is_literal_scoped_and_bounded_with_no_returned_url_use(self):
        result, api = self.search({"items": [item(PATH)]})
        self.assertEqual(result, [PATH])
        url = api.call_args.args[0]
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(query["q"], [f'repo:{REPO} in:file "{SYMBOL}"'])
        self.assertEqual(query["per_page"], ["5"])
        self.assertEqual(api.call_args.kwargs["limit"], 250000)

    def test_outside_tree_foreign_private_unsafe_and_duplicates_rejected(self):
        response = {
            "items": [
                item("src/absent.cc"),
                item(PATH, "other/repo"),
                item(PATH, private=True),
                item("../escape.cc"),
                item(PATH),
            ]
        }
        result, _ = self.search(response)
        self.assertEqual(result, [PATH])

    def test_tests_are_hints_not_preferred_implementation(self):
        result, _ = self.search({"items": [item("tests/lower.test.cc"), item(PATH)]})
        self.assertEqual(result, [PATH, "tests/lower.test.cc"])

    def test_unseen_implementation_precedes_observed_definition_without_extra_query(
        self,
    ):
        caller, definition, test = (
            "backend/service/git.go",
            "util/git/git.go",
            "util/git/git_test.go",
        )
        self.snapshot["files"] = [definition, PATH, caller, test]
        response = {"items": [item(definition), item(PATH), item(test), item(caller)]}
        with patch.object(self.reader, "_json", return_value=response) as api:
            result = self.reader.code_search_paths(
                REPO, self.snapshot, SYMBOL, deprioritize=[definition, PATH]
            )
        self.assertEqual(result, [caller, definition])
        self.assertEqual(api.call_count, 1)
        with patch.object(self.reader, "_json") as api:
            result = self.reader.code_search_paths(
                REPO, self.snapshot, SYMBOL, deprioritize=[caller, definition]
            )
        self.assertEqual(result, [PATH, definition])
        api.assert_not_called()

    def test_observed_sources_are_deprioritized_not_removed(self):
        with patch.object(self.reader, "_json", return_value={"items": [item(PATH)]}):
            self.assertEqual(
                self.reader.code_search_paths(
                    REPO, self.snapshot, SYMBOL, deprioritize=[PATH]
                ),
                [PATH],
            )

    def test_cache_reuses_query_but_still_intersects_exact_tree(self):
        _, api = self.search({"items": [item(PATH)]})
        self.assertEqual(api.call_count, 1)
        self.snapshot["files"] = []
        with patch.object(self.reader, "_json") as api:
            self.assertEqual(
                self.reader.code_search_paths(REPO, self.snapshot, SYMBOL), []
            )
        api.assert_not_called()

    def test_cache_revision_is_not_default_branch_identity(self):
        self.search({"items": [item(PATH)]})
        self.snapshot["commit"] = "b" * 40
        _, api = self.search({"items": [item(PATH)]})
        self.assertEqual(api.call_count, 1)

    def test_untrusted_query_and_response_fail_without_fallback(self):
        for symbol in (
            None,
            True,
            "x",
            'target" repo:evil/repo',
            "../target",
            "a" * 129,
        ):
            with self.subTest(symbol=symbol), self.assertRaises(ValueError):
                self.search({"items": []}, symbol)
        for response in ({}, {"items": None}, []):
            with self.assertRaises(ValueError):
                self.search(response)

    def test_failed_public_visibility_does_not_search(self):
        with (
            patch.object(self.reader, "_public", side_effect=ValueError("private")),
            patch.object(self.reader, "_json") as api,
        ):
            with self.assertRaises(ValueError):
                self.reader.code_search_paths(REPO, self.snapshot, SYMBOL)
        api.assert_not_called()

    def test_c_family_tree_members_are_not_silently_excluded(self):
        for suffix in (".cc", ".c", ".cxx"):
            path = "src/lower" + suffix
            self.assertEqual(research.relevant_paths({"files": [path]}, path), [path])


class FollowupCodeSearchTests(unittest.TestCase):
    def run_followup(
        self,
        enabled=True,
        drift=False,
        search_error=False,
        observed_source=False,
        request_text=None,
        decision="needs_context",
    ):
        raw = "// filler\n" * 120 + f"void {SYMBOL}() {{}}\n"
        raw += "// filler\n" * 100 + "void LowerToLDGPredicated() {}\n"
        if drift:
            raw = "// unrelated source at frozen revision\n" * 250

        class Reader(context.PublicContext):
            def __init__(self, root):
                super().__init__(root)
                self.searches, self.reads = [], []

            def _public(self, repo):
                return repo

            def snapshot(self, repo, ref="main"):
                paths = (
                    [PATH, "backend/caller.go", "src/second_definition.go"]
                    if observed_source
                    else [PATH]
                )
                return {
                    "commit": COMMIT,
                    "files": paths,
                    "blobs": {p: "b" * 40 for p in paths},
                }

            def _json(self, url, **kwargs):
                self.searches.append(url)
                if search_error:
                    raise OSError("offline")
                paths = (
                    [PATH, "backend/caller.go", "src/second_definition.go"]
                    if observed_source
                    else [PATH]
                )
                return {"items": [item(p) for p in paths]}

            def _read(self, url, *args, **kwargs):
                self.reads.append(url)
                return raw

            def issue_sources(self, repo, number):
                return [
                    {
                        "url": f"https://github.com/{repo}/issues/{number}",
                        "text": "Existing report",
                    }
                ]

            def duplicate_sources(self, *args):
                return []

            def issue_pr_context(self, *args):
                return {"sources": [], "status": "PARTIAL_TIMELINE", "search_exhaustive": False}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scout.initialize(root)
            config = root / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "objective": "Offline pinned context",
                        "queue_target": 4,
                        "repos": [
                            {
                                "repo": REPO,
                                "source_prefixes": ["src/"],
                                "followup_code_search": enabled,
                                "question": "Check contracts",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            reader = Reader(root)
            with patch.object(
                research, "lesson_suggestions", return_value={"status": "NO_MATCH"}
            ):
                producer = research.ResearchProducer(root, config, context=reader)
                producer.lessons = []
                spec = producer.config["repos"][0]
                original = [
                    {
                        "url": f"https://github.com/{REPO}/issues/42",
                        "text": "Existing report",
                    }
                ]
                if observed_source:
                    original = [
                        {
                            "url": f"https://raw.githubusercontent.com/{REPO}/{COMMIT}/{PATH}",
                            "text": f"definition {SYMBOL}",
                            "start_line": 1,
                            "end_line": 1,
                            "total_lines": 250,
                            "truncated": True,
                        }
                    ]
                producer.emit("old", spec, original, "issue_triage")
                with scout.connect(root) as db:
                    db.execute(
                        "UPDATE jobs SET state=?,finished=?,result=?",
                        (
                            "REVIEW" if decision == "lead" else "NEEDS_CONTEXT",
                            time.time(),
                            scout.dumps(
                                {
                                    "analysis": {
                                        "title": "Missing predicate implementation",
                                        "hypothesis": "Unverified predicate contract",
                                        "decision": decision,
                                        "next_check": request_text
                                        or f"Inspect references({SYMBOL}) and references(LowerToLDGPredicated)",
                                        "evidence": [],
                                    }
                                }
                            ),
                        ),
                    )
                progress = {}
                producer.followup(spec, progress)
                with scout.connect(root) as db:
                    rows = [
                        json.loads(row[0])
                        for row in db.execute("SELECT packet FROM jobs")
                    ]
            followups = [p for p in rows if "untrusted_prior_analysis" in p]
            return reader.searches, reader.reads, followups, progress

    def test_explicit_reference_request_is_honored_for_unvalidated_lead(self):
        searches, reads, packets, progress = self.run_followup(decision="lead")
        self.assertEqual(len(searches), 1)
        self.assertEqual(progress["code_search_requests"], 1)
        self.assertLessEqual(len(reads), 2)
        self.assertTrue(any("code_search_hint" in s for p in packets for s in p["sources"]))

    def test_lead_label_alone_does_not_enable_definition_or_prose_search(self):
        for request in (f"definition({SYMBOL})", f"Inspect caller of {SYMBOL}"):
            with self.subTest(request=request):
                searches, _, _, _ = self.run_followup(decision="lead", request_text=request)
                self.assertEqual(searches, [])

    def test_emitted_packet_contains_only_pinned_literal_windows_two_read_cap(self):
        searches, reads, packets, _ = self.run_followup()
        self.assertEqual(len(searches), 1)
        # Second source() uses the first read's pinned raw cache.
        self.assertEqual(len(reads), 1)
        self.assertEqual(len(packets), 1)
        evidence = [s for s in packets[0]["sources"] if "code_search_hint" in s]
        self.assertEqual(len(evidence), 2)
        for source in evidence:
            self.assertIn(f"/{COMMIT}/{PATH}", source["url"])
            self.assertIn(source["code_search_hint"]["symbol"], source["text"])
            self.assertLessEqual(source["end_line"] - source["start_line"] + 1, 80)
            self.assertNotIn("requested_definition_complete", source)
        self.assertLessEqual(
            len((scout.SYSTEM + scout.dumps(packets[0])).encode()),
            scout.MAX_INPUT_BYTES,
        )

    def test_missing_definition_uses_same_pinned_search_and_read_budget(self):
        searches, reads, packets, progress = self.run_followup(
            request_text=f"Inspect definition({SYMBOL})"
        )
        self.assertEqual(len(searches), 1)
        self.assertEqual(len(reads), 1)
        self.assertEqual(progress["code_search_requests"], 1)
        evidence = [s for s in packets[0]["sources"] if "code_search_hint" in s]
        self.assertEqual(len(evidence), 1)
        self.assertIn(f"/{COMMIT}/{PATH}", evidence[0]["url"])
        self.assertIn(SYMBOL, evidence[0]["text"])
        self.assertLessEqual(
            evidence[0]["end_line"] - evidence[0]["start_line"] + 1, 80
        )

    def test_definition_cannot_supply_a_url_or_an_arbitrary_search_query(self):
        for request in (
            "definition(https://other.invalid/evil.py)",
            "definition(Foo.method)",
            "definition(symbol repo:other/repo)",
        ):
            with self.subTest(request=request):
                searches, _, _, _ = self.run_followup(request_text=request)
                self.assertEqual(searches, [])

    def test_qualified_same_owner_definitions_share_one_bounded_search(self):
        searches, reads, packets, progress = self.run_followup(
            request_text=f"definition({SYMBOL}.register) definition({SYMBOL}.resolve)"
        )
        self.assertEqual(len(searches), 1)
        self.assertEqual(len(reads), 1)
        self.assertEqual(progress["code_search_requests"], 1)
        evidence = [s for s in packets[0]["sources"] if "code_search_hint" in s]
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["code_search_hint"]["symbol"], SYMBOL)
        self.assertIn(f"/{COMMIT}/{PATH}", evidence[0]["url"])
        self.assertLessEqual(evidence[0]["end_line"] - evidence[0]["start_line"] + 1, 80)
        self.assertNotIn("requested_definition_complete", evidence[0])

    def test_qualified_search_retains_opt_in_and_literal_drift_checks(self):
        request = f"definition({SYMBOL}.register)"
        searches, reads, _, _ = self.run_followup(enabled=False, request_text=request)
        self.assertEqual((searches, reads), ([], []))
        searches, _, packets, _ = self.run_followup(drift=True, request_text=request)
        self.assertEqual(len(searches), 1)
        self.assertFalse(any("code_search_hint" in s for p in packets for s in p["sources"]))

    def test_definition_retains_opt_in_and_pinned_literal_drift_rejection(self):
        request = f"definition({SYMBOL})"
        searches, reads, _, _ = self.run_followup(enabled=False, request_text=request)
        self.assertEqual(searches, [])
        self.assertEqual(reads, [])
        searches, _, packets, _ = self.run_followup(drift=True, request_text=request)
        self.assertEqual(len(searches), 1)
        self.assertFalse(
            any(
                "code_search_hint" in s for packet in packets for s in packet["sources"]
            )
        )

    def test_option_off_keeps_no_search_default(self):
        searches, reads, packets, _ = self.run_followup(enabled=False)
        self.assertEqual(searches, [])
        self.assertEqual(reads, [])
        self.assertEqual(packets, [])

    def test_source_followup_acquires_unseen_paths_instead_of_repeating_definition(
        self,
    ):
        searches, reads, packets, progress = self.run_followup(observed_source=True)
        self.assertEqual(len(searches), 1)
        self.assertEqual(progress["code_search_requests"], 1)
        self.assertEqual(len(reads), 2)
        self.assertEqual(len(packets), 1)
        evidence = [s for s in packets[0]["sources"] if "code_search_hint" in s]
        self.assertEqual(
            [s["url"].rsplit(f"/{COMMIT}/", 1)[-1] for s in evidence],
            ["backend/caller.go", "src/second_definition.go"],
        )
        self.assertTrue(all(s["end_line"] - s["start_line"] < 80 for s in evidence))

    def test_index_revision_drift_is_not_added_as_claimed_context(self):
        searches, reads, packets, _ = self.run_followup(drift=True)
        self.assertEqual(len(searches), 1)
        self.assertEqual(len(reads), 1)
        self.assertEqual(packets, [])

    def test_optional_search_failure_is_bounded_and_observable(self):
        searches, reads, packets, progress = self.run_followup(search_error=True)
        self.assertEqual(len(searches), 1)
        self.assertEqual(reads, [])
        self.assertEqual(packets, [])
        self.assertEqual(progress["code_search_error"], "OSError")


class LoopbackReferenceTests(unittest.TestCase):
    def test_real_client_reaches_pinned_caller_with_one_query_and_no_credentials(self):
        self.run_wire_case(200)

    def test_real_client_retains_forbidden_search_without_retry_or_absence_claim(self):
        self.run_wire_case(403)

    def run_wire_case(self, search_status):
        primary, caller = "src/engine.py", "src/project.py"
        raw = "class EngineFactory:\n    pass\n_SHARED_ENGINE = EngineFactory()\n"
        consumer = (
            "from .engine import _SHARED_ENGINE\n"
            "def project(batch):\n    if 1 <= batch:\n        return _SHARED_ENGINE(batch)\n"
        )
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append((self.path, dict(self.headers)))
                path = urlsplit(self.path).path
                code = 200
                if path == f"/api/repos/{REPO}":
                    body = json.dumps(
                        {"full_name": REPO, "private": False, "visibility": "public"}
                    )
                elif path == "/api/search/code":
                    code = search_status
                    body = (
                        json.dumps(
                            {
                                "items": [item(caller), item(primary)],
                                "total_count": 2,
                                "incomplete_results": False,
                            }
                        )
                        if code == 200
                        else '{"message":"Forbidden"}'
                    )
                elif path == f"/raw/{REPO}/{COMMIT}/{primary}":
                    body = raw
                elif path == f"/raw/{REPO}/{COMMIT}/{caller}":
                    body = consumer
                else:
                    code, body = 501, "unmodeled endpoint"
                payload = body.encode()
                self.send_response(code)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        real_build = urllib.request.build_opener

        class RouteHTTPS(urllib.request.HTTPSHandler):
            def https_open(self, request):
                url = urlsplit(request.full_url)
                prefix = {
                    "api.github.com": "/api",
                    "raw.githubusercontent.com": "/raw",
                }[url.netloc]
                target = f"http://127.0.0.1:{server.server_port}{prefix}{url.path}"
                if url.query:
                    target += "?" + url.query
                try:
                    return self.parent.open(
                        urllib.request.Request(target, headers=dict(request.headers))
                    )
                except urllib.error.HTTPError as error:
                    # This test transport nested another opener; close its error
                    # response while preserving the real 403 exception to Scout.
                    error.close()
                    raise

        class Reader(context.PublicContext):
            def snapshot(self, repo, ref="main"):
                return {
                    "commit": COMMIT,
                    "files": [primary, caller],
                    "blobs": {primary: "b" * 40, caller: "c" * 40},
                }

            def duplicate_sources(self, *args):
                return []

        try:
            with (
                tempfile.TemporaryDirectory() as directory,
                patch.object(
                    urllib.request,
                    "build_opener",
                    side_effect=lambda *h: real_build(
                        urllib.request.ProxyHandler({}), RouteHTTPS(), *h
                    ),
                ),
            ):
                root = Path(directory)
                scout.initialize(root)
                config = root / "config.json"
                config.write_text(
                    json.dumps(
                        {
                            "objective": "Loopback contract",
                            "queue_target": 4,
                            "repos": [
                                {
                                    "repo": REPO,
                                    "source_prefixes": ["src/"],
                                    "followup_code_search": True,
                                    "question": "Read caller",
                                }
                            ],
                        }
                    )
                )
                reader = Reader(root)
                # Same already-acquired primary cache in both routing versions.
                source = reader.source(REPO, COMMIT, primary)
                producer = research.ResearchProducer(root, config, context=reader)
                spec = producer.config["repos"][0]
                producer.emit("known-component", spec, [source], "source_audit")
                with scout.connect(root) as db:
                    db.execute(
                        "UPDATE jobs SET state='REVIEW',finished=?,result=?",
                        (
                            time.time(),
                            scout.dumps(
                                {
                                    "analysis": {
                                        "title": "Internal boundary needs caller",
                                        "decision": "lead",
                                        "next_check": "references(EngineFactory) references(_SHARED_ENGINE)",
                                        "hypothesis": "Zero input may be unreachable",
                                        "evidence": [],
                                    }
                                }
                            ),
                        ),
                    )
                progress = {}
                producer.followup(spec, progress)
                with scout.connect(root) as db:
                    packets = [
                        json.loads(r[0]) for r in db.execute("SELECT packet FROM jobs")
                    ]
                searches = [p for p, _ in requests if p.startswith("/api/search/code?")]
                self.assertEqual(len(searches), 1)
                self.assertEqual(
                    parse_qs(urlsplit(searches[0]).query)["q"],
                    [f'repo:{REPO} in:file "_SHARED_ENGINE"'],
                )
                self.assertEqual(progress["code_search_requests"], 1)
                self.assertFalse(any("Authorization" in h for _, h in requests))
                evidence = [
                    s for p in packets for s in p["sources"] if "code_search_hint" in s
                ]
                if search_status == 200:
                    chosen = [s for s in evidence if s["url"].endswith(caller)]
                    self.assertTrue(chosen)
                    self.assertIn("if 1 <= batch", chosen[0]["text"])
                    self.assertTrue(all(f"/{COMMIT}/" in s["url"] for s in evidence))
                    self.assertLessEqual(
                        sum(p.startswith("/raw/") for p, _ in requests), 3
                    )
                else:
                    self.assertEqual(progress["code_search_error"], "HTTPError")
                    self.assertEqual(evidence, [])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
