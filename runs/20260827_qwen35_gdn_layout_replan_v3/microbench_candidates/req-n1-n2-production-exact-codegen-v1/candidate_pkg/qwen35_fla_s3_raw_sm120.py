"""Frozen sequence dispatch for the production packed-K S3 raw main."""

from __future__ import annotations

from .qwen35_fla_s3_long_raw_sm120 import S3PackedWorkspaceDecayRawKernelSm120
from .qwen35_fla_s3_short_raw_sm120 import S3PackedEpiW16RawKernelSm120


def build_qwen35_fla_s3_raw_stage(
    sequence: int,
    dtype,
    cu_seqlens_dtype,
    *,
    candidate_id: str,
):
    if not 1 <= sequence <= 1024:
        raise ValueError(f"unqualified S3 sequence {sequence}")
    kernel_class = (
        S3PackedEpiW16RawKernelSm120
        if sequence <= 640
        else S3PackedWorkspaceDecayRawKernelSm120
    )
    if candidate_id not in ("C0", "C1", "C2"):
        raise ValueError(f"unqualified candidate_id {candidate_id!r}")
    return kernel_class(
        dtype,
        cu_seqlens_dtype,
        causal_qk_schedule=(candidate_id in ("C1", "C2")),
        causal_scorev_schedule=(candidate_id == "C2"),
    )


__all__ = ["build_qwen35_fla_s3_raw_stage"]
