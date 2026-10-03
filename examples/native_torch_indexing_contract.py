"""Native CUDA API counterexamples, not attention-backend qualification.

Run only on a selected authorized GPU. Requires an existing PyTorch environment;
does not install anything, compile a kernel, mock indexing or import Scout code.
CUDA_VISIBLE_DEVICES must contain exactly the expected full UUID.
"""

import argparse
import json
import os
import sys

import torch


def main():
    if sys.flags.optimize:
        raise SystemExit("Do not disable this reproduction's assertions with -O.")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-uuid", required=True)
    args = parser.parse_args()
    assert os.environ.get("CUDA_VISIBLE_DEVICES") == args.expected_uuid
    assert torch.cuda.is_available() and torch.cuda.device_count() == 1
    properties = torch.cuda.get_device_properties(0)
    actual_uuid = str(properties.uuid)
    assert actual_uuid.removeprefix("GPU-") == args.expected_uuid.removeprefix("GPU-")
    passed = []
    for count, flags in (
        (4, [True] * 4), (4, [False] * 4),
        (4, [True, False, True, False]), (0, []),
    ):
        cpu = torch.arange(count, dtype=torch.long)
        cuda = cpu.cuda()
        mask = torch.tensor(flags, dtype=torch.bool)  # Deliberately CPU.
        assert mask.device.type == "cpu" and cuda.device.type == "cuda"
        for selected in (mask, ~mask):
            actual = cuda[selected]
            assert actual.device.type == "cuda"
            assert torch.equal(actual.cpu(), cpu[selected])
        passed.append(f"cpu_bool_mask_{count}_{sum(flags)}")

    target = torch.zeros(4, device="cuda", dtype=torch.long)
    values = torch.tensor([5, 7], device="cuda", dtype=torch.long)
    index = torch.tensor([0, 2], dtype=torch.long)
    try:
        target.index_copy_(0, index, values)
    except RuntimeError as error:
        assert "device" in str(error).lower()
        invalid_copy_error = str(error)
    else:
        raise AssertionError("CPU index_copy_ index unexpectedly accepted")
    assert torch.equal(target.cpu(), torch.zeros(4, dtype=torch.long))
    passed.append("cpu_index_copy_index_rejected")
    target.index_copy_(0, index.cuda(), values)
    assert torch.equal(target.cpu(), torch.tensor([5, 0, 7, 0]))
    passed.append("same_device_index_copy_control")
    torch.cuda.synchronize()
    print(json.dumps({
        "torch": torch.__version__, "device": properties.name,
        "uuid": actual_uuid, "checks": passed, "index_copy_error": invalid_copy_error,
        "scope": "Exact native indexing APIs only; no full SGLang/backend/model/performance claim.",
    }, sort_keys=True))


if __name__ == "__main__":
    main()
