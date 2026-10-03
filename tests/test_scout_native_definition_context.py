"""Lexical native-source targeting; not compilation or reachability proof."""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout_context as context


class NativeDefinitionTests(unittest.TestCase):
    def test_go_function_and_receiver_method(self):
        for declaration in (
            "func produceFromList(tasks chan<- Object) error {",
            "func (s *Store[T]) produceFromList(tasks chan<- Object) error {",
        ):
            with self.subTest(declaration=declaration):
                lines = ["// produceFromList has a caller here", "produceFromList(tasks)", declaration]
                self.assertEqual(context._definition_line(lines, "produceFromList"), 2)

    def test_rust_function_visibility_and_modifiers(self):
        for declaration in (
            "fn query<T>(input: T) {",
            "pub async fn query(input: &str) {",
            "pub(crate) async fn query(input: &str) {",
            'pub unsafe extern "C" fn query(input: *const u8) {',
        ):
            with self.subTest(declaration=declaration):
                lines = ["// query(input) is referenced elsewhere", "self.query(input).await", declaration]
                self.assertEqual(context._definition_line(lines, "query"), 2)

    def test_native_mentions_and_function_types_are_not_declarations(self):
        lines = ["// fn query(input) {", "// func query(input) {", 'let text = "fn query()";',
                 "type Callback func(query int) error", "let callback: fn(query: i32) = callback;"]
        self.assertIsNone(context._definition_line(lines, "query"))

    def test_native_function_beats_same_named_local_variable(self):
        for declaration in ("pub async fn query(input: &str) {", "func query() error {"):
            with self.subTest(declaration=declaration):
                lines = ["let query = some_other_function();", "var query = input", declaration]
                self.assertEqual(context._definition_line(lines, "query"), 2)

    def test_native_window_prefers_declaration_over_earlier_call(self):
        commit = "a" * 40
        for suffix, declaration in (("go", "func query(input string) error {"),
                                    ("rs", "pub(crate) async fn query(input: &str) {")):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as root:
                path = "src/query." + suffix
                url = f"https://raw.githubusercontent.com/owner/project/{commit}/{path}"
                lines = ["// query is called here", "query(input)"] + ["// unrelated"] * 250
                lines += [declaration, "    return result", "}"] + ["// tail"] * 40
                client = context.PublicContext(root)
                with patch.object(client, "snapshot", return_value={"files": [path]}), \
                     patch.object(client, "_read", return_value="\n".join(lines)):
                    evidence = client.source("owner/project", commit, path, hints="query", max_lines=40)
                self.assertEqual(evidence["url"], url)
                self.assertIn(declaration, evidence["text"])
                self.assertGreater(evidence["start_line"], 200)
                self.assertLessEqual(len(evidence["text"].splitlines()), 40)
                self.assertTrue(evidence["truncated"])

    def test_explicit_start_still_overrides_native_declaration(self):
        lines = ["// unrelated"] * 20 + ["func query() {}"]
        commit = "a" * 40
        with tempfile.TemporaryDirectory() as root:
            client = context.PublicContext(root)
            with patch.object(client, "snapshot", return_value={"files": ["src/query.go"]}), \
                 patch.object(client, "_read", return_value="\n".join(lines)):
                evidence = client.source("owner/project", commit, "src/query.go", hints="query", start=1, max_lines=10)
            self.assertEqual(evidence["start_line"], 1)
            self.assertNotIn("func query", evidence["text"])


if __name__ == "__main__":
    unittest.main()
