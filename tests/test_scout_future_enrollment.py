"""Fresh admission order, not later success or convenient reproducibility."""
import hashlib
import json
from pathlib import Path
import sys
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout as scout
import kimi_scout_shadow as shadow
from tests.test_kimi_scout_shadow import packet


class FutureEnrollmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        scout.initialize(self.root)
        self.serial = 0
        with scout.connect(self.root) as db:
            shadow.initialize(db)

    def admit(self, created, *, stage="source_audit", repo="owner/repo", bound=True):
        item = packet()
        self.serial += 1
        item["name"] = "case-" + str(created) + "-" + str(self.serial)
        item["repo"] = repo
        item["research"]["stage"] = stage
        with scout.connect(self.root) as db:
            ident = scout.enqueue(self.root, item, db=db)
            db.execute("UPDATE jobs SET created=? WHERE id=?", (created, ident))
            if bound:
                with patch.object(shadow.time, "time", return_value=created + 1):
                    shadow.record(db, ident, item, scout.dumps(item))
        return ident

    def read(self, **kwargs):
        return shadow.enroll_future_source_audits(self.root, created_after=100,
            repositories=["owner/repo"], **kwargs)

    def test_prefix_is_stable_when_later_jobs_finish_or_fail(self):
        self.admit(99)
        self.admit(100)
        first = self.admit(101)
        self.admit(102, stage="source_followup")
        second = self.admit(103)
        third = self.admit(104)
        original = self.read(count=2)
        self.assertEqual([c["job_id"] for c in original["cases"]], [first, second])
        with scout.connect(self.root) as db:
            db.execute("UPDATE jobs SET state='FAILED',result='untrusted later answer' WHERE id=?", (first,))
            db.execute("UPDATE jobs SET state='REVIEW',result='successful later answer' WHERE id=?", (third,))
        self.assertEqual(self.read(count=2), original)
        self.assertNotIn("later answer", json.dumps(original))

    def test_incomplete_frame_keeps_prefix_and_missing_binding_keeps_slot(self):
        first = self.admit(101, bound=False)
        initial = self.read(count=2)
        self.assertEqual(initial["status"], "FRAME_INCOMPLETE")
        self.admit(102)
        complete = self.read(count=2)
        self.assertEqual(complete["status"], "FRAME_COMPLETE")
        self.assertEqual(complete["cases"][0], initial["cases"][0])
        self.assertEqual(complete["cases"][0]["job_id"], first)
        self.assertEqual(complete["cases"][0]["predecision_status"], "MISSING_PREDECISION_RECORD")

    def test_tampering_and_bad_time_are_disclosed_not_replaced(self):
        first, second = self.admit(101), self.admit(102)
        with scout.connect(self.root) as db:
            db.execute("UPDATE research_action_shadow SET packet_sha256=? WHERE job_id=?", ("0" * 64, first))
            db.execute("UPDATE research_action_shadow SET recorded_at=0 WHERE job_id=?", (second,))
        self.assertEqual([c["predecision_status"] for c in self.read(count=2)["cases"]],
            ["PREDECISION_PACKET_BINDING_MISMATCH", "INVALID_PREDECISION_TIME"])

    def test_repo_frame_and_exact_body_binding(self):
        self.admit(101, repo="other/repo")
        ident = self.admit(102)
        value = self.read(count=1)
        case = value["cases"][0]
        self.assertEqual(case["job_id"], ident)
        self.assertEqual(case["predecision_status"], "BOUND_PREDECISION_PACKET")
        self.assertEqual(hashlib.sha256(case["packet_body"].encode()).hexdigest(), case["packet_sha256"])

    def test_tied_creation_times_are_ordered_by_id(self):
        ids = [self.admit(101), self.admit(101)]
        self.assertEqual([c["job_id"] for c in self.read(count=2)["cases"]], sorted(ids))

    def test_reader_does_not_access_answers_or_mutate_queue(self):
        self.admit(101)
        connect = sqlite3.connect
        forbidden = {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE}
        def guarded(*args, **kwargs):
            self.assertIn("mode=ro", args[0])
            db = connect(*args, **kwargs)
            def authorize(action, table, column, *_):
                if action in forbidden or (action == sqlite3.SQLITE_READ and table == "jobs"
                        and column in {"state", "result", "error", "charge", "finished"}):
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            db.set_authorizer(authorize)
            return db
        with patch.object(shadow.sqlite3, "connect", side_effect=guarded):
            self.assertEqual(self.read(count=1)["status"], "FRAME_COMPLETE")

    def test_invalid_frames_do_not_open_database(self):
        for cutoff in (True, -1, float("inf"), "100"):
            with self.subTest(cutoff=cutoff), self.assertRaises(ValueError):
                shadow.enroll_future_source_audits(self.root, created_after=cutoff, repositories=["owner/repo"])
        for repos in ([], "owner/repo", [None], ["../repo"], ["owner/.."], ["owner/repo"] * 65):
            with self.subTest(repos=repos), self.assertRaises(ValueError):
                shadow.enroll_future_source_audits(self.root, created_after=100, repositories=repos)
        for count in (True, 0, 21):
            with self.subTest(count=count), self.assertRaises(ValueError):
                self.read(count=count)


if __name__ == "__main__":
    unittest.main()
