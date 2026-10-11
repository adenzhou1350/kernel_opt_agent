"""Native Git/export checks for the community trial's no-live-links source policy."""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from community_evaluation import safe_extract_zip, write_git_source_zip  # noqa: E402


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        stdout=subprocess.PIPE,
        encoding="utf-8",
    ).stdout.strip()


def repository(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Source Test")
    git(repo, "config", "user.email", "source@example.invalid")
    git(repo, "config", "core.autocrlf", "false")
    (repo / ".gitattributes").write_bytes(
        b"ignored.txt export-ignore\nsubstitution.txt export-subst\n"
        b"operator.py text eol=crlf\n"
    )
    (repo / "operator.py").write_bytes(b"value = 1\n")
    (repo / "ignored.txt").write_bytes(b"still part of the commit\n")
    (repo / "substitution.txt").write_bytes(b"$Format:%H$\n")
    git(repo, "add", ".")
    # Add a genuine mode-120000 Git entry without requiring Windows symlink rights.
    link_blob = subprocess.run(
        ["git", "-C", str(repo), "hash-object", "-w", "--stdin"],
        input=b"../outside",
        stdout=subprocess.PIPE,
        check=True,
    ).stdout.decode("ascii").strip()
    git(repo, "update-index", "--add", "--cacheinfo", f"120000,{link_blob},link")
    git(repo, "commit", "-q", "-m", "fixture")
    return repo, git(repo, "rev-parse", "HEAD")


def test_trial_export_preserves_raw_blobs_and_link_text(tmp_path: Path) -> None:
    repo, revision = repository(tmp_path)
    git(repo, "config", "core.autocrlf", "true")
    first = tmp_path / "first.zip"
    write_git_source_zip(repo, revision, first)
    (repo / "operator.py").write_bytes(b"dirty\r\n")
    (repo / ".gitattributes").write_bytes(b"* export-ignore\n")
    second = tmp_path / "second.zip"
    write_git_source_zip(repo, revision, second)
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        assert archive.namelist() == [
            ".gitattributes",
            "ignored.txt",
            "link",
            "operator.py",
            "substitution.txt",
        ]
        for path in archive.namelist():
            raw = subprocess.run(
                ["git", "-C", str(repo), "show", f"{revision}:{path}"],
                stdout=subprocess.PIPE,
                check=True,
            ).stdout
            assert archive.read(path) == raw
        assert archive.getinfo("link").external_attr >> 16 == 0o120000
    extracted = tmp_path / "extracted"
    safe_extract_zip(first, extracted)
    assert (extracted / "operator.py").read_bytes() == b"value = 1\n"
    assert (extracted / "substitution.txt").read_bytes() == b"$Format:%H$\n"
    assert (extracted / "link").read_bytes() == b"../outside"
    assert not (extracted / "link").is_symlink()
    assert not (tmp_path / "outside").exists()


def test_trial_export_rejects_gitlink_before_creating_archive(tmp_path: Path) -> None:
    repo, revision = repository(tmp_path)
    git(repo, "update-index", "--add", "--cacheinfo", f"160000,{revision},vendor")
    git(repo, "commit", "-q", "-m", "gitlink")
    archive = tmp_path / "unsupported.zip"
    with pytest.raises(ValueError, match="unsupported Git tree entry 160000"):
        write_git_source_zip(repo, git(repo, "rev-parse", "HEAD"), archive)
    assert not archive.exists()
