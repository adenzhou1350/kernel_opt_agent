"""Local disposable Git fixtures; no network, target imports or model calls."""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import qualification_source_bundle as bundle
import scout_public_export as exporter


def card(ident='first-lesson'):
    return dict(id=ident, title=ident, applies_when='Review a matching contract',
                lesson='Read the actual contract ' + ident, avoid_when='Do not infer qualification',
                status='hypothesis', evidence=[dict(url='https://example.org/evidence',
                                                    note='A public mechanism only')])


class PublicExportTests(unittest.TestCase):
    def git(self, *args):
        result = subprocess.run(['git', '-C', str(self.repo), *args], check=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return result.stdout.decode().strip()

    def write(self, path, raw):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)

    def commit(self):
        self.git('add', '.')
        self.git('-c', 'user.name=Export Test', '-c', 'user.email=export@example.invalid',
                 'commit', '-m', 'fixture')
        return self.git('rev-parse', 'HEAD')

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / 'repo'; self.repo.mkdir()
        self.git('init')
        self.git('config', 'core.autocrlf', 'false')
        self.write('scripts/kimi_scout.py', b'import helper\r\nraise RuntimeError("never import target")\r\n')
        self.write('scripts/scout_openai_backend.py', b'from helper import value\nimport json\n')
        self.write('scripts/helper.py', b'from more import value\nimport kimi_scout\n')
        self.write('scripts/more.py', b'value = 3\n')
        self.write('scripts/unused.py', b'import irrelevant\n')
        self.write('knowledge/lessons/first-lesson.json', json.dumps(card()).encode())
        self.write('run/scout.sqlite', b'not-for-export')
        self.write('provider.json', b'not-for-export')
        self.write('.env', b'not-for-export')
        self.pin = self.commit()
        self.output = self.root / 'export'

    def test_exact_pinned_bytes_static_cycle_and_private_files_excluded(self):
        original = self.git('status', '--porcelain')
        result = exporter.export(self.repo, self.pin, self.output)
        self.assertEqual(result['source_modules'], 4)
        self.assertEqual(result['lesson_cards'], 1)
        self.assertEqual(result['external_import_roots'], ['json'])
        self.assertEqual(set(result['files']), {
            'scripts/kimi_scout.py', 'scripts/scout_openai_backend.py',
            'scripts/helper.py', 'scripts/more.py', 'knowledge/lessons/first-lesson.json',
        })
        for path, identity in result['files'].items():
            raw = (self.output / path).read_bytes()
            self.assertEqual(raw, (self.repo / path).read_bytes())
            self.assertEqual(hashlib.sha256(raw).hexdigest(), identity['sha256'])
        self.assertEqual(self.git('status', '--porcelain'), original)
        self.assertIn('Not a secret scanner', result['boundary'])

    def test_dirty_checkout_and_untracked_provider_do_not_change_export(self):
        expected = (self.repo / 'scripts/kimi_scout.py').read_bytes()
        self.write('scripts/kimi_scout.py', b'import private_provider\n')
        self.write('scripts/private_provider.py', b'not-for-export')
        result = exporter.export(self.repo, self.pin, self.output)
        self.assertEqual((self.output / 'scripts/kimi_scout.py').read_bytes(), expected)
        self.assertNotIn('scripts/private_provider.py', result['files'])
        self.assertTrue(self.git('status', '--porcelain'))

    def test_batches_card_reads_not_one_git_process_per_file(self):
        for index in range(20):
            ident = f'lesson-{index}'
            self.write('knowledge/lessons/' + ident + '.json', json.dumps(card(ident)).encode())
        pin = self.commit()
        with patch.object(bundle.subprocess, 'Popen', wraps=subprocess.Popen) as calls:
            result = exporter.export(self.repo, pin, self.output)
        batches = [call for call in calls.call_args_list if 'cat-file' in call.args[0]]
        self.assertEqual(len(batches), 4)  # Three static import frontiers plus all cards.
        self.assertEqual(result['lesson_cards'], 21)

    def test_existing_output_preserved(self):
        self.output.mkdir(); (self.output / 'sentinel').write_bytes(b'preserved')
        with self.assertRaisesRegex(ValueError, 'fresh'):
            exporter.export(self.repo, self.pin, self.output)
        self.assertEqual((self.output / 'sentinel').read_bytes(), b'preserved')

    def test_full_commit_required_and_tree_is_not_a_commit(self):
        for revision in ('HEAD', self.pin[:8], self.git('rev-parse', 'HEAD^{tree}')):
            with self.assertRaises(ValueError):
                exporter.export(self.repo, revision, self.output)
            self.assertFalse(self.output.exists())

    def test_missing_entrypoint_no_output(self):
        (self.repo / 'scripts/kimi_scout.py').unlink()
        with self.assertRaisesRegex(ValueError, 'entrypoint'):
            exporter.export(self.repo, self.commit(), self.output)
        self.assertFalse(self.output.exists())

    def test_selected_symlink_is_not_followed(self):
        oid = self.git('rev-parse', self.pin + ':scripts/more.py')
        self.git('update-index', '--cacheinfo', '120000,' + oid + ',scripts/helper.py')
        self.git('-c', 'user.name=Export Test', '-c', 'user.email=export@example.invalid',
                 'commit', '-m', 'link fixture')
        with self.assertRaisesRegex(ValueError, 'regular Git file'):
            exporter.export(self.repo, self.git('rev-parse', 'HEAD'), self.output)
        self.assertFalse(self.output.exists())

    def test_sibling_relative_imports_resolve_without_importing_target(self):
        self.write('scripts/helper.py', b'from .more import value\nfrom . import kimi_scout\n')
        result = exporter.export(self.repo, self.commit(), self.output)
        self.assertEqual(result['source_modules'], 4)
        self.assertIn('scripts/more.py', result['files'])

    def test_parent_relative_and_local_package_imports_are_not_silently_omitted(self):
        for body in (b'from ..more import value\n', b'import pkg\n', b'from . import unknown\n'):
            self.write('scripts/helper.py', body)
            self.write('scripts/pkg/__init__.py', b'value = 1\n')
            with self.assertRaisesRegex(ValueError, 'separately reviewed package export'):
                exporter.export(self.repo, self.commit(), self.output)
            self.assertFalse(self.output.exists())

    def test_bad_lesson_or_identity_fails_before_output(self):
        for value in (b'not JSON', json.dumps(card('other-id')).encode()):
            self.write('knowledge/lessons/first-lesson.json', value)
            with self.assertRaises(ValueError):
                exporter.export(self.repo, self.commit(), self.output)
            self.assertFalse(self.output.exists())

    def test_file_blob_and_total_budgets_fail_before_output(self):
        for name, cap in (('MAX_FILES', 2), ('MAX_BLOB_BYTES', 2), ('MAX_TOTAL_BYTES', 2)):
            with patch.object(exporter, name, cap), self.assertRaisesRegex(ValueError, 'budget'):
                exporter.export(self.repo, self.pin, self.output)
            self.assertFalse(self.output.exists())

    def test_duplicate_library_advice_fails_before_output(self):
        second = card('second-lesson')
        second['title'] = 'FIRST LESSON!'
        self.write('knowledge/lessons/second-lesson.json', json.dumps(second).encode())
        with self.assertRaisesRegex(ValueError, 'duplicate lesson title'):
            exporter.export(self.repo, self.commit(), self.output)
        self.assertFalse(self.output.exists())

    def test_invalid_python_is_not_exported(self):
        self.write('scripts/helper.py', b'def broken(:\n')
        with self.assertRaises(SyntaxError):
            exporter.export(self.repo, self.commit(), self.output)
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
