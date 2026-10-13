"""Offline Go source-selection tests, never compile or execute the source."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from kimi_scout_context import PublicContext
import kimi_scout as scout
import kimi_scout_research as research
from scout_go_context import go_declaration_anchor

PIN = "a" * 40


class GoContextTests(unittest.TestCase):
    def test_plain_and_package_qualified_free_function(self):
        raw = 'package mem\n\nfunc SetUID(x int) {\n println(x)\n}\n'
        for request in ("definition(SetUID)", "definition(mem.SetUID)",
                        "definition(SetUID); compare Chown and SetGID"):
            with self.subTest(request=request):
                self.assertEqual(go_declaration_anchor(raw, request)["line"], 3)
        self.assertIsNone(go_declaration_anchor(raw, "definition(other.SetUID)"))

    def test_receiver_disambiguation_and_unqualified_ambiguity(self):
        raw = 'package p\nfunc (x *First) Read() {}\nfunc (Second) Read() {}\n'
        self.assertIsNone(go_declaration_anchor(raw, "definition(Read)"))
        self.assertEqual(go_declaration_anchor(raw, "definition(First.Read)")["line"], 2)
        self.assertEqual(go_declaration_anchor(raw, "definition(Second.Read)")["line"], 3)
        self.assertIsNone(go_declaration_anchor(raw, "definition(p.Read)"))

    def test_comments_raw_strings_quoted_strings_and_runes_do_not_define_symbols(self):
        raw = ('// package fake\npackage p\n'
               '/*\nfunc target() {}\n*/\n'
               'var text = `\nfunc target() {}\n`\n'
               'var quote = "func target() { \\"\"\n'
               "var runeValue = '}'\n"
               'func target() { println("}") }\n')
        self.assertEqual(go_declaration_anchor(raw, "definition(target)")["line"], 11)
        self.assertIsNone(go_declaration_anchor(raw, "definition(fake.target)"))

    def test_nested_declaration_shaped_text_is_not_a_top_level_match(self):
        raw = 'package p\nfunc outer() {\nfunc target() {}\n}\n'
        self.assertIsNone(go_declaration_anchor(raw, "definition(target)"))

    def test_indented_declaration_and_crlf_preserve_source_line(self):
        raw = '/* header */\r\npackage p\r\n\tfunc target() {}\r\n'
        self.assertEqual(go_declaration_anchor(raw, 'definition(p.target)')["line"], 3)

    def test_generic_function_but_not_generic_receiver_hint(self):
        self.assertEqual(go_declaration_anchor(
            'package p\nfunc target[T any](v T) T { return v }\n',
            'definition(target)',
        )["line"], 2)
        self.assertIsNone(go_declaration_anchor(
            'package p\nfunc (x Owner[T]) target() {}\n', 'definition(Owner.target)',
        ))

    def test_malformed_ambiguous_missing_or_unbounded_inputs_abstain(self):
        for raw, request in (
            ('package p\nfunc target() {}\nfunc target() {}', 'definition(target)'),
            ('package p\n/* func target() {}', 'definition(target)'),
            ('package p\nvar s = `func target() {}', 'definition(target)'),
            ('package p\nvar s = "bad\nfunc target() {}', 'definition(target)'),
            ('package p\nfunc target() {', 'definition(target)'),
            ('package p\nfunc target() {}\n}', 'definition(target)'),
            ('package p\nfunc target() {}', 'definition(missing); inspect target'),
            ('package p\nfunc target() {}', 'definition(target) definition(other)'),
            ('package p\nfunc target() {}', 'definition(target, other)'),
            ('package p\nfunc target() {}', 'definition(\ntarget)'),
            ('package p\nfunc target() {}', 'inspect target'),
            ('package p\n' + ' ' * 131072, 'definition(target)'),
            ('package p\n\x00func target() {}', 'definition(target)'),
            (None, 'definition(target)'),
        ):
            with self.subTest(raw=str(raw)[:45], request=request):
                self.assertIsNone(go_declaration_anchor(raw, request))

    def test_actual_public_context_selects_late_method_once_without_completeness_claim(self):
        path = "filesystem.go"
        raw = ('package p\n' + '\n' * 200 +
               'func (f *FS) Chown() {\n' + '\n' * 100 + ' println("tail")\n}\n')
        with tempfile.TemporaryDirectory() as root:
            ctx = PublicContext(Path(root))
            snapshot = dict(files=[path], blobs={path: "b" * 40})
            with patch.object(ctx, "snapshot", return_value=snapshot), patch.object(
                ctx, "_source_text", return_value=(raw, "injected"),
            ) as reader:
                evidence = ctx.source("owner/repo", PIN, path,
                    hints="background unrelated", request_hints="definition(FS.Chown)", max_lines=8)
                self.assertEqual(reader.call_count, 1)
            self.assertEqual(evidence["start_line"], 202)
            self.assertEqual(evidence["end_line"], 209)
            self.assertEqual(evidence["go_declaration_anchor"]["name"], "FS.Chown")
            self.assertNotIn("requested_definition_complete", evidence)
            self.assertNotIn('println("tail")', evidence["text"])
            self.assertTrue(evidence["truncated"])
            for extra in (dict(start=1), dict(exact_hint="package p")):
                with patch.object(ctx, "snapshot", return_value=snapshot):
                    evidence = ctx.source("owner/repo", PIN, path,
                        request_hints="definition(FS.Chown)", max_lines=8, **extra)
                self.assertNotIn("go_declaration_anchor", evidence)
                self.assertIn("package p", evidence["text"])

    def test_real_emitter_retains_anchor_and_bounds_without_claiming_complete_body(self):
        path = "filesystem.go"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ctx = PublicContext(root / "cache")
            with patch.object(ctx, "snapshot", return_value=dict(files=[path], blobs={path: "b" * 40})), patch.object(
                ctx, "_source_text", return_value=(
                    'package p\nfunc target() {\n' + '\n' * 100 + '}\n', "injected"),
            ):
                source = ctx.source("owner/repo", PIN, path,
                    request_hints="definition(target)", max_lines=8)
            run = root / "run"
            scout.initialize(run)
            config = root / "config.json"
            config.write_text(json.dumps(dict(objective="Offline Go evidence",
                queue_target=4, repos=[dict(repo="owner/repo", source_prefixes=[path],
                question="Check ordinary contracts")])), encoding="utf-8")
            producer = research.ResearchProducer(run, config, context=object())
            producer.lessons = []
            with patch.object(research, "lesson_suggestions", return_value={"status": "NO_MATCH"}):
                self.assertTrue(producer.emit("go-target", producer.config["repos"][0],
                    [source], "source_followup"))
            with scout.connect(run) as db:
                packet = json.loads(db.execute("SELECT packet FROM jobs").fetchone()[0])
            self.assertEqual(packet["sources"], [source])
            self.assertIn("not a complete body", source["go_declaration_anchor"]["scope"])
            self.assertNotIn("requested_definition_complete", source)
            self.assertLessEqual(len((scout.SYSTEM + scout.dumps(packet)).encode()), scout.MAX_INPUT_BYTES)


if __name__ == "__main__":
    unittest.main()
