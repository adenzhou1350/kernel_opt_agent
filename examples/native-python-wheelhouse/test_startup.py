"""Small pytest plugin preflight, not a target-project correctness test."""
import asyncio

import pytest
from typing_extensions import TypeIs


def test_sync_fixture(monkeypatch):
    monkeypatch.setenv("SCOUT_STARTUP_CANARY", "present")
    assert TypeIs is not None


@pytest.mark.asyncio
async def test_async_fixture(mocker):
    callback = mocker.Mock()
    await asyncio.sleep(0)
    callback("observed")
    callback.assert_called_once_with("observed")


@pytest.mark.repeat(2)
def test_repeat_plugin():
    assert sum((1, 2)) == 3
