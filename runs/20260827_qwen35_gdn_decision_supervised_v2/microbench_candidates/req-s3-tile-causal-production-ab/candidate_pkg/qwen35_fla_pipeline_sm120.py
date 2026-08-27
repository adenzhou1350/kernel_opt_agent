"""Static production checkpoint for the Qwen3.5 SM120 FLA pipeline.

This module deliberately does not import the microbenchmark Plan wrappers.
Those wrappers bind example tensors in ``__init__`` and are unsafe when one
Harrix plan is reused by several linear-attention layers.  Instead, this file
defines the final ownership boundary:

* one Python/TVM-FFI entry;
* six caller-owned tensors are dynamic on every invocation;
* all aliases of ``mixed`` and ``zba`` are constructed inside CuTe JIT;
* S01, S2, raw S3 and gated-RMS are launched in stream order;
* only intermediate workspaces, immutable metadata and the stream are stored.

The four stage objects are injected through ``ProductionStageBundle``.  Each
object must expose a CuTe-JIT ``launch`` method with the contract documented in
README.md.  This keeps the host ABI fixed while S2's G-layout experiment and
the final production-only S2/S3 source are being frozen.

No GPU work occurs when this module is imported.  Compilation and allocation
occur only when ``prepare_qwen35_fla_pipeline_sm120`` is called.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cuda.bindings.driver as cuda_driver
import cutlass
import cutlass.cute as cute
import torch

from .custom_compile_cache import (
    KeyedCompileMixin,
    cached_compile,
    sm12x_compile_options,
)
from .varlen_helper import (
    integer_dtype_to_cutlass,
)


BT = 64
D = 128
H = 16
ZBA_WIDTH_PER_HEAD = D + 2
QKV_CHANNELS_PER_HEAD = 3 * D

__all__ = ["prepare_qwen35_fla_cute_pipeline_sm120"]


@dataclass(frozen=True, slots=True)
class ProductionStageBundle:
    """Production-only stage launchers injected into the composite JIT.

    These must be kernel/launcher objects, not construction-bound Plan
    objects.  They may retain compile-time schedule choices but must not retain
    any caller-owned torch.Tensor.
    """

    s01: Any
    s2: Any
    s3_raw: Any
    post: Any
    h_cta_major: bool
    abi_tag: str


class Qwen35FLACompositeSm120(KeyedCompileMixin):
    """One TVM-FFI host stub that issues the four production CUDA kernels."""

    def __init__(
        self,
        dtype,
        cu_seqlens_dtype,
        *,
        sequence: int,
        stages: ProductionStageBundle,
    ) -> None:
        self.dtype = dtype
        self.cu_seqlens_dtype = cu_seqlens_dtype
        self.sequence = sequence
        self.padded_sequence = ((sequence + BT - 1) // BT) * BT
        self.num_chunks = self.padded_sequence // BT
        self.s01 = stages.s01
        self.s2 = stages.s2
        self.s3_raw = stages.s3_raw
        self.post = stages.post
        self.h_cta_major = stages.h_cta_major
        self.stage_abi_tag = stages.abi_tag
        self.manual_cache_key(
            "dtype",
            "cu_seqlens_dtype",
            "sequence",
            "h_cta_major",
            "stage_abi_tag",
        )

    @cute.jit
    def __call__(
        self,
        # Six dynamic caller-owned tensors.  Keep this group first and in the
        # same order as run_fused_gated_rms.
        g_output: cute.Tensor,
        g_mixed: cute.Tensor,
        g_zba: cute.Tensor,
        g_a_log: cute.Tensor,
        g_dt_bias: cute.Tensor,
        g_norm_weight: cute.Tensor,
        # Stable plan-owned workspaces.
        g_qhat_workspace: cute.Tensor,
        g_kpack_workspace: cute.Tensor,
        g_wpack_workspace: cute.Tensor,
        g_upack_workspace: cute.Tensor,
        g_cumulative_workspace: cute.Tensor,
        g_vnew_workspace: cute.Tensor,
        g_h_workspace: cute.Tensor,
        g_raw_o_workspace: cute.Tensor,
        g_m_debug_workspace: cute.Tensor,
        g_inverse_debug_workspace: cute.Tensor,
        g_beta_debug_workspace: cute.Tensor,
        g_s2_debug_workspace: cute.Tensor,
        g_cu_seqlens: cute.Tensor,
        scale: cutlass.Float32,
        epsilon: cutlass.Float32,
        stream,
    ):
        # Harrix exposes mixed logically as [1,3HD,S], but causal-conv writes
        # it in physical [S,3HD] channel-last order.  Never use g_mixed.stride
        # to infer Q/K/V: the physical production contract below is explicit.
        qkv_row_stride = cutlass.Int32(QKV_CHANNELS_PER_HEAD * H)
        qkv_layout = cute.make_layout(
            (self.sequence, H, D),
            stride=(qkv_row_stride, D, 1),
        )
        raw_q = cute.make_tensor(g_mixed.iterator, qkv_layout)
        raw_k = cute.make_tensor(
            g_mixed.iterator + cutlass.Int32(H * D), qkv_layout
        )
        raw_v = cute.make_tensor(
            g_mixed.iterator + cutlass.Int32(2 * H * D), qkv_layout
        )
        raw_k_tma = cute.make_tensor(
            raw_k.iterator,
            cute.make_layout(
                (D, self.sequence, H),
                stride=(1, qkv_row_stride, D),
            ),
        )
        raw_v_tma = cute.make_tensor(
            raw_v.iterator,
            cute.make_layout(
                (D, self.sequence, H),
                stride=(1, qkv_row_stride, D),
            ),
        )

        # zba is contiguous [S,H*(D+2)].  beta and decay have a gap between
        # successive tokens, so neither may be flattened into a contiguous
        # one-dimensional tensor.  S01 must index beta[token,head] explicitly.
        zba_row_stride = g_zba.stride[0]
        logits_layout = cute.make_layout(
            (self.sequence, H), stride=(zba_row_stride, 1)
        )
        beta_logits = cute.make_tensor(
            g_zba.iterator + cutlass.Int32(H * D), logits_layout
        )
        decay_logits = cute.make_tensor(
            g_zba.iterator + cutlass.Int32(H * (D + 1)), logits_layout
        )
        gate_z = cute.make_tensor(
            g_zba.iterator,
            cute.make_layout(
                (D, self.sequence, H),
                stride=(1, zba_row_stride, D),
            ),
        )

        # Logical aliases for stable workspaces.  These are CuTe metadata only;
        # no ATen view/as_strided operation occurs on the hot path.
        token_head_d = cute.make_layout(
            (self.sequence, H, D), stride=(H * D, D, 1)
        )
        d_token_head = cute.make_layout(
            (D, self.sequence, H), stride=(1, H * D, D)
        )
        qhat = cute.make_tensor(g_qhat_workspace.iterator, token_head_d)
        qhat_dsh = cute.make_tensor(g_qhat_workspace.iterator, d_token_head)
        padded_token_head_d = cute.make_layout(
            (self.padded_sequence, H, D), stride=(H * D, D, 1)
        )
        vnew = cute.make_tensor(g_vnew_workspace.iterator, padded_token_head_d)
        vnew_dsh = cute.make_tensor(g_vnew_workspace.iterator, d_token_head)
        raw_o = cute.make_tensor(g_raw_o_workspace.iterator, token_head_d)
        raw_o_dsh = cute.make_tensor(g_raw_o_workspace.iterator, d_token_head)
        output_dsh = cute.make_tensor(g_output.iterator, d_token_head)

        packed_layout = cute.make_layout(
            (self.num_chunks, H, D * BT),
            stride=(H * D * BT, D * BT, 1),
        )
        kpack = cute.make_tensor(g_kpack_workspace.iterator, packed_layout)
        wpack = cute.make_tensor(g_wpack_workspace.iterator, packed_layout)
        upack = cute.make_tensor(g_upack_workspace.iterator, packed_layout)
        packed_flat_layout = cute.make_layout(self.num_chunks * H * D * BT)
        kpack_flat = cute.make_tensor(
            g_kpack_workspace.iterator, packed_flat_layout
        )
        wpack_flat = cute.make_tensor(
            g_wpack_workspace.iterator, packed_flat_layout
        )
        upack_flat = cute.make_tensor(
            g_upack_workspace.iterator, packed_flat_layout
        )
        qhat_flat = cute.make_tensor(
            g_qhat_workspace.iterator,
            cute.make_layout(self.sequence * H * D),
        )

        # Frozen cross-stage ABI: physically contiguous [H,P].  S01 writes and
        # S2/S3 read cumulative[head,token] directly; no pack/transpose exists.
        cumulative_layout = cute.make_layout(
            (H, self.padded_sequence),
            stride=(self.padded_sequence, 1),
        )
        cumulative = cute.make_tensor(
            g_cumulative_workspace.iterator, cumulative_layout
        )

        # Exact M104 producer/consumer aliases.  The grid is head-interleaved:
        # head=block_idx%16 and value_group=block_idx//16.
        pair_layout = cute.make_layout(
            (BT, 64, 2, self.num_chunks, H),
            stride=(
                64,
                1,
                BT * 64,
                H * D * BT,
                D * BT,
            ),
        )
        w_pairs = cute.make_tensor(g_wpack_workspace.iterator, pair_layout)
        k_pairs = cute.make_tensor(g_kpack_workspace.iterator, pair_layout)
        u_groups = cute.make_tensor(
            g_upack_workspace.iterator,
            cute.make_layout(
                (BT, 16, self.num_chunks, 8, H),
                stride=(16, 1, H * D * BT, 16 * BT, D * BT),
            ),
        )
        cumulative_s2 = cute.make_tensor(
            g_cumulative_workspace.iterator,
            cute.make_layout(
                (BT, self.num_chunks, H),
                stride=(1, BT, self.padded_sequence),
            ),
        )
        vnew_s2 = cute.make_tensor(
            g_vnew_workspace.iterator,
            cute.make_layout(
                (BT, 16, self.num_chunks, 8, H),
                stride=(H * D, 1, BT * H * D, 16, D),
            ),
        )
        if cutlass.const_expr(self.h_cta_major):
            # S2 writes its native CTA-major tile order and S3 consumes the
            # identical CuTe view.  No restore/transpose kernel exists at this
            # boundary.  Physical storage is [value_group*head, chunk,
            # key_half, key_lane, value_lane].
            h_s2 = cute.make_tensor(
                g_h_workspace.iterator,
                cute.make_layout(
                    (2, 64, 16, self.num_chunks, 8, H),
                    stride=(
                        64 * 16,
                        16,
                        1,
                        2 * 64 * 16,
                        H * self.num_chunks * 2 * 64 * 16,
                        self.num_chunks * 2 * 64 * 16,
                    ),
                ),
            )
            h_state = h_s2
        else:
            h_s2 = cute.make_tensor(
                g_h_workspace.iterator,
                cute.make_layout(
                    (2, 64, 16, self.num_chunks, 8, H),
                    stride=(
                        64 * D,
                        D,
                        1,
                        H * D * D,
                        16,
                        D * D,
                    ),
                ),
            )
            h_state = cute.make_tensor(
                g_h_workspace.iterator,
                cute.make_layout(
                    (D, D, H, self.num_chunks),
                    stride=(D, 1, D * D, H * D * D),
                ),
            )
        s2_debug = cute.make_tensor(
            g_s2_debug_workspace.iterator,
            cute.make_layout(
                (2, 64, 16, H * 8),
                stride=(64 * 16, 16, 1, 2 * 64 * 16),
            ),
        )

        # Debug arguments temporarily preserve the accepted S01 source's
        # signature.  Production flags disable their stores.  They are built
        # here rather than with torch.view in Plan.run.
        m_debug = cute.make_tensor(
            g_m_debug_workspace.iterator,
            cute.make_layout(self.num_chunks * H * BT * BT),
        )
        inverse_debug = cute.make_tensor(
            g_inverse_debug_workspace.iterator,
            cute.make_layout(self.num_chunks * H * BT * BT),
        )
        beta_debug = cute.make_tensor(
            g_beta_debug_workspace.iterator,
            cute.make_layout((self.padded_sequence, H), stride=(H, 1)),
        )

        # Stage launch contracts are intentionally narrow.  Each launch method
        # must enqueue exactly one CUDA kernel on `stream` and must not allocate
        # or retain any tensor passed here.
        self.s01(
            raw_k_tma,
            raw_q,
            raw_v_tma,
            beta_logits,
            beta_debug,
            decay_logits,
            g_a_log,
            g_dt_bias,
            m_debug,
            inverse_debug,
            kpack_flat,
            qhat_flat,
            wpack_flat,
            upack_flat,
            cumulative,
            g_cu_seqlens,
            cutlass.Int32(H),
            cutlass.Int32(self.num_chunks),
            cutlass.Int32(self.num_chunks),
            cutlass.Int32(1),
            cutlass.Int32(H * self.num_chunks),
            stream,
        )
        self.s2(
            w_pairs,
            w_pairs,
            k_pairs,
            u_groups,
            cumulative_s2,
            s2_debug,
            vnew_s2,
            h_s2,
            cutlass.Int32(self.num_chunks),
            stream,
        )
        self.s3_raw(
            qhat_dsh,
            kpack_flat,
            vnew_dsh,
            h_state,
            cumulative,
            raw_o_dsh,
            g_cu_seqlens,
            scale,
            cutlass.Int32(H),
            cutlass.Int32(self.num_chunks),
            stream,
        )
        raw_o_rows = cute.make_tensor(
            g_raw_o_workspace.iterator,
            cute.make_layout((D, self.sequence * H), stride=(1, D)),
        )
        output_rows = cute.make_tensor(
            g_output.iterator,
            cute.make_layout((D, self.sequence * H), stride=(1, D)),
        )
        self.post(
            raw_o_rows,
            gate_z,
            g_norm_weight,
            output_rows,
            cutlass.Int32(self.sequence * H),
            cutlass.Int32(1),
            epsilon,
            stream,
        )


class Qwen35FLAPrefillPlanSm120:
    """Shape-specialized plan with a six-dynamic-tensor hot ABI."""

    def __init__(
        self,
        output: torch.Tensor,
        mixed: torch.Tensor,
        zba: torch.Tensor,
        A_log: torch.Tensor,
        dt_bias: torch.Tensor,
        norm_weight: torch.Tensor,
        cu_seqlens: torch.Tensor,
        *,
        stages: ProductionStageBundle,
        norm_epsilon: float = 1.0e-6,
        scale: float | None = None,
    ) -> None:
        if mixed.ndim != 3 or mixed.shape[0] != 1:
            raise ValueError("mixed must have shape [1,3*H*D,S]")
        _, channels, sequence = mixed.shape
        if channels != H * QKV_CHANNELS_PER_HEAD:
            raise ValueError(f"mixed channels must equal {H * QKV_CHANNELS_PER_HEAD}")
        expected_mixed_stride = (sequence * channels, 1, channels)
        if tuple(mixed.stride()) != expected_mixed_stride:
            raise ValueError(
                "mixed must use causal-conv channel-last physical layout; "
                f"expected stride {expected_mixed_stride}, got {tuple(mixed.stride())}"
            )
        if zba.shape != (sequence, H * ZBA_WIDTH_PER_HEAD) or not zba.is_contiguous():
            raise ValueError(f"zba must be contiguous [{sequence},{H * ZBA_WIDTH_PER_HEAD}]")
        expected_output = (sequence, H, D)
        if output.shape != expected_output or not output.is_contiguous():
            raise ValueError(f"output must be contiguous {expected_output}")
        if A_log.shape != (H,) or A_log.dtype != torch.float32:
            raise ValueError("A_log must be FP32 [H]")
        if dt_bias.shape != (H,) or dt_bias.dtype != torch.float32:
            raise ValueError("dt_bias must be FP32 [H]")
        if norm_weight.shape != (D,):
            raise ValueError("norm_weight must have shape [D]")
        if mixed.dtype != torch.bfloat16:
            raise ValueError("production checkpoint supports BF16 only")
        if any(t.device != mixed.device for t in (output, zba, A_log, dt_bias, norm_weight, cu_seqlens)):
            raise ValueError("all tensors must be on the mixed tensor's device")
        if cu_seqlens.shape != (2,) or cu_seqlens.dtype != torch.int64:
            raise ValueError("B=1 production requires int64 cu_seqlens[2]")

        padded_sequence = ((sequence + BT - 1) // BT) * BT
        num_chunks = padded_sequence // BT
        device = mixed.device
        dtype = mixed.dtype

        # Retain metadata and plan-owned storage only.  In particular, do not
        # assign output/mixed/zba/a_log/dt_bias/norm_weight to self.
        self.sequence = sequence
        self.padded_sequence = padded_sequence
        self.num_chunks = num_chunks
        self.device = device
        self.dtype = dtype
        self.scale = D**-0.5 if scale is None else scale
        self.norm_epsilon = norm_epsilon
        self.h_cta_major = stages.h_cta_major
        self.stage_abi_tag = stages.abi_tag

        self.qhat = torch.empty((sequence, H, D), dtype=dtype, device=device)
        packed_shape = (num_chunks, H, D * BT)
        self.kpack = torch.empty(packed_shape, dtype=dtype, device=device)
        self.wpack = torch.empty(packed_shape, dtype=dtype, device=device)
        self.upack = torch.empty(packed_shape, dtype=dtype, device=device)
        # Frozen physical ABI [H,P], allocated directly with no torch alias.
        self.cumulative = torch.zeros(
            (H, padded_sequence), dtype=torch.float32, device=device
        )
        self.vnew = torch.empty(
            (padded_sequence, H, D), dtype=dtype, device=device
        )
        if self.h_cta_major:
            self.h_state = torch.zeros(
                (H * 8, num_chunks, 2, 64, 16), dtype=dtype, device=device
            )
        else:
            self.h_state = torch.zeros(
                (num_chunks, H, D, D), dtype=dtype, device=device
            )
        self.raw_o = torch.empty((sequence, H, D), dtype=dtype, device=device)

        # Temporary accepted-S01 signature compatibility.  Stores are disabled
        # by production flags; remove these allocations after S01's debug ABI is
        # physically deleted from the frozen source.
        debug_matrix_shape = (num_chunks, H, BT, BT)
        self.m_debug = torch.empty(debug_matrix_shape, dtype=dtype, device=device)
        self.inverse_debug = torch.empty(
            debug_matrix_shape, dtype=torch.float16, device=device
        )
        self.beta_debug = torch.empty(
            (padded_sequence, H), dtype=torch.float32, device=device
        )
        self.s2_debug = torch.empty(
            (2, 64, 16, H * 8), dtype=torch.float32, device=device
        )
        self.cu_seqlens = cu_seqlens
        self.stream = cuda_driver.CUstream(
            torch.cuda.current_stream(device).cuda_stream
        )

        kernel = Qwen35FLACompositeSm120(
            cutlass.BFloat16,
            integer_dtype_to_cutlass(self.cu_seqlens.dtype),
            sequence=sequence,
            stages=stages,
        )
        options = (cute.EnableTVMFFI(True),) + sm12x_compile_options(device)

        def wrap(tensor: torch.Tensor, align: int):
            return cute.runtime.from_dlpack(
                tensor, assumed_align=align, enable_tvm_ffi=True
            ).mark_layout_dynamic()

        compile_args = (
            wrap(output, 16),
            wrap(mixed, 16),
            wrap(zba, 16),
            wrap(A_log, 16),
            wrap(dt_bias, 16),
            wrap(norm_weight, 16),
            wrap(self.qhat, 16),
            wrap(self.kpack, 16),
            wrap(self.wpack, 16),
            wrap(self.upack, 16),
            wrap(self.cumulative, 16),
            wrap(self.vnew, 16),
            wrap(self.h_state, 16),
            wrap(self.raw_o, 16),
            wrap(self.m_debug, 16),
            wrap(self.inverse_debug, 16),
            wrap(self.beta_debug, 16),
            wrap(self.s2_debug, 16),
            wrap(self.cu_seqlens, 8),
            cutlass.Float32(self.scale),
            cutlass.Float32(norm_epsilon),
            self.stream,
        )
        compiled = cached_compile(kernel, *compile_args, compile_options=options)
        self.compiled = compiled
        # CUTLASS DSL 4.7 may wrap the positional TVM-FFI function.  Resolve a
        # direct callable once during prepare; never rebind Function.__call__.
        get_tvm_ffi = getattr(compiled, "__tvm_ffi_object__", None)
        direct = get_tvm_ffi() if get_tvm_ffi is not None else None
        self._compiled_call = direct if direct is not None else compiled

    def run_fused_gated_rms(
        self,
        output: torch.Tensor,
        mixed: torch.Tensor,
        zba: torch.Tensor,
        A_log: torch.Tensor,
        dt_bias: torch.Tensor,
        norm_weight: torch.Tensor,
    ) -> torch.Tensor:
        self._compiled_call(
            output,
            mixed,
            zba,
            A_log,
            dt_bias,
            norm_weight,
            self.qhat,
            self.kpack,
            self.wpack,
            self.upack,
            self.cumulative,
            self.vnew,
            self.h_state,
            self.raw_o,
            self.m_debug,
            self.inverse_debug,
            self.beta_debug,
            self.s2_debug,
            self.cu_seqlens,
            self.scale,
            self.norm_epsilon,
            self.stream,
        )
        return output


def _build_production_stage_bundle(
    sequence: int,
    dtype,
    cu_seqlens_dtype,
    *,
    candidate_id: str,
) -> ProductionStageBundle:
    """Construct the four frozen, pointer-dynamic production launchers."""

    from flashinfer.gdn_kernels.delta_rule_dsl.qwen35_fla_post_sm120 import (
        build_qwen35_fla_post_stage,
    )
    from flashinfer.gdn_kernels.delta_rule_dsl.qwen35_fla_s01_sm120 import (
        build_qwen35_fla_s01_stage,
    )
    from flashinfer.gdn_kernels.delta_rule_dsl.qwen35_fla_s2_sm120 import (
        build_qwen35_fla_s2_stage,
    )
    from .qwen35_fla_s3_raw_sm120 import build_qwen35_fla_s3_raw_stage

    return ProductionStageBundle(
        s01=build_qwen35_fla_s01_stage(sequence, dtype, cu_seqlens_dtype),
        s2=build_qwen35_fla_s2_stage(sequence),
        s3_raw=build_qwen35_fla_s3_raw_stage(
            sequence,
            dtype,
            cu_seqlens_dtype,
            candidate_id=candidate_id,
        ),
        post=build_qwen35_fla_post_stage(sequence, dtype),
        h_cta_major=True,
        abi_tag=(
            "fla_l017_s01wstoreu4_s384to640_m104_headmajor_s2hcta_"
            "s3native_s3u4u8split_poststatic1_b384_v5_"
            "s3tileab_" + candidate_id.lower()
        ),
    )


def prepare_qwen35_fla_cute_pipeline_sm120(
    mixed: torch.Tensor,
    zba: torch.Tensor,
    A_log: torch.Tensor,
    dt_bias: torch.Tensor,
    norm_weight: torch.Tensor,
    cu_seqlens: torch.Tensor,
    *,
    norm_epsilon: float = 1.0e-6,
    scale: float | None = None,
    output: torch.Tensor | None = None,
    candidate_id: str,
) -> Qwen35FLAPrefillPlanSm120:
    """Allocate/compile a stream-bound plan; never called on the layer hot path."""

    sequence = mixed.shape[2]
    if mixed.dtype != torch.bfloat16:
        raise ValueError("production checkpoint supports BF16 only")
    if candidate_id not in ("C0", "C1"):
        raise ValueError(f"unqualified candidate_id {candidate_id!r}")
    stages = _build_production_stage_bundle(
        sequence,
        cutlass.BFloat16,
        integer_dtype_to_cutlass(cu_seqlens.dtype),
        candidate_id=candidate_id,
    )
    if output is None:
        output = torch.empty(
            (sequence, H, D), dtype=mixed.dtype, device=mixed.device
        )
    return Qwen35FLAPrefillPlanSm120(
        output,
        mixed,
        zba,
        A_log,
        dt_bias,
        norm_weight,
        cu_seqlens,
        stages=stages,
        norm_epsilon=norm_epsilon,
        scale=scale,
    )
