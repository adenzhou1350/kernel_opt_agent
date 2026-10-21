"""Opt-in CPU component witness for vLLM issue62808; no real LMCache engine."""

import hashlib
import json
import os
from pathlib import Path

if os.environ.get("CUDA_VISIBLE_DEVICES") != "":
    raise SystemExit("Run in an already reviewed CPU environment with CUDA hidden")

import torch  # noqa: E402
import vllm  # noqa: E402
from vllm.distributed.kv_transfer import kv_transfer_state as state  # noqa: E402
from vllm.distributed.kv_transfer.kv_connector.v1 import (  # noqa: E402
    base,
    lmcache_connector as module,
)

EXPECTED = {
    module: "833fd992fba0bd50c786f7653d421c6ab48dd09a436ea13154ae520130a6b68a",
    base: "3af87e036c13ac36132471e4253cc10847be323891e3c18ce20b30c03aaac8f7",
    state: "bcdbd57fab582202b62861a84a397c83559f5543de38ec04c3467a637318af62",
}


class TrackingEngine:
    def __init__(self):
        self.calls = 0

    def shutdown(self):
        self.calls += 1


class ForwardingControl(module.LMCacheConnectorV1):
    """Private causal control, not a complete production repair."""

    def shutdown(self):
        return self._lmcache_engine.shutdown()


def main():
    for imported, digest in EXPECTED.items():
        assert hashlib.sha256(Path(imported.__file__).read_bytes()).hexdigest() == digest
    assert state._KV_CONNECTOR_AGENT is None
    assert module.LMCacheConnectorV1.shutdown is base.KVConnectorBase_V1.shutdown
    records = []
    for cls, expected_calls in [(module.LMCacheConnectorV1, 0), (ForwardingControl, 1)]:
        for caller in ["direct", "ensure_kv_transfer_shutdown"]:
            # Deliberately bypass model/LMCache construction; retain real methods.
            connector = object.__new__(cls)
            engine = TrackingEngine()
            connector._lmcache_engine = engine
            if caller == "direct":
                connector.shutdown()
            else:
                state._KV_CONNECTOR_AGENT = connector
                try:
                    state.ensure_kv_transfer_shutdown()
                    assert state._KV_CONNECTOR_AGENT is None
                finally:
                    state._KV_CONNECTOR_AGENT = None
                state.ensure_kv_transfer_shutdown()  # no-agent control
            assert engine.calls == expected_calls
            records.append({"wrapper": cls.__name__, "caller": caller,
                            "observed_engine_calls": engine.calls})
    assert state._KV_CONNECTOR_AGENT is None
    for imported, digest in EXPECTED.items():
        assert hashlib.sha256(Path(imported.__file__).read_bytes()).hexdigest() == digest
    print(json.dumps({
        "records": records,
        "versions": {"vllm": vllm.__version__, "torch": torch.__version__},
        "source_sha256": {m.__name__: digest for m, digest in EXPECTED.items()},
        "boundary": "Native installed wrapper/base/transfer-state only; constructor bypassed, "
                    "tracking engine not LMCache. No server, SIGTERM, background-thread, "
                    "GPU, model or full-current-main qualification.",
    }))


if __name__ == "__main__":
    main()
