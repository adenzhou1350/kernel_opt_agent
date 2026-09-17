"""Synthetic proc/sysfs fixtures; no real driver or host mutation."""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from hardware_host import inspect_host, pci_address  # noqa: E402


class HardwareHostTests(unittest.TestCase):
    def test_pci_normalization_does_not_drop_nonzero_domains(self):
        self.assertEqual(pci_address("00000001:Ab:02.0"), "0001:ab:02.0")
        for invalid in (None, "../03:00.0", "12340001:03:00.0", "0000:03:00.8"):
            self.assertIsNone(pci_address(invalid))

    def test_missing_platform_or_files_remain_unknown(self):
        result = inspect_host([], platform="win32")
        self.assertEqual(result["status"], "UNAVAILABLE")
        with tempfile.TemporaryDirectory() as tmp:
            result = inspect_host(
                [{"uuid": "GPU-a", "pci_bus_id": "0000:03:00.0"}],
                platform="linux",
                proc_root=Path(tmp) / "proc",
                sys_root=Path(tmp) / "sys",
            )
            self.assertEqual(result["devices"][0]["identity_status"], "UNAVAILABLE")
            self.assertTrue(
                all(v is None for v in result["devices"][0]["pci_link"].values())
            )

    def test_layer_mismatch_is_preserved_not_relabelled(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = Path(tmp) / "proc"
            info = proc / "gpus/0001:03:00.0/information"
            content = "GPU UUID: GPU-physical\nBus Location: 0001:03:00.0\n"
            devices = [{"uuid": "GPU-runtime", "pci_bus_id": "0001:03:00.0"}]

            def observe():
                with patch(
                    "hardware_host.read_text",
                    side_effect=lambda p: content if p == info else None,
                ):
                    return inspect_host(
                        devices,
                        proc_root=proc,
                        sys_root=Path(tmp) / "sys",
                        platform="linux",
                    )

            result = observe()
            row = result["devices"][0]
            self.assertEqual(row["identity_status"], "DIFFERENT_IDENTITY_LAYERS")
            self.assertEqual(row["uuid"], "GPU-runtime")
            self.assertEqual(row["kernel_uuid"], "GPU-physical")
            devices[0]["uuid"] = "GPU-physical"
            self.assertEqual(
                observe()["devices"][0]["identity_status"],
                "SAME_BDF_UUID_MATCH",
            )
            content = "GPU UUID: GPU-physical\nBus Location: 0000:03:00.0\n"
            self.assertEqual(
                observe()["devices"][0]["identity_status"],
                "UNPARSED_KERNEL_RECORD",
            )

    def test_link_metadata_retains_units_and_unknowns(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pci = root / "sys/bus/pci/devices/0000:03:00.0"
            port = root / "sys/class/infiniband/mlx5_0/ports/1"
            port.mkdir(parents=True)
            (port / "rate").write_text("800 Gb/sec (4X XDR)\n")
            (port / "state").write_text("4: ACTIVE\n")
            from hardware_host import read_text

            with patch(
                "hardware_host.read_text",
                side_effect=lambda p: (
                    "32.0 GT/s PCIe" if p == pci / "max_link_speed" else read_text(p)
                ),
            ):
                result = inspect_host(
                    [{"uuid": "GPU-a", "pci_bus_id": "0000:03:00.0"}],
                    proc_root=root / "proc",
                    sys_root=root / "sys",
                    platform="linux",
                )
            self.assertEqual(
                result["devices"][0]["pci_link"]["max_link_speed"], "32.0 GT/s PCIe"
            )
            self.assertIsNone(result["devices"][0]["pci_link"]["current_link_speed"])
            self.assertEqual(result["rdma_ports"][0]["rate"], "800 Gb/sec (4X XDR)")
            self.assertNotIn("bandwidth_bytes_per_second", result["rdma_ports"][0])


if __name__ == "__main__":
    unittest.main()
