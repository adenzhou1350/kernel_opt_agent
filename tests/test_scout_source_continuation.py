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

    def test_explicit_missing_interval_is_bounded_by_observed_window(self):
        for hint in ("Read lines 361-537", "获取该文件361–537行", "Read lines 360-537"):
            with self.subTest(hint=hint):
                self.assertEqual(
                    continuation_request(
                        self.packet, self.snapshot, {"next_check": hint}
                    ),
                    {
                        "path": "src/worker.ts",
                        "start": 341,
                        "max_lines": 120,
                        "tail_start": 418,
                    },
                )
        for hint in (
            "Read lines 362-537",
            "Read lines 361-538",
            "Read lines 361-360",
            "Read lines 0-537",
            "Read lines 361-537 and after line 400",
            "Read lines 361-537 and lines 400-500",
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
                    "text": f"{kwargs['start']}: observed distinct fragment",
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
                                    "next_check": "获取该文件361-537行，检查实际调用入口",
                                }
                            }
                        ),
                    ),
                )
            self.assertTrue(producer.followup(spec, {}))
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0][0], "src/worker.ts")
            self.assertEqual(calls[0][1]["start"], 341)
            self.assertEqual(calls[0][1]["max_lines"], 120)
            self.assertEqual(calls[1][0], "src/worker.ts")
            self.assertEqual(calls[1][1]["start"], 418)
            self.assertEqual(calls[1][1]["max_lines"], 120)
            with scout.connect(root) as db:
                emitted = json.loads(
                    db.execute(
                        "SELECT packet FROM jobs ORDER BY created DESC LIMIT 1"
                    ).fetchone()[0]
                )
            fragments = [
                s for s in emitted["sources"] if s["url"].endswith("src/worker.ts")
            ]
            self.assertTrue(any(s["text"].startswith("341:") for s in fragments))
            self.assertTrue(any(s["text"].startswith("418:") for s in fragments))

    def test_short_range_and_unbounded_after_do_not_add_tail(self):
        self.assertEqual(
            continuation_request(
                self.packet, self.snapshot, {"next_check": "Read lines 361-400"}
            ),
            {"path": "src/worker.ts", "start": 341, "max_lines": 120},
        )
        self.assertEqual(
            continuation_request(
                self.packet, self.snapshot, {"next_check": "after line 360"}
            ),
            {"path": "src/worker.ts", "start": 341, "max_lines": 120},
        )

    def test_long_requested_tail_exposes_outer_handler_without_completeness_claim(self):
        from kimi_scout_context import PublicContext
        from unittest.mock import patch

        self.packet["sources"][0].update(start_line=361, end_line=481, total_lines=718)
        request = continuation_request(
            self.packet, self.snapshot, {"next_check": "检查481-718行外层catch"}
        )
        self.assertEqual(request["tail_start"], 599)
        with tempfile.TemporaryDirectory() as directory:
            ctx = PublicContext(Path(directory))
            lines = ["// padding"] * 718
            lines[644] = "} catch (error) {"
            lines[697] = 'return { status: "error" };'
            raw = "\n".join(lines)
            with (
                patch.object(ctx, "snapshot", return_value=self.snapshot),
                patch.object(ctx, "_read", return_value=raw) as read,
            ):
                head = ctx.source(
                    "a/b",
                    self.sha,
                    request["path"],
                    start=request["start"],
                    max_lines=120,
                )
                tail = ctx.source(
                    "a/b",
                    self.sha,
                    request["path"],
                    start=request["tail_start"],
                    max_lines=120,
                )
            self.assertNotIn("catch (error)", head["text"])
            self.assertIn("catch (error)", tail["text"])
            self.assertIn('status: "error"', tail["text"])
            self.assertEqual(
                read.call_count, 1
            )  # Second fragment reuses the full raw cache.
            self.assertTrue(head["truncated"] and tail["truncated"])
            self.assertNotIn("requested_definition_complete", tail)


if __name__ == "__main__":
    unittest.main()
