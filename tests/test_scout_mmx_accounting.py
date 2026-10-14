"""Accounting controls, not real provider quality/billing observations."""
import json
import os
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from scripts.scout_shadow_comparison import make_view, parse_mmx_message, parsed, run_arm


def message():
    # Matches the real mmx1.0.18 loopback control envelope. These are deliberately
    # injected counters, not measured model usage or dollar prices.
    return dict(id='msg_loopback_control', type='message', role='assistant', model='MiniMax-M3',
                content=[dict(type='text', text='{"route_ok":true}')], stop_reason='end_turn',
                usage=dict(input_tokens=12, cache_read_input_tokens=3,
                           cache_creation_input_tokens=0, output_tokens=5))


class MmxAccountingTests(unittest.TestCase):
    def parse(self, value=None, code=0):
        return parse_mmx_message(json.dumps(message() if value is None else value), exit_code=code)

    def test_complete_envelope_preserves_answer_usage_and_model(self):
        result = self.parse()
        self.assertTrue(result['response']['ok'])
        self.assertEqual(parsed(result), {'route_ok': True})
        self.assertEqual(result['normalized_total_tokens'], 20)
        self.assertEqual(result['model'], 'MiniMax-M3')
        self.assertNotIn('attempted', result)

    def test_quiet_answer_is_not_a_usage_envelope(self):
        result = self.parse({'route_ok': True})
        self.assertFalse(result['response']['ok'])
        self.assertIsNone(result['normalized_total_tokens'])
        self.assertIsNone(result['usage'])

    def test_missing_invalid_cache_counters_remain_unknown_not_zero(self):
        for key in message()['usage']:
            for value in (None, True, -1, 1.5, '2'):
                with self.subTest(key=key, value=value):
                    data = message()
                    if value is None:
                        del data['usage'][key]
                    else:
                        data['usage'][key] = value
                    result = self.parse(data)
                    self.assertIsNone(result['normalized_total_tokens'])
                    self.assertNotIn(key, result['usage'])
        data = message()
        del data['usage']
        self.assertTrue(self.parse(data)['response']['ok'])
        self.assertIsNone(self.parse(data)['normalized_total_tokens'])

    def test_truncated_or_failed_message_preserves_observed_usage_not_valid_answer(self):
        for stop in ('max_tokens', 'tool_use', 'stop_sequence', None):
            data = message()
            data['stop_reason'] = stop
            result = self.parse(data)
            self.assertFalse(result['response']['ok'])
            self.assertEqual(result['normalized_total_tokens'], 20)
        for code in (1, 127, -9):
            self.assertFalse(self.parse(code=code)['response']['ok'])

    def test_thinking_is_not_returned_as_answer_and_tool_content_is_unsupported(self):
        data = message()
        data['content'].insert(0, dict(type='thinking', thinking='not the answer'))
        self.assertEqual(self.parse(data)['response']['text'], '{"route_ok":true}')
        for content in (None, [], [dict(type='text')], [dict(type='tool_use', name='x')],
                        [dict(type='thinking', thinking='only reasoning')]):
            data['content'] = content
            self.assertFalse(self.parse(data)['response']['ok'])

    def test_identity_error_envelope_and_malformed_json_are_not_messages(self):
        for key in ('id', 'type', 'role', 'model'):
            data = message()
            del data[key]
            self.assertFalse(self.parse(data)['response']['ok'])
        for raw in ('', '{', '[]', '{"type":"message","type":"error"}', '{"usage":NaN}',
                    '{"error":{"message":"sensitive upstream diagnostic"}}'):
            result = parse_mmx_message(raw, exit_code=1)
            self.assertFalse(result['response']['ok'])
            self.assertNotIn('sensitive', json.dumps(result))

    def test_bounded_input_and_observed_exit_type(self):
        with self.assertRaises(ValueError):
            parse_mmx_message('x' * (2 * 1024 * 1024 + 1), exit_code=0)
        with self.assertRaises(ValueError):
            parse_mmx_message('{}', exit_code=False)

    def test_composed_arm_retains_all_call_usage(self):
        assets = {'a.py': dict(text='source', sha256='synthetic')}
        packet = dict(repo='o/r', sources=[dict(text='source', start_line=1, end_line=1,
            url='https://raw.githubusercontent.com/o/r/' + 'a' * 40 + '/a.py')])
        view = make_view(packet, repo='o/r', commit='a' * 40, assets=assets)
        for missing_usage in (False, True):
            def invoke(provider, prompt, cap):
                envelope = message()
                envelope['content'][0]['text'] = json.dumps(dict(verdict='INSUFFICIENT',
                    decisive_evidence=None, reason='Not an oracle', next_native_check=None))
                if missing_usage:
                    del envelope['usage']
                return parse_mmx_message(json.dumps(envelope), exit_code=0)
            result = run_arm(view, assets, ('control', 'm3', 'none', 'm3'), invoke)
            self.assertTrue(result['protocol_valid'])
            self.assertEqual(len(result['calls']), 2)
            self.assertEqual(result['normalized_total_tokens'], None if missing_usage else 40)


@unittest.skipUnless(os.environ.get('SCOUT_TEST_NODE') and os.environ.get('SCOUT_TEST_MMX_ENTRY'),
                     'optional installed Node/mmx loopback replay; no downloads')
class InstalledMmxTests(unittest.TestCase):
    def test_actual_cli_quiet_loses_usage_but_full_json_preserves_it(self):
        # Explicit dummy auth + empty config + explicit region: do not send real
        # credentials to the fixture or invoke region auto-detection/provider.
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers['Content-Length']))
                requests.append((self.path, self.headers.get('x-api-key'), json.loads(body)))
                data = json.dumps(message()).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as private:
                env = {k: v for k, v in os.environ.items() if k not in {
                    'MINIMAX_API_KEY', 'MINIMAX_BASE_URL', 'MINIMAX_REGION',
                    'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY'}}
                env.update(MMX_CONFIG_DIR=private, NO_PROXY='127.0.0.1,localhost')
                results = []
                for quiet in (True, False):
                    command = [str(Path(os.environ['SCOUT_TEST_NODE']).resolve(strict=True)),
                               str(Path(os.environ['SCOUT_TEST_MMX_ENTRY']).resolve(strict=True)),
                               'text', 'chat', '--message', 'user:Return only {"route_ok":true}.',
                               '--model', 'MiniMax-M3', '--max-tokens', '32', '--output', 'json',
                               '--non-interactive', '--no-color', '--timeout', '5',
                               '--api-key', 'loopback-fixture-not-a-secret', '--region', 'global',
                               '--base-url', 'http://127.0.0.1:' + str(server.server_port)]
                    if quiet:
                        command.append('--quiet')
                    child = subprocess.run(command, env=env, capture_output=True, timeout=10)
                    self.assertEqual(child.returncode, 0, 'loopback CLI failed; do not print auth diagnostics')
                    results.append(parse_mmx_message(child.stdout.decode(), exit_code=child.returncode))
                self.assertFalse(results[0]['response']['ok'])
                self.assertIsNone(results[0]['normalized_total_tokens'])
                self.assertTrue(results[1]['response']['ok'])
                self.assertEqual(results[1]['normalized_total_tokens'], 20)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(requests), 2)
        for path, key, body in requests:
            self.assertEqual(path, '/anthropic/v1/messages')
            self.assertEqual(key, 'loopback-fixture-not-a-secret')
            self.assertFalse(body['stream'])
            self.assertEqual(body['max_tokens'], 32)


if __name__ == '__main__':
    unittest.main()
