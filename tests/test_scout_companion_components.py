"""Path-only context regression; no repository code or model execution."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from kimi_scout_research import companion_source_paths


class CompanionComponentsTests(unittest.TestCase):
    def test_same_basename_in_sibling_src_component_is_not_a_companion(self):
        source = "src/cron/store/read-only.ts"
        unrelated = "src/channels/plugins/read-only.test.ts"
        self.assertEqual(
            companion_source_paths(source, [source, unrelated]), ([], None)
        )

    def test_matching_component_survives_both_input_orders(self):
        source = "src/cron/store/read-only.ts"
        related = "src/cron/store/read-only.test.ts"
        unrelated = "src/channels/plugins/read-only.test.ts"
        for files in ([unrelated, related], [related, unrelated]):
            with self.subTest(files=files):
                self.assertEqual(
                    companion_source_paths(source, files), ([related], None)
                )

    def test_mirrored_test_root_is_not_excluded(self):
        source = "apps/cli/src/tui/utils/read-only.ts"
        test = "apps/cli/test/tui/utils/read-only.test.ts"
        self.assertEqual(companion_source_paths(source, [test]), ([test], None))

    def test_generic_root_test_and_root_source_are_not_excluded(self):
        for source, test in (
            ("src/cron/read-only.ts", "tests/read-only.test.ts"),
            ("src/read-only.ts", "src/cron/read-only.test.ts"),
            ("src/cron/read-only.ts", "src/read-only.test.ts"),
        ):
            with self.subTest(source=source, test=test):
                self.assertEqual(companion_source_paths(source, [test]), ([test], None))

    def test_same_component_subdirectory_is_only_a_lexical_hint(self):
        source = "src/cron/store/read-only.ts"
        test = "src/cron/integration/read-only.test.ts"
        self.assertEqual(companion_source_paths(source, [test]), ([test], None))

    def test_distinct_workspace_roots_are_not_assumed_comparable(self):
        source = "apps/cli/src/tui/read-only.ts"
        test = "apps/other/src/cron/read-only.test.ts"
        self.assertEqual(companion_source_paths(source, [test]), ([test], None))

    def test_exact_local_name_beats_partial_and_distant_matches(self):
        source = "transfer-engine/src/config.cpp"
        files = [
            "conductor/tests/config_test.cpp",
            "transfer-engine/tests/config_lifecycle_test.cpp",
            "transfer-engine/tests/config_test.cpp",
        ]
        for candidates in (files, list(reversed(files))):
            self.assertEqual(
                companion_source_paths(source, candidates), ([files[-1]], None)
            )

    def test_mirrored_subdirectory_wins_same_basename_tie(self):
        source = "apps/cli/src/tui/utils/read-only.ts"
        files = [
            "apps/cli/test/tui/components/read-only.test.ts",
            "apps/cli/test/tui/utils/read-only.test.ts",
        ]
        for candidates in (files, list(reversed(files))):
            self.assertEqual(
                companion_source_paths(source, candidates), ([files[-1]], None)
            )


if __name__ == "__main__":
    unittest.main()
