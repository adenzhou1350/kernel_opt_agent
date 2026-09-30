"""Offline generated-variant context selection; no model, network or native code."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_generated_context import contract_requests

COMMIT = "a" * 40
MODULE = "pack_0123456789abcdef"
SOURCE = f"package/feature/csrc/sm_103a/{MODULE}_binding.cu"


class ContractRequestTests(unittest.TestCase):
    def setUp(self):
        self.packet = {
            "repo": "owner/repo",
            "sources": [
                {
                    "url": f"https://raw.githubusercontent.com/owner/repo/{COMMIT}/{SOURCE}"
                }
            ],
        }
        self.snapshot = {
            "files": [
                SOURCE,
                "package/feature/cake_jit.py",
                "package/feature/README.md",
                "package/feature/csrc/README.md",
                "unrelated/registry.py",
            ]
        }

    def test_nearest_observed_registry_and_its_contract_are_bounded(self):
        requests = contract_requests(self.packet, self.snapshot)
        self.assertEqual(
            [r["path"] for r in requests],
            ["package/feature/cake_jit.py", "package/feature/README.md"],
        )
        self.assertEqual(requests[0]["exact_hint"], f': "{MODULE}"')
        self.assertEqual(requests[0]["max_lines"], 80)
        self.assertEqual(requests[1]["start"], 1)
        self.snapshot["files"].remove("package/feature/README.md")
        self.assertEqual(len(contract_requests(self.packet, self.snapshot)), 1)

    def test_ambiguous_registry_does_not_guess(self):
        self.snapshot["files"].append("package/feature/another_jit.py")
        self.assertEqual(contract_requests(self.packet, self.snapshot), [])

    def test_foreign_mutable_unobserved_and_unsafe_paths_do_not_fetch(self):
        original = self.packet["sources"][0]["url"]
        for url in (
            original.replace("owner/repo/", "foreign/repo/"),
            original.replace(COMMIT, "main"),
            original + "?query=x",
            original + "#anchor",
            original.replace("https:", "http:"),
            original.replace("package/feature/", "../feature/"),
        ):
            with self.subTest(url=url):
                self.packet["sources"][0]["url"] = url
                self.assertEqual(contract_requests(self.packet, self.snapshot), [])
        self.packet["sources"][0]["url"] = original
        self.snapshot["files"].remove(SOURCE)
        self.assertEqual(contract_requests(self.packet, self.snapshot), [])

    def test_normal_cuda_and_missing_registry_leave_normal_search_intact(self):
        self.snapshot["files"] = [SOURCE, "unrelated/registry.py"]
        self.assertEqual(contract_requests(self.packet, self.snapshot), [])
        path = "package/feature/csrc/handwritten_kernel.cu"
        self.snapshot["files"] = [path, "package/feature/cake_jit.py"]
        self.packet["sources"][0]["url"] = (
            f"https://raw.githubusercontent.com/owner/repo/{COMMIT}/{path}"
        )
        self.assertEqual(contract_requests(self.packet, self.snapshot), [])


if __name__ == "__main__":
    unittest.main()
