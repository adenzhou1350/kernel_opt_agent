"""Passive Linux PCI/RDMA metadata and cross-layer GPU identity observations.

No context, transfer, benchmark, installation or host mutation. Kernel and
user-space identities can legitimately differ under MIG/proxies/virtualization;
a difference needs interpretation, not automatic relabeling or bypass.
"""

from itertools import islice
import os
from pathlib import Path
import re
import stat
import sys


def pci_address(value):
    if not isinstance(value, str):
        return None
    match = re.fullmatch(
        r"([0-9a-fA-F]{4}|0000[0-9a-fA-F]{4}):([0-9a-fA-F]{2}):([0-9a-fA-F]{2})\.([0-7])",
        value,
    )
    return (
        f"{match[1][-4:]}:{match[2]}:{match[3]}.{match[4]}".lower() if match else None
    )


def read_text(path):
    try:
        with path.open(encoding="utf-8", errors="replace") as stream:
            return stream.read(65536).strip()
    except OSError:
        return None


def rdma_device_visibility(dev_root):
    """Observe the current namespace without opening a device or loading verbs."""
    directory = Path(dev_root) / "infiniband"
    result = {
        "status": "UNAVAILABLE", "directory": str(directory),
        "nodes": [], "truncated": False,
        "boundary": "Device metadata only: permissions, cgroup access, verbs enumeration, registration and effective transport remain untested. An absent standard device directory does not prove the physical host lacks RDMA.",
    }
    try:
        with os.scandir(directory) as entries:
            visible = list(islice(entries, 129))
        result["truncated"] = len(visible) > 128
        for entry in sorted(visible[:128], key=lambda item: item.name):
            row = {"name": entry.name}
            try:
                info = entry.stat(follow_symlinks=False)
                row["kind"] = (
                    "character_device" if stat.S_ISCHR(info.st_mode)
                    else "symlink" if stat.S_ISLNK(info.st_mode) else "other"
                )
                row["mode_octal"] = format(stat.S_IMODE(info.st_mode), "04o")
            except OSError as exc:
                row.update(kind="unavailable", error=type(exc).__name__)
            result["nodes"].append(row)
        result["status"] = "OBSERVED"
    except FileNotFoundError:
        result["status"] = "DIRECTORY_ABSENT"
    except OSError as exc:
        result["error"] = type(exc).__name__
    return result


def inspect_host(
    devices,
    *,
    proc_root=Path("/proc/driver/nvidia"),
    sys_root=Path("/sys"),
    dev_root=Path("/dev"),
    platform=None,
):
    result = {
        "status": "UNAVAILABLE",
        "devices": [],
        "rdma_ports": [],
        "rdma_device_visibility": {"status": "NOT_QUERIED"},
        "unknowns": [
            "PCIe/RDMA link rates are metadata, not measured payload throughput or transport reachability.",
            "Kernel/user-space identity agreement is a cross-check, not physical-device attestation; MIG, proxies and visibility may change identity scope.",
        ],
    }
    if not (platform or sys.platform).startswith("linux"):
        result["unknowns"].append(
            "Linux proc/sysfs metadata is unavailable on this platform."
        )
        return result
    result["rdma_device_visibility"] = rdma_device_visibility(dev_root)
    result["kernel_driver"] = read_text(proc_root / "version")
    for device in devices:
        bus = pci_address(device.get("pci_bus_id"))
        row = {
            "uuid": device.get("uuid"),
            "pci_bus_id": bus,
            "kernel_uuid": None,
            "identity_status": "UNAVAILABLE",
            "pci_link": {},
        }
        result["devices"].append(row)
        if bus is None:
            continue
        information_path = proc_root / "gpus" / bus / "information"
        info = read_text(information_path)
        row["kernel_information_path"] = str(information_path)
        if info is not None:
            match = re.search(r"^GPU UUID:\s*(GPU-\S+)\s*$", info, re.MULTILINE)
            location = re.search(r"^Bus Location:\s*(\S+)\s*$", info, re.MULTILINE)
            if match and location and pci_address(location[1]) == bus:
                row["kernel_uuid"] = match[1]
                if row["uuid"]:
                    row["identity_status"] = (
                        "SAME_BDF_UUID_MATCH"
                        if row["uuid"] == match[1]
                        else "DIFFERENT_IDENTITY_LAYERS"
                    )
            elif info:
                row["identity_status"] = "UNPARSED_KERNEL_RECORD"
        base = sys_root / "bus" / "pci" / "devices" / bus
        row["pci_link"] = {
            key: read_text(base / key)
            for key in (
                "current_link_speed",
                "current_link_width",
                "max_link_speed",
                "max_link_width",
                "numa_node",
            )
        }
    try:
        ports = sorted((sys_root / "class" / "infiniband").glob("*/ports/*"))
    except OSError:
        ports = []
    for port in ports[:128]:
        if not port.name.isascii() or not port.name.isdigit():
            continue
        try:
            device_path = str((port.parent.parent / "device").resolve())
        except OSError:
            device_path = None
        result["rdma_ports"].append(
            {
                "device": port.parent.parent.name,
                "port": port.name,
                "device_sysfs_path": device_path,
                **{
                    key: read_text(port / key)
                    for key in ("state", "phys_state", "rate", "link_layer")
                },
            }
        )
    if len(ports) > 128:
        result["unknowns"].append("RDMA port inventory truncated at 128 entries.")
    if any(
        row["identity_status"] == "DIFFERENT_IDENTITY_LAYERS"
        for row in result["devices"]
    ):
        result["unknowns"].append(
            "Same PCI BDF has different kernel/user-space UUIDs. Keep runtime-visible observations separate from physical identity/topology claims; do not bypass a compatibility or isolation layer."
        )
    if (
        result["kernel_driver"]
        or result["rdma_ports"]
        or any(
            row["kernel_uuid"]
            or any(value is not None for value in row["pci_link"].values())
            for row in result["devices"]
        )
    ):
        result["status"] = "OBSERVED"
    return result
