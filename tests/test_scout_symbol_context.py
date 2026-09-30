"""Source hints select real owners without executing public source."""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout_context as context


class SymbolContextTests(unittest.TestCase):
    def test_constructor_belongs_to_requested_class_not_first_match(self):
        source = """raise RuntimeError('never execute public source')
class Other:
    def __init__(self):
        self.lower_bound = 17
class Layer:
    def __init__(self, lower_bound=None):
        self.lower_bound = lower_bound
"""
        self.assertEqual(context._definition_line(source.splitlines(), "Layer.__init__"), 5)

    def test_duplicate_method_selects_later_unconditional_definition(self):
        source = """class Backend:
    def get_metadata(self):
        return None
    async def get_metadata(self):
        return self.full_backend.metadata
"""
        self.assertEqual(
            context._definition_line(source.splitlines(), "Backend.get_metadata"), 3
        )

    def test_missing_or_inherited_method_does_not_pick_another_class(self):
        source = """class Other:
    def get_metadata(self):
        return 1
class Backend(Other):
    pass
"""
        self.assertEqual(
            context._definition_line(source.splitlines(), "Backend.get_metadata"), 3
        )

    def test_ambiguous_class_names_are_not_proven_owners(self):
        source = """class Backend:
    pass
def factory():
    class Backend:
        def get_metadata(self):
            return 1
    return Backend
"""
        self.assertIsNone(
            context._definition_line(source.splitlines(), "Backend.get_metadata")
        )

    def test_typescript_and_unqualified_hints_keep_lexical_fallback(self):
        for source, hints, expected in (
            ("// Foo.run\nexport function run() {}", "Foo.run", 1),
            ("# target\ndef target():\n    pass", "target", 1),
        ):
            with self.subTest(hints=hints):
                self.assertEqual(context._definition_line(source.splitlines(), hints), expected)

    def test_native_retrieval_keeps_pin_bounds_cache_and_explicit_start(self):
        commit, repo, path = "a" * 40, "a/b", "src/module.py"
        lines = ["# unrelated"] * 350
        lines[10:13] = ["class Other:", "    def __init__(self):", "        pass"]
        lines[210:213] = ["class Layer:", "    def __init__(self):", "        self.lower_bound = None"]
        raw = "\n".join(lines)
        snapshot = {"files": [path]}
        with tempfile.TemporaryDirectory() as directory:
            reader = context.PublicContext(directory)
            with patch.object(reader, "snapshot", return_value=snapshot), patch.object(
                reader, "_read", return_value=raw
            ) as fetch:
                evidence = reader.source(repo, commit, path, hints="Layer.__init__")
                self.assertIn("212:     def __init__", evidence["text"])
                self.assertIn("213:         self.lower_bound = None", evidence["text"])
                self.assertNotIn("12:     def __init__(self):", evidence["text"].splitlines())
                self.assertLessEqual(len(evidence["text"].splitlines()), 120)
                self.assertLessEqual(len(evidence["text"]), 9000)
                explicit = reader.source(repo, commit, path, hints="Layer.__init__", start=1)
                self.assertEqual(explicit["start_line"], 1)
                self.assertEqual(fetch.call_count, 1)
                self.assertIn(commit, evidence["url"])


if __name__ == "__main__":
    unittest.main()
