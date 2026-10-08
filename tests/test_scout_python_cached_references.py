"""Large cached Python consumers remain bounded, read-only source hints."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from kimi_scout_context import PublicContext
from scout_symbol_references import reference_requests


class CachedPythonReferencesTests(unittest.TestCase):
    def setUp(self):
        self.repo, self.sha, self.path = "a/b", "a" * 40, "src/optimizer.py"
        self.url = (
            f"https://raw.githubusercontent.com/{self.repo}/{self.sha}/{self.path}"
        )
        self.packet = {
            "repo": self.repo,
            "sources": [{"url": self.url, "start_line": 1, "end_line": 80}],
        }
        self.snapshot = {"commit": self.sha, "files": [self.path]}
        self.raw = (
            "# "
            + "padding" * 25000
            + "\n" * 100
            + ('def consume(owner):\n    return getattr(owner, "method", "gram")\n')
        )

    def requests(self, raw=None, request="references(self.method)"):
        return reference_requests(
            self.packet,
            self.snapshot,
            {"next_check": request},
            lambda *args: self.raw if raw is None else raw,
        )

    def test_qualified_name_finds_hidden_literal_getattr_consumer_in_large_cache(self):
        self.assertGreater(len(self.raw.encode()), 131072)
        self.assertEqual(
            self.requests(), [{"path": self.path, "start": 94, "max_lines": 80}]
        )

    def test_cache_accessor_accepts_existing_python_up_to_source_budget_without_fetch(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            reader = PublicContext(Path(directory))
            with (
                patch.object(
                    reader, "_load", return_value={"url": self.url, "text": self.raw}
                ),
                patch.object(
                    reader, "_read", side_effect=AssertionError("must not fetch")
                ),
            ):
                self.assertEqual(
                    reader.cached_source_text(self.repo, self.sha, self.path), self.raw
                )

    def test_cache_rejects_utf8_oversize_identity_drift_and_non_python_expansion(self):
        with tempfile.TemporaryDirectory() as directory:
            reader = PublicContext(Path(directory))
            for path, url, raw in (
                (self.path, self.url, "#" + "x" * 1000000),
                (self.path, self.url, "#" + "界" * 333334),
                (self.path, self.url.replace(self.sha, "b" * 40), self.raw),
                ("src/optimizer.ts", self.url.replace(".py", ".ts"), self.raw),
            ):
                with (
                    self.subTest(path=path, url=url),
                    patch.object(
                        reader, "_load", return_value={"url": url, "text": raw}
                    ),
                    patch.object(
                        reader, "_read", side_effect=AssertionError("must not fetch")
                    ),
                ):
                    self.assertIsNone(
                        reader.cached_source_text(self.repo, self.sha, path)
                    )
        self.assertEqual(self.requests("#" + "x" * 1000000), [])

    def test_reflection_only_literal_builtin_reads_not_plain_strings_or_dynamic_keys(
        self,
    ):
        for raw in (
            'message = "method"\n',
            "value = getattr(owner, key)\n",
            'value = owner.getattr(owner, "method")\n',
            'setattr(owner, "method", 1)\n',
        ):
            self.assertEqual(self.requests(raw), [])
        raw = "\n" * 100 + 'value = hasattr(owner, "method")\n'
        self.assertEqual(len(self.requests(raw)), 1)

    def test_qualified_names_are_terminal_name_hints_not_binding_resolution(self):
        raw = "\n" * 100 + "value = unrelated.method\n"
        self.assertEqual(len(self.requests(raw)), 1)
        for request in (
            "references(self.method())",
            "references(self[0].method)",
            "references(self..method)",
            "references(a.b.c.d.e.f)",
            "references(" + "a" * 129 + ".method)",
        ):
            self.assertEqual(self.requests(raw, request), [])

    def test_source_is_never_executed_and_limits_windows_not_file_absence_claims(self):
        raw = (
            'raise RuntimeError("never execute")\n'
            + "\n" * 100
            + "value = owner.method\n"
        )
        result = self.requests(raw)
        self.assertEqual(len(result), 1)
        self.assertLessEqual(result[0]["max_lines"], 80)
        self.packet["sources"][0].update(start_line=1, end_line=1000)
        self.assertEqual(self.requests(raw), [])


if __name__ == "__main__":
    unittest.main()
