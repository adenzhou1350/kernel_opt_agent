"""Native decoder counterexample remains retrievable without a repair claim."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import knowledge_notes
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions


class DecoderEofLessonTests(unittest.TestCase):
    def test_no_output_empty_input_distinction_is_retrievable(self):
        result = lesson_suggestions(
            "decoder compressed EOF first_try no output empty input"
        )
        card = next(
            m
            for m in result["matches"]
            if m["id"] == "decoder-no-output-is-not-empty-input"
        )
        knowledge_notes.validate(card)
        self.assertLessEqual(len(json.dumps(card).encode()), MAX_CARD_BYTES)
        self.assertEqual(card["status"], "counterexample")
        self.assertIn("before the first output", card["lesson"])
        self.assertIn("complete compressed empty streams", card["lesson"])
        self.assertNotIn("qualified", result)

    def test_component_scope_does_not_become_accepted_repair(self):
        result = lesson_suggestions(
            "decoder compressed EOF first_try no output empty input"
        )
        card = next(
            m
            for m in result["matches"]
            if m["id"] == "decoder-no-output-is-not-empty-input"
        )
        self.assertIn("not a verified repair", card["avoid_when"])
        self.assertIn("not establish a full installed-PR", card["avoid_when"])
        self.assertIn("prospective Scout cost advantage", card["avoid_when"])
        self.assertTrue(
            any("#issuecomment-6106161198" in e["url"] for e in card["evidence"])
        )


if __name__ == "__main__":
    unittest.main()
