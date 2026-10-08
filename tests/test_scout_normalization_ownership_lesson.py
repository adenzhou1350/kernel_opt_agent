"""Available input-ownership advice is not candidate qualification."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import knowledge_notes  # noqa: E402
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions  # noqa: E402


class NormalizationOwnershipLessonTests(unittest.TestCase):
    def test_scoped_advice_is_retrievable_and_complete(self):
        result = lesson_suggestions(
            "Normalize caller-owned options without writing results back into them"
        )
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        self.assertNotIn("qualified", result)
        card = result["matches"][0]
        self.assertEqual(card["id"], "normalization-without-input-writeback")
        knowledge_notes.validate(card)
        self.assertLessEqual(
            len(json.dumps(card, ensure_ascii=False).encode()), MAX_CARD_BYTES
        )
        self.assertIn("passing control", card["lesson"])
        self.assertIn("native operation", card["lesson"])

    def test_copy_scope_and_native_evidence_limits_survive_retrieval(self):
        card = lesson_suggestions(
            "caller-owned options normalization frozen nested storage maps reused"
        )["matches"][0]
        self.assertEqual(card["id"], "normalization-without-input-writeback")
        self.assertIn("shallow object spread", card["avoid_when"])
        self.assertIn("in-place builder", card["avoid_when"])
        self.assertIn("current-head native-build", card["avoid_when"])
        self.assertTrue(
            all(
                item["url"].startswith("https://github.com/")
                for item in card["evidence"]
            )
        )
        self.assertIn(
            "no current-head Rust/native rebuild", card["evidence"][-1]["note"]
        )


if __name__ == "__main__":
    unittest.main()
