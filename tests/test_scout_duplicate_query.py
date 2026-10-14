"""Source-bound hints must not become source-independent suppression rules."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_duplicate_query import source_duplicate_title  # noqa: E402


class DuplicateQueryTests(unittest.TestCase):
    repo = "public/project"
    title = "MoE unpermute 确定性路径重复分配全尺寸零张量"

    def source(self, name="unpermute", **changes):
        return {
            "url": f"https://raw.githubusercontent.com/{self.repo}/{'a' * 40}/ops.py",
            "requested_definition": {"name": name, "start_line": 499},
            "text": f"499: def {name}(\n500:     tensor,\n501: ):\n502:     pass",
            "requested_definition_complete": False,
            **changes,
        }

    def test_visible_declaration_replaces_generic_mixed_language_query(self):
        self.assertEqual(
            source_duplicate_title(self.repo, self.title, [self.source()]), "unpermute"
        )

    def test_numbered_source_without_selection_metadata_remains_usable(self):
        source = self.source()
        source.pop("requested_definition")
        self.assertEqual(
            source_duplicate_title(self.repo, self.title, [source]), "unpermute"
        )

    def test_missing_clipped_or_forged_declaration_retains_title(self):
        for changes in (
            {"requested_definition": None},
            {"text": "600: return unpermute(x)"},
            {"text": "499: # def unpermute("},
            {"text": "500: def unpermute("},
            {"text": None},
            {"requested_definition": {"name": "unpermute", "start_line": True}},
        ):
            with self.subTest(changes=changes):
                self.assertEqual(
                    source_duplicate_title(
                        self.repo, self.title, [self.source(**changes)]
                    ),
                    self.title,
                )

    def test_foreign_or_mutable_urls_cannot_supply_anchor(self):
        url = self.source()["url"]
        for wrong in (
            url.replace("public/project", "other/project"),
            url.replace("a" * 40, "main"),
            url.replace("https:", "http:"),
            url.replace("ops.py", "ops.ts"),
            url + "?token=secret",
        ):
            with self.subTest(url=wrong):
                self.assertEqual(
                    source_duplicate_title(
                        self.repo, self.title, [self.source(url=wrong)]
                    ),
                    self.title,
                )

    def test_unmentioned_or_multiple_definitions_retain_original_search(self):
        self.assertEqual(
            source_duplicate_title(self.repo, self.title, [self.source("unrelated")]),
            self.title,
        )
        title = self.title + " restore_tokens"
        self.assertEqual(
            source_duplicate_title(
                self.repo, title, [self.source(), self.source("restore_tokens")]
            ),
            title,
        )

    def test_injection_metadata_and_identifier_substrings_are_rejected(self):
        source = self.source("repo:private/data")
        title = self.title + " repo:private/data"
        self.assertEqual(source_duplicate_title(self.repo, title, [source]), title)
        title = "unpermute_v2 unrelated defect"
        self.assertEqual(
            source_duplicate_title(self.repo, title, [self.source()]), title
        )

    def test_async_and_repeated_same_definition_remain_one_hint(self):
        source = self.source(text="499: async def unpermute(")
        self.assertEqual(
            source_duplicate_title(self.repo, self.title, [source, source]), "unpermute"
        )

    def test_same_name_in_distinct_files_is_ambiguous(self):
        source = self.source()
        other = self.source(url=source["url"].replace("ops.py", "other.py"))
        self.assertEqual(
            source_duplicate_title(self.repo, self.title, [source, other]), self.title
        )

    def test_qualified_method_spelling_keeps_the_owner_in_search(self):
        for qualified in (
            "OneToOne.update",
            "ManyToMany.update",
            "DummyFile.__enter__",
        ):
            with self.subTest(qualified=qualified):
                name = qualified.rsplit(".", 1)[1]
                title = qualified + " 对一次性输入行为错误"
                self.assertEqual(
                    source_duplicate_title(self.repo, title, [self.source(name)]),
                    qualified,
                )

    def test_nested_qualified_spelling_is_only_a_title_hint(self):
        source = self.source("update")
        title = "package.Owner.update mixed-language failure"
        self.assertEqual(
            source_duplicate_title(self.repo, title, [source]), "package.Owner.update"
        )

    def test_two_owners_for_one_visible_method_keep_original_query(self):
        title = "One.update 与 Other.update 行为不一致"
        self.assertEqual(
            source_duplicate_title(self.repo, title, [self.source("update")]), title
        )

    def test_cpp_definition_restores_method_query_without_extra_requests(self):
        title = "非 eviction 模式 RemoveAll 漏删嵌套文件"
        source = self.source(url=self.source()["url"].replace("ops.py", "storage.cpp"),
                             text="583: void StorageBackend::RemoveAll() {\n584:   return;\n585: }")
        self.assertEqual(source_duplicate_title(self.repo, title, [source]), "RemoveAll")
        source["text"] = "583: void StorageBackend::RemoveAll(\n584:   ) {\n585: }"
        self.assertEqual(source_duplicate_title(self.repo, title, [source]), "RemoveAll")

    def test_cpp_comments_strings_calls_declarations_and_unsupported_syntax_abstain(self):
        title = "RemoveAll misses files"
        for text in (
            "583: // void Backend::RemoveAll() {",
            '583: const char* x = "void Backend::RemoveAll() {";',
            "583: /* void Backend::RemoveAll() { */",
            "583: void Backend::RemoveAll();",
            "583: return Backend::RemoveAll();",
            "583: auto result = Backend::RemoveAll();",
            "583: #define CLEAN void Backend::RemoveAll() {",
            '583: auto x = R"(void Backend::RemoveAll() {)";',
            "583: void Backend::RemoveAll(\n585: ) {",
            "void Backend::RemoveAll() {",
            "583: void Backend::RemoveAll(\n584: )",
        ):
            with self.subTest(text=text):
                source = self.source(url=self.source()["url"].replace("ops.py", "ops.cpp"), text=text)
                self.assertEqual(source_duplicate_title(self.repo, title, [source]), title)

    def test_multiple_cpp_owners_and_files_remain_ambiguous(self):
        title = "RemoveAll failure"
        source = self.source(url=self.source()["url"].replace("ops.py", "ops.cpp"),
                             text="583: void First::RemoveAll() {\n584: }\n585: void Second::RemoveAll() {\n586: }")
        self.assertEqual(source_duplicate_title(self.repo, title, [source]), title)
        source["text"] = "583: void First::RemoveAll() {\n584: }"
        other = {**source, "url": source["url"].replace("ops.cpp", "other.cpp")}
        self.assertEqual(source_duplicate_title(self.repo, title, [source, other]), title)

    def test_cpp_hint_composes_with_existing_bounded_issue_search(self):
        from unittest.mock import patch
        from urllib.parse import parse_qs, urlsplit
        import tempfile
        from kimi_scout_context import PublicContext

        source = self.source(url=self.source()["url"].replace("ops.py", "ops.cpp"),
                             text="583: void StorageBackend::RemoveAll() {\n584: }")
        title = "非 eviction 模式 RemoveAll 漏删嵌套文件"
        queries = []
        def respond(url):
            query = parse_qs(urlsplit(url).query)
            queries.append(query["q"][0])
            self.assertEqual(query["per_page"], ["5"])
            return {"items": [{"number": 3231, "title": "Existing RemoveAll RFC", "body": "Nested file-per-key files survive; scope containment required."}]}
        with tempfile.TemporaryDirectory() as root:
            context = PublicContext(Path(root))
            with patch.object(context, "_public"), patch.object(context, "_json", side_effect=respond):
                related = context.duplicate_sources(self.repo, source_duplicate_title(self.repo, title, [source]))
        self.assertEqual(queries, [f'repo:{self.repo} in:title,body "RemoveAll"',
                                   f'repo:{self.repo} is:pr in:title,body ("RemoveAll" OR "Remove All")'])
        self.assertEqual([item["url"] for item in related], [f"https://github.com/{self.repo}/issues/3231"])
        self.assertFalse(related[0]["search_exhaustive"])


if __name__ == "__main__":
    unittest.main()
