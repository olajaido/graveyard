"""Proves the socket blocker in conftest.py is active (CLI-TEST-1)."""

from __future__ import annotations

import socket

import httpx
import pytest


def test_httpx_client_cannot_reach_network() -> None:
    """CLI-TEST-1: a real HTTP request fails instead of leaving the machine."""
    with pytest.raises(Exception) as excinfo, httpx.Client() as client:
        client.get("https://example.org")
    chain: BaseException | None = excinfo.value
    messages: list[str] = []
    while chain is not None:
        messages.append(str(chain))
        chain = chain.__cause__ or chain.__context__
    assert any("network access in a cli test" in m for m in messages) or isinstance(
        excinfo.value, httpx.HTTPError
    )


def test_socket_primitives_raise_assertion_error() -> None:
    """CLI-TEST-1: both patched entry points raise the documented AssertionError."""
    with pytest.raises(AssertionError, match="network access in a cli test"):
        socket.create_connection(("127.0.0.1", 9))
    with pytest.raises(AssertionError, match="network access in a cli test"):
        socket.socket().connect(("127.0.0.1", 9))
