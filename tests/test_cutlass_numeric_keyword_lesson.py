"""Keep the constructor-specific counterexample small, scoped and retrievable."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import knowledge_notes  # noqa: E402


class CutlassNumericKeywordLessonTests(unittest.TestCase):
    def test_keyword_hypothesis_finds_the_api_specific_card(self):
        result = knowledge_notes.search(
            "CuTe CUTLASS Float32 loc ip constructor", limit=1
        )
        card = result["matches"][0]["card"]
        self.assertEqual(card["id"], "cutlass-float32-constructor-keywords")
        self.assertEqual(card["status"], "counterexample")
        self.assertLess(len(json.dumps(card).encode()), 2500)
        self.assertIn("keyword-only loc and ip", card["lesson"])
        self.assertIn("older installed DSL", card["avoid_when"])
        self.assertIn("not equivalence of metadata propagation", card["avoid_when"])
        self.assertTrue(
            any("/NVIDIA/cutlass/blob/" in e["url"] for e in card["evidence"])
        )


if __name__ == "__main__":
    unittest.main()
