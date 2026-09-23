"""Offline tests: no credentials, model calls, network or GPUs."""

import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "kimi_scout.py"
SPEC = importlib.util.spec_from_file_location("kimi_scout", SCRIPT)
scout = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scout)


def packet(name="one", revision="a" * 40):
    return {
        "name": name,
        "commit": revision,
        "sources": [
            {
                "url": f"https://raw.githubusercontent.com/a/b/{revision}/file.py",
                "text": "12: return values[index]",
                "truncated": False,
            }
        ],
        "question": "find a real bug, or no_lead",
    }


def result():
    return {
        "decision": "lead",
        "title": "bounds question",
        "hypothesis": "check caller",
        "baseline": "unchanged",
        "next_check": "read caller",
        "duplicate_risk": "unknown",
        "uncertainty": "not tested",
        "knowledge_suggestion": "",
        "evidence": [
            {"url": packet()["sources"][0]["url"], "quote": "return values[index]"}
        ],
    }


class ScoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        scout.initialize(self.root)

    def add(self, name="one"):
        return scout.enqueue(self.root, packet(name))

    def test_atomic_json_write_survives_transient_windows_read_conflict(self):
        destination = self.root / "status.json"
        replace = os.replace
        calls = 0

        def transient(source, target):
            nonlocal calls
            calls += 1
            if calls < 3:
                raise PermissionError("file is temporarily open")
            replace(source, target)

        with patch.object(scout.os, "replace", side_effect=transient):
            with patch.object(scout.time, "sleep"):
                scout.write_json(destination, {"state": "RUNNING"})
        self.assertEqual(calls, 3)
        self.assertEqual(json.loads(destination.read_text()), {"state": "RUNNING"})
        self.assertFalse(list(self.root.glob(".status.json.*.tmp")))

    def test_content_dedup_across_moving_revision(self):
        a = scout.enqueue(self.root, packet())
        b = scout.enqueue(self.root, packet(revision="b" * 40))
        self.assertEqual(a, b)
        self.assertEqual(len(scout.status(self.root)["jobs"]), 1)

    def test_related_title_churn_does_not_trigger_another_call(self):
        first = packet()
        first["related_open_items_sample"] = [{"title": "incidental PR"}]
        second = dict(first, related_open_items_sample=[{"title": "other PR"}])
        self.assertEqual(
            scout.enqueue(self.root, first), scout.enqueue(self.root, second)
        )

    def test_enqueue_respects_callers_transaction_rollback(self):
        with self.assertRaises(RuntimeError):
            with scout.connect(self.root) as db:
                db.execute("BEGIN IMMEDIATE")
                scout.enqueue(self.root, packet(), db=db)
                raise RuntimeError("rollback")
        self.assertEqual(scout.status(self.root)["jobs"], [])

    def test_citation_to_supplied_related_title_is_allowed(self):
        source = packet()
        source["related_open_items_sample"] = [
            {"url": "https://github.com/a/b/pull/1", "title": "Existing fix"}
        ]
        value = result()
        value["evidence"] = [
            {"url": "https://github.com/a/b/pull/1", "quote": "Existing fix"}
        ]
        self.assertEqual(scout.validate_result(value, source), value)

    def test_atomic_claim_and_persistent_daily_cap(self):
        for i in range(8):
            self.add(str(i))
        with ThreadPoolExecutor(max_workers=4) as pool:
            jobs = list(
                pool.map(lambda _: scout.claim(self.root, 2, 200000, 2048), range(8))
            )
        valid = [job for job in jobs if job]
        self.assertEqual(len(valid), 2)
        self.assertEqual(len({job["id"] for job in valid}), 2)
        self.assertIsNone(scout.claim(self.root, 2, 200000, 2048))

    def test_existing_wal_initialization_does_not_change_mode_under_writer(self):
        with scout.connect(self.root) as writer:
            writer.execute("BEGIN IMMEDIATE")
            started = time.monotonic()
            scout.initialize(self.root)
            self.assertLess(time.monotonic() - started, 2)

    def test_claim_retries_transient_database_lock_without_duplicate_claim(self):
        self.add()
        original = scout._claim_once
        calls = 0

        def transient(*args):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise sqlite3.OperationalError("database is locked")
            return original(*args)

        with patch.object(scout, "_claim_once", side_effect=transient):
            with patch.object(scout.time, "sleep"):
                job = scout.claim(self.root, 0, 0, 2048)
        self.assertEqual(calls, 2)
        self.assertIsNotNone(job)
        self.assertIsNone(scout.claim(self.root, 0, 0, 2048))

    def test_lock_retry_does_not_mask_other_database_errors(self):
        def invalid():
            raise sqlite3.OperationalError("no such table: jobs")

        with self.assertRaisesRegex(sqlite3.OperationalError, "no such table"):
            scout.retry_locked(invalid)

    def test_reservation_budget_blocks_before_provider_call(self):
        self.add()
        self.assertIsNone(scout.claim(self.root, 12, 100, 2048))
        self.assertEqual(scout.status(self.root)["jobs"][0]["state"], "PENDING")

    def test_explicit_zero_caps_allow_work_and_still_account(self):
        self.add()
        job = scout.claim(self.root, 0, 0, 4096)
        self.assertIsNotNone(job)
        self.assertGreater(job["charge"], 4096)

    def test_uncapped_claim_skips_history_aggregate(self):
        self.add()
        from contextlib import contextmanager

        statements = []
        real_connect = scout.connect

        @contextmanager
        def traced(root):
            with real_connect(root) as db:
                db.set_trace_callback(statements.append)
                yield db

        with patch.object(scout, "connect", traced):
            self.assertIsNotNone(scout.claim(self.root, 0, 0, 4096))
        self.assertFalse(any("SUM(charge)" in sql for sql in statements))

    def test_run_migrates_old_inbox_indexes_without_losing_jobs(self):
        self.add()
        with scout.connect(self.root) as db:
            db.execute("DROP INDEX scout_jobs_state_created")
            db.execute("DROP INDEX scout_jobs_started_charge")
        with patch.object(scout, "execute", side_effect=self.fake_execute):
            scout.run(self.run_args())
        with scout.connect(self.root) as db:
            indexes = {row[1] for row in db.execute("PRAGMA index_list(jobs)")}
            rows = list(db.execute("SELECT state FROM jobs"))
        self.assertTrue(
            {"scout_jobs_state_created", "scout_jobs_started_charge"} <= indexes
        )
        self.assertEqual([row[0] for row in rows], ["NO_LEAD"])

    def test_review_preferences_borrow_capacity_and_do_not_starve_discovery(self):
        for stage in ("source_audit", "source_followup", "reproduction_plan"):
            for i in range(7):
                value = packet(f"{stage}-{i}")
                value["research"] = {"stage": stage}
                scout.enqueue(self.root, value)
        selected = [
            json.loads(scout.claim(self.root, 0, 0, 4096, stages)["packet"])[
                "research"
            ]["stage"]
            for stages in scout.REVIEW_ROTATION * 2
        ]
        for cycle in (selected[:8], selected[8:]):
            self.assertEqual(cycle.count("source_audit"), 3)
            self.assertEqual(cycle.count("source_followup"), 3)
            self.assertEqual(cycle.count("reproduction_plan"), 2)
        # An absent role never strands other queued work.
        self.assertIsNotNone(scout.claim(self.root, 0, 0, 4096, ("absent",)))

    def test_review_preference_still_respects_atomic_cost_cap(self):
        self.add()
        self.assertIsNone(scout.claim(self.root, 0, 1, 4096, ("source_followup",)))
        self.assertEqual(scout.status(self.root)["jobs"][0]["state"], "PENDING")

    def run_args(self, **changes):
        defaults = dict(
            root=self.root,
            hours=0,
            concurrency=4,
            max_jobs=0,
            token_budget=0,
            feeds=None,
            github_auth=False,
            poll_seconds=300,
            output_tokens=4096,
            timeout=30,
            error_cooldown_seconds=60,
            kimi_python=sys.executable,
            once=True,
        )
        return SimpleNamespace(**dict(defaults, **changes))

    def fake_execute(self, root, job, *unused):
        with scout.connect(root) as db:
            db.execute(
                "UPDATE jobs SET state='NO_LEAD',finished=? WHERE id=?",
                (time.time(), job["id"]),
            )
        return {"state": "NO_LEAD", "finished": time.time()}

    def test_unlimited_run_drains_four_way_and_has_no_deadline(self):
        for i in range(9):
            self.add(str(i))
        with patch.object(scout, "execute", side_effect=self.fake_execute):
            current = scout.run(self.run_args())
        self.assertIsNone(current["runtime"]["deadline"])
        self.assertIsNone(current["runtime"]["daily_max_calls"])
        self.assertEqual(current["runtime"]["attempted_this_run"], 9)
        self.assertIsInstance(current["runtime"]["heartbeat_at"], float)
        self.assertIsNone(current["runtime"]["next_feed_at"])
        self.assertIsNone(current["runtime"]["cooldown_until"])
        self.assertTrue(all(job["state"] == "NO_LEAD" for job in current["jobs"]))

    def test_eight_and_sixteen_workers_can_really_run_simultaneously(self):
        for count in (8, 16):
            with self.subTest(concurrency=count):
                for i in range(count):
                    self.add(f"{count}-{i}")
                barrier = threading.Barrier(count, timeout=10)

                def execute(root, job, *unused):
                    barrier.wait()
                    return self.fake_execute(root, job)

                with patch.object(scout, "execute", side_effect=execute):
                    current = scout.run(
                        self.run_args(concurrency=count, review_priority=True)
                    )
                self.assertEqual(current["runtime"]["attempted_this_run"], count)
                self.assertEqual(current["runtime"]["concurrency"], count)
                self.assertEqual(current["runtime"]["queue_policy"], "review_weighted")

    def test_cli_accepts_up_to_sixteen_workers(self):
        args = [
            "--root",
            str(self.root),
            "run",
            "--kimi-python",
            sys.executable,
            "--concurrency",
            "8",
            "--review-priority",
            "--once",
        ]
        for count in (1, 8, 16):
            with self.subTest(concurrency=count):
                with patch.object(scout, "run", return_value={}) as run:
                    self.assertEqual(scout.main([*args[:6], str(count), *args[7:]]), 0)
                self.assertEqual(run.call_args.args[0].concurrency, count)
        for count in (0, 17):
            with self.subTest(concurrency=count), self.assertRaises(SystemExit):
                scout.main([*args[:6], str(count), *args[7:]])

    def test_heartbeat_and_next_feed_visible_during_inflight_call(self):
        self.add()
        heartbeat_seen = threading.Event()
        snapshots = []
        original_write = scout.write_json

        def record(path, value):
            original_write(path, value)
            if path.name == "runtime.json":
                snapshots.append(dict(value))
                if value["state"] == "RUNNING" and value.get("attempted_this_run") == 1:
                    heartbeat_seen.set()

        def execute(root, job, *unused):
            self.assertTrue(heartbeat_seen.wait(2), "heartbeat blocked on model call")
            return self.fake_execute(root, job)

        with (
            patch.object(scout, "HEARTBEAT_SECONDS", 0.01),
            patch.object(scout, "write_json", side_effect=record),
            patch.object(scout, "collect"),
            patch.object(scout, "execute", side_effect=execute),
        ):
            scout.run(self.run_args(feeds=Path("unused")))
        active = [s for s in snapshots if s.get("attempted_this_run") == 1]
        self.assertGreater(active[0]["heartbeat_at"], snapshots[0]["heartbeat_at"])
        self.assertGreater(active[0]["next_feed_at"], active[0]["heartbeat_at"])
        self.assertIsNone(snapshots[-1]["next_feed_at"])

    def test_continuous_worker_resumes_after_rolling_cap(self):
        self.add("first")
        self.add("second")
        calls = []

        def execute(root, job, *unused):
            calls.append(job["id"])
            value = self.fake_execute(root, job)
            if len(calls) == 2:
                (root / "STOP").touch()
            return value

        def expire_window(_):
            with scout.connect(self.root) as db:
                db.execute(
                    "UPDATE jobs SET started=? WHERE state='NO_LEAD'",
                    (time.time() - 86401,),
                )

        with (
            patch.object(scout, "execute", side_effect=execute),
            patch.object(scout.time, "sleep", side_effect=expire_window),
        ):
            scout.run(self.run_args(max_jobs=1, concurrency=1, once=False))
        self.assertEqual(len(calls), 2)

    def test_stop_during_feed_prevents_dispatch(self):
        self.add()

        def stop(*unused):
            (self.root / "STOP").touch()

        with (
            patch.object(scout, "collect", side_effect=stop),
            patch.object(scout, "execute") as execute,
        ):
            scout.run(self.run_args(feeds=Path("unused")))
        execute.assert_not_called()

    def test_cooldown_is_interruptible_without_replaying_failed_jobs(self):
        for i in range(5):
            self.add(str(i))

        def fail(root, job, *unused):
            with scout.connect(root) as db:
                db.execute("UPDATE jobs SET state='FAILED' WHERE id=?", (job["id"],))
            return {"state": "FAILED", "finished": time.time()}

        def stop(_):
            (self.root / "STOP").touch()

        with (
            patch.object(scout, "execute", side_effect=fail),
            patch.object(scout.time, "sleep", side_effect=stop),
        ):
            current = scout.run(self.run_args(concurrency=1, once=False))
        self.assertEqual(current["runtime"]["attempted_this_run"], 2)
        self.assertEqual(current["runtime"]["state"], "STOPPED")
        self.assertIsNone(current["runtime"]["cooldown_until"])
        self.assertEqual(sum(j["state"] == "PENDING" for j in current["jobs"]), 3)

    def test_persistent_bad_answers_have_separate_circuit_breaker(self):
        for i in range(10):
            self.add(str(i))

        def fail(root, job, *unused):
            with scout.connect(root) as db:
                db.execute("UPDATE jobs SET state='FAILED' WHERE id=?", (job["id"],))
            return {
                "state": "FAILED",
                "failure_scope": "answer",
                "finished": time.time(),
            }

        def stop(_):
            (self.root / "STOP").touch()

        with (
            patch.object(scout, "execute", side_effect=fail),
            patch.object(scout.time, "sleep", side_effect=stop),
        ):
            current = scout.run(self.run_args(concurrency=1, once=False))
        self.assertEqual(current["runtime"]["attempted_this_run"], 8)
        self.assertEqual(sum(j["state"] == "PENDING" for j in current["jobs"]), 2)

    def test_report_feed_splits_distinct_issues(self):
        def response(url, **unused):
            if "/search/issues?" in url:
                return json.dumps(
                    {
                        "items": [
                            {
                                "html_url": f"https://github.com/a/b/issues/{i}",
                                "title": str(i),
                                "body": "public bug report",
                            }
                            for i in range(2)
                        ]
                    }
                )
            if "/commits/" in url:
                return json.dumps({"sha": "a" * 40})
            if "/issues?" in url:
                return "[]"
            return '{"private": false}'

        with (
            patch.object(scout, "fetch", side_effect=response),
            patch.object(scout, "reviewed_lessons", return_value=[]),
        ):
            packets = scout.collect_source(
                {
                    "repo": "a/b",
                    "name": "test",
                    "question": "triage",
                    "issue_limit": 8,
                    "split_reports": True,
                }
            )
        self.assertEqual(len(packets), 2)
        self.assertNotEqual(packets[0]["name"], packets[1]["name"])
        self.assertTrue(all(len(p["sources"]) == 1 for p in packets))

    def test_private_or_oversized_packet_rejected(self):
        for url in (
            "http://github.com/a",
            "https://127.0.0.1/a",
            "https://github.com.evil.test/a",
            "file:///secret",
        ):
            bad = packet()
            bad["sources"][0]["url"] = url
            with self.assertRaises(ValueError):
                scout.enqueue(self.root, bad)
        bad = packet()
        bad["sources"][0]["text"] = "x" * 25000
        with self.assertRaises(ValueError):
            scout.enqueue(self.root, bad)

    def test_exact_evidence_required_no_invented_ready(self):
        self.assertEqual(scout.validate_result(result(), packet())["decision"], "lead")
        for change in (
            {"decision": "READY"},
            {"evidence": []},
            {"evidence": [{"url": "https://github.com/fake", "quote": "x"}]},
        ):
            with self.assertRaises(ValueError):
                scout.validate_result(dict(result(), **change), packet())
        bad = result()
        bad["evidence"][0]["quote"] = "imaginary measured speedup"
        with self.assertRaises(ValueError):
            scout.validate_result(bad, packet())

    def test_json_fence_only_no_arbitrary_prose(self):
        value = json.dumps(result())
        self.assertEqual(scout.parse_answer(value), result())
        self.assertEqual(scout.parse_answer("```json\n" + value + "\n```"), result())
        with self.assertRaises(ValueError):
            scout.parse_answer("I ran everything! " + value)

    def test_multiline_quote_can_omit_number_prefix_only(self):
        value = result()
        value["evidence"][0]["quote"] = "return values[index] + 1"
        source = packet()
        source["sources"][0]["text"] = "12: return values[index]\n13:     + 1"
        self.assertEqual(scout.validate_result(value, source), value)
        value["evidence"][0]["quote"] = "return values[index] + 2"
        with self.assertRaises(ValueError):
            scout.validate_result(value, source)

    def test_multiple_windows_of_one_url_remain_individually_quotable(self):
        source = packet()
        url = source["sources"][0]["url"]
        source["sources"].append(
            {"url": url, "text": "80: assert index >= 0", "truncated": True}
        )
        for quote in ("return values[index]", "assert index >= 0"):
            value = result()
            value["evidence"] = [{"url": url, "quote": quote}]
            self.assertEqual(scout.validate_result(value, source), value)
        value["evidence"][0]["quote"] = "return values[index] assert index >= 0"
        with self.assertRaises(ValueError):
            scout.validate_result(value, source)

    def test_automatic_feed_rejects_private_repository(self):
        with patch.object(scout, "fetch", return_value='{"private": true}'):
            with self.assertRaisesRegex(ValueError, "private"):
                scout.collect_source({"repo": "owner/private"}, True)

    def test_invalid_answer_preserved_as_untrusted(self):
        self.add()
        job = scout.claim(self.root, 12, 200000, 2048)
        response = {
            "ok": True,
            "text": "{}",
            "tools_advertised": 0,
            "tool_calls_executed": 0,
            "finish_reason": "stop",
            "usage": {"total_tokens": 321},
        }
        with patch.object(
            scout.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, json.dumps(response), ""),
        ):
            receipt = scout.execute(self.root, job, sys.executable, 30, 2048)
        self.assertEqual(receipt["error"], "unexpected result fields")
        self.assertEqual(receipt["charged_tokens_or_reservation"], 321)
        raw = json.loads(
            (self.root / "results" / (job["id"] + ".answer.json")).read_text()
        )
        self.assertTrue(raw["untrusted"])
        self.assertEqual(raw["text"], "{}")

    def test_success_is_only_review_and_records_usage(self):
        self.add()
        job = scout.claim(self.root, 12, 200000, 2048)
        response = {
            "ok": True,
            "text": json.dumps(result()),
            "usage": {"total_tokens": 321},
            "model_alias": "test",
            "tools_advertised": 0,
            "tool_calls_executed": 0,
        }
        with patch.object(
            scout.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, json.dumps(response), ""),
        ) as run:
            receipt = scout.execute(self.root, job, sys.executable, 30, 2048)
        self.assertEqual(receipt["state"], "REVIEW")
        self.assertFalse(receipt["result"]["qualified"])
        self.assertEqual(receipt["charged_tokens_or_reservation"], 321)
        self.assertIn("-I", run.call_args.args[0])
        self.assertNotIn("shell", run.call_args.kwargs)
        request = json.loads(run.call_args.kwargs["input"])
        self.assertEqual(request["max_output_tokens"], 2048)
        self.assertIn(scout.SYSTEM, request["prompt"])
        recorded = json.loads(
            (self.root / "results" / f"{job['id']}.request.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(recorded, request)
        arguments = run.call_args.args[0]
        live = Path(arguments[arguments.index("--progress-file") + 1])
        self.assertTrue(live.is_absolute())
        self.assertEqual(live, self.root / "results" / f"{job['id']}.live.json")
        self.assertNotIn("api_key", json.dumps(recorded))

    def test_execute_resolves_relative_root_before_changing_subprocess_cwd(self):
        self.add()
        job = scout.claim(self.root, 12, 200000, 2048)
        response = {
            "ok": True,
            "text": json.dumps(result()),
            "tools_advertised": 0,
            "tool_calls_executed": 0,
        }
        previous = Path.cwd()
        try:
            os.chdir(self.root.parent)
            with patch.object(
                scout.subprocess,
                "run",
                return_value=subprocess.CompletedProcess(
                    [], 0, json.dumps(response), ""
                ),
            ) as run:
                receipt = scout.execute(
                    Path(self.root.name), job, sys.executable, 30, 2048
                )
        finally:
            os.chdir(previous)
        self.assertEqual(receipt["state"], "REVIEW")
        self.assertTrue(run.call_args.kwargs["cwd"].is_absolute())
        arguments = run.call_args.args[0]
        self.assertEqual(
            Path(arguments[arguments.index("--progress-file") + 1]),
            self.root / "results" / f"{job['id']}.live.json",
        )

    def test_failure_and_timeout_not_retried_or_secret_logged(self):
        for name, response in (
            ("exit", subprocess.CompletedProcess([], 1, "secret", "api_key=SECRET")),
            ("timeout", subprocess.TimeoutExpired("secret", 30)),
        ):
            self.add(name)
            job = scout.claim(self.root, 12, 200000, 2048)
            kwargs = (
                {"side_effect": response}
                if isinstance(response, Exception)
                else {"return_value": response}
            )
            with patch.object(scout.subprocess, "run", **kwargs):
                receipt = scout.execute(self.root, job, sys.executable, 30, 2048)
            self.assertEqual(receipt["state"], "FAILED")
            self.assertEqual(receipt["charged_tokens_or_reservation"], job["charge"])
            self.assertNotIn("secret", json.dumps(receipt).lower())
            recorded = (self.root / "results" / f"{job['id']}.request.json").read_text(
                encoding="utf-8"
            )
            self.assertNotIn("secret", recorded.lower())
            live = (self.root / "results" / f"{job['id']}.live.json").read_text(
                encoding="utf-8"
            )
            self.assertEqual(json.loads(live)["phase"], "failed")
            self.assertNotIn("secret", live.lower())
        self.assertIsNone(scout.claim(self.root, 12, 200000, 2048))

    def test_timeout_preserves_only_visible_partial_progress(self):
        self.add()
        job = scout.claim(self.root, 12, 200000, 2048)
        path = self.root / "results" / f"{job['id']}.live.json"

        def timeout(*unused, **kwargs):
            scout.write_json(
                path,
                {
                    "text": "partial answer",
                    "phase": "streaming",
                    "updated_at": time.time(),
                },
            )
            raise subprocess.TimeoutExpired("private command", 30, stderr="SECRET")

        with patch.object(scout.subprocess, "run", side_effect=timeout):
            receipt = scout.execute(self.root, job, sys.executable, 30, 2048)
        self.assertEqual(receipt["state"], "FAILED")
        live = json.loads(path.read_text())
        self.assertEqual(live["text"], "partial answer")
        self.assertEqual(live["phase"], "failed")
        self.assertNotIn("SECRET", path.read_text())

    def test_unexpected_tool_capability_is_rejected(self):
        self.add()
        job = scout.claim(self.root, 12, 200000, 2048)
        response = {
            "ok": True,
            "text": json.dumps(result()),
            "tools_advertised": 1,
            "tool_calls_executed": 0,
        }
        with patch.object(
            scout.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, json.dumps(response), ""),
        ):
            self.assertEqual(
                scout.execute(self.root, job, sys.executable, 30, 2048)["state"],
                "FAILED",
            )

    def test_safe_fixed_remote_fetch(self):
        for url in (
            "https://localhost/",
            "https://api.github.com@evil.test/",
            "https://api.github.com:443/x",
            "file:///secret",
        ):
            with self.assertRaises(ValueError):
                scout.fetch(url)
        with self.assertRaises(ValueError):
            scout.NoRedirect().redirect_request(None, None, None, None, None, None)

    def test_single_runner_lock(self):
        with scout.single_runner(self.root):
            with self.assertRaises(OSError):
                with scout.single_runner(self.root):
                    self.fail("duplicate runner admitted")

    def test_stop_cli_does_not_touch_other_processes(self):
        self.assertEqual(scout.main(["--root", str(self.root), "stop"]), 0)
        self.assertTrue((self.root / "STOP").exists())
        self.assertTrue(scout.status(self.root)["stop_requested"])


if __name__ == "__main__":
    unittest.main()
