"""A completed sweep must not suppress its already-budgeted revision checks."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_kimi_scout_research import Context, research, scout


class SleepingSourceRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.spec = {"repo": "a/b", "ref": "main", "source_prefixes": ["src/"],
                     "question": "Check supported callers before proposing a bug."}
        config = self.root / "config.json"
        config.write_text(json.dumps({"objective": "test", "queue_target": 4,
                                      "source_windows": 1, "repos": [self.spec]}))
        scout.initialize(self.root)
        self.context = Context()
        self.producer = research.ResearchProducer(self.root, config, context=self.context)
        self.progress = {}
        self.assertTrue(self.producer.source_audit(self.spec, self.progress))
        self.assertFalse(self.producer.source_audit(self.spec, self.progress))
        with scout.connect(self.root) as db:
            db.execute("UPDATE jobs SET state='NO_LEAD'")
        self.progress.update(sources_after=2800, revision_check_after=999)

    def test_changed_revision_is_admitted_before_old_sweep_sleep_ends(self):
        self.context.revision = "d" * 40
        self.context.blob = "e" * 40
        with patch.object(research.time, "time", return_value=1000):
            self.assertTrue(self.producer.source_audit(self.spec, self.progress))
        with scout.connect(self.root) as db:
            packet = json.loads(db.execute("SELECT packet FROM jobs WHERE state='PENDING'").fetchone()[0])
        self.assertIn("/" + "d" * 40 + "/src/kernel.py", packet["sources"][0]["url"])
        self.assertEqual(self.progress["revision_check_after"], 1900)

    def test_unchanged_revision_preserves_sleep_and_bounded_check_interval(self):
        with patch.object(self.context, "snapshot", wraps=self.context.snapshot) as lookup:
            for now in (1000, 1001):
                with patch.object(research.time, "time", return_value=now):
                    self.assertFalse(self.producer.source_audit(self.spec, self.progress))
        self.assertEqual(lookup.call_count, 1)
        self.assertEqual(self.progress["sources_after"], 2800)
        self.assertEqual(self.progress["revision_check_after"], 1900)

    def test_sleep_before_revision_deadline_performs_no_lookup(self):
        self.progress["revision_check_after"] = 1500
        with patch.object(self.context, "snapshot") as lookup:
            with patch.object(research.time, "time", return_value=1000):
                self.assertFalse(self.producer.source_audit(self.spec, self.progress))
        lookup.assert_not_called()

    def test_new_commit_with_unchanged_blob_does_not_repeat_a_model_packet(self):
        self.context.revision = "d" * 40
        with patch.object(research.time, "time", return_value=1000):
            self.assertFalse(self.producer.source_audit(self.spec, self.progress))
        with scout.connect(self.root) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM jobs").fetchone()[0], 1)
        self.assertEqual(self.progress["last_sweep_commit"], "d" * 40)

    def test_failed_lookup_does_not_mutate_frontier_or_advance_check(self):
        previous = dict(self.progress)
        with patch.object(self.context, "snapshot", side_effect=OSError("offline")):
            with patch.object(research.time, "time", return_value=1000):
                with self.assertRaises(OSError):
                    self.producer.source_audit(self.spec, self.progress)
        self.assertEqual(self.progress, previous)


if __name__ == "__main__":
    unittest.main()
