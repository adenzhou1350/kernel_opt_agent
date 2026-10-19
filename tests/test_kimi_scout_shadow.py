"""Advisory shadow records only queue-time evidence; no model or network calls."""

import hashlib
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
    def test_native_language_sources_and_companion_tests_are_recognized(self):
        for extension, test_path in (
            (".go", "src/thing_test.go"),
            (".rs", "tests/thing.rs"),
            (".c", "tests/test_thing.c"),
            (".cc", "tests/thing_test.cc"),
            (".cxx", "tests/thing_test.cxx"),
        ):
            with self.subTest(extension=extension):
                item = packet(extension, with_test=False)
                self.assertEqual(shadow.source_facts(item), (COMMIT, extension, False))
                self.assertEqual(shadow.suggest(item),
                    ("FIND_REPOSITORY_NATIVE_TEST", "PINNED_NONPYTHON_SOURCE_NO_TEST"))
                item["sources"].append({
                    "url": f"https://raw.githubusercontent.com/owner/repo/{COMMIT}/{test_path}",
                    "text": "registered native test",
                })
                self.assertEqual(shadow.source_facts(item), (COMMIT, extension, True))
                self.assertEqual(shadow.suggest(item),
                    ("CHECK_TEST_AND_DOWNSTREAM_CONTRACT", "TEST_SOURCE_IN_PACKET"))
                for unrelated in (
                    item["sources"][1]["url"].replace("owner/repo", "other/repo"),
                    item["sources"][1]["url"].replace(COMMIT, "b" * 40),
                ):
                    item["sources"][1]["url"] = unrelated
                    self.assertEqual(shadow.source_facts(item), (COMMIT, extension, False))

    def test_source_extension_facts_cover_the_existing_discovery_frontier(self):
        import kimi_scout_research as research
        self.assertEqual(set(shadow.SOURCE_EXTENSIONS), set(research.SOURCE_SUFFIXES))
        for extension in (".yaml", ".toml", ".txt"):
            with self.subTest(extension=extension):
                self.assertEqual(shadow.source_facts(packet(extension)), (None, None, False))

    def test_policy_upgrade_preserves_old_records_and_versions_new_admissions(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            scout.initialize(root)
            old = packet(".go", with_test=False)
            with scout.connect(root) as db:
                shadow.initialize(db)
                old_id = scout.enqueue(root, old, db=db)
                # Exact v1 semantics for an unsupported Go suffix, not a fresh
                # v2 decision mislabeled as historical evidence.
                with (
                    patch.object(shadow, "POLICY_VERSION", "predecision-native-test-baseline-v1"),
                    patch.object(shadow, "source_facts", return_value=(None, None, False)),
                ):
                    shadow.record(db, old_id, old, scout.dumps(old))
                before = dict(db.execute("SELECT * FROM research_action_shadow WHERE job_id=?",
                                          (old_id,)).fetchone())
                shadow.record(db, old_id, old, scout.dumps(old))
                after = dict(db.execute("SELECT * FROM research_action_shadow WHERE job_id=?",
                                         (old_id,)).fetchone())
                self.assertEqual(after, before)
                self.assertEqual(after["suggested_action"], "VERIFY_PINNED_SOURCE")
                fresh = dict(old, name="new-admission")
                fresh_id = scout.enqueue(root, fresh, db=db)
                shadow.record(db, fresh_id, fresh, scout.dumps(fresh))
                row = db.execute("SELECT * FROM research_action_shadow WHERE job_id=?",
                                 (fresh_id,)).fetchone()
                self.assertEqual(row["policy_version"], "predecision-native-test-baseline-v2")
                self.assertEqual(row["source_extension"], ".go")
                self.assertEqual(row["suggested_action"], "FIND_REPOSITORY_NATIVE_TEST")
                self.assertEqual(row["packet_sha256"],
                    hashlib.sha256(scout.dumps(fresh).encode()).hexdigest())
                self.assertEqual([row[0] for row in db.execute("SELECT state FROM jobs")],
                                 ["PENDING", "PENDING"])

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
