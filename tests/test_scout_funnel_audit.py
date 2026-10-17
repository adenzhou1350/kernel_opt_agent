"""Offline tests for read-only, censored Scout funnel accounting."""

import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import scout_funnel_audit as funnel


class FunnelAuditTests(unittest.TestCase):
    def receipt_fixture(self, rows):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name).resolve()
        (root / "results").mkdir()
        scout, delivery = root / "scout.sqlite", root / "delivery.sqlite"
        with closing(sqlite3.connect(scout)) as db:
            db.execute("CREATE TABLE jobs (id TEXT,packet TEXT,state TEXT,charge INT,created REAL,result TEXT)")
            db.execute("CREATE TABLE research_action_shadow (job_id TEXT,source_class TEXT)")
            db.executemany("INSERT INTO jobs VALUES (?,?,?,?,?,?)", [
                (job_id, '{"repo":"a/b","research":{"stage":"source_audit"}}',
                 state, charge, 10, result)
                for job_id, state, charge, result in rows
            ])
            db.commit()
        with closing(sqlite3.connect(delivery)) as db:
            db.execute("CREATE TABLE delivery (source_job_id TEXT,state TEXT,reason TEXT)")
            db.commit()
        return root, scout, delivery

    def test_failed_receipt_usage_is_opt_in_bound_and_read_only(self):
        job_id = "a" * 24
        root, scout, delivery = self.receipt_fixture([
            (job_id, "FAILED", 23, "null"),
            ("b" * 24, "NO_LEAD", 19, '{"usage":{"total_tokens":19}}'),
        ])
        receipt = {"job_id": job_id, "state": "FAILED", "charge_basis": "provider_report",
                   "charged_tokens_or_reservation": 23,
                   "token_accounting": {"reported_usage": {"total_tokens": 23}}}
        path = root / "results" / (job_id + ".json")
        path.write_text(json.dumps(receipt), encoding="utf-8")
        before = {p: p.read_bytes() for p in (scout, delivery, path)}
        plain = funnel.audit(scout, delivery, 9, 11)
        self.assertEqual(plain["groups"][0]["reported_model_tokens"], 19)
        self.assertEqual(plain["groups"][0]["jobs_without_known_usage_in_projection"], 1)
        recovered = funnel.audit(scout, delivery, 9, 11, root)
        group = recovered["groups"][0]
        self.assertEqual(group["reported_model_tokens"], 42)
        self.assertEqual(group["jobs_with_reported_usage"], 2)
        self.assertEqual(group["jobs_with_receipt_usage"], 1)
        self.assertEqual(group["jobs_without_known_usage_in_projection"], 0)
        self.assertEqual(group["scout_states"], {"FAILED": 1, "NO_LEAD": 1})
        self.assertEqual(recovered["receipt_recovery"]["recovered"], 1)
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_receipt_recovery_rejects_missing_partial_or_unbound_usage(self):
        job_id = "a" * 24
        root, scout, delivery = self.receipt_fixture([(job_id, "FAILED", 23, "null")])
        valid = {"job_id": job_id, "state": "FAILED", "charge_basis": "provider_report",
                 "charged_tokens_or_reservation": 23,
                 "token_accounting": {"reported_usage": {"total_tokens": 23}}}
        bad = [
            {**valid, "job_id": "b" * 24}, {**valid, "state": "REVIEW"},
            {**valid, "charge_basis": "reservation"},
            {**valid, "charged_tokens_or_reservation": 24},
            {**valid, "charged_tokens_or_reservation": True},
            {**valid, "token_accounting": {"reported_usage": {"input_tokens": 23}}},
            *[{**valid, "token_accounting": {"reported_usage": {"total_tokens": value}}}
              for value in (True, "23", -1, 23.0, None)],
            {**valid, "token_accounting": {"interrupted_usage_observation": {"total_tokens": 23}}},
        ]
        path = root / "results" / (job_id + ".json")
        for item in bad:
            with self.subTest(item=item):
                path.write_text(json.dumps(item), encoding="utf-8")
                result = funnel.audit(scout, delivery, 9, 11, root)
                self.assertEqual(result["groups"][0]["reported_model_tokens"], 0)
                self.assertEqual(result["receipt_recovery"]["unavailable_or_unbound"], 1)
        for raw in ("not json", json.dumps(valid)[:-1] + ',"state":"FAILED"}',
                    json.dumps(valid) + " " * funnel.MAX_RECEIPT_BYTES):
            path.write_text(raw, encoding="utf-8")
            self.assertIsNone(funnel.receipt_usage(root, job_id, "FAILED", 23))
        self.assertIsNone(funnel.receipt_usage(root, "../outside", "FAILED", 23))
        with self.assertRaises(ValueError):
            funnel.audit(scout, delivery, 9, 11, root / "results")

    def test_recovery_does_not_multiply_cost_with_delivery_rows(self):
        job_id = "a" * 24
        root, scout, delivery = self.receipt_fixture([(job_id, "FAILED", 0, "null")])
        (root / "results" / (job_id + ".json")).write_text(json.dumps({
            "job_id": job_id, "state": "FAILED", "charge_basis": "provider_report",
            "charged_tokens_or_reservation": 0,
            "token_accounting": {"reported_usage": {"total_tokens": 0}},
        }), encoding="utf-8")
        with closing(sqlite3.connect(delivery)) as db:
            db.executemany("INSERT INTO delivery VALUES (?,?,?)", [(job_id, "PENDING", "")] * 2)
            db.commit()
        result = funnel.audit(scout, delivery, 9, 11, root)
        self.assertEqual(result["receipt_recovery"]["attempted"], 1)
        self.assertEqual(result["groups"][0]["jobs_with_reported_usage"], 1)
        self.assertEqual(result["groups"][0]["reported_model_tokens"], 0)

    def test_receipt_read_budget_preserves_unknowns(self):
        rows = [(f"{i:024x}", "FAILED", 5, "null")
                for i in range(funnel.MAX_RECEIPT_READS + 1)]
        root, scout, delivery = self.receipt_fixture(rows)
        result = funnel.audit(scout, delivery, 9, 11, root)
        self.assertEqual(result["receipt_recovery"]["attempted"], funnel.MAX_RECEIPT_READS)
        self.assertEqual(result["receipt_recovery"]["over_limit"], 1)
        self.assertEqual(result["groups"][0]["jobs_without_known_usage_in_projection"], len(rows))

    def test_sql_boolean_and_float_are_not_reported_token_counts(self):
        root, scout, delivery = self.receipt_fixture([
            ("a" * 24, "FAILED", 1, '{"usage":{"total_tokens":true}}'),
            ("b" * 24, "FAILED", 1, '{"usage":{"total_tokens":1.0}}'),
        ])
        result = funnel.audit(scout, delivery, 9, 11)
        self.assertEqual(result["groups"][0]["reported_model_tokens"], 0)
        self.assertEqual(result["groups"][0]["jobs_without_known_usage_in_projection"], 2)

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
                            '{"owner_score":'
                            + str({"job-1": 1, "job-2": 2, "job-3": 5}[source])
                            + ',"pr":{"url":"https://github.com/a/b/pull/'
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
                            '{"owner_score":2,"pr":{"url":"https://github.com/other/repo/pull/12"}}',
                        )
                    ],
                )
                db.commit()
            result = funnel.audit(scout, delivery, 10, 14)
            self.assertEqual(result["schema_version"], "scout-funnel-snapshot-v3")
            self.assertEqual(result["pr_open_candidate_rows"], 5)
            self.assertEqual(result["unique_linked_prs"], 2)
            self.assertEqual(result["invalid_pr_link_rows"], 1)
            group = result["groups"][0]
            self.assertEqual(group["jobs"], 3)
            self.assertEqual(group["charged_tokens_or_reservation"], 60)
            self.assertEqual(group["reported_model_tokens"], 6)
            self.assertEqual(group["delivery_states"], {"PR_OPEN": 5})
            self.assertEqual(group["unique_linked_prs"], 2)
            self.assertEqual(
                result["owner_score_snapshot"],
                [
                    {
                        "owner_score": 1,
                        "owner_review_required_rows": 0,
                        "pr_open_candidate_rows": 2,
                        "unique_linked_prs": 1,
                    },
                    {
                        "owner_score": 2,
                        "owner_review_required_rows": 0,
                        "pr_open_candidate_rows": 2,
                        "unique_linked_prs": 1,
                    },
                    {
                        "owner_score": 5,
                        "owner_review_required_rows": 0,
                        "pr_open_candidate_rows": 1,
                        "unique_linked_prs": 1,
                    },
                ],
            )

    def test_unscored_owner_review_is_not_treated_as_low_score(self):
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
                        (job, '{"repo":"a/b"}', "REVIEW", 1, 10, "{}")
                        for job in ("job-1", "job-2")
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
                        ("job-1", "OWNER_REVIEW_REQUIRED", "", "{}"),
                        ("job-2", "OWNER_REVIEW_REQUIRED", "", '{"owner_score":true}'),
                    ],
                )
                db.commit()
            result = funnel.audit(scout, delivery, 10, 11)
            self.assertEqual(result["owner_score_snapshot"], [])
            self.assertEqual(result["unscored_owner_candidate_rows"], 2)


if __name__ == "__main__":
    unittest.main()
