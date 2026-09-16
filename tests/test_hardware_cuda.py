"""Portable Driver API inventory tests; mocked calls never load a GPU driver."""

import ctypes
import importlib.util
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "hardware_cuda.py"
SPEC = importlib.util.spec_from_file_location("hardware_cuda", SCRIPT)
cuda = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cuda)


def fake_driver(count=1, failures=None):
    """A mock ABI with non-ordinal CUdevice handles and deterministic UUID bytes."""
    failures = failures or {}

    def output(pointer, value):
        pointer._obj.value = value
        return 0

    def identity(pointer, handle):
        pointer._obj.bytes[:] = bytes(range(handle.value, handle.value + 16))
        return 0

    def text_output(buffer, length, handle, pci=False):
        value = f"0000:{handle.value:02x}:00.0" if pci else f"Mock GPU {handle.value}"
        buffer.value = value.encode("ascii")
        return 0

    def attribute_output(pointer, attribute, handle):
        if attribute in failures:
            return failures[attribute]
        return output(
            pointer, 0 if attribute == 120 else 1000 + attribute + handle.value
        )

    callbacks = {
        "cuInit": lambda flags: 0,
        "cuDriverGetVersion": lambda pointer: output(pointer, 12050),
        "cuDeviceGetCount": lambda pointer: output(pointer, count),
        "cuDeviceGet": lambda pointer, ordinal: output(pointer, (8, 3)[ordinal]),
        "cuDeviceGetName": text_output,
        "cuDeviceGetUuid_v2": identity,
        "cuDeviceGetUuid": identity,
        "cuDeviceGetPCIBusId": lambda *args: text_output(*args, pci=True),
        "cuDeviceTotalMem_v2": lambda pointer, handle: output(pointer, 24 * 1024**3),
        "cuDeviceGetAttribute": attribute_output,
    }
    return SimpleNamespace(
        **{
            name: Mock(side_effect=callback)
            if name not in failures
            else Mock(return_value=failures[name])
            for name, callback in callbacks.items()
        }
    )


class HardwareCudaTests(unittest.TestCase):
    def worker(self, driver):
        with patch.object(cuda, "_load_driver", return_value=(driver, "mock-driver")):
            return cuda.worker()

    def test_inventory_uses_handles_and_records_uuid_api_and_visibility(self):
        driver = fake_driver(count=2)
        with patch.dict(cuda.os.environ, {"CUDA_VISIBLE_DEVICES": "8,3"}):
            result = self.worker(driver)
        self.assertEqual(result["status"], "OBSERVED")
        self.assertEqual(result["driver_version"], 12050)
        self.assertEqual(result["environment"], {"CUDA_VISIBLE_DEVICES": "8,3"})
        self.assertEqual([device["ordinal"] for device in result["devices"]], [0, 1])
        first, second = result["devices"]
        self.assertEqual(first["name"], "Mock GPU 8")
        self.assertEqual(second["name"], "Mock GPU 3")
        self.assertEqual(first["uuid"], "GPU-08090a0b-0c0d-0e0f-1011-121314151617")
        self.assertEqual(first["uuid_api"], "cuDeviceGetUuid_v2")
        self.assertNotEqual(first["uuid"], second["uuid"])
        self.assertEqual(first["pci_bus_id"], "0000:08:00.0")
        self.assertEqual(first["memory_total_bytes"], 24 * 1024**3)
        self.assertEqual(first["attributes"]["sm_count"], 1024)
        self.assertEqual(first["attributes"]["cluster_launch"], 0)
        self.assertEqual(
            driver.cuDeviceGetAttribute.call_count, 2 * len(cuda.ATTRIBUTES)
        )
        self.assertEqual(
            driver.cuDeviceTotalMem_v2.argtypes[0], ctypes.POINTER(ctypes.c_size_t)
        )
        driver.cuDeviceGetUuid.assert_not_called()

    def test_unavailable_driver_and_failed_initialization_are_explicit(self):
        with patch.object(cuda, "_load_driver", side_effect=OSError("driver absent")):
            result = cuda.worker()
        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertIn("driver absent", result["unknowns"][-1])
        driver = fake_driver(failures={"cuInit": 100})
        result = self.worker(driver)
        self.assertEqual(result["devices"], [])
        self.assertIn("cuInit failed with CUresult 100", result["unknowns"][-1])
        driver.cuDeviceGetCount.assert_not_called()

    def test_optional_failures_retain_other_attributes_and_devices(self):
        driver = fake_driver(failures={120: 1, 97: 801, "cuDeviceTotalMem_v2": 801})
        result = self.worker(driver)
        device = result["devices"][0]
        self.assertEqual(result["status"], "OBSERVED")
        self.assertIsNone(device["memory_total_bytes"])
        self.assertIsNone(device["attributes"]["cluster_launch"])
        self.assertIsNone(device["attributes"]["shared_memory_per_block_optin_bytes"])
        self.assertEqual(device["attributes"]["registers_per_sm"], 1090)
        self.assertTrue(
            any(
                "cluster_launch (attribute 120)" in item and "CUresult 1" in item
                for item in result["unknowns"]
            )
        )
        self.assertEqual(driver.cuDeviceGetAttribute.call_count, len(cuda.ATTRIBUTES))

    def test_missing_optional_symbol_and_driver_version_do_not_hide_devices(self):
        driver = fake_driver(failures={"cuDriverGetVersion": 801, "cuDeviceGetName": 1})
        del driver.cuDeviceGetPCIBusId
        result = self.worker(driver)
        self.assertEqual(result["status"], "OBSERVED")
        self.assertIsNone(result["driver_version"])
        self.assertIsNone(result["devices"][0]["pci_bus_id"])
        self.assertEqual(result["devices"][0]["name"], "")
        self.assertTrue(
            any(
                "cuDeviceGetPCIBusId unavailable" in item for item in result["unknowns"]
            )
        )

    def test_uuid_v1_fallback_is_explicit_and_failed_v2_is_not_replaced(self):
        driver = fake_driver()
        del driver.cuDeviceGetUuid_v2
        result = self.worker(driver)
        self.assertEqual(result["devices"][0]["uuid_api"], "cuDeviceGetUuid")
        self.assertIsNotNone(result["devices"][0]["uuid"])
        self.assertTrue(any("Legacy UUID" in item for item in result["unknowns"]))
        driver = fake_driver(failures={"cuDeviceGetUuid_v2": 801})
        result = self.worker(driver)
        self.assertIsNone(result["devices"][0]["uuid"])
        self.assertEqual(result["devices"][0]["uuid_api"], "cuDeviceGetUuid_v2")
        driver.cuDeviceGetUuid.assert_not_called()
        del driver.cuDeviceGetUuid_v2
        del driver.cuDeviceGetUuid
        result = self.worker(driver)
        self.assertIsNone(result["devices"][0]["uuid"])
        self.assertTrue(
            any("cuDeviceGetUuid unavailable" in item for item in result["unknowns"])
        )

    def test_empty_inventory_count_failure_and_device_failure(self):
        for driver in (
            fake_driver(count=0),
            fake_driver(failures={"cuDeviceGetCount": 3}),
            fake_driver(failures={"cuDeviceGet": 101}),
        ):
            with self.subTest(driver=driver):
                result = self.worker(driver)
                self.assertEqual(result["status"], "UNAVAILABLE")
                self.assertEqual(result["devices"], [])
                self.assertGreater(len(result["unknowns"]), 3)
                driver.cuDeviceGetAttribute.assert_not_called()

    def test_child_process_has_bounded_timeout_and_no_shell(self):
        expected = self.worker(fake_driver())
        completed = subprocess.CompletedProcess([], 0, json.dumps(expected), "")
        with patch.object(cuda.subprocess, "run", return_value=completed) as run:
            observed = cuda.inspect_cuda()
        self.assertEqual(observed["devices"], expected["devices"])
        self.assertEqual(
            run.call_args.args[0], [cuda.sys.executable, "-B", str(SCRIPT), "--worker"]
        )
        self.assertEqual(run.call_args.kwargs["timeout"], 10)
        self.assertFalse(run.call_args.kwargs.get("shell", False))
        self.assertEqual(run.call_args.kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(observed["evidence"]["worker"]["returncode"], 0)

    def test_child_timeout_crash_launch_error_and_invalid_json_are_unavailable(self):
        for response, message in (
            (subprocess.TimeoutExpired("worker", 10), "TimeoutExpired"),
            (OSError("interpreter absent"), "interpreter absent"),
            (
                subprocess.CompletedProcess([], -11, "", "driver crashed"),
                "driver crashed",
            ),
            (
                subprocess.CompletedProcess([], 0, "driver diagnostic", ""),
                "Invalid CUDA worker output",
            ),
            (
                subprocess.CompletedProcess([], 0, "[]", ""),
                "unexpected CUDA worker result shape",
            ),
        ):
            with self.subTest(message=message):
                kwargs = (
                    {"side_effect": response}
                    if isinstance(response, Exception)
                    else {"return_value": response}
                )
                with patch.object(cuda.subprocess, "run", **kwargs):
                    result = cuda.inspect_cuda()
                self.assertEqual(result["status"], "UNAVAILABLE")
                self.assertEqual(result["devices"], [])
                self.assertIn(message, result["unknowns"][-1])

    def test_windows_loader_is_restricted_to_system32(self):
        with (
            patch.object(cuda.sys, "platform", "win32"),
            patch.object(cuda.ctypes, "WinDLL", create=True) as loader,
        ):
            _, library = cuda._load_driver()
        loader.assert_called_once_with("nvcuda.dll", winmode=0x00000800)
        self.assertEqual(library, "System32/nvcuda.dll")

    def test_linux_loader_uses_soname_then_wsl_system_path(self):
        with (
            patch.object(cuda.sys, "platform", "linux"),
            patch.object(
                cuda.ctypes,
                "CDLL",
                side_effect=[OSError("not on loader path"), object()],
            ) as loader,
        ):
            _, library = cuda._load_driver()
        self.assertEqual(
            [call.args[0] for call in loader.call_args_list],
            ["libcuda.so.1", "/usr/lib/wsl/lib/libcuda.so.1"],
        )
        self.assertEqual(library, "/usr/lib/wsl/lib/libcuda.so.1")

    def test_attribute_ids_match_official_driver_enum_reference(self):
        # NVIDIA CUDA 12.5.1, CUdevice_attribute (not cudaDeviceAttr).
        # In particular DRIVER cluster_launch=120; do not substitute runtime IDs.
        expected = {
            "MAX_THREADS_PER_BLOCK": 1,
            "MAX_BLOCK_DIM_X": 2,
            "MAX_BLOCK_DIM_Y": 3,
            "MAX_BLOCK_DIM_Z": 4,
            "MAX_GRID_DIM_X": 5,
            "MAX_GRID_DIM_Y": 6,
            "MAX_GRID_DIM_Z": 7,
            "MAX_SHARED_MEMORY_PER_BLOCK": 8,
            "WARP_SIZE": 10,
            "MAX_REGISTERS_PER_BLOCK": 12,
            "CLOCK_RATE": 13,
            "MULTIPROCESSOR_COUNT": 16,
            "CONCURRENT_KERNELS": 31,
            "MEMORY_CLOCK_RATE": 36,
            "GLOBAL_MEMORY_BUS_WIDTH": 37,
            "L2_CACHE_SIZE": 38,
            "MAX_THREADS_PER_MULTIPROCESSOR": 39,
            "ASYNC_ENGINE_COUNT": 40,
            "UNIFIED_ADDRESSING": 41,
            "COMPUTE_CAPABILITY_MAJOR": 75,
            "COMPUTE_CAPABILITY_MINOR": 76,
            "MAX_SHARED_MEMORY_PER_MULTIPROCESSOR": 81,
            "MAX_REGISTERS_PER_MULTIPROCESSOR": 82,
            "COOPERATIVE_LAUNCH": 95,
            "MAX_SHARED_MEMORY_PER_BLOCK_OPTIN": 97,
            "MAX_BLOCKS_PER_MULTIPROCESSOR": 106,
            "CLUSTER_LAUNCH": 120,
        }
        self.assertEqual(
            {name: number for number, name in cuda.ATTRIBUTES.values()}, expected
        )
        evidence = self.worker(fake_driver())["evidence"]
        self.assertEqual(
            evidence["attribute_source"],
            "https://docs.nvidia.com/cuda/archive/12.5.1/cuda-driver-api/group__CUDA__TYPES.html",
        )
        self.assertEqual(evidence["attribute_ids"]["cluster_launch"], 120)
        self.assertEqual(
            evidence["attribute_names"]["cluster_launch"],
            "CU_DEVICE_ATTRIBUTE_CLUSTER_LAUNCH",
        )


if __name__ == "__main__":
    unittest.main()
