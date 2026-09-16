"""Read-only NVIDIA topology snapshots with checked management identities.

Only the GPU/NIC matrix form of ``nvidia-smi topo -m`` is supported. NVIDIA's
documented tokens describe connectivity, not measured speed or P2P capability:
https://docs.nvidia.com/deploy/nvidia-smi/#topology
"""

from __future__ import annotations

import csv
import re
import shutil
import subprocess


TIMEOUT_SECONDS = 2
NODE = re.compile(r"(?:GPU|NIC)(?:0|[1-9][0-9]*)\Z")
RELATIONSHIP = re.compile(r"(?:X|SYS|NODE|PHB|PXB|PIX|NV[1-9][0-9]*)\Z")
AFFINITIES = re.compile(r"(?:CPU Affinity(?: NUMA Affinity)?(?: GPU NUMA ID)?)?\Z")
AFFINITY_KEYS = {
    "CPU Affinity": "cpu_affinity",
    "NUMA Affinity": "numa_affinity",
    "GPU NUMA ID": "gpu_numa_id",
}


def _identities(rows: list) -> dict[int, str]:
    identities = {}
    for row in rows:
        if len(row) != 2:
            raise ValueError("Identity rows must contain exactly index and UUID.")
        index, uuid = row
        if (
            isinstance(index, bool)
            or not re.fullmatch(r"0|[1-9][0-9]*", str(index))
            or not isinstance(uuid, str)
            or not uuid.startswith("GPU-")
            or uuid.strip() != uuid
            or len(uuid) <= 4
        ):
            raise ValueError("Malformed GPU index or UUID.")
        index = int(index)
        if index in identities or uuid in identities.values():
            raise ValueError("Duplicate GPU index or UUID.")
        identities[index] = uuid
    if not identities:
        raise ValueError("No GPU identities were supplied or reported.")
    return identities


def _matrix(raw: str, identities: dict[int, str]) -> tuple[list, dict, dict]:
    lines = [line for line in raw.splitlines() if line.strip()]
    if not lines:
        raise ValueError("No topology matrix was reported.")
    header = lines[0].split()
    nodes = []
    for token in header:
        if not NODE.fullmatch(token):
            break
        nodes.append(token)
    suffix = " ".join(header[len(nodes) :])
    if not nodes or len(set(nodes)) != len(nodes) or not AFFINITIES.fullmatch(suffix):
        raise ValueError(
            "Unsupported or malformed topology header, or duplicate labels."
        )
    gpu_labels = {f"GPU{index}": uuid for index, uuid in identities.items()}
    if {node for node in nodes if node.startswith("GPU")} != set(gpu_labels):
        raise ValueError(
            "Topology GPU labels are missing or unknown in the checked inventory."
        )
    affinity_keys = [key for label, key in AFFINITY_KEYS.items() if label in suffix]
    affinity_count = len(affinity_keys)
    affinities = {}
    rows = {}
    for line in lines[1:]:
        parts = line.split()
        if parts == ["Legend:"] or parts == ["NIC", "Legend:"]:
            break
        label = parts[0]
        if label not in nodes or label in rows:
            raise ValueError("Unknown or duplicate topology row label.")
        values = parts[1 : len(nodes) + 1]
        tail_count = len(parts) - 1 - len(nodes)
        if (
            len(values) != len(nodes)
            or any(not RELATIONSHIP.fullmatch(value) for value in values)
            or tail_count < 0
            or tail_count > affinity_count
        ):
            raise ValueError("Unsupported relationship or malformed topology row.")
        rows[label] = values
        if label.startswith("GPU"):
            tail = parts[len(nodes) + 1 :]
            if not tail:
                tail = [""] * affinity_count
            elif len(tail) != affinity_count:
                # Whitespace splitting loses empty cells. Preserve explicit tab
                # columns when available; never shift a value into a guessed column.
                matrix_end = list(re.finditer(r"\S+", line))[len(nodes)].end()
                cells = line[matrix_end:].split("\t")
                if (
                    cells[0].strip()
                    or len(cells) != affinity_count + 1
                    or any(len(cell.split()) > 1 for cell in cells[1:])
                ):
                    raise ValueError("Ambiguous or malformed empty affinity columns.")
                tail = [cell.strip() for cell in cells[1:]]
            affinities[gpu_labels[label]] = dict(zip(affinity_keys, tail))
    if set(rows) != set(nodes):
        raise ValueError("Topology matrix is missing one or more labelled rows.")
    edges = []
    for i, source in enumerate(nodes):
        if rows[source][i] != "X":
            raise ValueError("Topology matrix has a malformed self relationship.")
        for j in range(i + 1, len(nodes)):
            target = nodes[j]
            relationship = rows[source][j]
            if relationship == "X" or relationship != rows[target][i]:
                raise ValueError(
                    "Topology matrix has an inconsistent pair relationship."
                )
            edges.append(
                {
                    "source": gpu_labels.get(source, source),
                    "target": gpu_labels.get(target, target),
                    "relationship": relationship,
                    "bandwidth_bytes_per_second": None,
                }
            )
    return edges, gpu_labels, affinities


def inspect_topology(devices: list[dict]) -> dict:
    """Observe one undirected edge per pair, never using CSV/matrix row order.

    At most three read-only commands run, each with a two-second timeout. The
    inventory's entire index/UUID mapping must equal both identity queries.
    Affinity values are observed strings, keyed by UUID; absent header columns
    are omitted and explicit blank cells remain empty strings. Failed checks
    discard edges and affinities while retaining the unmodified matrix text.
    """
    result = {
        "status": "UNAVAILABLE",
        "edges": [],
        "affinities": {},
        "raw": "",
        "evidence": {"commands": []},
        "unknowns": [
            "Topology does not establish bandwidth, P2P eligibility, RDMA capability, "
            "NIC usefulness, internal SM/L2 routing, or permission to use a device.",
            "Identity checks bracket the topology query; they are not an atomic snapshot.",
        ],
    }
    unknowns = result["unknowns"]
    try:
        expected = _identities(
            [[device.get("index"), device.get("uuid")] for device in devices]
        )
    except (AttributeError, TypeError, ValueError) as error:
        unknowns.append(f"Management inventory identity unavailable: {error}")
        return result
    smi = shutil.which("nvidia-smi")
    if not smi:
        unknowns.append(
            "nvidia-smi executable not found on PATH; topology unavailable."
        )
        return result

    def query(arguments):
        argv = [smi, *arguments]
        evidence = {"argv": argv, "returncode": None, "stdout": "", "stderr": ""}
        result["evidence"]["commands"].append(evidence)
        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            evidence["error"] = f"{type(error).__name__}: {error}"
            if isinstance(error, subprocess.TimeoutExpired):
                for key in ("stdout", "stderr"):
                    value = getattr(error, key, None) or ""
                    evidence[key] = (
                        value.decode("utf-8", errors="replace")
                        if isinstance(value, bytes)
                        else value
                    )
            unknowns.append(evidence["error"])
            return evidence
        evidence.update(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
        if completed.returncode:
            evidence["error"] = (
                f"nvidia-smi exited {completed.returncode}: "
                + (completed.stderr.strip() or completed.stdout.strip())[:1000]
            )
            unknowns.append(evidence["error"])
        return evidence

    def identity_query():
        evidence = query(["--query-gpu=index,uuid", "--format=csv,noheader,nounits"])
        if evidence["returncode"] != 0:
            return None
        try:
            rows = csv.reader(
                evidence["stdout"].splitlines(), skipinitialspace=True, strict=True
            )
            return _identities(
                [[value.strip() for value in row] for row in rows if row]
            )
        except (csv.Error, ValueError) as error:
            unknowns.append(f"Identity query unavailable: {error}")
            return None

    before = identity_query()
    if before is None:
        return result
    if before != expected:
        result["status"] = "IDENTITY_CHANGED"
        unknowns.append(
            "GPU index/UUID mapping differs from the supplied management inventory."
        )
        return result
    matrix = query(["topo", "-m"])
    result["raw"] = matrix["stdout"]
    after = identity_query()
    if after is None:
        unknowns.append(
            "Post-topology identity could not be verified; no edges attached."
        )
        return result
    if after != expected:
        result["status"] = "IDENTITY_CHANGED"
        unknowns.append(
            "GPU index/UUID mapping changed after the topology query; no edges attached."
        )
        return result
    if matrix["returncode"] != 0:
        return result
    try:
        edges, gpu_labels, affinities = _matrix(result["raw"], expected)
    except ValueError as error:
        unknowns.append(f"Topology parsing unavailable: {error}")
        return result
    result["status"] = "OBSERVED"
    result["edges"] = edges
    result["affinities"] = affinities
    result["evidence"]["gpu_labels"] = gpu_labels
    if any(
        edge[endpoint].startswith("NIC")
        for edge in edges
        for endpoint in ("source", "target")
    ):
        unknowns.append(
            "NIC labels are non-GPU matrix labels only; their stable device identities "
            "were not independently verified. Any NIC legend is retained only as raw output."
        )
    if not edges:
        unknowns.append("Single-device matrix has no inter-device edges to report.")
    return result
