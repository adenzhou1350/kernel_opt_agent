"""A native-testable discovery scope is not a new finding or whole-repo CI."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from kimi_scout_research import configuration, source_paths


class ChiSourceActivationTests(unittest.TestCase):
    def test_root_router_scope_keeps_baseline_and_historical_repair_boundaries(self):
        config = configuration(Path(__file__).resolve().parents[1] / 'templates/kimi-scout-research-wide.json')
        spec = next(row for row in config['repos'] if row['repo'] == 'go-chi/chi')
        self.assertEqual('master', spec['ref'])
        for text in ('baseline testability only', 'middleware, examples',
                     'self-mount repair aba86186 is already included',
                     'separate exact-source native reproduction'):
            self.assertIn(text, spec['question'])
        self.assertEqual(len(config['repos']), len({row['repo'] for row in config['repos']}))
        selected = source_paths(dict(files=[*spec['source_prefixes'], 'mux_test.go',
            'tree_test.go', 'middleware/client_ip.go', 'README.md', '_examples/hello-world/main.go']), spec)
        self.assertEqual(sorted(spec['source_prefixes']), selected)
        self.assertLess(len(json.dumps(spec)), 2500)


if __name__ == '__main__':
    unittest.main()
