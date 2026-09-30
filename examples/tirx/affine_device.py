"""Validate the same CPU-screened affine source on an already allocated B300."""
import argparse
import hashlib
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpu-result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    expected_uuid = os.environ["EXPECTED_GPU_UUID"]
    assert os.environ["CUDA_VISIBLE_DEVICES"] == expected_uuid
    import numpy as np
    import torch
    from tirx_kernels.runner import compile_kernel, cuda_target
    import affine_cases
    source_hash = hashlib.sha256(Path(affine_cases.__file__).read_bytes()).hexdigest()
    cpu = json.loads(args.cpu_result.read_text())
    assert cpu["status"] == "PASS" and cpu["source_sha256"] == source_hash
    assert cpu["source_unchanged"] and cpu["cases"]["valid"]["status"] == "PASS"
    assert torch.cuda.device_count() == 1
    observed = str(torch.cuda.get_device_properties(0).uuid)
    observed = observed if observed.startswith("GPU-") else "GPU-" + observed
    assert observed == expected_uuid
    assert torch.cuda.get_device_capability() == (10, 3)
    data = affine_cases.make_case("valid")
    source = torch.from_numpy(np.array(data["inputs"]["source"], copy=True)).cuda()
    output = torch.empty_like(source)
    with cuda_target():
        executable = compile_kernel(data["kernel"])
    executable(source, output)
    torch.cuda.synchronize()
    torch.testing.assert_close(output.cpu(), torch.from_numpy(data["expected"]["output"]), rtol=0, atol=0)
    args.output.write_text(json.dumps({"status": "PASS", "gpu_uuid": observed,
                                      "source_sha256": source_hash, "elements": 32,
                                      "cpu_result": str(args.cpu_result), "rtol": 0, "atol": 0}) + "\n")


if __name__ == "__main__":
    main()
