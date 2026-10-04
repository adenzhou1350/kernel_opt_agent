"""Tiny real-CUDA offload/prefetch check, independent of model downloads.

Choose an authorized device externally; this script does not allocate resources
for other tasks, change visible devices, or edit the selected source.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument(
        "--device", required=True, help="Explicit visible CUDA ordinal, e.g. cuda:0"
    )
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(source / "src"))

    import torch
    import transformers.cache_utils as module

    module_path = Path(module.__file__).resolve()
    if not module_path.is_relative_to(source / "src"):
        raise RuntimeError("cache_utils resolved outside the selected source")
    device = torch.device(args.device)
    if device.type != "cuda" or device.index is None:
        raise ValueError("--device requires an explicit CUDA ordinal")
    torch.cuda.set_device(device)
    torch.manual_seed(37)
    torch.cuda.reset_peak_memory_stats(device)
    records = []
    classes = [
        (module.LinearAttentionAndFullAttentionLayer, {}),
        (module.LinearAttentionAndSlidingWindowAttentionLayer, {"sliding_window": 4}),
        (module.LinearAttentionAndStaticFullAttentionLayer, {"max_cache_len": 8}),
        (
            module.LinearAttentionAndStaticSlidingWindowAttentionLayer,
            {"max_cache_len": 8, "sliding_window": 4},
        ),
    ]
    for cls, kwargs in classes:
        layer = cls(**kwargs)
        control = module.DynamicLayer()
        kv = torch.rand(1, 2, 2, 4, device=device)
        conv = torch.rand(1, 8, 4, device=device)
        recurrent = torch.rand(1, 2, 4, 4, device=device)
        layer.update(kv, kv + 1)
        control.update(kv, kv + 1)
        layer.update_conv_state(conv)
        layer.update_recurrent_state(recurrent)
        keys, values = layer.keys.clone(), layer.values.clone()
        cache = module.Cache(
            layers=[layer, control], offloading=True, offload_only_non_sliding=False
        )

        def devices(layer):
            return {
                "keys": str(layer.keys.device),
                "values": str(layer.values.device),
                "conv": str(layer.conv_states[0].device),
                "recurrent": str(layer.recurrent_states[0].device),
            }

        cache.offload(0, only_non_sliding=False)
        torch.cuda.synchronize(device)
        offloaded = devices(layer)
        cache.prefetch(0, only_non_sliding=False)
        torch.cuda.synchronize(device)
        prefetched = devices(layer)
        checks = {
            "kv_offloaded": offloaded["keys"] == offloaded["values"] == "cpu",
            "linear_states_resident": offloaded["conv"]
            == offloaded["recurrent"]
            == str(device),
            "kv_prefetched": prefetched["keys"] == prefetched["values"] == str(device),
            "linear_states_still_resident": prefetched["conv"]
            == prefetched["recurrent"]
            == str(device),
            "hybrid_not_linear_only": cache.is_linear[0] is False,
            "kv_data_preserved": torch.equal(layer.keys.cpu(), keys.cpu())
            and torch.equal(layer.values.cpu(), values.cpu()),
            "linear_data_preserved": torch.equal(layer.conv_states[0].cpu(), conv.cpu())
            and torch.equal(layer.recurrent_states[0].cpu(), recurrent.cpu()),
        }
        records.append(
            {
                "class": cls.__name__,
                "offloaded": offloaded,
                "prefetched": prefetched,
                "checks": checks,
                "pass": all(checks.values()),
            }
        )
        del cache, layer, control, kv, conv, recurrent, keys, values
    torch.cuda.synchronize(device)
    peak = torch.cuda.max_memory_allocated(device)
    if peak >= 16 * 1024**2:
        raise RuntimeError("tiny fixture exceeded its allocation budget")
    result = {
        "commit": subprocess.check_output(
            ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
        ).strip(),
        "module_sha256": hashlib.sha256(module_path.read_bytes()).hexdigest(),
        "torch": torch.__version__,
        "device": torch.cuda.get_device_name(device),
        "peak_allocated_bytes": peak,
        "records": records,
        "scope": "synchronized cache component only; not race, generation, performance or upstream CI",
    }
    print(json.dumps(result))
    return 0 if all(record["pass"] for record in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
