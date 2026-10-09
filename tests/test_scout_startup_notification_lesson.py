"""Startup-failure advice is retrievable without promoting its verification scope."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from knowledge_notes import validate  # noqa: E402
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions  # noqa: E402


class StartupNotificationLessonTests(unittest.TestCase):
    def test_error_notification_query_preserves_lifetime_and_scope(self):
        result = lesson_suggestions(
            "worker startup readiness exception completion queue"
        )
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        card = result["matches"][0]
        self.assertEqual(card["id"], "worker-startup-failure-notification")
        validate(card)
        self.assertLessEqual(len(json.dumps(card).encode()), MAX_CARD_BYTES)
        self.assertIn("parent-death", card["lesson"])
        self.assertIn("never returns", card["avoid_when"])
        self.assertIn("not real scheduler crashes", card["avoid_when"])
        self.assertIn(
            "not the official dependency-complete", card["evidence"][1]["note"]
        )
        self.assertNotIn("qualified", result)


if __name__ == "__main__":
    unittest.main()
