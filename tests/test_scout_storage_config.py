"""Keep the shipped storage frontier connected to native bindings."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import kimi_scout_research as research


class StorageConfigurationTests(unittest.TestCase):
    def test_storage_sources_include_core_and_language_bridges(self):
        config = research.configuration(ROOT / "templates/kimi-scout-research-wide.json")
        specs = {spec["repo"]: spec for spec in config["repos"]}
        sources = {
            "juicedata/juicefs": ["pkg/object/sql.go", "pkg/sync/sync.go", "sdk/java/libjfs/main.go"],
            "lancedb/lancedb": [
                "rust/lancedb/src/remote/table.rs",
                "python/python/lancedb/table.py",
                "python/src/table.rs",
                "nodejs/lancedb/table.ts",
                "nodejs/src/table.rs",
            ],
        }
        for repo, paths in sources.items():
            with self.subTest(repo=repo):
                snapshot = {"files": paths + ["docs/README.md", "tests/test_table.py"]}
                self.assertEqual(research.source_paths(snapshot, specs[repo]), sorted(paths))


if __name__ == "__main__":
    unittest.main()
