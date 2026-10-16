import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import scout_openai_backend as backend


def answer(**kwargs):
    return json.dumps(dict(choices=[dict(message=dict(content='{"decision":"no_lead"}',
        reasoning_content="private reasoning not returned"), finish_reason="stop")], **kwargs)).encode()


class BackendTests(unittest.TestCase):
    def test_existing_queue_validator_and_accounting_still_apply(self):
        from tests.test_kimi_scout import scout, packet, result
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scout.initialize(root)
            config = root / "provider.json"
            config.write_text(json.dumps(dict(endpoint="https://test.invalid/v1", model="m", alias="glm")))
            pool = backend.BackendPool(config)
            for valid in (True, False):
                scout.enqueue(root, packet(str(valid)))
                job = scout.claim(root, 0, 0, 16384)
                analysis = result()
                if not valid:
                    analysis["evidence"][0]["quote"] = "not in supplied source"
                async def completion(request, *args):
                    self.assertEqual(request["max_output_tokens"], 16384)
                    return dict(ok=True, text=json.dumps(analysis), finish_reason="stop",
                        usage=dict(input_tokens=100, output_tokens=700, total_tokens=800),
                        tools_advertised=0, tool_calls_executed=0)
                with patch.object(backend, "complete", completion):
                    receipt = scout.execute(root, job, sys.executable, 30, 16384, pool)
                self.assertEqual(receipt["state"], "REVIEW" if valid else "FAILED")
                self.assertEqual(receipt["charged_tokens_or_reservation"], 800)
                self.assertEqual(receipt["charge_basis"], "provider_report")
                if valid:
                    self.assertEqual(receipt["result"]["model"], "glm")
                    self.assertFalse(receipt["result"]["qualified"])
                else:
                    self.assertEqual(receipt["failure_scope"], "answer")

    def test_reasoning_budget_does_not_expand_default_kimi_contract(self):
        raw = json.dumps(dict(prompt="public", max_output_tokens=16384)).encode()
        with self.assertRaises(backend.contract.BackendError):
            backend.contract.read_request(raw)
        self.assertEqual(backend.read_request(json.loads(raw))["max_output_tokens"], 16384)
        raw = json.dumps(dict(prompt="public", max_output_tokens=32769)).encode()
        with self.assertRaises(backend.contract.BackendError):
            backend.read_request(json.loads(raw))

    def test_visible_answer_and_inclusive_usage_only(self):
        result = backend.decode_answer(answer(usage=dict(prompt_tokens=23, completion_tokens=41,
            total_tokens=64, reasoning_tokens=30)))
        self.assertTrue(result["ok"])
        self.assertNotIn("reasoning", json.dumps(result))
        self.assertEqual(result["usage"]["total_tokens"], 64)
        self.assertIsNone(result["usage"]["cached_input_tokens"])

    def test_truncation_not_success_and_usage_preserved(self):
        data = json.loads(answer(usage=dict(prompt_tokens=2, completion_tokens=256)))
        data["choices"][0]["finish_reason"] = "length"
        result = backend.decode_answer(json.dumps(data).encode())
        self.assertFalse(result["ok"])
        self.assertFalse(result["retryable"])
        self.assertEqual(result["usage"]["total_tokens"], 258)

    def test_tool_response_rejected(self):
        data = json.loads(answer())
        data["choices"][0]["message"]["tool_calls"] = [{"name": "run_shell"}]
        with self.assertRaisesRegex(backend.contract.BackendError, "unexpected_tool_call"):
            backend.decode_answer(json.dumps(data).encode())

    def test_invalid_responses_and_output_bound(self):
        for raw in (b"null", b"{}", b"not JSON", b'{"choices":[]}',
                    b'{"choices":[{},{}]}', b"x" * (backend.MAX_RESPONSE_BYTES + 1)):
            with self.subTest(raw_length=len(raw)), self.assertRaises(backend.contract.BackendError):
                backend.decode_answer(raw)

    def test_config_requires_explicit_http_and_no_foreign_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "provider.json"
            valid = dict(endpoint="http://test.invalid/v1/chat/completions", model="example", alias="example")
            path.write_text(json.dumps(valid))
            with self.assertRaises(backend.contract.BackendError):
                backend.load_config(path)
            valid["allow_http"] = True
            path.write_text(json.dumps(valid))
            self.assertEqual(backend.load_config(path), valid)
            for field, value in (("endpoint", "https://user:secret@test.invalid/v1"),
                                 ("endpoint", "https://test.invalid/v1?key=secret"),
                                 ("api_key", "secret\nheader"), ("allow_http", 1),
                                 ("kimi_config", "secret.toml")):
                invalid = {**valid, field: value}
                path.write_text(json.dumps(invalid))
                with self.subTest(field=field), self.assertRaises(backend.contract.BackendError):
                    backend.load_config(path)

    def test_no_kimi_credentials_or_reasoning_in_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "provider.json"
            path.write_text(json.dumps(dict(endpoint="https://test.invalid/v1/chat/completions", model="m", alias="glm")))
            pool = backend.BackendPool(path)
            async def denied(*args):
                raise backend.ProviderHTTPError(403)
            with patch.object(backend, "complete", denied):
                result = json.loads(pool.run(dict(prompt="public source", max_output_tokens=256),
                    Path(directory)/"live.json", 30).stdout)
            self.assertFalse(result["ok"])
            self.assertEqual(result["http_status"], 403)
            self.assertEqual(result["error_type"], "PermissionDeniedError")
            self.assertFalse(result["retryable"])
            self.assertEqual(result["model_alias"], "glm")
            self.assertEqual(result["provider_type"], "openai_http")
            self.assertNotIn("kimi_version", result)
            self.assertEqual(pool.process_starts, 0)

    def test_http_protocol_is_bounded_closed_and_never_retried(self):
        seen = {}
        class Context:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                seen["closed"] = seen.get("closed", 0) + 1
        class Response(Context):
            status_code = 200
            async def aiter_bytes(self):
                yield answer()
        class Client(Context):
            def __init__(self, **kwargs):
                seen["client"] = kwargs
            def stream(self, method, endpoint, **kwargs):
                seen.update(method=method, request=kwargs)
                seen["calls"] = seen.get("calls", 0) + 1
                return Response()
        fake = SimpleNamespace(AsyncClient=Client, Timeout=lambda *a, **k: (a, k))
        with patch.dict(sys.modules, {"httpx": fake}):
            result = asyncio.run(backend.complete(dict(prompt="public", max_output_tokens=256,
                timeout_seconds=2), dict(endpoint="https://test.invalid/v1", model="m", alias="m")))
        self.assertTrue(result["ok"])
        self.assertFalse(seen["client"]["trust_env"])
        self.assertFalse(seen["client"]["follow_redirects"])
        self.assertEqual(seen["calls"], 1)
        self.assertEqual(seen["closed"], 2)
        self.assertNotIn("Authorization", seen["request"]["headers"])
        self.assertNotIn("tools", seen["request"]["json"])
        self.assertFalse(seen["request"]["json"]["stream"])

    def test_deadline_cancels_and_closes(self):
        closed = []
        class Client:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                closed.append(True)
            def stream(self, *args, **kwargs):
                return self
            status_code = 200
            async def aiter_bytes(self):
                await asyncio.sleep(10)
                yield b""
        fake = SimpleNamespace(AsyncClient=lambda **k: Client(), Timeout=lambda *a, **k: None)
        with patch.dict(sys.modules, {"httpx": fake}), self.assertRaises(TimeoutError):
            asyncio.run(backend.complete(dict(prompt="public", max_output_tokens=256,
                timeout_seconds=0.01), dict(endpoint="https://test.invalid", model="m", alias="m")))
        self.assertEqual(len(closed), 2)


if __name__ == "__main__":
    unittest.main()
