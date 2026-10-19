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

    def test_rank_local_mono_query_keeps_affinity_countercondition(self):
        result = lesson_suggestions(
            "mono runner torch.cuda.current_stream TP multi device"
        )
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        card = next(
            card
            for card in result["matches"]
            if card["id"] == "cache-effective-device-identity"
        )
        self.assertLessEqual(
            len(json.dumps(card, ensure_ascii=False).encode()), MAX_CARD_BYTES
        )
        self.assertIn("supported caller", card["lesson"])
        self.assertIn("TP across processes alone", card["avoid_when"])
        self.assertIn("native allocations", card["avoid_when"])
        evidence = {row["url"]: row["note"] for row in card["evidence"]}
        self.assertTrue(any("gpu_worker.py#L445-L501" in url for url in evidence))
        mono = next(
            note for url, note in evidence.items() if "mono_decode.py#L60-L103" in url
        )
        self.assertIn("no native AMD execution", mono)
        self.assertIn("no-bug verdict", mono)
        self.assertNotIn("qualified", result)


if __name__ == "__main__":
    unittest.main()
