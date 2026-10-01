"""Numerical boundary advice is retrievable without declaring an API defect."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions


class NumericalContractLessonTests(unittest.TestCase):
    def test_optional_scale_counterexample_retains_contract_and_scope(self):
        result = lesson_suggestions("score_scale zero divisor numerical semantics")
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        lesson = next(
            card
            for card in result["matches"]
            if card["id"] == "precision-reference-contract"
        )
        self.assertLessEqual(
            len(json.dumps(lesson, ensure_ascii=False).encode()), MAX_CARD_BYTES
        )
        self.assertEqual(lesson["status"], "hypothesis")
        self.assertIn("multiplier or divisor", lesson["avoid_when"])
        self.assertIn("NaN/Inf", lesson["avoid_when"])
        self.assertIn("documented zero-input contract", lesson["avoid_when"])
        self.assertIn("default-only callers do not prove", lesson["avoid_when"])
        self.assertTrue(any("/qsa/mqa.py" in e["url"] for e in lesson["evidence"]))
        self.assertTrue(
            any("/qsa/qsa_indexer.py" in e["url"] for e in lesson["evidence"])
        )
        self.assertTrue(
            any("not native/GPU validation" in e["note"] for e in lesson["evidence"])
        )


if __name__ == "__main__":
    unittest.main()
