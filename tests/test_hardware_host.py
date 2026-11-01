"""Synthetic proc/sysfs fixtures; no real driver or host mutation."""

from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from hardware_host import inspect_host, pci_address, rdma_device_visibility  # noqa: E402


class HardwareHostTests(unittest.TestCase):
    def test_pci_normalization_does_not_drop_nonzero_domains(self):
        self.assertEqual(pci_address("00000001:Ab:02.0"), "0001:ab:02.0")
        for invalid in (None, "../03:00.0", "12340001:03:00.0", "0000:03:00.8"):
            self.assertIsNone(pci_address(invalid))

    def test_missing_platform_or_files_remain_unknown(self):
        with patch("hardware_host.rdma_device_visibility", side_effect=AssertionError("not Linux")):
            result = inspect_host([], platform="win32")
        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertEqual(result["rdma_device_visibility"]["status"], "NOT_QUERIED")
        with tempfile.TemporaryDirectory() as tmp:
            result = inspect_host(
                [{"uuid": "GPU-a", "pci_bus_id": "0000:03:00.0"}],
                platform="linux",
                proc_root=Path(tmp) / "proc",
                sys_root=Path(tmp) / "sys",
                dev_root=Path(tmp) / "dev",
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
                        dev_root=Path(tmp) / "dev",
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
                    dev_root=root / "dev",
                    platform="linux",
                )
            self.assertEqual(
                result["devices"][0]["pci_link"]["max_link_speed"], "32.0 GT/s PCIe"
            )
            self.assertIsNone(result["devices"][0]["pci_link"]["current_link_speed"])
            self.assertEqual(result["rdma_ports"][0]["rate"], "800 Gb/sec (4X XDR)")
            self.assertNotIn("bandwidth_bytes_per_second", result["rdma_ports"][0])
            # Active host ports do not imply a device mounted in this namespace.
            self.assertEqual(result["rdma_device_visibility"]["status"], "DIRECTORY_ABSENT")
            self.assertEqual(result["rdma_device_visibility"]["nodes"], [])

    def test_rdma_metadata_does_not_open_or_follow_device_entries(self):
        entries = [
            SimpleNamespace(name=name, stat=Mock(return_value=SimpleNamespace(st_mode=mode)))
            for name, mode in [("uverbs0", stat.S_IFCHR | 0o660),
                               ("link", stat.S_IFLNK | 0o777),
                               ("not-a-device", stat.S_IFREG | 0o600)]
        ]
        entries.append(SimpleNamespace(name="denied", stat=Mock(side_effect=PermissionError)))
        with patch("hardware_host.os.scandir") as scan, patch(
            "builtins.open", side_effect=AssertionError("device must not be opened")
        ):
            scan.return_value.__enter__.return_value = iter(entries)
            result = rdma_device_visibility(Path("/synthetic/dev"))
        self.assertEqual(result["status"], "OBSERVED")
        kinds = {row["name"]: row["kind"] for row in result["nodes"]}
        self.assertEqual(kinds, {"uverbs0": "character_device", "link": "symlink",
                                 "not-a-device": "other", "denied": "unavailable"})
        for entry in entries:
            entry.stat.assert_called_once_with(follow_symlinks=False)
        self.assertIn("transport remain untested", result["boundary"])

    def test_rdma_unavailable_is_not_reported_as_absent(self):
        for error in [PermissionError, NotADirectoryError]:
            with self.subTest(error=error), patch("hardware_host.os.scandir", side_effect=error):
                result = rdma_device_visibility(Path("/synthetic/dev"))
                self.assertEqual(result["status"], "UNAVAILABLE")
                self.assertEqual(result["error"], error.__name__)
                self.assertEqual(result["nodes"], [])

    def test_rdma_inventory_bounds_enumeration_and_reports_truncation(self):
        visited = []

        def entries():
            for index in range(1000):
                visited.append(index)
                yield SimpleNamespace(name=f"uverbs{index}", stat=Mock(
                    return_value=SimpleNamespace(st_mode=stat.S_IFCHR | 0o660)
                ))

        with patch("hardware_host.os.scandir") as scan:
            scan.return_value.__enter__.return_value = entries()
            result = rdma_device_visibility(Path("/synthetic/dev"))
        self.assertEqual(len(visited), 129)
        self.assertEqual(len(result["nodes"]), 128)
        self.assertTrue(result["truncated"])


if __name__ == "__main__":
    unittest.main()
