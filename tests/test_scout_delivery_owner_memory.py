"""Fresh optional owner advice reaches a request, not an automatic decision."""

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout_delivery as delivery
import scout_publication_context as memory

REPO = "public/project"
URL = f"https://raw.githubusercontent.com/{REPO}/{'a' * 40}/src/subject.py"
PR = f"https://github.com/{REPO}/pull/23"


class DeliveryMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write_notes(self):
        publication = memory.owner_publication_note_path(self.root, REPO)
        publication.parent.mkdir(exist_ok=True)
        publication.write_text(
            json.dumps(
                [
                    dict(
                        repo=REPO,
                        prior_hypothesis="Old subject fix",
                        source_url=URL,
                        pr_url=PR,
                    )
                ]
            ),
            encoding="utf-8",
        )
        deferral = memory.owner_source_note_path(self.root, REPO)
        deferral.parent.mkdir(exist_ok=True)
        deferral.write_text(
            json.dumps(
                [
                    dict(
                        repo=REPO,
                        prior_hypothesis="Subject old caller",
                        source_url=URL,
                        reason="Old caller did not reach that branch.",
                        reopen_when="A distinct supported caller or source change.",
                        evidence_url=f"https://github.com/{REPO}/blob/{'a' * 40}/src/subject.py",
                    )
                ]
            ),
            encoding="utf-8",
        )
        return publication, deferral

    def context(self):
        return dict(
            repo=REPO,
            url=URL,
            path="src/subject.py",
            hypothesis=dict(title="New distinct subject failure"),
            source="def value():\n    return 1\n",
        )

    def test_staged_old_packet_gets_new_notes_at_generation(self):
        worker = delivery.Delivery(
            SimpleNamespace(
                root=self.root,
                execution_concurrency=1,
                github_auth=False,
            )
        )
        delivery.initialize(worker.root)
        lead = dict(
            id="fresh",
            repo=REPO,
            canonical_key="distinct",
            packet={},
            analysis=self.context()["hypothesis"],
        )
        delivery.stage(worker.root, [lead])
        job = delivery.claim(worker.root)
        notes = self.write_notes()  # Recorded after the immutable lead was staged.
        before = {p: p.read_bytes() for p in notes}
        source = dict(source=self.context()["source"], path="src/subject.py", url=URL)
        answer = dict(
            decision="needs_context",
            reason="Distinct caller still needed",
            test_code="",
            edits=[],
        )
        with (
            patch.object(delivery, "load_source", return_value=source),
            patch.object(worker, "check_runtime") as runtime,
            patch.object(worker, "model", return_value=answer) as model,
            patch.object(worker, "sandbox") as sandbox,
        ):
            self.assertEqual(worker.execute(job), "INCONCLUSIVE")
        sandbox.assert_not_called()
        runtime.assert_called_once_with(worker.root / "jobs" / job["id"], "stdlib")
        self.assertEqual(model.call_count, 1)
        packet = json.loads(model.call_args.args[2].split("\nPUBLIC DATA:\n", 1)[1])
        self.assertEqual(packet["owner_publications"]["items"][0]["url"], PR)
        self.assertIn("Never reject", packet["owner_deferrals"]["caution"])
        self.assertEqual(packet["source"], source["source"])
        self.assertEqual(packet["hypothesis"], lead["analysis"])
        self.assertEqual({p: p.read_bytes() for p in notes}, before)
        with delivery.database(worker.root) as db:
            stored = json.loads(
                db.execute("SELECT payload FROM delivery").fetchone()[0]
            )
        self.assertEqual(stored, lead)  # No retroactive history/source rewrite.

    def test_advice_is_bounded_optional_and_keeps_primary_bytes(self):
        notes = self.write_notes()
        before = {p: p.read_bytes() for p in notes}
        context = self.context()
        original = copy.deepcopy(context)
        delivery.add_owner_delivery_memory(context, self.root, delivery.PROMPT)
        self.assertEqual({k: context[k] for k in original}, original)
        self.assertLessEqual(
            len(delivery.scout.dumps(context).encode())
            - len(delivery.scout.dumps(original).encode()),
            4096,
        )
        self.assertEqual(context["owner_publications"]["items"][0]["url"], PR)
        self.assertEqual({p: p.read_bytes() for p in notes}, before)

    def test_missing_corrupt_or_unmatched_advice_is_not_a_rejection(self):
        for variant in ("missing", "corrupt", "unmatched"):
            with self.subTest(variant=variant):
                if variant != "missing":
                    paths = self.write_notes()
                    if variant == "corrupt":
                        for p in paths:
                            p.write_text("not JSON", encoding="utf-8")
                context = self.context()
                if variant == "unmatched":
                    context["repo"] = "other/project"
                before = copy.deepcopy(context)
                delivery.add_owner_delivery_memory(context, self.root, delivery.PROMPT)
                self.assertEqual(context, before)

    def test_near_request_limit_never_grows_or_clips_primary_input(self):
        self.write_notes()
        for prefix in (delivery.PROMPT, delivery.GPU_PROMPT):
            with self.subTest(prefix=prefix[:20]):
                context = self.context()
                # Find a fitting base request with almost no room for advice;
                # quotes expand twice through the inner and outer JSON layers.
                low, high = 0, 120_000
                while low < high:
                    middle = (low + high + 1) // 2
                    context["source"] = '"' * middle
                    request = delivery.model_request(
                        prefix + "\nPUBLIC DATA:\n" + delivery.scout.dumps(context)
                    )
                    if len(delivery.scout.dumps(request).encode()) <= 240000:
                        low = middle
                    else:
                        high = middle - 1
                context["source"] = '"' * low
                before = copy.deepcopy(context)
                delivery.add_owner_delivery_memory(context, self.root, prefix)
                self.assertEqual({k: context[k] for k in before}, before)
                request = delivery.model_request(
                    prefix + "\nPUBLIC DATA:\n" + delivery.scout.dumps(context)
                )
                self.assertLessEqual(
                    len(delivery.scout.dumps(request).encode()), 240000
                )


if __name__ == "__main__":
    unittest.main()
