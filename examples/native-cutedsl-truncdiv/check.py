"""CPU-only scalar/IR witness for an explicitly reviewed CuTeDSL math module.

Not a sandbox, TileLang compiler test, vector check or new discovery benchmark.
"""
import argparse
from fractions import Fraction
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviewed-source", required=True, type=Path)
    parser.add_argument("--sha256", required=True)
    args = parser.parse_args()
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "":
        parser.error("run in a fresh process with CUDA_VISIBLE_DEVICES='' before imports")
    raw = args.reviewed_source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != args.sha256:
        parser.error("reviewed source SHA256 mismatch")
    started = time.monotonic()
    import cutlass
    import torch
    from cutlass._mlir import ir, passmanager
    from cutlass._mlir.dialects import func

    assert importlib.metadata.version("nvidia-cutlass-dsl") == "4.7.1"
    assert not torch.cuda.is_initialized()
    spec = importlib.util.spec_from_file_location("reviewed_cutedsl_math", args.reviewed_source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows, dynamic = [], []
    for cls, bits in ((cutlass.Int8, 8), (cutlass.Int16, 16),
                      (cutlass.Int32, 32), (cutlass.Int64, 64)):
        pairs = [(-7, 3), (7, -3), (-7, -3), (-1, 3), (0, 3), (7, 3),
                 (-(2 ** (bits - 1)), 3), (2 ** (bits - 1) - 1, 3)]
        for a, b in pairs:
            expected = int(Fraction(a, b))
            literal = module.truncdiv(a, b)
            assert literal == expected, (a, b, literal, expected)
            row = dict(dtype=cls.__name__, a=a, b=b, expected=expected, literal=literal)
            for name in ("cutlass_floor", "helper"):
                with ir.Context() as ctx, ir.Location.unknown():
                    ctx.allow_unregistered_dialects = True
                    native_module = ir.Module.create()
                    with ir.InsertionPoint(native_module.body):
                        ty = ir.IntegerType.get_signless(bits)
                        fn = func.FuncOp("constant_div", ir.FunctionType.get([], [ty]))
                        block = fn.add_entry_block()
                        with ir.InsertionPoint(block):
                            q = cls(a) // cls(b) if name == "cutlass_floor" else module.truncdiv(cls(a), cls(b))
                            func.ReturnOp([q.ir_value()])
                    assert native_module.operation.verify()
                    passmanager.PassManager.parse("builtin.module(canonicalize)").run(native_module.operation)
                    folded = native_module.body.operations[0].regions[0].blocks[0]
                    constants = [op.attributes["value"].value for op in folded.operations
                                 if op.operation.name == "arith.constant"]
                    assert len(constants) == 1, str(native_module)
                    row[name] = constants[0]
            assert row["helper"] == expected, row
            rows.append(row)
        with ir.Context() as ctx, ir.Location.unknown():
            ctx.allow_unregistered_dialects = True
            native_module = ir.Module.create()
            with ir.InsertionPoint(native_module.body):
                ty = ir.IntegerType.get_signless(bits)
                fn = func.FuncOp("dynamic_div", ir.FunctionType.get([ty, ty], [ty]))
                block = fn.add_entry_block()
                with ir.InsertionPoint(block):
                    q = module.truncdiv(*[cls(v) for v in block.arguments])
                    func.ReturnOp([q.ir_value()])
            assert native_module.operation.verify()
            operations = [op.operation.name for op in block.operations]
            assert operations == ["arith.divsi", "func.return"], operations
            dynamic.append(dict(dtype=cls.__name__, operations=operations))
    assert hashlib.sha256(args.reviewed_source.read_bytes()).hexdigest() == args.sha256
    assert not torch.cuda.is_initialized()
    print(json.dumps(dict(source_sha256=args.sha256, python=sys.version,
        cutlass_version=importlib.metadata.version("nvidia-cutlass-dsl"),
        cutlass_path=cutlass.__file__, torch_version=torch.__version__, rows=rows,
        dynamic=dynamic, cutlass_floor_mismatches=sum(r["cutlass_floor"] != r["expected"] for r in rows),
        helper_mismatches=0, cuda_initialized=False, wall_seconds=time.monotonic()-started,
        scope="SCALAR_HELPER_AND_NATIVE_MLIR_FOLDING_NOT_TILELANG_COMPILER_VECTOR_OR_GPU")))


if __name__ == "__main__":
    main()
