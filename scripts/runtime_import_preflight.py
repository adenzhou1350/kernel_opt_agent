#!/usr/bin/env python3
"""Verify the exact Python import closure before GPU or service startup."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from schema_utils import validate_instance

REQUEST_SCHEMA = "runtime_import_preflight_request.schema.json"
RESULT_SCHEMA = "runtime_import_preflight_result.schema.json"
REQUEST_VERSION = "runtime-import-preflight-request-v1"
RESULT_VERSION = "runtime-import-preflight-result-v1"
CLAIM_BOUNDARY = (
    "CPU_PROCESS_IMPORT_PATH_AND_TRANSITIVE_MODULE_PREFLIGHT_ONLY_NOT_NATIVE_BUILD_"
    "GPU_SERVICE_CORRECTNESS_PERFORMANCE_OR_EXECUTION_AUTHORIZATION"
)

WORKER = r"""
import hashlib
import importlib
import json
import pathlib
import sys


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


probe = json.loads(sys.stdin.read())
try:
    module = importlib.import_module(probe["module"])
    module_file_raw = getattr(module, "__file__", None)
    module_file = (
        pathlib.Path(module_file_raw).resolve() if module_file_raw else None
    )
    attribute_module = None
    if probe["attribute"] is not None:
        attribute = getattr(module, probe["attribute"])
        attribute_module = getattr(attribute, "__module__", None)
    forbidden = sorted(
        name
        for name in sys.modules
        if any(
            name == prefix or name.startswith(prefix + ".")
            for prefix in probe["forbidden_loaded_module_prefixes"]
        )
    )
    result = {
        "imported": True,
        "module_file": module_file.as_posix() if module_file else None,
        "module_sha256": (
            sha256_file(module_file) if module_file and module_file.is_file() else None
        ),
        "attribute_module": attribute_module,
        "forbidden_loaded_modules": forbidden,
        "error_type": None,
        "error": None,
    }
except BaseException as error:
    result = {
        "imported": False,
        "module_file": None,
        "module_sha256": None,
        "attribute_module": None,
        "forbidden_loaded_modules": [],
        "error_type": type(error).__name__,
        "error": str(error)[:2000],
    }
print("KERNEL_OPT_IMPORT_RESULT=" + json.dumps(result, sort_keys=True))
"""


def root() -> Path:
    return Path(__file__).resolve().parents[1]


def read_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected a JSON object: {path}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def validate(value: dict, schema_name: str, label: str) -> None:
    schema = read_object(root() / "schemas" / schema_name)
    errors = validate_instance(value, schema)
    if errors:
        raise ValueError(f"invalid {label}: " + "; ".join(errors))


def resolved_absolute(raw: str, label: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{label} must be absolute")
    return path.resolve(strict=False)


def same_path(left: str | None, right: Path) -> bool:
    if left is None:
        return False
    try:
        return Path(left).resolve(strict=False) == right
    except (OSError, RuntimeError):
        return False


def probe_import(
    interpreter: Path,
    working_directory: Path,
    environment: dict[str, str],
    specification: dict,
    timeout_seconds: float,
) -> dict:
    probe = {
        "module": specification["module"],
        "attribute": specification["attribute"],
        "forbidden_loaded_module_prefixes": specification[
            "forbidden_loaded_module_prefixes"
        ],
    }
    try:
        completed = subprocess.run(
            [str(interpreter), "-c", WORKER],
            input=json.dumps(probe, sort_keys=True),
            cwd=working_directory,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return {
            "import_id": specification["import_id"],
            "module": specification["module"],
            "attribute": specification["attribute"],
            "status": "BLOCKED",
            "module_file": None,
            "module_sha256": None,
            "attribute_module": None,
            "forbidden_loaded_modules": [],
            "error_type": "TimeoutExpired",
            "error": f"import exceeded {timeout_seconds:g} seconds",
            "blockers": ["IMPORT_TIMEOUT"],
        }

    blockers: list[str] = []
    result_lines = [
        line.removeprefix("KERNEL_OPT_IMPORT_RESULT=")
        for line in completed.stdout.splitlines()
        if line.startswith("KERNEL_OPT_IMPORT_RESULT=")
    ]
    try:
        if len(result_lines) != 1:
            raise json.JSONDecodeError("worker result sentinel count is not one", "", 0)
        observation = json.loads(result_lines[0])
    except json.JSONDecodeError:
        observation = {
            "imported": False,
            "module_file": None,
            "module_sha256": None,
            "attribute_module": None,
            "forbidden_loaded_modules": [],
            "error_type": "InvalidWorkerOutput",
            "error": (completed.stdout + "\n" + completed.stderr)[-2000:],
        }
    if completed.returncode != 0 or not observation.get("imported"):
        blockers.append("IMPORT_FAILED")
    expected_file = resolved_absolute(
        specification["expected_module_file"]["path"],
        f"{specification['import_id']} expected module file",
    )
    if observation.get("imported") and not same_path(
        observation.get("module_file"), expected_file
    ):
        blockers.append("MODULE_FILE_MISMATCH")
    if (
        observation.get("imported")
        and observation.get("module_sha256")
        != specification["expected_module_file"]["sha256"]
    ):
        blockers.append("MODULE_SHA256_MISMATCH")
    expected_attribute_module = specification["expected_attribute_module"]
    if (
        observation.get("imported")
        and expected_attribute_module is not None
        and observation.get("attribute_module") != expected_attribute_module
    ):
        blockers.append("ATTRIBUTE_MODULE_MISMATCH")
    if observation.get("forbidden_loaded_modules"):
        blockers.append("FORBIDDEN_TRANSITIVE_IMPORT")
    blockers = sorted(set(blockers))
    return {
        "import_id": specification["import_id"],
        "module": specification["module"],
        "attribute": specification["attribute"],
        "status": "PASS" if not blockers else "BLOCKED",
        "module_file": observation.get("module_file"),
        "module_sha256": observation.get("module_sha256"),
        "attribute_module": observation.get("attribute_module"),
        "forbidden_loaded_modules": observation.get("forbidden_loaded_modules", []),
        "error_type": observation.get("error_type"),
        "error": observation.get("error"),
        "blockers": blockers,
    }


def evaluate(
    request: dict, request_path: Path, inherited_environment: dict[str, str]
) -> dict:
    validate(request, REQUEST_SCHEMA, "runtime import preflight request")
    import_ids = [item["import_id"] for item in request["imports"]]
    if len(import_ids) != len(set(import_ids)):
        raise ValueError("import_id values must be unique")

    interpreter = resolved_absolute(request["interpreter"]["path"], "interpreter path")
    working_directory = resolved_absolute(
        request["working_directory"], "working directory"
    )
    python_paths = [
        resolved_absolute(path, "python path") for path in request["python_paths"]
    ]
    base_blockers: list[str] = []
    if not interpreter.is_file():
        base_blockers.append("INTERPRETER_MISSING")
    elif sha256_file(interpreter) != request["interpreter"]["sha256"]:
        base_blockers.append("INTERPRETER_SHA256_MISMATCH")
    if not working_directory.is_dir():
        base_blockers.append("WORKING_DIRECTORY_MISSING")
    if any(not path.is_dir() for path in python_paths):
        base_blockers.append("PYTHON_PATH_MISSING")

    environment = dict(inherited_environment)
    environment.update(request["environment_overrides"])
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPATH"] = os.pathsep.join(str(path) for path in python_paths)
    results = []
    if not base_blockers:
        results = [
            probe_import(
                interpreter,
                working_directory,
                environment,
                specification,
                request["timeout_seconds"],
            )
            for specification in request["imports"]
        ]
    blockers = list(base_blockers)
    blockers.extend(
        f"{result['import_id']}:{blocker}"
        for result in results
        for blocker in result["blockers"]
    )
    blockers = sorted(set(blockers))
    output = {
        "schema_version": RESULT_VERSION,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "candidate_id": request["candidate_id"],
        "request_identity": {
            "path": request_path.resolve().as_posix(),
            "sha256": sha256_file(request_path),
        },
        "decision": (
            "BLOCKED_RUNTIME_IMPORT" if blockers else "READY_FOR_NEXT_PREFLIGHT"
        ),
        "interpreter": {
            "path": interpreter.as_posix(),
            "sha256": sha256_file(interpreter) if interpreter.is_file() else None,
        },
        "working_directory": working_directory.as_posix(),
        "python_paths": [path.as_posix() for path in python_paths],
        "effective_environment_sha256": canonical_sha256(environment),
        "imports": results,
        "blockers": blockers,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    validate(output, RESULT_SCHEMA, "runtime import preflight result")
    return output


def request_template() -> dict:
    return {
        "schema_version": REQUEST_VERSION,
        "candidate_id": "replace-me",
        "interpreter": {
            "path": "/absolute/path/to/python",
            "sha256": "0" * 64,
        },
        "working_directory": "/absolute/source/root",
        "python_paths": ["/absolute/source/root"],
        "environment_overrides": {
            "CUDA_VISIBLE_DEVICES": "",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        },
        "timeout_seconds": 30,
        "imports": [
            {
                "import_id": "quant-config-only",
                "module": "package.models.optional_model",
                "attribute": "QuantConfig",
                "expected_module_file": {
                    "path": "/absolute/source/root/package/models/optional_model/__init__.py",
                    "sha256": "0" * 64,
                },
                "expected_attribute_module": "package.models.optional_model.quant_config",
                "forbidden_loaded_module_prefixes": [
                    "package.models.optional_model.cuda_backend"
                ],
            }
        ],
    }


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print-template", action="store_true")
    parser.add_argument("--request", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.print_template:
        if args.request or args.output:
            parser.error("--print-template does not accept --request or --output")
        print(json.dumps(request_template(), indent=2, sort_keys=True))
        return 0
    if args.request is None:
        parser.error("--request is required")
    request_path = args.request.resolve()
    result = evaluate(read_object(request_path), request_path, dict(os.environ))
    if args.output:
        atomic_json(args.output.resolve(), result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["decision"] == "READY_FOR_NEXT_PREFLIGHT" else 2


if __name__ == "__main__":
    raise SystemExit(main())
