"""Retrieve the scoped parser lesson without promoting its PR to acceptance."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions


class GrammarContextLessonTests(unittest.TestCase):
    def test_parenthesized_values_query_preserves_context_and_claim_scope(self):
        result = lesson_suggestions(
            "parser grammar Parenthesis VALUES comma identifier grouping"
        )
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        card = result["matches"][0]
        self.assertEqual(card["id"], "grammar-context-before-generic-grouping")
        self.assertLessEqual(
            len(json.dumps(card, ensure_ascii=False).encode()), MAX_CARD_BYTES
        )
        self.assertIn("direct row parentheses", card["lesson"])
        self.assertIn("not upstream acceptance", card["avoid_when"])
        self.assertIn("prospective evidence-selection", card["avoid_when"])
        self.assertTrue(any("baseline 11 failed/1 passed" in entry["note"]
                            for entry in card["evidence"]))
        self.assertIn("does not establish", result["caution"])


if __name__ == "__main__":
    unittest.main()
