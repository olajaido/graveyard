"""Property tests for ``HttpGateway`` on ``FakeClock`` and ``httpx.MockTransport`` (T7.5).

* ``test_gateway_never_raises``: any plan of faults from ``fault_transport`` gives ``Ok``,
  ``NotFound`` or ``Failed`` for every request (SRC-HTTP-11).
* ``test_backoff_bounds``: the sleeps of a retried request follow the full-jitter schedule
  of ``RetryPolicy``, or the ``Retry-After`` value when the host sent one (SRC-HTTP-8).
* ``test_failed_has_no_untrusted_text``: bodies, header values and exception text from the
  host never appear in a ``Failed`` (SRC-HTTP-11, SRC-SEC-3).

Waiting goes through ``FakeClock``, so nothing sleeps for real. Async code runs under
``asyncio.run``. Profiles (``dev`` = 200 examples, ``ci`` = 500) come from ``conftest.py``
via ``HYPOTHESIS_PROFILE``; no ``max_examples`` is set here.
"""

from __future__ import annotations

import asyncio
import dataclasses
import random
import string
from collections.abc import Callable
from dataclasses import replace
from typing import Final

import httpx
import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from core.sources.cassette import request_key
from core.sources.config import RetryPolicy, SourcesConfig, Timeouts
from core.sources.model import WARNING_CODES
from core.sources.urls import ALLOWED_HOSTS
from sources.gateway import ApiRequest, Failed, FetchResult, HttpGateway, NotFound, Ok
from sources.tests.clock import FakeClock
from sources.tests.transports import (
    ALWAYS,
    Fault,
    FaultKind,
    Handler,
    fault_transport,
    json_response,
)

pytestmark = pytest.mark.property

CONTACT = "ops@example.org"
SMALL_CAP: Final = 1024
HOSTS: Final = sorted(ALLOWED_HOSTS)
GITHUB = "api.github.com"

_BASE_DOCUMENT: Final = {"a": [1, "x", None], "b": {"c": True, "d": 2.5}}


def make_config(
    *,
    timeouts: Timeouts | None = None,
    retry: RetryPolicy | None = None,
    max_response_bytes: int = SMALL_CAP,
) -> SourcesConfig:
    """The default config with one small response cap on every host."""
    base = SourcesConfig.default(contact=CONTACT)
    hosts = {h: replace(p, max_response_bytes=max_response_bytes) for h, p in base.hosts.items()}
    return SourcesConfig(
        hosts=hosts,
        contact=CONTACT,
        timeouts=timeouts or Timeouts(),
        retry=retry or RetryPolicy(),
    )


def clean_handler(_request: httpx.Request) -> httpx.Response:
    return json_response(_BASE_DOCUMENT)


def gateway_for(
    transport: httpx.AsyncBaseTransport, config: SourcesConfig, clock: FakeClock, seed: int
) -> HttpGateway:
    return HttpGateway(config, clock, rng=random.Random(seed), transport=transport)


def key_for(request: ApiRequest) -> str:
    """The request key ``fault_transport`` computes for ``request`` as it goes out."""
    return request_key(request.method, request.url, request.body)


# ------------------------------------------------------------ never raises


def _request_pool() -> list[ApiRequest]:
    pool = [ApiRequest("GET", f"https://{host}/x/1", "depsdev") for host in HOSTS]
    pool += [
        ApiRequest("GET", "https://api.deps.dev/x/missing", "depsdev", not_found_ok=True),
        ApiRequest("POST", "https://api.osv.dev/v1/querybatch", "osv", body={"queries": [1, 2]}),
        ApiRequest("POST", "https://api.github.com/graphql", "github", body={"query": "{ a }"}),
        # Refused before anything is sent.
        ApiRequest("GET", "https://example.com/x", "depsdev"),
        ApiRequest("GET", "http://api.deps.dev/x/1", "depsdev"),
    ]
    return pool


REQUESTS: Final = _request_pool()

_RETRY_AFTER_VALUES: Final = [
    None,
    "0",
    "1",
    "5",
    "20",
    "21",
    "99999999999999999999",
    "soon",
    "",
    "Wed, 21 Oct 2037 07:28:00 GMT",
]
_times = st.one_of(st.integers(1, 5), st.just(ALWAYS))

_plain_faults = st.builds(
    Fault,
    kind=st.sampled_from(
        [
            "read_timeout",
            "connect_error",
            "truncated_body",
            "not_json",
            "wrong_content_type",
            "empty_object",
            "empty_array",
            "null_body",
            "wrong_field_types",
        ]
    ),
    times=_times,
)
_status_faults = st.builds(
    Fault,
    kind=st.just("status"),
    times=_times,
    status=st.sampled_from([400, 403, 404, 410, 429, 500, 502, 503, 504, 599]),
    retry_after=st.sampled_from(_RETRY_AFTER_VALUES),
)
_redirect_faults = st.builds(
    Fault, kind=st.just("redirect"), times=_times, status=st.sampled_from([301, 302, 307, 308])
)
_oversize_faults = st.builds(
    Fault,
    kind=st.just("oversize"),
    times=_times,
    size=st.integers(2 * SMALL_CAP, 8 * SMALL_CAP),
    chunked=st.booleans(),
)
faults = st.one_of(_plain_faults, _status_faults, _redirect_faults, _oversize_faults)


@given(
    plan_faults=st.lists(
        st.one_of(st.none(), faults), min_size=len(REQUESTS), max_size=len(REQUESTS)
    ),
    order=st.lists(st.integers(0, len(REQUESTS) - 1), min_size=1, max_size=10),
    concurrent=st.booleans(),
    batch_deadline=st.sampled_from([240.0, 4.0]),
    seed=st.integers(0, 2**16),
)
def test_gateway_never_raises(
    plan_faults: list[Fault | None],
    order: list[int],
    concurrent: bool,
    batch_deadline: float,
    seed: int,
) -> None:
    """SRC-HTTP-11: every request gives ``Ok | NotFound | Failed``, whatever the faults."""
    plan = {
        key_for(request): fault
        for request, fault in zip(REQUESTS, plan_faults, strict=True)
        if fault is not None
    }
    config = make_config(timeouts=Timeouts(batch_deadline=batch_deadline))
    requests = [REQUESTS[i] for i in order]

    async def scenario() -> list[FetchResult]:
        gateway = gateway_for(fault_transport(clean_handler, plan), config, FakeClock(), seed)
        async with gateway, asyncio.timeout(20):  # real time: a hang fails instead of blocking
            if concurrent:
                return list(await asyncio.gather(*(gateway.fetch(r) for r in requests)))
            return [await gateway.fetch(r) for r in requests]

    results = asyncio.run(scenario())  # an exception escaping ``fetch`` fails the test here

    assert len(results) == len(requests)
    for request, result in zip(requests, results, strict=True):
        assert isinstance(result, Ok | NotFound | Failed)
        if isinstance(result, Failed):
            assert result.kind in WARNING_CODES
        if isinstance(result, NotFound):
            assert request.not_found_ok


# ---------------------------------------------------------- backoff bounds

_RETRYABLE_STATUSES: Final = [429, 500, 502, 503, 504]

retry_policies = st.builds(
    RetryPolicy,
    max_attempts=st.integers(1, 8),
    base=st.floats(0.01, 2.0, allow_nan=False, allow_infinity=False),
    cap=st.floats(0.01, 30.0, allow_nan=False, allow_infinity=False),
    max_retry_after_seconds=st.floats(0.0, 30.0, allow_nan=False, allow_infinity=False),
)


def _fetch_with_persistent_fault(
    fault: Fault, retry: RetryPolicy, seed: int
) -> tuple[FetchResult, list[float]]:
    """Fetch one URL whose every answer is ``fault``; return the result and the fake sleeps."""
    request = ApiRequest("GET", "https://api.deps.dev/x/1", "depsdev")
    # A deadline far beyond any schedule here, so only the retry schedule decides the sleeps.
    config = make_config(timeouts=Timeouts(batch_deadline=10.0**6), retry=retry)
    clock = FakeClock()
    transport = fault_transport(clean_handler, {key_for(request): fault})

    async def scenario() -> FetchResult:
        async with gateway_for(transport, config, clock, seed) as gateway, asyncio.timeout(20):
            return await gateway.fetch(request)

    return asyncio.run(scenario()), clock.sleeps


@given(
    retry=retry_policies,
    seed=st.integers(0, 2**16),
    failure=st.sampled_from(
        [  # (fault kind, fault status, expected Failed.kind)
            ("status", 429, "RATE_LIMITED"),
            ("status", 500, "HTTP_STATUS"),
            ("status", 502, "HTTP_STATUS"),
            ("status", 503, "HTTP_STATUS"),
            ("status", 504, "HTTP_STATUS"),
            ("read_timeout", None, "TIMEOUT"),
            ("connect_error", None, "CONNECT_ERROR"),
        ]
    ),
)
def test_backoff_bounds(
    retry: RetryPolicy, seed: int, failure: tuple[FaultKind, int | None, str]
) -> None:
    """SRC-HTTP-8: sleep ``i`` is in ``[0, min(cap, base * 2**i)]``, one sleep per retry."""
    kind, status, expected_kind = failure
    fault = Fault(kind, times=ALWAYS, status=status)
    result, sleeps = _fetch_with_persistent_fault(fault, retry, seed)

    assert isinstance(result, Failed)
    assert result.kind == expected_kind
    assert result.status == status
    assert len(sleeps) == retry.max_attempts - 1
    for i, slept in enumerate(sleeps):
        assert 0.0 <= slept <= min(retry.cap, retry.base * 2**i)


@given(
    retry=retry_policies,
    seed=st.integers(0, 2**16),
    status=st.sampled_from(_RETRYABLE_STATUSES),
    retry_after=st.integers(0, 60),
)
def test_backoff_bounds_with_retry_after(
    retry: RetryPolicy, seed: int, status: int, retry_after: int
) -> None:
    """SRC-HTTP-8: a ``Retry-After`` within the cap is slept exactly; over the cap it is not."""
    fault = Fault("status", times=ALWAYS, status=status, retry_after=str(retry_after))
    result, sleeps = _fetch_with_persistent_fault(fault, retry, seed)

    assert isinstance(result, Failed)
    assert result.kind == "RATE_LIMITED"
    assert result.status == status
    if retry_after > retry.max_retry_after_seconds:
        assert sleeps == []
    else:
        assert sleeps == [float(retry_after)] * (retry.max_attempts - 1)


# ------------------------------------------------------ no untrusted text

_SAFE_HEADER_ALPHABET: Final = string.ascii_letters + string.digits + " _.:/-"
_tags = st.text(alphabet=string.ascii_letters + string.digits, min_size=12, max_size=24)
_noise = st.text(max_size=20)  # arbitrary unicode around the tag in bodies
_header_noise = st.text(alphabet=_SAFE_HEADER_ALPHABET, max_size=10)


def _scenario_handler(
    mode: str, tag: str, before: str, after: str, hdr: str, status: int
) -> Handler:
    """A hostile handler for ``mode`` that puts ``tag`` in every body, header and exception."""
    body_text = f"{before}{tag}{after}"
    headers = {"x-note": f"{hdr}{tag}", "x-ratelimit-remaining": "7"}
    size = SMALL_CAP * 2

    def respond(
        code: int,
        content: bytes,
        content_type: str | None = "application/json",
        extra: dict[str, str] | None = None,
    ) -> Handler:
        out = {**headers, **(extra or {})}
        if content_type is not None:
            out["content-type"] = content_type
        return lambda _request: httpx.Response(code, content=content, headers=out)

    def raising(make: Callable[[httpx.Request], Exception]) -> Handler:
        def handler(request: httpx.Request) -> httpx.Response:
            raise make(request)

        return handler

    json_body = httpx.Response(200, json={"message": body_text}).content
    handlers: dict[str, Handler] = {
        "error_status": respond(status, json_body, extra={"retry-after": f"{tag}"}),
        "invalid_json": respond(200, f"{{{body_text}".encode()),
        "invalid_utf8": respond(200, b"\xff\xfe" + tag.encode()),
        "non_finite": respond(200, f'{{"n": NaN, "m": "{tag}"}}'.encode()),
        "wrong_content_type": respond(
            200, json_body, content_type=f"text/html; note={hdr}{tag}", extra={"x-q": tag}
        ),
        "no_content_type": respond(200, json_body, content_type=None),
        "redirect": respond(
            302, b"", content_type=None, extra={"location": f"https://evil.example/{tag}"}
        ),
        "oversize": respond(200, (tag * (size // len(tag) + 1)).encode()),
        "connect_error": raising(lambda r: httpx.ConnectError(tag, request=r)),
        "read_timeout": raising(lambda r: httpx.ReadTimeout(tag, request=r)),
        "runtime_error": raising(lambda _r: RuntimeError(tag)),
    }
    return handlers[mode]


_MODES: Final = [
    "error_status",
    "invalid_json",
    "invalid_utf8",
    "non_finite",
    "wrong_content_type",
    "no_content_type",
    "redirect",
    "oversize",
    "connect_error",
    "read_timeout",
    "runtime_error",
]


@given(
    mode=st.sampled_from(_MODES),
    host=st.sampled_from(HOSTS),
    tag=_tags,
    before=_noise,
    after=_noise,
    hdr=_header_noise,
    status=st.sampled_from([400, 401, 403, 404, 410, 418, 429, 500, 503, 504]),
    seed=st.integers(0, 2**16),
)
def test_failed_has_no_untrusted_text(
    mode: str, host: str, tag: str, before: str, after: str, hdr: str, status: int, seed: int
) -> None:
    """SRC-HTTP-11, SRC-SEC-3: nothing the host sent or raised appears in a ``Failed``."""
    request = ApiRequest("GET", f"https://{host}/x/1", "depsdev")
    assume(tag.lower() not in request.url.lower())
    assume(tag.lower() not in " ".join(WARNING_CODES).lower())
    handler = _scenario_handler(mode, tag, before, after, hdr, status)
    config = make_config()

    async def scenario() -> FetchResult:
        transport = httpx.MockTransport(handler)
        async with gateway_for(transport, config, FakeClock(), seed) as gateway:
            async with asyncio.timeout(20):
                return await gateway.fetch(request)

    result = asyncio.run(scenario())

    assert isinstance(result, Failed), result
    fields = [str(getattr(result, f.name)) for f in dataclasses.fields(result)]
    for text in [repr(result), str(result), *fields]:
        assert tag not in text
        assert tag.lower() not in text.lower()
