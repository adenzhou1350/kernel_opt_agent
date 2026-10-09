"""Late descriptor ownership advice remains complete, bounded and advisory."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions  # noqa: E402


class FdOwnershipLessonTests(unittest.TestCase):
    def test_real_socket_race_guidance_is_retrievable_without_qualification(self):
        result = lesson_suggestions("fd receiver timeout SCM_RIGHTS ownership")
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        self.assertEqual(len(result["matches"]), 1)
        self.assertEqual(result["oversized_matches_omitted"], 0)
        card = result["matches"][0]
        self.assertEqual(card["id"], "timed-out-receivers-retain-fd-ownership")
        self.assertLessEqual(
            len(json.dumps(card, ensure_ascii=False).encode()), MAX_CARD_BYTES
        )
        self.assertIn("A join timeout is not worker cancellation", card["lesson"])
        self.assertIn("real UNIX sockets and SCM_RIGHTS", card["lesson"])
        self.assertIn("outgoing caller-owned descriptors remain valid", card["lesson"])
        self.assertIn(
            "does not prove that a daemon receiver has stopped", card["avoid_when"]
        )
        self.assertIn("not evidence of maintainer acceptance", card["avoid_when"])
        self.assertNotIn("qualified", result)
        self.assertTrue(
            all(
                "/blob/d6c3a6e08b7004812a44e36ec5445258cfe8aedf/" in e["url"]
                for e in card["evidence"]
            )
        )


if __name__ == "__main__":
    unittest.main()
