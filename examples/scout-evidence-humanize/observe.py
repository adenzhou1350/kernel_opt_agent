"""Source-bound public observation; no implementation copy, model or install."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--arm", choices=("parent", "head"), required=True)
    args = parser.parse_args()
    if any(name == "humanize" or name.startswith("humanize.") for name in sys.modules):
        raise ValueError("start a fresh process for each package")
    snapshot = json.loads(Path(__file__).with_name("observed.json").read_text(encoding="utf-8"))
    package = args.package.resolve(strict=True)
    expected = {**snapshot["module_sha256"], "time.py": snapshot["arms"][args.arm]["time_sha256"]}
    for name, digest in expected.items():
        path = package / "humanize" / name
        if not path.resolve(strict=True).is_relative_to(package):
            raise ValueError("package module escapes the supplied root")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("source identity mismatch: " + name)
    sys.path.insert(0, str(package))
    import humanize
    from humanize import time as humanize_time

    if not Path(humanize_time.__file__).resolve().is_relative_to(package):
        raise ValueError("wrong imported package")
    values = [humanize.naturaldelta(dt.timedelta(days=365*x)) for x in (2.4, 2.6, 2.9, 3)]
    normal = humanize.naturaldelta(dt.timedelta(days=7))
    for name, digest in expected.items():
        if hashlib.sha256((package / "humanize" / name).read_bytes()).hexdigest() != digest:
            raise ValueError("source changed during observation: " + name)
    print(json.dumps({"runtime": sys.version, "commit": snapshot["arms"][args.arm]["commit"],
                      "values": values, "ordinary_control": normal,
                      "scope": "Public native observation, not full test/packaging/locale qualification."}))
    if normal != "7 days":
        raise ValueError("ordinary control failed")


if __name__ == "__main__":
    main()
