#!/usr/bin/env python3
"""Tests for deterministic, checkout-independent Git source bundles."""

from __future__ import annotations

import gzip
import io
import json
import os
import stat
import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath

import jsonschema
import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from qualification_source_bundle import (  # noqa: E402
    build_bundle,
    canonical_json,
    deterministic_tar,
    entries_from_tar,
    entries_from_tar_stream,
    extract_bundle,
    extract_bundle_stream,
    git_tree_blobs,
    iter_git_tree_blobs,
    main,
    safe_symlink_target,
    verify_bundle,
    verified_bundle,
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


def test_literal_subset_is_exact_deterministic_and_labeled(tmp_path: Path) -> None:
    repo, commit, payload = source_repo(tmp_path)
    archive, manifest = bundle_paths(tmp_path, "subset")
    value = build_bundle(
        repo, commit, REPOSITORY, "source", archive, manifest,
        included_paths=["run.sh", "nested", "nested"],
    )
    assert value["source"]["included_paths"] == ["nested", "run.sh"]
    schema = json.loads((ROOT / "schemas/qualification_source_bundle.schema.json").read_bytes())
    jsonschema.Draft202012Validator(schema).validate(value)
    verified, tar_bytes = verify_bundle(archive, manifest)
    target = tmp_path / "subset-extracted"
    extract_bundle(tar_bytes, verified, target)
    assert (target / "source/nested/payload.bin").read_bytes() == payload
    assert not (target / "source/ignored.txt").exists()
    assert {e["path"] for e in value["entries"] if e["type"] == "file"} == {
        "source/nested/payload.bin", "source/run.sh"
    }
    archive2, manifest2 = bundle_paths(tmp_path, "reordered")
    build_bundle(repo, commit, REPOSITORY, "source", archive2, manifest2,
                 included_paths=["nested", "run.sh"])
    assert archive.read_bytes() == archive2.read_bytes()
    assert manifest.read_bytes() == manifest2.read_bytes()


def test_subset_avoids_unrelated_missing_blob_but_not_selected_missing_blob(tmp_path: Path) -> None:
    repo, commit, _ = source_repo(tmp_path)
    blob = run(repo, "rev-parse", f"{commit}:ignored.txt")
    loose_blob = repo / ".git/objects" / blob[:2] / blob[2:]
    loose_blob.chmod(stat.S_IREAD | stat.S_IWRITE)
    loose_blob.unlink()  # Disposable fixture, not a user repository.
    archive, manifest = bundle_paths(tmp_path, "full-missing")
    with pytest.raises(ValueError, match="unexpected git cat-file header"):
        build_bundle(repo, commit, REPOSITORY, "source", archive, manifest)
    assert not archive.exists() and not manifest.exists()
    archive, manifest = bundle_paths(tmp_path, "available-subset")
    build_bundle(repo, commit, REPOSITORY, "source", archive, manifest,
                 included_paths=["nested"])
    verify_bundle(archive, manifest)
    archive, manifest = bundle_paths(tmp_path, "selected-missing")
    with pytest.raises(ValueError, match="unexpected git cat-file header"):
        build_bundle(repo, commit, REPOSITORY, "source", archive, manifest,
                     included_paths=["ignored.txt"])
    assert not archive.exists() and not manifest.exists()


@pytest.mark.parametrize("paths", [[], ["../outside"], ["/absolute"], ["a/../b"],
                                  ["a\\b"], ["nested/"], ["./nested"], ["a//b"],
                                  ["C:/source"], [None], ["bad\0path"], ["absent"],
                                  ["nested", "absent"], [":(glob)*"], ["nest*"]])
def test_subset_rejects_unsafe_or_unmatched_literal_paths(tmp_path: Path, paths) -> None:
    repo, commit, _ = source_repo(tmp_path)
    archive, manifest = bundle_paths(tmp_path)
    with pytest.raises(ValueError):
        build_bundle(repo, commit, REPOSITORY, "source", archive, manifest,
                     included_paths=paths)
    assert not archive.exists() and not manifest.exists()


def test_subset_verifier_rejects_scope_lie(tmp_path: Path) -> None:
    repo, commit, _ = source_repo(tmp_path)
    archive, manifest = bundle_paths(tmp_path)
    value = build_bundle(repo, commit, REPOSITORY, "source", archive, manifest)
    value["source"]["included_paths"] = ["nested"]
    manifest.write_bytes(canonical_json(value))
    with pytest.raises(ValueError, match="outside included_paths"):
        verify_bundle(archive, manifest)


def test_subset_cli_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, commit, _ = source_repo(tmp_path)
    archive, manifest = bundle_paths(tmp_path)
    monkeypatch.setattr(sys, "argv", ["bundle", "--build", "--repo", str(repo),
        "--commit", commit, "--repository-url", REPOSITORY, "--path", "nested",
        "--archive", str(archive), "--manifest", str(manifest)])
    assert main() == 0
    target = tmp_path / "cli-subset"
    monkeypatch.setattr(sys, "argv", ["bundle", "--verify", "--extract-root", str(target),
        "--archive", str(archive), "--manifest", str(manifest)])
    assert main() == 0
    assert (target / "source/nested/payload.bin").is_file()
    monkeypatch.setattr(sys, "argv", ["bundle", "--verify", "--path", "nested",
        "--archive", str(archive), "--manifest", str(manifest)])
    assert main() == 2


def test_autocrlf_checkout_cannot_change_bundle_text(tmp_path: Path) -> None:
    repo, _, _ = source_repo(tmp_path)
    run(repo, "config", "core.autocrlf", "true")
    raw = "# Unicode text: 参数\nvalue = 'a}b'\n".encode("utf-8")
    (repo / "text.py").write_bytes(raw)
    run(repo, "add", "text.py")
    run(repo, "commit", "-m", "add normalized text")
    commit = run(repo, "rev-parse", "HEAD")
    checkout = tmp_path / "crlf-checkout"
    run(repo, "checkout-index", "--all", f"--prefix={checkout.as_posix()}/")
    assert (checkout / "text.py").read_bytes() == raw.replace(b"\n", b"\r\n")
    # Even a mixed/newline dirty copy must not replace committed LF bytes.
    (repo / "text.py").write_bytes(raw.replace(b"\n", b"\r\n") + b"# dirty\n")
    archive, manifest = bundle_paths(tmp_path)
    build_bundle(repo, commit, REPOSITORY, "source", archive, manifest)
    verified, tar_bytes = verify_bundle(archive, manifest)
    target = tmp_path / "raw-blob-extracted"
    extract_bundle(tar_bytes, verified, target)
    assert (target / "source" / "text.py").read_bytes() == raw


def test_streamed_build_matches_in_memory_tar_and_gzip(tmp_path: Path) -> None:
    repo, _, _ = source_repo(tmp_path)
    # More than a compression copy block, plus names requiring PAX headers.
    name = "参数-" + "long-" * 22 + ".txt"
    (repo / name).write_bytes(b"raw\x00bytes\xff\n" * 120_000)
    run(repo, "add", ".")
    run(repo, "commit", "-m", "add larger blob")
    commit = run(repo, "rev-parse", "HEAD")
    tar_bytes, entries = deterministic_tar(git_tree_blobs(repo, commit), "source")
    assert entries == entries_from_tar(tar_bytes, "source")
    compressed = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=compressed, mtime=0) as handle:
        handle.write(tar_bytes)
    archive, manifest = bundle_paths(tmp_path)
    value = build_bundle(repo, commit, REPOSITORY, "source", archive, manifest)
    assert archive.read_bytes() == compressed.getvalue()
    assert value["entries"] == entries
    assert verify_bundle(archive, manifest)[1] == tar_bytes


def test_tar_member_hashing_uses_bounded_reads() -> None:
    payload = b"binary\x00\xff" * 400_000
    tar_bytes, expected = deterministic_tar([("big.bin", 0o100644, payload)], "source")

    class BoundedReader(io.BytesIO):
        def read(self, size=-1):
            assert 0 <= size <= 1024 * 1024, "unbounded tar payload read"
            return super().read(size)

    assert entries_from_tar_stream(BoundedReader(tar_bytes), "source") == expected


def test_verified_stream_is_a_snapshot_and_closes_on_caller_failure(
    tmp_path: Path,
) -> None:
    repo, commit, payload = source_repo(tmp_path)
    archive, manifest = bundle_paths(tmp_path)
    expected = build_bundle(repo, commit, REPOSITORY, "source", archive, manifest)
    with pytest.raises(RuntimeError, match="caller failure"):
        with verified_bundle(archive, manifest) as (value, stream):
            assert value == expected
            # The pathname no longer contains the verified bytes. Extraction
            # must still use the checked private snapshot, never reopen it.
            archive.write_bytes(b"replaced after verification")
            target = tmp_path / "snapshot-extracted"
            extract_bundle_stream(stream, value, target)
            assert (target / "source/nested/payload.bin").read_bytes() == payload
            raise RuntimeError("caller failure")
    assert stream.closed
    assert not list(tmp_path.glob("tmp*"))


def test_verification_snapshots_compressed_bytes_under_per_file_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _, _ = source_repo(tmp_path)
    # Each source file fits the worker limit; their complete tar does not.
    for index in range(4):
        (repo / f"part-{index}.bin").write_bytes(bytes([index]) * 400_000)
    run(repo, "add", ".")
    run(repo, "commit", "-m", "larger highly compressible package")
    archive, manifest = bundle_paths(tmp_path)
    build_bundle(
        repo, run(repo, "rev-parse", "HEAD"), REPOSITORY,
        "source", archive, manifest,
    )
    assert archive.stat().st_size < 1024 * 1024
    import qualification_source_bundle as bundler
    temporary_file = bundler.tempfile.TemporaryFile
    written = []

    class LimitedFile:
        def __init__(self, *args, **kwargs):
            self.file = temporary_file(*args, **kwargs)
            written.append(0)
            self.index = len(written) - 1

        def write(self, data):
            extent = max(written[self.index], self.file.tell() + len(data))
            if extent > 1024 * 1024:
                raise OSError("per-file worker limit")
            written[self.index] = extent
            return self.file.write(data)

        def __getattr__(self, name):
            return getattr(self.file, name)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.file.close()

    monkeypatch.setattr(bundler.tempfile, "TemporaryFile", LimitedFile)
    with verified_bundle(archive, manifest) as (value, stream):
        # Preserve snapshot isolation even while extraction replays gzip seeks.
        archive.write_bytes(b"changed after verification")
        target = tmp_path / "limited-extracted"
        extract_bundle_stream(stream, value, target)
        for index in range(4):
            extracted = target / "source" / f"part-{index}.bin"
            assert extracted.read_bytes() == bytes([index]) * 400_000
    assert len(written) == 1
    assert written[0] == value["archive"]["bytes"]
    assert stream.closed


@pytest.mark.parametrize("corruption", ["truncate", "crc", "mtime"])
def test_streamed_verify_rejects_rebound_gzip_corruption(
    tmp_path: Path, corruption: str
) -> None:
    repo, commit, _ = source_repo(tmp_path)
    archive, manifest = bundle_paths(tmp_path)
    value = build_bundle(repo, commit, REPOSITORY, "source", archive, manifest)
    compressed = bytearray(archive.read_bytes())
    if corruption == "truncate":
        del compressed[-5:]
    elif corruption == "crc":
        compressed[-8] ^= 1
    else:
        compressed[4] = 1
    archive.write_bytes(compressed)
    from qualification_source_bundle import sha256_file

    value["archive"].update(bytes=len(compressed), sha256=sha256_file(archive))
    manifest.write_bytes(canonical_json(value))
    message = "mtime" if corruption == "mtime" else "invalid gzip"
    with pytest.raises(ValueError, match=message):
        with verified_bundle(archive, manifest):
            pytest.fail("corrupt gzip must not yield a verified stream")


@pytest.mark.parametrize(
    "kind, message",
    [
        ("traversal", "unsafe archive member"),
        ("duplicate", "duplicate archive member"),
        ("symlink", "symlink target escapes"),
        ("hardlink", "unsupported archive member type"),
        ("fifo", "unsupported archive member type"),
    ],
)
def test_streamed_verify_preserves_tar_rejections(
    tmp_path: Path, kind: str, message: str
) -> None:
    repo, commit, _ = source_repo(tmp_path)
    archive, manifest = bundle_paths(tmp_path)
    value = build_bundle(repo, commit, REPOSITORY, "source", archive, manifest)
    tar_output = io.BytesIO()
    with tarfile.open(fileobj=tar_output, mode="w:") as tar:
        root = tarfile.TarInfo("source/")
        root.type = tarfile.DIRTYPE
        tar.addfile(root)
        member = tarfile.TarInfo("source/entry")
        if kind == "traversal":
            member.name = "source/../escape"
        elif kind == "duplicate":
            member.name = "source"
            member.type = tarfile.DIRTYPE
        elif kind == "symlink":
            member.type = tarfile.SYMTYPE
            member.linkname = "../../escape"
        elif kind == "hardlink":
            member.type = tarfile.LNKTYPE
            member.linkname = "source/other"
        else:
            member.type = tarfile.FIFOTYPE
        tar.addfile(member)
    archive.write_bytes(gzip.compress(tar_output.getvalue(), mtime=0))
    from qualification_source_bundle import sha256_file

    value["archive"].update(
        bytes=archive.stat().st_size, sha256=sha256_file(archive)
    )
    manifest.write_bytes(canonical_json(value))
    with pytest.raises(ValueError, match=message):
        with verified_bundle(archive, manifest):
            pytest.fail("unsafe tar must not yield a verified stream")


def test_streamed_cli_does_not_use_in_memory_helpers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, commit, payload = source_repo(tmp_path)
    archive, manifest = bundle_paths(tmp_path)
    build_bundle(repo, commit, REPOSITORY, "source", archive, manifest)
    target = tmp_path / "streamed-cli"
    original_read_bytes = Path.read_bytes

    def read_bytes(path):
        assert path != archive, "whole compressed archive read"
        return original_read_bytes(path)

    def unbounded(*args, **kwargs):
        pytest.fail("CLI must not call a whole-payload helper")

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    monkeypatch.setattr(gzip, "decompress", unbounded)
    monkeypatch.setattr("qualification_source_bundle.verify_bundle", unbounded)
    monkeypatch.setattr("qualification_source_bundle.extract_bundle", unbounded)
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
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
    assert (target / "source/nested/payload.bin").read_bytes() == payload


def test_failed_streamed_cli_does_not_publish_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, commit, _ = source_repo(tmp_path)
    archive, manifest = bundle_paths(tmp_path)
    value = build_bundle(repo, commit, REPOSITORY, "source", archive, manifest)
    file_entry = next(entry for entry in value["entries"] if entry["type"] == "file")
    file_entry["sha256"] = "0" * 64
    manifest.write_bytes(canonical_json(value))
    target = tmp_path / "must-not-exist"
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
    before = sorted(path.name for path in tmp_path.iterdir())
    assert main() == 2
    assert "entries do not exactly match" in capsys.readouterr().err
    assert not target.exists()
    assert sorted(path.name for path in tmp_path.iterdir()) == before


@pytest.mark.skipif(os.name != "nt", reason="Native Windows path interpretation")
@pytest.mark.parametrize(
    "name",
    [
        "..\\..\\outside.txt",
        "C:/outside.txt",
        "payload:stream",
        "NUL.txt",
        "COM¹.log",
        "trailing.",
        "trailing ",
        "a?b",
    ],
)
def test_windows_member_rejected_before_native_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    tar_bytes, entries = deterministic_tar([(name, 0o100644, b"payload")], "source")
    assert entries_from_tar(tar_bytes, "source") == entries
    original_mkdir = Path.mkdir

    def mkdir(path, *args, **kwargs):
        assert path.resolve().is_relative_to(tmp_path.resolve()), "unsafe mkdir reached"
        return original_mkdir(path, *args, **kwargs)

    def open_file(*args, **kwargs):
        pytest.fail("native file write reached before path rejection")

    monkeypatch.setattr(Path, "mkdir", mkdir)
    monkeypatch.setattr(Path, "open", open_file)
    with pytest.raises(ValueError, match="unsafe Windows extraction path"):
        extract_bundle(tar_bytes, {"entries": entries}, tmp_path / "target")
    assert not (tmp_path / "target").exists()
    assert not list(tmp_path.glob(".target.*"))


@pytest.mark.skipif(os.name != "nt", reason="Native Windows symlink interpretation")
@pytest.mark.parametrize(
    "link_target", ["C:outside", "..\\..\\outside", "NUL", "payload:stream"]
)
def test_windows_link_target_rejected_before_link_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, link_target: str
) -> None:
    tar_bytes, entries = deterministic_tar(
        [("nested/link", 0o120000, link_target.encode())], "source"
    )
    assert entries_from_tar(tar_bytes, "source") == entries

    def symlink(*args, **kwargs):
        pytest.fail("native link creation reached before path rejection")

    monkeypatch.setattr(os, "symlink", symlink)
    with pytest.raises(ValueError, match="unsafe Windows extraction path"):
        extract_bundle(tar_bytes, {"entries": entries}, tmp_path / "target")
    assert not (tmp_path / "target").exists()
    assert not list(tmp_path.glob(".target.*"))


def test_member_under_symlink_is_rejected_before_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:") as archive:
        link = tarfile.TarInfo("source/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "."
        archive.addfile(link)
        archive.addfile(tarfile.TarInfo("source/link/child"), io.BytesIO(b""))
    tar_bytes = output.getvalue()
    entries = entries_from_tar(tar_bytes, "source")

    def symlink(*args, **kwargs):
        pytest.fail("symlink parent must be rejected before creation")

    monkeypatch.setattr(os, "symlink", symlink)
    with pytest.raises(ValueError, match="uses symlink parent"):
        extract_bundle(tar_bytes, {"entries": entries}, tmp_path / "target")
    assert not (tmp_path / "target").exists()
    assert not list(tmp_path.glob(".target.*"))


@pytest.mark.skipif(os.name == "nt", reason="Windows symlinks require host policy")
@pytest.mark.parametrize("link_name", ["alink", "zlink"])
def test_native_symlink_chain_cannot_escape_staging(
    tmp_path: Path, link_name: str
) -> None:
    # Both targets are lexically inside source/. Resolving d/step -> ..
    # consumes less depth than lexical normalization, making the other link
    # escape. alink is created before step; zlink is created after it.
    tar_bytes, entries = deterministic_tar(
        [("d/step", 0o120000, b".."),
         (link_name, 0o120000, b"d/step/../../outside.txt")],
        "source",
    )
    assert entries_from_tar(tar_bytes, "source") == entries
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"untouched sentinel")
    with pytest.raises(ValueError, match="escapes extraction staging"):
        extract_bundle(tar_bytes, {"entries": entries}, tmp_path / "target")
    assert outside.read_bytes() == b"untouched sentinel"
    assert not (tmp_path / "target").exists()
    assert not list(tmp_path.glob(".target.*"))


@pytest.mark.parametrize(
    "blobs, message",
    [
        ([("../escape", 0o100644, b"data")], "unsafe archive member"),
        ([("same", 0o100644, b"one"), ("same", 0o100644, b"two")], "duplicate"),
    ],
)
def test_streamed_tar_preserves_path_rejections(blobs, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        deterministic_tar(blobs, "source")


def test_missing_blob_does_not_publish_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, commit, _ = source_repo(tmp_path)
    monkeypatch.setattr(
        "qualification_source_bundle.git_tree_entries",
        lambda *_: [("missing", "100644", "0" * 40)],
    )
    archive, manifest = bundle_paths(tmp_path / "failed-build")
    with pytest.raises(ValueError, match="unexpected git cat-file header"):
        build_bundle(repo, commit, REPOSITORY, "source", archive, manifest)
    assert not archive.exists()
    assert not manifest.exists()


def test_promisor_missing_blob_does_not_trigger_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, commit, _ = source_repo(tmp_path)
    blob = run(repo, "rev-parse", f"{commit}:nested/payload.bin")
    # Only delete a loose object inside this disposable fixture repository.
    loose_blob = repo / ".git" / "objects" / blob[:2] / blob[2:]
    loose_blob.chmod(stat.S_IREAD | stat.S_IWRITE)  # Git marks objects read-only.
    loose_blob.unlink()
    run(repo, "config", "remote.origin.promisor", "true")
    run(repo, "config", "remote.origin.url", (tmp_path / "absent-remote").as_uri())
    trace = tmp_path / "git-trace.log"
    monkeypatch.setenv("GIT_TRACE", trace.as_posix())
    monkeypatch.setenv("GIT_NO_LAZY_FETCH", "0")
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")
    # Counterfactual: this fixture actually invokes lazy fetch without the
    # builder's protection. It can only target a nonexistent local file URI.
    control = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "blob", blob],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=15,
    )
    assert control.returncode != 0
    control_trace = trace.read_text(encoding="utf-8")
    assert "fetch origin" in control_trace

    archive, manifest = bundle_paths(tmp_path / "local-only")
    with pytest.raises(ValueError, match="unexpected git cat-file header"):
        build_bundle(repo, commit, REPOSITORY, "source", archive, manifest)
    build_trace = trace.read_text(encoding="utf-8")[len(control_trace) :]
    assert "fetch origin" not in build_trace
    assert not archive.exists()
    assert not manifest.exists()


def test_all_git_reads_force_local_only_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, commit, _ = source_repo(tmp_path)
    monkeypatch.setenv("GIT_NO_LAZY_FETCH", "0")
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "1")
    real_run, real_popen = subprocess.run, subprocess.Popen
    observed = []

    def check_env(kwargs):
        assert kwargs["env"]["GIT_NO_LAZY_FETCH"] == "1"
        assert kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"

    def checked_run(*args, **kwargs):
        check_env(kwargs)
        observed.append("run")
        return real_run(*args, **kwargs)

    def checked_popen(*args, **kwargs):
        check_env(kwargs)
        observed.append("popen")
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", checked_run)
    monkeypatch.setattr(subprocess, "Popen", checked_popen)
    archive, manifest = bundle_paths(tmp_path)
    build_bundle(repo, commit, REPOSITORY, "source", archive, manifest)
    assert observed.count("run") == 3
    assert observed.count("popen") == 4  # three run children plus batch reader


def test_submodule_is_not_silently_omitted(tmp_path: Path) -> None:
    repo, commit, _ = source_repo(tmp_path)
    run(repo, "update-index", "--add", "--cacheinfo", f"160000,{commit},vendor")
    run(repo, "commit", "-m", "add gitlink")
    archive, manifest = bundle_paths(tmp_path / "gitlink-build")
    with pytest.raises(ValueError, match="unsupported Git tree entry 160000 commit"):
        build_bundle(repo, "HEAD", REPOSITORY, "source", archive, manifest)
    assert not archive.exists()
    assert not manifest.exists()


def test_early_blob_iterator_close_reaps_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    object_id = "a" * 40

    class Child:
        stdout = io.BytesIO(f"{object_id} blob 1\nx\n".encode())
        returncode = None
        killed = False

        def poll(self):
            return self.returncode

        def kill(self):
            self.killed = True
            self.returncode = -9

        def wait(self):
            return self.returncode

    child = Child()

    def popen(*args, **kwargs):
        assert kwargs["stdin"].read() == f"{object_id}\n".encode()
        assert hasattr(kwargs["stderr"], "write")
        return child

    monkeypatch.setattr(subprocess, "Popen", popen)
    blobs = iter_git_tree_blobs(tmp_path, [("file", "100644", object_id)])
    assert next(blobs) == ("file", 0o100644, b"x")
    blobs.close()
    assert child.killed
    assert child.stdout.closed


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
