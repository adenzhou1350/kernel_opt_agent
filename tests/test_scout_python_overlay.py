"""Fresh-copy and observation mechanics, not target-package qualification."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import scout_python_overlay as overlay


class PackageOverlayTests(unittest.TestCase):
    def setUp(self):
        self.stage = tempfile.TemporaryDirectory()
        self.addCleanup(self.stage.cleanup)
        self.root = Path(self.stage.name)
        self.package = self.root/'original'
        self.package.mkdir()
        (self.package/'__init__.py').write_text('raise RuntimeError("must not import while staging")\n')
        (self.package/'value.py').write_bytes(b'answer = 1\n')
        (self.package/'native.so').write_bytes(b'not a real native extension')
        (self.package/'resource').mkdir()
        (self.package/'resource/config.json').write_bytes(b'{"kept":true}')
        self.output = self.root/'copied'

    def stage_package(self, replacements=None, **kw):
        return overlay.stage_package(self.package, self.output,
            {'value.py': b'answer = 2\n'} if replacements is None else replacements, **kw)

    def test_copies_resources_without_importing_or_modifying_source(self):
        result = self.stage_package()
        self.assertEqual((self.package/'value.py').read_bytes(), b'answer = 1\n')
        self.assertEqual((self.output/'value.py').read_bytes(), b'answer = 2\n')
        for name in ('__init__.py', 'native.so', 'resource/config.json'):
            self.assertEqual((self.output/name).read_bytes(), (self.package/name).read_bytes())
        self.assertEqual(result['overlays']['value.py']['replacement_sha256'],
                         hashlib.sha256(b'answer = 2\n').hexdigest())
        # Modifying the copy must not alias the original through hardlinks.
        (self.output/'native.so').write_bytes(b'private copy changed')
        self.assertEqual((self.package/'native.so').read_bytes(), b'not a real native extension')

    def test_omits_stale_bytecode_and_real_import_observes_overlay(self):
        (self.package/'__init__.py').write_bytes(b'from .value import answer\n')
        (self.package/'__pycache__').mkdir()
        (self.package/'__pycache__/value.cpython-312.pyc').write_bytes(b'old cache')
        (self.package/'value.pyc').write_bytes(b'legacy cache')
        self.stage_package()
        self.assertFalse((self.output/'__pycache__').exists())
        self.assertFalse((self.output/'value.pyc').exists())
        observed = subprocess.run([sys.executable, '-B', '-c',
            'import copied; print(copied.answer)'], cwd=self.root,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'), capture_output=True,
            text=True, timeout=10)
        self.assertEqual(observed.returncode, 0, observed.stderr)
        self.assertEqual(observed.stdout.strip(), '2')

    def test_existing_destination_is_not_merged_or_overwritten(self):
        self.output.mkdir()
        (self.output/'sentinel').write_bytes(b'keep')
        with self.assertRaises(ValueError): self.stage_package()
        self.assertEqual((self.output/'sentinel').read_bytes(), b'keep')

    def test_inside_source_destination_is_rejected(self):
        with self.assertRaises(ValueError):
            overlay.stage_package(self.package, self.package/'child', {'value.py': b'x'})
        self.assertFalse((self.package/'child').exists())

    def test_invalid_or_missing_overlays_fail_before_copy(self):
        for name in ('../escape.py', '/absolute.py', 'a/../value.py', 'C:/value.py',
                     'a\\value.py', 'native.so', '__pycache__/value.py', './value.py',
                     'absent.py', 'resource.py', 'a//b.py'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.stage_package({'value.py': b'valid', name: b'bad'})
            self.assertFalse(self.output.exists())
        for value in ({}, {'value.py': 'text'}, {'value.py': bytearray(b'x')},
                      {'value.py': b'x'*(8*1024**2+1)}):
            with self.assertRaises(ValueError): self.stage_package(value)
            self.assertFalse(self.output.exists())

    def test_observation_budget_is_checked_before_copy(self):
        with self.assertRaises(ValueError): self.stage_package(max_bytes=8)
        self.assertFalse(self.output.exists())
        with self.assertRaises(ValueError): self.stage_package(timeout=float('nan'))

    def test_source_mutation_stops_and_keeps_partial_fresh_copy(self):
        copy = overlay.shutil.copytree
        def changed(*args, **kwargs):
            result = copy(*args, **kwargs)
            (self.package/'value.py').write_bytes(b'changed concurrently')
            return result
        with patch.object(overlay.shutil, 'copytree', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'source package changed'):
                self.stage_package()
        self.assertTrue(self.output.exists())
        self.assertEqual((self.package/'value.py').read_bytes(), b'changed concurrently')
        with self.assertRaises(ValueError): self.stage_package()

    def test_caller_mapping_mutation_cannot_add_an_unvalidated_target(self):
        replacements = {'value.py': b'answer = 3\n'}
        copy = overlay.shutil.copytree
        def changed(*args, **kwargs):
            result = copy(*args, **kwargs)
            replacements.clear()
            replacements['../escape.py'] = b'not reviewed'
            return result
        with patch.object(overlay.shutil, 'copytree', side_effect=changed):
            result = self.stage_package(replacements)
        self.assertEqual(set(result['overlays']), {'value.py'})
        self.assertEqual((self.output/'value.py').read_bytes(), b'answer = 3\n')
        self.assertFalse((self.root/'escape.py').exists())

    def test_links_are_rejected_without_retargeting_or_flattening(self):
        link = self.package/'linked.py'
        try:
            link.symlink_to(self.package/'value.py')
        except (OSError, NotImplementedError):
            self.skipTest('native symlink permission unavailable')
        with self.assertRaisesRegex(ValueError, 'links'):
            self.stage_package()
        self.assertTrue(link.is_symlink())
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
