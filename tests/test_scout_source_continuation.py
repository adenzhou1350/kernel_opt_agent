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
        for hint in ("查看行360之后的重试分支", "补取360行之后的循环体",
                     "继续第360 行以后", "Read after line 360 for cleanup"):
            with self.subTest(hint=hint):
                self.assertEqual(
                    continuation_request(
                        self.packet, self.snapshot, {"next_check": hint}
                    ),
                    {"path": "src/worker.ts", "start": 341, "max_lines": 120},
                )

    def test_file_qualified_range_selects_only_the_named_observed_file(self):
        source = self.packet["sources"][0]
        other = {**source, "url": source["url"].replace("worker.ts", "other.ts")}
        packet = {**self.packet, "sources": [source, other]}
        snapshot = {**self.snapshot, "files": ["src/worker.ts", "src/other.ts"]}
        for hint in ("Read worker.ts:360-537", "查看 src/worker.ts:360–537",
                     "worker.ts:360-537 plus references(resolve_in_place)"):
            with self.subTest(hint=hint):
                self.assertEqual(
                    continuation_request(packet, snapshot, {"next_check": hint}),
                    {"path": "src/worker.ts", "start": 341,
                     "max_lines": 120, "tail_start": 418},
                )
        self.assertEqual(
            continuation_request(packet, snapshot, {"next_check": "worker.ts:100-240"}),
            {"path": "src/worker.ts", "start": 141,
             "max_lines": 120, "head_start": 100},
        )

    def test_file_qualified_ranges_reject_unknown_ambiguous_or_unanchored_targets(self):
        for hint in ("missing.ts:360-537", "other/worker.ts:360-537",
                     "worker.ts:362-537", "worker.ts:360-538",
                     "worker.ts:0-537", "worker.ts:360-359",
                     "worker.ts:360-537 and lines 400-500",
                     "worker.ts:360-537 and other.ts:360-537"):
            with self.subTest(hint=hint):
                self.assertIsNone(continuation_request(
                    self.packet, self.snapshot, {"next_check": hint},
                ))
        ambiguous = {**self.snapshot, "files": ["src/worker.ts", "other/worker.ts"]}
        # The other tree member was not supplied: "this file" is unambiguous.
        self.assertIsNotNone(continuation_request(
            self.packet, ambiguous, {"next_check": "worker.ts:360-537"},
        ))
        source = self.packet["sources"][0]
        packet = {**self.packet, "sources": [source, {
            **source, "url": source["url"].replace("src/worker.ts", "other/worker.ts"),
        }]}
        self.assertIsNone(continuation_request(
            packet, ambiguous, {"next_check": "worker.ts:360-537"},
        ))
        self.assertIsNotNone(continuation_request(
            packet, ambiguous, {"next_check": "src/worker.ts:360-537"},
        ))
        self.assertIsNone(continuation_request(
            self.packet, {**self.snapshot, "commit": "c" * 40},
            {"next_check": "worker.ts:360-537"},
        ))

    def test_file_qualified_continuation_precedes_references_without_extra_reads(self):
        calls, fragments = self.run_followup(
            "worker.ts:360-537 plus references(resolve_in_place)",
            cached_raw="fn resolve_in_place() {}\n" * 537,
        )
        self.assertEqual([(p, k["start"], k["max_lines"]) for p, k in calls],
                         [("src/worker.ts", 341, 120), ("src/worker.ts", 418, 120)])
        self.assertTrue(any(s["text"].startswith("341:") for s in fragments))
        self.assertTrue(any(s["text"].startswith("418:") for s in fragments))

    def test_requested_long_continuation_precedes_implicit_companion_test(self):
        self.snapshot["files"].append("src/tests/test_worker.ts")
        calls, _ = self.run_followup("worker.ts:360-537")
        self.assertEqual([(p, k.get("start"), k["max_lines"]) for p, k in calls],
                         [("src/worker.ts", 341, 120), ("src/worker.ts", 418, 120)])

    def test_short_qualified_continuation_keeps_companion_slot(self):
        self.snapshot["files"].append("src/tests/test_worker.ts")
        calls, _ = self.run_followup("worker.ts:360-400")
        self.assertEqual([(p, k.get("start"), k["max_lines"]) for p, k in calls],
                         [("src/worker.ts", 341, 120),
                          ("src/tests/test_worker.ts", None, 80)])

    def test_previously_supplied_text_context_keeps_same_pin_window_constraints(self):
        path = "requirements/cpu.txt"
        source = {**self.packet["sources"][0],
                  "url": f"https://raw.githubusercontent.com/a/b/{self.sha}/{path}"}
        packet = {**self.packet, "sources": [source]}
        snap = {**self.snapshot, "files": [path]}
        hint = {"next_check": "Read after line 360 for the next requirement"}
        self.assertEqual(
            continuation_request(packet, snap, hint),
            {"path": path, "start": 341, "max_lines": 120},
        )
        self.assertIsNone(continuation_request(packet, {**snap, "commit": "c" * 40}, hint))
        self.assertIsNone(continuation_request(packet, {**snap, "files": []}, hint))
        self.assertIsNone(continuation_request(packet, snap, {"next_check": "Read after line 400"}))

    def test_same_file_opposite_windows_can_anchor_one_missing_gap(self):
        source = self.packet["sources"][0]
        packet = {**self.packet, "sources": [
            {**source, "start_line": 301, "end_line": 365},
            {**source, "start_line": 209, "end_line": 272},
        ]}
        # Both requests touch recorded evidence, but from opposite directions.
        # Prefer the trailing fragment: it exposes the missing 273..300 sooner
        # than fetching the long definition's already-visible prefix again.
        for hint in ("获取272-301行", "获取209-300行"):
            with self.subTest(hint=hint):
                self.assertEqual(
                    continuation_request(packet, self.snapshot, {"next_check": hint}),
                    {"path": "src/worker.ts", "start": 253, "max_lines": 120},
                )

    def test_gap_merge_does_not_admit_ambiguous_files_or_unbounded_gaps(self):
        source = self.packet["sources"][0]
        before = {**source, "start_line": 209, "end_line": 272}
        after = {**source, "start_line": 301, "end_line": 365}
        snapshot = {**self.snapshot, "files": ["src/worker.ts", "src/other.ts"]}
        for changed, hint in (
            ({**after, "url": after["url"].replace("worker.ts", "other.ts")}, "获取272-301行"),
            ({**after, "total_lines": 538}, "获取272-301行"),
            ({**after, "start_line": 401, "end_line": 465}, "获取272-401行"),
        ):
            with self.subTest(changed=changed):
                packet = {**self.packet, "sources": [before, changed]}
                self.assertIsNone(continuation_request(packet, snapshot, {"next_check": hint}))

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

    def run_followup(self, hint, *, cached_raw=None):
        calls = []
        snapshot = dict(self.snapshot)

        class Context:
            def snapshot(self, repo, ref="main"):
                return snapshot

            def source(self, repo, commit, path, **kwargs):
                calls.append((path, kwargs))
                return {
                    "url": f"https://raw.githubusercontent.com/{repo}/{commit}/{path}",
                    "text": f"{kwargs.get('start', 1)}: observed distinct fragment",
                }

            def duplicate_sources(self, repo, title):
                return []

            def cached_source_text(self, repo, commit, path):
                return cached_raw

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
            source = {**self.packet["sources"][0],
                      "text": self.packet["sources"][0].get("text", "360: await worker.run();")}
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

    def test_incomplete_definition_cross_revision_reaches_unread_tail_in_producer(self):
        import hashlib

        raw = "def select_backend():\n" + "    # implementation\n" * 150 + "    return 'selected'\n"
        data = raw.encode()
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        # An unrelated repository revision changed, but this file's raw Git
        # identity is unchanged. The earlier read stopped at line65.
        path = "src/worker.py"
        self.snapshot.update(files=[path], blobs={path: blob})
        for revision in (self.sha, 'c'*40):
            with self.subTest(revision=revision):
                self.packet['sources'] = [dict(
                    url=f"https://raw.githubusercontent.com/a/b/{revision}/{path}",
                    start_line=1, end_line=65, total_lines=152, truncated=True,
                    requested_definition=dict(name='select_backend', start_line=1, end_line=152),
                    requested_definition_complete=False,
                    text='\n'.join(f'{i+1}: {line}' for i,line in enumerate(raw.splitlines()[:65])),
                )]
                calls, _ = self.run_followup('definition(select_backend) lines 65-152', cached_raw=raw)
                self.assertEqual([(p, k['start'], k['max_lines']) for p,k in calls], [(path,66,87)])

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

    def test_number_before_chinese_line_marker_reaches_producer_source_read(self):
        calls, fragments = self.run_followup("补取360行之后的循环体")
        self.assertLessEqual(len(calls), 2)
        self.assertEqual((calls[0][0], calls[0][1]["start"]), ("src/worker.ts", 341))
        self.assertTrue(any(s["text"].startswith("341:") for s in fragments))

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


class FollowupEvidenceBudgetTests(unittest.TestCase):
    def source(self, name, count, *, complete=False):
        return {
            "url": f"https://raw.githubusercontent.com/a/b/{'a' * 40}/src/{name}.py",
            "text": "\n".join(f"{i}: {'boundary_' * 3}" for i in range(1, count + 1)),
            "start_line": 1, "end_line": count, "total_lines": count + 100,
            "truncated": not complete,
            "requested_definition_complete": complete,
        }

    def emit(self, sources, prior, budget=None):
        from unittest.mock import patch
        import kimi_scout_research as research

        # Nothing is fetched, and admission occurs only in this temporary queue.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scout.initialize(root)
            spec = dict(repo="a/b", source_prefixes=["src/"], question="Check missing branch")
            config = root / "config.json"
            config.write_text(json.dumps(dict(objective="Context test", queue_target=4,
                                             repos=[spec])), encoding="utf8")
            producer = ResearchProducer(root, config, context=object())
            producer.lessons = []
            with (
                patch.object(research, "lesson_suggestions", return_value=[]),
                patch.object(research, "publication_context", return_value=[]),
                patch.object(research, "owner_deferral_context", return_value=[]),
                patch.object(scout, "MAX_INPUT_BYTES", budget or scout.MAX_INPUT_BYTES),
            ):
                self.assertTrue(producer.emit(
                    "followup", spec, json.loads(json.dumps(sources)), "source_followup",
                    parent=dict(id="parent", root="parent", depth=0,
                                analysis="Read the missing branch", sources=prior),
                ))
            with scout.connect(root) as db:
                packet = json.loads(db.execute("SELECT packet FROM jobs").fetchone()[0])
        if budget:
            self.assertLessEqual(len((scout.SYSTEM + scout.dumps(packet)).encode()), budget)
        self.assertNotIn("sources", packet["research"])
        return packet

    def fitted(self, sources, prior, excess):
        full = self.emit(sources, prior)
        budget = len((scout.SYSTEM + scout.dumps(full)).encode()) - excess
        return self.emit(sources, prior, budget)

    def test_old_partial_yields_before_larger_fresh_tail(self):
        old, fresh = self.source("old", 40), self.source("tail", 80)
        # The parent's excerpt was itself trimmed before admission. Its original
        # retrieval identity must continue matching during repeated shrinks.
        old["_scout_pretrim_sha256"] = "b" * 64
        packet = self.fitted([old, fresh], [old], 400)
        supplied_old, supplied_fresh = packet["sources"]
        self.assertLess(len(supplied_old["text"]), len(old["text"]))
        self.assertEqual(supplied_fresh, fresh)
        self.assertEqual(supplied_old["_scout_pretrim_sha256"], "b" * 64)
        self.assertEqual(supplied_old["end_line"], len(supplied_old["text"].splitlines()))

    def test_fresh_source_still_shrinks_when_old_evidence_is_not_enough(self):
        old, fresh = self.source("old", 40), self.source("tail", 80)
        packet = self.fitted([old, fresh], [old], 1700)
        self.assertLess(len(packet["sources"][0]["text"]), 300)
        self.assertLess(len(packet["sources"][1]["text"]), len(fresh["text"]))
        self.assertFalse(packet["sources"][1]["requested_definition_complete"])

    def test_complete_parent_body_keeps_existing_protection(self):
        old, fresh = self.source("old", 40, complete=True), self.source("tail", 80)
        packet = self.fitted([old, fresh], [old], 400)
        self.assertEqual(packet["sources"][0], old)
        self.assertLess(len(packet["sources"][1]["text"]), len(fresh["text"]))

    def test_peripheral_search_still_yields_before_inherited_code(self):
        old, fresh, search = (self.source("old", 40), self.source("tail", 80),
                              self.source("related", 40))
        search["search_exhaustive"] = False
        packet = self.fitted([old, fresh, search], [old], 300)
        self.assertEqual(packet["sources"][:2], [old, fresh])
        self.assertLess(len(packet["sources"][2]["text"]), len(search["text"]))


if __name__ == "__main__":
    unittest.main()
