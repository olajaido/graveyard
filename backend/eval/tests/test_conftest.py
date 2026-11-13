"""Proves the socket blocker in conftest.py is active (EV-RUN-4, EV-TEST-6)."""

from __future__ import annotations

import socket

import httpx
import pytest

_MESSAGE = "network access in an eval test"


def _chain_messages(exc: BaseException) -> list[str]:
    messages: list[str] = []
    current: BaseException | None = exc
    while current is not None:
        messages.append(str(current))
        current = current.__cause__ or current.__context__
    return messages


def test_httpx_client_cannot_reach_network() -> None:
    """A real HTTP request fails at connect instead of leaving the machine.

    An IP literal is used so the outcome does not depend on DNS working offline.
    """
    with pytest.raises(Exception) as excinfo, httpx.Client() as client:
        client.get("https://93.184.215.14")
    assert any(_MESSAGE in m for m in _chain_messages(excinfo.value))


def test_socket_primitives_raise_assertion_error() -> None:
    """Both patched entry points raise the documented AssertionError."""
    with pytest.raises(AssertionError, match=_MESSAGE):
        socket.create_connection(("example.org", 443))
    with pytest.raises(AssertionError, match=_MESSAGE):
        socket.socket().connect(("127.0.0.1", 9))
