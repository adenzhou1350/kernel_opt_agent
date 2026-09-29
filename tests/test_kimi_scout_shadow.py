"""Advisory shadow records only queue-time evidence; no model or network calls."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout as scout
import kimi_scout_shadow as shadow


COMMIT = "a" * 40


def packet(extension=".ts", with_test=True):
    sources = [
        {
            "url": f"https://raw.githubusercontent.com/owner/repo/{COMMIT}/src/thing{extension}",
            "text": "public code",
        }
    ]
    if with_test:
        sources.append(
            {
                "url": f"https://raw.githubusercontent.com/owner/repo/{COMMIT}/src/thing.test{extension}",
                "text": "registered test",
            }
        )
    return {
        "name": "shadow-case",
        "repo": "owner/repo",
        "sources": sources,
        "research": {
            "stage": "source_audit",
            "frontier": {
                "commit": COMMIT,
                "base_commit": "b" * 40,
                "changed_blob": True,
            },
        },
    }


class ShadowTests(unittest.TestCase):
    def test_source_test_contract_suggested_without_rejection(self):
        item = packet()
        self.assertEqual(shadow.source_facts(item), (COMMIT, ".ts", True))
        self.assertEqual(
            shadow.suggest(item),
            ("CHECK_TEST_AND_DOWNSTREAM_CONTRACT", "TEST_SOURCE_IN_PACKET"),
        )
        self.assertEqual(
            shadow.suggest(packet(".cu", with_test=False))[0],
            "VERIFY_BUILD_ARCH_AND_NATIVE_TEST",
        )
        experimental = packet(".cu", with_test=False)
        experimental["sources"][0]["url"] = (
            f"https://raw.githubusercontent.com/owner/repo/{COMMIT}/src/experimental/thing.cu"
        )
        self.assertEqual(shadow.source_class(experimental), "experimental")
        self.assertEqual(shadow.source_class(packet()), "other")

    def test_cross_repository_test_cannot_satisfy_source_fact(self):
        item = packet(with_test=False)
        item["sources"].append(
            {
                "url": f"https://raw.githubusercontent.com/other/repo/{COMMIT}/src/thing.test.ts",
                "text": "unrelated test",
            }
        )
        self.assertEqual(shadow.source_facts(item), (COMMIT, ".ts", False))

    def test_issue_without_source_is_not_labeled_no_bug(self):
        item = packet()
        item["research"]["stage"] = "issue_triage"
        item["sources"] = [{"url": "https://github.com/owner/repo/issues/1", "text": "report"}]
        self.assertEqual(
            shadow.suggest(item)[0], "VERIFY_ISSUE_ON_CURRENT_SOURCE"
        )

    def test_source_frontier_mismatch_requires_identity_check(self):
        item = packet()
        item["research"]["frontier"]["commit"] = "c" * 40
        self.assertEqual(
            shadow.suggest(item),
            ("VERIFY_PINNED_SOURCE", "SOURCE_FRONTIER_COMMIT_MISMATCH"),
        )

    def test_record_is_predecision_and_packet_bound(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            scout.initialize(root)
            item = packet()
            with scout.connect(root) as db:
                shadow.initialize(db)
                job_id = scout.enqueue(root, item, db=db)
                shadow.record(db, job_id, item, scout.dumps(item))
                row = db.execute(
                    "SELECT * FROM research_action_shadow WHERE job_id=?", (job_id,)
                ).fetchone()
                self.assertEqual(row["suggested_action"], "CHECK_TEST_AND_DOWNSTREAM_CONTRACT")
                self.assertEqual(row["has_test_source"], 1)
                self.assertEqual(row["changed_blob"], 1)
                self.assertEqual(row["source_commit"], COMMIT)
                self.assertEqual(row["source_class"], "other")
                self.assertEqual(row["authority"], "ADVISORY_ONLY_NO_REJECTION_NO_EXECUTION")
                self.assertNotIn("result", row.keys())
                self.assertEqual(
                    db.execute("SELECT state FROM jobs WHERE id=?", (job_id,)).fetchone()[0],
                    "PENDING",
                )
                with self.assertRaisesRegex(ValueError, "exact pending packet"):
                    shadow.record(db, job_id, item, json.dumps(item, indent=2))
                db.execute("UPDATE jobs SET state='REVIEW',result='future' WHERE id=?", (job_id,))
                with self.assertRaisesRegex(ValueError, "exact pending packet"):
                    shadow.record(db, job_id, item, scout.dumps(item))
                self.assertEqual(
                    db.execute("SELECT count(*) FROM research_action_shadow").fetchone()[0], 1
                )


if __name__ == "__main__":
    unittest.main()
