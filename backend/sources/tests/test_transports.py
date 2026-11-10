"""Unit tests for the test transports (T7.3; design §12, SRC-TEST-1)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable
from typing import Any

import httpx
import pytest

from core.sources.cassette import Cassette, CassetteEntry, request_key
from sources.tests.transports import (
    ALWAYS,
    FAULT_KINDS,
    Fault,
    FaultKind,
    counting_handler,
    fault_transport,
    json_response,
    key_of,
    replay_transport,
    slow_body_response,
)

A = "https://api.deps.dev/v3/systems/npm/packages/express"
B = "https://registry.npmjs.org/left-pad"
OSV = "https://api.osv.dev/v1/querybatch"
DOC = {"name": "express", "count": 3, "ok": True, "tags": ["a", "b"], "nested": {"n": None}}


def run[T](coro: Awaitable[T]) -> T:
    async def wrapper() -> T:
        return await coro

    return asyncio.run(wrapper())


async def _send(
    transport: httpx.AsyncBaseTransport,
    url: str,
    *,
    method: str = "GET",
    body: object = None,
) -> httpx.Response:
    async with httpx.AsyncClient(transport=transport) as client:
        return await client.request(method, url, json=body)


def send(
    transport: httpx.AsyncBaseTransport, url: str, *, method: str = "GET", body: object = None
) -> httpx.Response:
    return run(_send(transport, url, method=method, body=body))


def inner(request: httpx.Request) -> httpx.Response:
    return json_response(DOC)


# --------------------------------------------------------------- json_response


def test_json_response_defaults() -> None:
    response = json_response({"a": [1, 2]})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.content == b'{"a":[1,2]}'
    assert "retry-after" not in response.headers


def test_json_response_options() -> None:
    response = json_response(
        None, 429, content_type=None, retry_after="120", headers={"x-test": "1"}
    )
    assert response.status_code == 429
    assert "content-type" not in response.headers
    assert response.headers["retry-after"] == "120"
    assert response.headers["x-test"] == "1"
    assert response.content == b"null"


def test_json_response_rejects_non_json_values() -> None:
    with pytest.raises(ValueError):
        json_response({"a": float("nan")})
    with pytest.raises(ValueError):
        json_response({"a": object()})


# --------------------------------------------------------------------- replay


def _cassette() -> Cassette:
    return Cassette(
        (
            CassetteEntry("GET", A, None, 200, "application/json", None, {"hello": "world"}),
            CassetteEntry("GET", B, None, 429, None, "Wed, 21 Oct 2026 07:28:00 GMT", (1,)),
            CassetteEntry(
                "POST",
                OSV,
                {"queries": (1,), "b": 2},
                200,
                "application/json; charset=utf-8",
                None,
                {"results": ()},
            ),
        )
    )


def test_replay_returns_recorded_status_headers_and_body() -> None:
    transport, log = replay_transport(_cassette())
    first = send(transport, A)
    assert (first.status_code, first.json()) == (200, {"hello": "world"})
    assert first.headers["content-type"] == "application/json"

    second = send(transport, B)
    assert second.status_code == 429
    assert second.json() == [1]
    assert second.headers["retry-after"] == "Wed, 21 Oct 2026 07:28:00 GMT"
    assert "content-type" not in second.headers
    assert log.unmatched == []
    assert log.matched == [request_key("GET", A), request_key("GET", B)]


def test_replay_matches_post_body_regardless_of_key_order() -> None:
    transport, log = replay_transport(_cassette())
    response = send(transport, OSV, method="POST", body={"b": 2, "queries": [1]})
    assert response.json() == {"results": []}
    assert response.headers["content-type"] == "application/json; charset=utf-8"
    assert log.unmatched == []


def test_replay_logs_unmatched_and_raises_connect_error() -> None:
    transport, log = replay_transport(_cassette())
    other = "https://api.deps.dev/v3/systems/npm/packages/nope"
    with pytest.raises(httpx.ConnectError):
        send(transport, other)
    with pytest.raises(httpx.ConnectError):  # same URL, different body: no match
        send(transport, OSV, method="POST", body={"queries": [2], "b": 2})
    assert [(u.method, u.url) for u in log.unmatched] == [("GET", other), ("POST", OSV)]
    assert log.unmatched[0].key == request_key("GET", other)
    assert log.unmatched[1].key == request_key("POST", OSV, {"queries": [2], "b": 2})
    assert log.matched == []


def test_replay_wrong_method_is_unmatched() -> None:
    transport, log = replay_transport(_cassette())
    with pytest.raises(httpx.ConnectError):
        send(transport, A, method="POST", body=None)
    assert len(log.unmatched) == 1


def test_replay_of_empty_cassette_matches_nothing() -> None:
    transport, log = replay_transport(Cassette())
    with pytest.raises(httpx.ConnectError):
        send(transport, A)
    assert len(log.unmatched) == 1


def test_key_of_uses_method_url_and_json_body() -> None:
    request = httpx.Request("POST", OSV, json={"b": 2, "queries": [1]})
    assert key_of(request) == request_key("POST", OSV, {"queries": [1], "b": 2})
    assert key_of(httpx.Request("GET", A)) == request_key("GET", A)


# --------------------------------------------------------------------- faults


def _plan(fault: Fault, url: str = A) -> dict[str, Fault]:
    return {request_key("GET", url): fault}


def test_fault_kinds_are_the_design_list() -> None:
    assert set(FAULT_KINDS) == {
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
    }


def _faulted(fault: Fault) -> httpx.Response:
    return send(fault_transport(inner, _plan(fault)), A)


def test_read_timeout_fault() -> None:
    with pytest.raises(httpx.ReadTimeout):
        _faulted(Fault("read_timeout"))


def test_connect_error_fault() -> None:
    with pytest.raises(httpx.ConnectError):
        _faulted(Fault("connect_error"))


@pytest.mark.parametrize("status", [404, 429, 500, 502, 503, 504])
def test_status_fault(status: int) -> None:
    response = _faulted(Fault("status", status=status))
    assert response.status_code == status
    assert "retry-after" not in response.headers


def test_status_fault_defaults_to_503() -> None:
    assert _faulted(Fault("status")).status_code == 503


@pytest.mark.parametrize("value", ["7", "Wed, 21 Oct 2026 07:28:00 GMT"])
def test_status_fault_carries_retry_after_in_both_forms(value: str) -> None:
    response = _faulted(Fault("status", status=429, retry_after=value))
    assert response.status_code == 429
    assert response.headers["retry-after"] == value


def test_redirect_fault_has_location_and_is_not_followed() -> None:
    response = _faulted(Fault("redirect", location="https://evil.example/x"))
    assert response.status_code == 302
    assert response.headers["location"] == "https://evil.example/x"
    assert _faulted(Fault("redirect", status=301)).status_code == 301


def test_truncated_body_fault_is_cut_off_json() -> None:
    response = _faulted(Fault("truncated_body"))
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    with pytest.raises(ValueError):
        json.loads(response.content)


def test_not_json_fault() -> None:
    response = _faulted(Fault("not_json"))
    assert response.headers["content-type"] == "application/json"
    with pytest.raises(ValueError):
        json.loads(response.content)


def test_oversize_fault_with_content_length() -> None:
    response = _faulted(Fault("oversize", size=5000))
    assert len(response.content) == 5000
    assert response.headers["content-length"] == "5000"
    assert json.loads(response.content) == "a" * 4998


def test_oversize_fault_chunked_has_no_content_length() -> None:
    size = 200_000
    response = _faulted(Fault("oversize", size=size, chunked=True))
    assert len(response.content) == size
    assert "content-length" not in response.headers
    assert json.loads(response.content) == "a" * (size - 2)


def test_wrong_content_type_fault() -> None:
    response = _faulted(Fault("wrong_content_type"))
    assert response.headers["content-type"] == "text/html"
    assert response.json() == {}


@pytest.mark.parametrize(
    ("kind", "expected"),
    [("empty_object", {}), ("empty_array", []), ("null_body", None)],
)
def test_empty_shape_faults(kind: FaultKind, expected: object) -> None:
    response = _faulted(Fault(kind))
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == expected


def _same_shape_all_leaves_changed(original: Any, mutated: Any) -> bool:
    if isinstance(original, dict):
        return (
            isinstance(mutated, dict)
            and original.keys() == mutated.keys()
            and all(_same_shape_all_leaves_changed(original[k], mutated[k]) for k in original)
        )
    if isinstance(original, list):
        return (
            isinstance(mutated, list)
            and len(original) == len(mutated)
            and all(
                _same_shape_all_leaves_changed(o, m) for o, m in zip(original, mutated, strict=True)
            )
        )
    return type(original) is not type(mutated)


def test_wrong_field_types_fault_keeps_structure_and_changes_every_leaf_type() -> None:
    response = _faulted(Fault("wrong_field_types"))
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() != DOC
    assert _same_shape_all_leaves_changed(DOC, response.json())


def test_wrong_field_types_passes_through_a_body_that_is_not_json() -> None:
    def text_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"plain", headers={"content-type": "text/plain"})

    transport = fault_transport(text_handler, _plan(Fault("wrong_field_types")))
    assert send(transport, A).content == b"plain"


def test_fault_validation() -> None:
    with pytest.raises(ValueError):
        Fault("nonsense")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        Fault("status", times=0)
    with pytest.raises(ValueError):
        Fault("status", status=200)
    with pytest.raises(ValueError):
        Fault("redirect", status=404)
    with pytest.raises(ValueError):
        Fault("null_body", status=500)
    with pytest.raises(ValueError):
        Fault("oversize", size=0)


# ------------------------------------------------------- the `times` counter


def test_times_limits_a_fault_to_n_matching_requests() -> None:
    transport = fault_transport(inner, _plan(Fault("status", status=503, times=2)))

    async def go() -> list[int]:
        async with httpx.AsyncClient(transport=transport) as client:
            return [(await client.get(A)).status_code for _ in range(4)]

    assert run(go()) == [503, 503, 200, 200]


def test_times_counter_is_per_request_key_and_ignores_other_requests() -> None:
    plan = {
        request_key("GET", A): Fault("status", status=500, times=1),
        request_key("GET", B): Fault("status", status=502, times=2),
    }
    transport = fault_transport(inner, plan)
    c = "https://pypi.org/pypi/six/json"

    async def go() -> list[int]:
        async with httpx.AsyncClient(transport=transport) as client:
            order = [A, B, c, B, A, B, c, A]
            return [(await client.get(url)).status_code for url in order]

    # A: fault, then ok.  B: fault, fault, then ok.  c is unplanned: always ok.
    assert run(go()) == [500, 502, 200, 502, 200, 200, 200, 200]


def test_times_counter_is_keyed_by_body_not_just_url() -> None:
    first, second = {"q": 1}, {"q": 2}
    plan = {request_key("POST", OSV, first): Fault("status", status=500, times=1)}
    transport = fault_transport(lambda request: json_response({"results": []}), plan)

    async def go() -> list[int]:
        async with httpx.AsyncClient(transport=transport) as client:
            posts = [first, second, first, second]
            return [(await client.post(OSV, json=body)).status_code for body in posts]

    assert run(go()) == [500, 200, 200, 200]


def test_always_keeps_faulting() -> None:
    transport = fault_transport(inner, _plan(Fault("status", times=ALWAYS)))

    async def go() -> set[int]:
        async with httpx.AsyncClient(transport=transport) as client:
            return {(await client.get(A)).status_code for _ in range(20)}

    assert run(go()) == {503}


def test_each_transport_counts_independently_from_the_same_plan() -> None:
    plan = _plan(Fault("status", status=500, times=1))
    assert send(fault_transport(inner, plan), A).status_code == 500
    assert send(fault_transport(inner, plan), A).status_code == 500


def test_fault_transport_delegates_to_an_async_handler() -> None:
    async def async_handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0)
        return json_response({"async": True})

    transport = fault_transport(async_handler, {})
    assert send(transport, A).json() == {"async": True}


# ------------------------------------------------------------------- counting


def test_counting_handler_counts_total_hosts_and_endpoints() -> None:
    counter = counting_handler(inner)
    transport = httpx.MockTransport(counter)

    async def go() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            await client.get(A)
            await client.get(A)
            await client.get(B)
            await client.post(OSV, json={"queries": []})
            await client.get("https://registry.npmjs.org/%40babel%2Fcore")

    run(go())
    assert counter.total == 5
    assert counter.hosts == {"api.deps.dev": 2, "registry.npmjs.org": 2, "api.osv.dev": 1}
    assert counter.endpoints["GET api.deps.dev/v3/systems/npm/packages/express"] == 2
    assert counter.endpoints["POST api.osv.dev/v1/querybatch"] == 1
    assert counter.endpoints["GET registry.npmjs.org/%40babel%2Fcore"] == 1
    assert counter.urls[0] == A
    assert counter.count() == 5
    assert counter.count(host="registry.npmjs.org") == 2
    assert counter.count(method="post") == 1
    assert counter.count(host="api.deps.dev", path_prefix="/v3/systems/npm") == 2
    assert counter.count(host="api.deps.dev", path_prefix="/v3/systems/pypi") == 0
    assert counter.count(host="api.deps.dev", method="POST") == 0


def test_counting_handler_counts_requests_the_inner_handler_rejects() -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    counter = counting_handler(broken)
    with pytest.raises(httpx.ConnectError):
        send(httpx.MockTransport(counter), A)
    assert counter.total == 1


def test_counting_handler_wraps_a_fault_transport_handler_chain() -> None:
    counter = counting_handler(inner)
    transport = fault_transport(counter, _plan(Fault("status", status=500, times=1)))

    async def go() -> list[int]:
        async with httpx.AsyncClient(transport=transport) as client:
            return [(await client.get(A)).status_code for _ in range(3)]

    assert run(go()) == [500, 200, 200]
    assert counter.total == 2  # the injected fault never reached the wrapped handler


# ------------------------------------------------------------ slow body drip


def test_slow_body_response_yields_chunks_with_delay() -> None:
    chunks = [b'{"a":', b"[1,", b"2]}"]
    delay = 0.02

    async def go() -> tuple[list[bytes], float, httpx.Response]:
        transport = httpx.MockTransport(lambda request: slow_body_response(chunks, delay))
        loop = asyncio.get_running_loop()
        async with httpx.AsyncClient(transport=transport) as client:
            started = loop.time()
            async with client.stream("GET", A) as response:
                received = [part async for part in response.aiter_raw()]
            return received, loop.time() - started, response

    received, elapsed, response = run(go())
    assert b"".join(received) == b'{"a":[1,2]}'
    assert len(received) == 3
    assert elapsed >= 0.9 * delay * len(chunks)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert "content-length" not in response.headers


def test_slow_body_response_trips_a_short_real_deadline() -> None:
    transport = httpx.MockTransport(lambda request: slow_body_response([b"x"] * 50, 0.5))

    async def go() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            async with asyncio.timeout(0.05):
                async with client.stream("GET", A) as response:
                    async for _ in response.aiter_raw():
                        pass

    with pytest.raises(TimeoutError):
        run(go())


def test_slow_body_response_options_and_validation() -> None:
    response = slow_body_response([], 0.0, status=200, content_type=None)
    assert "content-type" not in response.headers
    with pytest.raises(ValueError):
        slow_body_response([b"x"], -1.0)
