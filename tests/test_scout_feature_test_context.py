"""Literal observed-path hints only; no XPU or network qualification."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout_research as research


class FeatureTestContextTests(unittest.TestCase):
    path = "python/sglang/srt/layers/attention/xpu_backend.py"
    files = [path, "test/registered/xpu/test_intel_xpu_backend.py", "test/registered/xpu/test_xpu_encoder_decoder_varlen.py"]
    source = "1061: def _forward_encoder_decoder_attn(\n1062:     self, q, key_cache\n"
    hints = "Check _forward_encoder_decoder_attn empty rows and actual tests"

    def choose(self, files=None, source=None, hints=None):
        return research.feature_companion_test(self.path, files or self.files, self.source if source is None else source, self.hints if hints is None else hints)

    def test_unique_feature_test_in_observed_tree(self):
        self.assertEqual(self.choose(), self.files[-1])

    def test_unseen_or_unnamed_method_does_not_choose(self):
        self.assertIsNone(self.choose(source="def unrelated_function(): pass"))
        self.assertIsNone(self.choose(hints="maybe encoder_decoder"))
        self.assertIsNone(self.choose(hints="Check _forward_encoder_decoder_attn_extra"))

    def test_ambiguous_tests_abstain(self):
        self.assertIsNone(self.choose(files=self.files + ["tests/test_xpu_encoder_decoder_other.py"]))

    def test_foreign_module_and_non_test_path_do_not_match(self):
        self.assertIsNone(self.choose(files=[self.path, "tests/test_cuda_encoder_decoder.py", "examples/xpu_encoder_decoder.py"]))

    def test_generic_or_single_feature_component_does_not_match(self):
        self.assertIsNone(self.choose(source="def _forward_encoder_attn(): pass", hints="_forward_encoder_attn"))
        self.assertIsNone(research.feature_companion_test("common.py", self.files, self.source, self.hints))

    def test_followup_opt_in_replaces_not_adds_one_test_read(self):
        snapshot = {"commit": "a" * 40, "files": self.files}
        packet = {"repo": "sgl-project/sglang", "sources": [{"url": f"https://raw.githubusercontent.com/sgl-project/sglang/{snapshot['commit']}/{self.path}", "text": self.source}]}
        analysis = {"next_check": self.hints}
        old = research.followup_test_request(packet, snapshot, analysis)
        new = research.followup_test_request(packet, snapshot, analysis, feature_names=True)
        self.assertEqual(old["path"], self.files[1])
        self.assertEqual(new["path"], self.files[2])
        self.assertEqual(set(old), set(new))
        self.assertEqual(new["max_lines"], 80)
        self.assertEqual(packet["sources"][0]["text"], self.source)

    def test_same_file_second_window_can_supply_method_but_foreign_file_cannot(self):
        snapshot = {"commit": "a" * 40, "files": self.files}
        url = f"https://raw.githubusercontent.com/sgl-project/sglang/{snapshot['commit']}/{self.path}"
        packet = {"repo": "sgl-project/sglang", "sources": [{"url": url, "text": "1000: return out"}, {"url": url, "text": self.source}]}
        analysis = {"next_check": self.hints}
        self.assertEqual(research.followup_test_request(packet, snapshot, analysis, feature_names=True)["path"], self.files[-1])
        packet["sources"][1]["url"] = url.replace("xpu_backend.py", "another.py")
        self.assertEqual(research.followup_test_request(packet, snapshot, analysis, feature_names=True)["path"], self.files[1])


if __name__ == "__main__":
    unittest.main()
