"""Filesystem controls, not claims of dependency isolation or Scout benefit."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.scout_dependency_tree import inspect_tree


class DependencyTreeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.cache = self.root/'cache'; self.cache.mkdir()
        (self.cache/'module.js').write_bytes(b'export const x = 1;\n')

    def test_same_contents_ignore_root_and_creation_order(self):
        (self.cache/'empty').mkdir()
        other = self.root/'other';other.mkdir();(other/'empty').mkdir()
        (other/'module.js').write_bytes((self.cache/'module.js').read_bytes())
        before, after = inspect_tree(self.cache), inspect_tree(other)
        self.assertEqual(before['content_sha256'], after['content_sha256'])
        self.assertEqual(before['entries'], 2)
        self.assertEqual(before['regular_files'], 1)
        self.assertEqual(before['regular_file_bytes'], len(b'export const x = 1;\n'))

    def test_content_name_and_empty_directory_drift_are_observable(self):
        before = inspect_tree(self.cache)['content_sha256']
        (self.cache/'module.js').write_bytes(b'export const x = 2;\n')
        content = inspect_tree(self.cache)['content_sha256']
        self.assertNotEqual(before, content)
        (self.cache/'module.js').rename(self.cache/'renamed.js')
        renamed = inspect_tree(self.cache)['content_sha256']
        self.assertNotEqual(content, renamed)
        (self.cache/'empty').mkdir()
        self.assertNotEqual(renamed, inspect_tree(self.cache)['content_sha256'])

    def test_entry_and_byte_budgets_never_return_partial_digest(self):
        (self.cache/'second').write_bytes(b'x')
        for budget in (dict(max_entries=1), dict(max_bytes=2)):
            with self.assertRaisesRegex(ValueError, 'budget exceeded'):
                inspect_tree(self.cache, **budget)
        with patch('scripts.scout_dependency_tree.MAX_METADATA_BYTES', 1):
            with self.assertRaisesRegex(ValueError, 'metadata budget exceeded'):
                inspect_tree(self.cache)

    def test_invalid_budgets_and_roots(self):
        for kwargs in (dict(max_entries=True), dict(max_entries=0), dict(max_entries=50001),
                       dict(max_bytes=-1), dict(timeout=True), dict(timeout=float('nan')),
                       dict(timeout=121)):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                inspect_tree(self.cache, **kwargs)
        with self.assertRaises(ValueError): inspect_tree(self.cache/'module.js')
        with self.assertRaises(FileNotFoundError): inspect_tree(self.root/'missing')

    def test_deadline_and_unreadable_walk_do_not_become_empty_success(self):
        with patch('scripts.scout_dependency_tree.time.monotonic', side_effect=[0, 2]):
            with self.assertRaises(TimeoutError): inspect_tree(self.cache, timeout=1)
        with patch('scripts.scout_dependency_tree.os.scandir',
                   side_effect=PermissionError('fixture unreadable directory')):
            with self.assertRaises(PermissionError): inspect_tree(self.cache)

    @unittest.skipUnless(os.name == 'posix', 'POSIX symlink controls')
    def test_internal_link_is_recorded_without_double_reading_target(self):
        (self.cache/'alias.js').symlink_to('module.js')
        value=inspect_tree(self.cache)
        self.assertEqual((value['entries'],value['regular_files'],value['symlinks']), (2,1,1))
        self.assertEqual(value['regular_file_bytes'], (self.cache/'module.js').stat().st_size)
        (self.cache/'alias.js').unlink();(self.cache/'other.js').write_bytes(b'x')
        (self.cache/'alias.js').symlink_to('other.js')
        self.assertNotEqual(value['content_sha256'],inspect_tree(self.cache)['content_sha256'])

    @unittest.skipUnless(os.name == 'posix', 'POSIX external/dangling links')
    def test_external_dangling_and_root_links_are_rejected(self):
        outside=self.root/'outside.js';outside.write_bytes(b'not part of tree')
        link=self.cache/'alias';link.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'escapes'): inspect_tree(self.cache)
        link.unlink();link.symlink_to('missing')
        with self.assertRaises(FileNotFoundError): inspect_tree(self.cache)
        link.unlink();link=self.root/'linked-root';link.symlink_to(self.cache,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'root must not'): inspect_tree(link)

    @unittest.skipUnless(os.name == 'posix', 'POSIX FIFO')
    def test_fifo_rejected_without_opening_or_hanging(self):
        os.mkfifo(self.cache/'fifo')
        with self.assertRaisesRegex(ValueError, 'special files'): inspect_tree(self.cache)

    def test_cli_expectation_and_exported_standalone_help(self):
        script=Path(__file__).resolve().parents[1]/'scripts/scout_dependency_tree.py'
        command=[sys.executable,'-B',str(script),str(self.cache)]
        before=subprocess.run(command,capture_output=True,text=True,timeout=10)
        self.assertEqual(before.returncode,0,before.stderr)
        digest=json.loads(before.stdout)['content_sha256']
        for expected,code in ((digest,0),('0'*64,2)):
            result=subprocess.run([*command,'--expect-sha256',expected],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,code,result.stderr)
            if code: self.assertEqual(result.stdout,'')


if __name__=='__main__':unittest.main()
