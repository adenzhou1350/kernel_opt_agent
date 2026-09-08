"""Process-wide diagnostic wrapper for torch.cuda.Event.synchronize.

Loaded through PYTHONPATH in every vLLM process. Calls are recorded only while
the harness-owned marker exists, so model initialization and warmup are not
mixed into the measured decode interval. The wrapper preserves synchronization
semantics and is diagnostic evidence, not a performance candidate.
"""

from __future__ import annotations

import atexit
import json
import os
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path


_OUTPUT_DIR = os.environ.get("VLLM_SYNC_ATTRIBUTION_DIR")
_ACTIVE_FILE = os.environ.get("VLLM_SYNC_ATTRIBUTION_ACTIVE_FILE")
_LOCK = threading.Lock()
_STATS: dict[str, dict[str, int]] = defaultdict(
    lambda: {"calls": 0, "total_ns": 0, "min_ns": 0, "max_ns": 0}
)


def _install() -> None:
    if not _OUTPUT_DIR or not _ACTIVE_FILE:
        return
    import torch

    original = torch.cuda.Event.synchronize
    if getattr(original, "_vllm_sync_attribution", False):
        return

    def synchronize(event) -> None:
        active = Path(_ACTIVE_FILE).is_file()
        if not active:
            return original(event)
        caller = sys._getframe(1)
        key = f"{caller.f_code.co_filename}:{caller.f_lineno}:{caller.f_code.co_name}"
        started = time.perf_counter_ns()
        try:
            return original(event)
        finally:
            elapsed = time.perf_counter_ns() - started
            with _LOCK:
                item = _STATS[key]
                item["calls"] += 1
                item["total_ns"] += elapsed
                item["min_ns"] = (
                    elapsed if item["min_ns"] == 0 else min(item["min_ns"], elapsed)
                )
                item["max_ns"] = max(item["max_ns"], elapsed)

    synchronize._vllm_sync_attribution = True
    torch.cuda.Event.synchronize = synchronize


def _write() -> None:
    if not _OUTPUT_DIR:
        return
    output = Path(_OUTPUT_DIR)
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    with _LOCK:
        for callsite, item in sorted(_STATS.items()):
            rows.append({"callsite": callsite, **item})
    payload = {
        "schema_version": "vllm-event-sync-attribution-v1",
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "rows": rows,
        "total_calls": sum(row["calls"] for row in rows),
        "total_ns": sum(row["total_ns"] for row in rows),
    }
    path = output / f"event-sync-{os.getpid()}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


_install()
atexit.register(_write)
