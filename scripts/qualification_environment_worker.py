#!/usr/bin/env python3
"""Collect or validate a read-only preprovisioned worker runtime attestation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from schema_utils import validate_json_file


SCHEMA = "qualification_environment_worker_attestation.schema.json"
VERSION = "qualification-environment-worker-attestation-v1"
CLAIM_BOUNDARY = (
    "READ_ONLY_WORKER_RUNTIME_AND_STORAGE_ATTESTATION_NOT_ENVIRONMENT_"
    "MATERIALIZATION_GPU_OR_WORKLOAD_AUTHORIZATION"
)


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, check=False, text=True)


def tool_identity(name: str) -> dict | None:
    command = shutil.which(name)
    if not command and name == "nvcc":
        canonical_nvcc = Path("/usr/local/cuda/bin/nvcc")
        if canonical_nvcc.is_file():
            command = str(canonical_nvcc)
    if not command:
        return None
    path = Path(command).resolve()
    version = run([str(path), "--version"])
    output = (version.stdout or version.stderr).strip().splitlines()
    return {
        "path": path.as_posix(),
        "sha256": sha256_file(path),
        "version": output[0] if output else "UNKNOWN",
    }


def mount_identity(path: Path) -> dict:
    result = run(
        ["findmnt", "--json", "--target", str(path), "--output", "TARGET,SOURCE,FSTYPE"]
    )
    if result.returncode != 0:
        return {"available": False, "error": (result.stderr or result.stdout).strip()}
    value = json.loads(result.stdout)
    filesystem = value.get("filesystems", [{}])[0]
    return {
        "available": True,
        "target": filesystem.get("target"),
        "source": filesystem.get("source"),
        "fstype": filesystem.get("fstype"),
    }


def collect(worker_id: str, host_id: str, storage_root: Path) -> dict:
    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
    resolved_storage = storage_root.resolve(strict=True)
    disk = shutil.disk_usage(resolved_storage)
    import torch

    torch_path = Path(torch.__file__).resolve()
    torch_root = torch_path.parent
    native_names = (
        "_C*.so",
        "lib/libc10*.so",
        "lib/libtorch_cuda*.so",
        "lib/libtorch_cpu*.so",
    )
    native_paths = sorted(
        {
            path.resolve()
            for pattern in native_names
            for path in torch_root.glob(pattern)
        }
    )
    if not native_paths:
        raise ValueError("Torch attestation found no native libraries")
    gpu_nodes = sorted(path.as_posix() for path in Path("/dev").glob("nvidia*"))
    runtimes = sorted(
        name
        for name in ("docker", "podman", "nerdctl", "ctr", "crictl", "enroot")
        if shutil.which(name)
    )
    process_probe = run(
        [
            "nvidia-smi",
            "--query-compute-apps=gpu_uuid,pid,process_name,used_memory",
            "--format=csv,noheader,nounits",
        ]
    )
    gpu_processes = (
        sorted(
            line.strip() for line in process_probe.stdout.splitlines() if line.strip()
        )
        if process_probe.returncode == 0
        else []
    )
    python_path = Path(sys.executable).resolve()
    compiled_arches = sorted(torch.cuda.get_arch_list())
    if not compiled_arches:
        arch_flags = getattr(torch._C, "_cuda_getArchFlags", lambda: "")()
        compiled_arches = sorted(flag for flag in arch_flags.split() if flag)
    build_config = torch.__config__.show()
    return {
        "schema_version": VERSION,
        "observed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "worker_id": worker_id,
        "host_id": host_id,
        "platform": {
            "os": platform.system().lower(),
            "architecture": platform.machine(),
            "hostname": socket.gethostname(),
        },
        "storage": {
            "requested_root": storage_root.as_posix(),
            "resolved_root": resolved_storage.as_posix(),
            "free_bytes": disk.free,
            "total_bytes": disk.total,
            "mount": mount_identity(resolved_storage),
        },
        "runtime": {
            "python": {
                "version": platform.python_version(),
                "path": python_path.as_posix(),
                "sha256": sha256_file(python_path),
            },
            "torch": {
                "version": torch.__version__,
                "cuda_version": torch.version.cuda,
                "module_path": torch_path.as_posix(),
                "module_sha256": sha256_file(torch_path),
                "build_config_sha256": hashlib.sha256(
                    build_config.encode("utf-8")
                ).hexdigest(),
                "compiled_arches": compiled_arches,
                "nccl_available": torch.distributed.is_nccl_available(),
                "native_libraries": [
                    {"path": path.as_posix(), "sha256": sha256_file(path)}
                    for path in native_paths
                ],
            },
            "toolchain": {
                name: tool_identity(name) for name in ("nvcc", "gcc", "g++", "ninja")
            },
        },
        "isolation": {
            "cuda_visible_devices": os.environ["CUDA_VISIBLE_DEVICES"],
            "torch_cuda_available": torch.cuda.is_available(),
            "gpu_device_nodes": gpu_nodes,
            "nested_container_runtimes": runtimes,
            "gpu_processes": gpu_processes,
        },
        "claim_boundary": CLAIM_BOUNDARY,
    }


def validate(path: Path) -> None:
    errors = validate_json_file(path, repository_root() / "schemas" / SCHEMA)
    if errors:
        raise ValueError("invalid worker attestation: " + "; ".join(errors))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--collect", action="store_true")
    mode.add_argument("--attestation", type=Path)
    parser.add_argument("--worker-id")
    parser.add_argument("--host-id")
    parser.add_argument("--storage-root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.collect:
        missing = [
            flag
            for flag, value in (
                ("--worker-id", args.worker_id),
                ("--host-id", args.host_id),
                ("--storage-root", args.storage_root),
                ("--output", args.output),
            )
            if value is None
        ]
        if missing:
            parser.error("--collect requires " + ", ".join(missing))
        value = collect(args.worker_id, args.host_id, args.storage_root)
        args.output.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        validate(args.output)
        path = args.output
    else:
        if any(
            value is not None
            for value in (args.worker_id, args.host_id, args.storage_root, args.output)
        ):
            parser.error("--attestation does not accept collection arguments")
        validate(args.attestation)
        path = args.attestation
    print(
        json.dumps(
            {
                "status": "PASS",
                "attestation": path.as_posix(),
                "sha256": sha256_file(path),
                "gpu_authorized": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
