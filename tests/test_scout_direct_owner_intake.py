"""Direct intake and publication accounting; no model, network or upstream code."""

import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout_delivery as delivery


def lead(number=1, *, native=False):
    value = {
        "id": str(number),
        "repo": "public/project",
        "canonical_key": "direct-intake-" + str(number),
        "packet": {"sources": []},
        "analysis": {"title": "fixture"},
    }
    if native:
        value["verification_route"] = "OWNER_NATIVE_CPU_REVIEW_ONLY"
    return value


class DirectOwnerIntakeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "delivery"
        delivery.initialize(self.root)
        self.url = "https://github.com/public/project/pull/23"

    def rows(self):
        with delivery.database(self.root) as db:
            return [
                dict(row) for row in db.execute("SELECT * FROM delivery ORDER BY id")
            ]

    def admit(self):
        self.assertEqual(delivery.stage(self.root, [lead()], owner_review=True), 1)
        return self.rows()[0]

    def test_admission_never_schedules_or_qualifies_work(self):
        row = self.admit()
        self.assertEqual(row["state"], delivery.OWNER_STATE)
        self.assertEqual(row["reported_tokens"], 0)
        self.assertEqual(json.loads(row["payload"]), lead())
        self.assertEqual(
            json.loads(row["result"]), {"intake": "owner_review_unverified"}
        )
        self.assertIsNone(delivery.claim(self.root))
        self.assertEqual(list((self.root / "jobs").iterdir()), [])

    def test_explicit_publication_needs_no_executor_file_and_is_idempotent(self):
        row = self.admit()
        self.assertNotIn("pr", json.loads(row["result"]))
        recorded = delivery.mark_pr(self.root, row["id"], self.url)
        self.assertEqual(recorded["intake"], "owner_review_unverified")
        self.assertIn("no automatic reproduction", recorded["claim_boundary"])
        stored = self.rows()[0]
        self.assertEqual(delivery.mark_pr(self.root, row["id"], self.url), recorded)
        self.assertEqual(self.rows()[0], stored)
        self.assertEqual(stored["state"], "PR_OPEN")
        self.assertEqual(stored["reported_tokens"], 0)
        self.assertEqual(json.loads(stored["result"])["pr"]["url"], self.url)
        self.assertEqual(list((self.root / "jobs").iterdir()), [])

    def test_publication_keeps_independent_evidence_and_cost(self):
        row = self.admit()
        evidence = {
            "intake": "owner_review_unverified",
            "native_result": {"passed": 3, "performance": "NOT_RUN"},
        }
        delivery.update(
            self.root, row["id"], delivery.OWNER_STATE, "observed", evidence
        )
        with delivery.database(self.root) as db:
            db.execute(
                "UPDATE delivery SET reported_tokens=321 WHERE id=?", (row["id"],)
            )
        delivery.mark_pr(self.root, row["id"], self.url)
        stored = self.rows()[0]
        result = json.loads(stored["result"])
        result.pop("pr")
        self.assertEqual(result, evidence)
        self.assertEqual(stored["reported_tokens"], 321)

    def test_default_admission_and_duplicates_keep_previous_behavior(self):
        self.assertEqual(delivery.stage(self.root, [lead()]), 1)
        original = self.rows()[0]
        self.assertEqual(original["state"], "PENDING")
        self.assertEqual(json.loads(original["result"]), {})
        self.assertEqual(delivery.stage(self.root, [lead()], owner_review=True), 0)
        self.assertEqual(self.rows()[0], original)
        claimed = delivery.claim(self.root)
        self.assertEqual(claimed["id"], original["id"])
        delivery.update(
            self.root, original["id"], "INCONCLUSIVE", "retained", {"raw": 1}
        )
        original = self.rows()[0]
        self.assertEqual(delivery.stage(self.root, [lead()], owner_review=True), 0)
        self.assertEqual(self.rows()[0], original)
        self.assertEqual(delivery.stage(self.root, [lead(2)], owner_review=True), 1)
        original = self.rows()
        self.assertEqual(delivery.stage(self.root, [lead(2)]), 0)
        self.assertEqual(self.rows(), original)
        self.assertIsNone(delivery.claim(self.root))

    def test_automatic_owner_rows_still_require_matching_executor_handoff(self):
        delivery.stage(self.root, [lead()])
        row = delivery.claim(self.root)
        delivery.update(self.root, row["id"], delivery.OWNER_STATE, "executor", {})
        before = self.rows()
        with self.assertRaisesRegex(ValueError, "matching owner handoff"):
            delivery.mark_pr(self.root, row["id"], self.url)
        self.assertEqual(self.rows(), before)
        handoff = self.root / "jobs" / row["id"] / "owner-handoff.json"
        handoff.parent.mkdir()
        handoff.write_text(json.dumps({"candidate_id": row["id"]}), encoding="utf-8")
        delivery.mark_pr(self.root, row["id"], self.url)
        self.assertNotIn("intake", json.loads(self.rows()[0]["result"])["pr"])

    def test_marker_cannot_publish_active_or_parked_rows(self):
        row = self.admit()
        for state in ("PENDING", "GENERATING", "FAILED", "OWNER_PARKED"):
            with self.subTest(state=state):
                delivery.update(
                    self.root,
                    row["id"],
                    state,
                    "unchanged marker",
                    {
                        "intake": "owner_review_unverified",
                    },
                )
                before = self.rows()
                with self.assertRaisesRegex(ValueError, "owner review"):
                    delivery.mark_pr(self.root, row["id"], self.url)
                self.assertEqual(self.rows(), before)

    def test_mismatched_invalid_and_relinked_urls_do_not_mutate_queue(self):
        row = self.admit()
        for url in (
            "https://github.com/other/project/pull/23",
            self.url + "?view=1",
            "http://github.com/public/project/pull/23",
        ):
            with self.subTest(url=url):
                before = self.rows()
                with self.assertRaises(ValueError):
                    delivery.mark_pr(self.root, row["id"], url)
                self.assertEqual(self.rows(), before)
        delivery.mark_pr(self.root, row["id"], self.url)
        before = self.rows()
        with self.assertRaisesRegex(ValueError, "another PR"):
            delivery.mark_pr(self.root, row["id"], self.url[:-2] + "24")
        self.assertEqual(self.rows(), before)

    def test_native_owner_route_cannot_enter_automatic_queue(self):
        with self.assertRaisesRegex(ValueError, "owner_review=True"):
            delivery.stage(self.root, [lead(), lead(2, native=True)])
        self.assertEqual(self.rows(), [])  # The first INSERT rolls back too.
        self.assertEqual(
            delivery.stage(self.root, [lead(native=True)], owner_review=True), 1
        )
        self.assertIsNone(delivery.claim(self.root))

    def test_boolean_mode_and_bounded_admission(self):
        for mode in (1, "false", None):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "boolean"):
                delivery.stage(self.root, [lead()], owner_review=mode)
        self.assertEqual(self.rows(), [])
        self.assertEqual(
            delivery.stage(self.root, [lead(), lead(2)], limit=1, owner_review=True), 1
        )
        self.assertEqual(len(self.rows()), 1)

    def test_parallel_claims_cannot_acquire_direct_intake(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            admission = pool.submit(
                delivery.stage, self.root, [lead()], owner_review=True
            )
            claims = [pool.submit(delivery.claim, self.root) for _ in range(12)]
            self.assertEqual(admission.result(), 1)
            self.assertTrue(all(future.result() is None for future in claims))
        self.assertEqual(self.rows()[0]["state"], delivery.OWNER_STATE)


if __name__ == "__main__":
    unittest.main()
