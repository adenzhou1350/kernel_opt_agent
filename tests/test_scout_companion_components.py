"""Path-only context regression; no repository code or model execution."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from kimi_scout_research import companion_source_paths


class CompanionComponentsTests(unittest.TestCase):
    def test_output_module_does_not_select_diffusion_outputs_generator(self):
        source = "python/sglang/srt/layers/layer_boundary/output.py"
        unrelated = "python/sglang/multimodal_gen/test/scripts/gen_diffusion_ci_outputs.py"
        self.assertEqual(companion_source_paths(source, [unrelated]), ([], None))

    def test_whole_module_token_survives_unrelated_substring_match(self):
        source = "python/sglang/srt/layers/layer_boundary/output.py"
        related = "test/registered/unit/test_layer_boundary_output.py"
        unrelated = "python/sglang/multimodal_gen/test/scripts/gen_diffusion_ci_outputs.py"
        for files in ([related, unrelated], [unrelated, related]):
            with self.subTest(files=files):
                self.assertEqual(companion_source_paths(source, files), ([related], None))

    def test_module_match_requires_name_boundaries_not_word_fragments(self):
        for source, unrelated in (
            ("src/config.py", "tests/test_configuration.py"),
            ("src/port.ts", "tests/import.test.ts"),
        ):
            with self.subTest(source=source):
                self.assertEqual(companion_source_paths(source, [unrelated]), ([], None))

    def test_module_directory_and_underscore_test_names_remain_hints(self):
        for source, related in (
            ("src/output.py", "tests/output/test_roundtrip.py"),
            ("src/config.py", "tests/test_config_lifecycle.py"),
            ("src/port.ts", "tests/port.spec.ts"),
        ):
            with self.subTest(source=source):
                self.assertEqual(companion_source_paths(source, [related]), ([related], None))

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
