"""Run-local C0/C1 package for the S3 causal tile screening experiment.

Only the four files in this directory override production modules.  Relative
imports for S01, S2, post and shared helpers resolve through the appended
frozen production package path and are checked by the driver before use.
"""

from pathlib import Path


PRODUCTION_PACKAGE = Path(
    "/workspace/dance/qwen35/flashinfer/flashinfer/gdn_kernels/delta_rule_dsl"
)
if not PRODUCTION_PACKAGE.is_dir():
    raise ImportError(f"missing frozen production package: {PRODUCTION_PACKAGE}")

__path__.append(str(PRODUCTION_PACKAGE))

from .qwen35_fla_pipeline_sm120 import (  # noqa: E402,F401
    prepare_qwen35_fla_cute_pipeline_sm120,
)

__all__ = ["prepare_qwen35_fla_cute_pipeline_sm120"]
