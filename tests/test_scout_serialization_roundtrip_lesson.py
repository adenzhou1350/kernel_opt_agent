"""A content-preservation counterexample remains scoped and retrievable."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions


class SerializationRoundtripLessonTests(unittest.TestCase):
    def test_trace_text_query_reuses_scoped_native_evidence(self):
        result = lesson_suggestions(
            "RPD JSON trace marker backslash roundtrip serialization"
        )
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        card = result["matches"][0]
        self.assertEqual(card["id"], "serialization-roundtrip-before-parse-success")
        self.assertLessEqual(
            len(json.dumps(card, ensure_ascii=False).encode()), MAX_CARD_BYTES
        )
        self.assertIn("exact decoded content", card["lesson"])
        self.assertIn("not a prospective selector comparison", card["avoid_when"])
        self.assertTrue(
            any(
                "no AMD capture/performance/merge claim" in e["note"]
                for e in card["evidence"]
            )
        )
        self.assertIn("does not establish", result["caution"])


if __name__ == "__main__":
    unittest.main()
