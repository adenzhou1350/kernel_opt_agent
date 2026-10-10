"""Native SQLite coverage: exact history, no evidence reads, explicit migration."""

import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout as scout
import kimi_scout_dashboard as dashboard
import kimi_scout_history_index as maintenance


class HistoryIndexTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        scout.initialize(self.root)
        self.database = self.root / "scout.sqlite"
        self.inbox = dashboard.Inbox(self.root)
        with scout.connect(self.root) as db:
            db.executemany(
                "INSERT INTO jobs(id,name,packet,state,created,started,finished,charge,result) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    (
                        f"{i:024x}",
                        "test",
                        json.dumps(
                            {
                                "repo": "test/repo",
                                "sources": [{"text": "x" * 1000}],
                                "research": {
                                    "stage": "reproduction_plan",
                                    "root_job_id": "root",
                                },
                            }
                        ),
                        "REVIEW",
                        i + 1,
                        9000,
                        9010,
                        42,
                        json.dumps(
                            {
                                "usage": {
                                    "input_tokens": 2,
                                    "output_tokens": 1,
                                    "total_tokens": 3,
                                    "cached_input_tokens": 0,
                                }
                            }
                        ),
                    )
                    for i in range(501)
                ),
            )

    def rows(self):
        return sorted(self.inbox.activity_rows(), key=lambda row: row["id"])

    def test_legacy_read_only_and_complete_state_equivalence(self):
        with patch.object(dashboard.time, "time", return_value=9020):
            before = self.inbox.state()
            self.assertEqual(before["summary"]["total_jobs"], 501)
            self.assertEqual(len(before["jobs"]), 500)
            self.assertEqual(before["activity"]["review_leaves"], 501)
            self.assertEqual(before["summary"]["reported_tokens"], 1503)
            with closing(sqlite3.connect(self.database)) as db:
                self.assertIsNone(
                    db.execute(
                        "SELECT 1 FROM sqlite_master WHERE name=?",
                        (dashboard.ACTIVITY_INDEX,),
                    ).fetchone()
                )
            maintenance.build_index(self.root)
            self.assertEqual(before, self.inbox.state())
        before_bytes = self.database.read_bytes()
        self.rows()
        self.assertEqual(before_bytes, self.database.read_bytes())

    def test_index_query_never_loads_table_payload_or_runs_json_functions(self):
        maintenance.build_index(self.root)
        with closing(sqlite3.connect(self.database)) as db:
            query = dashboard.ACTIVITY_QUERY + f" INDEXED BY {dashboard.ACTIVITY_INDEX}"
            vm = db.execute("EXPLAIN " + query).fetchall()
            rootpage = db.execute(
                "SELECT rootpage FROM sqlite_master WHERE name='jobs'"
            ).fetchone()[0]
            table_cursors = {
                row[2] for row in vm if row[1] == "OpenRead" and row[3] == rootpage
            }
            self.assertFalse(
                any(row[1] == "Column" and row[2] in table_cursors for row in vm)
            )
            self.assertFalse(any(row[1] in {"Function", "PureFunc"} for row in vm))
        # Verify the dashboard itself selects this path, rather than just an
        # independently constructed query having a good plan.
        connect = sqlite3.connect
        statements = []

        def traced(*args, **kwargs):
            db = connect(*args, **kwargs)
            db.set_trace_callback(statements.append)
            return db

        with patch.object(dashboard.sqlite3, "connect", side_effect=traced):
            self.rows()
        self.assertTrue(
            any(
                f"INDEXED BY {dashboard.ACTIVITY_INDEX}" in statement
                for statement in statements
            )
        )

    def test_live_mutations_null_usage_and_rollback_remain_exact(self):
        maintenance.build_index(self.root)
        with scout.connect(self.root) as db:
            db.execute(
                "UPDATE jobs SET state='FAILED',started=NULL,finished=NULL,charge=0,result=NULL,packet=? WHERE id=?",
                (
                    json.dumps(
                        {"repo": "other/repo", "research": {"parent_job_id": "parent"}}
                    ),
                    f"{0:024x}",
                ),
            )
            db.execute("DELETE FROM jobs WHERE id=?", (f"{1:024x}",))
            db.execute(
                "INSERT INTO jobs(id,name,packet,state,created) VALUES('new','test','{}','PENDING',42)"
            )
        with closing(sqlite3.connect(self.database)) as db:
            db.row_factory = sqlite3.Row
            expected = sorted(
                (
                    dict(row)
                    for row in db.execute(dashboard.ACTIVITY_QUERY + " NOT INDEXED")
                ),
                key=lambda row: row["id"],
            )
            self.assertEqual(self.rows(), expected)
            db.execute("UPDATE jobs SET state='RUNNING'")
            db.rollback()
        self.assertEqual(self.rows(), expected)
        maintenance.build_index(self.root)  # Idempotent, no duplicate records.
        self.assertEqual(self.rows(), expected)

    def test_interrupted_build_rolls_back_and_does_not_leave_partial_index(self):
        with (
            patch.object(maintenance.time, "monotonic", side_effect=[0] + [1000] * 100),
            self.assertRaisesRegex(sqlite3.OperationalError, "interrupted"),
        ):
            maintenance.build_index(self.root, timeout_seconds=1)
        with closing(sqlite3.connect(self.database)) as db:
            self.assertIsNone(
                db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name=?",
                    (dashboard.ACTIVITY_INDEX,),
                ).fetchone()
            )
        self.assertEqual(len(self.rows()), 501)
        maintenance.build_index(self.root)
        self.assertEqual(len(self.rows()), 501)

    def test_writer_contention_fails_without_queue_or_schema_mutation(self):
        with closing(sqlite3.connect(self.database)) as writer:
            writer.execute("BEGIN IMMEDIATE")
            with self.assertRaisesRegex(sqlite3.OperationalError, "locked"):
                maintenance.build_index(self.root, timeout_seconds=0.01)
            writer.rollback()
        self.assertEqual(len(self.rows()), 501)

    def test_missing_database_is_not_created(self):
        with self.assertRaises(sqlite3.OperationalError):
            maintenance.build_index(self.root / "missing")
        self.assertFalse((self.root / "missing").exists())
        for timeout in (0, -1, 3601, float("nan")):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                maintenance.build_index(self.root, timeout_seconds=timeout)


if __name__ == "__main__":
    unittest.main()
