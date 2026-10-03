"""The PTX counterexample stays advisory and does not waive memory ordering."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions


class Tcgen05DependencyLessonTests(unittest.TestCase):
    def test_precise_lookup_preserves_counterconditions(self):
        result = lesson_suggestions("tcgen05.ld register dependencies TMEM wait memory ordering")
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        card = result["matches"][0]
        self.assertEqual(card["id"], "tcgen05-register-dependency-versus-memory-ordering")
        self.assertEqual(card["status"], "counterexample")
        self.assertIn("anti-dependencies", card["lesson"])
        self.assertIn("cross-thread", card["avoid_when"])
        self.assertIn("SM100-only", card["avoid_when"])
        self.assertLessEqual(len(json.dumps(card).encode()), MAX_CARD_BYTES)
        self.assertNotIn("qualified", result)


if __name__ == "__main__":
    unittest.main()
