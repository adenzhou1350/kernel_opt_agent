import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from scripts.scout_pending_cohort import enroll


class PendingCohortTests(unittest.TestCase):
    def test_only_unfinished_input_is_exported_and_database_is_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "scout.sqlite"
            db = sqlite3.connect(path)
            db.executescript("""
                CREATE TABLE jobs (id TEXT,packet TEXT,created REAL,finished REAL,state TEXT,result TEXT);
                CREATE TABLE research_action_shadow (job_id TEXT,policy_version TEXT,
                    packet_sha256 TEXT,recorded_at REAL,suggested_action TEXT,reason TEXT);
            """)
            for index, state in enumerate(("PENDING", "RUNNING", "REVIEW", "NO_LEAD")):
                packet = {
                    "repo": "owner/repo",
                    "research": {
                        "stage": "source_followup",
                        "parent_job_id": "parent",
                        "root_job_id": "root",
                    },
                    "untrusted_prior_analysis": "Available before this decision",
                    "sources": [
                        {
                            "url": f"https://raw.githubusercontent.com/owner/repo/{'a' * 40}/{index}.py"
                        }
                    ],
                }
                raw = json.dumps(packet)
                db.execute(
                    "INSERT INTO jobs VALUES (?,?,?,?,?,?)",
                    (
                        str(index),
                        raw,
                        20,
                        None if index < 2 else 30,
                        state,
                        "FORBIDDEN_ANSWER",
                    ),
                )
                db.execute(
                    "INSERT INTO research_action_shadow VALUES (?,?,?,?,?,?)",
                    (
                        str(index),
                        "frozen-policy",
                        hashlib.sha256(raw.encode()).hexdigest(),
                        21,
                        "RULE_NOT_A_LABEL",
                        "PRIORITIZATION_ONLY",
                    ),
                )
            db.commit()
            db.close()
            before = path.read_bytes()
            inputs, metadata = enroll(path, created_after=10, limit=2, per_repo_cap=2)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(len(inputs), 2)
            shown = json.dumps(inputs)
            for forbidden in (
                "FORBIDDEN_ANSWER",
                "RULE_NOT_A_LABEL",
                "parent_job_id",
                "root_job_id",
            ):
                self.assertNotIn(forbidden, shown)
            self.assertIn("Available before this decision", shown)
            self.assertEqual(metadata["enrolled"], 2)
            self.assertEqual(metadata["enrollment"], "unfinished")
            all_inputs, admission = enroll(
                path, created_after=10, limit=4, per_repo_cap=4,
                enrollment="admission_recorded",
            )
            self.assertEqual(len(all_inputs), 4)
            self.assertEqual(admission["scanned_rows"], 4)
            self.assertIsNone(admission["scanned_unfinished_rows"])
            self.assertEqual(path.read_bytes(), before)
            self.assertNotIn("FORBIDDEN_ANSWER", json.dumps(all_inputs))
            self.assertNotIn("RULE_NOT_A_LABEL", json.dumps(all_inputs))
            real_connect = sqlite3.connect

            def deny_later_outcomes(*args, **kwargs):
                connection = real_connect(*args, **kwargs)
                connection.set_authorizer(
                    lambda operation, table, column, *unused:
                    sqlite3.SQLITE_DENY
                    if operation == sqlite3.SQLITE_READ and table == "jobs"
                    and column in {"result", "charge", "state", "finished"}
                    else sqlite3.SQLITE_OK
                )
                return connection

            with patch("scripts.scout_pending_cohort.sqlite3.connect",
                       side_effect=deny_later_outcomes):
                guarded, _ = enroll(
                    path, created_after=10, limit=4, per_repo_cap=4,
                    enrollment="admission_recorded",
                )
            self.assertEqual(guarded, all_inputs)
            db = sqlite3.connect(path)
            db.execute("UPDATE jobs SET state='FAILED',finished=40,result='DIFFERENT_OUTCOME'")
            db.commit()
            db.close()
            terminal_bytes = path.read_bytes()
            terminal_inputs, _ = enroll(
                path, created_after=10, limit=4, per_repo_cap=4,
                enrollment="admission_recorded",
            )
            self.assertEqual(terminal_inputs, all_inputs)
            self.assertEqual(path.read_bytes(), terminal_bytes)
            # Restore the fixture's two unfinished rows for existing checks.
            db = sqlite3.connect(path)
            db.execute("UPDATE jobs SET state='PENDING',finished=NULL WHERE id IN ('0','1')")
            db.commit()
            db.close()
            self.assertEqual(
                len(enroll(path, created_after=22, limit=2, per_repo_cap=2)[0]), 0
            )
            self.assertEqual(
                len(enroll(path, created_after=10, limit=2, per_repo_cap=1)[0]), 1
            )
            db = sqlite3.connect(path)
            original = db.execute("SELECT packet FROM jobs WHERE id='1'").fetchone()[0]
            db.execute(
                "UPDATE research_action_shadow SET packet_sha256='bad' WHERE job_id='1'"
            )
            db.commit()
            self.assertEqual(
                len(enroll(path, created_after=10, limit=2, per_repo_cap=2)[0]), 1
            )
            for mutation in ("duplicate_source", "foreign_host", "outcome"):
                with self.subTest(mutation=mutation):
                    packet = json.loads(original)
                    if mutation == "outcome":
                        packet["analysis"] = "FORBIDDEN_FUTURE_ANALYSIS"
                    else:
                        packet["sources"][0]["url"] = (
                            f"https://raw.githubusercontent.com/owner/repo/{'a' * 40}/0.py"
                            if mutation == "duplicate_source"
                            else "https://private.example/file.py"
                        )
                    raw = json.dumps(packet)
                    db.execute("UPDATE jobs SET packet=? WHERE id='1'", (raw,))
                    db.execute(
                        "UPDATE research_action_shadow SET packet_sha256=? WHERE job_id='1'",
                        (hashlib.sha256(raw.encode()).hexdigest(),),
                    )
                    db.commit()
                    self.assertEqual(
                        len(enroll(path, created_after=10, limit=2, per_repo_cap=2)[0]),
                        1,
                    )
            db.close()

    def test_rejects_invalid_caps_before_opening_database(self):
        for kwargs in (
            {"created_after": float("nan")},
            {"created_after": -1},
            {"created_after": 0, "limit": 0},
            {"created_after": 0, "scan_limit": 3000},
            {"created_after": 0, "decision_point": "unknown"},
            {"created_after": 0, "enrollment": "best_outcomes"},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                enroll(Path("missing"), **kwargs)

    def test_initial_decisions_are_separate_from_followup_cohorts(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "scout.sqlite"
            db = sqlite3.connect(path)
            db.executescript("""
                CREATE TABLE jobs (id TEXT,packet TEXT,created REAL,finished REAL,state TEXT,result TEXT);
                CREATE TABLE research_action_shadow (job_id TEXT,policy_version TEXT,
                    packet_sha256 TEXT,recorded_at REAL,suggested_action TEXT,reason TEXT);
            """)
            for index, stage in enumerate(("source_audit", "issue_triage", "source_followup")):
                packet = {
                    "repo": "owner/repo",
                    "research": {"stage": stage},
                    "sources": [{
                        "url": f"https://raw.githubusercontent.com/owner/repo/{'a' * 40}/{index}.py"
                    }],
                }
                if stage == "source_followup":
                    packet["research"]["parent_job_id"] = "parent"
                    packet["untrusted_prior_analysis"] = "Previous hypothesis"
                raw = json.dumps(packet)
                db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?)",
                           (str(index), raw, 20, None, "PENDING", "FORBIDDEN_ANSWER"))
                db.execute("INSERT INTO research_action_shadow VALUES (?,?,?,?,?,?)",
                           (str(index), "policy", hashlib.sha256(raw.encode()).hexdigest(),
                            21, "RULE_NOT_A_LABEL", "reason"))
            db.commit()
            db.close()
            before = path.read_bytes()
            initial, metadata = enroll(path, created_after=10, limit=3,
                                       per_repo_cap=3, decision_point="initial")
            followup, _ = enroll(path, created_after=10, limit=3, per_repo_cap=3)
            self.assertEqual(len(initial), 2)
            self.assertEqual(len(followup), 1)
            self.assertEqual(metadata["decision_point"], "initial")
            self.assertEqual(path.read_bytes(), before)
            self.assertNotIn("FORBIDDEN_ANSWER", json.dumps(initial))
            self.assertNotIn("RULE_NOT_A_LABEL", json.dumps(initial))
            self.assertNotIn("untrusted_prior_analysis", json.dumps(initial))
            for field, value in (("parent_job_id", "parent"), ("root_job_id", "root")):
                db = sqlite3.connect(path)
                packet = json.loads(db.execute("SELECT packet FROM jobs WHERE id='0'").fetchone()[0])
                packet["research"][field] = value
                raw = json.dumps(packet)
                db.execute("UPDATE jobs SET packet=? WHERE id='0'", (raw,))
                db.execute("UPDATE research_action_shadow SET packet_sha256=? WHERE job_id='0'",
                           (hashlib.sha256(raw.encode()).hexdigest(),))
                db.commit()
                db.close()
                self.assertEqual(len(enroll(path, created_after=10, limit=3, per_repo_cap=3,
                                            decision_point="initial")[0]), 1)


if __name__ == "__main__":
    unittest.main()
