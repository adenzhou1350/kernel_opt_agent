"""A native counterexample can overturn an isolated legacy reproduction."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout_delivery as delivery


class NativeCounterexampleTests(unittest.TestCase):
    def test_owner_rejection_preserves_legacy_evidence_and_cost(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            delivery.initialize(root)
            original = {"before": {"exit_code": 1}, "fixed": {"exit_code": 0},
                        "claim_scope": "ADAPTED_SINGLE_MODULE_CPU_SCREEN_NOT_UPSTREAM_SUITE"}
            job = "a" * 24
            with delivery.database(root) as db:
                db.execute("INSERT INTO delivery(id,source_job_id,dedup_key,repo,title,state,updated_at,"
                           "payload,reason,reported_tokens,result) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                           (job, "source", "dedup", "public/project", "fixture", "REPRODUCED", 123,
                            "{}", "isolated callback test passed", 13681, json.dumps(original)))
            url = "https://github.com/public/project/blob/" + "b" * 40 + "/producer.py#L120"
            reason = "Native consumer needs a transposed result; proposed edit breaks its existing tests"
            decision = delivery.reject_owner_candidate(root, job, reason, url)
            with delivery.database(root) as db:
                row = dict(db.execute("SELECT * FROM delivery WHERE id=?", (job,)).fetchone())
            stored = json.loads(row["result"])
            self.assertEqual(row["state"], "NO_BUG")
            self.assertEqual(row["reported_tokens"], 13681)
            self.assertEqual(stored.pop("owner_rejection"), decision)
            self.assertEqual(stored, original)
            self.assertEqual(decision["prior_state"], "REPRODUCED")
            self.assertEqual(delivery.reject_owner_candidate(root, job, reason, url), decision)
            for state in ("PENDING", "TESTING", "PR_OPEN"):
                with self.subTest(state=state):
                    delivery.update(root, job, state, "untouched", original)
                    with self.assertRaisesRegex(ValueError, "terminal review"):
                        delivery.reject_owner_candidate(root, job, reason, url)
                    with delivery.database(root) as db:
                        self.assertEqual(db.execute("SELECT state FROM delivery WHERE id=?", (job,)).fetchone()[0], state)


if __name__ == "__main__":
    unittest.main()
