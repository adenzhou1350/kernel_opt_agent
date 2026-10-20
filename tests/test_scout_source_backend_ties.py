"""Equal lexical relevance is not CPU/GPU identity; no source/model calls."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from kimi_scout_research import relevant_paths


class BackendTieTests(unittest.TestCase):
    cpu = "csrc/cpu/sgl-kernels/flash_attn.h"
    gpu = "vllm/v1/attention/backends/flash_attn.py"

    def rank(self, hints, paths=None, **kwargs):
        return relevant_paths({"files": paths or [self.cpu, self.gpu]}, hints, **kwargs)

    def test_cuda_report_does_not_choose_cpu_basename_by_alphabet(self):
        for word in ("CUDA", "GPU", "ROCm"):
            with self.subTest(word=word):
                self.assertEqual(self.rank(f"FLASH_ATTN returns wrong logits in {word} graphs"),
                                 [self.gpu, self.cpu])

    def test_cpu_report_prefers_cpu_to_explicit_gpu_directory(self):
        paths = ["csrc/cuda/flash_attn.h", "csrc/cpu/flash_attn.h"]
        self.assertEqual(self.rank("CPU flash_attn results", paths), list(reversed(paths)))

    def test_mixed_or_missing_devices_preserve_lexical_ties(self):
        for hints in ("flash_attn results", "CPU versus CUDA flash_attn results",
                      "gpu_model and cpus flash_attn results"):
            with self.subTest(hints=hints):
                self.assertEqual(self.rank(hints), [self.cpu, self.gpu])

    def test_explicit_filename_path_and_priority_override_weak_device_hint(self):
        for hints in ("CUDA flash_attn: inspect flash_attn.h", f"CUDA inspect {self.cpu}"):
            with self.subTest(hints=hints):
                self.assertEqual(self.rank(hints)[0], self.cpu)
        self.assertEqual(self.rank("CUDA flash_attn results", priority_hints=self.cpu)[0], self.cpu)

    def test_deprioritization_still_precedes_device_tie(self):
        self.assertEqual(self.rank("CUDA flash_attn results", deprioritize=[self.gpu])[0], self.cpu)

    def test_no_new_candidates_or_hardware_detection(self):
        # No CUDA/ROCm-versus-CPU hardware inference from model names, and no
        # suffix-based admission, tree expansion, platform exclusion or fetching.
        self.assertEqual(self.rank("H100 flash_attn results"), [self.cpu, self.gpu])
        self.assertEqual(self.rank("CUDA unrelated results"), [])
        self.assertEqual(self.rank("CUDA flash_attn results", paths=[self.cpu]), [self.cpu])
        before = {"files": [self.cpu, self.gpu]}
        relevant_paths(before, "CUDA flash_attn results")
        self.assertEqual(before, {"files": [self.cpu, self.gpu]})


if __name__ == "__main__":
    unittest.main()
