from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("candidate_source", ROOT / "scripts" / "candidate_source.py")
assert SPEC and SPEC.loader
candidate_source = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(candidate_source)


def git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return result.stdout.strip()


class CandidateSourceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repository = Path(self.temporary.name) / "source"
        self.repository.mkdir()
        git(self.repository, "init", "-q")
        git(self.repository, "config", "user.name", "Test User")
        git(self.repository, "config", "user.email", "test@example.com")
        git(self.repository, "config", "core.autocrlf", "false")
        (self.repository / "changed.txt").write_bytes(b"base\n")
        (self.repository / "deleted.txt").write_bytes(b"delete me\n")
        git(self.repository, "add", ".")
        git(self.repository, "commit", "-q", "-m", "base")
        self.base = git(self.repository, "rev-parse", "HEAD")

        (self.repository / "changed.txt").write_bytes(b"candidate\n")
        (self.repository / "deleted.txt").unlink()
        (self.repository / "added.bin").write_bytes(b"\x00\xff\x10")
        git(self.repository, "add", "-A")
        git(self.repository, "commit", "-q", "-m", "candidate")
        self.candidate = git(self.repository, "rev-parse", "HEAD")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_seal_and_verify_derive_exact_git_objects(self) -> None:
        receipt = Path(self.temporary.name) / "receipt.json"
        sealed = candidate_source.seal(self.repository, "example/project", self.base, self.candidate, receipt)

        self.assertEqual(sealed["candidate"]["tree"], git(self.repository, "rev-parse", "HEAD^{tree}"))
        self.assertEqual([entry["status"] for entry in sealed["changed_paths"]], ["A", "M", "D"])
        self.assertFalse(sealed["claim_boundary"]["worktree_bytes_used"])
        self.assertEqual(candidate_source.verify(self.repository, receipt), sealed)

    def test_verify_is_independent_of_checkout_line_endings(self) -> None:
        receipt = Path(self.temporary.name) / "receipt.json"
        sealed = candidate_source.seal(self.repository, "example/project", self.base, self.candidate, receipt)
        clone = Path(self.temporary.name) / "clone"
        subprocess.run(["git", "clone", "-q", str(self.repository), str(clone)], check=True)
        git(clone, "config", "core.autocrlf", "true")

        self.assertEqual(candidate_source.verify(clone, receipt)["source_identity_sha256"], sealed["source_identity_sha256"])

    def test_public_cli_dispatches_and_propagates_status(self) -> None:
        receipt = Path(self.temporary.name) / "cli-receipt.json"
        command = [
            sys.executable,
            str(ROOT / "scripts" / "kernel_opt.py"),
            "candidate-source",
            "seal",
            "--repository",
            str(self.repository),
            "--repository-id",
            "example/project",
            "--base",
            self.base,
            "--candidate",
            self.candidate,
            "--output",
            str(receipt),
        ]
        result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(receipt.is_file())
        failed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        self.assertEqual(failed.returncode, 2)
        self.assertIn("refusing to overwrite", failed.stderr)

    def test_seal_rejects_dirty_worktree_and_existing_output(self) -> None:
        receipt = Path(self.temporary.name) / "receipt.json"
        candidate_source.seal(self.repository, "example/project", self.base, self.candidate, receipt)
        with self.assertRaisesRegex(candidate_source.SourceIdentityError, "overwrite"):
            candidate_source.seal(self.repository, "example/project", self.base, self.candidate, receipt)
        (self.repository / "untracked.txt").write_text("dirty", encoding="utf-8")
        with self.assertRaisesRegex(candidate_source.SourceIdentityError, "not clean"):
            candidate_source.seal(
                self.repository,
                "example/project",
                self.base,
                self.candidate,
                Path(self.temporary.name) / "other.json",
            )

    def test_rejects_non_ancestor_and_empty_candidate(self) -> None:
        with self.assertRaisesRegex(candidate_source.SourceIdentityError, "no committed diff"):
            candidate_source.derive_identity(self.repository, "example/project", self.candidate, self.candidate)
        git(self.repository, "checkout", "-q", "--orphan", "unrelated")
        git(self.repository, "rm", "-q", "-rf", ".")
        (self.repository / "other.txt").write_text("other\n", encoding="utf-8")
        git(self.repository, "add", ".")
        git(self.repository, "commit", "-q", "-m", "unrelated")
        unrelated = git(self.repository, "rev-parse", "HEAD")
        with self.assertRaisesRegex(candidate_source.SourceIdentityError, "not an ancestor"):
            candidate_source.derive_identity(self.repository, "example/project", self.candidate, unrelated)

    def test_verify_rejects_tampered_tree_patch_and_blob(self) -> None:
        receipt = Path(self.temporary.name) / "receipt.json"
        candidate_source.seal(self.repository, "example/project", self.base, self.candidate, receipt)
        original = json.loads(receipt.read_text(encoding="utf-8"))
        mutations = [
            ("tree", lambda value: value["candidate"].update(tree="0" * 40)),
            ("patch", lambda value: value["patch"].update(diff_sha256="0" * 64)),
            ("blob", lambda value: value["changed_paths"][0]["candidate_object"].update(sha256="0" * 64)),
        ]
        for name, mutate in mutations:
            value = json.loads(json.dumps(original))
            mutate(value)
            tampered = Path(self.temporary.name) / f"tampered-{name}.json"
            tampered.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(candidate_source.SourceIdentityError, "does not match"):
                candidate_source.verify(self.repository, tampered)


if __name__ == "__main__":
    unittest.main()
