"""Do not fill an optional read slot after a complete explicit definition.

Offline producer/real AST-selector checks; no provider, network or execution.
"""

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout as scout
import kimi_scout_research as research
from scout_requested_definition import requested_function_window
from tests.test_kimi_scout_research import Context


REPO = "a/b"
PATH = "src/context.py"
OTHER = "src/unrelated.py"
RAW = "class TreeComponent:\n    def __init__(self):\n        self._session_leaves = defaultdict(set)\n"


class ExactDefinitionReadTests(unittest.TestCase):
    def run_followup(
        self,
        request="definition(TreeComponent.__init__)",
        *,
        complete=True,
        test_request=None,
        references=None,
        imports=None,
        continuation=None,
        definition_metadata=True,
        ranked_paths=None,
    ):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scout.initialize(root)
            config = root / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "objective": "Offline read admission",
                        "queue_target": 4,
                        "repos": [
                            {
                                "repo": REPO,
                                "source_prefixes": ["src/"],
                                "question": "Inspect the contract",
                            }
                        ],
                    }
                )
            )
            ctx = Context()
            ctx.cached_source_text = lambda *args: RAW
            calls = []

            def snapshot(*args, **kwargs):
                return {
                    "commit": ctx.revision,
                    "files": [PATH, OTHER, "tests/test_context.py"],
                    "blobs": {PATH: "b" * 40, OTHER: "c" * 40},
                }

            def source(repo, commit, path, **kwargs):
                calls.append(path)
                text = RAW if path == PATH else "unrelated fallback source"
                result = {
                    "url": f"https://raw.githubusercontent.com/{repo}/{commit}/{path}",
                    "text": text,
                }
                target = requested_function_window(
                    RAW.splitlines(), kwargs.get("request_hints")
                )
                if path == PATH and target is not None:
                    result.update(
                        requested_definition=target if definition_metadata else None,
                        requested_definition_complete=complete,
                    )
                return result

            with patch.object(
                research, "lesson_suggestions", return_value={"status": "NO_MATCH"}
            ):
                producer = research.ResearchProducer(root, config, context=ctx)
                producer.lessons = []
                spec = producer.config["repos"][0]
                spec["followup_import_context"] = bool(imports)
                producer.emit(
                    "parent",
                    spec,
                    [
                        {
                            "url": f"https://raw.githubusercontent.com/{REPO}/{ctx.revision}/{PATH}",
                            "text": "current_leaves = self._session_leaves[session_id]",
                        }
                    ],
                    "source_audit",
                )
                with scout.connect(root) as db:
                    db.execute(
                        "UPDATE jobs SET state='NEEDS_CONTEXT',finished=?,result=?",
                        (
                            time.time(),
                            scout.dumps(
                                {
                                    "analysis": {
                                        "title": "Context field",
                                        "hypothesis": "Check initialization",
                                        "decision": "needs_context",
                                        "next_check": request,
                                        "evidence": [],
                                    }
                                }
                            ),
                        ),
                    )
                progress = {}
                with (
                    patch.object(ctx, "snapshot", side_effect=snapshot),
                    patch.object(ctx, "source", side_effect=source),
                    patch.object(ctx, "duplicate_sources", return_value=[]),
                    patch.object(
                        research, "relevant_paths",
                        return_value=[PATH, OTHER] if ranked_paths is None else ranked_paths,
                    ),
                    patch.object(
                        research, "continuation_request", return_value=continuation
                    ),
                    patch.object(research, "contract_requests", return_value=[]),
                    patch.object(
                        research, "followup_test_request", return_value=test_request
                    ),
                    patch.object(
                        research, "reference_requests", return_value=references or []
                    ),
                    patch.object(
                        research, "import_requests", return_value=imports or []
                    ),
                ):
                    self.assertTrue(producer.followup(spec, progress))
                with scout.connect(root) as db:
                    packet = json.loads(
                        db.execute(
                            "SELECT packet FROM jobs WHERE name!='parent' ORDER BY created DESC LIMIT 1"
                        ).fetchone()[0]
                    )
                return calls, packet, progress

    def test_complete_explicit_definition_does_not_fetch_unrequested_fallback(self):
        calls, packet, progress = self.run_followup()
        self.assertEqual(calls, [PATH])
        self.assertIn("defaultdict(set)", scout.dumps(packet))
        self.assertNotIn("unrelated fallback source", scout.dumps(packet))
        self.assertEqual(progress["satisfied_definition_optional_reads_omitted"], 1)

    def test_incomplete_definition_keeps_the_existing_fallback(self):
        calls, _, progress = self.run_followup(complete=False)
        self.assertEqual(calls, [PATH, OTHER])
        self.assertNotIn("satisfied_definition_optional_reads_omitted", progress)

    def test_cached_qualified_target_precedes_an_unrelated_ranked_path(self):
        calls, packet, _ = self.run_followup(ranked_paths=[OTHER, PATH])
        self.assertEqual(calls, [PATH])
        self.assertIn("defaultdict(set)", scout.dumps(packet))
        self.assertNotIn("unrelated fallback source", scout.dumps(packet))

    def test_cached_target_does_not_add_an_ineligible_path(self):
        calls, _, _ = self.run_followup(ranked_paths=[OTHER])
        self.assertEqual(calls, [OTHER])

    def test_truthy_non_boolean_completeness_does_not_skip(self):
        calls, _, _ = self.run_followup(complete=1)
        self.assertEqual(calls, [PATH, OTHER])

    def test_missing_target_metadata_does_not_skip(self):
        calls, _, _ = self.run_followup(definition_metadata=False)
        self.assertEqual(calls, [PATH, OTHER])

    def test_plain_prose_is_not_a_single_explicit_request(self):
        calls, _, progress = self.run_followup("Inspect TreeComponent.__init__")
        self.assertEqual(calls, [PATH, OTHER])
        self.assertNotIn("satisfied_definition_optional_reads_omitted", progress)

    def test_multiple_explicit_definitions_are_not_silently_shortened(self):
        calls, _, _ = self.run_followup(
            "definition(TreeComponent.__init__) definition(other)"
        )
        self.assertEqual(calls, [PATH, OTHER])

    def test_repeated_explicit_markers_keep_the_existing_fallback(self):
        calls, _, _ = self.run_followup(
            "definition(TreeComponent.__init__) definition(TreeComponent.__init__)"
        )
        self.assertEqual(calls, [PATH, OTHER])

    def test_continuation_is_not_silently_shortened(self):
        calls, _, _ = self.run_followup(
            continuation={"path": PATH, "start": 1, "max_lines": 80, "tail_start": 81}
        )
        self.assertEqual(calls, [PATH, PATH])

    def test_companion_test_is_not_dropped(self):
        calls, _, _ = self.run_followup(
            test_request={"path": "tests/test_context.py", "max_lines": 80}
        )
        self.assertEqual(calls, [PATH, "tests/test_context.py"])

    def test_requested_reference_reads_are_not_shortened(self):
        calls, _, _ = self.run_followup(
            "definition(TreeComponent.__init__) references(field)",
            references=[
                {"path": PATH, "start": 1, "max_lines": 80},
                {"path": OTHER, "start": 1, "max_lines": 80},
            ],
        )
        self.assertEqual(calls, [PATH, OTHER])

    def test_import_hop_is_not_dropped(self):
        calls, _, _ = self.run_followup(imports=[{"path": OTHER, "max_lines": 80}])
        self.assertEqual(calls, [PATH, OTHER])


if __name__ == "__main__":
    unittest.main()
