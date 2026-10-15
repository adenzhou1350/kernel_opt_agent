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
        self.snapshot = {
            "commit": self.sha,
            "files": ["src/worker.ts"],
            "blobs": {"src/worker.ts": "b" * 40},
        }
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

    def test_explicit_head_replaces_one_window_with_overlap(self):
        for hint in ("Read before line 241 for validation", "查看241行之前的参数检查", "查看行241之前"):
            with self.subTest(hint=hint):
                self.assertEqual(
                    continuation_request(self.packet, self.snapshot, {"next_check": hint}),
                    {"path": "src/worker.ts", "start": 141, "max_lines": 120},
                )

    def test_head_interval_is_anchored_to_visible_start_not_an_arbitrary_range(self):
        for hint in ("Read lines 100-240", "获取100–241行"):
            with self.subTest(hint=hint):
                self.assertEqual(
                    continuation_request(self.packet, self.snapshot, {"next_check": hint}),
                    {"path": "src/worker.ts", "start": 141, "max_lines": 120, "head_start": 100},
                )
        for hint in ("Read before line 240", "Read lines 100-239", "Read lines 100-242",
                     "Read before line 241 and after line 360", "Read before line 241 and before line 100",
                     "Read before line 241 and lines 361-400", "Read lines 0-240"):
            with self.subTest(hint=hint):
                self.assertIsNone(continuation_request(self.packet, self.snapshot, {"next_check": hint}))

    def test_head_at_eof_and_near_bof_remains_bounded(self):
        source = self.packet["sources"][0]
        self.packet["sources"] = [{**source, "start_line": 25, "end_line": 537}]
        self.assertEqual(
            continuation_request(self.packet, self.snapshot, {"next_check": "before line 25"}),
            {"path": "src/worker.ts", "start": 1, "max_lines": 120},
        )
        self.packet["sources"][0]["start_line"] = 1
        self.assertIsNone(continuation_request(self.packet, self.snapshot, {"next_check": "before line 1"}))

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

    def test_tail_range_can_overlap_the_observed_end_without_a_new_target(self):
        for hint in ("Read lines 350-400", "聚焦350–400行", "Read lines 241-537"):
            with self.subTest(hint=hint):
                request = continuation_request(
                    self.packet, self.snapshot, {"next_check": hint}
                )
                self.assertEqual(request["path"], "src/worker.ts")
                self.assertEqual((request["start"], request["max_lines"]), (341, 120))
                self.assertEqual("tail_start" in request, "537" in hint)
        for hint in ("Read lines 240-400", "Read lines 350-360", "Read lines 350-538",
                     "Read lines 350-400 and after line 359"):
            with self.subTest(hint=hint):
                self.assertIsNone(continuation_request(
                    self.packet, self.snapshot, {"next_check": hint}
                ))

    def test_crossing_tail_keeps_same_pin_and_unique_window_requirements(self):
        source = self.packet["sources"][0]
        for changes in ({"url": source["url"].replace(self.sha, "b" * 40)},
                        {"truncated": False}, {"total_lines": 399},
                        {"start_line": True}):
            packet = {**self.packet, "sources": [{**source, **changes}]}
            self.assertIsNone(continuation_request(
                packet, self.snapshot, {"next_check": "Read lines 350-400"}
            ))
        packet = {**self.packet, "sources": [source, {**source, "start_line": 300}]}
        self.assertIsNone(continuation_request(
            packet, self.snapshot, {"next_check": "Read lines 350-400"}
        ))

    def test_head_rejects_drift_ambiguity_and_untrusted_metadata(self):
        source = self.packet["sources"][0]
        for patch in (
            {"end_line": 360.0},
            {"total_lines": 359},
            {"truncated": False},
            {"start_line": True},
            {"start_line": 0},
            {"url": source["url"].replace(self.sha, "b" * 40)},
            {"url": source["url"].replace("src/worker.ts", "src/missing.ts")},
        ):
            with self.subTest(patch=patch):
                packet = {**self.packet, "sources": [{**source, **patch}]}
                self.assertIsNone(
                    continuation_request(packet, self.snapshot, {"next_check": "before line 241"})
                )
        self.packet["sources"].append(dict(source))
        self.assertIsNone(
            continuation_request(self.packet, self.snapshot, {"next_check": "before line 241"})
        )

    def run_followup(self, hint):
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
                                    "next_check": hint,
                                }
                            }
                        ),
                    ),
                )
            self.assertTrue(producer.followup(spec, {}))
            with scout.connect(root) as db:
                emitted = json.loads(
                    db.execute(
                        "SELECT packet FROM jobs ORDER BY created DESC LIMIT 1"
                    ).fetchone()[0]
                )
            fragments = [
                s for s in emitted["sources"] if s["url"].endswith("src/worker.ts")
            ]
            return calls, fragments

    def test_real_followup_replaces_fetch_without_expanding_read_count(self):
        calls, fragments = self.run_followup("获取该文件361-537行，检查实际调用入口")
        self.assertEqual([(path, kw["start"], kw["max_lines"]) for path, kw in calls],
                         [("src/worker.ts", 341, 120), ("src/worker.ts", 418, 120)])
        for start in (341, 418):
            self.assertTrue(any(s["text"].startswith(f"{start}:") for s in fragments))

    def test_head_followup_uses_same_two_read_budget(self):
        calls, fragments = self.run_followup("Read lines 100-240 for preceding validation")
        self.assertEqual([(path, kw["start"], kw["max_lines"]) for path, kw in calls],
                         [("src/worker.ts", 141, 120), ("src/worker.ts", 100, 120)])
        for start in (141, 100):
            self.assertTrue(any(s["text"].startswith(f"{start}:") for s in fragments))

    def test_crossing_tail_followup_keeps_the_two_read_budget(self):
        calls, fragments = self.run_followup("Read lines 350-537 for the missing handler")
        self.assertEqual([(path, kw["start"], kw["max_lines"]) for path, kw in calls],
                         [("src/worker.ts", 341, 120), ("src/worker.ts", 418, 120)])
        for start in (341, 418):
            self.assertTrue(any(s["text"].startswith(f"{start}:") for s in fragments))

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

    def test_preceding_window_exposes_guard_without_an_extra_raw_fetch(self):
        from kimi_scout_context import PublicContext
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            ctx = PublicContext(Path(directory))
            lines = ["// padding"] * 537
            lines[134] = "require_integer_cuda_tensor(num_tokens_post_padded);"
            lines[255] = "check_numel(num_tokens_post_padded);"
            with (
                patch.object(ctx, "snapshot", return_value=self.snapshot),
                patch.object(ctx, "_read", return_value="\n".join(lines)) as read,
            ):
                original = ctx.source("a/b", self.sha, "src/worker.ts", start=228, max_lines=120)
                self.assertNotIn("require_integer_cuda_tensor", original["text"])
                request = continuation_request(
                    {"repo": "a/b", "sources": [original]}, self.snapshot,
                    {"next_check": "Read before line 228 for the earlier validation"},
                )
                preceding = ctx.source("a/b", self.sha, **request)
            self.assertIn("require_integer_cuda_tensor", preceding["text"])
            self.assertEqual(read.call_count, 1)
            self.assertEqual((preceding["start_line"], preceding["end_line"]), (128, 247))
            self.assertTrue(preceding["truncated"])
            self.assertNotIn("requested_definition_complete", preceding)


class TestCompanionContinuation(unittest.TestCase):
    def followup(self, total):
        from kimi_scout_context import PublicContext

        sha = "a" * 40
        test_path = "tests/s3_adapter_config_test.cpp"
        header = "src/config/s3_adapter_config.h"
        short = "include/conductor/common/types.h"
        snapshot = {
            "commit": sha,
            "files": [header, short, test_path],
            "blobs": {path: "b" * 40 for path in (header, short, test_path)},
        }
        raw = {header: "struct S3AdapterConfig {};\n" * 27,
               short: "// shared types\n" * 62,
               test_path: "// configuration case\n" * total}
        calls = []

        class Context(PublicContext):
            def snapshot(self, repo, ref="main"):
                return snapshot

            def _read(self, url, *args, **kwargs):
                prefix = f"https://raw.githubusercontent.com/a/b/{sha}/"
                if not url.startswith(prefix):
                    raise AssertionError("Unexpected network target")
                return raw[url[len(prefix):]]

            def source(self, repo, commit, path, **kwargs):
                calls.append((path, kwargs))
                return super().source(repo, commit, path, **kwargs)

            def duplicate_sources(self, repo, title):
                return []

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scout.initialize(root)
            config = root / "config.json"
            spec = {"repo": "a/b", "source_prefixes": ["src/", "include/"],
                    "question": "Check the configuration contract"}
            config.write_text(json.dumps({"objective": "Bounded evidence", "queue_target": 4,
                                          "repos": [spec]}), encoding="utf-8")
            context = Context(root)
            producer = ResearchProducer(root, config, context=context)
            sources = [context.source("a/b", sha, header, start=1),
                       context.source("a/b", sha, test_path, start=119, max_lines=80)]
            producer.emit("configuration", spec, sources, "source_audit")
            with scout.connect(root) as db:
                db.execute("UPDATE jobs SET state='NEEDS_CONTEXT',finished=1,result=?",
                           (json.dumps({"analysis": {
                               "title": "S3AdapterConfig::FromEnvironment still missing",
                               "decision": "needs_context",
                               "next_check": f"definition(S3AdapterConfig::FromEnvironment), read s3_adapter_config_test.cpp lines 198-{total}",
                           }}),))
            calls.clear()
            self.assertTrue(producer.followup(spec, {}))
            with scout.connect(root) as db:
                packet = json.loads(db.execute(
                    "SELECT packet FROM jobs WHERE state='PENDING'"
                ).fetchone()[0])
            return calls, packet

    def test_test_companion_cannot_steal_the_continuation_path(self):
        calls, packet = self.followup(228)
        self.assertLessEqual(len(calls), 2)
        self.assertEqual((calls[0][0], calls[0][1]["start"]),
                         ("tests/s3_adapter_config_test.cpp", 179))
        self.assertTrue(all(path == "tests/s3_adapter_config_test.cpp" or "start" not in kwargs
                            for path, kwargs in calls))
        self.assertTrue(any(source.get("start_line") == 179 and source.get("end_line") == 228
                            for source in packet["sources"]))

    def test_long_test_tail_reuses_two_slots_without_a_duplicate_test_read(self):
        calls, packet = self.followup(537)
        self.assertEqual([(path, kwargs["start"]) for path, kwargs in calls],
                         [("tests/s3_adapter_config_test.cpp", 179),
                          ("tests/s3_adapter_config_test.cpp", 418)])
        self.assertTrue(all(source["truncated"] for source in packet["sources"]
                            if source.get("start_line") in (179, 418)))


if __name__ == "__main__":
    unittest.main()
