"""Complete CPU screening example. Broken cases must never be launched on GPU."""
import numpy as np
from tvm.script import tirx as T


@T.prim_func
def affine(source: T.Buffer((32,), "float32"), output: T.Buffer((32,), "float32")):
    T.device_entry()
    _warp = T.warp_id([1])
    lane = T.lane_id([32])
    output[lane] = source[lane] * T.float32(2) + T.float32(1)


@T.prim_func
def race(output: T.Buffer((1,), "int32")):
    T.device_entry()
    _warp = T.warp_id([1])
    lane = T.lane_id([32])
    output[0] = lane


@T.prim_func
def sync(output: T.Buffer((1,), "int32")):
    T.device_entry()
    _warp = T.warp_id([1])
    lane = T.lane_id([32])
    barrier = T.alloc_buffer((1,), "uint64", scope="shared")
    if lane == 0:
        T.ptx.mbarrier.arrive.shared.b64(T.address_of(barrier[0]))
        output[0] = 1


def make_case(name):
    if name in ("valid", "numerical_bug"):
        source = np.linspace(-4, 4, 32, dtype=np.float32)
        return {"kernel": affine, "inputs": {"source": source, "output": np.zeros_like(source)},
                "expected": {"output": source * 2 + (1 if name == "valid" else 2)}, "rtol": 0, "atol": 0}
    if name in ("race_bug", "sync_bug"):
        return {"kernel": race if name == "race_bug" else sync,
                "inputs": {"output": np.zeros(1, np.int32)},
                "expected": {"output": np.zeros(1, np.int32)}, "rtol": 0, "atol": 0}
    raise ValueError(f"unknown case: {name}")
