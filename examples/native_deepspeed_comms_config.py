"""Observe real DeepSpeed logger configuration without launching a workload.

Run in an existing task-private DeepSpeed environment with CUDA hidden and
DS_ACCELERATOR=cpu. This tests configuration, not collective correctness,
overlap, performance, or every engine initialization path. No dependency install,
native build, distributed initialization, or model construction is performed.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--comm-sha256", required=True)
    parser.add_argument("--logging-sha256", required=True)
    args = parser.parse_args()
    if os.environ.get("CUDA_VISIBLE_DEVICES") not in ("", "-1"):
        parser.error("hide CUDA before importing DeepSpeed")
    if os.environ.get("DS_ACCELERATOR") != "cpu":
        parser.error("select the actual CPU accelerator before importing DeepSpeed")

    import torch
    import deepspeed
    from deepspeed.comm import comm
    from deepspeed.runtime.config import DeepSpeedConfig
    from deepspeed.utils import comms_logging

    root = args.source_root.resolve(strict=True)
    module = Path(comm.__file__).resolve(strict=True)
    if not module.is_relative_to(root):
        raise ValueError("DeepSpeed resolved outside the selected source root")
    digest = hashlib.sha256(module.read_bytes()).hexdigest()
    if digest != args.comm_sha256:
        raise ValueError("the imported comm module does not match the expected bytes")
    logging_module = Path(comms_logging.__file__).resolve(strict=True)
    logging_digest = hashlib.sha256(logging_module.read_bytes()).hexdigest()
    if not logging_module.is_relative_to(root) or logging_digest != args.logging_sha256:
        raise ValueError("the imported logger does not match the selected source")
    if torch.cuda.is_initialized():
        raise ValueError("CUDA was initialized before the configuration probe")

    logger = comm.comms_logger
    saved = {name: getattr(logger, name) for name in
             ("enabled", "prof_all", "prof_ops", "verbose", "debug")}
    rows = []
    try:
        for initial in (False, True):
            for name, section, expected in (
                ("absent", None, False),
                ("enabled", {"enabled": True}, True),
                ("disabled", {"enabled": False}, False),
                ("default_empty_section", {}, False),
            ):
                comm.configure(enabled=initial, prof_all=False, prof_ops=[], verbose=False, debug=False)
                assert logger.enabled is initial
                config = {"train_batch_size": 1, "train_micro_batch_size_per_gpu": 1}
                if section is not None:
                    config["comms_logger"] = section
                parsed = DeepSpeedConfig(config)
                comm.configure(deepspeed_config=parsed)
                rows.append({"case": name, "initial_enabled": initial, "expected_enabled": expected,
                             "parsed_enabled": None if section is None else parsed.comms_config.comms_logger.enabled,
                             "observed_enabled": logger.enabled, "matches": logger.enabled is expected})
        comm.configure(enabled=False)
        assert logger.enabled is False
        assert not torch.cuda.is_initialized()
    finally:
        comm.configure(**saved)
    matched = all(row["matches"] for row in rows)
    print(json.dumps({"status": "MATCH" if matched else "CONFIG_MISMATCH",
                      "deepspeed_version": deepspeed.__version__, "torch_version": torch.__version__,
                      "comm_sha256": digest, "logging_sha256": logging_digest,
                      "cases": rows, "explicit_reset_pass": True,
                      "cuda_initialized": False, "scope": "native configuration only"}))
    return 0 if matched else 1


if __name__ == "__main__":
    raise SystemExit(main())
