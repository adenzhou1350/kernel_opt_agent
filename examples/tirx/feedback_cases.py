"""Complete alternative mechanisms for exact FP32 max(2*x+1,0)."""
import numpy as np
from tvm.script import tirx as T

FAMILIES = ('threadwise', 'tiled', 'persistent', 'persistent_1024')


def make_kernel(family, size=37):
    if family not in FAMILIES:
        raise ValueError(f'unknown family: {family}')
    warps, items = (1, 1) if family == 'threadwise' else (4, 4)
    tile = 32 * warps * items
    needed = (size + tile - 1) // tile
    cap = 1024 if family == 'persistent_1024' else 128
    blocks = min(cap, needed) if family.startswith('persistent') else needed
    rounds = (needed + blocks - 1) // blocks

    @T.prim_func
    def kernel(source: T.Buffer((size,), 'float32'), output: T.Buffer((size,), 'float32')):
        T.device_entry()
        block = T.cta_id([blocks])
        warp = T.warp_id([warps])
        lane = T.lane_id([32])
        for chunk in T.serial(rounds):
            for item in T.unroll(items):
                index = (chunk * blocks + block) * tile + item * (32 * warps) + warp * 32 + lane
                if index < size:
                    output[index] = T.max(source[index] * T.float32(2) + T.float32(1), T.float32(0))
    return kernel


def make_case(name):
    family, _, text_size = name.partition(':')
    size = int(text_size) if text_size else 37
    source = np.random.default_rng(173).uniform(-3, 3, size).astype(np.float32)
    source[-1] = .75
    return {'kernel': make_kernel(family, size), 'inputs': {'source': source, 'output': np.zeros_like(source)},
            'expected': {'output': np.maximum(source * 2 + 1, 0)}, 'rtol': 0, 'atol': 0}
