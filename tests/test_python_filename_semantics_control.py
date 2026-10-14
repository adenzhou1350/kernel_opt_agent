"""Verify the exposed control's observed fields, not a prospective method win."""
import json
import unittest

from examples.python_filename_semantics import observe


class FilenameSemanticsControlTests(unittest.TestCase):
    def test_final_newline_is_preserved_but_match_and_fullmatch_disagree(self):
        row = observe()['observations'][-1]
        self.assertEqual(row['input'], 'pylock.spam.toml\n')
        self.assertEqual(row['path_name'], row['input'])
        self.assertTrue(row['path_name_preserves_input'])
        self.assertTrue(row['regex_match'])
        self.assertFalse(row['regex_fullmatch'])

    def test_retains_positive_and_negative_controls_without_conflating_wrapper(self):
        result = observe()
        self.assertEqual(len(result['observations']), 4)
        rows = {row['input']: row for row in result['observations']}
        self.assertTrue(rows['pylock.spam.toml']['regex_match'])
        self.assertTrue(rows['pylock.spam.toml']['regex_fullmatch'])
        self.assertFalse(rows['pylock.json']['regex_match'])
        self.assertFalse(rows['pylock.json']['regex_fullmatch'])
        # The real wrapper also accepts bare pylock.toml through a separate branch.
        self.assertFalse(rows['pylock.toml']['regex_match'])
        self.assertFalse(rows['pylock.toml']['regex_fullmatch'])
        self.assertIn('not package correctness', result['scope'])
        self.assertEqual(json.loads(json.dumps(result)), result)


if __name__ == '__main__':
    unittest.main()
