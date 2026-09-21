"""Offline frontier tests: no GitHub, credentials, Kimi, or GPU activity."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout as scout
import kimi_scout_research as research
from kimi_scout_context import IssuePage


class Context:
    def __init__(self):
        self.calls = []
        self.revision = "a" * 40
        self.blob = "b" * 40
        self.issue_version = "first"

    def snapshot(self, repo, ref="main"):
        return {
            "commit": self.revision,
            "files": ["src/kernel.py", "tests/test_kernel.py"],
            "blobs": {"src/kernel.py": self.blob, "tests/test_kernel.py": "c" * 40},
        }

    def source(self, repo, commit, path, hints="", start=None):
        self.calls.append((repo, commit, path, start))
        start = start or 1
        if start > 10:
            raise ValueError("source start line is beyond end of file")
        return {
            "url": f"https://raw.githubusercontent.com/{repo}/{commit}/{path}",
            "text": f"{start}: kernel boundary {self.blob}",
            "total_lines": 10,
        }

    def issue_page(self, repo, page=1):
        if page > 1:
            return []
        return [
            {
                "number": 42,
                "title": "kernel.py boundary",
                "body": "src/kernel.py index",
                "updated_at": self.issue_version,
                "html_url": f"https://github.com/{repo}/issues/42",
            }
        ]

    def issue_sources(self, repo, number):
        return [
            {
                "url": f"https://github.com/{repo}/issues/{number}",
                "text": "Full public report kernel.py index",
            },
            {
                "url": f"https://github.com/{repo}/issues/{number}#issuecomment-1",
                "text": "More context",
            },
        ]

    def duplicate_sources(self, repo, title):
        return [
            {
                "url": f"https://github.com/{repo}/pull/3",
                "text": "Related existing implementation",
            }
        ]


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        scout.initialize(self.root)
        self.config = self.root / "config.json"
        self.value = {
            "objective": "Find falsifiable public leads",
            "queue_target": 4,
            "repos": [
                {
                    "repo": "a/b",
                    "source_prefixes": ["src/"],
                    "question": "Check boundaries",
                }
            ],
        }
        self.config.write_text(json.dumps(self.value), encoding="utf-8")
        self.context = Context()
        self.producer = research.ResearchProducer(
            self.root, self.config, context=self.context
        )
        self.spec = self.value["repos"][0]

    def jobs(self):
        with scout.connect(self.root) as db:
            return list(db.execute("SELECT * FROM jobs ORDER BY created"))

    def finish(self, row, decision="lead"):
        with scout.connect(self.root) as db:
            db.execute(
                "UPDATE jobs SET state=?,result=?,finished=? WHERE id=?",
                (
                    "REVIEW" if decision == "lead" else "NO_LEAD",
                    json.dumps(
                        {
                            "analysis": {
                                "title": "kernel.py issue",
                                "next_check": "src/kernel.py boundary",
                            }
                        }
                    ),
                    time.time(),
                    row["id"],
                ),
            )

    def test_short_file_skips_past_eof_and_dedups_restart(self):
        progress = self.producer.state["repos"].setdefault("a/b", {})
        self.assertTrue(self.producer.source_audit(self.spec, progress))
        self.assertFalse(self.producer.source_audit(self.spec, progress))
        self.producer.save()
        again = research.ResearchProducer(self.root, self.config, context=self.context)
        self.assertFalse(again.source_audit(self.spec, again.state["repos"]["a/b"]))
        self.assertEqual(len(self.jobs()), 1)
        self.assertEqual(self.context.calls[0][-1], 1)

    def test_only_changed_blob_creates_fresh_source_work(self):
        self.assertTrue(self.producer.source_audit(self.spec, {}))
        self.context.revision = "d" * 40
        self.assertFalse(self.producer.source_audit(self.spec, {}))
        self.context.blob = "e" * 40
        self.assertTrue(self.producer.source_audit(self.spec, {}))
        self.assertEqual(len(self.jobs()), 2)

    def test_no_rephrasing_followup_and_two_step_cap(self):
        self.assertTrue(self.producer.issue(self.spec, {}))
        self.finish(self.jobs()[0])
        self.assertTrue(self.producer.followup(self.spec, {}))
        child = self.jobs()[-1]
        data = json.loads(child["packet"])["research"]
        self.assertEqual(data["depth"], 1)
        self.assertEqual(data["parent_job_id"], self.jobs()[0]["id"])
        self.finish(child)
        # Identical second-stage evidence costs no model call.
        self.assertFalse(self.producer.followup(self.spec, {}))
        self.assertEqual(len(self.jobs()), 2)

    def test_depth_two_is_handoff_even_with_new_evidence(self):
        self.producer.issue(self.spec, {})
        root = self.jobs()[0]
        packet = json.loads(root["packet"])
        packet["research"].update(depth=2, root_job_id=root["id"])
        with scout.connect(self.root) as db:
            db.execute(
                "UPDATE jobs SET packet=? WHERE id=?", (json.dumps(packet), root["id"])
            )
        self.finish(root)
        self.assertFalse(self.producer.followup(self.spec, {}))

    def test_no_lead_does_not_spawn(self):
        self.producer.issue(self.spec, {})
        self.finish(self.jobs()[0], "no_lead")
        self.assertFalse(self.producer.followup(self.spec, {}))

    def test_pr_only_page_advances_before_later_issue_and_real_eof(self):
        progress = {}
        issue = self.context.issue_page("a/b")[0]
        with patch.object(
            self.context,
            "issue_page",
            side_effect=[
                IssuePage([], exhausted=False),
                IssuePage([issue], exhausted=False),
                IssuePage([], exhausted=True),
            ],
        ) as pages:
            self.assertFalse(self.producer.issue(self.spec, progress))
            self.assertEqual(progress["issue_page"], 1)
            self.assertNotIn("issues_after", progress)
            self.assertTrue(self.producer.issue(self.spec, progress))
            self.assertFalse(self.producer.issue(self.spec, progress))
        self.assertEqual([call.args[1] for call in pages.call_args_list], [1, 2, 3])
        self.assertEqual(progress["issue_page"], 0)
        self.assertGreater(progress["issues_after"], time.time())

    def test_followup_older_than_global_limit_is_not_starved(self):
        for kind in ("foreign", "handled", "depth_two"):
            with self.subTest(kind=kind):
                self.producer.issue(self.spec, {})
                original = self.jobs()[0]
                self.finish(original)
                template = json.loads(original["packet"])
                template.pop("focus_issue", None)
                template["research"] = {"depth": 2 if kind == "depth_two" else 0}
                if kind == "foreign":
                    template["repo"] = "other/repo"
                with scout.connect(self.root) as db:
                    db.executemany(
                        "INSERT INTO jobs(id,name,packet,state,created,finished,result) "
                        "VALUES(?,?,?,'REVIEW',?,?,?)",
                        [
                            (
                                f"newer-{i}",
                                "noise",
                                json.dumps(template),
                                time.time(),
                                time.time() + 100 + i,
                                original["result"] or json.dumps({"analysis": {}}),
                            )
                            for i in range(1501)
                        ],
                    )
                    if kind == "handled":
                        db.executemany(
                            "INSERT INTO research_seen(key) VALUES(?)",
                            [(f"followup:newer-{i}:1",) for i in range(1501)],
                        )
                self.assertTrue(self.producer.followup(self.spec, {}))
                child = self.jobs()[-1]
                self.assertEqual(
                    json.loads(child["packet"])["research"]["parent_job_id"],
                    original["id"],
                )
                with scout.connect(self.root) as db:
                    db.execute("DELETE FROM jobs")
                    db.execute("DELETE FROM research_seen")

    def test_queue_ceiling_and_stop_are_enforced(self):
        for i in range(4):
            self.assertTrue(
                self.producer.emit(
                    str(i),
                    self.spec,
                    [{"url": "https://github.com/a/b/issues/1", "text": str(i)}],
                    "issue_triage",
                )
            )
        self.assertFalse(self.producer.tick())
        self.producer.halt.set()
        self.assertFalse(
            self.producer.emit(
                "new",
                self.spec,
                [{"url": "https://github.com/a/b/issues/1", "text": "new"}],
                "issue_triage",
            )
        )
        self.assertEqual(len(self.jobs()), 4)

    def test_hints_cannot_introduce_arbitrary_fetch_paths(self):
        paths = research.relevant_paths(
            self.context.snapshot("a/b"),
            "../../secret /etc/passwd https://evil.test/kernel.py src/kernel.py",
        )
        self.assertEqual(paths, ["src/kernel.py"])
        self.assertNotIn("secret", paths)

    def test_generic_filenames_need_an_observed_full_path(self):
        snapshot = {"files": ["src/kernel.py", "examples/kernel.py", "src/utils.py"]}
        self.assertEqual(research.relevant_paths(snapshot, "kernel.py utils.py"), [])
        self.assertEqual(
            research.relevant_paths(snapshot, "inspect src/kernel.py and src/utils.py"),
            ["src/kernel.py", "src/utils.py"],
        )

    def test_same_file_windows_survive_dedup_and_unchanged_packets_do_not_repeat(self):
        url = f"https://raw.githubusercontent.com/a/b/{self.context.revision}/src/kernel.py"
        old = {"url": url, "text": "1: original boundary"}
        new = {"url": url, "text": "121: caller validates the boundary"}
        self.assertTrue(
            self.producer.emit(
                "windows", self.spec, [old, new, dict(new)], "source_followup"
            )
        )
        self.assertEqual(json.loads(self.jobs()[0]["packet"])["sources"], [old, new])
        self.assertFalse(
            self.producer.emit("same", self.spec, [new, old], "source_followup")
        )
        self.assertEqual(len(self.jobs()), 1)

    def test_followup_keeps_new_same_file_window_and_stops_without_new_evidence(self):
        url = f"https://raw.githubusercontent.com/a/b/{self.context.revision}/src/kernel.py"
        old = {"url": url, "text": "1: original boundary"}
        new = {"url": url, "text": "121: caller validates the boundary"}
        self.producer.emit("root", self.spec, [old], "source_audit")
        self.finish(self.jobs()[0])
        with (
            patch.object(self.context, "source", return_value=new) as source,
            patch.object(self.context, "duplicate_sources", return_value=[]),
        ):
            self.assertTrue(self.producer.followup(self.spec, {}))
            child = self.jobs()[-1]
            packet = json.loads(child["packet"])
            self.assertEqual(packet["sources"], [old, new])
            answer = dict.fromkeys(
                (
                    "title",
                    "hypothesis",
                    "baseline",
                    "next_check",
                    "duplicate_risk",
                    "uncertainty",
                    "knowledge_suggestion",
                ),
                "Unexecuted regression hypothesis",
            )
            answer.update(
                decision="lead",
                evidence=[{"url": url, "quote": s["text"]} for s in (old, new)],
            )
            self.assertIs(scout.validate_result(answer, packet), answer)
            hints = source.call_args.kwargs["hints"]
            self.assertTrue(hints.startswith("src/kernel.py boundary\n"))
            self.assertIn(url, hints)
            self.assertNotIn('"next_check":', hints)
            self.finish(child)
            self.assertFalse(self.producer.followup(self.spec, {}))
        self.assertEqual(len(self.jobs()), 2)

    def test_revision_only_followup_does_not_create_fresh_evidence(self):
        url = f"https://raw.githubusercontent.com/a/b/{self.context.revision}/src/kernel.py"
        old = {"url": url, "text": "1: original boundary"}
        self.producer.emit("root", self.spec, [old], "source_audit")
        self.finish(self.jobs()[0])
        updated = dict(old, url=url.replace(self.context.revision, "d" * 40))
        with (
            patch.object(self.context, "source", return_value=updated),
            patch.object(self.context, "duplicate_sources", return_value=[]),
        ):
            self.assertFalse(self.producer.followup(self.spec, {}))
        self.assertEqual(len(self.jobs()), 1)

    def test_budget_trimmed_followup_does_not_repeat_unchanged_raw_windows(self):
        prefix = f"https://raw.githubusercontent.com/a/b/{self.context.revision}/"
        old = {"url": prefix + "src/kernel.py", "text": "a" * 9000}
        new = {"url": old["url"], "text": "b" * 9000}
        test = {"url": prefix + "tests/test_kernel.py", "text": "c" * 9000}

        def finish(row):
            self.finish(row)
            with scout.connect(self.root) as db:
                db.execute(
                    "UPDATE jobs SET result=? WHERE id=?",
                    (
                        json.dumps(
                            {
                                "analysis": {
                                    "title": "boundary",
                                    "next_check": "Inspect src/kernel.py and tests/test_kernel.py",
                                }
                            }
                        ),
                        row["id"],
                    ),
                )

        self.producer.emit("root", self.spec, [old, test], "source_audit")
        self.assertFalse(
            self.producer.emit("same-root", self.spec, [old, test], "source_audit")
        )
        finish(self.jobs()[0])
        with (
            patch.object(
                self.context,
                "source",
                side_effect=lambda repo, commit, path, **kwargs: (
                    new if path == "src/kernel.py" else test
                ),
            ),
            patch.object(self.context, "duplicate_sources", return_value=[]),
        ):
            self.assertTrue(self.producer.followup(self.spec, {}))
            child = self.jobs()[-1]
            sources = json.loads(child["packet"])["sources"]
            self.assertEqual(len(sources), 3)
            self.assertTrue(any("_scout_pretrim_sha256" in s for s in sources))
            self.assertTrue(any(len(s["text"]) < 9000 for s in sources))
            finish(child)
            self.assertFalse(self.producer.followup(self.spec, {}))
        self.assertEqual(len(self.jobs()), 2)

    def test_search_snippet_cannot_trigger_followup_when_full_issue_is_unchanged(self):
        self.producer.issue(self.spec, {})
        self.finish(self.jobs()[0])
        self.assertTrue(self.producer.followup(self.spec, {}))
        self.finish(self.jobs()[-1])
        snippet = {
            "url": "https://github.com/a/b/issues/42",
            "text": "shorter search snippet",
        }
        with patch.object(self.context, "duplicate_sources", return_value=[snippet]):
            self.assertFalse(self.producer.followup(self.spec, {}))
        self.assertEqual(len(self.jobs()), 2)

    def test_budget_trims_peripheral_search_before_same_file_code_windows(self):
        url = f"https://raw.githubusercontent.com/a/b/{self.context.revision}/src/kernel.py"
        code = [{"url": url, "text": "a" * 6000}, {"url": url, "text": "b" * 9000}]
        related = [
            {
                "url": f"https://github.com/a/b/pull/{i}",
                "text": "s" * 1800,
                "search_exhaustive": False,
            }
            for i in range(3)
        ]
        self.producer.emit(
            "large_windows", self.spec, code + related, "source_followup"
        )
        packet = json.loads(self.jobs()[0]["packet"])
        self.assertEqual(packet["sources"][:2], code)
        self.assertTrue(any(s.get("truncated") for s in packet["sources"][2:]))
        self.assertLessEqual(
            len((scout.SYSTEM + scout.dumps(packet)).encode()), scout.MAX_INPUT_BYTES
        )

    def test_oversize_evidence_trimmed_with_explicit_flag(self):
        self.producer.emit(
            "large",
            self.spec,
            [{"url": "https://github.com/a/b/issues/1", "text": "汉" * 30000}],
            "issue_triage",
        )
        packet = json.loads(self.jobs()[0]["packet"])
        self.assertLessEqual(
            len((scout.SYSTEM + scout.dumps(packet)).encode()), scout.MAX_INPUT_BYTES
        )
        self.assertTrue(packet["sources"][0]["truncated"])

    def test_issue_updated_at_only_new_issue_packets(self):
        self.assertTrue(self.producer.issue(self.spec, {}))
        self.assertFalse(self.producer.issue(self.spec, {}))
        self.context.issue_version = "second"
        # Content dedup in enqueue still prevents paying for identical evidence.
        self.assertFalse(self.producer.issue(self.spec, {}))
        self.assertEqual(len(self.jobs()), 1)

    def test_config_rejects_unsafe_prefix_and_duplicate_repos(self):
        self.value["repos"][0]["source_prefixes"] = ["../private"]
        self.config.write_text(json.dumps(self.value))
        with self.assertRaises(ValueError):
            research.configuration(self.config)

    def test_context_workers_default_and_bounds(self):
        self.assertEqual(research.configuration(self.config)["context_workers"], 1)
        for value in (0, 4, True, 1.5, "2"):
            with self.subTest(value=value):
                self.value["context_workers"] = value
                self.config.write_text(json.dumps(self.value))
                with self.assertRaises(ValueError):
                    research.configuration(self.config)
        self.value["context_workers"] = 3
        self.config.write_text(json.dumps(self.value))
        self.assertEqual(research.configuration(self.config)["context_workers"], 3)

    def test_repository_count_bounds(self):
        for count in (0, 1, 10, 12, 13):
            with self.subTest(count=count):
                self.value["repos"] = [
                    dict(self.spec, repo=f"owner/repo{i}") for i in range(count)
                ]
                self.config.write_text(json.dumps(self.value))
                if 1 <= count <= 12:
                    self.assertEqual(
                        len(research.configuration(self.config)["repos"]), count
                    )
                else:
                    with self.assertRaisesRegex(ValueError, "1..12"):
                        research.configuration(self.config)

    def test_ten_repository_frontier_visits_every_repository(self):
        self.value.update(
            queue_target=16,
            context_workers=3,
            repos=[dict(self.spec, repo=f"owner/repo{i}") for i in range(10)],
        )
        self.config.write_text(json.dumps(self.value))
        producer = research.ResearchProducer(
            self.root, self.config, context=self.context
        )
        for _ in range(10):
            self.assertTrue(producer.tick())
        self.assertEqual(
            {json.loads(row["packet"])["repo"] for row in self.jobs()},
            {spec["repo"] for spec in self.value["repos"]},
        )
        self.assertEqual(producer.config["context_workers"], 3)

    def test_javascript_and_typescript_observed_source_paths(self):
        paths = [
            f"src/router{suffix}"
            for suffix in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
        ]
        ignored = ["src/router.json", "src/vendor/router.ts", "docs/router.ts"]
        snapshot = {"files": paths + ignored}
        self.assertEqual(research.source_paths(snapshot, self.spec), sorted(paths))
        self.assertEqual(
            research.relevant_paths(
                {"files": paths + ["src/router.json"]},
                " ".join(paths) + " src/missing.ts",
            ),
            sorted(paths),
        )
        self.assertNotIn(
            paths[0],
            research.relevant_paths(snapshot, " ".join(paths), exclude=[paths[0]]),
        )

    def test_typescript_source_audit_includes_observed_related_test(self):
        paths = ["src/router.ts", "tests/router.test.ts"]
        snapshot = {
            "commit": self.context.revision,
            "files": paths,
            "blobs": {path: self.context.blob for path in paths},
        }
        with patch.object(self.context, "snapshot", return_value=snapshot):
            self.assertTrue(self.producer.source_audit(self.spec, {}))
        packet = json.loads(self.jobs()[0]["packet"])
        self.assertEqual(packet["research"]["stage"], "source_audit")
        self.assertEqual(
            [source["url"].rsplit("/", 1)[-1] for source in packet["sources"]],
            ["router.ts", "router.test.ts"],
        )

    def parallel_producer(self, context):
        self.value["context_workers"] = 2
        self.value["repos"].append(
            {"repo": "c/d", "source_prefixes": ["src/"], "question": "Check bounds"}
        )
        self.config.write_text(json.dumps(self.value))
        return research.ResearchProducer(self.root, self.config, context=context)

    def test_parallel_repository_progress_and_stop_drains_blocked_fetch(self):
        blocked, release, other_finished = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )
        original = self.context.snapshot
        calls = []

        def snapshot(repo, ref="main"):
            calls.append(repo)
            if repo == "a/b":
                blocked.set()
                if not release.wait(5):
                    raise TimeoutError("test release did not arrive")
            return original(repo, ref)

        producer = self.parallel_producer(self.context)
        emit = producer.emit

        def observed_emit(*args, **kwargs):
            made = emit(*args, **kwargs)
            if made and args[1]["repo"] == "c/d":
                other_finished.set()
            return made

        with (
            patch.object(self.context, "snapshot", side_effect=snapshot),
            patch.object(producer, "emit", side_effect=observed_emit),
        ):
            producer.start()
            stopper = None
            try:
                self.assertTrue(blocked.wait(2))
                self.assertTrue(other_finished.wait(2))
                # c/d emits while a/b is blocked, without a second a/b refill.
                self.assertEqual(calls.count("a/b"), 1)
                self.assertTrue(
                    any(json.loads(r["packet"])["repo"] == "c/d" for r in self.jobs())
                )
                stopper = threading.Thread(target=producer.stop)
                stopper.start()
                stopper.join(0.1)
                self.assertTrue(stopper.is_alive())
                release.set()
                stopper.join(3)
                self.assertFalse(stopper.is_alive())
                self.assertFalse(
                    any(json.loads(r["packet"])["repo"] == "a/b" for r in self.jobs())
                )
                self.assertFalse(any(call[0] == "a/b" for call in self.context.calls))
                status = json.loads((self.root / "research.json").read_text())
                self.assertEqual(status["phase"], "STOPPED")
                self.assertEqual(status["context_workers"], 2)
                self.assertEqual(status["context_inflight"], 0)
                with scout.connect(self.root) as db:
                    state = json.loads(
                        db.execute(
                            "SELECT value FROM research_meta WHERE key='frontier'"
                        ).fetchone()[0]
                    )
                self.assertEqual(set(state["repos"]), {"a/b", "c/d"})
                self.assertEqual(state["discovery_created"], len(self.jobs()))
            finally:
                release.set()
                producer.stop()
                if stopper:
                    stopper.join(3)

    def test_parallel_emissions_deduplicate_atomically(self):
        barrier = threading.Barrier(8)

        def submit(_):
            barrier.wait(timeout=3)
            return self.producer.emit(
                "same-key",
                self.spec,
                [{"url": "https://github.com/a/b/issues/1", "text": "same"}],
                "issue_triage",
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            made = list(pool.map(submit, range(8)))
        self.assertEqual(sum(made), 1)
        self.assertEqual(len(self.jobs()), 1)
        self.assertEqual(self.producer.state["discovery_created"], 1)
        with scout.connect(self.root) as db:
            self.assertEqual(
                db.execute("SELECT count(*) FROM research_seen").fetchone()[0], 2
            )

    def test_fast_parallel_refills_do_not_wait_for_idle_scan_interval(self):
        self.value["context_workers"] = 2
        self.config.write_text(json.dumps(self.value))
        producer = research.ResearchProducer(
            self.root, self.config, context=self.context
        )
        emitted = threading.Event()
        emit = producer.emit
        count = 0

        def observe(*args, **kwargs):
            nonlocal count
            made = emit(*args, **kwargs)
            count += int(made)
            if count >= 2:
                emitted.set()
            return made

        with patch.object(producer, "emit", side_effect=observe):
            producer.start()
            try:
                self.assertTrue(emitted.wait(2))
            finally:
                producer.stop()

    def test_parallel_last_queue_slot_preserves_deferred_source(self):
        for i in range(3):
            self.producer.emit(
                str(i),
                self.spec,
                [{"url": "https://github.com/a/b/issues/1", "text": str(i)}],
                "issue_triage",
            )
        producer = self.parallel_producer(self.context)
        barrier = threading.Barrier(2)
        original = self.context.source

        def source(repo, commit, path, **kwargs):
            if path == "src/kernel.py":
                barrier.wait(timeout=3)
            return original(repo, commit, path, **kwargs)

        progress = [{}, {}]
        specs = producer.config["repos"]
        with patch.object(self.context, "source", side_effect=source):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [
                    pool.submit(producer.refill, spec, p, 2)
                    for spec, p in zip(specs, progress)
                ]
                made = [f.result() for f in futures]
        self.assertEqual(sum(made), 1)
        self.assertEqual(len(self.jobs()), 4)
        deferred = made.index(False)
        self.assertEqual(progress[deferred].get("source_cursor", 0), 0)
        with scout.connect(self.root) as db:
            db.execute("UPDATE jobs SET state='NO_LEAD'")
        self.assertTrue(producer.refill(specs[deferred], progress[deferred], 2))
        self.assertEqual(len(self.jobs()), 5)

    def test_emit_rolls_back_job_when_transaction_fails(self):
        enqueue = scout.enqueue

        def fail_after_enqueue(*args, **kwargs):
            enqueue(*args, **kwargs)
            raise RuntimeError("injected database operation failure")

        with patch.object(scout, "enqueue", side_effect=fail_after_enqueue):
            with self.assertRaises(RuntimeError):
                self.producer.emit(
                    "rollback",
                    self.spec,
                    [{"url": "https://github.com/a/b/issues/1", "text": "rollback"}],
                    "issue_triage",
                )
        self.assertEqual(len(self.jobs()), 0)
        self.assertEqual(self.producer.state["discovery_created"], 0)
        with scout.connect(self.root) as db:
            self.assertEqual(
                db.execute("SELECT count(*) FROM research_seen").fetchone()[0], 0
            )

    def test_snapshot_published_no_model_or_credential_data(self):
        self.producer.publish("READY")
        value = json.loads((self.root / "research.json").read_text())
        self.assertEqual(value["queue_target"], 4)
        self.assertEqual(value["phase"], "READY")
        self.assertEqual(value["goals"][0]["repo"], "a/b")

    def test_unsupported_source_does_not_stall_frontier(self):
        progress = {}
        with patch.object(
            self.context,
            "source",
            side_effect=ValueError("binary source is not supported"),
        ):
            self.assertFalse(self.producer.source_audit(self.spec, progress))
        self.assertEqual(progress["skipped_sources"], 1)
        self.assertGreater(progress["sources_after"], time.time())

    def test_stop_during_context_prevents_later_fetch_and_enqueue(self):
        self.producer.issue(self.spec, {})
        self.finish(self.jobs()[0])
        original = self.context.issue_sources

        def cancel(*args):
            self.producer.halt.set()
            return original(*args)

        with (
            patch.object(self.context, "issue_sources", side_effect=cancel),
            patch.object(self.context, "duplicate_sources") as duplicate,
        ):
            self.assertFalse(self.producer.followup(self.spec, {}))
        duplicate.assert_not_called()
        self.assertEqual(len(self.jobs()), 1)

    def test_duplicate_search_does_not_replace_full_issue_context(self):
        self.producer.emit(
            "one",
            self.spec,
            [
                {"url": "https://github.com/a/b/issues/1", "text": "full source"},
                {"url": "https://github.com/a/b/issues/1", "text": "search snippet"},
            ],
            "source_followup",
        )
        self.assertEqual(
            json.loads(self.jobs()[0]["packet"])["sources"][0]["text"], "full source"
        )

    def test_cli_rejects_two_producers_and_once(self):
        with self.assertRaises(SystemExit):
            scout.main(
                [
                    "--root",
                    str(self.root),
                    "run",
                    "--kimi-python",
                    sys.executable,
                    "--research",
                    str(self.config),
                    "--feeds",
                    "unused",
                ]
            )
        self.assertEqual(
            scout.main(
                [
                    "--root",
                    str(self.root),
                    "run",
                    "--kimi-python",
                    sys.executable,
                    "--research",
                    str(self.config),
                    "--once",
                ]
            ),
            2,
        )


if __name__ == "__main__":
    unittest.main()
