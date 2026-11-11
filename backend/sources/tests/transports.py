"""Test transports for the source clients (design §12, SRC-TEST-1).

Everything here is an ``httpx.MockTransport`` or a handler for one. Nothing touches the
network.

* ``replay_transport(cassette)`` answers from a recorded ``Cassette`` and logs every request
  it has no recording for (``log.unmatched``), answering those with ``httpx.ConnectError``.
* ``fault_transport(handler, plan)`` wraps a handler and injects a ``Fault`` for the first
  ``times`` requests whose request key is in ``plan``; later requests, and requests whose key
  is not in the plan, go to the wrapped handler.
* ``counting_handler(handler)`` counts requests per host and per endpoint.
* ``slow_body_response(chunks, delay)`` is a response whose body drips in over real time, for
  testing the per-request deadline.
* ``json_response(...)`` builds a response from a JSON value.

The request key is ``core.sources.cassette.request_key(method, url, body)``: the method, the
URL as httpx serialises it, and the request body parsed as JSON (``None`` when empty). Headers
are never part of it, so a recorded exchange never depends on, or stores, a token (SRC-SEC-7).
Keying faults by request key rather than call index keeps a plan independent of scheduling.

Handlers may be sync or ``async``; the wrappers here are ``async`` so they can await either.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from collections.abc import AsyncIterator, Callable, Coroutine, Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Literal, get_args

import httpx

from core.sources.cassette import Cassette, freeze_json, request_key, thaw_json

type SyncHandler = Callable[[httpx.Request], httpx.Response]
type AsyncHandler = Callable[[httpx.Request], Coroutine[Any, Any, httpx.Response]]
type Handler = SyncHandler | AsyncHandler

JSON_CONTENT_TYPE: Final = "application/json"
ALWAYS: Final = sys.maxsize
"""``Fault.times`` value for a fault that never stops."""

_CHUNK_BYTES: Final = 64 * 1024


# ---------------------------------------------------------------------- helpers


def key_of(request: httpx.Request) -> str:
    """Return the request key of ``request``: (method, URL, JSON body)."""
    content = request.content
    body: object = None
    if content:
        try:
            body = json.loads(content)
        except ValueError:
            body = content.decode("utf-8", errors="replace")
    return request_key(request.method, str(request.url), body)


async def _call(handler: Handler, request: httpx.Request) -> httpx.Response:
    result = handler(request)
    if isinstance(result, httpx.Response):
        return result
    return await result


def json_response(
    data: object,
    status: int = 200,
    *,
    content_type: str | None = JSON_CONTENT_TYPE,
    retry_after: str | None = None,
    headers: Mapping[str, str] | None = None,
) -> httpx.Response:
    """Build a response whose body is ``data`` as compact JSON.

    ``content_type=None`` sends no ``Content-Type`` header. ``retry_after`` is the raw
    header value (seconds or an HTTP date). ``data`` must be JSON-compatible and finite.
    """
    plain = thaw_json(freeze_json(data))
    out: dict[str, str] = dict(headers or {})
    if content_type is not None:
        out["content-type"] = content_type
    if retry_after is not None:
        out["retry-after"] = retry_after
    body = json.dumps(plain, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return httpx.Response(status, content=body, headers=out)


class _ChunkStream(httpx.AsyncByteStream):
    """A body of ``chunks``; with ``delay`` > 0 each chunk waits that long (real time)."""

    def __init__(self, chunks: list[bytes], delay: float) -> None:
        self._chunks = chunks
        self._delay = delay

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            if self._delay > 0:
                await asyncio.sleep(self._delay)
            yield chunk

    async def aclose(self) -> None:
        return None


def slow_body_response(
    chunks: list[bytes],
    delay: float,
    *,
    status: int = 200,
    content_type: str | None = JSON_CONTENT_TYPE,
) -> httpx.Response:
    """A response whose body arrives as ``chunks``, ``delay`` real seconds before each one.

    The headers arrive at once and there is no ``Content-Length``, so a client that only
    bounds the connect/read timeouts stays busy. Used with a short real
    ``request_deadline`` to test that a slow-drip body cannot hold a slot.
    """
    if delay < 0:
        raise ValueError("delay must be non-negative")
    headers = {} if content_type is None else {"content-type": content_type}
    return httpx.Response(status, headers=headers, stream=_ChunkStream(list(chunks), delay))


# ----------------------------------------------------------------------- replay


@dataclass(frozen=True)
class UnmatchedRequest:
    """A request the cassette had no recording for. Holds no headers (SRC-SEC-7)."""

    method: str
    url: str
    key: str


@dataclass
class ReplayLog:
    """What a replay transport saw. A clean run asserts ``unmatched == []`` (SRC-TEST-1)."""

    unmatched: list[UnmatchedRequest] = field(default_factory=list)
    matched: list[str] = field(default_factory=list)  # request keys, in arrival order


def replay_transport(cassette: Cassette) -> tuple[httpx.MockTransport, ReplayLog]:
    """Return a transport that replays ``cassette`` and the log of what it served.

    A request is matched by its request key. The recorded status, ``Content-Type``,
    ``Retry-After`` and JSON body are replayed. A request with no recording is appended to
    ``log.unmatched`` and raises ``httpx.ConnectError``.
    """
    index = cassette.index()
    log = ReplayLog()

    def handler(request: httpx.Request) -> httpx.Response:
        key = key_of(request)
        entry = index.get(key)
        if entry is None:
            log.unmatched.append(UnmatchedRequest(request.method, str(request.url), key))
            raise httpx.ConnectError("no recorded response for this request", request=request)
        log.matched.append(key)
        return json_response(
            entry.response_body,
            entry.status,
            content_type=entry.content_type,
            retry_after=entry.retry_after,
        )

    return httpx.MockTransport(handler), log


# ----------------------------------------------------------------------- faults

FaultKind = Literal[
    "read_timeout",
    "connect_error",
    "status",
    "redirect",
    "truncated_body",
    "not_json",
    "oversize",
    "wrong_content_type",
    "empty_object",
    "empty_array",
    "null_body",
    "wrong_field_types",
    "wrong_one_leaf",
]
FAULT_KINDS: Final[tuple[str, ...]] = get_args(FaultKind)

_DEFAULT_OVERSIZE_BYTES: Final = 17 * 1024 * 1024  # above every host cap in the default config


@dataclass(frozen=True)
class Fault:
    """One kind of failure, applied to the first ``times`` matching requests.

    * ``read_timeout``, ``connect_error``: the transport raises ``httpx.ReadTimeout`` /
      ``httpx.ConnectError``.
    * ``status``: an error status (default 503; 429, 404 and 5xx are the ones used) with
      an optional raw ``retry_after`` header, an empty JSON object as body.
    * ``redirect``: a 3xx (default 302) with a ``Location`` header.
    * ``truncated_body``: a JSON document cut off mid-way, with a JSON content type.
    * ``not_json``: an HTML body with a JSON content type.
    * ``oversize``: a JSON string of ``size`` bytes. With ``chunked`` it is streamed with no
      ``Content-Length``, so only a streaming size check can catch it.
    * ``wrong_content_type``: ``{}`` with ``text/html``.
    * ``empty_object``, ``empty_array``, ``null_body``: ``{}``, ``[]``, ``null``.
    * ``wrong_field_types``: the wrapped handler's JSON with the same structure and every
      leaf replaced by a value of another type.
    * ``wrong_one_leaf``: the same, for **one** leaf only: the ``leaf``-th leaf in document
      order (modulo the number of leaves) gets a value of another type and the rest is
      untouched. Unlike ``wrong_field_types`` it leaves most of a response readable, so a
      single damaged commit node, count or date can be told apart from a wrecked response.
    """

    kind: FaultKind
    times: int = 1
    status: int | None = None
    retry_after: str | None = None
    location: str = "https://example.com/elsewhere"
    size: int = _DEFAULT_OVERSIZE_BYTES
    chunked: bool = False
    leaf: int = 0

    def __post_init__(self) -> None:
        if self.kind not in FAULT_KINDS:
            raise ValueError(f"unknown fault kind: {self.kind!r}")
        if isinstance(self.leaf, bool) or not isinstance(self.leaf, int) or self.leaf < 0:
            raise ValueError("leaf must be an integer >= 0")
        if isinstance(self.times, bool) or not isinstance(self.times, int) or self.times < 1:
            raise ValueError("times must be an integer >= 1")
        if self.kind == "status":
            if self.status is not None and not 400 <= self.status <= 599:
                raise ValueError("status fault needs a status in 400..599")
        elif self.kind == "redirect":
            if self.status is not None and not 300 <= self.status <= 399:
                raise ValueError("redirect fault needs a status in 300..399")
        elif self.status is not None:
            raise ValueError(f"status does not apply to a {self.kind} fault")
        if self.size < 1:
            raise ValueError("size must be positive")

    def effective_status(self) -> int:
        """The status for ``status`` and ``redirect`` faults, with the kind's default."""
        if self.status is not None:
            return self.status
        return 302 if self.kind == "redirect" else 503


def _wrong_type(value: object) -> object:
    """Same structure as ``value``, every leaf swapped for a different JSON type."""
    if isinstance(value, dict):
        return {key: _wrong_type(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_wrong_type(item) for item in value]
    if isinstance(value, bool):
        return "true"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, str):
        return 1
    return 0  # None


def _leaf_paths(document: object) -> list[tuple[str | int, ...]]:
    """Paths of every leaf (not a dict, not a list) in document order."""
    paths: list[tuple[str | int, ...]] = []

    def walk(node: object, path: tuple[str | int, ...]) -> None:
        if isinstance(node, dict):
            for key, item in node.items():
                walk(item, (*path, key))
        elif isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, (*path, index))
        else:
            paths.append(path)

    walk(document, ())
    return paths


def _wrong_one_leaf(document: object, leaf: int) -> object:
    """``document`` with the ``leaf``-th leaf swapped for a value of another type."""
    paths = _leaf_paths(document)
    if not paths:  # {} or []: nothing to damage
        return document
    path = paths[leaf % len(paths)]
    if not path:
        return _wrong_type(document)
    copy: Any = json.loads(json.dumps(document))
    parent: Any = copy
    for step in path[:-1]:
        parent = parent[step]
    parent[path[-1]] = _wrong_type(parent[path[-1]])
    return copy


def _oversize_response(fault: Fault) -> httpx.Response:
    head, tail = b'"', b'"'
    filler = fault.size - 2
    if not fault.chunked:
        return httpx.Response(
            200,
            content=head + b"a" * max(filler, 0) + tail,
            headers={"content-type": JSON_CONTENT_TYPE},
        )
    chunks = [head]
    remaining = max(filler, 0)
    while remaining > 0:
        step = min(remaining, _CHUNK_BYTES)
        chunks.append(b"a" * step)
        remaining -= step
    chunks.append(tail)
    return httpx.Response(
        200, headers={"content-type": JSON_CONTENT_TYPE}, stream=_ChunkStream(chunks, 0.0)
    )


async def _apply(fault: Fault, inner: Handler, request: httpx.Request) -> httpx.Response:
    kind = fault.kind
    if kind == "read_timeout":
        raise httpx.ReadTimeout("injected read timeout", request=request)
    if kind == "connect_error":
        raise httpx.ConnectError("injected connect error", request=request)
    if kind == "status":
        return json_response({}, fault.effective_status(), retry_after=fault.retry_after)
    if kind == "redirect":
        return httpx.Response(fault.effective_status(), headers={"location": fault.location})
    if kind == "truncated_body":
        return httpx.Response(
            200,
            content=b'{"truncated":[1,2,3,{"a":',
            headers={"content-type": JSON_CONTENT_TYPE},
        )
    if kind == "not_json":
        return httpx.Response(
            200,
            content=b"<html><body>not json</body></html>",
            headers={"content-type": JSON_CONTENT_TYPE},
        )
    if kind == "oversize":
        return _oversize_response(fault)
    if kind == "wrong_content_type":
        return json_response({}, content_type="text/html")
    if kind == "empty_object":
        return json_response({})
    if kind == "empty_array":
        return json_response([])
    if kind == "null_body":
        return json_response(None)
    # wrong_field_types, wrong_one_leaf: need the real answer to mutate
    response = await _call(inner, request)
    try:
        document = json.loads(response.content)
    except Exception:  # streamed, empty or not JSON: nothing to mutate, pass it through
        return response
    mutated = (
        _wrong_one_leaf(document, fault.leaf) if kind == "wrong_one_leaf" else _wrong_type(document)
    )
    return json_response(
        mutated,
        response.status_code,
        content_type=response.headers.get("content-type"),
    )


def fault_transport(handler: Handler, plan: Mapping[str, Fault]) -> httpx.MockTransport:
    """Wrap ``handler`` so that planned requests fail the first ``fault.times`` times.

    ``plan`` maps a request key (``request_key(method, url, body)``) to a ``Fault``. The
    counter is per request key, held inside the returned transport, so two transports built
    from one plan count independently. Requests whose key is not in the plan, and requests
    after the fault has been used up, go to ``handler``.
    """
    seen: Counter[str] = Counter()

    async def faulty(request: httpx.Request) -> httpx.Response:
        key = key_of(request)
        fault = plan.get(key)
        if fault is not None:
            seen[key] += 1
            if seen[key] <= fault.times:
                return await _apply(fault, handler, request)
        return await _call(handler, request)

    return httpx.MockTransport(faulty)


# --------------------------------------------------------------------- counting


class CountingHandler:
    """A handler wrapper that counts requests, then delegates.

    ``total`` counts every request; ``hosts`` per host; ``endpoints`` per
    ``"<METHOD> <host><path>"``; ``urls`` lists each requested URL in order. A request is
    counted before the wrapped handler runs, so one that raises is counted too.
    """

    def __init__(self, inner: Handler) -> None:
        self._inner = inner
        self.total = 0
        self.hosts: Counter[str] = Counter()
        self.endpoints: Counter[str] = Counter()
        self.urls: list[str] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.total += 1
        self.hosts[request.url.host] += 1
        path = request.url.raw_path.decode("ascii").split("?", 1)[0]  # keep %2F as sent
        self.endpoints[f"{request.method} {request.url.host}{path}"] += 1
        self.urls.append(str(request.url))
        return await _call(self._inner, request)

    def count(
        self,
        *,
        host: str | None = None,
        method: str | None = None,
        path_prefix: str | None = None,
    ) -> int:
        """Number of counted requests matching every given filter."""
        total = 0
        for endpoint, number in self.endpoints.items():
            request_method, rest = endpoint.split(" ", 1)
            request_host, _, path = rest.partition("/")
            if host is not None and request_host != host:
                continue
            if method is not None and request_method != method.upper():
                continue
            if path_prefix is not None and not ("/" + path).startswith(path_prefix):
                continue
            total += number
        return total


def counting_handler(handler: Handler) -> CountingHandler:
    """Wrap ``handler`` in a ``CountingHandler``; pass it to ``httpx.MockTransport``."""
    return CountingHandler(handler)
