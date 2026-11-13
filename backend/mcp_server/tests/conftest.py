"""Shared fixtures for the MCP server tests (KPW-TEST-12: no test may touch the network)."""

from __future__ import annotations

import socket
from collections.abc import Iterator
from typing import Any

import pytest

_MESSAGE = "network access in an mcp_server test"


def _blocked(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError(_MESSAGE)


@pytest.fixture(autouse=True)
def _block_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Make any socket connection attempt fail; monkeypatch restores both after each test."""
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    yield
