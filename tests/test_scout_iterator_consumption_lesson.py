"""One-shot input advice remains complete, scoped and available to Scout."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import knowledge_notes
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions


class IteratorConsumptionLessonTests(unittest.TestCase):
    def test_one_shot_public_adapter_is_retrievable(self):
        result = lesson_suggestions("FindUniquesBy ChannelToSeq one-shot iterator restartability")
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        card = result["matches"][0]
        self.assertEqual(card["id"], "one-shot-iterator-consumption")
        knowledge_notes.validate(card)
        self.assertLessEqual(len(json.dumps(card, ensure_ascii=False).encode()), MAX_CARD_BYTES)
        self.assertIn("memory", card["avoid_when"])
        self.assertIn("explicit API", card["avoid_when"])
        self.assertNotIn("qualified", result)

    def test_source_path_advice_is_not_a_blanket_duplicate_advance_rule(self):
        result = lesson_suggestions("Inspect collection", source_urls=[
            "https://raw.githubusercontent.com/samber/lo/5c6ddcb7063c9908031340db03f27ba7483d1ece/it/find.go"
        ])
        card = result["matches"][0]
        self.assertEqual(card["id"], "one-shot-iterator-consumption")
        self.assertIn("GPU producer/consumer", card["avoid_when"])
        self.assertIn("prospective routing benefit", card["avoid_when"])

    def test_unary_variadic_alias_reuses_the_same_scoped_lesson(self):
        result = lesson_suggestions("Inspect unary intersection", source_urls=[
            "https://raw.githubusercontent.com/samber/lo/5c6ddcb7063c9908031340db03f27ba7483d1ece/it/intersect.go"
        ])
        card = result["matches"][0]
        self.assertEqual(card["id"], "one-shot-iterator-consumption")
        self.assertIn("lists[len(lists)-1]", card["lesson"])
        self.assertIn("streaming Uniq/UniqBy", card["lesson"])
        self.assertLessEqual(len(json.dumps(card, ensure_ascii=False).encode()), MAX_CARD_BYTES)


if __name__ == "__main__":
    unittest.main()
