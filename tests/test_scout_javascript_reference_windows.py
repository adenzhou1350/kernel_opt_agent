"""Standalone, standard-library-only tests of cached JS/TS reference selection."""

from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_symbol_references import reference_requests


class JavaScriptReferenceWindowsTests(unittest.TestCase):
    def select(self, raw, *, extension="ts", seen=(241, 312), commit="a" * 40):
        repo, path = "example/project", "src/producer." + extension
        packet = {"repo": repo, "sources": [{
            "url": f"https://raw.githubusercontent.com/{repo}/{commit}/{path}",
            "start_line": seen[0], "end_line": seen[1],
        }]}
        cached = Mock(return_value=raw)
        result = reference_requests(
            packet, {"commit": "a" * 40, "files": [path]},
            {"next_check": "Inspect references(Result)"}, cached,
        )
        return result, cached

    def test_unseen_producer_not_type_declaration_or_repeated_consumer(self):
        raw = ('export type Result = { statusCode?: number };\n'
               + "\n" * 170
               + 'async function producer(): Promise<Result> {\n'
               + '  try { return await transport(); }\n'
               + '  catch (error) { return { statusCode: error.statusCode }; }\n}\n'
               + "\n" * 35
               + 'async function consumer(): Promise<Result[]> {\n'
               + '  return Promise.allSettled([producer()]);\n}\n')
        result, cached = self.select(raw)
        self.assertEqual(result, [{"path": "src/producer.ts", "start": 164, "max_lines": 80}])
        cached.assert_called_once_with("example/project", "a" * 40, "src/producer.ts")
        visible = raw.splitlines()[163:243]
        self.assertTrue(any("catch (error)" in line for line in visible))

    def test_comments_literals_templates_and_identifier_substrings_are_not_hints(self):
        raw = ('// Result\n/* Result */\nconst value = "Result";\n'
               'const template = `Result ${owner.Result}`;\n'
               'const Result$other = 1; const $Result = 2;\n')
        for extension in ("js", "mjs", "cjs", "ts"):
            self.assertEqual(self.select(raw, extension=extension, seen=(1, 1))[0], [])

    def test_unsupported_slash_complex_templates_and_unterminated_trivia_abstain(self):
        for raw in ('const r = /Result/; Result();', 'const n = a / b; Result();',
                    'const s = `${call(Result)}`; Result();',
                    'const s = `${`Result`}`; Result();',
                    '/* Result', 'const s = "unterminated; Result();'):
            self.assertEqual(self.select(raw, seen=(1, 1))[0], [])

    def test_only_exact_revision_existing_source_can_trigger_cache_lookup(self):
        result, cached = self.select('Result();', commit="b" * 40)
        self.assertEqual(result, [])
        cached.assert_not_called()


if __name__ == "__main__":
    unittest.main()
