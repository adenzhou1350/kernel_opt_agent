"""Bounded contract context for observed hash-named CUDA variants; no execution."""

import re
from urllib.parse import unquote, urlsplit


def contract_requests(packet, snapshot, *, hints=""):
    """Return a local registry and one bounded contract window.

    These are context hints, not proof that a file was generated or correct.
    Only a same-repository pinned primary source and observed tree members qualify.
    Ambiguous or unsupported conventions leave the ordinary source search intact.
    When a paired backend exists and there is a focused question, use it instead
    of the README. The backend is a caller hint, not proof of reachability.
    """
    sources = packet.get("sources", [])
    if not sources:
        return []
    url = urlsplit(sources[0].get("url", ""))
    repo = packet.get("repo", "")
    prefix = f"/{repo}/"
    if url.scheme != "https" or url.netloc != "raw.githubusercontent.com":
        return []
    if url.query or url.fragment or not repo or not url.path.startswith(prefix):
        return []
    parts = url.path[len(prefix) :].split("/", 1)
    if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{40}", parts[0]):
        return []
    path = unquote(parts[1])
    files = set(snapshot["files"])
    if path not in files or any(part in {"", ".", ".."} for part in path.split("/")):
        return []
    match = re.fullmatch(
        r"(.+_[0-9a-f]{8,64})_(?:kernel|binding)\.cu", path.rsplit("/", 1)[-1]
    )
    if match is None:
        return []
    module = match[1]
    directories = path.split("/")[:-1]
    while directories:
        directory = "/".join(directories)
        registries = sorted(
            p
            for p in files
            if p.rsplit("/", 1)[0] == directory
            and (p.endswith("_jit.py") or p.rsplit("/", 1)[-1] == "registry.py")
        )
        if len(registries) > 1:
            return []
        if registries:
            requests = [
                {
                    "path": registries[0],
                    "hints": module,
                    "exact_hint": f': "{module}"',
                    "max_lines": 80,
                }
            ]
            # A naming convention is enough to select a source to inspect, not
            # to conclude that it launches this variant. Never expand the read
            # count or search another directory for a guessed backend.
            registry = registries[0]
            backend = registry[: -len("_jit.py")] + "_backend.py"
            bounded_hints = hints[:2000] if isinstance(hints, str) else ""
            if (
                registry.endswith("_jit.py")
                and backend in files
                and bounded_hints.strip()
            ):
                requests.append(
                    {
                        "path": backend,
                        "hints": bounded_hints,
                        "request_hints": bounded_hints,
                        "max_lines": 60,
                    }
                )
                return requests
            readme = directory + "/README.md"
            if readme in files:
                requests.append({"path": readme, "start": 1, "max_lines": 60})
            return requests
        directories.pop()
    return []
