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


if __name__ == "__main__":
    unittest.main()
