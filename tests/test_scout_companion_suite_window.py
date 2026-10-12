"""Offline suite-window acquisition; no claimed model or PR benefit."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from kimi_scout_context import PublicContext, _test_suite_anchor
from kimi_scout_research import companion_source_hints


class CompanionSuiteWindowTests(unittest.TestCase):
    def test_observed_numbered_declarations_precede_filename(self):
        item = {"url": "https://example/a.ts", "text": "1: import { other } from './x';\n2: export function allowlistFor(\n3: class Profile {"}
        self.assertEqual(companion_source_hints(item, "shared"), "allowlistFor Profile shared")
        self.assertEqual(companion_source_hints({**item, "url": "https://example/a.py"}, "shared"), "shared")

    def test_literal_suite_beats_import_and_comments(self):
        lines = ["import { allowlistFor } from './shared';", "// describe('allowlistFor', () => {});", "describe('unrelated', () => {", "});", "describe('allowlistFor', () => {"]
        self.assertEqual(_test_suite_anchor(lines, "allowlistFor shared"), ("allowlistFor", 4))

    def test_ambiguous_dynamic_and_partial_titles_abstain(self):
        for lines in (
            ["describe('allowlistFor', () => {});", "describe('allowlistFor', () => {});"],
            ["describe(`allowlistFor`, () => {});"],
            ["describe(prefix + 'allowlistFor', () => {});"],
            ["describe('allowlistFor extras', () => {});"],
            ["describe('allowlistForOther', () => {});"],
        ):
            self.assertIsNone(_test_suite_anchor(lines, "allowlistFor"))

    def test_subject_order_and_bounds(self):
        lines = ["describe.skip('second', () => {});", 'describe.only("first", () => {});']
        self.assertEqual(_test_suite_anchor(lines, "first second"), ("first", 1))
        self.assertIsNone(_test_suite_anchor(lines, "x " * 1001 + "first"))
        text = "\n".join(f"export function subject{i}() {{}}" for i in range(20))
        hints = companion_source_hints({"url": "x.ts", "text": text}, "file")
        self.assertEqual(len(hints.split()), 9)

    def test_real_reader_exposes_late_suite_without_extra_read(self):
        path = "test/shared.test.ts"
        raw = "import { allowlistFor } from './shared';\n" + "// unrelated\n" * 300 + "describe('allowlistFor', () => {\n  it('wildcard with extras', () => {});\n});\n"
        with tempfile.TemporaryDirectory() as temp:
            reader = PublicContext(temp)
            with (
                patch.object(reader, "snapshot", return_value={"files": [path], "blobs": {path: "b" * 40}}),
                patch.object(reader, "_source_text", return_value=(raw, "raw")) as read,
            ):
                result = reader.source("owner/project", "a" * 40, path, hints="allowlistFor shared", max_lines=70)
                self.assertEqual(read.call_count, 1)
                self.assertEqual(result["start_line"], 302)
                self.assertIn("wildcard with extras", result["text"])
                self.assertEqual(result["test_suite_anchor"]["subject"], "allowlistFor")
                explicit = reader.source("owner/project", "a" * 40, path, hints="allowlistFor", start=1, max_lines=1)
                self.assertNotIn("test_suite_anchor", explicit)
                self.assertEqual(explicit["start_line"], 1)
                self.assertEqual(read.call_count, 1)

    def test_no_matching_suite_preserves_fallback(self):
        self.assertIsNone(_test_suite_anchor(["describe('other', () => {});"], "allowlistFor"))


if __name__ == "__main__":
    unittest.main()
