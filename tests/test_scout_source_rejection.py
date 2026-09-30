"""An explicit source audit can disprove a lead before costly environment repair."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout_delivery as delivery


class SourceRejectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        delivery.initialize(self.root)
        self.job_id = "a" * 24
        delivery.stage(
            self.root,
            [
                {
                    "id": "b" * 24,
                    "repo": "public/project",
                    "commit": "c" * 40,
                    "canonical_key": "one",
                    "packet": {},
                    "analysis": {"title": "test hypothesis"},
                }
            ],
        )
        with delivery.database(self.root) as db:
            self.job_id = db.execute("SELECT id FROM delivery").fetchone()[0]
        self.url = (
            "https://github.com/public/project/blob/" + "c" * 40 + "/module.py#L17"
        )

    def test_disprove_without_running_a_package(self):
        for state in ("ENVIRONMENT_BLOCKED", "INCONCLUSIVE", "GPU_REVIEW_REQUIRED"):
            with self.subTest(state=state):
                delivery.update(
                    self.root,
                    self.job_id,
                    state,
                    "missing package",
                    {"qualified": False, "private_raw": "kept"},
                )
                recorded = delivery.reject_owner_candidate(
                    self.root,
                    self.job_id,
                    "source proves the quantities equal",
                    self.url,
                )
                self.assertEqual(recorded["prior_state"], state)
                self.assertEqual(recorded["prior_reason"], "missing package")
                with delivery.database(self.root) as db:
                    row = db.execute(
                        "SELECT state,result FROM delivery WHERE id=?", (self.job_id,)
                    ).fetchone()
                self.assertEqual(row["state"], "NO_BUG")
                self.assertEqual(json.loads(row["result"])["private_raw"], "kept")
                self.assertFalse(json.loads(row["result"])["qualified"])
                self.assertEqual(
                    delivery.reject_owner_candidate(
                        self.root,
                        self.job_id,
                        "source proves the quantities equal",
                        self.url,
                    ),
                    recorded,
                )

    def test_active_pending_and_published_jobs_cannot_be_overridden(self):
        for state in ("PENDING", "GENERATING", "TESTING", "REPAIRING", "PR_OPEN"):
            with self.subTest(state=state):
                delivery.update(self.root, self.job_id, state)
                with self.assertRaisesRegex(ValueError, "terminal review"):
                    delivery.reject_owner_candidate(
                        self.root, self.job_id, "source audit", self.url
                    )

    def test_commit_and_repository_are_still_required(self):
        delivery.update(self.root, self.job_id, "ENVIRONMENT_BLOCKED")
        with self.assertRaisesRegex(ValueError, "commit-pinned"):
            delivery.reject_owner_candidate(
                self.root,
                self.job_id,
                "source audit",
                self.url.replace("c" * 40, "main"),
            )
        with self.assertRaisesRegex(ValueError, "repository"):
            delivery.reject_owner_candidate(
                self.root,
                self.job_id,
                "source audit",
                self.url.replace("public/project", "other/project"),
            )


if __name__ == "__main__":
    unittest.main()
