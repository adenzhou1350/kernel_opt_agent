"""Acquisition advice is retrievable, not a claim that a new bug is qualified."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import knowledge_notes  # noqa: E402
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions  # noqa: E402


class AcquisitionCancellationLessonTests(unittest.TestCase):
    def test_entry_boundary_advice_is_complete_and_retrievable(self):
        result = lesson_suggestions(
            "Test cancellation between resource creation and async context entry"
        )
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        card = result["matches"][0]
        self.assertEqual(card["id"], "async-acquisition-cancellation-gap")
        knowledge_notes.validate(card)
        self.assertLessEqual(
            len(json.dumps(card, ensure_ascii=False).encode()), MAX_CARD_BYTES
        )
        self.assertIn("real constructor", card["lesson"])
        self.assertIn("retain the manager", card["lesson"])
        self.assertNotIn("qualified", result)

    def test_return_shortcut_and_evidence_scope_are_not_generalized(self):
        card = lesson_suggestions(
            "acquisition cancellation gap __aenter__ __aexit__ retained finalization"
        )["matches"][0]
        self.assertEqual(card["id"], "async-acquisition-cancellation-gap")
        self.assertIn("side effects", card["avoid_when"])
        self.assertIn("not permanent leakage", card["avoid_when"])
        self.assertIn("not merged", card["avoid_when"])
        self.assertIn("Blockbuster", card["avoid_when"])


if __name__ == "__main__":
    unittest.main()
