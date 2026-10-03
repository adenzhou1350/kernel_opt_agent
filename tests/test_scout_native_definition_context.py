"""Lexical native-source targeting; not compilation or reachability proof."""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout_context as context


class NativeDefinitionTests(unittest.TestCase):
    def test_existing_python_and_typescript_declarations_are_preserved(self):
        for declaration, name in (("def query(input):", "query"),
                                  ("const SAFE_NETWORK_CODES = new Set();", "SAFE_NETWORK_CODES"),
                                  ("export function query(input) {", "query")):
            with self.subTest(declaration=declaration):
                self.assertEqual(context._definition_line(["// incidental " + name, declaration], name), 1)

    def test_python_docstring_native_example_cannot_replace_python_definition(self):
        lines = ['"""Example:', 'pub async fn query() {', '"""', 'def query():', '    return None']
        self.assertEqual(context._definition_line(lines, "query", language=".py"), 3)
        self.assertIsNone(context._definition_line(["func query() {}"], "query", language=".rs"))
        self.assertIsNone(context._definition_line(["fn query() {}"], "query", language=".go"))

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

    def source(self, suffix, lines, *, start=None, hints="query"):
        commit, path = "a" * 40, "src/query." + suffix
        with tempfile.TemporaryDirectory() as root:
            client = context.PublicContext(root)
            with patch.object(client, "snapshot", return_value={"files": [path]}), \
                 patch.object(client, "_read", return_value="\n".join(lines)) as read:
                result = client.source("owner/project", commit, path, hints=hints, start=start, max_lines=20)
            self.assertEqual(read.call_count, 1)
            self.assertLessEqual(len(result["text"].splitlines()), 20)
            return result

    def test_rust_trait_and_impl_same_name_exposes_lines_without_guessing_owner(self):
        lines = ["trait Base {", "    async fn query(&self);", "}"]
        lines += ["// unrelated"] * 70
        lines += ["impl Base for NativeTable {", "    async fn query(&self) {", "        run_native();", "    }", "}"]
        result = self.source("rs", lines, hints="NativeTable.query")
        choice = result["definition_selection"]
        self.assertEqual(choice["selected_line"], 2)
        self.assertEqual(choice["candidate_lines"], [2, 75])
        self.assertEqual(choice["symbol"], "query")
        self.assertNotIn("run_native", result["text"])
        self.assertIn("not resolved owners", choice["caution"])

    def test_go_receiver_variants_are_advisory_not_selected_by_owner_name(self):
        lines = ["func (s *OldStore) query() {}"] + ["// tail"] * 50
        lines += ["func (s *NewStore) query() {}"]
        result = self.source("go", lines, hints="NewStore.query")
        self.assertEqual(result["definition_selection"]["candidate_lines"], [1, 52])
        self.assertEqual(result["definition_selection"]["selected_line"], 1)

    def test_candidate_cap_and_omitted_count_preserve_read_and_excerpt_budget(self):
        lines = ["fn query() {}"] * 12
        choice = self.source("rs", lines)["definition_selection"]
        self.assertEqual(choice["candidate_lines"], [1, 2, 3, 4, 5])
        self.assertEqual(choice["omitted"], 7)
        self.assertLess(len(str(choice).encode()), 1024)

    def test_explicit_start_does_not_get_automatic_definition_choices(self):
        result = self.source("rs", ["fn query() {}", "fn query() {}"], start=2)
        self.assertEqual(result["start_line"], 2)
        self.assertNotIn("definition_selection", result)

    def test_unique_native_symbol_and_other_language_keep_existing_shape(self):
        for suffix, lines in (("rs", ["fn query() {}"]),
                              ("go", ["func query() {}"]),
                              ("py", ["def query():", "    pass", "def query():", "    pass"]),
                              ("rs", ["// fn query() {}", 'let s = "fn query() {}";', "fn query() {}"]),
                              ("rs", ["fn query() {}", "fn query_snapshot() {}"])):
            with self.subTest(suffix=suffix, lines=lines):
                self.assertNotIn("definition_selection", self.source(suffix, lines))

    def test_explicit_followup_reuses_pinned_bytes_without_another_read(self):
        commit, path = "a" * 40, "src/query.rs"
        lines = ["trait Base {", "    fn query(&self);", "}"] + ["// tail"] * 30
        lines += ["impl Base for NativeTable {", "    fn query(&self) {", "        actual_query();", "    }", "}"]
        with tempfile.TemporaryDirectory() as root:
            client = context.PublicContext(root)
            with patch.object(client, "snapshot", return_value={"files": [path]}), \
                 patch.object(client, "_read", return_value="\n".join(lines)) as read:
                first = client.source("owner/project", commit, path, hints="NativeTable.query", max_lines=20)
                followup = client.source("owner/project", commit, path,
                                         start=first["definition_selection"]["candidate_lines"][1], max_lines=20)
                self.assertEqual(read.call_count, 1)
        self.assertNotIn("actual_query", first["text"])
        self.assertIn("actual_query", followup["text"])
        self.assertNotIn("definition_selection", followup)

    def test_long_identifier_cannot_expand_advisory_metadata(self):
        name = "q" * 129
        self.assertIsNone(context._native_definition_choices(
            [f"fn {name}() {{}}", f"fn {name}() {{}}"], 0, ".rs"))


if __name__ == "__main__":
    unittest.main()
