"""Literal source targeting only; no C++ parser, imports or native execution."""
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from kimi_scout_context import PublicContext
from scout_requested_definition import requested_native_literal_anchor


class CppQualifiedHintTests(unittest.TestCase):
    def source(self, raw, request, *, path='src/codegen.cc', start=None, exact_hint=None,
               max_lines=80, hints='GEMM store BufferStoreNode'):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        reader = PublicContext(Path(directory.name))
        data = raw.encode()
        blob = hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        snapshot = dict(files=[path], blobs={path:blob})
        with patch.object(reader, 'snapshot', return_value=snapshot), \
             patch.object(reader, '_read', return_value=raw) as fetch:
            arguments = dict(hints=hints, request_hints=request, max_lines=max_lines,
                             start=start, exact_hint=exact_hint)
            result = reader.source('owner/project', 'a'*40, path, **arguments)
            repeated = reader.source('owner/project', 'a'*40, path, **arguments)
        self.assertEqual(result, repeated)
        self.assertEqual(fetch.call_count, 1)
        self.assertLessEqual(len(result['text'].splitlines()), max_lines)
        return result

    def test_qualified_request_beats_unrelated_keyword_score(self):
        raw = ('// GEMM store BufferStoreNode\n'+'// unrelated\n'*200+
               'void CodeGenTileLangPTO::EmitScalarizedStore(const BufferStoreNode *op) {\n'
               '  emit_actual_store();\n}\n'+'// tail\n'*100)
        result = self.source(raw, 'definition(CodeGenTileLangPTO::EmitScalarizedStore)')
        self.assertEqual(result['start_line'], 202)
        self.assertIn('emit_actual_store', result['text'])
        self.assertEqual(result['requested_native_literal']['literal'],
                         'CodeGenTileLangPTO::EmitScalarizedStore')
        self.assertNotIn('requested_definition_complete', result)

    def test_explicit_start_and_literal_keep_precedence(self):
        raw = '// chosen\n'+'// tail\n'*100+'void Owner::target() {}\n'
        for arguments in (dict(start=1), dict(exact_hint='chosen')):
            with self.subTest(arguments=arguments):
                result = self.source(raw, 'definition(Owner::target)', **arguments)
                self.assertEqual(result['start_line'], 1)
                self.assertNotIn('requested_native_literal', result)

    def test_non_native_files_do_not_gain_cpp_location_semantics(self):
        raw = '// GEMM store BufferStoreNode\n'+'// tail\n'*100+'void Owner::target() {}\n'
        result = self.source(raw, 'definition(Owner::target)', path='src/fixture.py')
        self.assertEqual(result['start_line'], 1)
        self.assertNotIn('requested_native_literal', result)

    def test_ambiguous_missing_or_multiple_requests_keep_fallback(self):
        for request, tail in (
            ('definition(Owner::target)', 'void Owner::target();\nvoid Owner::target() {}\n'),
            ('definition(Owner::missing)', 'void Owner::target() {}\n'),
            ('definition(Owner::target) definition(Owner::other)', 'void Owner::target() {}\n'),
            ('definition(Owner::target); definition(Owner::target)', 'void Owner::target() {}\n'),
            ('definition(Owner::target); definition(', 'void Owner::target() {}\n'),
            ('references(Owner::target)', 'void Owner::target() {}\n'),
            ('definition(Owner::target<int>)', 'void Owner::target() {}\n'),
        ):
            with self.subTest(request=request, tail=tail):
                raw = '// GEMM store BufferStoreNode\n'+'// filler\n'*100+tail
                result = self.source(raw, request)
                self.assertEqual(result['start_line'], 1)
                self.assertNotIn('requested_native_literal', result)

    def test_names_are_literal_not_substrings_or_owner_resolution(self):
        raw = ('// GEMM store BufferStoreNode\n'+'// filler\n'*100+
               'void OtherOwner::target() {}\nvoid Owner::target_suffix() {}\n'
               'void Deep::Owner::target() {}\nvoid Owner::target() {}\n')
        result = self.source(raw, 'definition(Owner::target)')
        self.assertEqual(result['start_line'], 105)
        self.assertEqual(result['requested_native_literal']['line'], 105)

    def test_scope_explicitly_allows_comments_and_generated_source_strings(self):
        raw = '// Owner::target() in a generated example, not a definition\n'
        result = self.source(raw, 'definition(Owner::target)')
        self.assertIn('comments/strings', result['requested_native_literal']['scope'])
        self.assertNotIn('requested_definition_complete', result)

    def test_window_and_character_caps_do_not_become_complete_body_claims(self):
        raw = 'void Owner::target() {\n'+'  '+('x'*12000)+'\n}\n'
        result = self.source(raw, 'definition(Owner::target)', max_lines=2)
        self.assertLessEqual(result['end_line'], 2)
        self.assertLessEqual(len(result['text']), 9000)
        self.assertTrue(result['truncated'])
        self.assertNotIn('requested_definition_complete', result)

    def test_standalone_lookup_remains_bounded_and_rejects_malformed_inputs(self):
        for raw, request in ((None, 'definition(Owner::target)'),
                             ('void Owner::target() {}', None),
                             ('x'*1_000_001, 'definition(Owner::target)'),
                             ('void Owner::target() {}', 'definition(Owner::target\n)'),
                             ('void Owner::target() {}', 'definition(Owner::operator())')):
            with self.subTest(request=request):
                self.assertIsNone(requested_native_literal_anchor(raw, request))


if __name__ == '__main__':
    unittest.main()
