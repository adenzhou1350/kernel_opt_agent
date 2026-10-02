"""Device-stream evidence remains advisory and separate from kernel qualification."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions  # noqa: E402


class DeviceStreamLessonTests(unittest.TestCase):
    def test_noncurrent_tensor_stream_query_reuses_existing_device_card(self):
        result = lesson_suggestions(
            "CUDA current_stream first_tensor noncurrent device stream"
        )
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        self.assertEqual(result["oversized_matches_omitted"], 0)
        card = result["matches"][0]
        self.assertEqual(card["id"], "cache-effective-device-identity")
        self.assertLessEqual(
            len(json.dumps(card, ensure_ascii=False).encode()), MAX_CARD_BYTES
        )
        self.assertIn("distinct nondefault streams", card["lesson"])
        self.assertIn("Preserve explicit caller streams", card["avoid_when"])
        self.assertIn("not TileLang kernel", card["avoid_when"])
        self.assertTrue(
            any("#issuecomment-5956886017" in e["url"] for e in card["evidence"])
        )
        self.assertNotIn("qualified", result)


if __name__ == "__main__":
    unittest.main()
