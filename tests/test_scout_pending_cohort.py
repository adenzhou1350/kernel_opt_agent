import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

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
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                enroll(Path("missing"), **kwargs)


if __name__ == "__main__":
    unittest.main()
