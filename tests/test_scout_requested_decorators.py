"""Requested Python declarations include their syntax, not only the def body."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_requested_definition import requested_function_window


class RequestedDecoratorTests(unittest.TestCase):
    def test_decorated_functions_keep_first_decorator(self):
        for declaration in (
            "@cute.jit\ndef target():\n    pass",
            "@first\n@second(option=True)\ndef target():\n    pass",
            "@configure(\n    option=True,\n)\ndef target():\n    pass",
            "@first\nasync def target():\n    pass",
            "@(\n    configure\n)\ndef target():\n    pass",
            "@(\n    # A comment before the expression is still decorator syntax.\n    configure\n)\ndef target():\n    pass",
        ):
            with self.subTest(declaration=declaration):
                lines = ["# header", ""] + declaration.splitlines()
                result = requested_function_window(lines, "Inspect target")
                self.assertEqual(result["start_line"], 3)
                self.assertEqual(result["end_line"], len(lines))

    def test_method_starts_at_its_decorator_not_the_class_decorator(self):
        lines = ["@owner", "class Executor:", "    @first", "    @second",
                 "    def target(self):", "        return True"]
        result = requested_function_window(lines, "Inspect Executor.target")
        self.assertEqual(result["start_line"], 3)
        self.assertEqual(result["end_line"], 6)

    def test_strings_comments_and_previous_decorators_do_not_shift_plain_function(self):
        lines = ["@previous", "def other():", "    pass", "# @comment",
                 "text = '@not_a_decorator'", "def target():", "    return text"]
        self.assertEqual(requested_function_window(lines, "Inspect target")["start_line"], 6)

    def test_matrix_operator_inside_parenthesized_decorator_is_not_a_new_start(self):
        lines = ["@(\n    left\n    @ right\n)\ndef target():\n    pass"]
        result = requested_function_window(lines[0].splitlines(), "Inspect target")
        self.assertEqual(result["start_line"], 1)

    def test_ambiguous_and_invalid_source_still_have_no_definition_claim(self):
        for text in ("@first\ndef target(): pass\ndef target(): pass", "@broken(\ndef target():"):
            self.assertIsNone(requested_function_window(text.splitlines(), "Inspect target"))

    def test_actual_public_context_preserves_decorator_and_completeness_budget(self):
        from kimi_scout_context import PublicContext

        raw = "# preceding context\n" * 120 + "@cute.jit\ndef target():\n    return True\n"
        with tempfile.TemporaryDirectory() as directory:
            context = PublicContext(directory)
            with patch.object(context, "snapshot", return_value={"files": ["kernel.py"]}), \
                    patch.object(context, "_read", return_value=raw) as read:
                for max_lines, complete in ((4, True), (1, False)):
                    evidence = context.source(
                        "owner/project", "a" * 40, "kernel.py",
                        request_hints="Inspect target", max_lines=max_lines,
                    )
                    self.assertEqual(evidence["start_line"], 121)
                    self.assertTrue(evidence["text"].startswith("121: @cute.jit"))
                    self.assertEqual(evidence["requested_definition_complete"], complete)
                    self.assertLessEqual(len(evidence["text"].splitlines()), max_lines)
                explicit = context.source(
                    "owner/project", "a" * 40, "kernel.py",
                    request_hints="Inspect target", start=122, max_lines=2,
                )
                self.assertEqual(explicit["start_line"], 122)
                self.assertNotIn("requested_definition", explicit)
                self.assertEqual(read.call_count, 1)


if __name__ == "__main__":
    unittest.main()
