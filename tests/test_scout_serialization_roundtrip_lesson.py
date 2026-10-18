"""A content-preservation counterexample remains scoped and retrievable."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions


class SerializationRoundtripLessonTests(unittest.TestCase):
    def test_query_source_reuses_the_same_roundtrip_lesson(self):
        result = lesson_suggestions(
            "URL query escaping round trip",
            source_urls=[
                "https://raw.githubusercontent.com/8treenet/goraven/"
                "b17666240a7a0cdfccf55f3fe21d2ca1dbd84ba5/util/url.go"
            ],
        )
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        self.assertTrue(result.get("source_path_match"))
        card = result["matches"][0]
        self.assertEqual(card["id"], "serialization-roundtrip-before-parse-success")
        self.assertIn("query value", card["lesson"])
        self.assertIn("adjacent parameters", card["lesson"])
        self.assertIn("whole backend", card["avoid_when"])
        self.assertIn("path segment", card["avoid_when"])
        witness = next(
            e for e in card["evidence"] if "/util/url_query_test.go" in e["url"]
        )
        self.assertIn("18 old-production failures", witness["note"])
        self.assertIn("21 passing controls", witness["note"])
        self.assertIn("include four parents", witness["note"])
        self.assertIn("not a new Scout discovery", witness["note"])
        self.assertIn("no performance, acceptance", witness["note"])
        self.assertLessEqual(
            len(json.dumps(card, ensure_ascii=False).encode()), MAX_CARD_BYTES
        )
        self.assertNotIn("qualified", result)

    def test_trace_text_query_reuses_scoped_native_evidence(self):
        result = lesson_suggestions(
            "RPD JSON trace marker backslash roundtrip serialization"
        )
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        card = result["matches"][0]
        self.assertEqual(card["id"], "serialization-roundtrip-before-parse-success")
        self.assertLessEqual(
            len(json.dumps(card, ensure_ascii=False).encode()), MAX_CARD_BYTES
        )
        self.assertIn("exact decoded content", card["lesson"])
        self.assertIn("not a prospective selector comparison", card["avoid_when"])
        self.assertIn("old wheel", card["avoid_when"])
        self.assertTrue(
            any("Source-only comparison" in entry["note"]
                and "backslashes with slashes" in entry["note"]
                for entry in card["evidence"])
        )
        self.assertTrue(
            any(
                "no AMD capture/performance/merge claim" in e["note"]
                for e in card["evidence"]
            )
        )
        self.assertIn("does not establish", result["caution"])


if __name__ == "__main__":
    unittest.main()
