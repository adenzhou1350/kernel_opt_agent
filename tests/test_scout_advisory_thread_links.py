"""Specific public comment evidence stays advisory, not a publication identity."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import scout_owner_note as writer


class AdvisoryThreadLinkTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = "public/project"
        self.base = f"https://github.com/{self.repo}"
        self.note = dict(
            repo=self.repo, prior_hypothesis="Optional positional parameter policy",
            source_url=f"https://raw.githubusercontent.com/{self.repo}/{'a' * 40}/src/hooks.py",
            reason="The maintainer changed the policy; preserve binding and warn.",
            reopen_when="A new contract or caller needs independent verification.",
            evidence_url=self.base + "/issues/12#issuecomment-34",
        )

    def test_public_comment_and_review_links_are_projected(self):
        for suffix in (
            "/issues/12#issuecomment-34", "/pull/12#issuecomment-34",
            "/pull/12#pullrequestreview-34", "/pull/12#discussion_r34",
            "/discussions/12#discussioncomment-34",
        ):
            with self.subTest(suffix=suffix):
                result = writer.write_note(self.root, {**self.note, "evidence_url": self.base + suffix})
                self.assertEqual(result["context_status"], "SELECTED_NOW")
                self.assertEqual(result["projection"]["evidence_url"], self.base + suffix)

    def test_comment_evidence_does_not_become_a_canonical_pr(self):
        url = self.base + "/pull/12#issuecomment-34"
        self.assertIsNotNone(writer.memory.advisory_evidence_match(url))
        # Use the canonical identity primitive shared by deployed and current
        # readers; publication-metrics integration has its own separate suite.
        self.assertIsNone(writer.memory.PR_URL.fullmatch(url))

    def test_policy_update_replaces_only_the_stable_hypothesis_key(self):
        old = {**self.note, "reason": "Wait for a policy decision.", "evidence_url": self.base + "/pull/12"}
        unrelated = {**old, "prior_hypothesis": "Another contract", "reason": "Preserve this distinct evidence."}
        target = writer.memory.owner_source_note_path(self.root, self.repo)
        target.parent.mkdir()
        target.write_text(json.dumps([old, unrelated]), encoding="utf-8")
        before = target.read_bytes()
        result = writer.write_note(self.root, self.note)
        self.assertEqual(result["context_status"], "SELECTED_NOW")
        self.assertEqual(json.loads(target.read_bytes()), [unrelated, self.note])
        self.assertIn("Wait for a policy decision.", before.decode())
        self.assertFalse((self.root / "delivery").exists())

    def test_malformed_or_cross_endpoint_fragments_are_rejected(self):
        for suffix in (
            "/issues/12#pullrequestreview-34", "/issues/12#discussion_r34",
            "/discussions/12#issuecomment-34", "/pull/12#discussioncomment-34",
            "/issues/0#issuecomment-34", "/issues/12#issuecomment-0",
            "/issues/12#issuecomment-34?token=secret", "/issues/12?token=secret#issuecomment-34",
            "/issues/12#issuecomment-34/extra", "/issues/12#issuecomment-34%0a",
            "/issues/12#issuecomment-34\n", "/issues/12#issuecomment-34#other",
            "/issues/12#arbitrary", "/pull/12#issuecomment-34 extra",
        ):
            with self.subTest(suffix=suffix):
                self.assertIsNone(writer.memory.advisory_evidence_match(self.base + suffix))

    def test_foreign_repository_comment_cannot_be_owner_evidence(self):
        with self.assertRaisesRegex(ValueError, "same-repository"):
            writer.write_note(self.root, {**self.note, "evidence_url": "https://github.com/other/project/issues/12#issuecomment-34"})
        self.assertFalse(writer.memory.owner_source_note_path(self.root, self.repo).exists())

    def test_canonical_links_remain_compatible(self):
        for suffix in ("/issues/12", "/pull/12", "/discussions/12"):
            with self.subTest(suffix=suffix):
                self.assertIsNotNone(writer.memory.advisory_evidence_match(self.base + suffix))


if __name__ == "__main__":
    unittest.main()
