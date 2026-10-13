import hashlib
import unittest

from scripts.scout_source_window import source_window, source_windows


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

    def test_split_ranges_reach_caller_and_callee_without_increasing_budget(self):
        lines = [f"line {i}" for i in range(1, 401)]
        lines[19] = "def callee():"
        lines[319] = "    return callee()"
        text = "\n".join(lines)
        result = source_windows(text, [
            {"start_line": 1, "line_count": 40},
            {"start_line": 301, "line_count": 40},
        ])
        self.assertEqual(result["status"], "ACQUIRED")
        self.assertEqual(result["selected_lines"], 80)
        self.assertLessEqual(result["selected_chars"], 4500)
        self.assertIn("def callee():", result["windows"][0]["text"])
        self.assertIn("return callee()", result["windows"][1]["text"])
        self.assertNotIn("return callee()", source_window(text, start_line=1)["text"])

    def test_set_preserves_order_exact_bounds_unicode_and_raw_digest(self):
        text = "a\r\n判断\r\n\r\nlast\n"
        result = source_windows(text, [
            {"start_line": 4, "line_count": 1},
            {"start_line": 2, "line_count": 2},
        ], max_chars=8)
        self.assertEqual(result["status"], "ACQUIRED")
        self.assertEqual(result["selected_chars"], 8)
        self.assertEqual(result["selected_lines"], 3)
        self.assertEqual([w["start_line"] for w in result["windows"]], [4, 2])
        self.assertEqual(result["source_sha256"], hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(result["windows"][1]["text"], "判断\n")

    def test_shared_character_budget_includes_between_range_separator(self):
        ranges = [{"start_line": 1, "line_count": 1},
                  {"start_line": 3, "line_count": 1}]
        result = source_windows("ab\nskip\ncd", ranges, max_chars=4)
        self.assertEqual(result, {"status": "FAILED",
                                 "error_kind": "SHARED_CHAR_BUDGET_EXCEEDED",
                                 "failed_range": 1})
        self.assertEqual(source_windows("ab\nskip\ncd", ranges, max_chars=5)["selected_chars"], 5)
        self.assertEqual(source_windows("a\nskip\n\n", ranges, max_chars=2)["selected_chars"], 2)

    def test_set_failure_never_exposes_an_earlier_successful_range(self):
        ranges = [{"start_line": 1, "line_count": 1},
                  {"start_line": 3, "line_count": 2}]
        for text, error in (("a\nb\nc", "INCOMPLETE_REQUESTED_RANGE"),
                            ("a\nb", "WINDOW_BEYOND_SOURCE"),
                            ("a\nb\nvery long", "FIRST_LINE_EXCEEDS_CHAR_BUDGET")):
            result = source_windows(text, ranges, max_chars=3)
            self.assertEqual(result["error_kind"], error)
            self.assertNotIn("windows", result)
            self.assertNotIn("text", result)
        self.assertEqual(source_windows(None, ranges)["error_kind"], "INVALID_SOURCE")
        clipped = source_windows("a\nbb\ncc", [
            {"start_line": 1, "line_count": 3},
        ], max_chars=4)
        self.assertEqual(clipped["error_kind"], "INCOMPLETE_REQUESTED_RANGE")
        self.assertNotIn("windows", clipped)

    def test_range_validation_rejects_overlap_and_per_range_budget_inflation(self):
        for ranges in ([], [None], [{"start_line": True, "line_count": 1}],
                       [{"start_line": 0, "line_count": 1}],
                       [{"start_line": 1, "line_count": False}],
                       [{"start_line": 1, "line_count": 1, "extra": 2}],
                       [{"start_line": 1, "line_count": 41},
                        {"start_line": 100, "line_count": 40}],
                       [{"start_line": 2, "line_count": 2},
                        {"start_line": 1, "line_count": 2}],
                       [{"start_line": 1, "line_count": 1}] * 9):
            with self.subTest(ranges=ranges), self.assertRaises(ValueError):
                source_windows("a", ranges)
        ranges = [{"start_line": 1, "line_count": 1}]
        for kwargs in ({"max_lines": True}, {"max_lines": 81},
                       {"max_chars": 0}, {"max_chars": 10001}):
            with self.assertRaises(ValueError):
                source_windows("a", ranges, **kwargs)


if __name__ == "__main__":
    unittest.main()
