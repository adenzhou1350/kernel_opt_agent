import importlib.util
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location(
    "torch_quick_reference",
    Path(__file__).resolve().parents[1] / "hardware/probes/torch_quick_reference.py",
)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)
DEVICE = "GPU-12345678-1234-5678-1234-567812345678"


class QuickReferenceTests(unittest.TestCase):
    def test_matched_rate_arithmetic(self):
        copy = probe.summarize([3, 1, 2], 2 * 8 * 1024**2, "bytes/s", "copy")
        self.assertEqual(copy["median_ms"], 2)
        self.assertEqual(copy["rate_per_second"], 2 * 8 * 1024**2 / 0.002)
        mm = probe.summarize([4, 2, 3], 2 * 2048**3, "FLOP/s", "mm")
        self.assertEqual(mm["rate_per_second"], 2 * 2048**3 / 0.003)
        self.assertEqual(mm["status"], "empirical_reference")
        for bad in ([], [0], [-1], [float("nan")], [float("inf")]):
            with self.assertRaises(ValueError):
                probe.summarize(bad, 1, "bytes/s", "x")

    def test_config_requires_one_exact_full_uuid_and_fresh_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            self.assertEqual(
                probe.validate_config(DEVICE, output, {"CUDA_VISIBLE_DEVICES": DEVICE}),
                (DEVICE, output),
            )
            for visible in ("0", DEVICE + "," + DEVICE, "", DEVICE.lower()):
                with self.assertRaises(ValueError):
                    probe.validate_config(
                        DEVICE, output, {"CUDA_VISIBLE_DEVICES": visible}
                    )
            for device in ("0", "GPU-12345678", DEVICE.removeprefix("GPU-")):
                with self.assertRaises(ValueError):
                    probe.validate_config(
                        device, output, {"CUDA_VISIBLE_DEVICES": device}
                    )
            output.write_text("preserve", encoding="utf-8")
            with patch.dict(os.environ, {"CUDA_VISIBLE_DEVICES": DEVICE}):
                with self.assertRaises(ValueError):
                    probe.main(["--device", DEVICE, "--output", str(output)])
            self.assertEqual(output.read_text(encoding="utf-8"), "preserve")

    def test_identity_rejection_precedes_any_allocation(self):
        for count, uuid in ((2, DEVICE), (1, ""), (1, DEVICE[:-1] + "9")):
            cuda = SimpleNamespace(
                device_count=Mock(return_value=count),
                get_device_properties=Mock(return_value=SimpleNamespace(uuid=uuid)),
            )
            torch = SimpleNamespace(cuda=cuda, full=Mock())
            with patch.dict(os.environ, {"CUDA_VISIBLE_DEVICES": DEVICE}):
                with self.assertRaises((ValueError, RuntimeError)):
                    probe.run_probe(torch)
            torch.full.assert_not_called()

    def test_warmups_and_repeats_use_synchronized_events(self):
        start, end = Mock(), Mock()
        start.elapsed_time.return_value = 2.5
        torch = SimpleNamespace(
            cuda=SimpleNamespace(
                Event=Mock(side_effect=[start, end]), synchronize=Mock()
            )
        )
        operation = Mock()
        self.assertEqual(probe.timed(torch, operation), [2.5] * 7)
        self.assertEqual(operation.call_count, 10)
        self.assertEqual(end.synchronize.call_count, 7)
        torch.cuda.synchronize.assert_called_once()


if __name__ == "__main__":
    unittest.main()
