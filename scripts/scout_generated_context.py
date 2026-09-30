"""Bounded contract context for observed hash-named CUDA variants; no execution."""

import re
from urllib.parse import unquote, urlsplit


def contract_requests(packet, snapshot):
    """Return at most one local registry window and its README.

    These are context hints, not proof that a file was generated or correct.
    Only a same-repository pinned primary source and observed tree members qualify.
    Ambiguous or unsupported conventions leave the ordinary source search intact.
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
            readme = directory + "/README.md"
            if readme in files:
                requests.append({"path": readme, "start": 1, "max_lines": 60})
            return requests
        directories.pop()
    return []
