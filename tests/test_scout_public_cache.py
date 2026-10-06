import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_public_cache import compress_entry, read_cache
from kimi_scout_context import PublicContext


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.context = PublicContext(self.temp.name)
        self.path = self.context.cache / ("snapshot-" + "a" * 64 + ".json")
        self.raw = json.dumps({"source": "line\n" * 1000}, indent=2).encode()
        self.path.write_bytes(self.raw)

    def test_exact_bytes_and_public_reader(self):
        self.assertGreater(compress_entry(self.path), 0)
        self.assertFalse(self.path.exists())
        self.assertEqual(read_cache(self.path), self.raw)
        self.assertEqual(self.context._load(self.path), json.loads(self.raw))

    def test_new_plain_entry_overrides_old_compressed_alias(self):
        compress_entry(self.path)
        self.path.write_text('{"new": true}', encoding="utf-8")
        self.assertEqual(self.context._load(self.path), {"new": True})
        self.path.write_text("invalid", encoding="utf-8")
        self.assertIsNone(self.context._load(self.path))

    def test_conflict_preserves_original(self):
        self.path.with_suffix(".json.gz").write_bytes(gzip.compress(b'{}'))
        with self.assertRaisesRegex(ValueError, "conflicting"):
            compress_entry(self.path)
        self.assertEqual(self.path.read_bytes(), self.raw)

    def test_corruption_and_decompression_limit(self):
        compress_entry(self.path)
        with self.assertRaises(ValueError):
            read_cache(self.path, 100)
        self.path.with_suffix(".json.gz").write_bytes(b"not gzip")
        self.assertIsNone(self.context._load(self.path))

    def test_existing_equal_archive_is_reusable(self):
        self.path.with_suffix(".json.gz").write_bytes(gzip.compress(self.raw))
        self.assertGreater(compress_entry(self.path), 0)
        self.assertEqual(read_cache(self.path), self.raw)

    def test_invalid_json_and_filename_untouched(self):
        self.path.write_bytes(b"invalid")
        with self.assertRaises(ValueError):
            compress_entry(self.path)
        wrong = self.path.parent / "private.json"
        wrong.write_bytes(self.raw)
        with self.assertRaises(ValueError):
            compress_entry(wrong)
        self.assertTrue(wrong.exists())

    def test_disk_failure_preserves_original_and_cleans_temporary(self):
        with patch('scout_public_cache.os.replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                compress_entry(self.path)
        self.assertEqual(self.path.read_bytes(), self.raw)
        self.assertEqual(list(self.path.parent.glob('*.cache-tmp')), [])

    def test_changed_source_is_not_removed_or_hidden_by_old_archive(self):
        pack = gzip.compress

        def change_source(data, **kwargs):
            self.path.write_bytes(b'{"new": true}')
            return pack(data, **kwargs)

        with patch('scout_public_cache.gzip.compress', side_effect=change_source):
            with self.assertRaisesRegex(ValueError, 'changed'):
                compress_entry(self.path)
        self.assertEqual(self.context._load(self.path), {'new': True})

    def test_existing_filesystem_compression_does_not_grow_allocation(self):
        with patch('scout_public_cache.allocated_bytes', return_value=1):
            self.assertEqual(compress_entry(self.path), 0)
        self.assertEqual(self.path.read_bytes(), self.raw)
        self.assertFalse(self.path.with_suffix('.json.gz').exists())


if __name__ == "__main__":
    unittest.main()
