"""Owner deferral keeps evidence, cost and worker liveness separate."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout_delivery as delivery


class OwnerParkingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.inbox = Path(self.temp.name)
        self.root = self.inbox / "delivery"
        self.root.mkdir()
        delivery.initialize(self.root)
        self.job = "a" * 24
        self.evidence = (
            "https://github.com/public/project/blob/" + "b" * 40 + "/module.py#L4"
        )
        self.result = {
            "before": {"exit_code": 1},
            "fixed": {"exit_code": 0},
            "qualified": False,
            "owner_score": 4,
        }
        with delivery.database(self.root) as db:
            db.execute(
                "INSERT INTO delivery(id,source_job_id,dedup_key,repo,title,state,updated_at,"
                "payload,reason,reported_tokens,result) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    self.job,
                    "source",
                    "dedup",
                    "public/project",
                    "fixture",
                    delivery.OWNER_STATE,
                    123,
                    "{}",
                    "direct reproduction",
                    1234,
                    json.dumps(self.result),
                ),
            )

    def park(self, **changes):
        options = dict(
            job_id=self.job,
            reason="consumer not demonstrated",
            evidence_url=self.evidence,
            reopen_when="a real consumer reproduces the defect",
        )
        options.update(changes)
        return delivery.park_owner_candidate(self.root, **options)

    def row(self):
        with delivery.database(self.root) as db:
            return dict(
                db.execute("SELECT * FROM delivery WHERE id=?", (self.job,)).fetchone()
            )

    def test_deferral_preserves_evidence_tokens_and_idempotent_original_decision(self):
        first = self.park()
        row = self.row()
        self.assertEqual(row["state"], "OWNER_PARKED")
        self.assertEqual(row["reported_tokens"], 1234)
        stored = json.loads(row["result"])
        self.assertEqual(stored.pop("owner_disposition"), first)
        self.assertEqual(stored, self.result)
        self.assertEqual(first["prior_state"], delivery.OWNER_STATE)
        self.assertEqual(first["prior_reason"], "direct reproduction")
        self.assertEqual(self.park(), first)
        self.assertEqual(self.row(), row)
        with self.assertRaisesRegex(ValueError, "different decision"):
            self.park(reason="different explanation")
        self.assertEqual(self.row(), row)

    def test_immutable_deletion_commit_can_support_deferral(self):
        evidence = "https://github.com/public/project/commit/" + "b" * 40
        decision = self.park(evidence_url=evidence)
        self.assertEqual(decision["evidence_url"], evidence)
        self.assertEqual(self.row()["state"], "OWNER_PARKED")
        self.assertEqual(
            json.loads(self.row()["result"])["before"], self.result["before"]
        )

    def test_same_document_line_correction_preserves_decision_and_old_link(self):
        first = self.park()
        before = self.row()
        evidence = self.evidence.replace("#L4", "#L6-L8")
        corrected = self.park(evidence_url=evidence)
        self.assertEqual(corrected["evidence_url"], evidence)
        self.assertEqual(
            corrected["evidence_url_history"][0]["evidence_url"], self.evidence
        )
        for key in (
            "reason",
            "reopen_when",
            "prior_state",
            "prior_reason",
            "recorded_at",
            "claim_boundary",
        ):
            self.assertEqual(corrected[key], first[key])
        after = self.row()
        for key in ("state", "reason", "reported_tokens", "payload", "source_job_id"):
            self.assertEqual(after[key], before[key])
        result = json.loads(after["result"])
        result.pop("owner_disposition")
        self.assertEqual(result, self.result)
        self.assertEqual(self.park(evidence_url=evidence), corrected)
        self.assertEqual(self.row(), after)

    def test_locator_correction_cannot_change_document_revision_or_decision(self):
        self.park()
        for change in (
            {"evidence_url": self.evidence.replace("module.py", "other.py")},
            {"evidence_url": self.evidence.replace("b" * 40, "c" * 40)},
            {
                "evidence_url": self.evidence.replace("#L4", "#L6"),
                "reason": "different",
            },
            {
                "evidence_url": self.evidence.replace("#L4", "#L6"),
                "reopen_when": "different",
            },
        ):
            before = self.row()
            with self.assertRaisesRegex(ValueError, "different decision"):
                self.park(**change)
            self.assertEqual(self.row(), before)

    def test_locator_correction_history_is_bounded_and_validated(self):
        for history in ("malformed", [{}] * 16):
            self.park()
            result = json.loads(self.row()["result"])
            result["owner_disposition"]["evidence_url_history"] = history
            with delivery.database(self.root) as db:
                db.execute(
                    "UPDATE delivery SET result=? WHERE id=?",
                    (json.dumps(result), self.job),
                )
            before = self.row()
            with self.assertRaisesRegex(ValueError, "locator history"):
                self.park(evidence_url=self.evidence.replace("#L4", "#L6"))
            self.assertEqual(self.row(), before)

    def test_commit_evidence_must_be_pinned_unadorned_and_same_repository(self):
        prefix = "https://github.com/public/project/commit/"
        for evidence in (
            prefix + "main",
            prefix + "b" * 39,
            prefix + "b" * 40 + "?diff=split",
            prefix + "b" * 40 + "#diff",
            prefix.replace("public/project", "other/project") + "b" * 40,
        ):
            with self.subTest(evidence=evidence):
                before = self.row()
                with self.assertRaises(ValueError):
                    self.park(evidence_url=evidence)
                self.assertEqual(self.row(), before)

    def test_legacy_and_gpu_proposals_can_be_deferred_without_fake_execution(self):
        for state in ("REPRODUCED", "GPU_REVIEW_REQUIRED"):
            with self.subTest(state=state):
                delivery.update(self.root, self.job, state, "prior", self.result)
                self.assertEqual(self.park()["prior_state"], state)
                self.assertEqual(
                    json.loads(self.row()["result"])["fixed"], self.result["fixed"]
                )

    def test_owner_can_defer_environment_blocked_lead_without_claiming_execution(self):
        blocked = {"attempt": {"state": "NOT_RUN", "error": "missing package"}}
        delivery.update(self.root, self.job, "ENVIRONMENT_BLOCKED", "prior", blocked)
        before = self.row()
        decision = self.park(reason="existing author owns the documented fix")
        after = self.row()
        self.assertEqual(decision["prior_state"], "ENVIRONMENT_BLOCKED")
        self.assertEqual(decision["prior_reason"], "prior")
        self.assertEqual(after["reported_tokens"], before["reported_tokens"])
        self.assertEqual(after["payload"], before["payload"])
        stored = json.loads(after["result"])
        stored.pop("owner_disposition")
        self.assertEqual(stored, blocked)
        self.assertNotIn("fixed", stored)
        self.assertEqual(list((self.root / "jobs").iterdir()), [])

    def test_active_published_negative_and_failed_states_are_not_silently_changed(
        self,
    ):
        for state in ("PENDING", "TESTING", "PR_OPEN", "NO_BUG", "FAILED"):
            with self.subTest(state=state):
                delivery.update(self.root, self.job, state, "prior", self.result)
                before = self.row()
                with self.assertRaisesRegex(ValueError, "owner-review"):
                    self.park()
                self.assertEqual(self.row(), before)

    def test_evidence_and_reopening_condition_must_be_explicit(self):
        for change in (
            {"job_id": "../escape"},
            {"job_id": "c" * 24},
            {"reason": " "},
            {"reason": "x" * 1001},
            {"reopen_when": ""},
            {"evidence_url": self.evidence.replace("public/project", "other/project")},
            {"evidence_url": self.evidence.replace("b" * 40, "main")},
            {"evidence_url": None},
        ):
            with self.subTest(change=change):
                before = self.row()
                with self.assertRaises(ValueError):
                    self.park(**change)
                self.assertEqual(self.row(), before)

    def test_offline_refresh_updates_queue_but_preserves_stopped_worker_identity(self):
        previous = {
            "state": "STOPPED",
            "pid": 999,
            "heartbeat_at": 100,
            "concurrency": 16,
            "execution_concurrency": 1,
        }
        (self.root / "runtime.json").write_text(json.dumps(previous))
        self.park()
        args = SimpleNamespace(
            root=self.inbox,
            concurrency=4,
            execution_concurrency=2,
            owner_queue_limit=64,
        )
        delivery.Delivery(args).publish(None, refresh_only=True)
        runtime = json.loads((self.root / "runtime.json").read_text())
        for key, value in previous.items():
            self.assertEqual(runtime[key], value)
        self.assertEqual(runtime["owner_ready"], 0)
        self.assertEqual(runtime["counts"], {"OWNER_PARKED": 1})
        self.assertEqual(runtime["reported_tokens"], 1234)
        self.assertEqual(runtime["publications"]["distinct_prs"], 0)
        self.assertEqual(
            json.loads((self.root / "owner-queue.json").read_text())["items"], []
        )

    def test_refresh_without_worker_history_does_not_fabricate_a_process(self):
        args = SimpleNamespace(
            root=self.inbox,
            concurrency=4,
            execution_concurrency=2,
            owner_queue_limit=64,
        )
        delivery.Delivery(args).publish(None, refresh_only=True)
        runtime = json.loads((self.root / "runtime.json").read_text())
        self.assertEqual(runtime["state"], "UNKNOWN")
        self.assertIsNone(runtime["pid"])
        self.assertIsNone(runtime["heartbeat_at"])

    def test_cli_requires_complete_separate_operation_and_does_not_start_models(self):
        command = [
            sys.executable,
            "-B",
            str(Path(delivery.__file__)),
            "--root",
            str(self.inbox),
            "--park-owner-job",
            self.job,
            "--park-reason",
            "consumer not demonstrated",
            "--park-evidence-url",
            self.evidence,
            "--reopen-when",
            "a real consumer reproduces the defect",
        ]
        for extra in (
            ["--stop"],
            ["--retry-preflight-job", self.job],
            ["--max-jobs", "1"],
        ):
            result = subprocess.run(command + extra, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(self.row()["state"], delivery.OWNER_STATE)
        incomplete = subprocess.run(command[:-2], capture_output=True, text=True)
        self.assertEqual(incomplete.returncode, 2)
        accepted = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertEqual(
            json.loads(accepted.stdout)["prior_state"], delivery.OWNER_STATE
        )
        self.assertFalse((self.root / "STOP").exists())
        self.assertEqual(list((self.root / "jobs").iterdir()), [])

    def test_cli_parks_terminal_candidate_without_overwriting_live_worker_snapshot(
        self,
    ):
        command = [
            sys.executable,
            "-B",
            str(Path(delivery.__file__)),
            "--root",
            str(self.inbox),
            "--park-owner-job",
            self.job,
            "--park-reason",
            "consumer not demonstrated",
            "--park-evidence-url",
            self.evidence,
            "--reopen-when",
            "a real consumer reproduces the defect",
        ]
        snapshot = b'{"state":"RUNNING","pid":123,"heartbeat_at":456}'
        (self.root / "runtime.json").write_bytes(snapshot)
        (self.root / "owner-queue.json").write_bytes(b'{"items":[]}')
        with delivery.scout.single_runner(self.root):
            accepted = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            self.assertEqual(self.row()["state"], "OWNER_PARKED")
            self.assertEqual((self.root / "runtime.json").read_bytes(), snapshot)
            self.assertEqual(
                (self.root / "owner-queue.json").read_bytes(), b'{"items":[]}'
            )
            repeated = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            self.assertEqual(json.loads(accepted.stdout), json.loads(repeated.stdout))
        self.assertEqual(self.row()["reported_tokens"], 1234)
        self.assertFalse((self.root / "STOP").exists())


if __name__ == "__main__":
    unittest.main()
