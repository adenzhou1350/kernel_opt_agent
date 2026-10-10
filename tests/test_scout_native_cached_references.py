"""Native reference hints reuse bounded cached source, without fetching."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from kimi_scout_context import PublicContext, RAW_LIMIT
from scout_symbol_references import reference_cache_limit, reference_requests


class NativeCachedReferencesTests(unittest.TestCase):
    def setUp(self):
        self.repo, self.sha = "a/b", "a" * 40
        self.raw = "// " + "x" * 150000 + "\n" * 100 + "ring[0] = next;\n"

    def packet(self, path):
        url = f"https://raw.githubusercontent.com/{self.repo}/{self.sha}/{path}"
        return (
            {
                "repo": self.repo,
                "sources": [{"url": url, "start_line": 1, "end_line": 80}],
            },
            {"commit": self.sha, "files": [path]},
            url,
        )

    def requests(self, path, raw):
        packet, snapshot, _ = self.packet(path)
        return reference_requests(
            packet, snapshot, {"next_check": "references(ring)"}, lambda *args: raw
        )

    def test_all_native_suffixes_reuse_source_budget(self):
        for suffix in ("c", "cc", "cpp", "cxx", "h", "hh", "hpp", "hxx", "cu", "cuh"):
            with self.subTest(suffix=suffix):
                path = "src/kernel." + suffix
                self.assertEqual(reference_cache_limit(path), RAW_LIMIT)
                self.assertEqual(
                    self.requests(path, self.raw),
                    [{"path": path, "start": 93, "max_lines": 80}],
                )

    def test_cached_accessor_and_selected_window_never_fetch(self):
        path = "src/kernel.cu"
        packet, snapshot, url = self.packet(path)
        with tempfile.TemporaryDirectory() as directory:
            reader = PublicContext(Path(directory))
            with (
                patch.object(
                    reader, "_load", return_value={"url": url, "text": self.raw}
                ),
                patch.object(
                    reader, "_read", side_effect=AssertionError("must not fetch")
                ),
                patch.object(reader, "snapshot", return_value=snapshot),
            ):
                requests = reference_requests(
                    packet,
                    snapshot,
                    {"next_check": "references(ring)"},
                    reader.cached_source_text,
                )
                self.assertEqual(len(requests), 1)
                window = reader.source(self.repo, self.sha, **requests[0])
                self.assertIn("ring[0] = next;", window["text"])
                self.assertLessEqual(len(window["text"].splitlines()), 80)
                self.assertTrue(window["truncated"])

    def test_byte_limit_cache_identity_and_unsupported_syntax_remain_bounded(self):
        path = "src/kernel.cu"
        _, _, url = self.packet(path)
        exact = "ring();\n//" + "x" * (RAW_LIMIT - 10)
        self.assertEqual(len(exact.encode()), RAW_LIMIT)
        self.assertEqual(
            len(self.requests(path, "\n" * 100 + exact[: RAW_LIMIT - 100])), 1
        )
        with tempfile.TemporaryDirectory() as directory:
            reader = PublicContext(Path(directory))
            with patch.object(
                reader, "_load", return_value={"url": url, "text": exact}
            ):
                self.assertEqual(
                    reader.cached_source_text(self.repo, self.sha, path), exact
                )
            for raw, cached_url in (
                (exact + "x", url),
                ("界" * 333334, url),
                (self.raw, url.replace(self.sha, "b" * 40)),
            ):
                with (
                    self.subTest(size=len(raw)),
                    patch.object(
                        reader, "_load", return_value={"url": cached_url, "text": raw}
                    ),
                ):
                    self.assertIsNone(
                        reader.cached_source_text(self.repo, self.sha, path)
                    )
        for raw in (
            exact + "x",
            "界" * 333334,
            'R"(ring)"; ring();',
            "/* ring",
            "ring\x00",
        ):
            self.assertEqual(self.requests(path, raw), [])

    def test_javascript_budget_and_two_window_cap_are_unchanged(self):
        for suffix in ("js", "mjs", "cjs", "ts"):
            self.assertEqual(reference_cache_limit("src/kernel." + suffix), 131072)
            self.assertEqual(self.requests("src/kernel." + suffix, self.raw), [])
        self.assertEqual(reference_cache_limit("src/kernel.py"), RAW_LIMIT)
        raw = self.raw + "\n" * 200 + "ring();\n" + "\n" * 200 + "ring();\n"
        requests = self.requests("src/kernel.cu", raw)
        self.assertEqual(len(requests), 2)
        self.assertTrue(all(item["max_lines"] == 80 for item in requests))


if __name__ == "__main__":
    unittest.main()
