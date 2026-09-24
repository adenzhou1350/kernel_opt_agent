#!/usr/bin/env python3
"""Owner-invoked Linux GPU screen for explicitly reviewed, trusted Python code.

This is NOT a sandbox for arbitrary/unreviewed Kimi code. There is no Docker,
unshare, network isolation, or automatic delivery hook. The owner must review
all three files, including imports, resource use and absence of distributed work.
Run with the intended existing Torch/Triton interpreter. --reviewed-sha256 names
a JSON file containing exactly {"baseline": SHA256, "candidate": SHA256,
"test": SHA256}. Hashes bind the reviewed bytes, not their safety or correctness.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

MAX_FILE = 262_144
MAX_OUTPUT = 32_768
TIMEOUT = 30
MIN_HEADROOM_MIB = 6144
MAX_TORCH_ALLOC_MIB = 4096
MAX_UTILIZATION = 80
MARKER = "KIMI_GPU_VERIFY_RESULT="
SCOPE = "OWNER_REVIEWED_SINGLE_MODULE_GPU_SCREEN_NOT_UPSTREAM_SUITE"
UUID_RE = r"GPU-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
HARNESS = f"""import json, sys, unittest
import torch
expected, inputs = sys.argv[1:]
if torch.cuda.device_count() != 1:
    raise RuntimeError("expected exactly one visible CUDA device")
actual = str(getattr(torch.cuda.get_device_properties(0), "uuid", ""))
if actual.lower().removeprefix("gpu-") != expected.lower().removeprefix("gpu-"):
    raise RuntimeError("visible CUDA UUID does not match selected UUID: " + actual)
torch.cuda.set_device(0)
total_mib = torch.cuda.get_device_properties(0).total_memory / (1024 * 1024)
torch.cuda.set_per_process_memory_fraction(min(0.25, {MAX_TORCH_ALLOC_MIB} / total_mib), 0)
torch.set_num_threads(1)
sys.path.insert(0, inputs)
suite = unittest.defaultTestLoader.discover(inputs, pattern="test_subject.py")
result = unittest.TextTestRunner(verbosity=2).run(suite)
torch.cuda.synchronize()
report = dict(uuid=actual, tests_run=result.testsRun, skipped=len(result.skipped),
              failures=len(result.failures), errors=len(result.errors))
print("KIMI_GPU_VERIFY_RESULT=" + json.dumps(report), flush=True)
sys.exit(0 if result.wasSuccessful() and result.testsRun >= 2 and not result.skipped else 1)
"""


def read_regular(value):
    path = Path(value).absolute()
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("inputs must be regular files")
    for entry in (path, *path.parents):
        info = entry.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("symlink/reparse input paths are not permitted")
    fd = os.open(
        path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    )
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("inputs must be regular files")
        data = stream.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        raise ValueError("input exceeds 256 KiB")
    return data


def reviewed_inputs(paths, manifest):
    hashes = json.loads(read_regular(manifest))
    if not isinstance(hashes, dict) or set(hashes) != {"baseline", "candidate", "test"}:
        raise ValueError(
            "reviewed manifest requires exactly baseline, candidate, test hashes"
        )
    data = {}
    for name, path in paths.items():
        expected = hashes[name]
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ValueError("reviewed hashes must be lowercase SHA256 hex")
        if Path(path).suffix != ".py":
            raise ValueError("reviewed inputs must be .py files")
        data[name] = read_regular(path)
        if hashlib.sha256(data[name]).hexdigest() != expected:
            raise ValueError("reviewed SHA256 mismatch: " + name)
    return data, hashes


@contextmanager
def gpu_lock(directory, gpu_uuid):
    import fcntl

    directory = Path(directory).absolute()
    directory.mkdir(parents=True, exist_ok=True)
    if any(p.is_symlink() for p in (directory, *directory.parents)):
        raise ValueError("GPU lock path must not contain symlinks")
    gpu_uuid = "GPU-" + gpu_uuid[4:].lower()
    fd = os.open(
        directory / (gpu_uuid + ".lock"), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600
    )
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("GPU lock must be a regular file")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)  # Keep the lock inode: unlinking would split cooperating owners.


def snapshot(gpu_uuid):
    def query(arguments):
        result = subprocess.run(
            ["/usr/bin/nvidia-smi", *arguments, "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
            env={"PATH": "/usr/bin:/bin", "LANG": "C"},
        )
        return list(csv.reader(result.stdout.strip().splitlines()))

    rows = query(
        [
            "--id=" + gpu_uuid,
            "--query-gpu=uuid,index,memory.total,memory.used,utilization.gpu",
        ]
    )
    if (
        len(rows) != 1
        or len(rows[0]) != 5
        or rows[0][0].strip().lower() != gpu_uuid.lower()
    ):
        raise ValueError("nvidia-smi did not identify the exact selected GPU")
    row = [item.strip() for item in rows[0]]
    if any(not value.isdigit() for value in row[1:]):
        raise ValueError("unrecognized nvidia-smi GPU metrics")
    processes = query(["--query-compute-apps=gpu_uuid,pid,process_name"])
    if any(len(p) != 3 or not p[1].strip().isdigit() for p in processes):
        raise ValueError("unrecognized nvidia-smi process inventory")
    return {
        "uuid": row[0],
        "index": int(row[1]),
        "total_mib": int(row[2]),
        "memory_mib": int(row[3]),
        "utilization": int(row[4]),
        "processes": [p for p in processes if p[0].strip().lower() == gpu_uuid.lower()],
    }


def idle_samples(gpu_uuid):
    """Require headroom for a bounded correctness screen; sharing is allowed."""
    samples = []
    for index in range(3):
        if index:
            time.sleep(1)
        sample = snapshot(gpu_uuid)
        samples.append(sample)
        if (
            sample["total_mib"] - sample["memory_mib"] < MIN_HEADROOM_MIB
            or sample["utilization"] > MAX_UTILIZATION
        ):
            raise RuntimeError(
                "selected GPU lacks bounded headroom: " + json.dumps(sample)
            )
    return samples


def group_exists(pgid):
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False


def clean_group(process):
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            break
        try:
            process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            pass
        time.sleep(0.1)
        if not group_exists(process.pid):
            break
    process.wait(timeout=1)
    return not group_exists(process.pid)


def run_process(command, cwd, environment):
    identity = (
        {"user": 65534, "group": 65534, "extra_groups": []} if os.geteuid() == 0 else {}
    )
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        **identity,
    )
    captured = {"stdout": bytearray(), "stderr": bytearray()}
    truncated = {"stdout": False, "stderr": False}

    def drain(name, stream):
        while chunk := stream.read(4096):
            remaining = MAX_OUTPUT - len(captured[name])
            captured[name].extend(chunk[:remaining])
            truncated[name] |= len(chunk) > remaining
        stream.close()

    threads = [
        threading.Thread(target=drain, args=(name, getattr(process, name)), daemon=True)
        for name in captured
    ]
    for thread in threads:
        thread.start()
    timed_out = False
    try:
        process.wait(timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        timed_out = True
    finally:
        try:
            cleaned = clean_group(process)
        except (OSError, subprocess.TimeoutExpired):
            cleaned = False
        for thread in threads:
            thread.join(timeout=1)
    result = {
        "exit_code": process.returncode,
        "timed_out": timed_out,
        "cleanup": cleaned and not any(t.is_alive() for t in threads),
        "truncated": truncated,
    }
    result.update(
        {
            name: bytes(value).decode("utf-8", errors="replace")
            for name, value in captured.items()
        }
    )
    reports = [
        line[len(MARKER) :]
        for line in result["stdout"].splitlines()
        if line.startswith(MARKER)
    ]
    try:
        record = json.loads(reports[0]) if len(reports) == 1 else None
        valid = isinstance(record, dict) and isinstance(record.get("uuid"), str)
        valid = valid and all(
            type(record.get(k)) is int and record[k] >= 0
            for k in ("tests_run", "skipped", "failures", "errors")
        )
        result["tests"] = record if valid else None
    except (ValueError, TypeError):
        result["tests"] = None
    return result


def run_arm(data, test, gpu_uuid):
    with tempfile.TemporaryDirectory(prefix="kimi-reviewed-gpu-") as temporary:
        root = Path(temporary)
        root.chmod(0o711)
        inputs, scratch = root / "input", root / "scratch"
        inputs.mkdir()
        scratch.mkdir(mode=0o700)
        for name, content in {
            "subject.py": data,
            "test_subject.py": test,
            "harness.py": HARNESS.encode(),
        }.items():
            destination = inputs / name
            destination.write_bytes(content)
            destination.chmod(0o444)
        inputs.chmod(0o555)
        if os.geteuid() == 0:
            os.chown(scratch, 65534, 65534)
        environment = {
            "PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "HOME": str(scratch),
            "TMPDIR": str(scratch),
            "XDG_CACHE_HOME": str(scratch / "cache"),
            "TRITON_CACHE_DIR": str(scratch / "triton"),
            "TORCH_HOME": str(scratch / "torch"),
            "CUDA_CACHE_PATH": str(scratch / "cuda"),
            "CUDA_VISIBLE_DEVICES": gpu_uuid,
            "CUDA_DEVICE_ORDER": "PCI_BUS_ID",
            "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
        }
        try:
            return run_process(
                [
                    sys.executable,
                    "-I",
                    "-B",
                    str(inputs / "harness.py"),
                    gpu_uuid,
                    str(inputs),
                ],
                scratch,
                environment,
            )
        finally:
            inputs.chmod(
                0o755
            )  # Permit the owning non-root controller to remove its input copies.


def verify(args):
    if sys.platform != "linux":
        raise ValueError("explicit owner-invoked Linux tool only")
    if not re.fullmatch(UUID_RE, args.gpu_uuid):
        raise ValueError("a full GPU UUID is required")
    data, hashes = reviewed_inputs(
        {name: getattr(args, name) for name in ("baseline", "candidate", "test")},
        args.reviewed_sha256,
    )
    report = {
        "scope": SCOPE,
        "qualified": False,
        "reviewed_sha256": hashes,
        "gpu_uuid": args.gpu_uuid,
        "arms": {},
    }
    with gpu_lock(args.lock_dir, args.gpu_uuid):
        report["initial_idle"] = idle_samples(args.gpu_uuid)
        for name in ("baseline", "candidate"):
            arm = report["arms"][name] = run_arm(
                data[name], data["test"], args.gpu_uuid
            )
            try:
                arm["after_idle"] = idle_samples(args.gpu_uuid)
            except Exception as exc:  # noqa: BLE001 - Any failed inventory must stop further GPU work.
                report["stopped"] = "post-run GPU inventory uncertain: " + str(exc)
                break
            tests = arm["tests"]
            valid_tests = (
                tests is not None
                and tests["tests_run"] >= 2
                and tests["skipped"] == 0
                and tests["uuid"].lower().removeprefix("gpu-")
                == args.gpu_uuid[4:].lower()
            )
            if (
                arm["timed_out"]
                or not arm["cleanup"]
                or any(arm["truncated"].values())
                or not valid_tests
                or arm["exit_code"] not in (0, 1)
            ):
                report["stopped"] = (
                    name
                    + " execution/cleanup evidence uncertain; no further arm launched"
                )
                break
    arms = report["arms"]
    report["matched_test_count"] = (
        len(arms) == 2
        and all(a["tests"] for a in arms.values())
        and arms["baseline"]["tests"]["tests_run"]
        == arms["candidate"]["tests"]["tests_run"]
        >= 2
        and all(a["tests"]["skipped"] == 0 for a in arms.values())
    )
    report["screen_passed"] = bool(
        report["matched_test_count"]
        and "stopped" not in report
        and arms["baseline"]["exit_code"] == 1
        and arms["baseline"]["tests"]["failures"] >= 1
        and arms["baseline"]["tests"]["errors"] == 0
        and arms["candidate"]["exit_code"] == 0
        and arms["candidate"]["tests"]["failures"] == 0
        and arms["candidate"]["tests"]["errors"] == 0
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("baseline", "candidate", "test", "gpu-uuid", "reviewed-sha256"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--lock-dir", default="/workspace/kernel-opt/direct-gpu-locks")
    try:
        report = verify(parser.parse_args())
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report["screen_passed"] else 2
    except Exception as exc:  # noqa: BLE001 - CLI boundary reports failure without qualification.
        print(json.dumps({"scope": SCOPE, "qualified": False, "error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
