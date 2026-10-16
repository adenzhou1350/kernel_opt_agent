"""Observe reviewed Click source; a fresh process, not an untrusted-code sandbox."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--utils-sha256", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{64}", args.utils_sha256):
        parser.error("--utils-sha256 must be a full lowercase SHA256")
    root = args.source.resolve(strict=True)
    expected = (root / "src/click/utils.py").resolve(strict=True)
    if not expected.is_relative_to(root):
        parser.error("utils.py resolves outside source")
    if hashlib.sha256(expected.read_bytes()).hexdigest() != args.utils_sha256:
        parser.error("reviewed utils.py hash mismatch")
    sys.path.insert(0, str(root / "src"))
    import click
    import click.utils

    if Path(click.utils.__file__).resolve() != expected:
        parser.error("imported Click utils is not the reviewed file")
    if not Path(click.__file__).resolve().is_relative_to(root):
        parser.error("imported Click package is outside source")
    cases = [
        ("Weigh apples vs. pears.", 30),
        ("Weigh apples vs. pears and plums.", 20),
        ("Pick a fruit.", 20),
        ("", 10),
    ]
    values = [
        click.Command("fruit", help=text).get_short_help_str(limit=limit)
        for text, limit in cases
    ]
    if hashlib.sha256(expected.read_bytes()).hexdigest() != args.utils_sha256:
        parser.error("reviewed source changed during observation")
    print(json.dumps({"values": values, "python": sys.version,
                      "source": str(expected), "utils_sha256": args.utils_sha256}))


if __name__ == "__main__":
    main()
