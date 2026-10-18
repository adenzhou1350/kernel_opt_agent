"""Version-scoped reference advice reaches Scout without a qualification claim."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions


class CompatibilityReferenceLessonTests(unittest.TestCase):
    def test_old_release_restoration_requires_current_api_intent(self):
        result = lesson_suggestions(
            "Pluggy class-valued hookspec compatibility restoration old-release acceptance"
        )
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        card = result["matches"][0]
        self.assertEqual(card["id"], "version-pinned-compatibility-contract")
        self.assertIn("directed the fix downstream", card["lesson"])
        self.assertIn("cannot decide API intent", card["lesson"])
        self.assertIn("shared upstream defect", card["avoid_when"])
        self.assertTrue(any("/issues/794#" in e["url"] for e in card["evidence"]))
        self.assertLessEqual(len(json.dumps(card, ensure_ascii=False).encode()), MAX_CARD_BYTES)
        self.assertNotIn("qualified", result)

    def test_shim_query_keeps_reference_and_counterconditions(self):
        result = lesson_suggestions(
            "hf_parameter_utils get_parameter_device get_parameter_dtype buffer fallback compatibility"
        )
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        card = result["matches"][0]
        self.assertEqual(card["id"], "version-pinned-compatibility-contract")
        self.assertEqual(card["status"], "counterexample")
        self.assertLessEqual(
            len(json.dumps(card, ensure_ascii=False).encode()), MAX_CARD_BYTES
        )
        self.assertIn("5.5.4", card["lesson"])
        self.assertIn("shared upstream defect", card["avoid_when"])
        self.assertIn("not whole-package qualification", card["lesson"])
        self.assertTrue(any("/requirements.txt" in e["url"] for e in card["evidence"]))
        self.assertTrue(
            any("/huggingface/transformers/" in e["url"] for e in card["evidence"])
        )

    def test_backport_path_uses_named_reference_without_universal_equivalence(self):
        result = lesson_suggestions(
            "Zipp Path.relative_to pathlib compatibility reference",
            source_urls=["https://github.com/jaraco/zipp/blob/"
                         "8f98e1b5a6203557bf70ed3e84969543d4360c76/zipp/__init__.py"],
        )
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        card = result["matches"][0]
        self.assertEqual(card["id"], "version-pinned-compatibility-contract")
        self.assertIn("zipfile.Path", card["lesson"])
        self.assertIn("not all possible defects", card["lesson"])
        self.assertIn("shared upstream defect", card["avoid_when"])
        self.assertLessEqual(len(json.dumps(card, ensure_ascii=False).encode()), MAX_CARD_BYTES)


if __name__ == "__main__":
    unittest.main()
