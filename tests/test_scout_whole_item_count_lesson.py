"""Retrieval preserves a count/consumer counterexample, not a bug classifier."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import knowledge_notes
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions


class WholeItemCountLessonTests(unittest.TestCase):
    def test_full_item_cache_query_preserves_complete_advice(self):
        result = lesson_suggestions(
            "multimodal full item token count embedding cache chunk slicing overlap"
        )
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        card = result["matches"][0]
        self.assertEqual(card["id"], "whole-item-count-before-chunk-slicing")
        knowledge_notes.validate(card)
        self.assertLessEqual(
            len(json.dumps(card, ensure_ascii=False).encode()), MAX_CARD_BYTES
        )
        self.assertIn("split size of five, not one", card["lesson"])
        self.assertIn("actual encoder is incremental", card["lesson"])
        self.assertIn("true chunk-local encoder", card["avoid_when"])
        self.assertIn("server execution", card["avoid_when"])
        self.assertEqual(card["status"], "counterexample")
        self.assertNotIn("qualified", result)
        self.assertNotIn("verdict", result)
        self.assertEqual(len(card["evidence"]), 3)

    def test_explicit_exclusion_does_not_force_the_counterexample(self):
        result = lesson_suggestions(
            "multimodal full item token count embedding cache chunk slicing overlap",
            exclude=["whole-item-count-before-chunk-slicing"],
        )
        self.assertTrue(all(
            card["id"] != "whole-item-count-before-chunk-slicing"
            for card in result["matches"]
        ))


if __name__ == "__main__":
    unittest.main()
