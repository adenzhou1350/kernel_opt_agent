"""Cached container initializers are syntax evidence, not runtime constants."""

import ast
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_symbol_references import _python_literal_assignments, reference_requests


class LiteralContainerReferenceTests(unittest.TestCase):
    def setUp(self):
        self.repo, self.commit, self.path = "public/library", "a" * 40, "tokenizer.py"
        self.url = f"https://raw.githubusercontent.com/{self.repo}/{self.commit}/{self.path}"
        self.packet = {"repo": self.repo, "sources": [{
            "url": self.url, "start_line": 180, "end_line": 260,
        }]}
        self.snapshot = {"commit": self.commit, "files": [self.path]}

    def requests(self, raw, name="VOCAB_FILES_NAMES", **kwargs):
        cached = Mock(return_value=raw)
        result = reference_requests(
            self.packet, self.snapshot, {"next_check": f"references({name})"},
            cached, **kwargs,
        )
        cached.assert_called_once_with(self.repo, self.commit, self.path)
        return result

    def test_dictionary_declaration_precedes_the_already_shown_consumer(self):
        raw = (
            'raise RuntimeError("cached source must never execute")\n'
            + "\n" * 29
            + 'VOCAB_FILES_NAMES = {"vocab_file": "tokenizer.model"}\n'
            + "\n" * 170
            + "class Tokenizer:\n    vocab_files_names = VOCAB_FILES_NAMES\n"
        )
        self.assertEqual(self.requests(raw), [{"path": self.path, "start": 23, "max_lines": 80}])

    def test_literal_containers_and_nested_annotation_without_evaluation(self):
        for initializer in (
            "{}", "[]", "()", "{1, 2}", "[1, None, True]", '("a", "b")',
            '{"files": ["vocab.json", "merges.txt"], "bounds": (1, 2)}',
        ):
            for assignment in (f"FILES = {initializer}", f"FILES: object = {initializer}"):
                with self.subTest(assignment=assignment):
                    self.assertEqual(_python_literal_assignments(ast.parse(assignment), ["FILES"]), {1})

    def test_uppercase_container_entries_are_shown_not_resolved(self):
        for value in ('{"vocab": TOKENIZER_FILE}', "[FIRST, SECOND]", "{KEY: (VALUE, 1)}"):
            with self.subTest(value=value):
                self.assertEqual(_python_literal_assignments(ast.parse(f"FILES = {value}"), ["FILES"]), {1})

    def test_calls_computed_names_comprehensions_unpacking_and_operators_abstain(self):
        for initializer in (
            "dict()", "set()", '{"vocab": read_file()}', '{"vocab": filename}',
            '{"vocab": config.FILE}', "OTHER",
            "[x for x in values]", "{x: x for x in values}", "{**OTHER}",
            '{**{"x": 1}}', "[*OTHER]", "[1] + [2]", '[f"{name}"]',
        ):
            with self.subTest(initializer=initializer):
                self.assertEqual(
                    _python_literal_assignments(ast.parse(f"FILES = {initializer}"), ["FILES"]), set()
                )

    def test_rebinding_and_cross_scope_ambiguity_remain_rejected(self):
        for suffix in (
            "FILES = {}", "def helper(FILES): pass", "class Owner:\n    FILES = {}",
            "from other import FILES", "from other import *", "del FILES",
        ):
            with self.subTest(suffix=suffix):
                self.assertEqual(
                    _python_literal_assignments(ast.parse("FILES = {}\n" + suffix), ["FILES"]), set()
                )

    def test_qualified_request_does_not_turn_module_dictionary_into_class_attribute(self):
        raw = 'VOCAB_FILES_NAMES = {"vocab_file": "tokenizer.model"}\n'
        self.assertEqual(self.requests(raw, "Tokenizer.VOCAB_FILES_NAMES"), [])
        self.assertEqual(self.requests("vocab_files_names = {}\n", "vocab_files_names"), [])

    def test_mutation_does_not_make_the_initializer_a_runtime_value_claim(self):
        raw = 'FILES = {"vocab": "old"}\nFILES["vocab"] = "new"\n'
        # The old initializer remains useful source to inspect; no evaluation,
        # immutable-value claim or resolved receiver is returned by this helper.
        self.assertEqual(_python_literal_assignments(ast.parse(raw), ["FILES"]), {1})
        self.assertEqual(set(self.requests(raw, "FILES")[0]), {"path", "start", "max_lines"})

    def test_existing_window_limit_and_seen_source_budget(self):
        raw = "FIRST = {}\n" + "\n" * 300 + "LAST = []\n"
        cached = Mock(return_value=raw)
        result = reference_requests(
            self.packet, self.snapshot,
            {"next_check": "references(FIRST) references(LAST)"}, cached, limit=1,
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["max_lines"], 80)
        cached.assert_called_once()
        self.packet["sources"][0].update(start_line=1, end_line=1000)
        self.assertEqual(self.requests(raw, "FIRST"), [])


if __name__ == "__main__":
    unittest.main()
