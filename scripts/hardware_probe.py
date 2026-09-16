"""Read-only, standard-library NVIDIA inventory; no CUDA context is created.

This snapshot is metadata, not current idle authorization, calibration, or proof
of hardware performance. Only NVIDIA is implemented. No compiler, framework,
package installer, or GPU workload is invoked, and throughput is not inferred.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import math
import re
import shutil
import subprocess


TIMEOUT_SECONDS = 2
TOOLS = ("nvidia-smi", "nvcc", "ptxas", "nvdisasm", "cuobjdump", "ncu", "nsys")
# Query names map to explicitly unit-labelled output keys. Optional capabilities
# vary across nvidia-smi versions and devices, so one failure must not hide GPUs.
OPTIONAL_FIELDS = {
    "memory.total": "memory_total_mib",
    "memory.used": "memory_used_mib",
    "utilization.gpu": "gpu_utilization_percent",
    "pci.bus_id": "pci_bus_id",
    "driver_version": "driver_version",
    "compute_cap": "compute_capability",
    "clocks.current.sm": "sm_clock_current_mhz",
    "clocks.max.sm": "sm_clock_max_mhz",
    "clocks.current.memory": "memory_clock_current_mhz",
    "clocks.max.memory": "memory_clock_max_mhz",
    "power.draw": "power_draw_w",
    "power.limit": "power_limit_w",
    "power.min_limit": "power_min_limit_w",
    "power.max_limit": "power_max_limit_w",
}
UNAVAILABLE_VALUES = {"", "n/a", "[n/a]", "not supported", "[not supported]", "unknown"}


def _value(field: str, raw: str):
    value = raw.strip()
    if value.lower() in UNAVAILABLE_VALUES:
        return None
    if field in ("pci.bus_id", "driver_version"):
        return value
    if field == "compute_cap":
        return value if re.fullmatch(r"\d+\.\d+", value) else None
    try:
        number = float(value)
    except ValueError:
        return None
    if not math.isfinite(number) or number < 0:
        return None
    if field == "utilization.gpu" and number > 100:
        return None
    return number


def inspect_nvidia() -> dict:
    """Return observations and explicit unknowns without acquiring a device.

    Queries time out after two seconds. At most one inventory query, one bulk
    metadata query, and one fallback query per optional field are attempted.
    A timeout or execution failure stops further queries. Every metadata row
    must match both the reported index and UUID; CSV order is never an identity.
    """
    tools = {name: shutil.which(name) for name in TOOLS}
    result = {
        "profile_version": 1,
        "status": "UNAVAILABLE",
        "vendor": "NVIDIA",
        "devices": [],
        "tools": tools,
        "unknowns": [
            "Only NVIDIA inventory is implemented; other vendors were not inspected.",
            "Metadata does not establish current idle authorization, calibration, or performance.",
        ],
        "evidence": {
            "commands": [],
            "captured_at": datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
        },
    }
    unknowns = result["unknowns"]
    smi = tools["nvidia-smi"]
    if not smi:
        unknowns.append(
            "nvidia-smi executable not found on PATH; NVIDIA inventory unavailable."
        )
        return result

    def query(fields):
        argv = [smi, "--query-gpu=" + ",".join(fields), "--format=csv,noheader,nounits"]
        evidence = {"argv": argv, "returncode": None}
        result["evidence"]["commands"].append(evidence)
        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            evidence["error"] = f"{type(error).__name__}: {error}"
            return None, evidence["error"], True
        evidence["returncode"] = completed.returncode
        if completed.returncode:
            evidence["error"] = (
                f"nvidia-smi exited {completed.returncode}: "
                + (completed.stderr.strip() or completed.stdout.strip())[:1000]
            )
            return None, evidence["error"], False
        try:
            rows = list(
                csv.reader(
                    completed.stdout.splitlines(), skipinitialspace=True, strict=True
                )
            )
        except csv.Error as error:
            evidence["error"] = f"Malformed nvidia-smi CSV: {error}"
            return None, evidence["error"], False
        return rows, None, False

    rows, error, _ = query(["index", "name", "uuid"])
    if rows is None:
        unknowns.append(
            "Required identity fields index,name,uuid unavailable: " + error
        )
        return result
    devices = {}
    indices, uuids = set(), set()
    for row in rows:
        if not row:
            continue
        values = [value.strip() for value in row]
        if (
            len(values) != 3
            or not values[0].isascii()
            or not values[0].isdigit()
            or any(value.lower() in UNAVAILABLE_VALUES for value in values[1:])
        ):
            unknowns.append(f"Malformed required identity row ignored: {row!r}")
            continue
        index, name, uuid = int(values[0]), values[1], values[2]
        if index in indices or uuid in uuids:
            unknowns.append(f"Duplicate device index or UUID ignored: {index}, {uuid}")
            continue
        device = {"index": index, "name": name, "uuid": uuid}
        device.update({key: None for key in OPTIONAL_FIELDS.values()})
        devices[(index, uuid)] = device
        indices.add(index)
        uuids.add(uuid)
    result["devices"] = sorted(devices.values(), key=lambda device: device["index"])
    if not devices:
        unknowns.append("No valid NVIDIA device identity was reported.")
        return result
    result["status"] = "OBSERVED"

    def apply_rows(rows, fields):
        seen = set()
        for row in rows:
            if not row:
                continue
            values = [value.strip() for value in row]
            if (
                len(values) != len(fields) + 2
                or not values[0].isascii()
                or not values[0].isdigit()
            ):
                unknowns.append(f"Malformed optional metadata row ignored: {row!r}")
                continue
            identity = (int(values[0]), values[1])
            if identity not in devices or identity in seen:
                unknowns.append(
                    f"Unmatched or duplicate metadata identity ignored: {identity!r}"
                )
                continue
            seen.add(identity)
            for field, raw in zip(fields, values[2:]):
                parsed = _value(field, raw)
                devices[identity][OPTIONAL_FIELDS[field]] = parsed
                if parsed is None:
                    unknowns.append(
                        f"GPU {identity[0]} ({identity[1]}) {field} unavailable or malformed: {raw!r}"
                    )
        for identity in devices.keys() - seen:
            unknowns.append(
                f"GPU {identity[0]} ({identity[1]}) missing metadata fields: {','.join(fields)}"
            )

    fields = list(OPTIONAL_FIELDS)
    rows, error, fatal = query(["index", "uuid", *fields])
    if rows is not None:
        apply_rows(rows, fields)
    elif fatal:
        unknowns.append(
            "Optional metadata unavailable; further queries stopped: " + error
        )
    else:
        for position, field in enumerate(fields):
            rows, error, fatal = query(["index", "uuid", field])
            if rows is not None:
                apply_rows(rows, [field])
            else:
                unknowns.append(f"Optional field {field} unavailable: {error}")
            if fatal:
                unknowns.append(
                    "Further optional queries stopped; unqueried fields: "
                    + ",".join(fields[position + 1 :])
                )
                break
    return result
