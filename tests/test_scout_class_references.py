"""Offline syntactic class context; never import or execute the cached source."""

from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_symbol_references import reference_requests


class ClassReferenceTests(unittest.TestCase):
    def setUp(self):
        self.repo = "example/library"
        self.commit = "a" * 40
        self.path = "types.py"
        self.url = f"https://raw.githubusercontent.com/{self.repo}/{self.commit}/{self.path}"
        self.packet = {
            "repo": self.repo,
            "sources": [{"url": self.url, "start_line": 201, "end_line": 260}],
        }
        self.snapshot = {"commit": self.commit, "files": [self.path]}
        self.raw = (
            'raise RuntimeError("cached source must not execute")\n'
            "from enum import Enum\n"
            + "\n" * 47
            + 'class Backend(Enum):\n    GPU = "gpu"\n    CPU = "cpu"\n'
            + "\n" * 250
            + "selected = Backend.GPU\n"
        )
        self.cache = Mock(side_effect=lambda *args: self.raw)

    def requests(self, name="Backend", **kwargs):
        return reference_requests(
            self.packet, self.snapshot, {"next_check": f"Inspect references({name})"},
            self.cache, **kwargs,
        )

    def excerpt(self, request):
        return "\n".join(self.raw.splitlines()[
            request["start"] - 1:request["start"] - 1 + request["max_lines"]
        ])

    def test_unseen_unique_class_exposes_base_and_members_before_later_load(self):
        result = self.requests()
        self.assertEqual(len(result), 2)
        self.assertIn("class Backend(Enum):", self.excerpt(result[0]))
        self.assertIn('GPU = "gpu"', self.excerpt(result[0]))
        self.assertIn("selected = Backend.GPU", self.excerpt(result[1]))
        self.assertTrue(all(r["max_lines"] == 80 for r in result))
        self.assertTrue(all(set(r) == {"path", "start", "max_lines"} for r in result))
        self.cache.assert_called_once_with(self.repo, self.commit, self.path)

    def test_unique_class_without_load_is_still_useful_context(self):
        self.raw = self.raw.rsplit("selected =", 1)[0]
        self.assertIn("class Backend(Enum):", self.excerpt(self.requests()[0]))

    def test_already_shown_class_only_adds_unseen_load(self):
        self.packet["sources"].append({"url": self.url, "start_line": 1, "end_line": 100})
        result = self.requests()
        self.assertEqual(len(result), 1)
        self.assertIn("selected = Backend.GPU", self.excerpt(result[0]))

    def test_ambiguous_class_names_do_not_introduce_declarations(self):
        self.raw = "class Backend:\n    pass\n" + "\n" * 100 + "class Backend:\n    pass\n"
        self.assertEqual(self.requests(), [])
        self.raw += "\n" * 200 + "selected = Backend()\n"
        result = self.requests()
        self.assertEqual(len(result), 1)
        self.assertNotIn("class Backend", self.excerpt(result[0]))

    def test_function_definitions_comments_and_strings_remain_excluded(self):
        self.raw = 'def Backend():\n    pass\n# Backend\ntext = "class Backend: pass"\n'
        self.assertEqual(self.requests(), [])

    def test_limit_one_retains_class_and_does_not_expand_read_budget(self):
        result = self.requests(limit=1)
        self.assertEqual(len(result), 1)
        self.assertIn("class Backend(Enum):", self.excerpt(result[0]))

    def test_drifted_pin_is_not_a_new_fetch_target(self):
        self.packet["sources"][0]["url"] = self.url.replace(self.commit, "b" * 40)
        self.assertEqual(self.requests(), [])
        self.cache.assert_not_called()

    def test_missing_cache_and_malformed_source_abstain(self):
        for raw in (None, "class Backend(:", "\x00class Backend: pass"):
            self.raw = raw
            with self.subTest(raw=raw):
                self.assertEqual(self.requests(), [])


if __name__ == "__main__":
    unittest.main()
