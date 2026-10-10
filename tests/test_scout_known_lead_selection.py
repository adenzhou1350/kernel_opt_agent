"""Read-only known-lead lookup retains ordinary delivery admission semantics."""

import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from kimi_scout_delivery_source import select_leads


class KnownLeadSelectionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        with closing(sqlite3.connect(self.root / "scout.sqlite")) as db:
            db.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY,state TEXT,packet TEXT,result TEXT,finished REAL)")
            for job_id, state, parent, suffix, finished in (
                ("older", "REVIEW", None, ".py", 1),
                ("newer", "REVIEW", None, ".py", 2),
                ("pending", "PENDING", None, ".py", 3),
                ("parent", "REVIEW", None, ".py", 4),
                ("child", "REVIEW", "parent", ".py", 5),
                ("native", "REVIEW", None, ".cu", 6),
                ("branch", "REVIEW", None, ".py", 7),
            ):
                commit = "main" if job_id == "branch" else "a" * 40
                packet = {"repo": "owner/project", "research": {"parent_job_id": parent},
                          "sources": [{"url": f"https://raw.githubusercontent.com/owner/project/{commit}/src/check{suffix}"}]}
                result = {"analysis": {"title": job_id, "hypothesis": job_id}}
                db.execute("INSERT INTO jobs VALUES (?,?,?,?,?)",
                           (job_id, state, json.dumps(packet), json.dumps(result), finished))
            db.commit()

    def test_known_id_precedes_scan_limit_and_preserves_canonical_identity(self):
        before = (self.root / "scout.sqlite").read_bytes()
        ordinary = next(row for row in select_leads(self.root, 20) if row["id"] == "older")
        selected = select_leads(self.root, 1, scan_limit=1, source_ids=["older"])
        self.assertEqual(selected, [ordinary])
        self.assertEqual((self.root / "scout.sqlite").read_bytes(), before)
        self.assertEqual({p.name for p in self.root.iterdir()}, {"scout.sqlite"})

    def test_known_id_does_not_bypass_state_child_source_or_explicit_exclusions(self):
        for job_id in ("pending", "parent", "native", "branch", "absent"):
            with self.subTest(job_id=job_id):
                self.assertEqual(select_leads(self.root, source_ids=[job_id]), [])
        self.assertEqual(select_leads(self.root, source_ids=["older"], exclude_source_ids=["older"]), [])
        older = select_leads(self.root, source_ids=["older"])[0]
        self.assertEqual(select_leads(self.root, source_ids=["older"], exclude_keys=[older["canonical_key"]]), [])

    def test_staged_known_id_stays_excluded(self):
        queue = self.root / "delivery"
        queue.mkdir()
        with closing(sqlite3.connect(queue / "delivery.sqlite")) as db:
            db.execute("CREATE TABLE delivery (source_job_id TEXT)")
            db.execute("INSERT INTO delivery VALUES ('older')")
            db.commit()
        self.assertEqual(select_leads(self.root, source_ids=["older"]), [])

    def test_empty_selection_never_opens_or_creates_database(self):
        self.assertEqual(select_leads(self.root / "missing", source_ids=[]), [])
        self.assertFalse((self.root / "missing").exists())

    def test_parameterized_ids_and_input_bounds(self):
        self.assertEqual(select_leads(self.root, source_ids=["older", "older"])[0]["id"], "older")
        self.assertEqual(select_leads(self.root, source_ids=["' OR 1=1 --"]), [])
        for value in ("older", {"id": "older"}, [None], [""], ["a" * 129], [str(i) for i in range(101)]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                select_leads(self.root, source_ids=value)


if __name__ == "__main__":
    unittest.main()
