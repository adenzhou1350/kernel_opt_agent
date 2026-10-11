"""A proven queue reentrancy case supplies bounded advice, not qualification."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import knowledge_notes
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions


class ReentrantCapacityLessonTests(unittest.TestCase):
    def test_synchronous_event_capacity_advice_is_complete_and_retrievable(self):
        result = lesson_suggestions(
            "queue reentrant active listeners pending capacity concurrency"
        )
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        card = result["matches"][0]
        self.assertEqual(card["id"], "reserve-capacity-before-reentrant-events")
        knowledge_notes.validate(card)
        self.assertLessEqual(len(json.dumps(card).encode()), MAX_CARD_BYTES)
        self.assertIn("shared release gate", card["lesson"])
        self.assertIn("exception", card["lesson"])
        self.assertEqual(result["oversized_matches_omitted"], 0)
        self.assertNotIn("qualified", result)

    def test_callback_cleanup_and_publication_limits_are_not_generalized(self):
        card = lesson_suggestions(
            "synchronous reentrant scheduler emits pending task active"
        )["matches"][0]
        self.assertEqual(card["id"], "reserve-capacity-before-reentrant-events")
        self.assertIn("not arbitrary multi-thread safety", card["avoid_when"])
        self.assertIn("not the full Linux", card["avoid_when"])
        self.assertIn("issue contribution, not an upstream PR", card["avoid_when"])
        self.assertIn("different fork patch as merged", card["avoid_when"])
        self.assertTrue(
            any(entry["url"].endswith("/issues/255") for entry in card["evidence"])
        )
        self.assertTrue(
            any(entry["url"].endswith("/commit/22edad49b42214b9b5add8312391401c063d8b27")
                and "Maintainer's own fix" in entry["note"]
                for entry in card["evidence"])
        )


if __name__ == "__main__":
    unittest.main()
