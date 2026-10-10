"""Explicit class requests use observed syntax and the existing source budget."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from kimi_scout_context import PublicContext
from scout_requested_definition import requested_function_window


class RequestedClassTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ctx = PublicContext(Path(self.temp.name))
        self.raw = ("def unrelated():\n    pass\n" + "\n" * 150
                    + "class _FfnUpdate:\n"
                    + "    def update(self, hidden_states, residual):\n"
                    + "        hidden_states = self.state.apply_ffn_combine(hidden_states, residual)\n"
                    + "        self.state.clear_coefficients()\n"
                    + "        return hidden_states\n")
        self.snapshot = patch.object(self.ctx, "snapshot", return_value={"files": ["src/gated.py"]})
        self.snapshot.start()
        self.addCleanup(self.snapshot.stop)
        self.reader = patch.object(self.ctx, "_read", side_effect=lambda *a, **kw: self.raw)
        self.read_mock = self.reader.start()
        self.addCleanup(self.reader.stop)

    def source(self, **kwargs):
        return self.ctx.source("a/b", "a" * 40, "src/gated.py",
                               hints="Inspect unrelated clearing logic",
                               request_hints="definition(_FfnUpdate); compare unrelated", **kwargs)

    def test_private_class_request_reads_cleanup_outside_first_window(self):
        result = self.source()
        self.assertEqual(result["requested_definition"]["name"], "_FfnUpdate")
        self.assertEqual(result["start_line"], 153)
        self.assertEqual(result["end_line"], 157)
        self.assertTrue(result["requested_definition_complete"])
        self.assertIn("self.state.clear_coefficients()", result["text"])
        self.assertNotIn("def unrelated", result["text"])
        self.assertEqual(self.read_mock.call_count, 1)

    def test_class_selection_is_explicit_only(self):
        self.assertIsNone(requested_function_window(self.raw.splitlines(), "Inspect _FfnUpdate"))

    def test_qualified_method_in_private_owner_still_selects_method(self):
        result = requested_function_window(self.raw.splitlines(), "definition(_FfnUpdate.update)")
        self.assertEqual(result["name"], "update")
        self.assertEqual(result["start_line"], 154)

    def test_ambiguous_missing_or_multiple_targets_do_not_select_a_class(self):
        for raw, request in (
            ("class Target: pass\nclass Target: pass", "definition(Target)"),
            ("def Target(): pass\nclass Target: pass", "definition(Target)"),
            (self.raw, "definition(Missing); inspect _FfnUpdate"),
            (self.raw, "definition(_FfnUpdate) definition(unrelated)"),
        ):
            with self.subTest(request=request, raw=raw):
                self.assertIsNone(requested_function_window(raw.splitlines(), request))

    def test_decorated_class_includes_actual_decorator(self):
        raw = "@(\n    decorate\n)\nclass Target:\n    pass\n"
        result = requested_function_window(raw.splitlines(), "definition(Target)")
        self.assertEqual(result["start_line"], 1)
        self.assertEqual(result["end_line"], 5)

    def test_class_line_and_character_caps_do_not_claim_completeness(self):
        result = self.source(max_lines=2)
        self.assertFalse(result["requested_definition_complete"])
        self.assertEqual(result["end_line"], 154)
        self.raw = "class _FfnUpdate:\n    # " + "x" * 10000 + "\n    pass\n"
        # The immutable cache belongs to the previous source, so use a fresh cache.
        self.ctx = PublicContext(Path(self.temp.name) / "long")
        with patch.object(self.ctx, "snapshot", return_value={"files": ["src/gated.py"]}), \
                patch.object(self.ctx, "_read", return_value=self.raw):
            result = self.source()
        self.assertFalse(result["requested_definition_complete"])
        self.assertLessEqual(len(result["text"]), 9000)

    def test_explicit_start_and_literal_keep_precedence(self):
        for kwargs in ({"start": 1, "max_lines": 2}, {"exact_hint": "def unrelated"}):
            result = self.source(**kwargs)
            self.assertNotIn("requested_definition", result)
            self.assertIn("def unrelated", result["text"])


if __name__ == "__main__":
    unittest.main()
