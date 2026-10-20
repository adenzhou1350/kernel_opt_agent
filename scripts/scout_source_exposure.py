"""Compare reviewed source lines with one saved Scout request, without execution.

This answers a request-content question, not whether a provider received/read
the prompt, a model missed a defect, or a selector improved semantic recall.
The expected source must be reviewed separately, e.g. from scout_git_source.
Never union different jobs to claim that one request contained all evidence.
"""

import argparse
import hashlib
import json
import re
from pathlib import Path

import kimi_scout as scout
from scout_evidence_acquisition import pinned_raw_url


MAX_RECORD_BYTES = 262_144
MARKER = "\nUNTRUSTED PUBLIC EVIDENCE PACKET:\n"
BOUNDARY = (
    "Saved request content relative to caller-reviewed expected lines only; "
    "not public provenance authentication, provider receipt/attention, "
    "defect detection, source reachability, semantic recall or study efficacy."
)


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON field")
        value[key] = item
    return value


def _parse(raw):
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_RECORD_BYTES:
        raise ValueError("record exceeds bound or is not UTF-8 text")
    return json.loads(raw, object_pairs_hook=_object)


def _lines(text):
    if not isinstance(text, str) or not text or len(text.encode("utf-8")) > MAX_RECORD_BYTES:
        raise ValueError("expected nonempty bounded numbered source")
    result = {}
    previous = 0
    # Conventional newlines only: Unicode separators can be source literals.
    for line in text.replace("\r\n", "\n").split("\n"):
        if line == "":
            continue  # scout_git_source separates explicit disjoint ranges.
        match = re.fullmatch(r"([1-9][0-9]{0,7}): (.*)", line)
        if not match:
            raise ValueError("unrecognized numbered source line")
        number = int(match[1])
        if number <= previous:
            raise ValueError("source numbers must increase without duplicates")
        result[number] = match[2]
        previous = number
    if not result:
        raise ValueError("numbered source has no lines")
    return result


def _ranges(numbers):
    result = []
    for number in sorted(numbers):
        if result and number == result[-1][1] + 1:
            result[-1][1] = number
        else:
            result.append([number, number])
    return result


def inspect_exposure(packet_raw, request, expected):
    """Compare one exact job packet/request; do not infer coverage from metadata.

    expected is one {url,text,...} source from a reviewed pinned source packet.
    Text and numbering, not start_line/end_line or an outcome, decide presence.
    Missing/mismatched saved requests remain unknown, never zero exposure.
    """
    packet = _parse(packet_raw)
    if (not isinstance(packet, dict) or not isinstance(packet.get("sources"), list)
            or len(packet["sources"]) > 64 or not isinstance(expected, dict)
            or not pinned_raw_url(expected.get("url"))):
        raise ValueError("invalid packet or expected pinned source")
    wanted = _lines(expected.get("text"))
    if not isinstance(request, (dict, type(None))):
        raise ValueError("request must be an object or missing")
    prepared = (request is not None
                and request.get("prompt") == scout.SYSTEM + MARKER + packet_raw)
    observed, invalid = {}, False
    matching = 0
    for source in packet["sources"]:
        if not isinstance(source, dict) or source.get("url") != expected["url"]:
            continue
        matching += 1
        try:
            lines = _lines(source.get("text"))
        except ValueError:
            invalid = True
            continue
        for number, text in lines.items():
            observed.setdefault(number, set()).add(text)
    present = {n for n, text in wanted.items() if observed.get(n) == {text}}
    conflicts = {n for n, text in wanted.items()
                 if n in observed and observed[n] != {text}}
    if invalid or conflicts:
        packet_status = "INCONSISTENT_SOURCE_LINES"
    elif not matching:
        packet_status = "NO_MATCHING_PINNED_SOURCE"
    elif len(present) == len(wanted):
        packet_status = "EXPECTED_LINES_PRESENT"
    else:
        packet_status = "EXPECTED_LINES_PARTIAL_OR_ABSENT"
    return {
        "status": packet_status if prepared else "SAVED_REQUEST_UNVERIFIED",
        "saved_request_matches_packet": prepared,
        "packet_status": packet_status,
        "expected_url": expected["url"],
        "expected_lines": len(wanted),
        "present_lines": len(present),
        "missing_ranges": _ranges(set(wanted) - present),
        "conflicting_ranges": _ranges(conflicts),
        "matching_source_entries": matching,
        "packet_sha256": hashlib.sha256(packet_raw.encode("utf-8")).hexdigest(),
        "expected_text_sha256": hashlib.sha256(expected["text"].encode("utf-8")).hexdigest(),
        "boundary": BOUNDARY,
    }


def _read(path):
    with path.open("rb") as stream:
        raw = stream.read(MAX_RECORD_BYTES + 1)
    if len(raw) > MAX_RECORD_BYTES:
        raise ValueError("input exceeds bound")
    return raw.decode("utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True, help="exact saved job packet text")
    parser.add_argument("--request", type=Path, help="existing saved .request.json; absent means unknown")
    parser.add_argument("--expected", type=Path, required=True, help="reviewed packet containing one pinned source")
    args = parser.parse_args(argv)
    try:
        expected = _parse(_read(args.expected))
        if not isinstance(expected, dict) or len(expected.get("sources", [])) != 1:
            raise ValueError("expected packet must contain exactly one source")
        result = inspect_exposure(
            _read(args.packet), _parse(_read(args.request)) if args.request else None,
            expected["sources"][0],
        )
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(json.dumps({"status": "INVALID_INPUT", "error_type": type(error).__name__, "boundary": BOUNDARY}))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
