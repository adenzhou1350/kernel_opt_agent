"""Bounded feedback search: CPU compile, real device checks, measured family view.

Requires Linux, a trusted private environment, and authorization for the idle GPU
specified by EXPECTED_GPU_UUID/CUDA_VISIBLE_DEVICES. Run with an outer timeout.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import random
import statistics
import subprocess
import sys
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--pairs', type=int, default=5)
parser.add_argument('--epochs', type=int, default=3)
parser.add_argument('--sizes', type=int, nargs='+', default=[4096, 131072, 1048576, 1048583, 4194313])
args = parser.parse_args()
if args.pairs < 1 or args.epochs < 1 or any(size < 1 for size in args.sizes):
    parser.error('sizes, pairs and epochs must be positive')
uuid = os.environ['EXPECTED_GPU_UUID']
assert os.environ['CUDA_VISIBLE_DEVICES'] == uuid
START = time.monotonic()
import numpy as np
import torch
import feedback_cases as cases
from tirx_kernels.runner import compile_kernel, cuda_initialization_guard, cuda_target
from tvm.tirx.bench import bench

args.output.parent.mkdir(parents=True, exist_ok=True)
result = {'status': 'RUNNING', 'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'cases_sha256': hashlib.sha256(Path(cases.__file__).read_bytes()).hexdigest(), 'epochs': [],
          'scope': 'Fixed mechanism search, actual device outputs and warm event timings; no full agent/model A/B'}


def save():
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')


save()
compiled = {}
with cuda_initialization_guard():
    with cuda_target():
        for size in args.sizes:
            for family in cases.FAMILIES:
                compiled[size, family] = compile_kernel(cases.make_kernel(family, size))
assert not torch.cuda.is_initialized()
result['cpu_preparation_s'] = time.monotonic() - START
with open('/tmp/kernel-opt-'+uuid+'.lock', 'w') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    for query in range(3):
        state = subprocess.check_output(['nvidia-smi', '-i', uuid,
            '--query-gpu=uuid,memory.used,utilization.gpu', '--format=csv,noheader'], text=True)
        observed, memory, utilization = [item.strip() for item in state.split(',')]
        assert observed == uuid and int(memory.split()[0]) < 64, state
        if int(utilization.split()[0]) == 0:
            break
        time.sleep(1)
    else:
        raise RuntimeError('GPU is busy; no launch')
    gpu_started = time.monotonic()
    assert torch.cuda.device_count() == 1
    observed = str(torch.cuda.get_device_properties(0).uuid)
    assert observed.removeprefix('GPU-') == uuid.removeprefix('GPU-')
    result['gpu_uuid'] = uuid
    result['gpu_name'] = torch.cuda.get_device_name(0)
    result['multiprocessors'] = torch.cuda.get_device_properties(0).multi_processor_count
    rng = random.Random(419)
    for epoch in range(args.epochs):
        rows = []
        result['epochs'].append(rows)
        order_sizes = list(args.sizes)
        rng.shuffle(order_sizes)
        for size in order_sizes:
            source = torch.empty(size, dtype=torch.float32, device='cuda')
            outputs = {family: torch.empty_like(source) for family in cases.FAMILIES}
            functions = {family: (lambda family=family: compiled[size, family](source, outputs[family]))
                         for family in cases.FAMILIES}
            row = {'size': size, 'correctness': [], 'pairs': []}
            rows.append(row)
            for seed in (173, 419, 997):
                torch.manual_seed(seed + epoch*1000)
                source.normal_()
                source[-1] = .75
                reference = torch.clamp(source*2+1, min=0)
                for family, function in functions.items():
                    outputs[family].fill_(float('nan'))
                    function()
                    torch.cuda.synchronize()
                    torch.testing.assert_close(outputs[family], reference, rtol=0, atol=0)
                    row['correctness'].append({'family': family, 'seed': seed+epoch*1000, 'status': 'PASS'})
            for pair in range(args.pairs):
                order = list(functions)
                rng.shuffle(order)
                measurement = bench({family: functions[family] for family in order}, timer='event',
                                    warmup=10, repeat=30, cooldown_s=.1, rounds=1)
                assert not measurement['errors'], measurement['errors']
                row['pairs'].append({'order': order, 'times_us': measurement['impls'],
                                     'protocol': measurement['benchmark_protocol']})
            row['medians_us'] = {family: statistics.median(pair['times_us'][family] for pair in row['pairs'])
                                 for family in cases.FAMILIES}
            for family, function in functions.items():
                function()
                torch.cuda.synchronize()
                torch.testing.assert_close(outputs[family], reference, rtol=0, atol=0)
            save()
            print(json.dumps({'epoch': epoch, 'size': size, 'medians_us': row['medians_us']}), flush=True)
        # Separate measurement windows; this bounded study is not a long-term reliability soak.
        if epoch+1 < args.epochs:
            time.sleep(1)
    result['gpu_reserved_s'] = time.monotonic() - gpu_started
result['elapsed_s'] = time.monotonic() - START
result['status'] = 'PASS'
save()
