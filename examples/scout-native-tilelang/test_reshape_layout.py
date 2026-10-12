"""Native Buffer contract for a reviewed complete TileLang customize module.

Owner-run reproduction of tile-ai/tilelang#3339, not a competing repair.
This deliberately does not replace reshape or mock its TVM dependencies.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys

import pytest


@pytest.fixture(scope="session")
def subject():
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "":
        raise RuntimeError("run this frontend-only check with CUDA_VISIBLE_DEVICES=''")
    path = Path(os.environ["TILELANG_CUSTOMIZE_SOURCE"])
    expected = os.environ["TILELANG_CUSTOMIZE_SHA256"]
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise RuntimeError("supply an absolute reviewed regular source file")
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise RuntimeError("supply the reviewed raw Git-blob SHA256")
    if path.stat().st_size > 8 * 1024 * 1024:
        raise RuntimeError("source exceeds 8 MiB")
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise RuntimeError("reviewed customize module hash mismatch")

    import tilelang
    import torch
    import tvm

    assert not torch.cuda.is_initialized()
    # Preserve the real package context, including relative .atomic imports.
    # Other modules/native libraries belong to the observed dependency runtime,
    # not necessarily the selected source revision. Do not call this full-stack.
    name = "tilelang.language.owner_reviewed_customize"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        assert Path(module.__file__).resolve() == path.resolve()
        print("NATIVE_PROVENANCE " + json.dumps({
            "source": str(path), "source_sha256": expected,
            "python": sys.version, "tilelang_version": tilelang.__version__,
            "tilelang_path": tilelang.__file__, "tvm_path": tvm.__file__,
            "torch_version": torch.__version__, "torch_path": torch.__file__,
            "scope": "complete Python module over observed native dependencies; frontend only",
        }))
        yield module
    finally:
        sys.modules.pop(name, None)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
        assert not torch.cuda.is_initialized()


def check_compact(subject, source, target):
    actual = subject.reshape(source, target)
    assert tuple(int(x) for x in actual.shape) == target
    assert actual.dtype == source.dtype
    assert actual.data.same_as(source.data)
    assert int(actual.elem_offset) == 0
    expected_strides = []
    stride = 1
    for extent in reversed(target):
        expected_strides.insert(0, stride)
        stride *= extent
    # An empty stride list is TVM's implicit compact representation.
    assert not actual.strides or [int(x) for x in actual.strides] == expected_strides


def test_implicit_compact(subject):
    from tvm.tirx import decl_buffer
    check_compact(subject, decl_buffer((4, 8), "float32"), (2, 16))


def test_explicit_compact(subject):
    from tvm.tirx import decl_buffer
    check_compact(subject, decl_buffer((4, 8), "float32", strides=(8, 1)), (2, 16))


def test_singleton_stride(subject):
    from tvm.tirx import decl_buffer
    check_compact(subject, decl_buffer((1, 4), "float32", strides=(999, 1)), (4,))


def test_nonzero_offset(subject):
    from tvm.tirx import decl_buffer
    source = decl_buffer((4, 8), "float32", elem_offset=100)
    with pytest.raises(ValueError, match="non-zero elem_offset"):
        subject.reshape(source, (2, 16))


def test_symbolic_offset(subject):
    from tvm.tirx import decl_buffer, Var
    source = decl_buffer((4, 8), "float32", elem_offset=Var("offset", "int32"))
    with pytest.raises(ValueError, match="non-zero elem_offset"):
        subject.reshape(source, (2, 16))


def test_noncompact_stride(subject):
    from tvm.tirx import decl_buffer
    source = decl_buffer((4, 4), "float32", strides=(8, 1))
    with pytest.raises(ValueError, match="densely packed"):
        subject.reshape(source, (16,))


def test_bits_mismatch(subject):
    from tvm.tirx import decl_buffer
    with pytest.raises(AssertionError, match="shape check failed"):
        subject.reshape(decl_buffer((4, 8), "float32"), (16,))
