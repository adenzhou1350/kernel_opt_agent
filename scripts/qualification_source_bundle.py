#!/usr/bin/env python3
"""Build, verify, and safely extract deterministic source bundles from Git objects."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import posixpath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO


SCHEMA_VERSION = "qualification-source-bundle-v1"
GIT_SHA1_PATTERN = "0123456789abcdef"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: dict) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def git(repo: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"git {' '.join(args)} failed: {detail}")
    return completed.stdout


def full_sha1(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(character in GIT_SHA1_PATTERN for character in value)
    )


def read_exact(handle: BinaryIO, size: int) -> bytes:
    data = handle.read(size)
    if len(data) != size:
        raise ValueError("git cat-file returned a truncated blob")
    return data


def git_tree_blobs(repo: Path, commit: str) -> list[tuple[str, int, bytes]]:
    """Return tracked paths, modes, and exact blob bytes without a checkout."""

    records = git(repo, "ls-tree", "-rz", "--full-tree", "-r", commit).split(b"\0")
    identities: list[tuple[str, str, str]] = []
    for record in records:
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, object_type, object_id = metadata.decode("ascii").split(" ")
            path = raw_path.decode("utf-8")
        except (UnicodeDecodeError, ValueError) as error:
            raise ValueError(
                "Git tree contains an unsupported path or record"
            ) from error
        if object_type != "blob" or mode not in {"100644", "100755", "120000"}:
            raise ValueError(
                f"unsupported Git tree entry {mode} {object_type} at {path!r}"
            )
        candidate = PurePosixPath(path)
        if candidate.is_absolute() or ".." in candidate.parts or not candidate.parts:
            raise ValueError(f"unsafe Git tree path: {path!r}")
        identities.append((path, mode, object_id))
    if not identities:
        raise ValueError("source bundle must contain at least one Git blob")

    process = subprocess.Popen(
        ["git", "-C", str(repo), "cat-file", "--batch"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    request = b"".join(
        object_id.encode("ascii") + b"\n" for _, _, object_id in identities
    )
    stdout, stderr = process.communicate(request)
    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"git cat-file --batch failed: {detail}")

    stream = io.BytesIO(stdout)
    result: list[tuple[str, int, bytes]] = []
    for path, mode_text, object_id in identities:
        header = stream.readline().rstrip(b"\n").decode("ascii", errors="replace")
        parts = header.split(" ")
        if len(parts) != 3 or parts[0] != object_id or parts[1] != "blob":
            raise ValueError(f"unexpected git cat-file header for {path!r}: {header!r}")
        try:
            size = int(parts[2])
        except ValueError as error:
            raise ValueError(f"invalid Git blob size for {path!r}") from error
        data = read_exact(stream, size)
        if stream.read(1) != b"\n":
            raise ValueError(f"invalid Git blob delimiter for {path!r}")
        result.append((path, int(mode_text, 8), data))
    if stream.read(1):
        raise ValueError("git cat-file returned trailing data")
    return result


def deterministic_tar(
    blobs: list[tuple[str, int, bytes]], prefix: str
) -> tuple[bytes, list[dict]]:
    directories = {prefix}
    for path, _, _ in blobs:
        parts = PurePosixPath(path).parts
        for index in range(1, len(parts)):
            directories.add(PurePosixPath(prefix, *parts[:index]).as_posix())

    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:", format=tarfile.PAX_FORMAT) as archive:
        for path in sorted(directories):
            info = tarfile.TarInfo(path + "/")
            info.type = tarfile.DIRTYPE
            info.mode = 0o755
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            archive.addfile(info)
        for path, git_mode, data in sorted(blobs):
            archive_path = PurePosixPath(prefix, path).as_posix()
            info = tarfile.TarInfo(archive_path)
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            if git_mode == 0o120000:
                try:
                    target = data.decode("utf-8")
                except UnicodeDecodeError as error:
                    raise ValueError(
                        f"symlink target at {path!r} is not UTF-8"
                    ) from error
                safe_symlink_target(PurePosixPath(archive_path), target, prefix)
                info.type = tarfile.SYMTYPE
                info.mode = 0o777
                info.linkname = target
                archive.addfile(info)
            else:
                info.type = tarfile.REGTYPE
                info.mode = 0o755 if git_mode == 0o100755 else 0o644
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
    tar_bytes = output.getvalue()
    return tar_bytes, entries_from_tar(tar_bytes, prefix)


def validate_prefix(prefix: str) -> str:
    value = prefix.strip().rstrip("/")
    path = PurePosixPath(value)
    if (
        not re.fullmatch(r"[A-Za-z0-9_-]+", value)
        or path.is_absolute()
        or len(path.parts) != 1
    ):
        raise ValueError(
            "prefix must be one ASCII alphanumeric, underscore, or hyphen segment"
        )
    return value


def safe_member_path(value: str, prefix: str) -> PurePosixPath:
    path = PurePosixPath(value.rstrip("/"))
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"unsafe archive member path: {value!r}")
    if path.parts[0] != prefix:
        raise ValueError(f"archive member is outside prefix {prefix!r}: {value!r}")
    return path


def safe_symlink_target(member_path: PurePosixPath, target: str, prefix: str) -> None:
    target_path = PurePosixPath(target)
    if target_path.is_absolute():
        raise ValueError(f"absolute symlink target is forbidden: {target!r}")
    resolved = posixpath.normpath(posixpath.join(member_path.parent.as_posix(), target))
    if resolved != prefix and not resolved.startswith(prefix + "/"):
        raise ValueError(
            f"symlink target escapes bundle prefix: {member_path} -> {target}"
        )


def entries_from_tar(tar_bytes: bytes, prefix: str) -> list[dict]:
    entries: list[dict] = []
    seen: set[str] = set()
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as archive:
        for member in archive.getmembers():
            path = safe_member_path(member.name, prefix)
            normalized = path.as_posix()
            if normalized in seen:
                raise ValueError(f"duplicate archive member: {normalized}")
            seen.add(normalized)
            base = {"mode": stat.S_IMODE(member.mode), "path": normalized}
            if member.isdir():
                entries.append({**base, "type": "directory"})
            elif member.isfile():
                handle = archive.extractfile(member)
                if handle is None:
                    raise ValueError(f"cannot read archive member: {normalized}")
                data = handle.read()
                entries.append(
                    {
                        **base,
                        "type": "file",
                        "size": len(data),
                        "sha256": sha256_bytes(data),
                    }
                )
            elif member.issym():
                safe_symlink_target(path, member.linkname, prefix)
                entries.append({**base, "type": "symlink", "target": member.linkname})
            else:
                raise ValueError(
                    f"unsupported archive member type for {normalized}: {member.type!r}"
                )
    return entries


def build_bundle(
    repo: Path,
    commit: str,
    repository_url: str,
    prefix: str,
    archive_path: Path,
    manifest_path: Path,
) -> dict:
    repo = repo.resolve()
    if not (repo / ".git").exists() and not (repo / "HEAD").is_file():
        # Worktrees use a .git file; bare repositories use HEAD directly.
        if not (repo / ".git").is_file():
            raise ValueError(f"not a Git repository or worktree: {repo}")
    if archive_path.exists() or manifest_path.exists():
        raise ValueError("archive and manifest outputs must not already exist")
    if not repository_url.strip():
        raise ValueError("repository URL or logical identity must not be empty")
    prefix = validate_prefix(prefix)
    resolved_commit = (
        git(repo, "rev-parse", "--verify", f"{commit}^{{commit}}").decode().strip()
    )
    tree = (
        git(repo, "rev-parse", "--verify", f"{resolved_commit}^{{tree}}")
        .decode()
        .strip()
    )
    if not full_sha1(resolved_commit) or not full_sha1(tree):
        raise ValueError("Git commit and tree must use full SHA-1 identities")
    tar_bytes, entries = deterministic_tar(
        git_tree_blobs(repo, resolved_commit), prefix
    )

    compressed = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=compressed, mtime=0) as handle:
        handle.write(tar_bytes)
    archive_bytes = compressed.getvalue()
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "commit": resolved_commit,
            "git_tree": tree,
            "repository": repository_url.strip(),
        },
        "archive": {
            "bytes": len(archive_bytes),
            "construction": "raw Git blobs -> deterministic POSIX tar -> gzip(mtime=0)",
            "prefix": prefix,
            "sha256": sha256_bytes(archive_bytes),
        },
        "entries": entries,
    }
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_bytes(archive_bytes)
    manifest_path.write_bytes(canonical_json(manifest))
    return manifest


def read_manifest(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"manifest must use schema_version={SCHEMA_VERSION}")
    if set(value) != {"schema_version", "source", "archive", "entries"}:
        raise ValueError("manifest contains missing or unrecognized top-level fields")
    return value


def verify_bundle(archive_path: Path, manifest_path: Path) -> tuple[dict, bytes]:
    manifest = read_manifest(manifest_path)
    archive_record = manifest.get("archive")
    source = manifest.get("source")
    entries = manifest.get("entries")
    if not isinstance(archive_record, dict) or not isinstance(source, dict):
        raise ValueError("manifest archive and source records are required")
    if set(source) != {"commit", "git_tree", "repository"}:
        raise ValueError(
            "manifest source record contains missing or unrecognized fields"
        )
    if set(archive_record) != {
        "bytes",
        "construction",
        "prefix",
        "sha256",
    }:
        raise ValueError(
            "manifest archive record contains missing or unrecognized fields"
        )
    if not isinstance(entries, list) or not entries:
        raise ValueError("manifest entries must be a non-empty array")
    for field in ("commit", "git_tree"):
        value = source.get(field)
        if not full_sha1(value):
            raise ValueError(f"source.{field} must be a full SHA-1 identity")
    if (
        not isinstance(source.get("repository"), str)
        or not source["repository"].strip()
    ):
        raise ValueError("source.repository must be a non-empty logical identity")
    archive_bytes = archive_path.read_bytes()
    if archive_record.get("bytes") != len(archive_bytes):
        raise ValueError("archive byte count does not match manifest")
    if archive_record.get("sha256") != sha256_bytes(archive_bytes):
        raise ValueError("archive SHA-256 does not match manifest")
    if len(archive_bytes) < 10 or archive_bytes[:3] != b"\x1f\x8b\x08":
        raise ValueError("archive is not a gzip stream")
    if archive_bytes[4:8] != b"\x00\x00\x00\x00":
        raise ValueError("gzip header mtime must be zero")
    prefix = validate_prefix(str(archive_record.get("prefix", "")))
    try:
        tar_bytes = gzip.decompress(archive_bytes)
    except (EOFError, OSError) as error:
        raise ValueError(f"invalid gzip archive: {error}") from error
    observed = entries_from_tar(tar_bytes, prefix)
    if observed != entries:
        raise ValueError("archive entries do not exactly match the manifest")
    return manifest, tar_bytes


def extract_bundle(tar_bytes: bytes, manifest: dict, target: Path) -> None:
    target = target.resolve()
    if target.exists():
        raise ValueError(f"extract target must not already exist: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as archive:
            members = {
                member.name.rstrip("/"): member for member in archive.getmembers()
            }
            for entry in manifest["entries"]:
                relative = PurePosixPath(entry["path"])
                destination = temporary.joinpath(*relative.parts)
                if entry["type"] == "directory":
                    destination.mkdir(parents=True, exist_ok=True)
                    os.chmod(destination, entry["mode"])
                elif entry["type"] == "file":
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    handle = archive.extractfile(members[entry["path"]])
                    if handle is None:
                        raise ValueError(f"cannot extract {entry['path']}")
                    with destination.open("xb") as output:
                        shutil.copyfileobj(handle, output)
                    os.chmod(destination, entry["mode"])
                elif entry["type"] == "symlink":
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    os.symlink(entry["target"], destination)
                else:
                    raise ValueError(
                        f"unsupported manifest entry type: {entry['type']}"
                    )
        os.replace(temporary, target)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def write_receipt(path: Path | None, value: dict) -> None:
    if path is None:
        print(json.dumps(value, indent=2, sort_keys=True))
        return
    if path.exists():
        raise ValueError(f"receipt output must not already exist: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json(value))
    print(json.dumps(value, indent=2, sort_keys=True))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--build", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--commit")
    parser.add_argument("--repository-url")
    parser.add_argument("--prefix", default="source")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--extract-root", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.build:
            if args.repo is None or not args.commit or not args.repository_url:
                raise ValueError(
                    "--build requires --repo, --commit, and --repository-url"
                )
            if args.extract_root is not None:
                raise ValueError("--extract-root is valid only with --verify")
            manifest = build_bundle(
                args.repo,
                args.commit,
                args.repository_url,
                args.prefix,
                args.archive,
                args.manifest,
            )
            receipt = {
                "schema_version": "qualification-source-bundle-build-result-v1",
                "status": "PASS",
                "archive": {
                    "path": str(args.archive.resolve()),
                    "sha256": manifest["archive"]["sha256"],
                    "bytes": manifest["archive"]["bytes"],
                },
                "manifest": {
                    "path": str(args.manifest.resolve()),
                    "sha256": sha256_file(args.manifest),
                    "entries": len(manifest["entries"]),
                },
                "source": manifest["source"],
                "claim_boundary": "DETERMINISTIC SOURCE TRANSPORT ONLY; NO BUILD, IMPORT, CORRECTNESS, PERFORMANCE, GPU OR EXECUTION AUTHORIZATION",
            }
        else:
            if args.repo is not None or args.commit or args.repository_url:
                raise ValueError(
                    "--repo, --commit, and --repository-url are valid only with --build"
                )
            manifest, tar_bytes = verify_bundle(args.archive, args.manifest)
            if args.extract_root is not None:
                extract_bundle(tar_bytes, manifest, args.extract_root)
            receipt = {
                "schema_version": "qualification-source-bundle-verification-result-v1",
                "status": "PASS",
                "archive": {
                    "path": str(args.archive.resolve()),
                    "sha256": sha256_file(args.archive),
                    "bytes": args.archive.stat().st_size,
                },
                "manifest": {
                    "path": str(args.manifest.resolve()),
                    "sha256": sha256_file(args.manifest),
                    "entries": len(manifest["entries"]),
                },
                "source": manifest["source"],
                "extracted": args.extract_root is not None,
                "extract_root": (
                    str(args.extract_root.resolve()) if args.extract_root else None
                ),
                "claim_boundary": "SOURCE BUNDLE IDENTITY AND OPTIONAL SAFE EXTRACTION ONLY; NO BUILD, IMPORT, CORRECTNESS, PERFORMANCE, GPU OR EXECUTION AUTHORIZATION",
            }
        write_receipt(args.output, receipt)
    except (OSError, ValueError, json.JSONDecodeError, tarfile.TarError) as error:
        print(f"qualification source bundle failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
