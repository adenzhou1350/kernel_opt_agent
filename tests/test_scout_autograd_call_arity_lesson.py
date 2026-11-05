"""Advisory retrieval only; native engine controls live in examples/."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_lesson_context import lesson_suggestions  # noqa: E402


class AutogradCallArityLessonTests(unittest.TestCase):
    def test_arity_advice_keeps_explicit_argument_and_operator_boundaries(self):
        result = lesson_suggestions(
            "Float8Tensor SplitAlongDim backward forward optional squeeze default apply"
        )
        card = result["matches"][0]
        self.assertEqual(card["id"], "autograd-call-arity-before-gradient-count")
        self.assertEqual(card["status"], "counterexample")
        self.assertIn("omitted Python default", card["lesson"])
        self.assertIn("Explicitly passing False or True", card["avoid_when"])
        self.assertIn("does not execute TransformerEngine", card["avoid_when"])
        self.assertEqual(result["oversized_matches_omitted"], 0)


if __name__ == "__main__":
    unittest.main()
