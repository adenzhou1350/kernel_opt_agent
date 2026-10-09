"""Persistence advice is scoped source evidence, not an automatic defect verdict."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from knowledge_notes import validate  # noqa: E402
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions  # noqa: E402


class PersistentPatchLessonTests(unittest.TestCase):
    def test_patch_lifetime_query_preserves_counterconditions(self):
        result = lesson_suggestions(
            "global functional patch unpatch persistence restoration lifetime"
        )
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        card = result["matches"][0]
        self.assertEqual(card["id"], "persistent-functional-patch-lifetime")
        validate(card)
        self.assertLessEqual(len(json.dumps(card).encode()), MAX_CARD_BYTES)
        self.assertEqual(card["status"], "counterexample")
        self.assertIn("manually reset", card["lesson"])
        self.assertIn("Comments can be stale", card["avoid_when"])
        self.assertIn("Do not automatically reject", card["avoid_when"])
        self.assertNotIn("qualified", result)


if __name__ == "__main__":
    unittest.main()
