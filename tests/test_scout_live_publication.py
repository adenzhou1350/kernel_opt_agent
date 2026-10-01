"""Owner publication must not require stopping a running delivery worker."""

import errno
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout_delivery as delivery


class LivePublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.inbox = Path(self.temp.name)
        self.root = self.inbox / "delivery"
        self.root.mkdir()
        delivery.initialize(self.root)
        self.job = "a" * 24
        self.url = "https://github.com/public/project/pull/1"
        self.evidence = {
            "before": {"exit_code": 1},
            "fixed": {"exit_code": 0},
            "qualified": False,
        }
        with delivery.database(self.root) as db:
            db.execute(
                "INSERT INTO delivery(id,source_job_id,dedup_key,repo,title,state,updated_at,payload,reason,"
                "reported_tokens,result) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    self.job,
                    "source",
                    "key",
                    "public/project",
                    "fixture",
                    "ENVIRONMENT_BLOCKED",
                    123,
                    "{}",
                    "missing package",
                    321,
                    json.dumps(self.evidence),
                ),
            )

    def row(self):
        with delivery.database(self.root) as db:
            return dict(
                db.execute("SELECT * FROM delivery WHERE id=?", (self.job,)).fetchone()
            )

    def cli(self, *extra):
        return subprocess.run(
            [
                sys.executable,
                "-B",
                str(Path(delivery.__file__)),
                "--root",
                str(self.inbox),
                "--mark-pr-job",
                self.job,
                "--pr-url",
                self.url,
                *extra,
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )

    def test_live_worker_keeps_its_snapshots_and_owner_can_link_idempotently(self):
        runtime = b'{"state":"RUNNING","pid":123,"heartbeat_at":456}'
        queue = b'{"items":[]}'
        (self.root / "runtime.json").write_bytes(runtime)
        (self.root / "owner-queue.json").write_bytes(queue)
        with delivery.scout.single_runner(self.root):
            first = self.cli("--owner-reproduced-after-block")
            self.assertEqual(first.returncode, 0, first.stderr)
            repeated = self.cli("--owner-reproduced-after-block")
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            self.assertEqual(json.loads(first.stdout), json.loads(repeated.stdout))
            self.assertEqual((self.root / "runtime.json").read_bytes(), runtime)
            self.assertEqual((self.root / "owner-queue.json").read_bytes(), queue)
        row = self.row()
        self.assertEqual(row["state"], "PR_OPEN")
        self.assertEqual(row["reported_tokens"], 321)
        result = json.loads(row["result"])
        self.assertEqual(result.pop("pr")["prior_state"], "ENVIRONMENT_BLOCKED")
        self.assertEqual(result, self.evidence)
        self.assertFalse((self.root / "STOP").exists())
        self.assertEqual(list((self.root / "jobs").iterdir()), [])

    def test_idle_refresh_preserves_worker_history_and_counts_publication(self):
        history = {"state": "STOPPED", "pid": 123, "heartbeat_at": 456}
        (self.root / "runtime.json").write_text(json.dumps(history))
        result = self.cli("--owner-reproduced-after-block")
        self.assertEqual(result.returncode, 0, result.stderr)
        runtime = json.loads((self.root / "runtime.json").read_text())
        self.assertEqual({k: runtime[k] for k in history}, history)
        self.assertEqual(runtime["counts"], {"PR_OPEN": 1})
        self.assertEqual(runtime["publications"]["distinct_prs"], 1)

    def test_publication_cannot_promote_active_states_or_override_repository_or_pr(
        self,
    ):
        with delivery.database(self.root) as db:
            db.execute("UPDATE delivery SET state='TESTING'")
        before = self.row()
        with delivery.scout.single_runner(self.root):
            result = self.cli("--owner-reproduced-after-block")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.row(), before)
        with self.assertRaisesRegex(ValueError, "repository"):
            delivery.mark_pr(
                self.root, self.job, "https://github.com/other/project/pull/1"
            )
        with delivery.database(self.root) as db:
            db.execute("UPDATE delivery SET state='ENVIRONMENT_BLOCKED'")
        delivery.mark_pr(
            self.root, self.job, self.url, owner_reproduced_after_block=True
        )
        with self.assertRaisesRegex(ValueError, "another PR"):
            delivery.mark_pr(self.root, self.job, self.url[:-1] + "2")

    def test_publication_flags_require_separate_explicit_operation(self):
        for flags in [
            (),
            ("--owner-reproduced-after-block", "--stop"),
            ("--owner-reproduced-after-block", "--max-jobs", "1"),
            ("--owner-reproduced-after-block", "--retry-preflight-job", self.job),
            ("--owner-reproduced-after-block", "--owner-verified-legacy"),
        ]:
            with self.subTest(flags=flags):
                self.assertNotEqual(self.cli(*flags).returncode, 0)
                self.assertEqual(self.row()["state"], "ENVIRONMENT_BLOCKED")
                self.assertFalse((self.root / "STOP").exists())

    def test_legacy_publication_keeps_its_separate_claim_boundary(self):
        with delivery.database(self.root) as db:
            db.execute("UPDATE delivery SET state='REPRODUCED'")
        result = self.cli("--owner-verified-legacy")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "no handoff or new tests inferred",
            json.loads(result.stdout)["claim_boundary"],
        )

    def test_normal_publication_requires_matching_owner_handoff(self):
        with delivery.database(self.root) as db:
            db.execute("UPDATE delivery SET state=?", (delivery.OWNER_STATE,))
        before = self.row()
        self.assertNotEqual(self.cli().returncode, 0)
        self.assertEqual(self.row(), before)
        handoff = self.root / "jobs" / self.job / "owner-handoff.json"
        handoff.parent.mkdir()
        handoff.write_text(json.dumps({"candidate_id": "b" * 24}))
        self.assertNotEqual(self.cli().returncode, 0)
        self.assertEqual(self.row(), before)
        handoff.write_text(json.dumps({"candidate_id": self.job}))
        with delivery.scout.single_runner(self.root):
            result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.row()["state"], "PR_OPEN")
        self.assertEqual(self.row()["reported_tokens"], 321)

    def test_noncanonical_links_and_missing_candidates_do_not_change_queue(self):
        before = self.row()
        for url in (
            "http://github.com/public/project/pull/1",
            self.url + "?view=1",
            self.url + "/files",
            self.url[:-1] + "0",
        ):
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, "canonical"):
                delivery.mark_pr(
                    self.root, self.job, url, owner_reproduced_after_block=True
                )
        with self.assertRaisesRegex(ValueError, "candidate not found"):
            delivery.mark_pr(
                self.root, "b" * 24, self.url, owner_reproduced_after_block=True
            )
        self.assertEqual(self.row(), before)

    def test_snapshot_refresh_does_not_suppress_unexpected_io_failures(self):
        args = SimpleNamespace(root=self.inbox)
        with patch.object(
            delivery.scout,
            "single_runner",
            side_effect=OSError(errno.EIO, "I/O failure"),
        ):
            with self.assertRaises(OSError):
                delivery.refresh_owner_snapshots_if_idle(args, self.root)


if __name__ == "__main__":
    unittest.main()
