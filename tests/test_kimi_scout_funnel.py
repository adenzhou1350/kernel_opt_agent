import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from sys import path

path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from kimi_scout_funnel import inspect  # noqa: E402


class FunnelTest(unittest.TestCase):
    def test_counts_review_leaves_and_blockers_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with closing(sqlite3.connect(root / "scout.sqlite")) as connection:
                connection.execute(
                    "CREATE TABLE jobs (id TEXT,state TEXT,packet TEXT,result TEXT)"
                )
                rows = [
                    ("a", "REVIEW", "repo/one", "source_audit", None, 7),
                    ("b", "REVIEW", "repo/one", "reproduction_plan", "a", 11),
                    ("c", "NO_LEAD", "repo/two", "source_audit", None, 13),
                    ("d", "PENDING", "repo/two", "issue_triage", None, None),
                ]
                for job_id, state, repo, stage, parent, tokens in rows:
                    connection.execute(
                        "INSERT INTO jobs VALUES (?,?,?,?)",
                        (
                            job_id,
                            state,
                            json.dumps(
                                {
                                    "repo": repo,
                                    "research": {
                                        "stage": stage,
                                        "parent_job_id": parent,
                                    },
                                }
                            ),
                            json.dumps({"usage": {"total_tokens": tokens}})
                            if tokens is not None
                            else None,
                        ),
                    )
                connection.commit()
            (root / "delivery").mkdir()
            with closing(
                sqlite3.connect(root / "delivery" / "delivery.sqlite")
            ) as connection:
                connection.execute(
                    "CREATE TABLE delivery (repo TEXT,state TEXT,reason TEXT)"
                )
                connection.executemany(
                    "INSERT INTO delivery VALUES (?,?,?)",
                    [
                        (
                            "repo/one",
                            "ENVIRONMENT_BLOCKED",
                            "no immutable same-repository Python source URL in packet",
                        ),
                        ("repo/two", "ENVIRONMENT_BLOCKED", "other missing tool"),
                        ("repo/one", "OWNER_REVIEW_REQUIRED", "test passed"),
                    ],
                )
                connection.commit()
            before = sorted(p.relative_to(root) for p in root.rglob("*"))
            report = inspect(root)
            self.assertEqual(report["research"]["jobs"], 4)
            self.assertEqual(report["research"]["review_leaves"], 1)
            self.assertEqual(report["research"]["reported_tokens"], 31)
            self.assertEqual(
                report["delivery"]["environment_blockers"],
                {
                    "no_python_source": 1,
                    "other": 1,
                },
            )
            self.assertEqual(report["repositories"][0]["review_leaves"], 1)
            self.assertEqual(report["repositories"][0]["reported_tokens"], 18)
            self.assertIsNone(report["linked_pr_count"])
            self.assertEqual(
                before, sorted(p.relative_to(root) for p in root.rglob("*"))
            )

    def test_missing_delivery_is_an_empty_funnel(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with closing(sqlite3.connect(root / "scout.sqlite")) as connection:
                connection.execute(
                    "CREATE TABLE jobs (id TEXT,state TEXT,packet TEXT,result TEXT)"
                )
            self.assertEqual(inspect(root)["delivery"]["jobs"], 0)


if __name__ == "__main__":
    unittest.main()
