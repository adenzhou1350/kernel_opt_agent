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

    def test_generic_moe_module_prefers_component_over_rust_renderer_basename(self):
        source = "vllm/model_executor/layers/fused_moe/utils.py"
        related = "tests/kernels/moe/utils.py"
        files = ["rust/src/chat/src/renderer/test_utils.rs",
                 "vllm/model_executor/layers/quantization/utils/marlin_utils_test.py",
                 "tests/distributed/test_utils.py",
                 "tests/model_executor/test_utils.py", related]
        for candidates in (files, list(reversed(files))):
            self.assertEqual(companion_source_paths(source, candidates), ([related], None))

    def test_generic_component_test_can_beat_exact_unrelated_name(self):
        source = "src/package/attention/helpers.py"
        related = "tests/attention/test_helpers_layout.py"
        unrelated = "rust/src/chat/test_helpers.rs"
        self.assertEqual(companion_source_paths(source, [unrelated, related]), ([related], None))

    def test_same_component_cross_language_binding_is_not_banned(self):
        source = "native/moe/utils.cpp"
        binding_test = "native/moe/tests/test_utils.py"
        distant = "tests/test_utils.cpp"
        self.assertEqual(companion_source_paths(source, [distant, binding_test]),
                         ([binding_test], None))

    def test_generic_language_affinity_groups_related_source_suffixes(self):
        for source, related, unrelated in (
            ("src/utils.cpp", "tests/utils_test.cu", "tests/test_utils.py"),
            ("src/helpers.ts", "tests/helpers_syntax.test.jsx", "tests/test_helpers.rs"),
        ):
            with self.subTest(source=source):
                self.assertEqual(companion_source_paths(source, [unrelated, related]),
                                 ([related], None))

    def test_generic_foreign_language_only_candidate_remains_an_unproven_hint(self):
        source, candidate = "src/utils.cpp", "tests/test_utils.py"
        self.assertEqual(companion_source_paths(source, [candidate]), ([candidate], None))

    def test_nongeneric_module_keeps_existing_exact_name_precedence(self):
        source = "native/engine/routing.py"
        exact = "tests/test_routing.rs"
        partial = "native/engine/tests/test_routing_lifecycle.py"
        self.assertEqual(companion_source_paths(source, [partial, exact]), ([exact], None))


if __name__ == "__main__":
    unittest.main()
