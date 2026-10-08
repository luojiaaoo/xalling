"""Async tests use the same backend as Uvicorn and Claude SDK."""

import pytest


@pytest.fixture
def anyio_backend():
    return "asyncio"
