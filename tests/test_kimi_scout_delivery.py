"""Offline delivery-queue and repair-loop tests; no model, Docker or network."""

import io
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout_delivery as delivery

SOURCE = "def value():\n    return 1\n"
TEST = """import unittest
import subject
class Tests(unittest.TestCase):
    def test_regression(self): self.assertEqual(subject.value(), 2)
    def test_normal(self): self.assertIsInstance(subject.value(), int)
"""


def proposal():
    return {
        "decision": "test",
        "reason": "fixture",
        "test_code": TEST,
        "edits": [{"old": "return 1", "new": "return 2"}],
    }


def lead(number=1):
    return {
        "id": str(number),
        "repo": "public/project",
        "commit": "a" * 40,
        "canonical_key": "hypothesis" + str(number),
        "packet": {},
        "analysis": {"title": "fixture", "hypothesis": "small fixture"},
    }


def result(before=1, fixed=0, *, count=2, output="", cleanup=True):
    return {
        "inconclusive": False,
        "before": {
            "exit_code": before,
            "reported_tests_run": count,
            "output": output,
            "cleanup_ok": cleanup,
        },
        "fixed": {
            "exit_code": fixed,
            "reported_tests_run": count,
            "output": "",
            "cleanup_ok": cleanup,
        },
    }


class DeliveryTests(unittest.TestCase):
    def test_cpu_prompt_checks_dtype_and_singleton_contract_without_forcing_unsupported_dtypes(self):
        self.assertIn("broadcasting may change promotion and output dtype", delivery.PROMPT)
        self.assertIn("singleton reference parity", delivery.PROMPT)
        self.assertIn("only dtypes actually supported", delivery.PROMPT)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.inbox = Path(self.temp.name)
        self.args = SimpleNamespace(
            root=self.inbox,
            concurrency=4,
            execution_concurrency=2,
            owner_queue_limit=64,
            github_auth=False,
            kimi_python=Path(sys.executable),
            wsl="Ubuntu",
        )
        self.worker = delivery.Delivery(self.args)
        delivery.initialize(self.worker.root)

    def test_admission_deduplicates_and_atomic_parallel_claims_are_unique(self):
        self.assertEqual(
            delivery.stage(self.worker.root, [lead(i) for i in range(12)], 8), 8
        )
        self.assertEqual(delivery.stage(self.worker.root, [lead(0)]), 0)
        with ThreadPoolExecutor(max_workers=4) as pool:
            jobs = list(pool.map(lambda _: delivery.claim(self.worker.root), range(10)))
        ids = [j["id"] for j in jobs if j]
        self.assertEqual(len(ids), 8)
        self.assertEqual(len(set(ids)), 8)

    def test_memory_admission_reserves_inflight_headroom_and_handles_unknown(self):
        self.args.min_free_memory_mb = 2048
        self.args.worker_memory_mb = 256
        with patch.object(delivery.scout, "available_memory_mb", return_value=2560):
            self.assertTrue(self.worker.memory_admits_work(0))
            self.assertTrue(self.worker.memory_admits_work(1))
            self.assertFalse(self.worker.memory_admits_work(2))
        with patch.object(delivery.scout, "available_memory_mb", return_value=None):
            self.assertFalse(self.worker.memory_admits_work(0))
        self.args.min_free_memory_mb = self.args.worker_memory_mb = 0
        with patch.object(delivery.scout, "available_memory_mb") as probe:
            self.assertTrue(self.worker.memory_admits_work(3))
            probe.assert_not_called()

    def test_memory_pause_does_not_claim_queued_work_and_remains_visible(self):
        self.args.max_jobs = 0
        self.args.min_free_memory_mb = 2048
        self.args.worker_memory_mb = 256
        delivery.stage(self.worker.root, [lead(1)], 1)
        with (
            patch.object(delivery.scout, "available_memory_mb", return_value=1024),
            patch.object(self.worker, "refill") as refill,
            patch.object(self.worker, "execute") as execute,
            patch.object(
                self.worker.halt, "wait", side_effect=lambda _: self.worker.halt.set()
            ),
        ):
            self.worker.run()
        refill.assert_not_called()
        execute.assert_not_called()
        with delivery.database(self.worker.root) as db:
            self.assertEqual(
                db.execute("SELECT state FROM delivery").fetchone()[0], "PENDING"
            )
        # Stop is terminal; the explicit pause status can also be observed while live.
        self.worker.publish("MEMORY_PAUSED")
        runtime = json.loads(
            (self.worker.root / "runtime.json").read_text(encoding="utf-8")
        )
        self.assertTrue(runtime["memory_paused"])
        self.assertEqual(runtime["min_free_memory_mb"], 2048)

    def test_queue_uses_wal_and_a_bounded_busy_timeout(self):
        with delivery.database(self.worker.root) as db:
            self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            self.assertEqual(
                db.execute("PRAGMA busy_timeout").fetchone()[0],
                delivery.DATABASE_BUSY_TIMEOUT_MS,
            )

    def test_refill_excludes_already_admitted_source_and_dedup_keys(self):
        delivery.stage(self.worker.root, [lead(1)])
        with patch.object(delivery, "select_leads", return_value=[lead(2)]) as select:
            self.assertEqual(self.worker.refill(active=0), 1)
        self.assertEqual(select.call_args.kwargs["exclude_source_ids"], {"1"})
        self.assertEqual(select.call_args.kwargs["exclude_keys"], {"hypothesis1"})

    def test_fast_terminal_batch_refills_before_poll_deadline(self):
        leads = [lead(i) for i in range(20)]
        with (
            patch.object(delivery, "select_leads", return_value=leads),
            patch.object(delivery.time, "time", return_value=100),
        ):
            self.assertEqual(self.worker.refill(active=0), 8)
            for _ in range(8):
                job = delivery.claim(self.worker.root)
                delivery.update(self.worker.root, job["id"], "ENVIRONMENT_BLOCKED")
            self.assertEqual(self.worker.refill(active=0), 8)
        with delivery.database(self.worker.root) as db:
            counts = dict(
                db.execute("SELECT state,count(*) FROM delivery GROUP BY state")
            )
        self.assertEqual(counts, {"ENVIRONMENT_BLOCKED": 8, "PENDING": 8})

    def test_exhausted_source_backs_off_and_never_retries_terminal_jobs(self):
        with (
            patch.object(delivery, "select_leads", return_value=[lead(1)]) as select,
            patch.object(delivery.time, "time", return_value=100),
        ):
            self.assertEqual(self.worker.refill(active=0), 1)
            job = delivery.claim(self.worker.root)
            delivery.update(self.worker.root, job["id"], "ENVIRONMENT_BLOCKED")
            self.assertEqual(self.worker.refill(active=0), 0)
            self.assertEqual(select.call_count, 1)
        with (
            patch.object(delivery, "select_leads", return_value=[lead(1), lead(2)]),
            patch.object(delivery.time, "time", return_value=110),
        ):
            self.assertEqual(self.worker.refill(active=0), 1)
        self.assertEqual(delivery.claim(self.worker.root)["source_job_id"], "2")
        self.assertIsNone(delivery.claim(self.worker.root))

    def test_refill_waits_while_pending_can_fill_free_slots(self):
        with (
            patch.object(
                delivery, "select_leads", return_value=[lead(i) for i in range(20)]
            ) as select,
            patch.object(delivery.time, "time", return_value=100),
        ):
            self.assertEqual(self.worker.refill(active=0), 8)
            for _ in range(6):
                delivery.claim(self.worker.root)
            self.assertEqual(self.worker.refill(active=2), 0)
            self.assertEqual(select.call_count, 1)
            delivery.claim(self.worker.root)
            self.assertEqual(self.worker.refill(active=2), 7)

    def test_cli_accepts_sixteen_slots_and_rejects_seventeen(self):
        (self.inbox / "scout.sqlite").touch()
        arguments = [
            "delivery",
            "--root",
            str(self.inbox),
            "--kimi-python",
            sys.executable,
            "--concurrency",
            "16",
        ]
        with (
            patch.object(sys, "argv", arguments),
            patch.object(delivery.Delivery, "run", autospec=True) as run,
        ):
            delivery.main()
        self.assertEqual(run.call_args.args[0].args.concurrency, 16)
        self.assertEqual(run.call_args.args[0].args.execution_concurrency, 4)
        with (
            patch.object(sys, "argv", arguments[:-1] + ["17"]),
            patch.object(sys, "stderr", io.StringIO()),
            self.assertRaises(SystemExit) as error,
        ):
            delivery.main()
        self.assertEqual(error.exception.code, 2)

    def test_replacement_is_bounded_and_unique(self):
        self.assertIn("return 2", delivery.proposal(proposal(), SOURCE))
        for source in ("no match", SOURCE + SOURCE):
            with self.assertRaises(ValueError):
                delivery.proposal(proposal(), source)
        value = proposal()
        value["edits"][0]["path"] = "/outside/private.py"
        with self.assertRaises(ValueError):
            delivery.proposal(value, SOURCE)

    def test_direct_from_subject_import_is_valid_but_relative_is_not(self):
        code = TEST.replace("import subject", "from subject import value").replace(
            "subject.value()", "value()"
        )
        self.assertIn(
            "return 2", delivery.proposal({**proposal(), "test_code": code}, SOURCE)
        )
        with self.assertRaises(ValueError):
            delivery.proposal(
                {
                    **proposal(),
                    "test_code": code.replace("from subject", "from .subject"),
                },
                SOURCE,
            )

    def test_gpu_proposal_is_explicit_opt_in_and_never_executes(self):
        self.args.gpu_proposals = True
        delivery.stage(self.worker.root, [lead()])
        job = delivery.claim(self.worker.root)
        source = {
            "source": SOURCE,
            "path": "gpu.py",
            "url": "https://public.invalid/data",
            "required_dependency_modules": ["torch", "triton"],
        }
        with (
            patch.object(delivery, "load_source", return_value=source),
            patch.object(self.worker, "model", return_value=proposal()) as model,
            patch.object(self.worker, "sandbox") as sandbox,
        ):
            self.assertEqual(self.worker.execute(job), "GPU_REVIEW_REQUIRED")
        sandbox.assert_not_called()
        self.assertEqual(model.call_count, 1)
        work = self.worker.root / "jobs" / job["id"]
        saved = json.loads((work / "gpu-proposal.json").read_text())
        self.assertFalse(saved["executed"])
        self.assertFalse(saved["qualified"])
        self.assertTrue((work / "gpu-test.py").is_file())
        self.assertFalse((work / "approval.json").exists())

    def test_explicit_gpu_route_preserves_cpu_terminal_and_is_once_only(self):
        delivery.stage(self.worker.root, [lead()])
        job = delivery.claim(self.worker.root)
        work = self.worker.root / "jobs" / job["id"]
        work.mkdir()
        delivery.update(
            self.worker.root,
            job["id"],
            "ENVIRONMENT_BLOCKED",
            "requires CUDA",
            {"executed": False},
        )
        self.assertEqual(delivery.route_blocked_gpu(self.worker.root), 1)
        saved = json.loads((work / "cpu-terminal-before-gpu.json").read_text())
        self.assertEqual(saved["state"], "ENVIRONMENT_BLOCKED")
        routed = delivery.claim(self.worker.root)
        self.assertTrue(json.loads(routed["payload"])["gpu_proposal_route"])
        delivery.update(
            self.worker.root, job["id"], "ENVIRONMENT_BLOCKED", "requires CUDA"
        )
        self.assertEqual(delivery.route_blocked_gpu(self.worker.root), 0)

    def test_gpu_invalid_proposal_gets_only_one_repair_without_outage_state(self):
        delivery.stage(self.worker.root, [lead()])
        job = delivery.claim(self.worker.root)
        work = self.worker.root / "jobs" / job["id"]
        work.mkdir()
        invalid = {**proposal(), "test_code": "import unittest"}
        with (
            patch.object(self.worker, "model", side_effect=[invalid, invalid]) as model,
            patch.object(self.worker, "sandbox") as sandbox,
        ):
            self.assertEqual(
                self.worker.prepare_gpu(job, work, {}, SOURCE), "INCONCLUSIVE"
            )
        self.assertEqual(model.call_count, 2)
        sandbox.assert_not_called()
        with delivery.database(self.worker.root) as db:
            row = db.execute("SELECT state,reason FROM delivery").fetchone()
        self.assertEqual(row["state"], "INCONCLUSIVE")
        self.assertIn("proposal validation", row["reason"])

    def test_saved_invalid_gpu_answer_is_not_regenerated_before_one_repair(self):
        delivery.stage(self.worker.root, [lead()])
        job = delivery.claim(self.worker.root)
        work = self.worker.root / "jobs" / job["id"]
        work.mkdir()
        delivery.scout.write_json(
            work / "gpu-proposal.answer.json",
            {"ok": True, "tool_calls_executed": 0, "text": "not json"},
        )
        with patch.object(self.worker, "model", return_value=proposal()) as model:
            self.assertEqual(
                self.worker.prepare_gpu(job, work, {}, SOURCE), "GPU_REVIEW_REQUIRED"
            )
        self.assertEqual(model.call_count, 1)
        self.assertEqual(model.call_args.args[1], "gpu-proposal-repair")

    def test_cpu_gpu_environment_response_routes_to_proposal_not_execution(self):
        self.args.gpu_proposals = True
        rejection = {
            "decision": "needs_environment",
            "reason": "requires CUDA device",
            "test_code": "",
            "edits": [],
        }
        state, row, model, sandbox = self.run_job([], [rejection, proposal()])
        self.assertEqual(state, "GPU_REVIEW_REQUIRED")
        self.assertEqual(model.call_count, 2)
        sandbox.assert_not_called()
        self.assertFalse(json.loads(row["result"])["executed"])

    def test_gpu_routing_does_not_bypass_malformed_cpu_proposal_repair(self):
        self.args.gpu_proposals = True
        invalid_values = (
            [],
            None,
            {**proposal(), "decision": "needs_environment", "reason": []},
        )
        for number, invalid in enumerate(invalid_values):
            with self.subTest(invalid=invalid):
                state, row, model, sandbox = self.run_job(
                    [], [invalid, invalid], number=number
                )
                self.assertEqual(state, "INCONCLUSIVE")
                self.assertEqual(model.call_count, 2)
                self.assertEqual(model.call_args.args[1], "repair")
                sandbox.assert_not_called()
                self.assertIn("proposal validation", row["reason"])

    def test_zero_skip_and_copied_only_tests_do_not_admit(self):
        for code in (
            "pass",
            TEST.replace("import subject", ""),
            TEST.replace(
                "def test_normal", "@unittest.skip('fake')\n    def test_normal"
            ),
        ):
            with self.subTest(code=code), self.assertRaises(ValueError):
                delivery.proposal({**proposal(), "test_code": code}, SOURCE)

    def test_profile_is_controller_chosen_from_required_dependencies(self):
        self.assertEqual(delivery.choose_profile({"dependency_modules": []}), "stdlib")
        self.assertEqual(
            delivery.choose_profile({"dependency_modules": ["torch", "numpy"]}),
            "torch-cpu",
        )
        self.assertEqual(
            delivery.choose_profile(
                {
                    "required_dependency_modules": [],
                    "dependency_modules": ["unavailable_lazy"],
                }
            ),
            "stdlib",
        )
        with self.assertRaises(delivery.UnsupportedEnvironment):
            delivery.choose_profile({"dependency_modules": ["custom_framework"]})

    def test_outcomes_do_not_promote_zero_tests_or_missing_imports(self):
        self.assertEqual(delivery.classify(result())[0], "REVIEWING")
        self.assertEqual(delivery.classify(result(0, 0))[0], "INCONCLUSIVE")
        self.assertEqual(delivery.classify(result(count=0))[0], "INCONCLUSIVE")
        self.assertEqual(
            delivery.classify(result(output="ModuleNotFoundError: no torch\n"))[0],
            "ENVIRONMENT_BLOCKED",
        )
        self.assertEqual(delivery.classify({"inconclusive": True})[0], "INCONCLUSIVE")

    def run_job(self, outputs, answers, *, number=1):
        delivery.stage(self.worker.root, [lead(number)])
        job = delivery.claim(self.worker.root)
        source = {
            "source": SOURCE,
            "path": "public.py",
            "url": "https://public.invalid/data",
            "sha256": "a" * 64,
            "dependency_modules": [],
        }
        with (
            patch.object(delivery, "load_source", return_value=source),
            patch.object(self.worker, "model", side_effect=answers) as model,
            patch.object(self.worker, "sandbox", side_effect=outputs) as sandbox,
        ):
            state = self.worker.execute(job)
        with delivery.database(self.worker.root) as db:
            row = dict(
                db.execute("SELECT * FROM delivery WHERE id=?", (job["id"],)).fetchone()
            )
        return state, row, model, sandbox

    def test_real_output_gets_one_repair_then_owner_handoff(self):
        state, row, model, sandbox = self.run_job(
            [result(1, 1), result()], [proposal(), proposal()]
        )
        self.assertEqual(state, delivery.OWNER_STATE)
        self.assertEqual(model.call_count, 2)
        self.assertEqual(sandbox.call_count, 2)
        self.assertIn("actual_result", model.call_args_list[1].args[2])
        self.assertFalse(json.loads(row["result"])["qualified"])
        handoff = json.loads(
            (self.worker.root / "jobs" / row["id"] / "owner-handoff.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(handoff["repair_used"])
        self.assertEqual(handoff["tests_run"], 2)
        self.assertFalse(handoff["claims"]["pr_ready"])

    def test_second_failure_is_terminal_without_third_execution(self):
        state, _, model, sandbox = self.run_job(
            [result(1, 1), result(1, 1)], [proposal(), proposal()]
        )
        self.assertEqual(state, "INCONCLUSIVE")
        self.assertEqual(model.call_count, 2)
        self.assertEqual(sandbox.call_count, 2)

    def test_model_rejection_has_no_container_and_is_labeled_advisory(self):
        rejection = {
            "decision": "reject",
            "reason": "caller excludes this input",
            "test_code": "",
            "edits": [],
        }
        state, row, _, sandbox = self.run_job([], [rejection])
        self.assertEqual(state, "NO_BUG")
        self.assertIn("Model advisory", row["reason"])
        sandbox.assert_not_called()

    def test_environment_failure_does_not_spend_repair_call(self):
        state, _, model, sandbox = self.run_job(
            [result(output="ImportError: package mismatch\n")], [proposal()]
        )
        self.assertEqual(state, "ENVIRONMENT_BLOCKED")
        self.assertEqual(model.call_count, 1)
        self.assertEqual(sandbox.call_count, 1)

    def test_direct_reproduction_stops_before_model_final_review(self):
        state, row, model, sandbox = self.run_job([result()], [proposal()])
        self.assertEqual(state, delivery.OWNER_STATE)
        self.assertEqual(model.call_count, 1)
        self.assertEqual(sandbox.call_count, 1)
        self.assertFalse(json.loads(row["result"])["qualified"])

    def test_publish_writes_a_bounded_owner_queue(self):
        state, row, _, _ = self.run_job([result()], [proposal()])
        self.assertEqual(state, delivery.OWNER_STATE)
        self.worker.publish("RUNNING")
        queue = json.loads(
            (self.worker.root / "owner-queue.json").read_text(encoding="utf-8")
        )
        self.assertEqual(queue["schema_version"], "kimi-owner-queue-v1")
        self.assertEqual(queue["total"], 1)
        self.assertEqual(queue["count"], 1)
        self.assertEqual(queue["items"][0]["id"], row["id"])
        self.assertFalse(queue["items"][0]["legacy"])
        self.assertIn("owner review", queue["claim_boundary"])

    def test_owner_queue_groups_exact_patches_without_dropping_jobs(self):
        self.args.owner_queue_limit = 2
        _, first, _, _ = self.run_job([result()], [proposal()], number=1)
        _, duplicate, _, _ = self.run_job([result()], [proposal()], number=2)
        distinct = proposal()
        distinct["edits"] = [{"old": "return 1", "new": "return 3"}]
        _, third, _, _ = self.run_job([result()], [distinct], number=3)

        self.worker.publish("RUNNING")
        queue = json.loads(
            (self.worker.root / "owner-queue.json").read_text(encoding="utf-8")
        )
        self.assertEqual(queue["total"], 3)
        self.assertEqual(queue["count"], 2)
        runtime = json.loads(
            (self.worker.root / "runtime.json").read_text(encoding="utf-8")
        )
        self.assertEqual(runtime["owner_distinct_displayed"], 2)
        self.assertEqual(runtime["owner_exact_duplicates_seen"], 1)
        self.assertIn(third["id"], {item["id"] for item in queue["items"]})
        groups = [item for item in queue["items"] if item["exact_patch_duplicates"]]
        self.assertEqual(len(groups), 1)
        self.assertEqual(
            {groups[0]["id"], *groups[0]["exact_patch_duplicates"]},
            {first["id"], duplicate["id"]},
        )
        with delivery.database(self.worker.root) as db:
            self.assertEqual(
                db.execute(
                    "SELECT count(*) FROM delivery WHERE state=?",
                    (delivery.OWNER_STATE,),
                ).fetchone()[0],
                3,
            )

    def test_reviewed_merged_audit_removes_only_matching_owner_display(self):
        self.args.owner_queue_limit = 1
        _, merged, _, _ = self.run_job([result()], [proposal()], number=1)
        _, pending, _, _ = self.run_job([result()], [proposal()], number=2)
        patch = self.worker.root / "jobs" / merged["id"] / "change-1.patch"
        audit_dir = self.worker.root / "owner-audits"
        audit_dir.mkdir()
        audit = {
            "schema_version": "scout-owner-public-pr-reconciliation-v1",
            "candidate_id": merged["id"],
            "repo": merged["repo"],
            "candidate_patch": {
                "path": f"jobs/{merged['id']}/change-1.patch",
                "sha256": hashlib.sha256(patch.read_bytes()).hexdigest(),
            },
            "public_pr": {
                "url": "https://github.com/public/project/pull/5000",
                "state": "MERGED",
                "upstream_merge_commit": "a" * 40,
            },
            "decision": "ALREADY_MERGED_NOT_A_NEW_PR_CANDIDATE",
        }
        audit_path = audit_dir / "merged.json"
        audit_path.write_text(json.dumps(audit), encoding="utf-8")
        self.worker.publish("STOPPED")
        queue = json.loads((self.worker.root / "owner-queue.json").read_text())
        runtime = json.loads((self.worker.root / "runtime.json").read_text())
        self.assertEqual((queue["total"], queue["actionable_total"]), (2, 1))
        self.assertEqual(queue["reviewed_merged_total"], 1)
        self.assertEqual([item["id"] for item in queue["items"]], [pending["id"]])
        self.assertEqual(runtime["owner_actionable"], 1)
        with delivery.database(self.worker.root) as db:
            self.assertEqual(
                db.execute(
                    "SELECT state FROM delivery WHERE id=?", (merged["id"],)
                ).fetchone()[0],
                delivery.OWNER_STATE,
            )

        audit["candidate_patch"]["sha256"] = "0" * 64
        audit_path.write_text(json.dumps(audit), encoding="utf-8")
        self.worker.publish("STOPPED")
        queue = json.loads((self.worker.root / "owner-queue.json").read_text())
        self.assertEqual(queue["actionable_total"], 2)

        audit["candidate_patch"]["sha256"] = hashlib.sha256(
            patch.read_bytes()
        ).hexdigest()
        audit["repo"] = "public/other"
        audit_path.write_text(json.dumps(audit), encoding="utf-8")
        self.worker.publish("STOPPED")
        queue = json.loads((self.worker.root / "owner-queue.json").read_text())
        self.assertEqual(queue["actionable_total"], 2)

    def test_explicit_source_fetch_retry_is_one_time_and_pre_model_only(self):
        delivery.stage(self.worker.root, [lead(1)])
        job = delivery.claim(self.worker.root)
        work = self.worker.root / "jobs" / job["id"]
        work.mkdir()
        delivery.update(self.worker.root, job["id"], "FAILED", "HTTPError")

        receipt = delivery.retry_preflight_transport(self.worker.root, job["id"])
        self.assertEqual(receipt["prior_reason"], "HTTPError")
        self.assertFalse(work.exists())
        self.assertEqual(delivery.claim(self.worker.root)["id"], job["id"])
        self.assertTrue(
            (self.worker.root / "preflight-retries" / (job["id"] + ".json")).is_file()
        )
        delivery.update(self.worker.root, job["id"], "FAILED", "HTTPError")
        with self.assertRaisesRegex(ValueError, "once-retryable"):
            delivery.retry_preflight_transport(self.worker.root, job["id"])

    def test_preflight_retry_rejects_any_model_or_test_artifact(self):
        for number, reason, tokens, artifact in (
            (1, "HTTPError", 1, False),
            (2, "HTTPError", 0, True),
            (3, "TimeoutError", 0, False),
        ):
            with self.subTest(number=number):
                delivery.stage(self.worker.root, [lead(number)])
                job = delivery.claim(self.worker.root)
                work = self.worker.root / "jobs" / job["id"]
                work.mkdir()
                if artifact:
                    (work / "generate.request.json").write_text("{}", encoding="utf-8")
                delivery.update(self.worker.root, job["id"], "FAILED", reason)
                with delivery.database(self.worker.root) as db:
                    db.execute(
                        "UPDATE delivery SET reported_tokens=? WHERE id=?",
                        (tokens, job["id"]),
                    )
                with self.assertRaisesRegex(ValueError, "once-retryable"):
                    delivery.retry_preflight_transport(self.worker.root, job["id"])
                with delivery.database(self.worker.root) as db:
                    state = db.execute(
                        "SELECT state FROM delivery WHERE id=?", (job["id"],)
                    ).fetchone()[0]
                self.assertEqual(state, "FAILED")

    def test_sandbox_transport_or_cleanup_uncertainty_stops_new_work(self):
        work = self.worker.root / "jobs" / "a"
        work.mkdir()
        for response in (
            subprocess.TimeoutExpired("fixed verifier", 150),
            SimpleNamespace(stdout=b"not JSON", returncode=1),
            SimpleNamespace(stdout=b'{"inconclusive":true}', returncode=1),
        ):
            self.worker.halt.clear()
            options = (
                {"side_effect": response}
                if isinstance(response, Exception)
                else {"return_value": response}
            )
            with patch.object(delivery.subprocess, "run", **options):
                try:
                    self.worker.sandbox(work, 1, "stdlib")
                except RuntimeError:
                    pass
            self.assertTrue(self.worker.halt.is_set())

    def test_stop_blocks_new_model_and_container_stages(self):
        (self.worker.root / "STOP").write_text("owner stop", encoding="utf-8")
        with patch.object(delivery.subprocess, "run") as execute:
            with self.assertRaises(RuntimeError):
                self.worker.model({"id": "unused"}, "repair", "no new paid call")
            result = self.worker.sandbox(self.worker.root, 1, "stdlib")
            self.assertTrue(result["inconclusive"])
            execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
