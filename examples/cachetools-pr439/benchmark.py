"""Source-bound cache-hit microbenchmark, not whole-application performance."""
import argparse
import gc
import hashlib
import json
import sys
import time
from pathlib import Path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True, help='reviewed checkout src directory')
    parser.add_argument('--sha256', required=True, help='reviewed cachetools/__init__.py SHA256')
    parser.add_argument('--mode', choices=('getitem', 'get'), required=True)
    parser.add_argument('--keys', choices=('int', 'str', 'tuple'), required=True)
    args = parser.parse_args()
    package = args.package.resolve(strict=True)
    path = package / 'cachetools/__init__.py'
    if hashlib.sha256(path.read_bytes()).hexdigest() != args.sha256:
        raise ValueError('reviewed source identity mismatch before import')
    sys.path.insert(0, str(package))
    import cachetools
    if Path(cachetools.__file__).resolve() != path.resolve():
        raise ValueError('imported another cachetools package')
    keys = list(range(1024))
    if args.keys == 'str':
        keys = [str(key) for key in keys]
    elif args.keys == 'tuple':
        keys = [(key, 'entry') for key in keys]
    cache = cachetools.LRUCache(maxsize=2048)
    for index, key in enumerate(keys):
        cache[key] = index
    stream = keys * 256
    for key in keys * 10:
        cache[key]
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        total = 0
        if args.mode == 'getitem':
            start = time.perf_counter_ns()
            for key in stream:
                total += cache[key]
        else:
            start = time.perf_counter_ns()
            for key in stream:
                total += cache.get(key)
        elapsed = time.perf_counter_ns() - start
    finally:
        if was_enabled:
            gc.enable()
    if total != sum(range(1024)) * 256 or len(cache) != 1024:
        raise AssertionError('unexpected hit result or cache size')
    if hashlib.sha256(path.read_bytes()).hexdigest() != args.sha256:
        raise ValueError('reviewed source changed during execution')
    print(json.dumps(dict(elapsed_ns=elapsed, operations=len(stream), ns_per_operation=elapsed/len(stream),
        mode=args.mode, keys=args.keys, checksum=total, module_sha256=args.sha256,
        python=sys.version, gc_disabled_during_measurement=True)))
