#!/usr/bin/env python3
"""Tests for deterministic, checkout-independent Git source bundles."""

from __future__ import annotations

import io
import gzip
import hashlib
import json
import os
import stat
import subprocess
import sys
import tarfile
import tracemalloc
from pathlib import Path, PurePosixPath

import jsonschema
import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from qualification_source_bundle import (  # noqa: E402
    build_bundle,
    canonical_json,
    extract_bundle,
    main,
    safe_symlink_target,
    verify_bundle,
    verify_bundle_into,
)


REPOSITORY = "https://example.invalid/framework.git"


def run(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    return completed.stdout.strip()


def source_repo(tmp_path: Path) -> tuple[Path, str, bytes]:
    repo = tmp_path / "repository"
    repo.mkdir()
    run(repo, "init")
    run(repo, "config", "user.name", "Source Bundle Test")
    run(repo, "config", "user.email", "source-bundle@example.invalid")
    payload = b"committed\r\nraw\x00bytes\xff\n"
    (repo / "nested").mkdir()
    (repo / "nested" / "payload.bin").write_bytes(payload)
    (repo / "run.sh").write_bytes(b"#!/bin/sh\nexit 0\n")
    (repo / ".gitattributes").write_text(
        "ignored.txt export-ignore\nsubstitution.txt export-subst\n", encoding="utf-8"
    )
    (repo / "ignored.txt").write_text("must remain\n", encoding="utf-8")
    (repo / "substitution.txt").write_text("$Format:%H$\n", encoding="utf-8")
    run(repo, "add", ".")
    run(repo, "update-index", "--chmod=+x", "run.sh")
    run(repo, "commit", "-m", "fixture")
    return repo, run(repo, "rev-parse", "HEAD"), payload


def bundle_paths(root: Path, stem: str = "source") -> tuple[Path, Path]:
    return root / f"{stem}.tar.gz", root / f"{stem}.manifest.json"


def test_build_is_git_object_exact_and_checkout_independent(tmp_path: Path) -> None:
    repo, commit, payload = source_repo(tmp_path)
    archive_a, manifest_a = bundle_paths(tmp_path, "first")
    value_a = build_bundle(repo, commit, REPOSITORY, "source", archive_a, manifest_a)

    # Dirty working-tree bytes must never enter the source transport.
    (repo / "nested" / "payload.bin").write_bytes(b"dirty working tree\n")
    second_root = tmp_path / "different-output-directory"
    archive_b, manifest_b = bundle_paths(second_root, "renamed")
    value_b = build_bundle(repo, commit, REPOSITORY, "source", archive_b, manifest_b)

    assert archive_a.read_bytes() == archive_b.read_bytes()
    assert manifest_a.read_bytes() == manifest_b.read_bytes()
    assert value_a == value_b
    assert value_a["source"] == {
        "commit": commit,
        "git_tree": run(repo, "rev-parse", "HEAD^{tree}"),
        "repository": REPOSITORY,
    }
    entries = {entry["path"]: entry for entry in value_a["entries"]}
    assert entries["source/run.sh"]["mode"] == 0o755
    assert entries["source/ignored.txt"]["size"] == len(b"must remain\n")

    verified, tar_bytes = verify_bundle(archive_a, manifest_a)
    target = tmp_path / "extracted"
    extract_bundle(tar_bytes, verified, target)
    assert (target / "source" / "nested" / "payload.bin").read_bytes() == payload
    assert (target / "source" / "ignored.txt").read_bytes() == b"must remain\n"
    assert (target / "source" / "substitution.txt").read_bytes() == b"$Format:%H$\n"


def test_streamed_archive_keeps_previous_tar_and_gzip_bytes(tmp_path: Path) -> None:
    repo, commit, _ = source_repo(tmp_path)
    # Exercise PAX path records, executability, empty blobs and non-ASCII names.
    (repo / "nested" / ("long-" + "x" * 110)).write_bytes(b"long\n")
    (repo / "nested" / "caf\u00e9.txt").write_bytes(b"unicode\n")
    (repo / "empty").touch()
    run(repo, "add", ".")
    run(repo, "commit", "-m", "archive layouts")
    commit = run(repo, "rev-parse", "HEAD")
    records = subprocess.check_output(
        ["git", "-C", str(repo), "ls-tree", "-rz", "--full-tree", "-r", commit]
    ).split(b"\0")
    files = []
    directories = {"source"}
    for record in filter(None, records):
        metadata, path = record.split(b"\t", 1)
        mode, _, oid = metadata.decode().split()
        path = path.decode()
        files.append(
            (
                path,
                mode,
                subprocess.check_output(
                    ["git", "-C", str(repo), "cat-file", "blob", oid]
                ),
            )
        )
        parts = PurePosixPath(path).parts
        for index in range(1, len(parts)):
            directories.add(PurePosixPath("source", *parts[:index]).as_posix())
    reference = io.BytesIO()
    with tarfile.open(fileobj=reference, mode="w:", format=tarfile.PAX_FORMAT) as tar:
        for path in sorted(directories):
            member = tarfile.TarInfo(path + "/")
            member.type = tarfile.DIRTYPE
            member.mode = 0o755
            tar.addfile(member)
        for path, mode, data in sorted(files):
            member = tarfile.TarInfo("source/" + path)
            member.mode = 0o755 if mode == "100755" else 0o644
            member.size = len(data)
            tar.addfile(member, io.BytesIO(data))
    compressed = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=compressed, mtime=0) as output:
        output.write(reference.getvalue())
    archive, manifest = bundle_paths(tmp_path)
    build_bundle(repo, commit, REPOSITORY, "source", archive, manifest)
    assert archive.read_bytes() == compressed.getvalue()
    verified, contents = verify_bundle(archive, manifest)
    with (tmp_path / "verified.tar").open("w+b") as output:
        output.write(b"stale scratch contents")
        assert verify_bundle_into(archive, manifest, output) == verified
        assert output.read() == contents


def test_large_blob_build_and_verify_have_bounded_python_allocations(
    tmp_path: Path,
) -> None:
    repo, _, _ = source_repo(tmp_path)
    size = 16 * 1024 * 1024
    with (repo / "large.bin").open("wb") as output:
        block = bytes(range(256)) * 4096
        for _ in range(16):
            output.write(block)
    run(repo, "add", "large.bin")
    run(repo, "commit", "-m", "large transport blob")
    commit = run(repo, "rev-parse", "HEAD")
    archive, manifest = bundle_paths(tmp_path)
    tracemalloc.start()
    try:
        built = build_bundle(repo, commit, REPOSITORY, "source", archive, manifest)
        _, build_peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    tracemalloc.start()
    try:
        with (tmp_path / "verified.tar").open("w+b") as output:
            assert verify_bundle_into(archive, manifest, output) == built
            extract_bundle(output, built, tmp_path / "large-extracted")
        _, verify_peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    # More than a chunk-buffer budget, less than even one whole transported blob.
    assert build_peak < size // 2
    assert verify_peak < size // 2
    restored = tmp_path / "large-extracted" / "source" / "large.bin"
    assert restored.stat().st_size == size
    with restored.open("rb") as source:
        assert hashlib.file_digest(source, "sha256").hexdigest() == next(
            entry["sha256"]
            for entry in built["entries"]
            if entry["path"] == "source/large.bin"
        )


def test_missing_git_blob_does_not_publish_partial_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import qualification_source_bundle as bundle

    repo, commit, _ = source_repo(tmp_path)
    monkeypatch.setattr(
        bundle, "git_tree_entries", lambda *_: [("missing", "100644", "0" * 40)]
    )
    archive, manifest = bundle_paths(tmp_path)
    with pytest.raises(ValueError, match="unexpected git cat-file header"):
        build_bundle(repo, commit, REPOSITORY, "source", archive, manifest)
    assert not archive.exists()
    assert not manifest.exists()


def test_truncated_batch_blob_reaps_child_without_publishing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import qualification_source_bundle as bundle

    repo, commit, _ = source_repo(tmp_path)
    popen = subprocess.Popen
    children = []

    def truncated_batch(args, **kwargs):
        if args[-2:] != ["cat-file", "--batch"]:
            return popen(args, **kwargs)
        child = popen(
            [
                sys.executable,
                "-c",
                "import sys; oid=sys.stdin.buffer.readline().strip(); "
                "sys.stdout.buffer.write(oid+b' blob 1024\\nshort'); "
                "sys.stdout.buffer.flush()",
            ],
            **kwargs,
        )
        children.append(child)
        return child

    monkeypatch.setattr(bundle.subprocess, "Popen", truncated_batch)
    archive, manifest = bundle_paths(tmp_path)
    with pytest.raises(ValueError, match="truncated blob"):
        build_bundle(repo, commit, REPOSITORY, "source", archive, manifest)
    assert children and all(child.poll() is not None for child in children)
    assert not archive.exists() and not manifest.exists()


def test_git_symlink_escape_is_rejected_before_publication(tmp_path: Path) -> None:
    repo, _, _ = source_repo(tmp_path)
    oid = (
        subprocess.check_output(
            ["git", "-C", str(repo), "hash-object", "-w", "--stdin"],
            input=b"../../outside",
        )
        .strip()
        .decode()
    )
    # Build the Git entry directly: no Windows symlink permission is required.
    run(repo, "update-index", "--add", "--cacheinfo", f"120000,{oid},bad-link")
    run(repo, "commit", "-m", "unsafe committed symlink")
    archive, manifest = bundle_paths(tmp_path)
    with pytest.raises(ValueError, match="symlink target escapes"):
        build_bundle(
            repo,
            run(repo, "rev-parse", "HEAD"),
            REPOSITORY,
            "source",
            archive,
            manifest,
        )
    assert not archive.exists() and not manifest.exists()


def test_corrupt_gzip_snapshot_cannot_reach_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, commit, _ = source_repo(tmp_path)
    archive, manifest = bundle_paths(tmp_path)
    build_bundle(repo, commit, REPOSITORY, "source", archive, manifest)
    corrupt = archive.read_bytes()[:-4]
    archive.write_bytes(corrupt)
    value = json.loads(manifest.read_text())
    value["archive"].update(
        bytes=len(corrupt), sha256=hashlib.sha256(corrupt).hexdigest()
    )
    manifest.write_bytes(canonical_json(value))
    target = tmp_path / "must-not-extract"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "qualification_source_bundle.py",
            "--verify",
            "--archive",
            str(archive),
            "--manifest",
            str(manifest),
            "--extract-root",
            str(target),
        ],
    )
    assert main() == 2
    assert not target.exists()


def test_verification_extracts_the_hashed_snapshot_not_a_reopened_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, commit, _ = source_repo(tmp_path)
    archive, manifest = bundle_paths(tmp_path)
    built = build_bundle(repo, commit, REPOSITORY, "source", archive, manifest)
    gzip_file = gzip.GzipFile

    def replace_original(*args, **kwargs):
        archive.write_bytes(b"concurrent replacement")
        return gzip_file(*args, **kwargs)

    monkeypatch.setattr(gzip, "GzipFile", replace_original)
    target = tmp_path / "snapshot-extracted"
    with (tmp_path / "verified.tar").open("w+b") as output:
        assert verify_bundle_into(archive, manifest, output) == built
        extract_bundle(output, built, target)
    assert (target / "source" / "run.sh").read_bytes() == b"#!/bin/sh\nexit 0\n"
    # The CLI must not publish a receipt binding the replaced archive's hash.
    build_bundle(repo, commit, REPOSITORY, "source", *bundle_paths(tmp_path, "cli"))
    cli_archive, cli_manifest = bundle_paths(tmp_path, "cli")

    def replace_cli_original(*args, **kwargs):
        cli_archive.write_bytes(b"concurrent CLI replacement")
        return gzip_file(*args, **kwargs)

    monkeypatch.setattr(gzip, "GzipFile", replace_cli_original)
    receipt = tmp_path / "must-not-publish.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "qualification_source_bundle.py",
            "--verify",
            "--archive",
            str(cli_archive),
            "--manifest",
            str(cli_manifest),
            "--output",
            str(receipt),
        ],
    )
    assert main() == 2
    assert not receipt.exists()


def test_manifest_validates_against_public_schema(tmp_path: Path) -> None:
    repo, commit, _ = source_repo(tmp_path)
    archive, manifest = bundle_paths(tmp_path)
    value = build_bundle(repo, commit, REPOSITORY, "source", archive, manifest)
    schema = json.loads(
        (ROOT / "schemas" / "qualification_source_bundle.schema.json").read_text(
            encoding="utf-8"
        )
    )

    jsonschema.Draft202012Validator(schema).validate(value)


def test_archive_or_manifest_tamper_fails_closed(tmp_path: Path) -> None:
    repo, commit, _ = source_repo(tmp_path)
    archive, manifest = bundle_paths(tmp_path)
    build_bundle(repo, commit, REPOSITORY, "source", archive, manifest)

    original_archive = archive.read_bytes()
    archive.write_bytes(original_archive[:-1] + bytes([original_archive[-1] ^ 1]))
    with pytest.raises(ValueError, match="SHA-256"):
        verify_bundle(archive, manifest)

    archive.write_bytes(original_archive)
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["entries"][-1]["mode"] ^= 0o111
    manifest.write_bytes(canonical_json(value))
    with pytest.raises(ValueError, match="entries"):
        verify_bundle(archive, manifest)


def test_unrecognized_manifest_payload_fails_closed(tmp_path: Path) -> None:
    repo, commit, _ = source_repo(tmp_path)
    archive, manifest = bundle_paths(tmp_path)
    build_bundle(repo, commit, REPOSITORY, "source", archive, manifest)
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["authorization"] = {"gpu": True}
    manifest.write_bytes(canonical_json(value))

    with pytest.raises(ValueError, match="unrecognized top-level"):
        verify_bundle(archive, manifest)


def test_output_and_extract_targets_are_immutable(tmp_path: Path) -> None:
    repo, commit, _ = source_repo(tmp_path)
    archive, manifest = bundle_paths(tmp_path)
    build_bundle(repo, commit, REPOSITORY, "source", archive, manifest)
    with pytest.raises(ValueError, match="must not already exist"):
        build_bundle(repo, commit, REPOSITORY, "source", archive, manifest)

    value, tar_bytes = verify_bundle(archive, manifest)
    target = tmp_path / "target"
    target.mkdir()
    with pytest.raises(ValueError, match="must not already exist"):
        extract_bundle(tar_bytes, value, target)


@pytest.mark.parametrize("target", ["../../escape", "/absolute", "../../../source"])
def test_symlink_escape_is_rejected(target: str) -> None:
    with pytest.raises(ValueError, match="symlink target"):
        safe_symlink_target(PurePosixPath("source/nested/link"), target, "source")


def test_special_archive_entry_is_rejected(tmp_path: Path) -> None:
    tar_output = io.BytesIO()
    with tarfile.open(fileobj=tar_output, mode="w:") as archive:
        root = tarfile.TarInfo("source/")
        root.type = tarfile.DIRTYPE
        root.mode = 0o755
        archive.addfile(root)
        fifo = tarfile.TarInfo("source/pipe")
        fifo.type = tarfile.FIFOTYPE
        fifo.mode = stat.S_IRUSR | stat.S_IWUSR
        archive.addfile(fifo)

    from qualification_source_bundle import entries_from_tar

    with pytest.raises(ValueError, match="unsupported archive member type"):
        entries_from_tar(tar_output.getvalue(), "source")


def test_cli_build_and_verify_emit_bound_receipts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, commit, _ = source_repo(tmp_path)
    archive, manifest = bundle_paths(tmp_path)
    build_receipt = tmp_path / "build-result.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "qualification_source_bundle.py",
            "--build",
            "--repo",
            str(repo),
            "--commit",
            commit,
            "--repository-url",
            REPOSITORY,
            "--archive",
            str(archive),
            "--manifest",
            str(manifest),
            "--output",
            str(build_receipt),
        ],
    )
    assert main() == 0
    capsys.readouterr()
    built = json.loads(build_receipt.read_text(encoding="utf-8"))
    assert built["status"] == "PASS"
    assert built["source"]["commit"] == commit

    verify_receipt = tmp_path / "verify-result.json"
    extract_root = tmp_path / "cli-extracted"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "qualification_source_bundle.py",
            "--verify",
            "--archive",
            str(archive),
            "--manifest",
            str(manifest),
            "--extract-root",
            str(extract_root),
            "--output",
            str(verify_receipt),
        ],
    )
    assert main() == 0
    capsys.readouterr()
    verified = json.loads(verify_receipt.read_text(encoding="utf-8"))
    assert verified["status"] == "PASS"
    assert verified["extracted"] is True
    assert (extract_root / "source" / "run.sh").read_bytes().startswith(b"#!")


@pytest.mark.skipif(os.name == "nt", reason="Windows symlinks require host policy")
def test_safe_relative_symlink_round_trip(tmp_path: Path) -> None:
    repo, commit, _ = source_repo(tmp_path)
    os.symlink("payload.bin", repo / "nested" / "payload-link")
    run(repo, "add", "nested/payload-link")
    run(repo, "commit", "-m", "add symlink")
    commit = run(repo, "rev-parse", "HEAD")
    archive, manifest = bundle_paths(tmp_path)
    value = build_bundle(repo, commit, REPOSITORY, "source", archive, manifest)
    verified, tar_bytes = verify_bundle(archive, manifest)
    target = tmp_path / "symlink-extracted"
    extract_bundle(tar_bytes, verified, target)
    assert (target / "source" / "nested" / "payload-link").is_symlink()
    assert any(entry["type"] == "symlink" for entry in value["entries"])
