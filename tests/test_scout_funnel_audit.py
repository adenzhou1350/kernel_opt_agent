"""Offline tests for read-only, censored Scout funnel accounting."""

import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import scout_funnel_audit as funnel


class FunnelAuditTests(unittest.TestCase):
    def test_snapshot_preserves_blockers_and_undelivered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scout = root / "scout.sqlite"
            delivery = root / "delivery.sqlite"
            with closing(sqlite3.connect(scout)) as db:
                db.execute(
                    "CREATE TABLE jobs (id TEXT, packet TEXT, state TEXT, charge INT, created REAL, result TEXT)"
                )
                db.execute(
                    "CREATE TABLE research_action_shadow (job_id TEXT, source_class TEXT)"
                )
                db.executemany(
                    "INSERT INTO jobs VALUES (?,?,?,?,?,?)",
                    [
                        (
                            "one",
                            '{"repo":"a/b","research":{"stage":"source_audit"}}',
                            "REVIEW",
                            50,
                            10,
                            '{"usage":{"total_tokens":45}}',
                        ),
                        (
                            "two",
                            '{"repo":"a/b","research":{"stage":"source_audit"}}',
                            "REVIEW",
                            30,
                            11,
                            "{}",
                        ),
                        ("old", '{"repo":"a/b"}', "NO_LEAD", 100, 9, "{}"),
                    ],
                )
                db.executemany(
                    "INSERT INTO research_action_shadow VALUES (?,?)",
                    [("one", "experimental"), ("two", "experimental")],
                )
                db.commit()
            with closing(sqlite3.connect(delivery)) as db:
                db.execute(
                    "CREATE TABLE delivery (source_job_id TEXT, state TEXT, reason TEXT)"
                )
                db.execute(
                    "INSERT INTO delivery VALUES (?,?,?)",
                    (
                        "one",
                        "ENVIRONMENT_BLOCKED",
                        "x.py: relative import requires package context (line 1)",
                    ),
                )
                db.commit()
            result = funnel.audit(scout, delivery, 10, 12)
            self.assertEqual(len(result["groups"]), 1)
            group = result["groups"][0]
            self.assertEqual(group["jobs"], 2)
            self.assertEqual(group["reported_model_tokens"], 45)
            self.assertEqual(group["charged_tokens_or_reservation"], 80)
            self.assertEqual(group["jobs_with_reported_usage"], 1)
            self.assertEqual(
                group["delivery_states"], {"ENVIRONMENT_BLOCKED": 1, "NOT_DELIVERED": 1}
            )
            self.assertEqual(group["environment_blockers"], {"package_context": 1})
            self.assertIn("censored", result["claim_boundary"])

    def test_bad_window_is_rejected(self):
        with self.assertRaises(ValueError):
            funnel.audit(Path("missing"), Path("missing"), 2, 1)

    def test_unique_prs_do_not_inflate_job_or_token_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scout = root / "scout.sqlite"
            delivery = root / "delivery.sqlite"
            with closing(sqlite3.connect(scout)) as db:
                db.execute(
                    "CREATE TABLE jobs (id TEXT, packet TEXT, state TEXT, charge INT, created REAL, result TEXT)"
                )
                db.execute(
                    "CREATE TABLE research_action_shadow (job_id TEXT, source_class TEXT)"
                )
                db.executemany(
                    "INSERT INTO jobs VALUES (?,?,?,?,?,?)",
                    [
                        (
                            f"job-{index}",
                            '{"repo":"a/b","research":{"stage":"source_audit"}}',
                            "REVIEW",
                            index * 10,
                            10 + index,
                            '{"usage":{"total_tokens":2}}',
                        )
                        for index in (1, 2, 3)
                    ],
                )
                db.commit()
            with closing(sqlite3.connect(delivery)) as db:
                db.execute(
                    "CREATE TABLE delivery (source_job_id TEXT, state TEXT, reason TEXT, result TEXT)"
                )
                db.executemany(
                    "INSERT INTO delivery VALUES (?,?,?,?)",
                    [
                        (
                            source,
                            "PR_OPEN",
                            "",
                            '{"pr":{"url":"https://github.com/a/b/pull/'
                            + number
                            + '"}}',
                        )
                        for source, number in (
                            ("job-1", "10"),
                            ("job-1", "10"),
                            ("job-2", "10"),
                            ("job-3", "11"),
                        )
                    ]
                    + [
                        (
                            "job-2",
                            "PR_OPEN",
                            "",
                            '{"pr":{"url":"https://github.com/other/repo/pull/12"}}',
                        )
                    ],
                )
                db.commit()
            result = funnel.audit(scout, delivery, 10, 14)
            self.assertEqual(result["schema_version"], "scout-funnel-snapshot-v2")
            self.assertEqual(result["pr_open_candidate_rows"], 5)
            self.assertEqual(result["unique_linked_prs"], 2)
            self.assertEqual(result["invalid_pr_link_rows"], 1)
            group = result["groups"][0]
            self.assertEqual(group["jobs"], 3)
            self.assertEqual(group["charged_tokens_or_reservation"], 60)
            self.assertEqual(group["reported_model_tokens"], 6)
            self.assertEqual(group["delivery_states"], {"PR_OPEN": 5})
            self.assertEqual(group["unique_linked_prs"], 2)


if __name__ == "__main__":
    unittest.main()
