"""Library identity is observable without publishing advice or synchronizing it."""
import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import knowledge_notes as notes


class KnowledgeInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.card = dict(id='example-rule', title='Example rule', applies_when='Example inputs.',
                         lesson='Observe the actual boundary.', avoid_when='Other protocols differ.',
                         status='hypothesis', evidence=[dict(url='https://example.com/evidence', note='Public example.')])
        self.path = self.directory/'example-rule.json'
        self.path.write_text(json.dumps(self.card), encoding='utf-8')

    def test_readonly_identities_do_not_export_card_bodies_or_local_paths(self):
        before = self.path.read_bytes()
        value = notes.inventory(self.directory)
        self.assertEqual(value['count'], 1)
        self.assertEqual(value['entries'][self.path.name]['raw_sha256'], hashlib.sha256(before).hexdigest())
        serialized = json.dumps(value)
        self.assertNotIn(str(self.directory), serialized)
        self.assertNotIn(self.card['lesson'], serialized)
        self.assertNotIn('example.com', serialized)
        self.assertEqual(self.path.read_bytes(), before)

    def test_formatting_and_utf8_bom_only_change_raw_hash(self):
        original = notes.inventory(self.directory)['entries'][self.path.name]
        self.path.write_bytes(('\ufeff'+json.dumps(self.card, indent=2, sort_keys=True)+'\r\n').encode())
        reformatted = notes.inventory(self.directory)['entries'][self.path.name]
        self.assertNotEqual(original['raw_sha256'], reformatted['raw_sha256'])
        self.assertEqual(original['content_sha256'], reformatted['content_sha256'])

    def test_a_semantic_edit_changes_content_hash(self):
        original = notes.inventory(self.directory)['entries'][self.path.name]
        self.card['avoid_when'] = 'Do not transfer this to a different runtime.'
        self.path.write_text(json.dumps(self.card), encoding='utf-8')
        changed = notes.inventory(self.directory)['entries'][self.path.name]
        self.assertNotEqual(original['content_sha256'], changed['content_sha256'])

    def test_invalid_library_and_duplicates_do_not_look_successfully_empty(self):
        self.path.write_text('{}', encoding='utf-8')
        with self.assertRaises(ValueError):
            notes.inventory(self.directory)
        self.path.write_text(json.dumps(self.card), encoding='utf-8')
        second = dict(self.card, id='another-rule')
        (self.directory/'another-rule.json').write_text(json.dumps(second), encoding='utf-8')
        with self.assertRaises(ValueError):
            notes.inventory(self.directory)

    def test_content_change_between_validation_and_byte_read_is_rejected(self):
        old = dict(self.card)
        self.card['lesson'] = 'A concurrent writer changed the actual card.'
        self.path.write_text(json.dumps(self.card), encoding='utf-8')
        with patch.object(notes, 'read_cards', return_value=[(self.path, old)]):
            with self.assertRaisesRegex(ValueError, 'changed while reading'):
                notes.inventory(self.directory)

    def test_cli_inventory_is_readonly_and_empty_library_is_explicit(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = notes.main(['--directory', str(self.directory), 'inventory'])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())['count'], 1)
        self.path.unlink()
        self.assertEqual(notes.inventory(self.directory)['entries'], {})
        with self.assertRaises(ValueError):
            notes.inventory(self.directory/'absent')


if __name__ == '__main__':
    unittest.main()
