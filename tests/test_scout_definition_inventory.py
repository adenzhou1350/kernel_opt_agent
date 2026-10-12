"""Ambiguous implementations stay visible without another source/model read."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from kimi_scout_context import PublicContext
from scout_requested_definition import (
    requested_definition_inventory,
    requested_function_window,
)


class DefinitionInventoryTests(unittest.TestCase):
    raw = (
        "class Budget:\n"
        "    def prepare_load_back(self):\n"
        "        return True\n" + "\n" * 150 + "class SharedBudget(Budget):\n"
        "    async def prepare_load_back(self):\n"
        "        return self.reclaim()\n"
    )
    request = "definition(prepare_load_back) and definition(init_load_back)"

    def inventory(self, raw=None, request=None, symbol="prepare_load_back"):
        return requested_definition_inventory(
            (raw or self.raw).splitlines(), request or self.request, symbol
        )

    def source(self, path="src/budget.py", request=None):
        with tempfile.TemporaryDirectory() as temp:
            reader = PublicContext(Path(temp))
            with (
                patch.object(reader, "snapshot", return_value={
                    "files": [path], "blobs": {path: "b" * 40},
                }),
                patch.object(reader, "_read", return_value=self.raw) as read,
            ):
                source = reader.source(
                    "owner/project",
                    "a" * 40,
                    path,
                    exact_hint="prepare_load_back",
                    max_lines=80,
                    request_hints=request or self.request,
                )
                self.assertEqual(read.call_count, 1)
        return source

    def test_real_source_reader_keeps_override_location_outside_default_window(self):
        source = self.source()
        self.assertIn("return True", source["text"])
        self.assertNotIn("self.reclaim", source["text"])
        self.assertLessEqual(source["end_line"] - source["start_line"] + 1, 80)
        inventory = source["definition_inventory"]
        self.assertEqual(inventory["total_matches"], 2)
        self.assertEqual(
            [item["qualified_name"] for item in inventory["candidates"]],
            ["Budget.prepare_load_back", "SharedBudget.prepare_load_back"],
        )
        self.assertGreater(
            inventory["candidates"][1]["declaration_line"], source["end_line"]
        )
        self.assertNotIn("requested_definition_complete", source)

    def test_explicit_qualified_next_request_can_select_override_body(self):
        inventory = self.inventory()
        selected = inventory["candidates"][1]
        window = requested_function_window(
            self.raw.splitlines(), f"definition({selected['qualified_name']})"
        )
        self.assertEqual(window["start_line"], selected["declaration_line"])
        self.assertEqual(window["end_line"], selected["end_line"])

    def test_no_inventory_for_single_declaration_or_unsupported_syntax(self):
        for raw in ("def prepare_load_back(): return True", "def broken("):
            self.assertIsNone(self.inventory(raw=raw))
        self.assertNotIn("definition_inventory", self.source(path="src/budget.cc"))

    def test_no_implicit_or_qualified_request_or_injected_query(self):
        for request in (
            "references(prepare_load_back)",
            "Inspect prepare_load_back",
            "definition(Budget.prepare_load_back)",
            "definition(prepare_load_back repo:private/other)",
            "definition(https://other.invalid/prepare_load_back)",
            "definition(\nprepare_load_back)",
            "xdefinition(prepare_load_back)",
        ):
            with self.subTest(request=request):
                self.assertIsNone(self.inventory(request=request))
                self.assertNotIn("definition_inventory", self.source(request=request))
        for symbol in (None, 1, "x", "target repo:other/repo", "a" * 129):
            self.assertIsNone(self.inventory(symbol=symbol))

    def test_inventory_is_bounded_and_reports_omissions(self):
        raw = "\n".join(
            f"class Owner{i}:\n    def prepare_load_back(self): pass" for i in range(12)
        )
        inventory = self.inventory(raw=raw)
        self.assertEqual(inventory["total_matches"], 12)
        self.assertEqual(len(inventory["candidates"]), 8)
        self.assertTrue(inventory["truncated"])
        self.assertEqual(
            inventory["candidates"][-1]["qualified_name"],
            "Owner7.prepare_load_back",
        )

    def test_nested_and_duplicate_owners_are_lexical_not_resolved(self):
        raw = (
            "def factory():\n    class Owner:\n"
            "        def prepare_load_back(self): pass\n"
            "class Owner:\n    def prepare_load_back(self): pass\n"
        )
        inventory = self.inventory(raw=raw)
        self.assertEqual(
            [item["qualified_name"] for item in inventory["candidates"]],
            ["factory.Owner.prepare_load_back", "Owner.prepare_load_back"],
        )
        self.assertIn("Not receiver resolution", inventory["scope"])
        self.assertIsNone(
            requested_function_window(
                raw.splitlines(), "definition(Owner.prepare_load_back)"
            )
        )

    def test_source_is_parsed_never_imported_or_executed(self):
        raw = "raise AssertionError('must not execute')\n" + self.raw
        self.assertEqual(self.inventory(raw=raw)["total_matches"], 2)

    def test_excessive_owner_name_does_not_expand_packet(self):
        raw = self.raw + f"\nclass {'X' * 257}:\n    def prepare_load_back(self): pass"
        self.assertIsNone(self.inventory(raw=raw))


if __name__ == "__main__":
    unittest.main()
