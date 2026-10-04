"""Advisory shadow records only queue-time evidence; no model or network calls."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

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
    def test_native_primary_sources_are_not_missing_evidence(self):
        for extension in (".go", ".rs", ".c", ".cc", ".cxx"):
            with self.subTest(extension=extension):
                item = packet(extension, with_test=False)
                self.assertEqual(shadow.source_facts(item), (COMMIT, extension, False))
                self.assertEqual(shadow.suggest(item), (
                    "FIND_REPOSITORY_NATIVE_TEST", "PINNED_NONPYTHON_SOURCE_NO_TEST"))
                item = packet(extension, with_test=True)
                self.assertEqual(shadow.source_facts(item), (COMMIT, extension, True))
                self.assertEqual(shadow.suggest(item)[0], "CHECK_TEST_AND_DOWNSTREAM_CONTRACT")

    def test_storage_source_pins_survive_sampling_cluster_extraction(self):
        for repo, commit, path, extension in (
            ("juicedata/juicefs", "adcca1cc61bb4d668a945d64b2e176b44ac8e5b5", "pkg/object/sql.go", ".go"),
            ("lancedb/lancedb", "0be3ae960eb39b43faad5685cd381c5126a305c5", "rust/lancedb/src/table.rs", ".rs"),
        ):
            with self.subTest(repo=repo):
                item = {"repo": repo, "sources": [{
                    "url": f"https://raw.githubusercontent.com/{repo}/{commit}/{path}"}],
                    "research": {"stage": "source_audit", "frontier": {"commit": commit}}}
                self.assertEqual(shadow.source_facts(item), (commit, extension, False))
                self.assertEqual(shadow.suggest(item)[0], "FIND_REPOSITORY_NATIVE_TEST")
                item["research"]["frontier"]["commit"] = "c" * 40
                self.assertEqual(shadow.suggest(item), (
                    "VERIFY_PINNED_SOURCE", "SOURCE_FRONTIER_COMMIT_MISMATCH"))

    def test_new_native_extensions_do_not_relax_source_ownership(self):
        for extension in (".go", ".rs", ".cc"):
            with self.subTest(extension=extension):
                item = packet(extension, with_test=False)
                item["sources"][0]["url"] = item["sources"][0]["url"].replace("owner/repo", "other/repo")
                self.assertEqual(shadow.source_facts(item), (None, None, False))
                self.assertEqual(shadow.suggest(item)[1], "NO_SAME_REPOSITORY_PINNED_SOURCE")
        item = packet(".txt", with_test=False)
        self.assertEqual(shadow.source_facts(item), (None, None, False))

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
                self.assertEqual(row["policy_version"], shadow.POLICY_VERSION)
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

    def test_native_admission_keeps_existing_policy_rows_immutable(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            scout.initialize(root)
            with scout.connect(root) as db:
                shadow.initialize(db)
                for extension in (".go", ".rs"):
                    item = packet(extension, with_test=False)
                    job_id = scout.enqueue(root, item, db=db)
                    raw = scout.dumps(item)
                    shadow.record(db, job_id, item, raw)
                    before = dict(db.execute(
                        "SELECT * FROM research_action_shadow WHERE job_id=?", (job_id,)
                    ).fetchone())
                    self.assertEqual(before["source_commit"], COMMIT)
                    self.assertEqual(before["source_extension"], extension)
                    self.assertEqual(before["suggested_action"], "FIND_REPOSITORY_NATIVE_TEST")
                    with patch.object(shadow, "POLICY_VERSION", "later-experimental-policy"):
                        shadow.record(db, job_id, item, raw)
                    after = dict(db.execute(
                        "SELECT * FROM research_action_shadow WHERE job_id=?", (job_id,)
                    ).fetchone())
                    self.assertEqual(before, after)
                    self.assertEqual(db.execute("SELECT state FROM jobs WHERE id=?", (job_id,)).fetchone()[0], "PENDING")


if __name__ == "__main__":
    unittest.main()
