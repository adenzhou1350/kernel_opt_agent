#!/usr/bin/env python3
"""Derive writable cache paths confined to one task closure."""

from __future__ import annotations

from pathlib import PurePosixPath


CACHE_ENVIRONMENT_KEYS = (
    "XDG_CACHE_HOME",
    "HF_HOME",
    "TORCH_HOME",
    "TORCHINDUCTOR_CACHE_DIR",
    "TRITON_CACHE_DIR",
    "CUDA_CACHE_PATH",
    "SGLANG_CACHE_DIR",
    "FLASHINFER_WORKSPACE_BASE",
    "TMPDIR",
)


def cpu_only_cache_environment(
    closure_root: str, storage_root: str = "/workspace"
) -> dict[str, str]:
    """Return cache paths confined to an absolute worker closure."""
    closure = PurePosixPath(closure_root)
    storage = PurePosixPath(storage_root)
    if not closure.is_absolute() or not storage.is_absolute():
        raise ValueError("closure and storage roots must be absolute POSIX paths")
    try:
        relative = closure.relative_to(storage)
    except ValueError as exc:
        raise ValueError("closure root must be inside the storage root") from exc
    if not relative.parts:
        raise ValueError("closure root must not equal the storage root")
    cache = closure / "cache"
    values = {
        "XDG_CACHE_HOME": cache / "xdg",
        "HF_HOME": cache / "huggingface",
        "TORCH_HOME": cache / "torch",
        "TORCHINDUCTOR_CACHE_DIR": cache / "torchinductor",
        "TRITON_CACHE_DIR": cache / "triton-autotune",
        "CUDA_CACHE_PATH": cache / "cuda",
        "SGLANG_CACHE_DIR": cache / "sglang",
        "FLASHINFER_WORKSPACE_BASE": cache / "flashinfer",
        "TMPDIR": closure / "tmp",
    }
    return {key: values[key].as_posix() for key in CACHE_ENVIRONMENT_KEYS}
