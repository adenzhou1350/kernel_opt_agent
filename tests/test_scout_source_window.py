import hashlib
import unittest

from scripts.scout_source_window import source_window


class SourceWindowTests(unittest.TestCase):
    def test_ts_cpp_python_literals_are_not_definition_claims(self):
        for declaration in (
            "export function createNpmFailureFacts(",
            "void publish_address(const char* path) {",
            "async def publish_address(path):",
        ):
            text = "// context\n" + declaration + "\nbody\n"
            result = source_window(text, anchor=declaration)
            self.assertEqual(result["status"], "ACQUIRED")
            self.assertEqual(result["start_line"], 2)
            self.assertEqual(
                result["source_sha256"], hashlib.sha256(text.encode()).hexdigest()
            )
            self.assertEqual(result["text"], declaration + "\nbody")

    def test_missing_ambiguous_and_overlapping_literals_fail_without_fallback(self):
        for text, anchor, error in (
            ("hello", "world", "ANCHOR_NOT_FOUND"),
            ("foo foo", "foo", "AMBIGUOUS_ANCHOR"),
            ("foo\nfoo", "foo", "AMBIGUOUS_ANCHOR"),
            ("aaa", "aa", "AMBIGUOUS_ANCHOR"),
        ):
            self.assertEqual(source_window(text, anchor=anchor)["error_kind"], error)

    def test_literal_not_regex_and_comment_match_is_only_text(self):
        result = source_window("// a.*[x]\nrun();", anchor="a.*[x]")
        self.assertEqual(result["start_line"], 1)
        self.assertEqual(result["selector"], "literal")

    def test_crlf_cr_unicode_and_sha_preserve_original_bytes(self):
        text = "one\r\ntwo\r判断 = '\u2028';\r\nlast\n"
        result = source_window(text, anchor="判断")
        self.assertEqual(result["start_line"], 3)
        self.assertEqual(result["end_line"], 4)
        self.assertEqual(
            result["source_sha256"], hashlib.sha256(text.encode()).hexdigest()
        )
        self.assertIn("\u2028", result["text"])

    def test_exact_line_limits_and_end_of_source(self):
        text = "a\nbb\nccc\ndddd\n"
        result = source_window(text, start_line=2, max_chars=6)
        self.assertEqual(result["text"], "bb\nccc")
        self.assertTrue(result["truncated"])
        result = source_window(text, start_line=4, max_lines=1)
        self.assertFalse(result["truncated"])
        self.assertEqual(
            source_window(text, start_line=5)["error_kind"], "WINDOW_BEYOND_SOURCE"
        )
        self.assertEqual(
            source_window("", start_line=1)["error_kind"], "WINDOW_BEYOND_SOURCE"
        )

    def test_first_line_cannot_hide_anchor_by_clipping(self):
        result = source_window("long declaration", anchor="declaration", max_chars=5)
        self.assertEqual(result["error_kind"], "FIRST_LINE_EXCEEDS_CHAR_BUDGET")
        self.assertNotIn("text", result)

    def test_invalid_selectors_and_sources(self):
        for kwargs in (
            {},
            {"start_line": 1, "anchor": "a"},
            {"start_line": True},
            {"start_line": 0},
            {"anchor": " "},
            {"anchor": "a\nb"},
            {"anchor": "a" * 513},
        ):
            self.assertEqual(source_window("a", **kwargs)["status"], "FAILED")
        for text in (None, "\ud800", "x" * 1_000_001, "判断" * 200000):
            self.assertEqual(source_window(text, start_line=1)["status"], "FAILED")
        for kwargs in ({"max_lines": True}, {"max_lines": 81}, {"max_chars": 10001}):
            with self.assertRaises(ValueError):
                source_window("a", start_line=1, **kwargs)


if __name__ == "__main__":
    unittest.main()
