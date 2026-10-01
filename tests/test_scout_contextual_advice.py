"""Contextual advice must not become a domain gate or consume source budget."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout as scout
import kimi_scout_research as research
from scout_lesson_context import lesson_suggestions


class ContextualAdviceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        scout.initialize(self.root)

    def test_no_unconditional_gpu_cards_or_library_io(self):
        with patch.object(scout, "ROOT", self.root / "absent"):
            self.assertEqual(scout.reviewed_lessons(), [])

    def test_former_baseline_card_is_still_available_when_relevant(self):
        result = lesson_suggestions("CUDA graph replay production execution mode")
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        self.assertEqual(
            result["matches"][0]["id"], "measure-production-execution-mode"
        )
        self.assertIn("avoid_when", result["matches"][0])

    def test_research_drops_advice_before_primary_source(self):
        config = self.root / "config.json"
        spec = {
            "repo": "a/b",
            "question": "Inspect TypeScript cleanup",
            "source_prefixes": ["src/"],
        }
        config.write_text(
            json.dumps(
                {"objective": "Public source", "queue_target": 4, "repos": [spec]}
            ),
            encoding="utf-8",
        )
        producer = research.ResearchProducer(self.root, config, context=object())
        source = {
            "url": "https://raw.githubusercontent.com/a/b/"
            + "a" * 40
            + "/src/cleanup.ts",
            "text": "x" * 18000,
        }
        advice = {"matches": [{"id": "large", "lesson": "y" * 7000}]}
        with patch.object(research, "lesson_suggestions", return_value=advice):
            self.assertTrue(producer.emit("first", spec, [source], "source_audit"))
        with scout.connect(self.root) as db:
            packet = json.loads(db.execute("SELECT packet FROM jobs").fetchone()[0])
        self.assertEqual(packet["reviewed_lessons"], [])
        self.assertNotIn("lesson_suggestions", packet)
        self.assertEqual(packet["sources"][0]["text"], source["text"])
        self.assertNotIn("truncated", packet["sources"][0])

    def test_changed_advice_does_not_trigger_a_paid_duplicate(self):
        packet = {
            "name": "fixed",
            "repo": "a/b",
            "question": "same input",
            "reviewed_lessons": [],
            "sources": [
                {"url": "https://github.com/a/b/issues/1", "text": "same report"}
            ],
            "lesson_suggestions": {"matches": [{"id": "one"}]},
        }
        first = scout.enqueue(self.root, packet)
        packet["lesson_suggestions"] = {"matches": [{"id": "two"}]}
        self.assertEqual(scout.enqueue(self.root, packet), first)
        with scout.connect(self.root) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM jobs").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
