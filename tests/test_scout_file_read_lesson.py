"""Real-file boundary advice stays scoped and does not displace DSL advice."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions  # noqa: E402


class FileReadLessonTests(unittest.TestCase):
    def test_real_file_controls_are_available_to_scout(self):
        for query in (
            "BytesIO negative read EOF",
            "fsspec read_block size-offset",
            "buffered file read(-2) memory backend",
        ):
            with self.subTest(query=query):
                result = lesson_suggestions(query)
                card = result["matches"][0]
                self.assertEqual(card["id"], "file-like-negative-read-contract")
                self.assertIn("one-byte-past and farther-past", card["lesson"])
                self.assertIn("wrapper converts None", card["lesson"])
                self.assertIn(
                    "not a claim that every negative size is invalid",
                    card["avoid_when"],
                )
                self.assertLessEqual(len(json.dumps(card).encode()), MAX_CARD_BYTES)
                self.assertEqual(result["oversized_matches_omitted"], 0)
                self.assertNotIn("qualified", result)

    def test_distinct_receiver_advice_remains_available(self):
        self.assertEqual(
            lesson_suggestions("CUTLASS Array slice vector start count")["matches"][0][
                "id"
            ],
            "cutlass-array-vector-slice-count",
        )

    def test_forward_only_delimiter_advice_is_distinct_and_complete(self):
        result = lesson_suggestions("HTTP streaming readline seek delimiter lookahead")
        card = result["matches"][0]
        self.assertEqual(card["id"], "forward-stream-delimiter-lookahead")
        self.assertIn("real transport", card["lesson"])
        self.assertIn("submitted PR", card["avoid_when"])
        self.assertLessEqual(len(json.dumps(card).encode()), MAX_CARD_BYTES)
        self.assertEqual(result["oversized_matches_omitted"], 0)


if __name__ == "__main__":
    unittest.main()
