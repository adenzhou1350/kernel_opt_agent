"""Offline bounded followup regression: model hints never define fetch targets."""

import sys
import json
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from kimi_scout_research import continuation_request
import kimi_scout as scout
from kimi_scout_research import ResearchProducer


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.sha = "a" * 40
        self.snapshot = {"commit": self.sha, "files": ["src/worker.ts"]}
        self.packet = {
            "repo": "a/b",
            "sources": [
                {
                    "url": f"https://raw.githubusercontent.com/a/b/{self.sha}/src/worker.ts",
                    "start_line": 241,
                    "end_line": 360,
                    "total_lines": 537,
                    "truncated": True,
                }
            ],
        }

    def test_explicit_tail_replaces_one_window_with_overlap(self):
        for hint in ("查看行360之后的重试分支", "Read after line 360 for cleanup"):
            with self.subTest(hint=hint):
                self.assertEqual(
                    continuation_request(
                        self.packet, self.snapshot, {"next_check": hint}
                    ),
                    {"path": "src/worker.ts", "start": 341, "max_lines": 120},
                )

    def test_arbitrary_boundary_or_url_cannot_select_source(self):
        for hint in (
            "Read after line 400",
            "Read https://evil.invalid/after/360",
            "Read after line 360 and after line 400",
        ):
            with self.subTest(hint=hint):
                self.assertIsNone(
                    continuation_request(
                        self.packet, self.snapshot, {"next_check": hint}
                    )
                )

    def test_drift_unknown_path_eof_missing_metadata_and_ambiguity_rejected(self):
        source = self.packet["sources"][0]
        for patch in (
            {"end_line": 360.0},
            {"total_lines": 360},
            {"truncated": False},
            {"start_line": True},
            {"url": source["url"].replace(self.sha, "b" * 40)},
            {"url": source["url"].replace("src/worker.ts", "src/missing.ts")},
        ):
            with self.subTest(patch=patch):
                packet = {**self.packet, "sources": [{**source, **patch}]}
                self.assertIsNone(
                    continuation_request(
                        packet, self.snapshot, {"next_check": "after line 360"}
                    )
                )
        self.packet["sources"].append(dict(source))
        self.assertIsNone(
            continuation_request(
                self.packet, self.snapshot, {"next_check": "after line 360"}
            )
        )

    def test_real_followup_replaces_fetch_without_expanding_read_count(self):
        calls = []
        snapshot = {**self.snapshot, "blobs": {"src/worker.ts": "b" * 40}}

        class Context:
            def snapshot(self, repo, ref="main"):
                return snapshot

            def source(self, repo, commit, path, **kwargs):
                calls.append((path, kwargs))
                return {
                    "url": f"https://raw.githubusercontent.com/{repo}/{commit}/{path}",
                    "text": "369: await worker.close();\n391: worker.createNativeReplacement();",
                }

            def duplicate_sources(self, repo, title):
                return []

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scout.initialize(root)
            config = root / "config.json"
            spec = {
                "repo": "a/b",
                "source_prefixes": ["src/"],
                "question": "Check lifecycle",
            }
            config.write_text(
                json.dumps(
                    {
                        "objective": "Test bounded evidence",
                        "queue_target": 4,
                        "repos": [spec],
                    }
                ),
                encoding="utf-8",
            )
            producer = ResearchProducer(root, config, context=Context())
            source = {**self.packet["sources"][0], "text": "360: await worker.run();"}
            producer.emit("worker", spec, [source], "source_audit")
            with scout.connect(root) as db:
                db.execute(
                    "UPDATE jobs SET state='REVIEW',finished=1,result=?",
                    (
                        json.dumps(
                            {
                                "analysis": {
                                    "title": "worker lifecycle",
                                    "next_check": "Read after line 360",
                                }
                            }
                        ),
                    ),
                )
            self.assertTrue(producer.followup(spec, {}))
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][0], "src/worker.ts")
            self.assertEqual(calls[0][1]["start"], 341)
            self.assertEqual(calls[0][1]["max_lines"], 120)


class NativeDeclarationContinuationTests(unittest.TestCase):
    def setUp(self):
        self.sha = "a" * 40
        self.snapshot = {"commit": self.sha, "files": ["src/table.rs"]}
        self.source = {
            "url": f"https://raw.githubusercontent.com/a/b/{self.sha}/src/table.rs",
            "start_line": 585, "end_line": 664, "total_lines": 4000,
            "definition_selection": {"symbol": "query", "selected_line": 605,
                                     "candidate_lines": [605, 1725, 3582]},
        }
        self.packet = {"repo": "a/b", "sources": [self.source]}

    def request(self, text="Read declaration at line 3582", packet=None, snapshot=None):
        return continuation_request(packet or self.packet, snapshot or self.snapshot, {"next_check": text})

    def test_observed_native_candidate_replaces_window(self):
        for text in ("Read declaration at line 3582", "Read declaration line 1725"):
            with self.subTest(text=text):
                self.assertEqual(self.request(text), {"path": "src/table.rs", "start": int(text.split()[-1]), "max_lines": 120})

    def test_unobserved_multiple_url_and_tail_requests_rejected(self):
        for text in ("Read declaration line 400", "Read declaration line 605",
                     "Read declaration line 3582 and declaration line 1725",
                     "Read declaration line 3582 https://evil.invalid/a",
                     "Read declaration line 3582 after line 664",
                     "Read declaration line 3582 and lines 665-700",
                     "Read declaration line 3582，行664之后",
                     "Read declaration line 3582，665-700行"):
            with self.subTest(text=text):
                self.assertIsNone(self.request(text))

    def test_bad_controller_metadata_cannot_select_a_line(self):
        for change in ({"candidate_lines": [605, True, 3582]},
                       {"candidate_lines": [605, 3582, 3582]},
                       {"candidate_lines": [3582, 605]},
                       {"candidate_lines": [605, 1725, 3582, 4001]},
                       {"candidate_lines": [605, 700, 800, 900, 1000, 3582]},
                       {"selected_line": 700}, {"symbol": "q" * 129}):
            with self.subTest(change=change):
                source = {**self.source, "definition_selection": {**self.source["definition_selection"], **change}}
                self.assertIsNone(self.request(packet={"repo": "a/b", "sources": [source]}))

    def test_drift_unknown_path_and_ambiguous_sources_rejected(self):
        self.assertIsNone(self.request(snapshot={**self.snapshot, "commit": "b" * 40}))
        self.assertIsNone(self.request(snapshot={**self.snapshot, "files": []}))
        self.assertIsNone(self.request(packet={"repo": "a/b", "sources": [self.source, dict(self.source)]}))
        for key, value in (("start_line", True), ("end_line", 5000), ("total_lines", None)):
            with self.subTest(key=key):
                self.assertIsNone(self.request(packet={"repo": "a/b", "sources": [{**self.source, key: value}]}))

    def test_producer_follows_observed_impl_with_one_cached_raw_read(self):
        from kimi_scout_context import PublicContext
        from unittest.mock import patch
        snapshot = {**self.snapshot, "blobs": {"src/table.rs": "b" * 40}}
        lines = ["// unrelated"] * 4000
        lines[604] = "    async fn query(&self);"
        lines[1724] = "    pub fn query(&self) -> Query {"
        lines[3581] = "    async fn query(&self) {"
        lines[3582] = "        execute_native_query().await;"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scout.initialize(root)
            spec = {"repo": "a/b", "source_prefixes": ["src/"], "question": "Inspect native query"}
            config = root / "config.json"
            scout.write_json(config, {"objective": "Acquire implementation evidence", "queue_target": 4, "repos": [spec]})
            ctx = PublicContext(root)
            with patch.object(ctx, "snapshot", return_value=snapshot), \
                 patch.object(ctx, "_read", return_value="\n".join(lines)) as read, \
                 patch.object(ctx, "duplicate_sources", return_value=[]):
                initial = ctx.source("a/b", self.sha, "src/table.rs", hints="NativeTable.query", max_lines=80)
                self.assertNotIn("execute_native_query", initial["text"])
                producer = ResearchProducer(root, config, context=ctx)
                producer.emit("native-query", spec, [initial], "source_audit")
                with scout.connect(root) as db:
                    db.execute("UPDATE jobs SET state='REVIEW',finished=1,result=?", (
                        json.dumps({"analysis": {"title": "NativeTable query", "next_check": "Read declaration line 3582"}}),))
                self.assertTrue(producer.followup(spec, {}))
                self.assertEqual(read.call_count, 1)
            with scout.connect(root) as db:
                packet = json.loads(db.execute("SELECT packet FROM jobs ORDER BY created DESC LIMIT 1").fetchone()[0])
            fragments = [s for s in packet["sources"] if s["url"] == initial["url"]]
            self.assertEqual(len(fragments), 2)  # Existing followup retains its parent's evidence.
            implementation = [s for s in fragments if s["start_line"] == 3582]
            self.assertEqual(len(implementation), 1)
            self.assertIn("execute_native_query", implementation[0]["text"])
            self.assertLessEqual(len(implementation[0]["text"].splitlines()), 120)


if __name__ == "__main__":
    unittest.main()
