"""Offline naming hints: selection is not a symbol index or defect verdict."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout as scout
import kimi_scout_research as research
import kimi_scout_context as context
from tests.test_kimi_scout_research import Context

PATH = "vllm/v1/attention/backends/mla/flashinfer_mla_sparse.py"
SYMBOL = "FlashInferMLASparseTRTLLMMetadataBuilder"


class SymbolPathTests(unittest.TestCase):
    def ranked(self, hints, files=None, **kwargs):
        return research.relevant_paths({"files": files or [PATH]}, hints, **kwargs)

    def test_compound_class_selects_observed_snake_case_module(self):
        self.assertEqual(self.ranked(f"Inspect {SYMBOL} support"), [PATH])

    def test_longer_complete_module_prefix_precedes_shorter_prefix(self):
        short = PATH.replace("_sparse", "")
        self.assertEqual(self.ranked(SYMBOL, [short, PATH]), [PATH, short])

    def test_explicit_filename_or_path_precedes_inferred_module(self):
        other = "src/other_runner.py"
        for hint in ("other_runner.py", other):
            self.assertEqual(self.ranked(f"{SYMBOL} inspect {hint}", [PATH, other]), [other, PATH])

    def test_partial_word_all_caps_and_short_generic_names_do_not_match(self):
        for hint, path in (
            ("AsyncClientish", "src/async_client.py"),
            ("FLASHINFERMLASPARSE", PATH),
            ("utils kernel CommonUtils", "src/utils.py"),
            ("TinyOpBuilder", "src/tiny_op.py"),
        ):
            self.assertEqual(self.ranked(hint, [path]), [])

    def test_existing_same_named_modules_remain_visible(self):
        alternate = "tests/flashinfer_mla_sparse.py"
        self.assertEqual(self.ranked(SYMBOL, [alternate, PATH]), [alternate, PATH])

    def test_missing_or_excluded_paths_cannot_be_created_by_hint(self):
        self.assertEqual(self.ranked(SYMBOL, ["src/unrelated.py"]), [])
        self.assertEqual(self.ranked(SYMBOL, exclude=[PATH]), [])

    def test_input_and_suffix_bounds_remain(self):
        self.assertEqual(self.ranked("x" * 16000 + SYMBOL), [])
        self.assertEqual(self.ranked(SYMBOL, [PATH.replace(".py", ".bin")]), [])

    def test_exact_class_beyond_header_keywords_is_visible_in_source_window(self):
        raw = "# prefill mentioned earlier\n" + "# padding\n" * 180
        raw += f"class {SYMBOL}:\n    _cudagraph_support = AttentionCGSupport.ALWAYS\n"
        hints = " ".join(f"header{i}" for i in range(40)) + f" prefill inspect {SYMBOL}"
        with tempfile.TemporaryDirectory() as tmp:
            ctx = context.PublicContext(Path(tmp))
            with patch.object(ctx, "snapshot", return_value={"files": [PATH]}), patch.object(ctx, "_read", return_value=raw) as reader:
                result = ctx.source("a/b", "a" * 40, PATH, hints=hints)
            self.assertIn(f"class {SYMBOL}", result["text"])
            self.assertIn("AttentionCGSupport.ALWAYS", result["text"])
            self.assertEqual(reader.call_count, 1)
            self.assertLessEqual(result["end_line"] - result["start_line"] + 1, 120)
            self.assertTrue(result["truncated"])
            self.assertNotIn("requested_definition_complete", result)

    def test_ambiguous_classes_do_not_replace_existing_lexical_fallback(self):
        lines = ["class FirstBuilder:", "    pass", "class SecondBuilder:", "    pass"]
        self.assertIsNone(context._definition_line(lines, " ".join(f"header{i}" for i in range(40)) + " FirstBuilder SecondBuilder"))

    def test_qualified_method_remains_before_class_hint(self):
        lines = ["class ExactBuilder:", "    def target(self): pass"]
        self.assertEqual(context._definition_line(lines, "Inspect ExactBuilder.target"), 1)

    def test_issue_emits_only_one_existing_pinned_source_read(self):
        class SymbolContext(Context):
            def snapshot(self, repo, ref="main"):
                return {"commit": self.revision, "files": [PATH], "blobs": {PATH: self.blob}}

            def issue_page(self, repo, page=1):
                return [{"number": 42, "title": f"Inspect {SYMBOL}", "body": "Missing graph capability",
                         "updated_at": "first", "html_url": f"https://github.com/{repo}/issues/42"}]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "config.json"
            config.write_text(json.dumps({"objective": "Offline source routing", "queue_target": 4,
                                         "repos": [{"repo": "a/b", "source_prefixes": ["vllm/"],
                                                    "question": "Inspect graph support"}]}), encoding="utf-8")
            scout.initialize(root)
            ctx = SymbolContext()
            with patch.object(research, "lesson_suggestions", return_value={"status": "NO_MATCH"}, create=True):
                producer = research.ResearchProducer(root, config, context=ctx)
                self.assertTrue(producer.issue(producer.config["repos"][0], {}))
            self.assertEqual(len(ctx.calls), 1)
            self.assertEqual(ctx.calls[0][2], PATH)
            with scout.connect(root) as db:
                packet = json.loads(db.execute("SELECT packet FROM jobs").fetchone()[0])
            self.assertEqual(len(packet["sources"]), 2)
            self.assertIn(f"/{ctx.revision}/{PATH}", packet["sources"][1]["url"])
            self.assertLessEqual(len((scout.SYSTEM + scout.dumps(packet)).encode("utf-8")), scout.MAX_INPUT_BYTES)


if __name__ == "__main__":
    unittest.main()
