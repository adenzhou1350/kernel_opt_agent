"""Name-identity evidence is optional, scoped and intact in Scout retrieval."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions  # noqa: E402


class IRParameterNameLessonTests(unittest.TestCase):
    def test_identity_and_reserved_name_counterexample_remains_scoped(self):
        result = lesson_suggestions(
            "scalar Var name_hint duplicate generated signatures kernels device_id"
        )
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        self.assertEqual(result["oversized_matches_omitted"], 0)
        card = result["matches"][0]
        self.assertEqual(card["id"], "ir-identity-before-generated-parameter-names")
        self.assertLessEqual(
            len(json.dumps(card, ensure_ascii=False).encode()), MAX_CARD_BYTES
        )
        self.assertIn("Removing a repeated entry loses a positional input", card["lesson"])
        self.assertIn("not a GPU numerical or launch qualification", card["avoid_when"])
        self.assertTrue(
            any("issuecomment-5957506375" in e["url"] for e in card["evidence"])
        )
        self.assertIn("each lowered host call site", card["lesson"])
        self.assertIn("not TMA GPU launch", card["avoid_when"])
        self.assertTrue(any("/pull/3414" in e["url"] for e in card["evidence"]))
        self.assertIn("NVRTC retains one call per kernel name", card["avoid_when"])
        self.assertIn("historical", card["avoid_when"])
        review = next(e for e in card["evidence"] if "5477573199" in e["url"])
        self.assertIn("not measured", review["note"])
        self.assertIn("separate", review["note"])
        self.assertNotIn("qualified", result)


if __name__ == "__main__":
    unittest.main()
