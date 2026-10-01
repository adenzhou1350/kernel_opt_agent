"""Assert the realized backend in a native Hypothesis test (AnyIO #1353)."""
from __future__ import annotations

import os

import pytest
from anyio.lowlevel import get_async_backend
from hypothesis import given, settings
from hypothesis.strategies import just


@pytest.fixture(scope="session", params=(
    ["trio", "asyncio"] if os.environ.get("REVERSE_BACKEND_ORDER") == "1"
    else ["asyncio", "trio"]
))
def anyio_backend(request):
    return request.param


@pytest.mark.anyio
@settings(max_examples=1, deadline=None, database=None)
@given(x=just(1))
async def test_hypothesis_backend_identity(anyio_backend, x):
    assert x == 1
    actual = get_async_backend().__module__.rsplit(".", 1)[-1].removeprefix("_")
    assert actual == anyio_backend, (anyio_backend, actual)


@pytest.mark.anyio
async def test_plain_backend_identity(anyio_backend):
    actual = get_async_backend().__module__.rsplit(".", 1)[-1].removeprefix("_")
    assert actual == anyio_backend, (anyio_backend, actual)
