"""Bounded CUDA Driver API metadata inventory, requiring only the standard library.

No context, allocation, compilation or GPU workload is requested. Device limits
and nominal clocks are observations, not measured bandwidth or throughput.
"""

from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid


TIMEOUT_SECONDS = 10
ATTRIBUTE_SOURCE = (
    "https://docs.nvidia.com/cuda/archive/12.5.1/"
    "cuda-driver-api/group__CUDA__TYPES.html"
)
DEVICE_SOURCE = (
    "https://docs.nvidia.com/cuda/archive/12.5.1/"
    "cuda-driver-api/group__CUDA__DEVICE.html"
)
# CUdevice_attribute declarations in the official, versioned reference above.
# These are DRIVER enum IDs; similarly named runtime enum IDs can differ.
ATTRIBUTES = {
    "max_threads_per_block": (1, "MAX_THREADS_PER_BLOCK"),
    "max_block_dim_x": (2, "MAX_BLOCK_DIM_X"),
    "max_block_dim_y": (3, "MAX_BLOCK_DIM_Y"),
    "max_block_dim_z": (4, "MAX_BLOCK_DIM_Z"),
    "max_grid_dim_x": (5, "MAX_GRID_DIM_X"),
    "max_grid_dim_y": (6, "MAX_GRID_DIM_Y"),
    "max_grid_dim_z": (7, "MAX_GRID_DIM_Z"),
    "shared_memory_per_block_bytes": (8, "MAX_SHARED_MEMORY_PER_BLOCK"),
    "warp_size": (10, "WARP_SIZE"),
    "registers_per_block": (12, "MAX_REGISTERS_PER_BLOCK"),
    "clock_rate_khz": (13, "CLOCK_RATE"),
    "sm_count": (16, "MULTIPROCESSOR_COUNT"),
    "concurrent_kernels": (31, "CONCURRENT_KERNELS"),
    "memory_clock_rate_khz": (36, "MEMORY_CLOCK_RATE"),
    "memory_bus_width_bits": (37, "GLOBAL_MEMORY_BUS_WIDTH"),
    "l2_cache_bytes": (38, "L2_CACHE_SIZE"),
    "max_threads_per_sm": (39, "MAX_THREADS_PER_MULTIPROCESSOR"),
    "async_engine_count": (40, "ASYNC_ENGINE_COUNT"),
    "unified_addressing": (41, "UNIFIED_ADDRESSING"),
    "compute_capability_major": (75, "COMPUTE_CAPABILITY_MAJOR"),
    "compute_capability_minor": (76, "COMPUTE_CAPABILITY_MINOR"),
    "shared_memory_per_sm_bytes": (81, "MAX_SHARED_MEMORY_PER_MULTIPROCESSOR"),
    "registers_per_sm": (82, "MAX_REGISTERS_PER_MULTIPROCESSOR"),
    "cooperative_launch": (95, "COOPERATIVE_LAUNCH"),
    "shared_memory_per_block_optin_bytes": (97, "MAX_SHARED_MEMORY_PER_BLOCK_OPTIN"),
    "max_blocks_per_sm": (106, "MAX_BLOCKS_PER_MULTIPROCESSOR"),
    "cluster_launch": (120, "CLUSTER_LAUNCH"),
}


class CUuuid(ctypes.Structure):
    _fields_ = [("bytes", ctypes.c_ubyte * 16)]


def _empty() -> dict:
    return {
        "status": "UNAVAILABLE",
        "driver_version": None,
        "devices": [],
        "environment": {"CUDA_VISIBLE_DEVICES": os.environ.get("CUDA_VISIBLE_DEVICES")},
        "evidence": {
            "api": "CUDA Driver API",
            "attribute_ids": {key: item[0] for key, item in ATTRIBUTES.items()},
            "attribute_names": {
                key: "CU_DEVICE_ATTRIBUTE_" + item[1]
                for key, item in ATTRIBUTES.items()
            },
            "attribute_source": ATTRIBUTE_SOURCE,
            "device_source": DEVICE_SOURCE,
        },
        "unknowns": [
            "CUDA ordinals may be remapped by visibility settings; do not join other inventories by ordinal.",
            "Clocks are nominal Driver API metadata (core typical, memory peak), not live clocks or measured performance.",
            "Registers are counts of 32-bit registers. Limits do not establish kernel occupancy, bandwidth or throughput.",
        ],
    }


def _load_driver():
    if sys.platform == "win32":
        # LOAD_LIBRARY_SEARCH_SYSTEM32 prevents loading a local nvcuda.dll.
        return ctypes.WinDLL("nvcuda.dll", winmode=0x00000800), "System32/nvcuda.dll"
    if sys.platform.startswith("linux"):
        errors = []
        for name in ("libcuda.so.1", "/usr/lib/wsl/lib/libcuda.so.1"):
            try:
                return ctypes.CDLL(name), name
            except OSError as error:
                errors.append(str(error))
        raise OSError("; ".join(errors))
    raise OSError(f"CUDA driver loading is not implemented for {sys.platform}")


def _bind(driver, name, argtypes):
    function = getattr(driver, name, None)
    if function is not None:
        function.argtypes = argtypes
        function.restype = ctypes.c_int
    return function


def worker() -> dict:
    """Query driver metadata in the child process; call inspect_cuda for a deadline."""
    result = _empty()
    unknowns = result["unknowns"]
    try:
        driver, library = _load_driver()
    except (OSError, AttributeError) as error:
        unknowns.append(f"CUDA driver unavailable: {type(error).__name__}: {error}")
        return result
    result["evidence"]["library"] = library
    if sys.platform.startswith("linux"):
        try:
            maps = Path("/proc/self/maps").read_text(encoding="utf-8", errors="replace")
            result["evidence"]["loaded_library_paths"] = sorted(
                {
                    line.split()[-1]
                    for line in maps.splitlines()
                    if "/" in line and "libcuda" in line.split()[-1]
                }
            )
        except OSError:
            result["evidence"]["loaded_library_paths"] = None
    pointer_int = ctypes.POINTER(ctypes.c_int)
    signatures = {
        "cuInit": [ctypes.c_uint],
        "cuDriverGetVersion": [pointer_int],
        "cuDeviceGetCount": [pointer_int],
        "cuDeviceGet": [pointer_int, ctypes.c_int],
        "cuDeviceGetName": [ctypes.POINTER(ctypes.c_char), ctypes.c_int, ctypes.c_int],
        "cuDeviceGetUuid_v2": [ctypes.POINTER(CUuuid), ctypes.c_int],
        "cuDeviceGetUuid": [ctypes.POINTER(CUuuid), ctypes.c_int],
        "cuDeviceGetPCIBusId": [
            ctypes.POINTER(ctypes.c_char),
            ctypes.c_int,
            ctypes.c_int,
        ],
        "cuDeviceTotalMem_v2": [ctypes.POINTER(ctypes.c_size_t), ctypes.c_int],
        "cuDeviceGetAttribute": [pointer_int, ctypes.c_int, ctypes.c_int],
    }
    functions = {name: _bind(driver, name, args) for name, args in signatures.items()}

    def call(name, *args, field=None):
        label = f"{field}: {name}" if field else name
        function = functions[name]
        if function is None:
            unknowns.append(f"{label} unavailable (driver symbol missing).")
            return False
        try:
            error = function(*args)
        except (OSError, ctypes.ArgumentError) as error:
            unknowns.append(f"{label} failed: {type(error).__name__}: {error}")
            return False
        if error != 0:
            unknowns.append(f"{label} failed with CUresult {error}.")
            return False
        return True

    if not call("cuInit", 0):
        return result
    version = ctypes.c_int()
    if call("cuDriverGetVersion", ctypes.byref(version)):
        result["driver_version"] = version.value
    count = ctypes.c_int()
    if not call("cuDeviceGetCount", ctypes.byref(count)):
        return result
    if count.value <= 0:
        unknowns.append(f"CUDA reported no visible devices (count={count.value}).")
        return result
    for ordinal in range(count.value):
        handle = ctypes.c_int()
        prefix = f"CUDA ordinal {ordinal}"
        if not call("cuDeviceGet", ctypes.byref(handle), ordinal, field=prefix):
            continue
        device = {
            "ordinal": ordinal,
            "name": "",
            "uuid": None,
            "uuid_api": None,
            "pci_bus_id": None,
            "memory_total_bytes": None,
            "attributes": {key: None for key in ATTRIBUTES},
        }
        result["devices"].append(device)
        name = ctypes.create_string_buffer(256)
        if call("cuDeviceGetName", name, len(name), handle, field=prefix):
            device["name"] = name.value.decode("utf-8", errors="replace")
        uuid_api = "cuDeviceGetUuid_v2"
        if functions[uuid_api] is None:
            uuid_api = "cuDeviceGetUuid"
            unknowns.append(
                f"{prefix}: cuDeviceGetUuid_v2 unavailable; trying legacy cuDeviceGetUuid. "
                "Legacy UUID does not establish a unique MIG compute-instance identity."
            )
        raw_uuid = CUuuid()
        device["uuid_api"] = uuid_api
        uuid_ok = call(uuid_api, ctypes.byref(raw_uuid), handle, field=prefix)
        if uuid_ok:
            device["uuid"] = "GPU-" + str(uuid.UUID(bytes=bytes(raw_uuid.bytes)))
        pci = ctypes.create_string_buffer(32)
        if call("cuDeviceGetPCIBusId", pci, len(pci), handle, field=prefix):
            device["pci_bus_id"] = pci.value.decode("ascii", errors="replace")
        memory = ctypes.c_size_t()
        if call("cuDeviceTotalMem_v2", ctypes.byref(memory), handle, field=prefix):
            device["memory_total_bytes"] = memory.value
        for key, (attribute, _) in ATTRIBUTES.items():
            value = ctypes.c_int()
            if call(
                "cuDeviceGetAttribute",
                ctypes.byref(value),
                attribute,
                handle,
                field=f"{prefix} {key} (attribute {attribute})",
            ):
                device["attributes"][key] = value.value
    if result["devices"]:
        result["status"] = "OBSERVED"
    return result


def inspect_cuda() -> dict:
    """Return an isolated inventory; a stalled or crashing driver cannot stall callers."""
    result = _empty()
    argv = [sys.executable, "-B", str(Path(__file__).resolve()), "--worker"]
    command = {"argv": argv, "timeout_seconds": TIMEOUT_SECONDS, "returncode": None}
    result["evidence"]["worker"] = command
    try:
        completed = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_SECONDS,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        result["unknowns"].append(
            f"CUDA worker unavailable: {type(error).__name__}: {error}"
        )
        return result
    command["returncode"] = completed.returncode
    if completed.returncode:
        result["unknowns"].append(
            f"CUDA worker exited {completed.returncode}: {completed.stderr.strip()[:1000]}"
        )
        return result
    try:
        observed = json.loads(completed.stdout)
        if (
            not isinstance(observed, dict)
            or observed.get("status") not in ("OBSERVED", "UNAVAILABLE")
            or not isinstance(observed.get("devices"), list)
            or not isinstance(observed.get("evidence"), dict)
            or not isinstance(observed.get("unknowns"), list)
        ):
            raise ValueError("unexpected CUDA worker result shape")
    except (ValueError, TypeError) as error:
        result["unknowns"].append(f"Invalid CUDA worker output: {error}")
        return result
    observed["evidence"]["worker"] = command
    return observed


if __name__ == "__main__":
    print(
        json.dumps(
            worker() if sys.argv[1:] == ["--worker"] else inspect_cuda(), indent=2
        )
    )
