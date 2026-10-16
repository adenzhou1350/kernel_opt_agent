"""Offline Rust lexical source-location tests; no Rust compilation or network."""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from kimi_scout_context import PublicContext
from scout_requested_definition import requested_rust_fn_anchor


class RustFnContextTests(unittest.TestCase):
    def test_unique_fn_location_skips_earlier_doc_reference(self):
        raw = "//! See execute_write for details.\n" + "\n" * 100 + "pub(crate) async fn execute_write(\n    input: Reader,\n) -> Result<()> {\n    validate(&input)?;\n    writer.put(input).await?;\n    Ok(())\n}\n"
        result = requested_rust_fn_anchor(raw, "definition(execute_write)")
        self.assertEqual(result["line"], 102)
        self.assertEqual(result["literal"], "fn execute_write")
        self.assertIn("Not a parsed definition", result["scope"])

    def test_one_explicit_target_only_and_no_qualified_owner_guess(self):
        raw = "fn target() {}\n"
        for request in (
            "target", "references(target)", "definition(Owner.target)",
            "definition(module::target)", "definition(target, other)",
            "definition(\ntarget)", "definition(target", "definition(absent)",
            "definition(target) definition(target)",
            "definition(target) definition(other)", None, [],
            "x" * 2000 + "definition(target)",
        ):
            with self.subTest(request=request):
                self.assertIsNone(requested_rust_fn_anchor(raw, request))
        self.assertIsNone(requested_rust_fn_anchor([], "definition(target)"))
        self.assertIsNone(requested_rust_fn_anchor("x" * 1_000_001, "definition(target)"))

    def test_repeated_literals_abstain_but_unique_comments_are_labeled_lexical(self):
        for raw in (
            "impl A { fn target() {} }\nimpl B { fn target() {} }",
            "// fn target() {}\nfn target() {}",
            'const SAMPLE: &str = "fn target() {}";\nfn target() {}',
            "fn target_suffix() {}", "fn target2() {}", "some_fn target() {}",
        ):
            with self.subTest(raw=raw):
                self.assertIsNone(requested_rust_fn_anchor(raw, "definition(target)"))
        for raw in ("// fn target() {}", 'let sample = "fn target() {}";'):
            value = requested_rust_fn_anchor(raw, "definition(target)")
            self.assertIn("including comments/strings", value["scope"])
            self.assertNotIn("end_line", value)
        self.assertEqual(requested_rust_fn_anchor("fn target<T>(v: T) {}", "definition(target)")["line"], 1)

    def source(self, raw, **kwargs):
        with tempfile.TemporaryDirectory() as temporary:
            context = PublicContext(Path(temporary))
            path = kwargs.pop("path", "src/write.rs")
            with patch.object(context, "snapshot", return_value={"files": [path], "blobs": {path: "b" * 40}}), patch.object(context, "_source_text", return_value=(raw, "fixture")) as read:
                result = context.source("public/project", "a" * 40, path,
                    hints="target", request_hints="definition(target)", **kwargs)
            self.assertEqual(read.call_count, 1)
            return result

    def test_actual_reader_returns_existing_bounded_window_without_body_claim(self):
        raw = "//! See target.\n" + "\n" * 100 + "pub async fn target() {\n" + "    step();\n" * 100 + "}\n"
        result = self.source(raw, max_lines=4)
        self.assertEqual((result["start_line"], result["end_line"]), (102, 105))
        self.assertIn("pub async fn target", result["text"])
        self.assertEqual(result["requested_rust_fn_literal"]["line"], 102)
        self.assertNotIn("requested_definition", result)
        self.assertNotIn("requested_definition_complete", result)
        self.assertTrue(result["truncated"])

    def test_explicit_line_or_literal_and_other_languages_keep_precedence(self):
        raw = "// MARK\n" + "\n" * 100 + "fn target() {}\n"
        for options in ({"start": 1}, {"exact_hint": "MARK"}, {"path": "src/write.cpp"}):
            result = self.source(raw, max_lines=4, **options)
            self.assertNotIn("requested_rust_fn_literal", result)
        result = self.source("// fn target() {}\nfn target() {}\n", max_lines=4)
        self.assertNotIn("requested_rust_fn_literal", result)


if __name__ == "__main__":
    unittest.main()
