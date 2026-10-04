"""Optional native CPU checks of a pinned, reviewed TorchTitan checkout."""

# Import native dependencies only after the explicit optional-source opt-in.
# ruff: noqa: E402

import hashlib
import inspect
import os
import queue
import shutil
import sys
import threading
from datetime import timedelta
from pathlib import Path

import pytest

source = os.environ.get("TORCHTITAN_AUDIT_SOURCE_ROOT")
if not source:
    pytest.skip("Set TORCHTITAN_AUDIT_SOURCE_ROOT explicitly", allow_module_level=True)
root = Path(source).resolve(strict=True)
sys.path.insert(0, str(root))

import torch
import torch.distributed as dist
from torch.distributed.device_mesh import DeviceMesh
from torch.distributed.tensor import DTensor, Replicate

from torchtitan.components.checkpointer import base
from torchtitan.quantization import _fsdp_tensor


@pytest.fixture(autouse=True)
def exact_cpu_source():
    assert os.environ.get("CUDA_VISIBLE_DEVICES") == ""
    assert not torch.cuda.is_initialized()
    expected = (
        (
            base,
            "torchtitan/components/checkpointer/base.py",
            "7c4848207dc27c32ffb6de38252e9276a28913cc5185193ec8dde6365fa65268",
        ),
        (
            _fsdp_tensor,
            "torchtitan/quantization/_fsdp_tensor.py",
            "cfbb4a40371392a1126da8f7878d8c3ea18bcc3ef0434aabb9864fed4cd454b0",
        ),
    )
    for module, relative, digest in expected:
        path = root / relative
        assert Path(inspect.getfile(module)).resolve() == path.resolve()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    yield
    assert not torch.cuda.is_initialized()


def test_purge_thread_real_backend_failure_and_shutdown(tmp_path):
    stale = tmp_path / "stale"
    retained = tmp_path / "after-shutdown"
    stale.mkdir()
    retained.mkdir()
    requests = queue.Queue()
    for item in (str(tmp_path / "missing"), str(stale), None, str(retained)):
        requests.put(item)
    worker = threading.Thread(
        target=base.purge_thread, args=(requests, shutil.rmtree), daemon=True
    )
    worker.start()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert not stale.exists()
    assert retained.is_dir()
    assert requests.get_nowait() == str(retained)
    assert requests.empty()


def test_wrapper_alias_copy_fallback_keeps_cache_and_values():
    class Weight(_fsdp_tensor._ShardedFSDPTensor):
        pass

    model = torch.nn.Module()
    model.register_buffer("weight", Weight(torch.zeros(4)))
    wrapper = base.ModelWrapper(model)
    cached = wrapper.state_dict()["weight"]
    # Observed Torch 2.11 behavior: outer wrappers do not report aliasing, while
    # their actual inner tensors do. Validate the consumer, not a guessed verdict.
    assert not base._shares_storage(cached, model.weight)
    assert torch._C._is_alias_of(cached._tensor, model.weight._tensor)
    pointer = cached._tensor.untyped_storage().data_ptr()
    with torch.no_grad():
        model.weight._tensor.fill_(2)
    refreshed = wrapper.state_dict()["weight"]
    assert refreshed is cached
    assert refreshed._tensor.untyped_storage().data_ptr() == pointer
    torch.testing.assert_close(refreshed._tensor, torch.full((4,), 2.0))
    wrapper.load_state_dict({"weight": torch.full((4,), 3.0)})
    torch.testing.assert_close(model.weight._tensor, torch.full((4,), 3.0))


def test_dtensor_local_storage_alias_with_single_rank_gloo(tmp_path):
    assert not dist.is_initialized()
    dist.init_process_group(
        "gloo",
        store=dist.FileStore(str(tmp_path / "rendezvous"), 1),
        rank=0,
        world_size=1,
        timeout=timedelta(seconds=10),
    )
    try:
        mesh = DeviceMesh("cpu", [0])
        local = torch.arange(4, dtype=torch.float32)
        first = DTensor.from_local(local, mesh, [Replicate()])
        same = DTensor.from_local(local.view(4), mesh, [Replicate()])
        other = DTensor.from_local(local.clone(), mesh, [Replicate()])
        assert base._shares_storage(first, same)
        assert base._shares_storage(first, local)
        assert not base._shares_storage(first, other)
    finally:
        dist.destroy_process_group()
    assert not dist.is_initialized()
