#!/usr/bin/env python3
"""Small, local, curated lesson library; retrieval never decides readiness."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import tempfile
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_DIRECTORY = Path(__file__).resolve().parents[1] / "knowledge" / "lessons"
TEXT_FIELDS = ("id", "title", "applies_when", "lesson", "avoid_when", "status")
CAUTION = "Advisory matches only: read applies_when, avoid_when and evidence scope; retrieval does not establish correctness, performance or readiness."


def normalized(value: str) -> str:
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", value).casefold()))


def public_url(value: str) -> bool:
    """Reject obvious local/private URLs without fetching or claiming accessibility."""
    try:
        url = urlsplit(value)
        _ = url.port  # Reject malformed port syntax as well as malformed hosts.
        host = (url.hostname or "").rstrip(".").lower()
        if url.scheme not in {"http", "https"} or url.username or url.password:
            return False
        if (
            not host
            or "." not in host
            or host.endswith((".local", ".internal", ".localhost"))
        ):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return not host.replace(".", "").isdigit() and not any(
                c.isspace() for c in value
            )
    except ValueError:
        return False


def validate(card: dict) -> None:
    if not isinstance(card, dict) or set(card) != set(TEXT_FIELDS) | {"evidence"}:
        raise ValueError(
            "A lesson needs exactly: " + ", ".join((*TEXT_FIELDS, "evidence"))
        )
    for key in TEXT_FIELDS:
        if not isinstance(card[key], str) or not normalized(card[key]):
            raise ValueError(f"{key} must be nonempty text")
    if len(card["id"]) > 80 or not re.fullmatch(
        r"[a-z0-9]+(?:-[a-z0-9]+)*", card["id"]
    ):
        raise ValueError("id must be a lowercase ASCII slug of at most 80 characters")
    if re.fullmatch(r"con|prn|aux|nul|com[1-9]|lpt[1-9]", card["id"]):
        raise ValueError("id must not be a reserved Windows filename")
    if card["status"] not in {"hypothesis", "validated", "counterexample"}:
        raise ValueError("status must be hypothesis, validated or counterexample")
    evidence = card["evidence"]
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("evidence must contain at least one public URL and scope note")
    for item in evidence:
        if not isinstance(item, dict) or set(item) != {"url", "note"}:
            raise ValueError("Each evidence item needs exactly url and note")
        if not isinstance(item["url"], str) or not public_url(item["url"]):
            raise ValueError(
                "evidence URL must be an HTTP(S) public URL without credentials"
            )
        if not isinstance(item["note"], str) or not normalized(item["note"]):
            raise ValueError(
                "evidence note must explain what the public source supports"
            )


def read_card(path: Path) -> dict:
    try:
        card = json.loads(path.read_text(encoding="utf-8-sig"))
        validate(card)
    except (ValueError, OSError) as exc:
        raise ValueError(f"{path}: {exc}") from exc
    return card


def read_cards(directory: Path) -> list[tuple[Path, dict]]:
    directory = directory.resolve()
    if not directory.is_dir():
        raise ValueError(f"Lesson directory does not exist: {directory}")
    cards = []
    seen = {key: {} for key in ("id", "title", "lesson")}
    for path in sorted(directory.glob("*.json")):
        if path.is_symlink() or path.resolve().parent != directory:
            raise ValueError(
                f"Lesson must be a regular file inside the library: {path}"
            )
        card = read_card(path)
        if path.name != card["id"] + ".json":
            raise ValueError(f"Filename must match lesson id: {path}")
        for key, values in seen.items():
            value = normalized(card[key])
            if value in values:
                raise ValueError(f"Duplicate {key}: {path.name} and {values[value]}")
            values[value] = path.name
        cards.append((path, card))
    return cards


def add_note(
    card: dict, directory: Path = DEFAULT_DIRECTORY, replace: bool = False
) -> dict:
    validate(card)
    directory = directory.resolve()
    cards = read_cards(directory) if directory.exists() else []
    current = next(((p, c) for p, c in cards if c["id"] == card["id"]), None)
    if current and current[1] == card:
        return {"action": "unchanged", "id": card["id"], "source": str(current[0])}
    if current and not replace:
        raise ValueError(
            f"{card['id']} already exists; review it and use --replace to update"
        )
    if replace and not current:
        raise ValueError("--replace requires an existing lesson with the same id")
    for path, existing in cards:
        if existing["id"] == card["id"]:
            continue
        if any(
            normalized(existing[k]) == normalized(card[k]) for k in ("title", "lesson")
        ):
            if current:
                raise ValueError(
                    f"Replacement duplicates existing lesson {existing['id']}"
                )
            return {"action": "duplicate", "id": existing["id"], "source": str(path)}
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (card["id"] + ".json")
    if target.is_symlink() or target.resolve().parent != directory:
        raise ValueError("Lesson destination must stay inside the library")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=directory, suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(card, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {
        "action": "replaced" if current else "added",
        "id": card["id"],
        "source": str(target),
    }


def search(query: str, directory: Path = DEFAULT_DIRECTORY, limit: int = 3) -> dict:
    terms = set(normalized(query).split())
    if not terms or limit < 1:
        raise ValueError("search needs a nonempty query and a positive limit")
    matches = []
    for path, card in read_cards(directory):
        score = sum(
            weight * len(terms & set(normalized(card[key]).split()))
            for key, weight in (
                ("id", 3),
                ("title", 3),
                ("applies_when", 2),
                ("lesson", 1),
                ("avoid_when", 1),
            )
        )
        if score:
            matches.append({"score": score, "source": str(path), "card": card})
    matches.sort(key=lambda match: (-match["score"], match["card"]["id"]))
    return {"query": query, "caution": CAUTION, "matches": matches[:limit]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=DEFAULT_DIRECTORY)
    commands = parser.add_subparsers(dest="command", required=True)
    find = commands.add_parser("search", help="Find a few advisory curated lessons")
    find.add_argument("query")
    find.add_argument("--limit", type=int, default=3)
    add = commands.add_parser(
        "add", help="Add a reusable public lesson or update its stable id"
    )
    add.add_argument("--file", type=Path, required=True)
    add.add_argument("--replace", action="store_true")
    commands.add_parser(
        "check", help="Check card fields, filenames, links and duplicates offline"
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "search":
            result = search(args.query, args.directory, args.limit)
        elif args.command == "add":
            result = add_note(read_card(args.file), args.directory, args.replace)
        else:
            cards = read_cards(args.directory)
            result = {
                "action": "checked",
                "count": len(cards),
                "directory": str(args.directory.resolve()),
            }
    except (ValueError, OSError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
