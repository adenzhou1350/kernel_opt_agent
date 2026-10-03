import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from kimi_scout_research import relevant_paths
from scout_file_mentions import filename_mentions


class FilenameMentionsTests(unittest.TestCase):
    def test_compound_names_do_not_name_their_suffix(self):
        for suffix in ("py", "cpp", "cuh", "ts", "js"):
            with self.subTest(suffix=suffix):
                named = f"test_backend.{suffix}"
                unrelated = f"backend.{suffix}"
                snapshot = {"files": [f"src/{unrelated}", f"tests/{named}"]}
                self.assertEqual(filename_mentions(f"Error in `{named}`"), {named})
                self.assertEqual(
                    relevant_paths(snapshot, f"Error in `{named}`"), [f"tests/{named}"]
                )

    def test_real_explicit_filenames_and_observed_paths_remain_eligible(self):
        snapshot = {"files": ["src/backend.py", "tests/test_backend.py"]}
        self.assertEqual(relevant_paths(snapshot, "backend.py"), ["src/backend.py"])
        self.assertEqual(
            relevant_paths(snapshot, "tests/test_backend.py:42"),
            ["tests/test_backend.py"],
        )
        self.assertEqual(
            filename_mentions(r"C:\repo\tests\TEST_BACKEND.PY:42"), {"test_backend.py"}
        )

    def test_backup_or_longer_extension_is_not_an_explicit_match(self):
        hints = "backend.py.bak backend.tsx test_cache.py"
        self.assertEqual(
            filename_mentions(hints), {"backend.py.bak", "backend.tsx", "test_cache.py"}
        )
        snapshot = {
            "files": ["src/backend.py", "src/backend.ts", "tests/test_cache.py"]
        }
        # Weak vocabulary matches remain suggestions, not explicit file mentions.
        self.assertEqual(relevant_paths(snapshot, hints)[0], "tests/test_cache.py")

    def test_mentions_cannot_add_paths_or_escape_snapshot_exclusions(self):
        snapshot = {"files": ["src/backend.py"]}
        self.assertEqual(
            relevant_paths(snapshot, "secret.py /etc/passwd ../../secret"), []
        )
        self.assertEqual(
            relevant_paths(snapshot, "backend.py", exclude=["src/backend.py"]), []
        )
        self.assertEqual(filename_mentions("x" * 16000 + " backend.py"), set())


if __name__ == "__main__":
    unittest.main()
