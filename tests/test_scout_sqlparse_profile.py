"""Offline configuration boundary for the native CPU discovery profile."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from kimi_scout_research import configuration  # noqa: E402


class SQLParseProfileTest(unittest.TestCase):
    def test_profile_is_valid_and_limits_claims_to_public_native_behavior(self):
        config = configuration(ROOT / 'templates/kimi-scout-research-wide.json')
        rows = [row for row in config['repos'] if row['repo'] == 'andialbrecht/sqlparse']
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['ref'], 'master')
        self.assertEqual(row['tree_roots'], ['sqlparse', 'tests'])
        self.assertTrue(all(path.startswith('sqlparse/') for path in row['source_prefixes']))
        self.assertIn('non-validating', row['question'])
        self.assertIn('unverified hypothesis', row['question'])
        self.assertNotIn('execution', row)
        self.assertNotIn('worker', json.dumps(row))


if __name__ == '__main__':
    unittest.main()
