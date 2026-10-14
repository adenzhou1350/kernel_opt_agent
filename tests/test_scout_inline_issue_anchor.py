"""An observed inline Python name can survive a long issue template."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from kimi_scout_context import PublicContext, _definition_line


HEADER = "Checklist " + " ".join("templateword" + str(i) for i in range(45))


class InlineIssueAnchorTests(unittest.TestCase):
    def test_inline_name_after_generic_word_budget_locates_real_function(self):
        hints = HEADER + "\n`load_audio` decodes the supplied bytes."
        raw = "# unrelated\n" * 180 + "def load_audio(source):\n    return source\n" + "# templateword0\n" * 150
        self.assertEqual(_definition_line(raw.splitlines(), hints), 180)

    def test_actual_source_reader_keeps_one_fetch_and_line_budget(self):
        raw = "# context\n" * 180 + "async def load_audio(source):\n    return source\n" + "# tail\n" * 150
        with tempfile.TemporaryDirectory() as root:
            context = PublicContext(root)
            with patch.object(context, "snapshot", return_value={"files": ["src/audio.py"], "blobs": {"src/audio.py": "b" * 40}}), patch.object(context, "_source_text", return_value=(raw, "test")) as fetch:
                result = context.source("a/b", "a" * 40, "src/audio.py", hints=HEADER + "\n`load_audio` needs review.", max_lines=80)
            self.assertEqual(fetch.call_count, 1)
            self.assertIn("async def load_audio", result["text"])
            self.assertLessEqual(result["end_line"] - result["start_line"] + 1, 80)
            self.assertNotIn("requested_definition_complete", result)

    def test_duplicate_or_multiple_inline_function_matches_do_not_guess(self):
        for raw, hint in (
            ("class A:\n    def load_audio(self): pass\nclass B:\n    def load_audio(self): pass", "`load_audio`"),
            ("def first_audio(): pass\ndef second_audio(): pass", "`first_audio` and `second_audio`"),
        ):
            with self.subTest(hint=hint):
                self.assertIsNone(_definition_line(raw.splitlines(), HEADER + "\n" + hint))

    def test_missing_literal_comment_and_string_are_not_definitions(self):
        raw = '# def load_audio(source):\ntext = """\ndef load_audio(source):\n    pass\n"""\ndef other(): pass'
        self.assertIsNone(_definition_line(raw.splitlines(), HEADER + "\n`load_audio`"))

    def test_qualified_existing_target_keeps_precedence(self):
        raw = "class Executor:\n    def dispatch(self): pass\ndef load_audio(source): pass"
        self.assertEqual(_definition_line(raw.splitlines(), "Executor.dispatch compared with `load_audio`"), 1)

    def test_inline_python_target_is_not_a_general_js_or_class_resolver(self):
        for raw in ("const load_audio = 1;", "class load_audio: pass", "function load_audio() {}"):
            with self.subTest(raw=raw):
                self.assertIsNone(_definition_line(raw.splitlines(), HEADER + "\n`load_audio`"))

    def test_fences_paths_and_out_of_budget_names_do_not_activate(self):
        raw = "def load_audio(source): pass"
        for hint in ("```load_audio```", "`src/load_audio.py`", "`https://private/load_audio`", "x " * 1001 + "`load_audio`"):
            with self.subTest(hint=hint[-60:]):
                self.assertIsNone(_definition_line(raw.splitlines(), HEADER + "\n" + hint))

    def test_many_inline_names_are_not_truncated_into_a_unique_target(self):
        hints = " ".join("`name_" + str(i) + "`" for i in range(9))
        self.assertIsNone(_definition_line(["def name_0(): pass"], HEADER + "\n" + hints))

    def test_syntax_selector_keeps_decorators_and_rejects_invalid_python(self):
        hints = HEADER + "\n`load_audio`"
        self.assertEqual(_definition_line(["@decorate", "def load_audio(): pass"], hints), 0)
        self.assertIsNone(_definition_line(["def load_audio(: pass"], hints))


if __name__ == "__main__":
    unittest.main()
