"""Source activation is admission guidance, not native reproduction."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from kimi_scout_research import configuration, source_paths


class BackoffSourceActivationTests(unittest.TestCase):
    def test_wide_template_keeps_version_and_contribution_boundary(self):
        path = Path(__file__).resolve().parents[1] / 'templates/kimi-scout-research-wide.json'
        config = configuration(path)
        spec = next(row for row in config['repos'] if row['repo'] == 'cenkalti/backoff')
        self.assertEqual('v7', spec['ref'])
        self.assertIn('issue discussion before a PR', spec['question'])
        self.assertIn('baseline testability only', spec['question'])
        self.assertIn('Issue194 already reports', spec['question'])
        self.assertEqual(len(config['repos']), len({row['repo'] for row in config['repos']}))
        paths = source_paths(dict(files=[*spec['source_prefixes'], 'retry_test.go',
                                        'README.md', 'vendor/retry.go']), spec)
        self.assertEqual(sorted(spec['source_prefixes']), paths)
        self.assertLess(len(json.dumps(spec)), 2500)


if __name__ == '__main__':
    unittest.main()
