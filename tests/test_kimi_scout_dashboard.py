"""Local-only viewer checks: no model, external network or GPU calls."""

import importlib.util
import json
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dashboard = load("kimi_scout_dashboard")
scout = load("kimi_scout")


class DashboardTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        scout.initialize(self.root)
        self.packet = {
            "name": "public issue review",
            "repo": "a/b",
            "question": "Review a public snippet",
            "sources": [{"url": "https://github.com/a/b/issues/1", "text": "return x"}],
        }
        self.job_id = scout.enqueue(self.root, self.packet)
        self.inbox = dashboard.Inbox(self.root)

    def artifact(self, suffix, value):
        scout.write_json(self.root / "results" / f"{self.job_id}.{suffix}.json", value)

    def test_read_only_database(self):
        before = (self.root / "scout.sqlite").read_bytes()
        self.assertEqual(self.inbox.state()["summary"]["total_jobs"], 1)
        self.assertEqual(self.inbox.detail(self.job_id)["packet"], self.packet)
        self.assertEqual(before, (self.root / "scout.sqlite").read_bytes())
        with closing(sqlite3.connect(self.root / "scout.sqlite")) as db:
            self.assertEqual(
                db.execute("SELECT state FROM jobs").fetchone()[0], "PENDING"
            )

    @unittest.skipUnless(
        shutil.which("node"), "Node is needed for the offline DOM test"
    )
    def test_worker_cards_follow_runtime_concurrency_up_to_sixteen(self):
        page = (SCRIPTS / "kimi_scout_dashboard.html").read_text(encoding="utf-8")
        script = page.split("<script>", 1)[1].split("</script>", 1)[0]
        # Execute the actual overview renderer with a tiny DOM, without polling.
        overview = script.split("  function renderHistory() {", 1)[0]
        harness = """
const elements = new Map();
function element() {
  return {
    children: [], firstElementChild: {},
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; },
    addEventListener() {},
  };
}
global.document = {
  createElement: element,
  getElementById(id) {
    if (!elements.has(id)) elements.set(id, element());
    return elements.get(id);
  },
};
"""
        exercise = """
  function renderHistory() {}
  const observations = [];
  for (const count of [1, 8, 16, 32]) {
    state = {
      summary: {counts: {RUNNING: count}},
      runtime: {concurrency: count, alive: true, state: "RUNNING"},
      jobs: Array.from({length: count}, (_, i) => ({
        id: String(i), name: "job-" + i, state: "RUNNING", started: i + 1,
      })),
    };
    renderOverview();
    const cards = elements.get("workers").children;
    observations.push({
      count: cards.length,
      last: cards.at(-1).children[1].textContent,
      warning: elements.get("warnings").textContent,
    });
  }
  process.stdout.write(JSON.stringify(observations));
})();
"""
        result = subprocess.run(
            [shutil.which("node"), "-"],
            input=harness + overview + exercise,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=10,
            check=True,
        )
        values = json.loads(result.stdout)
        self.assertEqual([value["count"] for value in values], [1, 8, 16, 16])
        self.assertEqual(values[2]["last"], "job-15")
        self.assertEqual(values[2]["warning"], "")
        self.assertTrue(values[3]["warning"])

    def test_actual_usage_not_reservations_including_failed_answers(self):
        with scout.connect(self.root) as db:
            db.execute("UPDATE jobs SET state='FAILED',charge=30000")
        summary = self.inbox.state()["summary"]
        self.assertEqual(summary["reported_tokens"], 0)
        self.assertEqual(summary["reserved_tokens"], 30000)
        self.artifact(
            "answer",
            {
                "text": "invalid JSON",
                "usage": {
                    "total_tokens": 123,
                    "input_tokens": 100,
                    "output_tokens": 23,
                },
            },
        )
        summary = self.inbox.state()["summary"]
        self.assertEqual(summary["reported_tokens"], 123)
        self.assertEqual(summary["reserved_tokens"], 0)
        self.assertEqual(summary["usage_known_jobs"], 1)
        self.assertEqual(
            self.inbox.state()["activity"]["repos"][0]["reported_tokens"], 123
        )

    def test_activity_aggregates_beyond_display_limit_and_includes_empty_repos(self):
        now = 10000
        scout.write_json(self.root / "research.json", {
            "goals": [{"repo": "zero/repo"}, {"repo": "zero/repo"}]
        })
        with scout.connect(self.root) as db:
            db.execute("UPDATE jobs SET created=?", (now - 2000,))
            db.executemany(
                "INSERT INTO jobs (id,name,packet,state,created,started,finished,result) "
                "VALUES (?,?,?,?,?,?,?,?)",
                [
                    (
                        f"{index:024x}",
                        f"job-{index}",
                        json.dumps({
                            "repo": "many/jobs",
                            "research": {"stage": "reproduction_plan"},
                        }),
                        "REVIEW" if index == 0 else "FAILED" if index == 1 else "NO_LEAD",
                        now - 1000 + index,
                        now - 30,
                        now - 10,
                        json.dumps({"usage": {"total_tokens": 10}}),
                    )
                    for index in range(501)
                ],
            )
        with patch.object(dashboard.time, "time", return_value=now):
            state = self.inbox.state()
        self.assertEqual(len(state["jobs"]), 500)
        self.assertNotIn(self.job_id, {job["id"] for job in state["jobs"]})
        activity = state["activity"]
        self.assertEqual(activity["window_seconds"], 900)
        self.assertEqual(activity["observed_seconds"], 900)
        self.assertEqual(activity["completed"], 501)
        self.assertAlmostEqual(activity["completed_per_minute"], 33.4)
        self.assertEqual(activity["failed"], 1)
        self.assertEqual(activity["average_elapsed_seconds"], 20)
        self.assertEqual(activity["last_completion"], now - 10)
        self.assertEqual(activity["review_leaves"], 1)
        self.assertEqual(activity["reproduction_leaves"], 1)
        repos = {repo["repo"]: repo for repo in activity["repos"]}
        self.assertEqual(set(repos), {"a/b", "many/jobs", "zero/repo"})
        self.assertEqual(repos["a/b"]["pending"], 1)
        self.assertEqual(repos["many/jobs"]["total"], 501)
        self.assertEqual(repos["many/jobs"]["completed"], 501)
        self.assertEqual(repos["many/jobs"]["failed"], 1)
        self.assertEqual(repos["many/jobs"]["reported_tokens"], 5010)
        self.assertEqual(repos["many/jobs"]["review_leaves"], 1)
        self.assertEqual(repos["zero/repo"]["total"], 0)
        self.assertIsNone(repos["zero/repo"]["last_finished"])

    def test_stored_usage_skips_answer_artifact_reads(self):
        with scout.connect(self.root) as db:
            db.execute(
                "UPDATE jobs SET result=?",
                (json.dumps({"usage": {"total_tokens": 7}}),),
            )
        with patch.object(self.inbox, "artifact") as artifact:
            state = self.inbox.state()
        artifact.assert_not_called()
        self.assertEqual(state["summary"]["reported_tokens"], 7)
        self.assertEqual(state["activity"]["repos"][0]["reported_tokens"], 7)

    def test_activity_leaf_exclusion_uses_children_in_every_state(self):
        child_id = scout.enqueue(self.root, {
            **self.packet,
            "name": "cross-repo child",
            "repo": "child/repo",
            "research": {
                "parent_job_id": self.job_id,
                "stage": "reproduction_plan",
            },
        })
        with scout.connect(self.root) as db:
            db.execute("UPDATE jobs SET state='REVIEW' WHERE id=?", (self.job_id,))
        for child_state in ("PENDING", "RUNNING", "FAILED", "NO_LEAD", "REVIEW"):
            with self.subTest(state=child_state):
                with scout.connect(self.root) as db:
                    db.execute("UPDATE jobs SET state=? WHERE id=?", (child_state, child_id))
                activity = self.inbox.state()["activity"]
                expected = int(child_state == "REVIEW")
                self.assertEqual(activity["review_leaves"], expected)
                self.assertEqual(activity["reproduction_leaves"], expected)
                self.assertEqual(activity["repos"][0]["review_leaves"], 0)
        scout.enqueue(self.root, {
            **self.packet,
            "name": "pending grandchild",
            "research": {"parent_job_id": child_id},
        })
        self.assertEqual(self.inbox.state()["activity"]["review_leaves"], 0)

    def test_activity_recent_window_boundaries_and_last_completion(self):
        now = 10000
        with scout.connect(self.root) as db:
            db.execute(
                "UPDATE jobs SET state='FAILED',created=?,started=?,finished=?",
                (now - 2000, now - 920, now - 900),
            )
        with patch.object(dashboard.time, "time", return_value=now):
            activity = self.inbox.state()["activity"]
        self.assertEqual(activity["completed"], 1)
        self.assertEqual(activity["failed"], 1)
        self.assertEqual(activity["average_elapsed_seconds"], 20)
        for finished in (now - 901, now + 1):
            with self.subTest(finished=finished):
                with scout.connect(self.root) as db:
                    db.execute("UPDATE jobs SET finished=?", (finished,))
                with patch.object(dashboard.time, "time", return_value=now):
                    activity = self.inbox.state()["activity"]
                self.assertEqual(activity["completed"], 0)
                self.assertEqual(activity["completed_per_minute"], 0)
                self.assertEqual(activity["failed"], 0)
                self.assertIsNone(activity["average_elapsed_seconds"])
                self.assertEqual(activity["last_completion"], finished)

    def test_activity_short_observation_and_empty_inbox(self):
        now = 10000
        with scout.connect(self.root) as db:
            db.execute(
                "UPDATE jobs SET state='NO_LEAD',created=?,started=?,finished=?",
                (now - 30, now - 10, now - 5),
            )
        with patch.object(dashboard.time, "time", return_value=now):
            activity = self.inbox.state()["activity"]
        self.assertEqual(activity["observed_seconds"], 30)
        self.assertEqual(activity["completed_per_minute"], 2)
        for created in (now, now + 1):
            with self.subTest(created=created):
                with scout.connect(self.root) as db:
                    db.execute("UPDATE jobs SET created=?", (created,))
                with patch.object(dashboard.time, "time", return_value=now):
                    activity = self.inbox.state()["activity"]
                self.assertEqual(activity["observed_seconds"], 0)
                self.assertEqual(activity["completed_per_minute"], 0)
        with scout.connect(self.root) as db:
            db.execute("DELETE FROM jobs")
        with patch.object(dashboard.time, "time", return_value=now):
            activity = self.inbox.state()["activity"]
        self.assertEqual(activity["observed_seconds"], 0)
        self.assertEqual(activity["completed"], 0)
        self.assertEqual(activity["completed_per_minute"], 0)
        self.assertEqual(activity["repos"], [])
        self.assertIsNone(activity["average_elapsed_seconds"])
        self.assertIsNone(activity["last_completion"])

    def test_legacy_prompts_are_explicitly_reconstructed(self):
        detail = self.inbox.detail(self.job_id)
        self.assertTrue(detail["prompt_reconstructed"])
        self.assertIsNone(self.inbox.state()["research"])
        for key in ("stage", "parent_job_id", "root_job_id"):
            self.assertIsNone(detail["job"][key])
        self.artifact("request", {"prompt": "exact saved prompt"})
        detail = self.inbox.detail(self.job_id)
        self.assertFalse(detail["prompt_reconstructed"])
        self.assertEqual(detail["prompt"], "exact saved prompt")

    def test_research_snapshot_and_review_chain_counts_are_read_only(self):
        snapshot = {
            "enabled": True,
            "objective": "Investigate public source evidence",
            "phase": "WAITING_FOR_NEW_EVIDENCE",
            "updated_at": time.time(),
            "queue_target": 24,
            "queued": 3,
            "followups_created": 2,
            "discovery_created": 1,
            "scanned_sources": 7,
            "next_scan_at": time.time() + 600,
            "last_error": None,
            "goals": [
                {"repo": "a/b", "scanned_sources": 7, "available_sources": 10, "issue_page": 2}
            ],
        }
        scout.write_json(self.root / "research.json", snapshot)
        child = {
            **self.packet,
            "name": "follow up source",
            "research": {
                "stage": "source_followup",
                "parent_job_id": self.job_id,
                "root_job_id": self.job_id,
                "depth": 1,
                "objective": snapshot["objective"],
            },
        }
        child_id = scout.enqueue(self.root, child)
        with scout.connect(self.root) as db:
            db.execute("UPDATE jobs SET state='REVIEW'")
        before = (self.root / "research.json").read_bytes()
        state = self.inbox.state()
        self.assertEqual(state["research"], snapshot)
        self.assertEqual(state["summary"]["total_jobs"], 2)
        self.assertEqual(state["summary"]["counts"]["REVIEW"], 2)
        self.assertEqual(state["summary"]["candidate_roots"], 1)
        detail = self.inbox.detail(child_id)
        for key in ("stage", "parent_job_id", "root_job_id"):
            self.assertEqual(detail["job"][key], child["research"][key])
        self.assertEqual(before, (self.root / "research.json").read_bytes())

    def test_research_snapshot_is_optional_and_confined(self):
        self.assertIsNone(self.inbox.state()["research"])
        snapshot = self.root / "research.json"
        for content in ("{", "[]", "null", "{}"):
            with self.subTest(content=content):
                snapshot.write_text(content, encoding="utf-8")
                self.assertIsNone(self.inbox.state()["research"])
        snapshot.unlink()
        with tempfile.TemporaryDirectory() as other:
            secret = Path(other) / "provider.json"
            secret.write_text('{"private":"never"}', encoding="utf-8")
            try:
                snapshot.symlink_to(secret)
            except OSError:
                self.skipTest("Symlinks require privileges on this Windows account")
            self.assertIsNone(self.inbox.state()["research"])

    def test_delivery_snapshot_is_optional_and_size_bounded(self):
        self.assertIsNone(self.inbox.state()["delivery"])
        directory = self.root / "delivery"
        directory.mkdir()
        snapshot = directory / "runtime.json"
        for content in ("{", "[]", "null", "{}"):
            with self.subTest(content=content):
                snapshot.write_text(content, encoding="utf-8")
                self.assertIsNone(self.inbox.state()["delivery"])
        snapshot.write_text('{"state":"RUNNING"}', encoding="utf-8")
        with patch.object(dashboard, "MAX_FILE_BYTES", 4):
            self.assertIsNone(self.inbox.state()["delivery"])

    def test_delivery_snapshot_cannot_follow_a_directory_outside_root(self):
        with tempfile.TemporaryDirectory() as other:
            (Path(other) / "runtime.json").write_text(
                '{"private":"never"}', encoding="utf-8"
            )
            try:
                (self.root / "delivery").symlink_to(other, target_is_directory=True)
            except OSError:
                self.skipTest("Symlinks require privileges on this Windows account")
            self.assertIsNone(self.inbox.state()["delivery"])

    def test_delivery_snapshot_is_read_only_and_separate_from_search(self):
        now = 10000
        path = self.root / "delivery" / "runtime.json"
        path.parent.mkdir()
        snapshot = {
            "pid": 123, "state": "RUNNING", "heartbeat_at": now - 5,
            "concurrency": 4, "execution_concurrency": 2, "active": 2,
            "counts": {"REPRODUCED": 1, "NO_BUG": 1}, "reported_tokens": 987,
            "jobs": [None] + [{"id": str(index)} for index in range(21)],
        }
        scout.write_json(path, snapshot)
        before = path.read_bytes()
        with (
            patch.object(dashboard.time, "time", return_value=now),
            patch.object(dashboard, "process_alive", side_effect=lambda pid: pid == 123),
        ):
            state = self.inbox.state()
        delivery = state["delivery"]
        self.assertTrue(delivery["alive"])
        self.assertTrue(delivery["heartbeat_fresh"])
        self.assertEqual(delivery["jobs"], [{"id": str(index)} for index in range(20)])
        self.assertEqual(delivery["counts"], snapshot["counts"])
        self.assertEqual(delivery["concurrency"], 4)
        self.assertEqual(delivery["execution_concurrency"], 2)
        self.assertEqual(state["summary"]["counts"], {"PENDING": 1})
        self.assertEqual(state["summary"]["reported_tokens"], 0)
        self.assertEqual(path.read_bytes(), before)
        for alive, status, heartbeat, expected_status, fresh in (
            (False, "RUNNING", now, "OFFLINE", True),
            (False, "STOPPED", now, "STOPPED", True),
            (True, "RUNNING", now - 181, "RUNNING", False),
            (True, "RUNNING", now + 1, "RUNNING", False),
            (True, "RUNNING", "invalid", "RUNNING", False),
        ):
            with self.subTest(alive=alive, status=status, heartbeat=heartbeat):
                scout.write_json(path, {
                    **snapshot, "state": status, "heartbeat_at": heartbeat,
                    "jobs": "invalid",
                })
                with (
                    patch.object(dashboard.time, "time", return_value=now),
                    patch.object(dashboard, "process_alive", return_value=alive),
                ):
                    delivery = self.inbox.state()["delivery"]
                self.assertEqual(delivery["state"], expected_status)
                self.assertEqual(delivery["heartbeat_fresh"], fresh)
                self.assertEqual(delivery["jobs"], [])

    @unittest.skipUnless(shutil.which("node"), "Node is needed for the offline DOM test")
    def test_delivery_render_is_text_only_separate_and_honest_about_evidence(self):
        page = (SCRIPTS / "kimi_scout_dashboard.html").read_text(encoding="utf-8")
        script = page.split("<script>", 1)[1].split("</script>", 1)[0]
        overview = script.split("  function renderHistory() {", 1)[0]
        harness = """
const elements = new Map();
function element() {
  return {
    children: [], firstElementChild: {}, listeners: {},
    set innerHTML(value) { throw Error("HTML injection sink used"); },
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; },
    addEventListener(event, callback) { this.listeners[event] = callback; },
  };
}
global.document = {
  createElement: element,
  getElementById(id) {
    if (!elements.has(id)) elements.set(id, element());
    return elements.get(id);
  },
};
function collect(el) {
  return [el.textContent || "", ...el.children.map(collect)].join(" ");
}
"""
        exercise = """
  function renderHistory() {}
  let selected = null;
  function selectJob(id) { selected = id; }
  state = {
    summary: {counts: {}}, jobs: [],
    runtime: {concurrency: 12, alive: true, state: "RUNNING"},
    delivery: {
      alive: true, heartbeat_fresh: true, state: "RUNNING", active: 2,
      concurrency: 4, execution_concurrency: 2, reported_tokens: 1234,
      counts: {PENDING: 3, REPRODUCED: 1, NO_BUG: 1},
      jobs: [
        {title: "<script>alert(1)</script>", repo: "<img src=x>",
         state: "REPRODUCED", reason: "<b>old fails/new passes</b>",
         source_job_id: "a".repeat(24), tests_run: 2, baseline_exit: 1, candidate_exit: 0},
        {title: "judgment only", state: "NO_BUG", source_job_id: "javascript:alert(1)"},
        ...Array.from({length: 21}, (_, i) => ({id: "job-" + i, state: "PENDING"})),
      ],
    },
  };
  renderOverview();
  const rows = elements.get("deliveryJobs").children;
  rows[0].children.at(-1).listeners.click();
  const values = {
    hidden: elements.get("deliveryPanel").hidden,
    capacity: elements.get("deliveryCapacity").textContent,
    executions: elements.get("deliveryExecutionLimit").textContent,
    finderCount: elements.get("workers").children.length,
    finderHeading: elements.get("workersHeading").textContent,
    count: rows.length, first: collect(rows[0]), second: collect(rows[1]), selected,
    secondHasButton: rows[1].children.some(child => child.listeners.click),
    reproduced: elements.get("deliveryReproduced").textContent,
  };
  state.delivery.heartbeat_fresh = false;
  renderDelivery();
  values.staleCapacity = elements.get("deliveryCapacity").textContent;
  values.staleNote = elements.get("deliveryActivity").textContent;
  values.staleState = elements.get("deliveryState").textContent;
  state.delivery = null;
  renderDelivery();
  values.absentHidden = elements.get("deliveryPanel").hidden;
  process.stdout.write(JSON.stringify(values));
})();
"""
        result = subprocess.run(
            [shutil.which("node"), "-"], input=harness + overview + exercise,
            text=True, encoding="utf-8", capture_output=True, timeout=10, check=True,
        )
        values = json.loads(result.stdout)
        self.assertFalse(values["hidden"])
        self.assertEqual(values["capacity"], "2 / 4")
        self.assertEqual(values["executions"], "2")
        self.assertEqual(values["finderCount"], 12)
        self.assertEqual(values["finderHeading"], "搜索 / 反证槽位 · 12 并发")
        self.assertEqual(values["count"], 20)
        for literal in (
            "<script>alert(1)</script>", "<img src=x>", "<b>old fails/new passes</b>",
            "旧失败 / 新通过 · 待复核", "退出码 1 → 0", "测试数 2",
        ):
            self.assertIn(literal, values["first"])
        self.assertIn("仅有模型判断，尚无无缺陷证明", values["second"])
        self.assertFalse(values["secondHasButton"])
        self.assertEqual(values["selected"], "a" * 24)
        self.assertEqual(values["reproduced"], "1")
        self.assertEqual(values["staleCapacity"], "— / 4")
        self.assertIn("不代表正在执行", values["staleNote"])
        self.assertEqual(values["staleState"], "心跳待确认")
        self.assertTrue(values["absentHidden"])

    def test_malformed_research_metadata_preserves_old_jobs(self):
        for metadata in (
            None, [], "invalid", {"root_job_id": ["not", "an", "id"]},
            {"parent_job_id": ["not", "an", "id"]},
        ):
            with self.subTest(metadata=metadata):
                with scout.connect(self.root) as db:
                    db.execute(
                        "UPDATE jobs SET state='REVIEW',packet=?",
                        (json.dumps({**self.packet, "research": metadata}),),
                    )
                self.assertEqual(self.inbox.state()["summary"]["candidate_roots"], 1)
                self.assertEqual(self.inbox.detail(self.job_id)["job"]["repo"], "a/b")

    def test_live_partial_and_malformed_file(self):
        with scout.connect(self.root) as db:
            db.execute("UPDATE jobs SET state='RUNNING',started=?", (time.time() - 10,))
        self.artifact(
            "live",
            {
                "text": "partial <script>alert(1)</script>",
                "phase": "streaming",
                "updated_at": time.time(),
                "unexpected": "not exposed",
            },
        )
        detail = self.inbox.detail(self.job_id)
        self.assertEqual(detail["live"]["phase"], "streaming")
        self.assertNotIn("unexpected", detail["live"])
        self.assertTrue(detail["job"]["has_live_output"])
        self.assertGreaterEqual(detail["job"]["elapsed_seconds"], 10)
        (self.root / "results" / f"{self.job_id}.live.json").write_text(
            "{", encoding="utf-8"
        )
        self.assertIsNone(self.inbox.detail(self.job_id)["live"])

    def test_dead_and_stale_runner_are_not_silently_running(self):
        scout.write_json(
            self.root / "runtime.json",
            {"pid": 123, "state": "RUNNING", "heartbeat_at": time.time() - 500},
        )
        with patch.object(dashboard, "process_alive", return_value=False):
            state = self.inbox.state()
            self.assertEqual(state["runtime"]["state"], "OFFLINE")
            self.assertTrue(state["warnings"])
        with patch.object(dashboard, "process_alive", return_value=True):
            self.assertIn("心跳", self.inbox.state()["warnings"][0])

    def test_reject_arbitrary_paths_and_symlink_escape(self):
        for value in ("../runtime.json", "1", "a" * 24 + "/secret", "a" * 23):
            with self.assertRaises(KeyError):
                self.inbox.detail(value)
        with tempfile.TemporaryDirectory() as other:
            path = Path(other) / "secret.json"
            path.write_text('{"private":"never"}', encoding="utf-8")
            self.assertEqual(dashboard.read_artifact(self.root, str(path)), {})
            link = self.root / "results" / f"{self.job_id}.answer.json"
            try:
                link.symlink_to(path)
            except OSError:
                return  # Some Windows accounts lack symlink privileges.
            self.assertEqual(self.inbox.artifact(self.job_id, "answer"), {})

    def test_read_only_http_routes_headers_and_origin(self):
        scout.write_json(self.root / "research.json", {"enabled": True, "phase": "READY"})
        (self.root / "delivery").mkdir()
        scout.write_json(self.root / "delivery" / "runtime.json", {
            "state": "STOPPED", "concurrency": 4, "execution_concurrency": 2,
        })
        scout.write_json(self.root / "provider.json", {"private": "never"})
        server = dashboard.make_server(self.root, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with urlopen(base + "/api/state", timeout=3) as response:
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                self.assertNotIn("Access-Control-Allow-Origin", response.headers)
                state = json.load(response)
                self.assertEqual(state["summary"]["total_jobs"], 1)
                self.assertEqual(state["research"], {"enabled": True, "phase": "READY"})
                self.assertEqual(state["delivery"]["state"], "STOPPED")
                self.assertFalse(state["delivery"]["alive"])
                self.assertEqual(state["delivery"]["execution_concurrency"], 2)
                self.assertNotIn("never", json.dumps(state))
            with urlopen(base + "/api/state?research=provider.json", timeout=3) as response:
                self.assertNotIn("never", response.read().decode("utf-8"))
            for path, headers, method, status in (
                ("/api/state", {"Host": "evil.example"}, "GET", 403),
                ("/api/state", {"Origin": "https://evil.example"}, "GET", 403),
                ("/api/jobs/../../config.toml", {}, "GET", 404),
                ("/runtime.json", {}, "GET", 404),
                ("/research.json", {}, "GET", 404),
                ("/delivery/runtime.json", {}, "GET", 404),
                ("/provider.json", {}, "GET", 404),
                ("/api/stop", {}, "POST", 501),
                ("/api/research", {}, "POST", 501),
                ("/api/delivery", {}, "POST", 501),
            ):
                with (
                    self.subTest(path=path, method=method),
                    self.assertRaises(HTTPError) as error,
                ):
                    urlopen(
                        Request(base + path, headers=headers, method=method), timeout=3
                    )
                self.assertEqual(error.exception.code, status)
            with urlopen(base + "/api/jobs/" + self.job_id, timeout=3) as response:
                self.assertEqual(json.load(response)["packet"], self.packet)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_unknown_usage_never_invented(self):
        for value in (None, {}, {"total_tokens": True}, {"total_tokens": -1}):
            self.assertIsNone(dashboard.valid_usage(value))
        self.assertEqual(
            dashboard.valid_usage({"total_tokens": 0}), {"total_tokens": 0}
        )


if __name__ == "__main__":
    unittest.main()
