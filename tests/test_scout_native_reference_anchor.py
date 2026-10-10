"""Indexed native reference windows should not stop at a using declaration."""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from kimi_scout_context import PublicContext  # noqa: E402
from scout_symbol_references import native_invocation_hint_line  # noqa: E402

REPO = "owner/project"
COMMIT = "a" * 40


class NativeReferenceAnchorTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.reader = PublicContext(Path(directory.name))

    def source(self, raw, request="references(target)", path="src/kernel.cu"):
        snapshot = {"commit": COMMIT, "files": [path]}
        with (
            patch.object(self.reader, "snapshot", return_value=snapshot),
            patch.object(self.reader, "_read", return_value=raw) as read,
        ):
            result = self.reader.source(
                REPO,
                COMMIT,
                path,
                exact_hint="target",
                request_hints=request,
                max_lines=80,
            )
        return result, read.call_count

    def test_explicit_native_reference_prefers_invocation_shape_to_import_trivia(self):
        raw = (
            "using demo::target;\n"
            "// target();\n"
            'const char* example = "target()";\n'
            "#define TARGET_CALL \\\n"
            "  target()\n"
            + "// filler\n" * 210
            + "void work() {\n  target\n    ();\n}\n"
        )
        result, reads = self.source(raw)
        self.assertGreater(result["start_line"], 90)
        self.assertRegex(result["text"], r"\d+:   target\n\d+:     \(\);")
        self.assertNotIn("using demo::target", result["text"])
        self.assertNotIn("TARGET_CALL", result["text"])
        self.assertEqual(reads, 1)
        self.assertLessEqual(len(result["text"].splitlines()), 80)
        self.assertTrue(result["exact_hint_matched"])
        # Already-read pinned bytes are reused; no second acquisition is added.
        repeated, reads = self.source(raw)
        self.assertEqual(repeated, result)
        self.assertEqual(reads, 0)

    def test_ordinary_literals_other_requests_and_non_native_sources_keep_first_match(
        self,
    ):
        raw = "using demo::target;\n" + "// filler\n" * 110 + "target();\n"
        for request, path in (
            ("", "src/default.cpp"),
            ("references(other)", "src/other.cpp"),
            ("references(target)", "src/plain.py"),
        ):
            with self.subTest(request=request, path=path):
                result, _ = self.source(raw, request, path)
                self.assertEqual(result["start_line"], 1)

    def test_unsupported_raw_strings_or_no_invocation_keep_literal_fallback(self):
        for number, raw in enumerate(
            (
                'auto s = R"tag(target())tag";\n' + "// filler\n" * 110 + "target();\n",
                "/* target()\n" + "// filler\n" * 110 + "target();\n",
                "using demo::target;\n" + "// filler\n" * 110,
            )
        ):
            with self.subTest(number=number):
                result, _ = self.source(raw, path=f"src/fallback{number}.cpp")
                self.assertEqual(result["start_line"], 1)
                self.assertTrue(result["exact_hint_matched"])

    def test_hint_is_bounded_lexical_evidence_not_call_resolution(self):
        self.assertEqual(
            native_invocation_hint_line("othertarget();\nvoid target();\n", "target"), 1
        )
        # Conditional compilation is not evaluated; declarations can also match.
        self.assertEqual(
            native_invocation_hint_line("#if 0\ntarget();\n#endif\n", "target"), 1
        )
        for raw, symbol in (
            ("target();", "other.target"),
            ("target();", None),
            (" " * 1_000_001, "target"),
        ):
            self.assertIsNone(native_invocation_hint_line(raw, symbol))


if __name__ == "__main__":
    unittest.main()
