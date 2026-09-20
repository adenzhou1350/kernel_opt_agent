"""Offline backend safety tests; fake provider modules never contact a service."""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "kimi_scout_backend.py"
SPEC = importlib.util.spec_from_file_location("kimi_scout_backend", SCRIPT)
backend = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backend)


class FakeStream:
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk

    async def close(self):
        self.closed = True


def chunk(text="review", finish="stop", tool_calls=None, usage=True, reasoning=""):
    return SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=100,
            completion_tokens=10,
            prompt_tokens_details=SimpleNamespace(cached_tokens=30),
        )
        if usage
        else None,
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(
                    content=text, tool_calls=tool_calls, reasoning_content=reasoning
                ),
                finish_reason=finish,
            )
        ],
    )


class BackendTests(unittest.TestCase):
    def test_request_limits_and_unknown_fields(self):
        self.assertEqual(
            backend.read_request(b'{"prompt":"source"}')["max_output_tokens"], 2048
        )
        bad = [
            b"[]",
            b"not json",
            b'{"prompt":""}',
            b'{"prompt":"x","max_output_tokens":true}',
            b'{"prompt":"x","max_output_tokens":255}',
            b'{"prompt":"x","max_output_tokens":4097}',
            b'{"prompt":"x","timeout_seconds":NaN}',
            b'{"prompt":"x","timeout_seconds":601}',
            b'{"prompt":"x","system":"override"}',
            b"x" * (backend.MAX_INPUT_BYTES + 1),
        ]
        for raw in bad:
            with self.subTest(raw=raw[:80]), self.assertRaises(backend.BackendError):
                backend.read_request(raw)

    def config_file(self, root, **overrides):
        config = {
            "type": "kimi",
            "base_url": "https://model.invalid/v1",
            "api_key": "TEST_ONLY_NOT_A_CREDENTIAL",
        }
        config.update(overrides)
        lines = [
            'default_model = "model"',
            "[models.model]",
            'provider = "configured"',
            'model = "test-kimi"',
            "[providers.configured]",
        ]
        for key, value in config.items():
            if isinstance(value, dict):
                lines.append(
                    f"{key} = {{"
                    + ", ".join(f"{k} = {json.dumps(v)}" for k, v in value.items())
                    + "}"
                )
            else:
                lines.append(f"{key} = {json.dumps(value)}")
        path = Path(root) / "config.toml"
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def test_only_pinned_kimi_api_key_config_is_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.config_file(directory)
            with patch.object(
                backend.importlib.metadata, "version", return_value="1.30.0"
            ):
                loaded = backend.load_provider(path)
                self.assertEqual(loaded["model"], "test-kimi")
                for changes in (
                    {"type": "_scripted_echo"},
                    {"type": "openai_legacy"},
                    {"oauth": {"storage": "file", "key": "oauth/test"}},
                    {"env": {"CUSTOM_MODULE": "untrusted"}},
                    {"base_url": "https://user:password@model.invalid/v1"},
                    {"base_url": "file:///secret"},
                    {"api_key": ""},
                ):
                    with (
                        self.subTest(changes=changes),
                        self.assertRaises(backend.BackendError),
                    ):
                        backend.load_provider(self.config_file(directory, **changes))
            with patch.object(
                backend.importlib.metadata, "version", return_value="1.31.0"
            ):
                with self.assertRaisesRegex(
                    backend.BackendError, "unsupported_kimi_version"
                ):
                    backend.load_provider(path)

    def test_check_does_not_call_backend_or_print_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.config_file(directory)
            output = io.StringIO()
            with (
                patch.object(
                    backend.importlib.metadata, "version", return_value="1.30.0"
                ),
                patch.object(
                    backend.sys,
                    "flags",
                    SimpleNamespace(isolated=True, ignore_environment=True),
                ),
                patch.object(
                    backend, "complete", side_effect=AssertionError("must not call")
                ),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(
                    backend.main(["--check", "--config-file", str(path)]), 0
                )
            payload = json.loads(output.getvalue())
            self.assertTrue(payload["check_only"])
            self.assertNotIn("TEST_ONLY", output.getvalue())
            self.assertNotIn("model.invalid", output.getvalue())

    def fake_completion(self, chunks, progress=None):
        calls = {}
        stream = FakeStream(chunks)

        class FakeHTTPClient:
            def __init__(self, **kwargs):
                calls["http"] = kwargs

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                calls["http_closed"] = True

        class FakeKimi:
            def __init__(self, **kwargs):
                calls["provider"] = kwargs
                self.client = SimpleNamespace(
                    chat=SimpleNamespace(
                        completions=SimpleNamespace(create=self.create)
                    )
                )

            async def create(self, **kwargs):
                calls["request"] = kwargs
                return stream

        fake_httpx = ModuleType("httpx")
        fake_httpx.AsyncClient = FakeHTTPClient
        fake_httpx.Timeout = lambda *args, **kwargs: (args, kwargs)
        fake_kimi = ModuleType("kosong.chat_provider.kimi")
        fake_kimi.Kimi = FakeKimi
        fake_kimi.extract_usage_from_chunk = lambda item: item.usage
        fake_loguru = ModuleType("loguru")
        fake_loguru.logger = SimpleNamespace(remove=lambda: None)
        modules = {
            "httpx": fake_httpx,
            "kosong": ModuleType("kosong"),
            "kosong.chat_provider": ModuleType("kosong.chat_provider"),
            "kosong.chat_provider.kimi": fake_kimi,
            "loguru": fake_loguru,
        }
        provider = {
            "model": "fake-kimi",
            "base_url": "https://model.invalid/v1",
            "api_key": "TEST_ONLY",
            "headers": {},
        }
        request = backend.read_request(b'{"prompt":"explicit public source"}')
        with patch.dict(sys.modules, modules), patch.object(backend.logging, "disable"):
            result = asyncio.run(backend.complete(request, provider, progress))
        return result, calls, stream

    def test_progress_contains_only_visible_content_and_finishes(self):
        updates = []
        result, _, _ = self.fake_completion(
            [
                chunk(text="", finish=None, reasoning="PRIVATE_REASONING"),
                chunk(text="visible ", finish=None),
                chunk(text="answer"),
            ],
            lambda text, phase: updates.append({"text": text, "phase": phase}),
        )
        self.assertEqual(updates[0], {"text": "", "phase": "requesting"})
        self.assertIn({"text": "visible ", "phase": "streaming"}, updates)
        self.assertEqual(updates[-1], {"text": "visible answer", "phase": "completed"})
        self.assertEqual(result["text"], "visible answer")
        serialized = json.dumps(updates)
        for forbidden in ("PRIVATE_REASONING", "TEST_ONLY", "model.invalid", "api_key"):
            self.assertNotIn(forbidden, serialized)

    def test_progress_failure_keeps_partial_text_without_exception_details(self):
        updates = []
        with self.assertRaises(RuntimeError):
            self.fake_completion(
                [chunk(text="partial", finish=None), RuntimeError("SECRET_HEADERS")],
                lambda text, phase: updates.append({"text": text, "phase": phase}),
            )
        self.assertEqual(updates[-1], {"text": "partial", "phase": "failed"})
        self.assertNotIn("SECRET_HEADERS", json.dumps(updates))
        updates.clear()
        result, _, _ = self.fake_completion(
            [chunk(finish="length")],
            lambda text, phase: updates.append({"text": text, "phase": phase}),
        )
        self.assertFalse(result["ok"])
        self.assertEqual(updates[-1], {"text": "review", "phase": "failed"})

    def test_progress_callback_failure_does_not_change_model_call(self):
        def fail(*unused):
            raise OSError("private location")

        result, calls, stream = self.fake_completion([chunk()], fail)
        self.assertTrue(result["ok"])
        self.assertEqual(calls["request"]["tools"], [])
        self.assertEqual(calls["provider"]["max_retries"], 0)
        self.assertTrue(stream.closed)

    def test_atomic_progress_is_throttled_and_forces_terminal_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "visible.live.json"
            progress = backend.ProgressFile(path)
            with patch.object(
                backend.time, "monotonic", side_effect=[0, 0.1, 0.26, 0.27]
            ):
                progress("first", "streaming")
                progress("second", "streaming")
                self.assertEqual(json.loads(path.read_text())["text"], "first")
                progress("third", "streaming")
                self.assertEqual(json.loads(path.read_text())["text"], "third")
                progress("final", "failed")
            snapshot = json.loads(path.read_text())
            self.assertEqual(set(snapshot), {"text", "updated_at", "phase"})
            self.assertEqual(snapshot["text"], "final")
            self.assertEqual(snapshot["phase"], "failed")
            self.assertIsInstance(snapshot["updated_at"], float)
            self.assertEqual(list(Path(directory).iterdir()), [path])
            # An inaccessible progress destination is explicitly non-fatal.
            result, _, _ = self.fake_completion(
                [chunk()],
                backend.ProgressFile(Path(directory) / "missing" / "live.json"),
            )
            self.assertTrue(result["ok"])

    def test_pre_request_failure_gets_safe_terminal_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "visible.live.json"
            output = io.StringIO()
            with (
                patch.object(
                    backend.sys,
                    "flags",
                    SimpleNamespace(isolated=True, ignore_environment=True),
                ),
                patch.object(
                    backend.sys,
                    "stdin",
                    SimpleNamespace(buffer=io.BytesIO(b'{"prompt":"public"}')),
                ),
                patch.object(
                    backend, "load_provider", side_effect=RuntimeError("SECRET_KEY")
                ),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(backend.main(["--progress-file", str(path)]), 1)
            snapshot = json.loads(path.read_text())
            self.assertEqual(snapshot["phase"], "failed")
            self.assertEqual(snapshot["text"], "")
            self.assertNotIn("SECRET_KEY", path.read_text() + output.getvalue())
            self.assertEqual(json.loads(output.getvalue())["error"], "backend_failure")

    def test_relative_progress_path_cannot_follow_backend_working_directory(self):
        output = io.StringIO()
        with (
            patch.object(backend, "load_provider") as load,
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(backend.main(["--progress-file", "relative.json"]), 1)
        load.assert_not_called()
        self.assertEqual(
            json.loads(output.getvalue())["error"], "absolute_progress_file_required"
        )

    def test_no_tools_retries_proxy_environment_or_redirects(self):
        result, calls, stream = self.fake_completion([chunk()])
        self.assertTrue(result["ok"])
        self.assertEqual(calls["request"]["tools"], [])
        self.assertEqual(calls["request"]["tool_choice"], "none")
        self.assertEqual(calls["request"]["max_tokens"], 2048)
        self.assertEqual(calls["provider"]["max_retries"], 0)
        self.assertEqual(calls["provider"]["organization"], "")
        self.assertFalse(calls["http"]["trust_env"])
        self.assertFalse(calls["http"]["follow_redirects"])
        self.assertTrue(stream.closed)
        self.assertTrue(calls["http_closed"])

    def test_cache_tokens_are_already_in_input_and_total(self):
        result, _, _ = self.fake_completion([chunk()])
        self.assertEqual(result["usage"]["input_tokens"], 100)
        self.assertEqual(result["usage"]["cached_input_tokens"], 30)
        self.assertEqual(result["usage"]["total_tokens"], 110)
        result, _, _ = self.fake_completion([chunk(usage=False)])
        self.assertIsNone(result["usage"])

    def test_truncated_filtered_missing_finish_and_empty_answers_fail(self):
        for finish in ("length", "content_filter", None, "tool_calls"):
            with self.subTest(finish=finish):
                result, _, stream = self.fake_completion([chunk(finish=finish)])
                self.assertFalse(result["ok"])
                self.assertEqual(result["error"], "incomplete_response")
                self.assertEqual(result["usage"]["total_tokens"], 110)
                self.assertTrue(stream.closed)
        result, _, _ = self.fake_completion([chunk(text="")])
        self.assertFalse(result["ok"])

    def test_unsolicited_tools_and_oversized_output_never_execute(self):
        with self.assertRaisesRegex(backend.BackendError, "unexpected_tool_call"):
            self.fake_completion([chunk(tool_calls=[{"name": "Shell"}])])
        with self.assertRaisesRegex(backend.BackendError, "output_too_large"):
            self.fake_completion([chunk(text="x" * (backend.MAX_OUTPUT_CHARS + 1))])

    def test_errors_hide_exception_message_and_headers(self):
        exception = RuntimeError("Authorization: secret request body")
        payload = backend.safe_error(exception)
        self.assertNotIn("secret", json.dumps(payload))
        exception.status_code = 429
        self.assertTrue(backend.safe_error(exception)["retryable"])
        self.assertTrue(backend.safe_error(TimeoutError("secret"))["retryable"])
        self.assertFalse(
            backend.safe_error(backend.BackendError("invalid_input"))["retryable"]
        )


if __name__ == "__main__":
    unittest.main()
