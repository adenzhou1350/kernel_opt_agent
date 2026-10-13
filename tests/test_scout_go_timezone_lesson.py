"""Keep runtime-data advice scoped and retrievable without execution claims."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import knowledge_notes
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions


class GoTimezoneLessonTests(unittest.TestCase):
    def test_cross_built_runtime_data_advice_is_complete(self):
        result = lesson_suggestions("cross-built Go Windows timezone ZONEINFO LoadLocation")
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        card = result["matches"][0]
        self.assertEqual(card["id"], "cross-built-go-timezone-data")
        knowledge_notes.validate(card)
        self.assertLessEqual(len(json.dumps(card, ensure_ascii=False).encode()), MAX_CARD_BYTES)
        self.assertIn("identical executable", card["lesson"])
        self.assertIn("UTC and Local", card["avoid_when"])
        self.assertNotIn("qualified", result)

    def test_hook_source_match_does_not_infer_a_decoder_defect(self):
        result = lesson_suggestions("Inspect hook", source_urls=[
            "https://raw.githubusercontent.com/go-viper/mapstructure/52aa5c6dc1d27226460807054ca2107b2d54fb2d/decode_hooks.go"
        ])
        card = result["matches"][0]
        self.assertEqual(card["id"], "cross-built-go-timezone-data")
        self.assertIn("weaken assertions", card["lesson"])
        self.assertIn("wrong location name", card["avoid_when"])


if __name__ == "__main__":
    unittest.main()
