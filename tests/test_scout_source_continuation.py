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


if __name__ == "__main__":
    unittest.main()
