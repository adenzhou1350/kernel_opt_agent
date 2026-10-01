"""Offline import-context hints: no network, provider, source execution or GPU."""

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_import_context import import_requests

COMMIT = "a" * 40


class ImportContextTests(unittest.TestCase):
    def requests(
        self,
        raw,
        next_check="Inspect Schema and readVersion",
        *,
        path="src/read.ts",
        files=None,
        limit=2,
    ):
        packet = {
            "repo": "o/r",
            "sources": [
                {
                    "url": f"https://raw.githubusercontent.com/o/r/{COMMIT}/{path}",
                    "text": "100: window does not include the imports",
                }
            ],
        }
        snapshot = {
            "commit": COMMIT,
            "files": files or [path, "src/contracts.ts", "src/version.ts"],
        }
        cache = Mock(return_value=raw)
        result = import_requests(
            packet, snapshot, {"next_check": next_check}, cache, limit=limit
        )
        return result, cache, packet, snapshot

    def test_named_types_and_functions_replace_filename_guessing(self):
        result, cache, _, _ = (
            self.requests("""import type { Schema } from "./contracts.js";
import { readVersion } from "./version.js";
export function read() {}""")
        )
        self.assertEqual(
            result,
            [
                {"path": "src/contracts.ts", "hints": "Schema", "max_lines": 80},
                {"path": "src/version.ts", "hints": "readVersion", "max_lines": 80},
            ],
        )
        cache.assert_called_once_with("o/r", COMMIT, "src/read.ts")

    def test_aliases_use_observed_imported_name_not_untrusted_hint(self):
        result, _, _, _ = self.requests(
            'import Default, { type Original as Schema } from "./contracts.js";',
            "Schema",
        )
        self.assertEqual(result[0]["hints"], "Original")

    def test_order_and_budget_follow_explicit_missing_symbols(self):
        raw = 'import {Schema} from "./contracts.js"; import {readVersion} from "./version.js";'
        result, _, _, _ = self.requests(raw, "readVersion then Schema", limit=1)
        self.assertEqual([r["path"] for r in result], ["src/version.ts"])
        result, _, _, _ = self.requests(raw, "Schema Schema")
        self.assertEqual(len(result), 1)

    def test_comments_strings_and_imports_after_statements_not_guessed(self):
        raw = """/* import { Schema } from "./contracts.js"; */
// import { readVersion } from "./version.js";
const text = `import { Schema } from "./contracts.js";`;
import { readVersion } from "./version.js";"""
        self.assertEqual(self.requests(raw)[0], [])
        raw = (
            '"use client"; import "setup"; import path from "node:path";\n'
            'import { Schema } from "./contracts.js";'
        )
        self.assertEqual(self.requests(raw)[0][0]["path"], "src/contracts.ts")

    def test_bare_wildcard_escaped_and_missing_imports_abstain(self):
        for raw in (
            'import {Schema} from "package";',
            'import * as Schema from "./contracts.js";',
            'import {Schema} from "./missing.js";',
            'import {Schema} from "./contra\\x63ts.js";',
        ):
            self.assertEqual(self.requests(raw, "Schema")[0], [])

    def test_ambiguous_resolution_and_escape_abstain(self):
        raw = 'import {Schema} from "./contracts.js";'
        self.assertEqual(
            self.requests(
                raw, files=["src/read.ts", "src/contracts.ts", "src/contracts.js"]
            )[0],
            [],
        )
        self.assertEqual(
            self.requests(
                'import {Schema} from "../../contracts.js";',
                files=["src/read.ts", "contracts.ts"],
            )[0],
            [],
        )
        result, _, _, _ = self.requests(
            'import {Schema} from "../contracts.js";',
            files=["src/read.ts", "contracts.ts"],
        )
        self.assertEqual(result[0]["path"], "contracts.ts")

    def test_python_relative_alias_is_module_hint_not_installed_package_proof(self):
        raw = "from .contracts import Original as Schema\nfrom external import readVersion\n"
        result, _, _, _ = self.requests(
            raw, path="pkg/read.py", files=["pkg/read.py", "pkg/contracts.py"]
        )
        self.assertEqual(
            result, [{"path": "pkg/contracts.py", "hints": "Original", "max_lines": 80}]
        )
        self.assertEqual(self.requests("def broken(", path="pkg/read.py")[0], [])

    def test_revision_and_url_mismatch_do_not_even_read_cache(self):
        _, _, packet, snapshot = self.requests("")
        for url in (
            packet["sources"][0]["url"].replace(COMMIT, "b" * 40),
            packet["sources"][0]["url"] + "?q=1",
            packet["sources"][0]["url"].replace("o/r", "evil/r"),
        ):
            packet["sources"][0]["url"] = url
            cache = Mock(side_effect=AssertionError("must not read cache"))
            self.assertEqual(
                import_requests(packet, snapshot, {"next_check": "Schema"}, cache), []
            )
            cache.assert_not_called()

    def test_missing_hints_or_cache_large_and_binary_source_abstain(self):
        for raw in (None, "x" * 131073, "\x00", ""):
            self.assertEqual(self.requests(raw)[0], [])
        self.assertEqual(
            self.requests('import {Schema} from "./contracts.js";', "no symbol")[0], []
        )
        with self.assertRaises(ValueError):
            self.requests("", limit=True)


if __name__ == "__main__":
    unittest.main()
