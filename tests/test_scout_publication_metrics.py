"""Offline recorded-PR identity counts; no GitHub, model or execution calls."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout_delivery as delivery


def link(repo="public/project", number=1):
    return {
        "repo": repo,
        "result": json.dumps(
            {"pr": {"url": f"https://github.com/{repo}/pull/{number}"}}
        ),
    }


class PublicationMetricsTests(unittest.TestCase):
    def legacy_candidate(self, root, state):
        delivery.initialize(root)
        result = {"before": {"exit_code": 1}, "fixed": {"exit_code": 0}}
        with delivery.database(root) as db:
            db.execute(
                "INSERT INTO delivery "
                "(id,source_job_id,dedup_key,repo,title,state,reason,updated_at,payload,result,reported_tokens) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "a" * 24,
                    "b" * 24,
                    "key",
                    "public/project",
                    "candidate",
                    state,
                    "historical result",
                    0,
                    '{"source":"unchanged"}',
                    json.dumps(result),
                    321,
                ),
            )
        return result

    def test_duplicate_candidates_count_as_one_pr(self):
        result = delivery.publication_summary(
            [link(), link("PUBLIC/Project"), link(number=2), link("other/project")]
        )
        self.assertEqual(result["candidate_records"], 4)
        self.assertEqual(result["distinct_prs"], 3)
        self.assertEqual(result["unverified_links"], 0)
        self.assertIn("not inferred", result["claim_boundary"])

    def test_owner_reproduction_can_reconcile_an_inconclusive_screen(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = self.legacy_candidate(root, "INCONCLUSIVE")
            url = "https://github.com/public/project/pull/123"
            with self.assertRaises(ValueError):
                delivery.mark_pr(root, "a" * 24, url)
            recorded = delivery.mark_pr(
                root, "a" * 24, url, owner_reproduced_after_block=True
            )
            self.assertEqual(recorded["prior_state"], "INCONCLUSIVE")
            self.assertEqual(recorded["prior_reason"], "historical result")
            self.assertIn("inconclusive screen", recorded["claim_boundary"])
            self.assertEqual(delivery.mark_pr(root, "a" * 24, url), recorded)
            with self.assertRaisesRegex(ValueError, "another PR"):
                delivery.mark_pr(root, "a" * 24, url.replace("123", "124"))
            with delivery.database(root) as db:
                row = db.execute("SELECT * FROM delivery").fetchone()
            self.assertEqual(row["state"], "PR_OPEN")
            self.assertEqual(row["reported_tokens"], 321)
            self.assertEqual(row["payload"], '{"source":"unchanged"}')
            updated = json.loads(row["result"])
            self.assertEqual({k: v for k, v in updated.items() if k != "pr"}, original)
            self.assertNotIn("owner_handoff", updated)

    def test_reproduction_flag_cannot_override_active_or_other_terminal_states(self):
        for state in (
            "PENDING",
            "TESTING",
            "FAILED",
            "NO_BUG",
            "OWNER_PARKED",
            "GPU_REVIEW_REQUIRED",
            "REPRODUCED",
            "OWNER_REVIEW_REQUIRED",
        ):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                original = self.legacy_candidate(root, state)
                with self.assertRaises(ValueError):
                    delivery.mark_pr(
                        root,
                        "a" * 24,
                        "https://github.com/public/project/pull/1",
                        owner_reproduced_after_block=True,
                    )
                with delivery.database(root) as db:
                    row = db.execute("SELECT * FROM delivery").fetchone()
                self.assertEqual(row["state"], state)
                self.assertEqual(json.loads(row["result"]), original)

    def test_inconclusive_reproduction_still_requires_the_same_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = self.legacy_candidate(root, "INCONCLUSIVE")
            with self.assertRaisesRegex(ValueError, "repository"):
                delivery.mark_pr(
                    root,
                    "a" * 24,
                    "https://github.com/other/project/pull/1",
                    owner_reproduced_after_block=True,
                )
            with delivery.database(root) as db:
                row = db.execute("SELECT * FROM delivery").fetchone()
            self.assertEqual(row["state"], "INCONCLUSIVE")
            self.assertEqual(json.loads(row["result"]), original)

    def test_unbound_or_malformed_links_are_not_publications(self):
        invalid = [
            {"repo": "public/project", "result": value}
            for value in ("{}", "null", "[]", "invalid JSON", None)
        ]
        for url in (
            "https://github.com/other/project/pull/1",
            "https://github.com/public/project/issues/1",
            "https://github.com/public/project/pull/1#discussion",
            "https://github.com/public/project/pull/01",
            "https://example.com/public/project/pull/1",
        ):
            invalid.append(
                {"repo": "public/project", "result": json.dumps({"pr": {"url": url}})}
            )
        invalid.append({"repo": None, "result": link()["result"]})
        result = delivery.publication_summary(iter(invalid))
        self.assertEqual(result["candidate_records"], len(invalid))
        self.assertEqual(result["distinct_prs"], 0)
        self.assertEqual(result["unverified_links"], len(invalid))

    def test_empty_records_are_zero_not_a_live_github_assertion(self):
        result = delivery.publication_summary([])
        self.assertEqual(result["distinct_prs"], 0)
        self.assertEqual(result["candidate_records"], 0)

    def test_worker_publishes_distinct_count_separate_from_row_states(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            worker = delivery.Delivery.__new__(delivery.Delivery)
            worker.root = root
            worker.args = SimpleNamespace(
                concurrency=16, execution_concurrency=1, owner_queue_limit=64
            )
            delivery.initialize(root)
            with delivery.database(root) as db:
                for i in range(2):
                    db.execute(
                        "INSERT INTO delivery "
                        "(id,source_job_id,dedup_key,repo,title,state,reason,updated_at,payload,result) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (
                            f"{i:024x}",
                            f"{i:024x}",
                            f"{i:024x}",
                            "public/project",
                            "candidate",
                            "PR_OPEN",
                            "Owner linked PR",
                            0,
                            "{}",
                            link()["result"],
                        ),
                    )
            worker.publish("STOPPED")
            runtime = json.loads((root / "runtime.json").read_text(encoding="utf-8"))
            self.assertEqual(runtime["counts"]["PR_OPEN"], 2)
            self.assertEqual(runtime["publications"]["distinct_prs"], 1)
            self.assertEqual(runtime["publications"]["candidate_records"], 2)
            self.assertEqual(runtime["owner_ready"], 0)


if __name__ == "__main__":
    unittest.main()
