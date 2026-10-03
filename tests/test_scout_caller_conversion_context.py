"""Offline caller-argument evidence; never execute the subject source."""

from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout
from scout_symbol_references import reference_requests


class CallerConversionTests(unittest.TestCase):
    def test_prompt_exposes_supported_languages_without_runtime_claims(self):
        self.assertIn("C-family/Python/JS/TS", kimi_scout.SYSTEM)
        self.assertIn("references(NAME)", kimi_scout.SYSTEM)
        self.assertIn("needs_context with references(CALLEE)", kimi_scout.SYSTEM)
        self.assertIn(
            "do not resolve bindings or prove reachability", kimi_scout.SYSTEM
        )

    def test_unseen_caller_conversion_replaces_invented_direct_call_evidence(self):
        repo, commit, path = "a/b", "a" * 40, "src/prepared.py"
        url = f"https://raw.githubusercontent.com/{repo}/{commit}/{path}"
        raw = (
            'raise RuntimeError("source must never execute")\n'
            "def select_program():\n    return 'kernel', {'SPLITS': 16}\n"
            "@cache\ndef load_program(program, arch, sms, defines):\n"
            "    return build(program, arch, sms, defines)\n"
            + "\n" * 200
            + "class Plan:\n    def prepare(self):\n"
            + "        program, defines = select_program()\n"
            + "        return load_program(\n"
            + "            program, arch, sms, tuple(sorted(defines.items()))\n"
            + "        )\n"
        )
        packet = {
            "repo": repo,
            "sources": [
                {
                    "url": url,
                    "start_line": 1,
                    "end_line": 8,
                    "text": "selector and loader",
                }
            ],
        }
        snapshot = {"commit": commit, "files": [path]}
        lookup = Mock(return_value=raw)
        requests = reference_requests(
            packet,
            snapshot,
            {
                "decision": "needs_context",
                "next_check": "Inspect references(load_program)",
            },
            lookup,
        )
        self.assertEqual(len(requests), 1)
        lookup.assert_called_once_with(repo, commit, path)
        request = requests[0]
        lines = raw.splitlines()[
            request["start"] - 1 : request["start"] - 1 + request["max_lines"]
        ]
        excerpt = "\n".join(lines)
        self.assertIn("tuple(sorted(defines.items()))", excerpt)
        self.assertLessEqual(len(lines), 80)
        self.assertNotIn("source must never execute", excerpt)
        self.assertEqual(request["path"], path)
        # The tool does not silently guess identifiers from natural-language prose.
        self.assertEqual(
            reference_requests(
                packet,
                snapshot,
                {"next_check": "look for the calling function"},
                lookup,
            ),
            [],
        )
        # A different revision cannot turn a cached match into source evidence.
        self.assertEqual(
            reference_requests(
                packet,
                {"commit": "b" * 40, "files": [path]},
                {"next_check": "references(load_program)"},
                lookup,
            ),
            [],
        )
        self.assertEqual(lookup.call_count, 1)


if __name__ == "__main__":
    unittest.main()
