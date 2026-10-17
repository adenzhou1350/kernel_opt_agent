"""Opt-in tool-free HTTP completions, sharing Scout's existing queue contract.

Configuration is controller-owned, never selected by an evidence packet. There
are no inherited Kimi credentials, automatic retries, tools or model sessions.
Only the visible answer and numeric usage leave the response boundary.
"""
from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import kimi_scout_backend as contract

MAX_RESPONSE_BYTES = 1_048_576
MAX_OUTPUT_TOKENS = 32768


def read_request(value):
    tokens = value.get("max_output_tokens", 2048) if isinstance(value, dict) else None
    if type(tokens) is not int or not 256 <= tokens <= MAX_OUTPUT_TOKENS:
        raise contract.BackendError("invalid_max_output_tokens")
    # Reuse every common input rule without expanding the Kimi SDK contract.
    request = contract.read_request(json.dumps({**value, "max_output_tokens": min(tokens, 4096)}).encode())
    request["max_output_tokens"] = tokens
    return request


def load_config(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise contract.BackendError("invalid_http_backend_configuration") from None
    if not isinstance(value, dict) or set(value) - {
        "endpoint", "model", "alias", "api_key", "allow_http", "reasoning_effort"
    }:
        raise contract.BackendError("invalid_http_backend_configuration")
    if any(not isinstance(value.get(k), str) or not value[k].strip()
           for k in ("endpoint", "model", "alias")):
        raise contract.BackendError("invalid_http_backend_configuration")
    key = value.get("api_key")
    if key is not None and (not isinstance(key, str) or not key.strip() or "\n" in key or "\r" in key):
        raise contract.BackendError("invalid_http_backend_configuration")
    if "allow_http" in value and type(value["allow_http"]) is not bool:
        raise contract.BackendError("invalid_http_backend_configuration")
    if "reasoning_effort" in value and value["reasoning_effort"] not in ("low", "high", "max"):
        raise contract.BackendError("invalid_http_backend_configuration")
    try:
        url = urlsplit(value["endpoint"])
        valid = (url.scheme == "https" or (url.scheme == "http" and value.get("allow_http") is True))
        valid = valid and url.hostname and not (url.username or url.password or url.query or url.fragment)
        valid = valid and not any(c.isspace() for c in value["endpoint"])
        url.port  # Reject malformed ports without including the URL in errors.
    except ValueError:
        valid = False
    if not valid:
        raise contract.BackendError("invalid_http_backend_endpoint")
    return value


def reported_usage(raw):
    """Normalize only numeric observations, independently of answer acceptance."""
    if not isinstance(raw, dict):
        return None
    details = raw.get("prompt_tokens_details")
    details = (SimpleNamespace(cached_tokens=details.get("cached_tokens"))
               if isinstance(details, dict) else None)
    usage = contract.usage_payload(SimpleNamespace(
        prompt_tokens=raw.get("prompt_tokens"), completion_tokens=raw.get("completion_tokens"),
        cached_tokens=raw.get("cached_tokens"), prompt_tokens_details=details))
    if usage is not None:
        completion = raw.get("completion_tokens_details")
        reasoning = completion.get("reasoning_tokens") if isinstance(completion, dict) else None
        # This is a subset of inclusive completion tokens, never an extra charge.
        usage["reported_reasoning_output_tokens"] = (
            reasoning if type(reasoning) is int and 0 <= reasoning <= usage["output_tokens"] else None)
    return usage


def decode_answer(raw):
    if len(raw) > MAX_RESPONSE_BYTES:
        raise contract.BackendError("output_too_large")
    usage = None
    try:
        data = json.loads(raw)
        usage = reported_usage(data.get("usage")) if isinstance(data, dict) else None
        choices = data["choices"]
        if not isinstance(choices, list) or len(choices) != 1:
            raise ValueError
        choice = choices[0]
        message = choice["message"]
        if message.get("tool_calls") or message.get("function_call"):
            raise contract.BackendError("unexpected_tool_call")
        text = message.get("content") or ""
        if not isinstance(text, str):
            raise ValueError
        if len(text) > contract.MAX_OUTPUT_CHARS:
            raise contract.BackendError("output_too_large")
        reason = choice.get("finish_reason")
        if reason is not None and not isinstance(reason, str):
            raise ValueError
    except contract.BackendError as error:
        error._scout_final_usage = usage
        raise
    except (ValueError, TypeError, KeyError, AttributeError):
        error = contract.BackendError("invalid_http_backend_response")
        error._scout_final_usage = usage
        raise error from None
    ok = reason == "stop" and bool(text.strip())
    payload = dict(ok=ok, text=text, usage=usage,
        finish_reason=reason if reason in {None, "stop", "length", "content_filter", "tool_calls", "function_call"} else "unexpected",
        tools_advertised=0, tool_calls_executed=0)
    if not ok:
        payload.update(error="incomplete_response", retryable=False)
    return payload


class ProviderHTTPError(Exception):
    def __init__(self, status):
        self.status_code = status


async def complete(request, config, progress=None):
    import httpx

    contract.report_progress(progress, "", "requesting")
    body = dict(model=config["model"], messages=[
        dict(role="system", content=contract.SYSTEM_PROMPT),
        dict(role="user", content=request["prompt"])],
        max_tokens=request["max_output_tokens"], stream=False, n=1)
    if "reasoning_effort" in config:
        body["reasoning_effort"] = config["reasoning_effort"]
    headers = {"Content-Type": "application/json", "User-Agent": "kernel-opt-scout-tool-free"}
    if config.get("api_key"):
        headers["Authorization"] = "Bearer " + config["api_key"]
    timeout = request["timeout_seconds"]
    try:
        async with asyncio.timeout(timeout):
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=min(timeout, 15)),
                    trust_env=False, follow_redirects=False) as client:
                async with client.stream("POST", config["endpoint"], json=body, headers=headers) as response:
                    if response.status_code != 200:
                        raise ProviderHTTPError(response.status_code)
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > MAX_RESPONSE_BYTES:
                            raise contract.BackendError("output_too_large")
        payload = decode_answer(raw)
        contract.report_progress(progress, payload["text"], "completed" if payload["ok"] else "failed")
        return payload
    except Exception as error:
        contract.report_progress(progress, "", "failed")
        error._scout_failure_phase = "requesting"
        raise


class BackendPool:
    """Called by the existing bounded worker executor, without child SDKs."""
    process_starts = 0

    def __init__(self, config_file):
        self.config = load_config(config_file)

    def run(self, request, progress_file, timeout):
        try:
            request = read_request(request)
            if not math.isfinite(timeout) or timeout <= 0:
                raise contract.BackendError("invalid_timeout_seconds")
            request["timeout_seconds"] = min(request["timeout_seconds"], timeout)
            payload = asyncio.run(complete(request, self.config, contract.ProgressFile(progress_file)))
        except Exception as error:
            payload = contract.safe_error(error)
            observed = getattr(error, "_scout_final_usage", None)
            if isinstance(error, contract.BackendError) and isinstance(observed, dict):
                # Re-normalize a whitelist; no arbitrary exception data crosses.
                usage = reported_usage(dict(prompt_tokens=observed.get("input_tokens"),
                    completion_tokens=observed.get("output_tokens"),
                    cached_tokens=observed.get("cached_input_tokens"),
                    completion_tokens_details=dict(
                        reasoning_tokens=observed.get("reported_reasoning_output_tokens"))))
                if usage is not None:
                    payload["usage"] = usage
            # Preserve the existing supervisor's terminal access-denial route.
            if payload.get("http_status") in {401, 403}:
                payload["error_type"] = ("AuthenticationError" if payload["http_status"] == 401
                                         else "PermissionDeniedError")
        payload.update(model_alias=self.config["alias"], provider_type="openai_http")
        return SimpleNamespace(returncode=0 if payload["ok"] else 1,
            stdout=json.dumps(payload), stderr="")

    def close(self):
        pass  # Each request owns and closes its client/response.
