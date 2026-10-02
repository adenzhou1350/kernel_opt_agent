"""Offline indexed-path discovery and pinned consumer tests; no network/model."""

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout as scout
import kimi_scout_context as context
import kimi_scout_research as research

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
    def run_followup(self, enabled=True, drift=False, search_error=False):
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
                return {"commit": COMMIT, "files": [PATH], "blobs": {PATH: "b" * 40}}

            def _json(self, url, **kwargs):
                self.searches.append(url)
                if search_error:
                    raise OSError("offline")
                return {"items": [item(PATH)]}

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
                producer.emit("old", spec, original, "issue_triage")
                with scout.connect(root) as db:
                    db.execute(
                        "UPDATE jobs SET state='NEEDS_CONTEXT',finished=?,result=?",
                        (
                            time.time(),
                            scout.dumps(
                                {
                                    "analysis": {
                                        "title": "Missing predicate implementation",
                                        "hypothesis": "Unverified predicate contract",
                                        "decision": "needs_context",
                                        "next_check": f"Inspect references({SYMBOL}) and references(LowerToLDGPredicated)",
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

    def test_option_off_keeps_no_search_default(self):
        searches, reads, packets, _ = self.run_followup(enabled=False)
        self.assertEqual(searches, [])
        self.assertEqual(reads, [])
        self.assertEqual(packets, [])

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


if __name__ == "__main__":
    unittest.main()
