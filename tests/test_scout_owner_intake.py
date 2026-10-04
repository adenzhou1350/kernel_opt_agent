"""Native offline owner-intake tests; no model, upstream execution or network."""

import json
import sqlite3
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout_delivery as delivery
from kimi_scout_delivery_source import select_leads


class OwnerIntakeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.queue = self.root / "delivery"
        delivery.initialize(self.queue)
        packet = {
            "repo": "owner/project",
            "sources": [
                {
                    "url": "https://raw.githubusercontent.com/owner/project/"
                    + "a" * 40
                    + "/src/check.py",
                    "text": "1: pass",
                }
            ],
            "research": {"stage": "reproduction_plan", "parent_job_id": None},
        }
        with closing(sqlite3.connect(self.root / "scout.sqlite")) as db:
            db.execute(
                "CREATE TABLE jobs "
                "(id TEXT,state TEXT,packet TEXT,result TEXT,finished REAL)"
            )
            for i in range(4):
                db.execute(
                    "INSERT INTO jobs VALUES (?,?,?,?,?)",
                    (
                        str(i),
                        "REVIEW",
                        json.dumps(packet),
                        json.dumps(
                            {"analysis": {"title": str(i), "hypothesis": str(i)}}
                        ),
                        i,
                    ),
                )
            db.commit()
        self.leads = select_leads(self.root, limit=4, scan_limit=4)

    def rows(self):
        with delivery.database(self.queue) as db:
            return [dict(row) for row in db.execute("SELECT * FROM delivery")]

    def test_owner_intake_is_nonexecuting_and_excluded_from_selection(self):
        self.assertEqual(delivery.stage(self.queue, self.leads, owner_review=True), 4)
        self.assertIsNone(delivery.claim(self.queue))
        self.assertEqual(select_leads(self.root, limit=4, scan_limit=4), [])
        rows = self.rows()
        self.assertEqual({row["state"] for row in rows}, {delivery.OWNER_STATE})
        self.assertTrue(all(row["reported_tokens"] == 0 for row in rows))
        self.assertTrue(all(json.loads(row["result"]) == {} for row in rows))
        self.assertEqual(
            {json.loads(row["payload"])["id"] for row in rows},
            {lead["id"] for lead in self.leads},
        )

    def test_default_and_duplicate_intake_preserve_existing_evidence(self):
        first, second = self.leads[:2]
        delivery.stage(self.queue, [first])
        claimed = delivery.claim(self.queue)
        self.assertEqual(claimed["source_job_id"], first["id"])
        delivery.update(
            self.queue,
            claimed["id"],
            "INCONCLUSIVE",
            "independent observation retained",
            {"observed": {"exit_code": 1}},
        )
        original = self.rows()[0]
        self.assertEqual(delivery.stage(self.queue, [first], owner_review=True), 0)
        self.assertEqual(self.rows()[0], original)
        self.assertEqual(delivery.stage(self.queue, [second], owner_review=True), 1)
        self.assertEqual(delivery.stage(self.queue, [second]), 0)
        self.assertIsNone(delivery.claim(self.queue))

    def test_parallel_claim_cannot_acquire_owner_intake(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [
                pool.submit(delivery.stage, self.queue, self.leads, owner_review=True)
            ]
            futures += [pool.submit(delivery.claim, self.queue) for _ in range(12)]
            self.assertEqual(futures[0].result(), 4)
            self.assertTrue(all(future.result() is None for future in futures[1:]))
        self.assertEqual({row["state"] for row in self.rows()}, {delivery.OWNER_STATE})

    def test_limit_and_invalid_mode_are_not_implicit_truthiness(self):
        for mode in (1, "false", None):
            with self.assertRaisesRegex(ValueError, "boolean"):
                delivery.stage(self.queue, self.leads, owner_review=mode)
        self.assertEqual(self.rows(), [])
        self.assertEqual(
            delivery.stage(self.queue, self.leads, limit=1, owner_review=True), 1
        )
        self.assertEqual(len(self.rows()), 1)


if __name__ == "__main__":
    unittest.main()
