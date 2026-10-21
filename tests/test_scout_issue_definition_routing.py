"""Issue names cannot make a same-basename sibling the target declaration."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout as scout
import kimi_scout_context as context
import kimi_scout_research as research
from scout_requested_definition import issue_definition_request


class IssueDefinitionRoutingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.paths = ["src/aux/routed_experts.py", "src/model/routed_experts.py"]
        self.bodies = {
            self.paths[
                0
            ]: "class RoutedExpertBuffer:\n    def capture(self):\n        pass\n",
            self.paths[
                1
            ]: "class RoutedExperts:\n    def load_weights(self):\n        return 42\n",
        }
        self.snapshot = {
            "commit": "a" * 40,
            "files": self.paths,
            "blobs": {
                p: hashlib.sha1(
                    b"blob " + str(len(b.encode())).encode() + b"\0" + b.encode()
                ).hexdigest()
                for p, b in self.bodies.items()
            },
        }
        self.ctx = context.PublicContext(self.root)
        self.config = self.root / "config.json"
        self.config.write_text(
            json.dumps(
                {
                    "objective": "CPU source selection",
                    "queue_target": 4,
                    "repos": [
                        {
                            "repo": "a/b",
                            "source_prefixes": ["src/"],
                            "question": "Boundary",
                        }
                    ],
                }
            )
        )
        scout.initialize(self.root)
        self.producer = research.ResearchProducer(
            self.root, self.config, context=self.ctx
        )
        self.spec = self.producer.config["repos"][0]
        self.hints = "Report: `RoutedExperts.load_weights` rebuilds mappings"

    def select(self, hints=None):
        def read(repo, blob, url):
            return self.bodies[
                next(p for p in self.paths if url.endswith("/" + p))
            ], "fixture"

        with (
            patch.object(self.ctx, "snapshot", return_value=self.snapshot),
            patch.object(self.ctx, "_source_text", side_effect=read) as fetch,
        ):
            result = self.producer.issue_source(
                self.spec, self.snapshot, self.paths, hints or self.hints
            )
        return result, fetch.call_count

    def test_native_reader_selects_exact_owner_and_keeps_one_bounded_source(self):
        result, calls = self.select()
        self.assertEqual(calls, 2)
        self.assertTrue(result["url"].endswith("/" + self.paths[1]))
        self.assertEqual(result["requested_definition"]["name"], "load_weights")
        self.assertIn("def load_weights", result["text"])
        self.assertLessEqual(result["end_line"] - result["start_line"] + 1, 120)
        self.assertTrue(result["requested_definition_complete"])

    def test_issue_packet_emits_only_the_selected_pinned_source(self):
        item = {
            "number": 42,
            "title": self.hints,
            "body": "",
            "updated_at": "first",
            "html_url": "https://github.com/a/b/issues/42",
        }

        def read(repo, blob, url):
            return self.bodies[
                next(p for p in self.paths if url.endswith("/" + p))
            ], "fixture"

        with (
            patch.object(self.ctx, "snapshot", return_value=self.snapshot),
            patch.object(self.ctx, "issue_page", return_value=[item]),
            patch.object(
                self.ctx, "issue_linked_pr_context", return_value={"sources": []}
            ),
            patch.object(self.ctx, "_source_text", side_effect=read) as fetch,
        ):
            self.assertTrue(self.producer.issue(self.spec, {}))
        with scout.connect(self.root) as db:
            packet = json.loads(db.execute("SELECT packet FROM jobs").fetchone()[0])
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(len(packet["sources"]), 2)
        self.assertTrue(packet["sources"][1]["url"].endswith("/" + self.paths[1]))
        self.assertLessEqual(
            len((scout.SYSTEM + scout.dumps(packet)).encode()), scout.MAX_INPUT_BYTES
        )

    def test_explicit_path_is_not_displaced(self):
        result, calls = self.select(self.hints + " inspect " + self.paths[0])
        self.assertTrue(result["url"].endswith("/" + self.paths[0]))
        self.assertEqual(calls, 1)

    def test_first_declaration_needs_no_extra_read(self):
        self.bodies[self.paths[0]] = self.bodies[self.paths[1]]
        result, calls = self.select()
        self.assertTrue(result["url"].endswith("/" + self.paths[0]))
        self.assertEqual(calls, 1)

    def test_absent_or_ambiguous_declarations_retain_fallback(self):
        for raw in ["class Other: pass\n", self.bodies[self.paths[1]] * 2]:
            with self.subTest(raw=raw):
                self.bodies[self.paths[1]] = raw
                result, calls = self.select()
                self.assertTrue(result["url"].endswith("/" + self.paths[0]))
                self.assertLessEqual(calls, 2)
                # Do not reuse a different trial's cache.
                for cached in self.ctx.cache.glob("raw-*.json"):
                    cached.unlink()

    def test_missing_alternative_or_multiple_siblings_never_expands_search(self):
        for paths in [
            self.paths[:1],
            self.paths + ["src/third/routed_experts.py"],
            [self.paths[0], "src/model/other.py"],
        ]:
            with patch.object(
                self.ctx, "source", return_value={"url": "first"}
            ) as read:
                self.assertEqual(
                    self.producer.issue_source(
                        self.spec, self.snapshot, paths, self.hints
                    ),
                    {"url": "first"},
                )
            self.assertEqual(read.call_count, 1)

    def test_optional_unreadable_source_keeps_first_but_denial_propagates(self):
        for error, raises in [
            (ValueError("source exceeds read budget"), False),
            (PermissionError("denied"), True),
        ]:
            with patch.object(
                self.ctx, "source", side_effect=[{"url": "first"}, error]
            ) as read:
                if raises:
                    with self.assertRaises(PermissionError):
                        self.producer.issue_source(
                            self.spec, self.snapshot, self.paths, self.hints
                        )
                else:
                    self.assertEqual(
                        self.producer.issue_source(
                            self.spec, self.snapshot, self.paths, self.hints
                        ),
                        {"url": "first"},
                    )
            self.assertEqual(read.call_count, 2)

    def test_literal_and_budget_bounds(self):
        for hints in [
            "RoutedExperts.load_weights",
            "`package.RoutedExperts.load_weights`",
            "`RoutedExperts.load_weights` `OtherClass.target_method`",
            "```RoutedExperts.load_weights```",
            "`https://evil.invalid/Class.method`",
            "x" * 2000 + self.hints,
            "definition(RoutedExperts.load_weights)",
        ]:
            with self.subTest(hints=hints[:100]):
                self.assertIsNone(issue_definition_request(hints))
        self.assertEqual(
            issue_definition_request(self.hints * 2),
            "definition(RoutedExperts.load_weights)",
        )


if __name__ == "__main__":
    unittest.main()
