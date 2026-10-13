"""Advice availability and scope only, not a discovery-yield experiment."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions


class VirtualPathLessonTests(unittest.TestCase):
    def test_current_and_future_source_path_retrieve_whole_card(self):
        for revision in ("eb6a92826ea568e3f40ab91fcbda8d2b38b61d3e", "a" * 40):
            with self.subTest(revision=revision):
                result = lesson_suggestions("directory adapter",
                    source_urls=[f"https://raw.githubusercontent.com/spf13/afero/{revision}/iofs.go"])
                self.assertEqual(result["status"], "ADVISORY_MATCH")
                self.assertTrue(result["source_path_match"])
                card = result["matches"][0]
                self.assertEqual(card["id"], "virtual-path-contract-before-host-path-rules")
                self.assertLessEqual(len(json.dumps(card, ensure_ascii=False).encode()), MAX_CARD_BYTES)
                self.assertIn("Backslash and colon can be valid literal", card["lesson"])
                self.assertIn("not proof of security", card["avoid_when"])

    def test_lexical_retrieval_without_source(self):
        result = lesson_suggestions("virtual-path-contract-before-host-path-rules")
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        self.assertEqual(result["matches"][0]["id"], "virtual-path-contract-before-host-path-rules")


if __name__ == "__main__":
    unittest.main()
