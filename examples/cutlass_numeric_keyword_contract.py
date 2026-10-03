"""Check the installed CuTe numeric keyword API; no kernel or GPU execution.

This discriminates an unsupported-constructor-keyword hypothesis. It does not
qualify FlashAttention's inline assembly, location propagation or kernel output.
"""

import importlib.metadata
import inspect
import json

from cutlass import Float32


def main():
    signature = inspect.signature(Float32)
    signature.bind(1.25, loc=None, ip=None)
    value = Float32(1.25, loc=None, ip=None)
    if value.value != 1.25:
        raise RuntimeError("constructor value changed")
    print(
        json.dumps(
            {
                "status": "PASS",
                "cutlass_dsl": importlib.metadata.version("nvidia-cutlass-dsl"),
                "signature": str(signature),
                "scope": "Constructor accepts loc/ip keywords; no IR emission, SASS or kernel correctness claim",
            }
        )
    )


if __name__ == "__main__":
    main()
