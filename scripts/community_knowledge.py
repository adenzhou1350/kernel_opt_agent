#!/usr/bin/env python3
"""Capture and validate immutable community optimization evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from schema_utils import validate_instance, validate_json_file


API_VERSION = "2022-11-28"
SNAPSHOT_SCHEMA = "community-pr-snapshot-v1"
INDEX_SCHEMA = "community-corpus-index-v1"
EVENT_SCHEMA = "community-optimization-event-v1"
GRAPH_SCHEMA = "community-optimization-graph-v1"
MATCH_SCHEMA = "community-match-receipt-v1"
RUN_INPUT_PATHS = (
    "operator.json",
    "workload.json",
    "hardware.json",
    "models/opportunity_map.json",
)
REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
ARTIFACT_SPECS = (
    ("PULL_REQUEST", "pr.json", "application/vnd.github+json"),
    ("FILES", "files.json", "application/vnd.github+json"),
    ("COMMITS", "commits.json", "application/vnd.github+json"),
    ("ISSUE_COMMENTS", "issue_comments.json", "application/vnd.github+json"),
    ("REVIEWS", "reviews.json", "application/vnd.github+json"),
    ("REVIEW_COMMENTS", "review_comments.json", "application/vnd.github+json"),
    ("TIMELINE", "timeline.json", "application/vnd.github+json"),
    ("DIFF", "pull.diff", "application/vnd.github.v3.diff"),
)
TOKEN_ALIASES = {
    "bfloat16": "bf16",
    "float16": "fp16",
    "language": "lm",
}
TOKEN_STOPWORDS = {
    "a",
    "and",
    "for",
    "gpu",
    "in",
    "inference",
    "kernel",
    "model",
    "of",
    "on",
    "path",
    "the",
    "to",
    "vllm",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(canonical_json(value))
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_link_header(value: str | None) -> dict[str, str]:
    links: dict[str, str] = {}
    if not value:
        return links
    for item in value.split(","):
        match = re.match(r'\s*<([^>]+)>;\s*rel="([^"]+)"', item)
        if match:
            links[match.group(2)] = match.group(1)
    return links


class GitHubClient:
    def __init__(self, token: str | None = None, timeout: float = 30.0):
        self.token = token
        self.timeout = timeout
        self.api_base = "https://api.github.com"

    @property
    def authenticated(self) -> bool:
        return bool(self.token)

    def request(self, url: str, accept: str) -> tuple[bytes, dict[str, str]]:
        headers = {
            "Accept": accept,
            "User-Agent": "kernel-opt-agent-community-evidence/1",
            "X-GitHub-Api-Version": API_VERSION,
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read(), dict(response.headers.items())
        except urllib.error.HTTPError as error:
            remaining = error.headers.get("X-RateLimit-Remaining", "unknown")
            raise RuntimeError(
                f"GitHub request failed with HTTP {error.code}; "
                f"rate-limit remaining={remaining}; url={url}"
            ) from error

    def json_pages(self, path: str, accept: str) -> tuple[list[Any], list[str]]:
        url = path if path.startswith("https://") else f"{self.api_base}{path}"
        values: list[Any] = []
        urls: list[str] = []
        while url:
            payload, headers = self.request(url, accept)
            value = json.loads(payload)
            urls.append(url)
            if isinstance(value, list):
                values.extend(value)
            elif not values:
                return [value], urls
            else:
                raise ValueError(f"paginated GitHub endpoint changed JSON shape: {url}")
            url = parse_link_header(headers.get("Link")).get("next", "")
        return values, urls

    def bytes(self, url: str, accept: str) -> tuple[bytes, list[str]]:
        payload, _ = self.request(url, accept)
        return payload, [url]


def endpoint_for(repository: str, number: int, kind: str) -> str:
    prefix = f"/repos/{repository}"
    return {
        "PULL_REQUEST": f"{prefix}/pulls/{number}",
        "FILES": f"{prefix}/pulls/{number}/files?per_page=100",
        "COMMITS": f"{prefix}/pulls/{number}/commits?per_page=100",
        "ISSUE_COMMENTS": f"{prefix}/issues/{number}/comments?per_page=100",
        "REVIEWS": f"{prefix}/pulls/{number}/reviews?per_page=100",
        "REVIEW_COMMENTS": f"{prefix}/pulls/{number}/comments?per_page=100",
        "TIMELINE": f"{prefix}/issues/{number}/timeline?per_page=100",
        "DIFF": f"https://github.com/{repository}/pull/{number}.diff",
    }[kind]


def pull_summary(value: dict) -> dict:
    required = (
        "title",
        "state",
        "draft",
        "merged",
        "created_at",
        "updated_at",
        "base",
        "head",
        "user",
    )
    missing = [field for field in required if field not in value]
    if missing:
        raise ValueError(f"GitHub pull response is missing fields: {', '.join(missing)}")
    return {
        "title": value["title"],
        "author": value["user"]["login"],
        "state": value["state"],
        "draft": bool(value["draft"]),
        "merged": bool(value["merged"]),
        "created_at": value["created_at"],
        "updated_at": value["updated_at"],
        "closed_at": value.get("closed_at"),
        "merged_at": value.get("merged_at"),
        "base_sha": value["base"]["sha"],
        "head_sha": value["head"]["sha"],
        "labels": sorted({item["name"] for item in value.get("labels", [])}),
    }


def snapshot_identity(manifest: dict) -> str:
    stable = {
        "source": {
            "repository": manifest["source"]["repository"],
            "number": manifest["source"]["number"],
        },
        "pull_request": {
            "updated_at": manifest["pull_request"]["updated_at"],
            "base_sha": manifest["pull_request"]["base_sha"],
            "head_sha": manifest["pull_request"]["head_sha"],
        },
        "artifacts": [
            {"kind": item["kind"], "sha256": item["sha256"]}
            for item in manifest["artifacts"]
        ],
    }
    return sha256_bytes(canonical_json(stable))[:20]


def lifecycle(manifest: dict) -> str:
    pull = manifest["pull_request"]
    if pull["merged"]:
        return "MERGED"
    if pull["state"] == "closed":
        return "CLOSED_UNMERGED"
    return "OPEN"


def parse_source_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def artifact_source_timestamps(kind: str, value: object) -> list[datetime]:
    """Read only timestamps owned by the PR artifact, not nested repo metadata."""
    rows = value if isinstance(value, list) else [value]
    timestamps: list[datetime] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        values: list[object] = []
        if kind == "PULL_REQUEST":
            values.append(row.get("updated_at"))
        elif kind in {"ISSUE_COMMENTS", "REVIEW_COMMENTS"}:
            values.append(row.get("updated_at") or row.get("created_at"))
        elif kind == "REVIEWS":
            values.append(row.get("submitted_at"))
        elif kind == "TIMELINE":
            values.append(row.get("created_at"))
        elif kind == "COMMITS":
            commit = row.get("commit", {})
            if isinstance(commit, dict):
                for actor in ("author", "committer"):
                    record = commit.get(actor, {})
                    if isinstance(record, dict):
                        values.append(record.get("date"))
        timestamps.extend(
            parsed
            for item in values
            if (parsed := parse_source_timestamp(item)) is not None
        )
    return timestamps


def snapshot_source_available_at(manifest_path: Path) -> str:
    """Conservatively date the latest source content, not our later capture."""
    manifest = read_object(manifest_path)
    timestamps: list[datetime] = []
    for artifact in manifest["artifacts"]:
        if not artifact["path"].endswith(".json"):
            continue
        value = json.loads(
            (manifest_path.parent / artifact["path"]).read_text(encoding="utf-8")
        )
        timestamps.extend(artifact_source_timestamps(artifact["kind"], value))
    if not timestamps:
        return manifest["captured_at"]
    return max(timestamps).astimezone(timezone.utc).isoformat()


def event_source_available_at(corpus: Path, event: dict) -> str:
    """Date only artifacts that substantiate one reviewed event."""
    manifest_path = event_manifest_path(corpus, event)
    manifest = read_object(manifest_path)
    artifacts = {item["kind"]: item for item in manifest["artifacts"]}
    kinds = {item["artifact_kind"] for item in evidence_references(event)}
    if kinds & {"DIFF", "FILES"}:
        kinds.add("COMMITS")
    timestamps: list[datetime] = []
    for kind in kinds:
        artifact = artifacts[kind]
        if not artifact["path"].endswith(".json"):
            continue
        value = json.loads(
            (manifest_path.parent / artifact["path"]).read_text(encoding="utf-8")
        )
        timestamps.extend(artifact_source_timestamps(kind, value))
    if not timestamps:
        return manifest["captured_at"]
    return max(timestamps).astimezone(timezone.utc).isoformat()


def validate_manifest(manifest_path: Path, root: Path | None = None) -> list[str]:
    root = root or repository_root()
    errors = validate_json_file(
        manifest_path, root / "schemas" / "community_pr_snapshot.schema.json"
    )
    if errors:
        return errors
    manifest = read_object(manifest_path)
    kinds = [item["kind"] for item in manifest["artifacts"]]
    expected = [item[0] for item in ARTIFACT_SPECS]
    if kinds != expected:
        errors.append(f"artifact kinds must appear exactly once in order: {expected}")
    for artifact in manifest["artifacts"]:
        path = manifest_path.parent / artifact["path"]
        if not path.is_file():
            errors.append(f"missing artifact: {artifact['path']}")
            continue
        if path.stat().st_size != artifact["byte_length"]:
            errors.append(f"artifact length changed: {artifact['path']}")
        if sha256_file(path) != artifact["sha256"]:
            errors.append(f"artifact hash changed: {artifact['path']}")
    if snapshot_identity(manifest) != manifest["snapshot_id"]:
        errors.append("snapshot identity does not match the bound evidence")
    return errors


def index_entry(manifest_path: Path, corpus: Path) -> dict:
    manifest = read_object(manifest_path)
    return {
        "provider": "github",
        "repository": manifest["source"]["repository"],
        "pr_number": manifest["source"]["number"],
        "snapshot_id": manifest["snapshot_id"],
        "path": manifest_path.parent.relative_to(corpus).as_posix(),
        "manifest_sha256": sha256_file(manifest_path),
        "source_updated_at": manifest["pull_request"]["updated_at"],
        "lifecycle": lifecycle(manifest),
    }


def update_index(corpus: Path, entry: dict, root: Path | None = None) -> dict:
    root = root or repository_root()
    path = corpus / "index.json"
    if path.is_file():
        index = read_object(path)
    else:
        index = {"schema_version": INDEX_SCHEMA, "generated_at": now(), "snapshots": []}
    by_identity = {
        (item["repository"], item["pr_number"], item["snapshot_id"]): item
        for item in index["snapshots"]
    }
    by_identity[(entry["repository"], entry["pr_number"], entry["snapshot_id"])] = entry
    index["snapshots"] = sorted(
        by_identity.values(),
        key=lambda item: (
            item["repository"].lower(),
            item["pr_number"],
            item["source_updated_at"],
            item["snapshot_id"],
        ),
    )
    index["generated_at"] = now()
    errors = validate_instance(
        index,
        read_object(root / "schemas" / "community_corpus_index.schema.json"),
    )
    if errors:
        raise ValueError("invalid corpus index: " + "; ".join(errors))
    atomic_json(path, index)
    return index


def capture_pr(
    repository: str,
    number: int,
    corpus: Path,
    client: GitHubClient,
    root: Path | None = None,
) -> dict:
    root = root or repository_root()
    if not REPOSITORY_PATTERN.fullmatch(repository):
        raise ValueError("repository must use the owner/name GitHub form")
    if number < 1:
        raise ValueError("pull-request number must be positive")
    corpus = corpus.resolve()
    corpus.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".capture-", dir=corpus))
    artifacts = []
    pull_value: dict | None = None
    try:
        for kind, filename, media_type in ARTIFACT_SPECS:
            endpoint = endpoint_for(repository, number, kind)
            if kind == "DIFF":
                payload, urls = client.bytes(endpoint, media_type)
            else:
                pages, urls = client.json_pages(endpoint, media_type)
                value: Any = pages[0] if kind == "PULL_REQUEST" else pages
                if kind == "PULL_REQUEST":
                    if len(pages) != 1 or not isinstance(value, dict):
                        raise ValueError("GitHub pull endpoint returned an unexpected shape")
                    pull_value = value
                payload = canonical_json(value)
            (staging / filename).write_bytes(payload)
            artifacts.append(
                {
                    "kind": kind,
                    "path": filename,
                    "sha256": sha256_bytes(payload),
                    "byte_length": len(payload),
                    "media_type": media_type,
                    "source_urls": urls,
                }
            )
        assert pull_value is not None
        manifest = {
            "schema_version": SNAPSHOT_SCHEMA,
            "snapshot_id": "0" * 20,
            "captured_at": now(),
            "source": {
                "provider": "github",
                "repository": repository,
                "number": number,
                "html_url": f"https://github.com/{repository}/pull/{number}",
                "api_version": API_VERSION,
                "authenticated": client.authenticated,
            },
            "pull_request": pull_summary(pull_value),
            "artifacts": artifacts,
        }
        manifest["snapshot_id"] = snapshot_identity(manifest)
        manifest_path = staging / "manifest.json"
        atomic_json(manifest_path, manifest)
        errors = validate_manifest(manifest_path, root)
        if errors:
            raise ValueError("captured snapshot failed validation: " + "; ".join(errors))

        owner, name = repository.split("/", 1)
        target = (
            corpus
            / "snapshots"
            / "github"
            / owner
            / name
            / str(number)
            / manifest["snapshot_id"]
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.rmtree(staging)
        else:
            os.replace(staging, target)
        final_manifest = target / "manifest.json"
        index = update_index(corpus, index_entry(final_manifest, corpus), root)
        return {
            "status": "PASS",
            "snapshot_id": manifest["snapshot_id"],
            "manifest": str(final_manifest),
            "corpus_snapshot_count": len(index["snapshots"]),
        }
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def validate_corpus(corpus: Path, root: Path | None = None) -> dict:
    root = root or repository_root()
    corpus = corpus.resolve()
    index_path = corpus / "index.json"
    if not index_path.is_file():
        raise FileNotFoundError(f"missing corpus index: {index_path}")
    schema_errors = validate_json_file(
        index_path, root / "schemas" / "community_corpus_index.schema.json"
    )
    if schema_errors:
        raise ValueError("invalid corpus index: " + "; ".join(schema_errors))
    index = read_object(index_path)
    expected_paths: set[str] = set()
    for entry in index["snapshots"]:
        manifest_path = corpus / entry["path"] / "manifest.json"
        expected_paths.add(manifest_path.parent.resolve().as_posix())
        errors = validate_manifest(manifest_path, root)
        if errors:
            raise ValueError(f"invalid snapshot {entry['snapshot_id']}: " + "; ".join(errors))
        if index_entry(manifest_path, corpus) != entry:
            raise ValueError(f"stale or edited index entry for snapshot {entry['snapshot_id']}")
    discovered_paths = {
        path.parent.resolve().as_posix()
        for path in (corpus / "snapshots").glob("github/*/*/*/*/manifest.json")
    }
    if discovered_paths != expected_paths:
        raise ValueError("corpus contains unindexed or missing snapshot directories")
    return {"status": "PASS", "snapshot_count": len(index["snapshots"])}


def evidence_references(event: dict) -> list[dict]:
    references = [
        measurement["evidence_ref"]
        for measurement in event["validation"]["measurements"]
    ]
    for claim in event["claims"]:
        references.extend(claim["evidence_refs"])
    return references


def event_manifest_path(corpus: Path, event: dict) -> Path:
    source = event["source_snapshot"]
    owner, name = source["repository"].split("/", 1)
    return (
        corpus.resolve()
        / "snapshots"
        / "github"
        / owner
        / name
        / str(source["pr_number"])
        / source["snapshot_id"]
        / "manifest.json"
    )


def validate_event(event_path: Path, corpus: Path, root: Path | None = None) -> dict:
    root = root or repository_root()
    errors = validate_json_file(
        event_path, root / "schemas" / "community_optimization_event.schema.json"
    )
    if errors:
        raise ValueError("invalid optimization event: " + "; ".join(errors))
    event = read_object(event_path)
    if event["schema_version"] != EVENT_SCHEMA:
        raise ValueError("unsupported optimization-event schema")
    source = event["source_snapshot"]
    manifest_path = event_manifest_path(corpus, event)
    manifest_errors = validate_manifest(manifest_path, root)
    if manifest_errors:
        raise ValueError("event source snapshot is invalid: " + "; ".join(manifest_errors))
    manifest = read_object(manifest_path)
    if sha256_file(manifest_path) != source["manifest_sha256"]:
        raise ValueError("event source manifest hash is stale")
    if (
        manifest["source"]["repository"] != source["repository"]
        or manifest["source"]["number"] != source["pr_number"]
    ):
        raise ValueError("event source identity does not match the manifest")
    artifact_by_kind = {item["kind"]: item for item in manifest["artifacts"]}
    for reference in evidence_references(event):
        artifact = artifact_by_kind.get(reference["artifact_kind"])
        if artifact is None or artifact["sha256"] != reference["sha256"]:
            raise ValueError(
                "event evidence reference is not bound to source snapshot: "
                f"{reference['artifact_kind']}"
            )
    return {
        "status": "PASS",
        "event_id": event["event_id"],
        "review_status": event["review_status"],
        "evidence_reference_count": len(evidence_references(event)),
    }


def event_paths(corpus: Path) -> list[Path]:
    return sorted((corpus / "events").glob("*.json"))


def graph_input_identity(
    corpus: Path, selected_event_ids: set[str] | None = None
) -> dict:
    paths = event_paths(corpus)
    if selected_event_ids is not None:
        paths = [
            path
            for path in paths
            if read_object(path)["event_id"] in selected_event_ids
        ]
    if not paths:
        raise ValueError("community corpus has no extracted optimization events")
    return {
        "corpus_index_sha256": sha256_file(corpus / "index.json"),
        "events": [
            {
                "path": path.relative_to(corpus).as_posix(),
                "sha256": sha256_file(path),
            }
            for path in paths
        ],
    }


def stable_identifier(value: object, length: int = 16) -> str:
    return sha256_bytes(canonical_json(value))[:length]


def graph_node(event: dict, source_available_at: str) -> dict:
    source = event["source_snapshot"]
    return {
        "event_id": event["event_id"],
        "repository": source["repository"],
        "pr_number": source["pr_number"],
        "source_url": (
            f"https://github.com/{source['repository']}/pull/{source['pr_number']}"
        ),
        "source_available_at": source_available_at,
        "outcome": event["lifecycle"]["outcome"],
        "review_status": event["review_status"],
        "summary": event["summary"],
        "rewrite_families": sorted(event["mechanism"]["rewrite_families"]),
        "operators": sorted(event["applicability"]["operators"]),
        "subsystems": sorted(event["applicability"]["subsystems"]),
        "dtypes": sorted(event["applicability"]["dtypes"]),
        "hardware": sorted(event["applicability"]["hardware"]),
        "required_capabilities": sorted(
            event["applicability"]["required_capabilities"]
        ),
        "hard_requirements": event["applicability"]["hard_requirements"],
        "implementation_recipe": event["implementation"]["recipe"],
        "correctness_recipe": event["validation"]["correctness"],
        "expected_bottleneck_shifts": event["mechanism"][
            "expected_bottleneck_shifts"
        ],
        "limitations": event["validation"]["limitations"],
    }


def build_graph(
    corpus: Path,
    repositories: list[str],
    root: Path | None = None,
    cutoff_at: str | None = None,
) -> dict:
    root = root or repository_root()
    corpus = corpus.resolve()
    validate_corpus(corpus, root)
    repository_universe = sorted(set(repositories), key=str.lower)
    if not repository_universe or any(
        not REPOSITORY_PATTERN.fullmatch(item) for item in repository_universe
    ):
        raise ValueError("repository universe must contain owner/name values")
    cutoff = (
        datetime.fromisoformat(cutoff_at.replace("Z", "+00:00"))
        if cutoff_at
        else None
    )
    if cutoff is not None and cutoff.tzinfo is None:
        raise ValueError("graph cutoff must include a timezone")
    all_event_ids = {
        read_object(path)["event_id"] for path in event_paths(corpus)
    }
    events: list[tuple[dict, str]] = []
    for path in event_paths(corpus):
        validate_event(path, corpus, root)
        event = read_object(path)
        available_at = event_source_available_at(corpus, event)
        if cutoff is not None:
            available = datetime.fromisoformat(available_at.replace("Z", "+00:00"))
            if available > cutoff:
                continue
        events.append((event, available_at))
    if not events:
        raise ValueError("community corpus has no events available by the cutoff")
    identifiers = [event["event_id"] for event, _ in events]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("community corpus contains duplicate event_id values")
    nodes = sorted(
        (graph_node(event, available_at) for event, available_at in events),
        key=lambda item: item["event_id"],
    )
    known_events = set(identifiers)
    method_ids = {
        path.stem for path in (root / "knowledge" / "methods").glob("*.json")
    }
    edges = []
    compositions: dict[str, dict] = {}
    for event, _ in events:
        for relation in event["relations"]:
            target = relation["target"]
            if cutoff is not None and target in all_event_ids and target not in known_events:
                continue
            target_kind = "METHOD" if target in method_ids else "EVENT"
            present = target in method_ids if target_kind == "METHOD" else target in known_events
            edge = {
                "source": event["event_id"],
                "type": relation["type"],
                "target": target,
                "target_kind": target_kind,
                "resolution": "PRESENT" if present else "MISSING",
                "rationale": relation["rationale"],
            }
            edges.append(edge)
            if relation["type"] == "COMPLEMENTS" and present and target_kind == "EVENT":
                pair = sorted((event["event_id"], target))
                hypothesis_id = stable_identifier({"relation": "COMPLEMENTS", "events": pair})
                compositions[hypothesis_id] = {
                    "hypothesis_id": hypothesis_id,
                    "events": pair,
                    "relation": "COMPLEMENTS",
                    "rationale": relation["rationale"],
                    "claim_boundary": "UNVALIDATED_COMPOSITION_HYPOTHESIS",
                }
    coverage: dict[tuple[str, str], dict[str, set[str]]] = {}
    for node in nodes:
        if node["review_status"] == "DRAFT":
            continue
        for family in node["rewrite_families"]:
            for subsystem in node["subsystems"]:
                bucket = coverage.setdefault(
                    (family, subsystem), {"repositories": set(), "events": set()}
                )
                bucket["repositories"].add(node["repository"])
                bucket["events"].add(node["event_id"])
    gaps = []
    for (family, subsystem), bucket in sorted(coverage.items()):
        observed = sorted(bucket["repositories"], key=str.lower)
        missing = sorted(set(repository_universe) - set(observed), key=str.lower)
        if not missing:
            continue
        identity = {
            "rewrite_family": family,
            "subsystem": subsystem,
            "observed": observed,
            "missing": missing,
        }
        gaps.append(
            {
                "gap_id": stable_identifier(identity),
                "rewrite_family": family,
                "subsystem": subsystem,
                "observed_repositories": observed,
                "missing_repositories": missing,
                "evidence_events": sorted(bucket["events"]),
                "claim_boundary": "CORPUS_COVERAGE_GAP_ONLY",
            }
        )
    graph = {
        "schema_version": GRAPH_SCHEMA,
        "generated_at": now(),
        "temporal_cutoff_at": cutoff_at,
        "claim_boundary": "DISCOVERY_PRIOR_ONLY",
        "input_identity": graph_input_identity(
            corpus,
            {event["event_id"] for event, _ in events},
        ),
        "repository_universe": repository_universe,
        "nodes": nodes,
        "edges": sorted(
            edges, key=lambda item: (item["source"], item["type"], item["target"])
        ),
        "coverage_gaps": gaps,
        "composition_hypotheses": sorted(
            compositions.values(), key=lambda item: item["hypothesis_id"]
        ),
    }
    errors = validate_instance(
        graph,
        read_object(root / "schemas" / "community_optimization_graph.schema.json"),
    )
    if errors:
        raise ValueError("invalid community graph: " + "; ".join(errors))
    return graph


def validate_graph(graph_path: Path, corpus: Path, root: Path | None = None) -> dict:
    root = root or repository_root()
    graph = read_object(graph_path)
    errors = validate_instance(
        graph,
        read_object(root / "schemas" / "community_optimization_graph.schema.json"),
    )
    if errors:
        raise ValueError("invalid community graph: " + "; ".join(errors))
    expected = build_graph(
        corpus,
        graph["repository_universe"],
        root,
        graph["temporal_cutoff_at"],
    )
    observed_stable = {key: value for key, value in graph.items() if key != "generated_at"}
    expected_stable = {key: value for key, value in expected.items() if key != "generated_at"}
    if observed_stable != expected_stable:
        raise ValueError("community graph is stale or was edited without recomputation")
    return {
        "status": "PASS",
        "node_count": len(graph["nodes"]),
        "edge_count": len(graph["edges"]),
        "coverage_gap_count": len(graph["coverage_gaps"]),
        "composition_count": len(graph["composition_hypotheses"]),
    }


def run_input_identities(run: Path) -> list[dict]:
    identities = []
    for relative in RUN_INPUT_PATHS:
        path = run / relative
        if not path.is_file():
            raise FileNotFoundError(f"community routing requires {relative}")
        identities.append({"path": relative, "sha256": sha256_file(path)})
    return identities


def attach_graph(run: Path, graph_path: Path, corpus: Path, root: Path | None = None) -> dict:
    validation = validate_graph(graph_path, corpus, root)
    target = run.resolve() / "knowledge" / "community_graph.json"
    atomic_json(target, read_object(graph_path))
    return {**validation, "status": "PASS", "attached_graph": str(target)}


def scalar_text(value: object) -> str:
    if isinstance(value, dict):
        return " ".join(scalar_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(scalar_text(item) for item in value)
    return str(value).lower()


def semantic_tokens(value: str) -> set[str]:
    """Normalize common spelling variants without pretending to be an embedding."""
    tokens = {
        TOKEN_ALIASES.get(token, token)
        for token in re.findall(r"[a-z0-9]+", value.lower())
    }
    return tokens - TOKEN_STOPWORDS


def term_matches_text(term: str, text: str) -> bool:
    """Require a salient token-level match when exact phrasing differs."""
    term_tokens = semantic_tokens(term)
    if not term_tokens:
        return False
    text_tokens = semantic_tokens(text)
    required = 1 if len(term_tokens) == 1 else 2
    return len(term_tokens & text_tokens) >= required


def opportunity_routing_text(opportunity: dict) -> str:
    """Exclude historical observations that can mention unrelated bottlenecks."""
    return scalar_text(
        {
            key: opportunity.get(key)
            for key in (
                "opportunity_id",
                "name",
                "hypothesis",
                "rewrite_families",
                "affected_stages",
                "source_model_term",
            )
        }
    )


def explicit_parallel_width(value: object) -> int | None:
    """Return only a parallel width explicitly frozen in operator/workload input."""
    widths: list[int] = []
    keys = {
        "data_parallel_size",
        "dp_size",
        "gpu_count",
        "parallel_width",
        "tensor_parallel_size",
        "tp_size",
        "world_size",
    }

    def visit(item: object) -> None:
        if isinstance(item, dict):
            for raw_key, child in item.items():
                key = str(raw_key).lower().replace("-", "_").replace(" ", "_")
                if key in keys and not isinstance(child, bool):
                    try:
                        width = int(child)
                    except (TypeError, ValueError):
                        pass
                    else:
                        if width >= 1:
                            widths.append(width)
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return max(widths) if widths else None


def applicability_blockers(
    node: dict,
    operator: dict,
    workload: dict,
    hardware: dict,
) -> list[str]:
    """Fail closed only for event-card requirements declared as hard gates."""
    requirements = node["hard_requirements"]
    blockers = []
    capabilities = requirements["compute_capabilities"]
    target = hardware.get("target", {})
    observed_capability = (
        str(target.get("compute_capability"))
        if isinstance(target, dict) and target.get("compute_capability") is not None
        else None
    )
    if capabilities:
        if observed_capability is None:
            blockers.append("target compute capability is not explicit")
        elif observed_capability not in capabilities:
            blockers.append(
                "target compute capability "
                f"{observed_capability} is outside {','.join(capabilities)}"
            )

    minimum_width = int(requirements["minimum_parallel_width"])
    if minimum_width > 1:
        observed_width = explicit_parallel_width(
            {"operator": operator, "workload": workload}
        )
        if observed_width is None:
            blockers.append(
                f"parallel width >= {minimum_width} is required but not explicit"
            )
        elif observed_width < minimum_width:
            blockers.append(
                f"parallel width {observed_width} is below required {minimum_width}"
            )

    target_context = scalar_text({"operator": operator, "workload": workload})
    for term in requirements["required_context_terms"]:
        if not term_matches_text(term, target_context):
            blockers.append(f"required target context is absent: {term}")
    return blockers


def unique_strings(values: list[str]) -> list[str]:
    """Keep deterministic first-seen order while removing duplicates."""
    return list(dict.fromkeys(values))


def build_composition_matches(graph: dict, matches: list[dict], limit: int) -> list[dict]:
    """Materialize only explicit, jointly applicable complement hypotheses."""
    matches_by_event = {item["event_id"]: item for item in matches}
    nodes_by_event = {item["event_id"]: item for item in graph["nodes"]}
    rows = []
    for hypothesis in graph["composition_hypotheses"]:
        event_ids = hypothesis["events"]
        if any(event_id not in matches_by_event for event_id in event_ids):
            continue
        event_matches = [matches_by_event[event_id] for event_id in event_ids]
        nodes = [nodes_by_event[event_id] for event_id in event_ids]
        shifts = unique_strings(
            [shift for node in nodes for shift in node["expected_bottleneck_shifts"]]
        )
        recipes = unique_strings(
            [step for node in nodes for step in node["implementation_recipe"]]
        )
        correctness = unique_strings(
            [step for node in nodes for step in node["correctness_recipe"]]
        )
        limitations = unique_strings(
            [item for node in nodes for item in node["limitations"]]
        )
        families = unique_strings(
            [family for match in event_matches for family in match["family_hits"]]
        )
        family = families[0] if families else event_matches[0]["candidate_archetype"]["family"]
        diversity_bonus = 2.0 if len(shifts) > 1 else 0.0
        rows.append(
            {
                "hypothesis_id": hypothesis["hypothesis_id"],
                "events": event_ids,
                "score": min(float(item["score"]) for item in event_matches)
                + diversity_bonus
                - 3.0,
                "rationale": hypothesis["rationale"],
                "candidate_archetype": {
                    "family": family,
                    "name": "compose " + " + ".join(event_ids),
                    "change_axes": [
                        "compose explicit complementary transformations",
                        "measure the combined bottleneck shift",
                        "retain each component as an ablation control",
                    ],
                    "template": " Then ".join(recipes),
                },
                "correctness_recipe": correctness,
                "expected_bottleneck_shifts": shifts,
                "interaction_risks": unique_strings(
                    [
                        *limitations,
                        "The combination may move or amplify a bottleneck; compare "
                        "both single-component ablations with the composed candidate.",
                    ]
                ),
                "claim_boundary": "UNVALIDATED_COMPOSITION_HYPOTHESIS",
            }
        )
    rows.sort(key=lambda item: (-float(item["score"]), item["hypothesis_id"]))
    return rows[:limit]


def build_match_receipt(run: Path, limit: int = 3, root: Path | None = None) -> dict:
    root = root or repository_root()
    graph_path = run / "knowledge" / "community_graph.json"
    graph = read_object(graph_path)
    graph_errors = validate_instance(
        graph,
        read_object(root / "schemas" / "community_optimization_graph.schema.json"),
    )
    if graph_errors:
        raise ValueError("attached community graph is invalid: " + "; ".join(graph_errors))
    opportunity_map = read_object(run / "models" / "opportunity_map.json")
    if (
        opportunity_map.get("schema_version") != "opportunity-map-v1"
        or opportunity_map.get("status") != "READY"
    ):
        raise ValueError("community routing requires a READY opportunity-map-v1")
    operator = read_object(run / "operator.json")
    workload = read_object(run / "workload.json")
    hardware = read_object(run / "hardware.json")
    context = scalar_text(
        {"operator": operator, "workload": workload, "hardware": hardware}
    )
    recommendations = []
    for opportunity in opportunity_map["opportunities"]:
        if opportunity.get("status") == "CLOSED":
            continue
        rows = []
        screened_out = []
        opportunity_families = set(opportunity["rewrite_families"])
        opportunity_text = opportunity_routing_text(opportunity)
        for node in graph["nodes"]:
            family_hits = sorted(opportunity_families & set(node["rewrite_families"]))
            routing_terms = sorted(set(node["operators"] + node["subsystems"]))
            context_terms = sorted(set(routing_terms + node["dtypes"]))
            opportunity_hits = [
                term
                for term in routing_terms
                if term_matches_text(term, opportunity_text)
            ]
            context_hits = [
                term for term in context_terms if term_matches_text(term, context)
            ]
            if not family_hits and not opportunity_hits:
                continue
            blockers = applicability_blockers(node, operator, workload, hardware)
            if blockers:
                screened_out.append(
                    {
                        "event_id": node["event_id"],
                        "blockers": blockers,
                        "claim_boundary": "APPLICABILITY_GATE",
                    }
                )
                continue
            lifecycle_bonus = 2.0 if node["outcome"] == "MERGED" else 0.0
            review_bonus = 1.0 if node["review_status"] in {"REVIEWED", "PROMOTED"} else 0.0
            draft_penalty = 2.0 if node["outcome"] == "OPEN" else 0.0
            score = (
                12.0 * len(family_hits)
                + min(8.0, 4.0 * len(opportunity_hits))
                + min(2.0, float(len(context_hits)))
                + lifecycle_bonus
                + review_bonus
                - draft_penalty
            )
            family = family_hits[0] if family_hits else node["rewrite_families"][0]
            rows.append(
                {
                    "event_id": node["event_id"],
                    "summary": node["summary"],
                    "source_url": node["source_url"],
                    "outcome": node["outcome"],
                    "review_status": node["review_status"],
                    "transfer_status": "ADAPTATION_REQUIRED",
                    "score": score,
                    "family_hits": family_hits,
                    "opportunity_hits": opportunity_hits,
                    "context_hits": context_hits,
                    "applicability_requirements": node["hard_requirements"],
                    "candidate_archetype": {
                        "family": family,
                        "name": f"adapt {node['event_id']}",
                        "change_axes": [
                            "baseline work",
                            "data layout",
                            "bottleneck shift",
                        ],
                        "template": " ".join(node["implementation_recipe"]),
                    },
                    "correctness_recipe": node["correctness_recipe"],
                    "expected_bottleneck_shifts": node["expected_bottleneck_shifts"],
                    "limitations": node["limitations"],
                    "claim_boundary": "DISCOVERY_PRIOR_ONLY",
                }
            )
        rows.sort(key=lambda item: (-float(item["score"]), item["event_id"]))
        selected = rows[:limit]
        recommendations.append(
            {
                "opportunity_id": opportunity["opportunity_id"],
                "opportunity_priority_rank": opportunity["priority_rank"],
                "matches": selected,
                "composition_matches": build_composition_matches(
                    graph, selected, limit
                ),
                "screened_out": sorted(
                    screened_out, key=lambda item: item["event_id"]
                ),
            }
        )
    recommendations.sort(
        key=lambda item: (item["opportunity_priority_rank"], item["opportunity_id"])
    )
    receipt = {
        "schema_version": MATCH_SCHEMA,
        "generated_at": now(),
        "claim_boundary": "DISCOVERY_PRIOR_ONLY",
        "input_identities": run_input_identities(run),
        "graph_identity": {
            "path": "knowledge/community_graph.json",
            "sha256": sha256_file(graph_path),
        },
        "policy": {
            "max_matches_per_opportunity": limit,
            "community_claim_policy": "SOURCE_PRIOR_NOT_TARGET_PROOF",
            "score_formula": (
                "12*family_hits + min(8,4*opportunity_hits) + "
                "min(2,context_hits) + 2*merged + 1*reviewed - 2*open"
            ),
        },
        "recommendations": recommendations,
    }
    errors = validate_instance(
        receipt,
        read_object(root / "schemas" / "community_match_receipt.schema.json"),
    )
    if errors:
        raise ValueError("invalid community-match receipt: " + "; ".join(errors))
    return receipt


def validate_match_receipt(
    receipt: dict, run: Path, root: Path | None = None
) -> None:
    root = root or repository_root()
    errors = validate_instance(
        receipt,
        read_object(root / "schemas" / "community_match_receipt.schema.json"),
    )
    if errors:
        raise ValueError("invalid community-match receipt: " + "; ".join(errors))
    limit = int(receipt["policy"]["max_matches_per_opportunity"])
    expected = build_match_receipt(run, limit, root)
    observed_stable = {key: value for key, value in receipt.items() if key != "generated_at"}
    expected_stable = {key: value for key, value in expected.items() if key != "generated_at"}
    if observed_stable != expected_stable:
        raise ValueError("community-match receipt is stale or was edited without recomputation")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    capture = subparsers.add_parser("capture-pr", help="capture one immutable GitHub PR snapshot")
    capture.add_argument("--repository", required=True)
    capture.add_argument("--number", type=int, required=True)
    capture.add_argument("--corpus", type=Path, required=True)
    capture.add_argument("--timeout", type=float, default=30.0)
    validate = subparsers.add_parser(
        "validate-corpus", help="validate every indexed snapshot and hash"
    )
    validate.add_argument("--corpus", type=Path, required=True)
    event = subparsers.add_parser(
        "validate-event", help="validate one extracted optimization event"
    )
    event.add_argument("--event", type=Path, required=True)
    event.add_argument("--corpus", type=Path, required=True)
    graph = subparsers.add_parser(
        "build-graph", help="build method relations and corpus coverage gaps"
    )
    graph.add_argument("--corpus", type=Path, required=True)
    graph.add_argument("--output", type=Path, required=True)
    graph.add_argument("--repository", action="append", required=True)
    graph.add_argument(
        "--cutoff",
        help="include only events whose captured source content existed by this timestamp",
    )
    graph_validate = subparsers.add_parser(
        "validate-graph", help="recompute and validate a community graph"
    )
    graph_validate.add_argument("--graph", type=Path, required=True)
    graph_validate.add_argument("--corpus", type=Path, required=True)
    attach = subparsers.add_parser(
        "attach-graph", help="freeze a validated graph into one optimization run"
    )
    attach.add_argument("--run", type=Path, required=True)
    attach.add_argument("--graph", type=Path, required=True)
    attach.add_argument("--corpus", type=Path, required=True)
    recommend = subparsers.add_parser(
        "recommend", help="route community events to run opportunities"
    )
    recommend.add_argument("--run", type=Path, required=True)
    recommend.add_argument("--limit", type=int, default=3, choices=range(1, 9))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.operation == "capture-pr":
            client = GitHubClient(os.environ.get("GITHUB_TOKEN"), timeout=args.timeout)
            result = capture_pr(args.repository, args.number, args.corpus, client)
        elif args.operation == "validate-corpus":
            result = validate_corpus(args.corpus)
        elif args.operation == "validate-event":
            result = validate_event(args.event, args.corpus)
        elif args.operation == "build-graph":
            graph = build_graph(args.corpus, args.repository, cutoff_at=args.cutoff)
            atomic_json(args.output.resolve(), graph)
            result = validate_graph(args.output.resolve(), args.corpus)
            result["graph"] = str(args.output.resolve())
        elif args.operation == "validate-graph":
            result = validate_graph(args.graph, args.corpus)
        elif args.operation == "attach-graph":
            result = attach_graph(args.run, args.graph, args.corpus)
        else:
            run = args.run.resolve()
            receipt = build_match_receipt(run, args.limit)
            validate_match_receipt(receipt, run)
            atomic_json(run / "models" / "community_matches.json", receipt)
            result = receipt
    except Exception as error:
        print(f"ERROR: {error}", file=__import__("sys").stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
