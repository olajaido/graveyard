"""Unit tests for ``HttpGateway`` on ``FakeClock`` and ``httpx.MockTransport`` (T7.4).

Covers SRC-HTTP-1…11, SRC-RATE-1/2/4 and SRC-TEST-10. Nothing touches the network. Waiting
goes through ``FakeClock``; the one exception is the slow-drip test, which uses a real 50 ms
per-request deadline because ``asyncio.timeout`` runs on event-loop time.
"""

from __future__ import annotations

import asyncio
import dataclasses
import gzip
import random
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import Any

import httpx
import pytest

from core.sources.config import RetryPolicy, SourcesConfig, Timeouts
from core.sources.model import WARNING_CODES, JsonValue
from core.sources.secret import SecretToken
from core.sources.urls import ALLOWED_HOSTS
from sources.gateway import (
    GATEWAY_VERSION,
    ApiRequest,
    Failed,
    FetchResult,
    HttpGateway,
    NotFound,
    Ok,
)
from sources.tests.clock import FakeClock
from sources.tests.transports import (
    CountingHandler,
    Handler,
    counting_handler,
    json_response,
    slow_body_response,
)

CONTACT = "ops@example.org"
TOKEN = "tok-secret-0123456789"
JSON = "application/json"
URL = "https://api.deps.dev/v3/systems/npm/packages/express"
URL_B = "https://api.deps.dev/v3/systems/npm/packages/left-pad"
GITHUB_URL = "https://api.github.com/graphql"
OSV_URL = "https://api.osv.dev/v1/querybatch"
PYPISTATS_URL = "https://pypistats.org/api/packages/requests/recent"


# ---------------------------------------------------------------------- helpers


def make_config(
    *,
    timeouts: Timeouts | None = None,
    retry: RetryPolicy | None = None,
    max_response_bytes: int | None = None,
) -> SourcesConfig:
    """The default config, with the response cap of every host replaced when given."""
    base = SourcesConfig.default(contact=CONTACT)
    hosts = dict(base.hosts)
    if max_response_bytes is not None:
        hosts = {h: replace(p, max_response_bytes=max_response_bytes) for h, p in hosts.items()}
    return SourcesConfig(
        hosts=hosts,
        contact=CONTACT,
        timeouts=timeouts or Timeouts(),
        retry=retry or RetryPolicy(),
    )


CONFIG = make_config()


def get(url: str = URL, *, not_found_ok: bool = False, accept: str = JSON) -> ApiRequest:
    return ApiRequest("GET", url, "depsdev", accept=accept, not_found_ok=not_found_ok)


type Step = Callable[[httpx.Request], httpx.Response]


def reply(
    status: int = 200,
    data: object = None,
    *,
    retry_after: str | None = None,
    content_type: str | None = JSON,
    headers: dict[str, str] | None = None,
) -> Step:
    body = {} if data is None else data
    return lambda _request: json_response(
        body, status, content_type=content_type, retry_after=retry_after, headers=headers
    )


def raw(
    body: bytes,
    *,
    status: int = 200,
    content_type: str | None = JSON,
    headers: dict[str, str] | None = None,
) -> Step:
    out = dict(headers or {})
    if content_type is not None:
        out["content-type"] = content_type
    return lambda _request: httpx.Response(status, content=body, headers=out)


def raises(exc: type[httpx.TransportError]) -> Step:
    def step(request: httpx.Request) -> httpx.Response:
        raise exc("injected", request=request)

    return step


class Script:
    """A handler that plays ``steps`` in order and repeats the last one when they run out."""

    def __init__(self, *steps: Step) -> None:
        self._steps = steps
        self.calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        step = self._steps[min(self.calls, len(self._steps) - 1)]
        self.calls += 1
        return step(request)


class TrackingStream(httpx.AsyncByteStream):
    """A response body that counts how many chunks the reader pulled."""

    def __init__(self, chunks: Sequence[bytes]) -> None:
        self._chunks = list(chunks)
        self.yielded = 0

    async def __aiter__(self) -> Any:
        for chunk in self._chunks:
            self.yielded += 1
            yield chunk

    async def aclose(self) -> None:
        return None


class EdgeRng(random.Random):
    """``uniform`` returns the upper (``high``) or lower bound, so the schedule is exact."""

    def __init__(self, *, high: bool) -> None:
        super().__init__(0)
        self._high = high

    def uniform(self, a: float, b: float) -> float:
        return b if self._high else a


@dataclass
class Run[T]:
    value: T
    clock: FakeClock
    seen: CountingHandler


def run_gateway[T](
    handler: Handler,
    scenario: Callable[[HttpGateway, FakeClock], Awaitable[T]],
    *,
    config: SourcesConfig = CONFIG,
    token: SecretToken | None = None,
    rng: random.Random | None = None,
    clock: FakeClock | None = None,
) -> Run[T]:
    clock = clock or FakeClock()
    seen = counting_handler(handler)
    gateway = HttpGateway(
        config,
        clock,
        token=token,
        rng=rng or random.Random(1),
        transport=httpx.MockTransport(seen),
    )

    async def main() -> T:
        async with gateway:
            return await scenario(gateway, clock)

    return Run(asyncio.run(main()), clock, seen)


def fetch_one(
    handler: Handler,
    request: ApiRequest | None = None,
    *,
    config: SourcesConfig = CONFIG,
    token: SecretToken | None = None,
    rng: random.Random | None = None,
) -> Run[FetchResult]:
    target = request or get()

    async def scenario(gateway: HttpGateway, _clock: FakeClock) -> FetchResult:
        return await gateway.fetch(target)

    return run_gateway(handler, scenario, config=config, token=token, rng=rng)


def assert_failed(result: FetchResult, kind: str, status: int | None = None) -> Failed:
    assert isinstance(result, Failed), result
    assert (result.kind, result.status) == (kind, status)
    return result


def assert_ok(result: FetchResult) -> Ok:
    assert isinstance(result, Ok), result
    return result


# --------------------------------------------------------------------- success


def test_ok_parses_json_and_stamps_the_injected_clock() -> None:
    run = fetch_one(Script(reply(200, {"a": [1, 2]})))
    ok = assert_ok(run.value)
    assert ok.data == {"a": [1, 2]}
    assert ok.url == URL
    assert ok.fetched_at == run.clock.now()
    assert run.seen.total == 1
    assert run.clock.sleeps == []


def test_get_sends_user_agent_with_contact_and_the_requested_accept() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return json_response({})

    request = get(accept="application/vnd.npm.install-v1+json")
    assert_ok(fetch_one(handler, request).value)
    assert requests[0].headers["user-agent"] == f"graveyard/{GATEWAY_VERSION} (+{CONTACT})"
    assert requests[0].headers["accept"] == "application/vnd.npm.install-v1+json"
    assert requests[0].content == b""


def test_post_body_is_compact_json_with_sorted_keys() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return json_response({})

    body: JsonValue = {"b": [2, 1], "a": {"z": 1, "y": None}}
    request = ApiRequest("POST", OSV_URL, "osv", body=body)
    assert_ok(fetch_one(handler, request).value)
    assert requests[0].content == b'{"a":{"y":null,"z":1},"b":[2,1]}'
    assert requests[0].headers["content-type"] == JSON


# ------------------------------------------------------------------- allow-list


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/x",
        "https://api.deps.dev.evil.example/x",
        "http://api.deps.dev/v3/x",
        "ftp://api.deps.dev/x",
        "https://api.deps.dev:8443/x",
        "https://api.deps.dev:443/x",
        "https://user:pw@api.deps.dev/x",
        "https://api.deps.dev@evil.example/x",
        "https://api.deps.dev/x#fragment",
        "https://api.deps.dev/x y",
        "https://api.deps.dev\\@evil.example/x",
        "/relative/path",
        "",
    ],
)
def test_url_outside_the_allow_list_is_rejected_without_a_request(url: str) -> None:
    run = fetch_one(Script(reply()), get(url))
    assert_failed(run.value, "HOST_NOT_ALLOWED", None)
    assert run.seen.total == 0
    assert run.clock.sleeps == []


@pytest.mark.parametrize("host", sorted(ALLOWED_HOSTS))
def test_every_allow_listed_https_host_is_requested(host: str) -> None:
    run = fetch_one(Script(reply()), get(f"https://{host}/x"))
    assert_ok(run.value)
    assert run.seen.hosts == {host: 1}


# --------------------------------------------------------------------- redirects


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_redirect_is_refused_and_location_is_never_requested(status: int) -> None:
    location = "https://api.deps.dev/v3/LOCATION-TARGET"
    run = fetch_one(
        Script(lambda _r: httpx.Response(status, headers={"location": location})),
    )
    failed = assert_failed(run.value, "REDIRECT_REFUSED", status)
    assert run.seen.total == 1
    assert run.seen.urls == [URL]
    assert "LOCATION-TARGET" not in repr(failed)
    assert run.clock.sleeps == []  # not retried


# ------------------------------------------------------------------------- 404


def test_404_is_not_found_when_the_request_allows_it() -> None:
    run = fetch_one(Script(reply(404)), get(not_found_ok=True))
    assert isinstance(run.value, NotFound), run.value
    assert run.value.url == URL
    assert run.value.fetched_at == run.clock.now()
    assert run.seen.total == 1


def test_404_is_a_plain_failure_when_the_request_does_not_allow_it() -> None:
    run = fetch_one(Script(reply(404)))
    assert_failed(run.value, "HTTP_STATUS", 404)
    assert run.seen.total == 1


@pytest.mark.parametrize("status", [400, 401, 403, 404, 405, 410, 422])
def test_other_4xx_fail_at_once_without_a_retry(status: int) -> None:
    run = fetch_one(Script(reply(status)))
    assert_failed(run.value, "HTTP_STATUS", status)
    assert run.seen.total == 1
    assert run.clock.sleeps == []


def test_a_404_that_is_allowed_only_applies_to_404() -> None:
    run = fetch_one(Script(reply(410)), get(not_found_ok=True))
    assert_failed(run.value, "HTTP_STATUS", 410)


# -------------------------------------------------------------------- size caps


def _quoted(size: int) -> bytes:
    """A JSON string literal of exactly ``size`` bytes."""
    return b'"' + b"a" * (size - 2) + b'"'


def test_body_exactly_at_the_cap_is_accepted_and_one_byte_more_is_not() -> None:
    config = make_config(max_response_bytes=100)
    assert_ok(fetch_one(Script(raw(_quoted(100))), config=config).value)
    assert_failed(
        fetch_one(Script(raw(_quoted(101))), config=config).value, "RESPONSE_TOO_LARGE", 200
    )


def test_declared_content_length_over_the_cap_fails_before_reading() -> None:
    stream = TrackingStream([b'"x"'])
    config = make_config(max_response_bytes=100)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": JSON, "content-length": "5000"}, stream=stream
        )

    run = fetch_one(handler, config=config)
    assert_failed(run.value, "RESPONSE_TOO_LARGE", 200)
    assert stream.yielded == 0
    assert run.seen.total == 1  # a too-large body is not retried


def test_streamed_body_over_the_cap_stops_reading_as_soon_as_it_is_exceeded() -> None:
    chunks = [b'"', b"a" * 60, b"a" * 60, b"a" * 60, b'"']
    stream = TrackingStream(chunks)
    config = make_config(max_response_bytes=100)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": JSON}, stream=stream)

    run = fetch_one(handler, config=config)
    assert_failed(run.value, "RESPONSE_TOO_LARGE", 200)
    assert stream.yielded == 3  # 1 + 60 + 60 bytes crosses 100; the rest is never pulled


def test_gzip_body_that_expands_past_the_cap_is_counted_after_decoding() -> None:
    cap = 1_000
    compressed = gzip.compress(_quoted(100_000))
    assert len(compressed) < cap  # passes the Content-Length check on its own
    stream = TrackingStream([compressed])

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "content-type": JSON,
                "content-encoding": "gzip",
                "content-length": str(len(compressed)),
            },
            stream=stream,
        )

    run = fetch_one(handler, config=make_config(max_response_bytes=cap))
    assert_failed(run.value, "RESPONSE_TOO_LARGE", 200)


def test_gzip_body_under_the_cap_is_decoded_and_parsed() -> None:
    compressed = gzip.compress(b'{"gz":true}')

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": JSON, "content-encoding": "gzip"},
            stream=TrackingStream([compressed]),
        )

    assert assert_ok(fetch_one(handler).value).data == {"gz": True}


# ------------------------------------------------------------------ defensive JSON


@pytest.mark.parametrize(
    "body",
    [
        b"NaN",
        b"Infinity",
        b"-Infinity",
        b'{"a": NaN}',
        b"[1, Infinity]",
        b"[" * 100_000 + b"]" * 100_000,
        b'"\xff\xfe"',
        b"\xc3\x28",
        b"",
        b'{"truncated": [1, 2',
        b"<html>nope</html>",
    ],
    ids=[
        "nan",
        "infinity",
        "negative-infinity",
        "nan-in-object",
        "infinity-in-array",
        "nested-100000",
        "invalid-utf8-in-string",
        "invalid-utf8-start",
        "empty",
        "truncated",
        "html",
    ],
)
def test_malformed_or_unsafe_json_is_invalid_json(body: bytes) -> None:
    run = fetch_one(Script(raw(body)))
    assert_failed(run.value, "INVALID_JSON", 200)
    assert run.seen.total == 1  # not retried


@pytest.mark.parametrize("body", [b"null", b"[]", b"7", b'"text"', b"true", b"{}"])
def test_any_top_level_json_type_is_returned_for_the_caller_to_check(body: bytes) -> None:
    assert_ok(fetch_one(Script(raw(body))).value)


# ------------------------------------------------------------------ content type


@pytest.mark.parametrize(
    "content_type", ["text/html", "text/plain", "application/xml", "application/jsonp", None]
)
def test_wrong_or_missing_content_type_is_refused(content_type: str | None) -> None:
    run = fetch_one(Script(raw(b"{}", content_type=content_type)))
    assert_failed(run.value, "BAD_CONTENT_TYPE", 200)
    assert run.seen.total == 1


@pytest.mark.parametrize(
    "content_type",
    [
        "application/json",
        "application/json; charset=utf-8",
        "APPLICATION/JSON",
        "application/vnd.npm.install-v1+json",
        "application/vnd.api+json",
        "application/hal+json; charset=utf-8",
    ],
)
def test_json_media_types_are_accepted(content_type: str) -> None:
    run = fetch_one(Script(raw(b'{"ok":true}', content_type=content_type)))
    assert assert_ok(run.value).data == {"ok": True}


# ------------------------------------------------------------------------ retry


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_retryable_status_is_retried_and_a_later_success_is_returned(status: int) -> None:
    script = Script(reply(status), reply(200, {"after": "retry"}))
    run = fetch_one(script)
    assert assert_ok(run.value).data == {"after": "retry"}
    assert script.calls == 2
    assert len(run.clock.sleeps) == 1


@pytest.mark.parametrize("exc", [httpx.ReadTimeout, httpx.ConnectError])
def test_transport_errors_are_retried_and_a_later_success_is_returned(
    exc: type[httpx.TransportError],
) -> None:
    script = Script(raises(exc), raises(exc), reply(200, {"fine": 1}))
    run = fetch_one(script)
    assert assert_ok(run.value).data == {"fine": 1}
    assert script.calls == 3
    assert len(run.clock.sleeps) == 2


@pytest.mark.parametrize(
    ("step", "kind", "status"),
    [
        (reply(503), "HTTP_STATUS", 503),
        (reply(500), "HTTP_STATUS", 500),
        (reply(429), "RATE_LIMITED", 429),
        (raises(httpx.ReadTimeout), "TIMEOUT", None),
        (raises(httpx.ConnectError), "CONNECT_ERROR", None),
    ],
    ids=["503", "500", "429", "read-timeout", "connect-error"],
)
def test_gives_up_after_max_attempts_without_sleeping_after_the_last(
    step: Step, kind: str, status: int | None
) -> None:
    config = make_config(retry=RetryPolicy(max_attempts=3))
    script = Script(step)
    run = fetch_one(script, config=config)
    failed = assert_failed(run.value, kind, status)
    assert failed.url == URL
    assert script.calls == 3
    assert len(run.clock.sleeps) == 2


def test_default_policy_makes_four_attempts() -> None:
    script = Script(reply(503))
    run = fetch_one(script)
    assert_failed(run.value, "HTTP_STATUS", 503)
    assert script.calls == 4


def test_max_attempts_one_never_retries() -> None:
    script = Script(reply(503))
    run = fetch_one(script, config=make_config(retry=RetryPolicy(max_attempts=1)))
    assert_failed(run.value, "HTTP_STATUS", 503)
    assert script.calls == 1
    assert run.clock.sleeps == []


# ---------------------------------------------------------------------- backoff


def test_backoff_ceiling_doubles_up_to_the_cap() -> None:
    retry = RetryPolicy(max_attempts=7, base=1.0, cap=4.0)
    run = fetch_one(Script(reply(503)), config=make_config(retry=retry), rng=EdgeRng(high=True))
    assert_failed(run.value, "HTTP_STATUS", 503)
    assert run.clock.sleeps == [1.0, 2.0, 4.0, 4.0, 4.0, 4.0]


def test_backoff_floor_is_zero() -> None:
    retry = RetryPolicy(max_attempts=4, base=1.0, cap=4.0)
    run = fetch_one(Script(reply(503)), config=make_config(retry=retry), rng=EdgeRng(high=False))
    assert run.clock.sleeps == [0.0, 0.0, 0.0]


def test_backoff_uses_the_injected_rng_within_the_ceiling() -> None:
    retry = RetryPolicy(max_attempts=5, base=0.5, cap=1.5)
    run = fetch_one(Script(reply(500)), config=make_config(retry=retry), rng=random.Random(7))
    twin = random.Random(7)
    expected = [twin.uniform(0.0, min(1.5, 0.5 * 2**n)) for n in range(4)]
    assert run.clock.sleeps == expected
    for n, slept in enumerate(run.clock.sleeps):
        assert 0.0 <= slept <= min(1.5, 0.5 * 2**n)


# ------------------------------------------------------------------ Retry-After


def test_retry_after_seconds_is_honoured_instead_of_the_backoff() -> None:
    script = Script(reply(429, retry_after="5"), reply(200, {"ok": 1}))
    run = fetch_one(script)
    assert_ok(run.value)
    assert run.clock.sleeps == [5.0]


def test_retry_after_http_date_is_honoured() -> None:
    date = format_datetime(FakeClock().now() + timedelta(seconds=7), usegmt=True)
    script = Script(reply(429, retry_after=date), reply(200))
    run = fetch_one(script)
    assert_ok(run.value)
    assert run.clock.sleeps == [7.0]


def test_retry_after_date_in_the_past_waits_zero() -> None:
    date = format_datetime(FakeClock().now() - timedelta(hours=1), usegmt=True)
    run = fetch_one(Script(reply(429, retry_after=date), reply(200)))
    assert_ok(run.value)
    assert run.clock.sleeps == [0.0]


def test_retry_after_on_a_5xx_is_honoured_too() -> None:
    run = fetch_one(Script(reply(503, retry_after="3"), reply(200)))
    assert_ok(run.value)
    assert run.clock.sleeps == [3.0]


def test_retry_after_exactly_at_the_cap_is_honoured() -> None:
    run = fetch_one(Script(reply(429, retry_after="20"), reply(200)))
    assert_ok(run.value)
    assert run.clock.sleeps == [20.0]


def test_unparsable_retry_after_falls_back_to_the_backoff() -> None:
    run = fetch_one(Script(reply(429, retry_after="soon"), reply(200)), rng=EdgeRng(high=True))
    assert_ok(run.value)
    assert run.clock.sleeps == [RetryPolicy().base]


_PAST_CAP_DATE = format_datetime(FakeClock().now() + timedelta(hours=1), usegmt=True)


@pytest.mark.parametrize(
    ("status", "retry_after", "timeouts"),
    [
        (429, "21", Timeouts()),
        (503, "21", Timeouts()),
        (429, "99999999999999999999", Timeouts()),
        (429, _PAST_CAP_DATE, Timeouts()),
        (429, "15", Timeouts(batch_deadline=10.0)),  # within the cap, past the deadline
        (503, "15", Timeouts(batch_deadline=10.0)),
    ],
    ids=["over-cap", "over-cap-5xx", "huge", "date-over-cap", "over-deadline", "over-deadline-5xx"],
)
def test_retry_after_over_the_cap_or_the_deadline_is_rate_limited_without_sleeping(
    status: int, retry_after: str, timeouts: Timeouts
) -> None:
    script = Script(reply(status, retry_after=retry_after), reply(200))
    run = fetch_one(script, config=make_config(timeouts=timeouts))
    assert_failed(run.value, "RATE_LIMITED", status)
    assert script.calls == 1
    assert run.clock.sleeps == []


# ------------------------------------------------------------ sibling penalty


def test_a_429_delays_a_sibling_task_on_the_same_host() -> None:
    clock = FakeClock()
    t0 = clock.monotonic()
    sibling_times: list[float] = []
    first_call = {"a": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/express"):
            if first_call["a"]:
                first_call["a"] = False
                return json_response({}, 429, retry_after="10")
            return json_response({"a": 1})
        sibling_times.append(clock.monotonic())
        return json_response({"b": 1})

    async def scenario(gateway: HttpGateway, clk: FakeClock) -> list[FetchResult]:
        async def sibling() -> FetchResult:
            # Start the sibling only once the 429 has been seen and the wait has begun.
            for _ in range(1_000):
                if clk.sleeps:
                    break
                await asyncio.sleep(0)
            return await gateway.fetch(get(URL_B))

        return list(await asyncio.gather(gateway.fetch(get(URL)), sibling()))

    run = run_gateway(handler, scenario, clock=clock)
    for result in run.value:
        assert_ok(result)
    assert sibling_times == [t0 + 10.0]


# --------------------------------------------------------------------- deadlines


def test_requests_after_the_batch_deadline_fail_fast_without_a_request() -> None:
    config = make_config(timeouts=Timeouts(batch_deadline=100.0))

    async def scenario(gateway: HttpGateway, clock: FakeClock) -> tuple[FetchResult, FetchResult]:
        before = await gateway.fetch(get())
        clock.advance(101.0)
        return before, await gateway.fetch(get(URL_B))

    run = run_gateway(Script(reply(200)), scenario, config=config)
    before, after = run.value
    assert_ok(before)
    assert_failed(after, "DEADLINE_EXCEEDED", None)
    assert run.seen.total == 1


def test_start_batch_restarts_the_batch_deadline_from_now() -> None:
    config = make_config(timeouts=Timeouts(batch_deadline=100.0))

    async def scenario(gateway: HttpGateway, clock: FakeClock) -> tuple[FetchResult, FetchResult]:
        clock.advance(101.0)
        expired = await gateway.fetch(get())
        gateway.start_batch()
        return expired, await gateway.fetch(get(URL_B))

    run = run_gateway(Script(reply(200)), scenario, config=config)
    expired, renewed = run.value
    assert_failed(expired, "DEADLINE_EXCEEDED", None)
    assert_ok(renewed)
    assert run.seen.total == 1


def test_a_task_that_waits_for_a_slot_past_the_deadline_fails_without_a_request() -> None:
    # pypistats spaces starts 3 s apart; the batch deadline is 2 s, so the second start
    # is assigned a time that is already past the deadline.
    config = make_config(timeouts=Timeouts(batch_deadline=2.0))

    async def scenario(gateway: HttpGateway, _clock: FakeClock) -> list[FetchResult]:
        request = ApiRequest("GET", PYPISTATS_URL, "pypistats")
        return list(await asyncio.gather(gateway.fetch(request), gateway.fetch(request)))

    run = run_gateway(Script(reply(200)), scenario, config=config)
    kinds = sorted(type(r).__name__ for r in run.value)
    assert kinds == ["Failed", "Ok"]
    failed = next(r for r in run.value if isinstance(r, Failed))
    assert_failed(failed, "DEADLINE_EXCEEDED", None)
    assert run.seen.total == 1


def test_backoff_that_would_pass_the_deadline_gives_up_instead_of_sleeping() -> None:
    config = make_config(timeouts=Timeouts(batch_deadline=1.0))
    script = Script(reply(503))
    run = fetch_one(script, config=config, rng=EdgeRng(high=True))
    assert_failed(run.value, "HTTP_STATUS", 503)
    assert script.calls == 2
    assert run.clock.sleeps == [0.5]  # 1.0 would not fit in the remaining 0.5 s


# ------------------------------------------------------ real per-request deadline


def test_slow_drip_body_hits_the_real_50ms_request_deadline_and_frees_the_slot() -> None:
    config = make_config(
        timeouts=Timeouts(request_deadline=0.05), retry=RetryPolicy(max_attempts=1)
    )
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            # 22 chunks 20 ms apart: about 440 ms in all, far past the 50 ms deadline, while
            # the 15 s read timeout never fires because bytes keep arriving.
            return slow_body_response([b'"'] + [b"a"] * 20 + [b'"'], 0.02)
        return json_response({"after": "slow"})

    async def scenario(gateway: HttpGateway, _clock: FakeClock) -> tuple[FetchResult, FetchResult]:
        # api.github.com is serial (one slot), so a leaked slot would hang the second fetch.
        request = ApiRequest("GET", GITHUB_URL, "github")
        first = await gateway.fetch(request)
        async with asyncio.timeout(5):
            return first, await gateway.fetch(request)

    run = run_gateway(handler, scenario, config=config)
    first, second = run.value
    assert_failed(first, "TIMEOUT", None)
    assert assert_ok(second).data == {"after": "slow"}


def test_slow_drip_body_is_retried_as_a_timeout() -> None:
    config = make_config(
        timeouts=Timeouts(request_deadline=0.05), retry=RetryPolicy(max_attempts=2)
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return slow_body_response([b'"'] + [b"a"] * 20 + [b'"'], 0.02)

    run = fetch_one(handler, config=config)
    assert_failed(run.value, "TIMEOUT", None)
    assert run.seen.total == 2
    assert len(run.clock.sleeps) == 1


# ------------------------------------------------------------------ Authorization


def test_authorization_is_sent_to_api_github_com_only() -> None:
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen[request.url.host] = request.headers.get("authorization")
        return json_response({})

    async def scenario(gateway: HttpGateway, _clock: FakeClock) -> list[FetchResult]:
        # One gateway and one client for every host, so a default header would show up.
        return [
            await gateway.fetch(ApiRequest("GET", f"https://{host}/x", "internal"))
            for host in sorted(ALLOWED_HOSTS)
        ]

    run = run_gateway(handler, scenario, token=SecretToken(TOKEN))
    for result in run.value:
        assert_ok(result)
    assert set(seen) == ALLOWED_HOSTS
    assert seen["api.github.com"] == f"Bearer {TOKEN}"
    assert {host: value for host, value in seen.items() if host != "api.github.com"} == {
        host: None for host in ALLOWED_HOSTS - {"api.github.com"}
    }


def test_no_token_means_no_authorization_header_even_for_github() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return json_response({})

    assert_ok(fetch_one(handler, get(GITHUB_URL)).value)
    assert "authorization" not in requests[0].headers


def test_authorization_is_added_again_on_a_github_retry() -> None:
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("authorization"))
        return json_response({}, 503 if len(seen) == 1 else 200)

    assert_ok(fetch_one(handler, get(GITHUB_URL), token=SecretToken(TOKEN)).value)
    assert seen == [f"Bearer {TOKEN}"] * 2


def test_github_rate_limit_403_is_retried_but_other_hosts_403_is_not() -> None:
    limited = reply(403, headers={"x-ratelimit-remaining": "0"}, retry_after="3")
    github = fetch_one(Script(limited, reply(200)), get(GITHUB_URL))
    assert_ok(github.value)
    assert github.clock.sleeps == [3.0]
    other = fetch_one(Script(limited, reply(200)))
    assert_failed(other.value, "HTTP_STATUS", 403)
    assert other.seen.total == 1


# ------------------------------------------------------------ environment, cookies


def test_client_ignores_the_environment_and_never_follows_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # httpx skips proxy and certificate variables when a transport is injected, so an
    # answered request would not prove trust_env is off. Inspect the client the gateway
    # builds instead, with hostile variables set.
    for name in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy", "HTTP_PROXY"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")
    monkeypatch.setenv("SSL_CERT_FILE", "/nonexistent/ca-bundle.pem")
    created: list[tuple[httpx.AsyncClient, dict[str, Any]]] = []

    class SpyClient(httpx.AsyncClient):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            created.append((self, kwargs))

    monkeypatch.setattr(httpx, "AsyncClient", SpyClient)
    run = fetch_one(Script(reply(200, {"direct": True})))
    assert assert_ok(run.value).data == {"direct": True}
    assert len(created) == 1
    client, kwargs = created[0]
    assert client.trust_env is False
    assert client.follow_redirects is False
    assert client.auth is None
    assert "authorization" not in client.headers
    assert kwargs.get("verify", True) is True  # TLS verification stays on


def _cookie_handler(seen: list[str | None]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("cookie"))
        return json_response({}, headers={"set-cookie": "sid=abc123; Path=/"})

    return handler


def test_cookie_control_a_plain_client_would_send_the_cookie_back() -> None:
    # Guards the next test against passing vacuously: this mock server does set a cookie
    # that a client with a live cookie jar sends on its next request.
    seen: list[str | None] = []

    async def main() -> None:
        transport = httpx.MockTransport(_cookie_handler(seen))
        async with httpx.AsyncClient(transport=transport) as client:
            await client.get(URL)
            await client.get(URL)

    asyncio.run(main())
    assert seen[0] is None
    assert seen[1] is not None
    assert "sid=abc123" in seen[1]


def test_cookie_from_set_cookie_is_not_sent_on_the_next_request() -> None:
    seen: list[str | None] = []

    async def scenario(gateway: HttpGateway, _clock: FakeClock) -> list[FetchResult]:
        return [await gateway.fetch(get()), await gateway.fetch(get(URL_B))]

    run = run_gateway(_cookie_handler(seen), scenario)
    for result in run.value:
        assert_ok(result)
    assert seen == [None, None]


def test_cookie_set_by_a_failed_attempt_is_not_sent_on_the_retry() -> None:
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("cookie"))
        return json_response({}, 503, headers={"set-cookie": "sid=abc123; Path=/"})

    run = fetch_one(handler)
    assert_failed(run.value, "HTTP_STATUS", 503)
    assert seen == [None] * 4


# ------------------------------------------------------------ Failed carries no text


def _marked(
    status: int,
    *,
    content_type: str = JSON,
    body: bytes = b'{"m":"BODY-MARKER"}',
    extra: dict[str, str] | None = None,
) -> Step:
    headers = {"x-leak": "HEADER-MARKER", "www-authenticate": "Bearer realm=HEADER-MARKER"}
    return raw(body, status=status, content_type=content_type, headers={**headers, **(extra or {})})


def _raising(exc: Exception) -> Step:
    def step(_request: httpx.Request) -> httpx.Response:
        raise exc

    return step


@pytest.mark.parametrize(
    ("step", "kind", "status"),
    [
        (_marked(500), "HTTP_STATUS", 500),
        (_marked(400), "HTTP_STATUS", 400),
        (_marked(200, content_type="text/html"), "BAD_CONTENT_TYPE", 200),
        (_marked(200, body=b'{"BODY-MARKER": nope}'), "INVALID_JSON", 200),
        (
            _marked(302, extra={"location": "https://api.deps.dev/HEADER-MARKER"}),
            "REDIRECT_REFUSED",
            302,
        ),
        (_marked(429, extra={"retry-after": "7"}), "RATE_LIMITED", 429),
        (_raising(httpx.ConnectError("EXC-MARKER")), "CONNECT_ERROR", None),
        (_raising(httpx.ReadTimeout("EXC-MARKER")), "TIMEOUT", None),
        (_raising(RuntimeError("EXC-MARKER")), "INTERNAL_ERROR", None),
    ],
    ids=[
        "500",
        "400",
        "bad-content-type",
        "invalid-json",
        "redirect",
        "429",
        "connect-error",
        "timeout",
        "unexpected-exception",
    ],
)
def test_failed_carries_no_body_header_or_exception_text(
    step: Step, kind: str, status: int | None
) -> None:
    failed = assert_failed(fetch_one(Script(step)).value, kind, status)
    assert kind in WARNING_CODES
    assert [f.name for f in dataclasses.fields(Failed)] == ["kind", "url", "status"]
    assert failed.url == URL
    for marker in ("BODY-MARKER", "HEADER-MARKER", "EXC-MARKER"):
        assert marker not in repr(failed)


# --------------------------------------------------------------------- never raises


def test_an_unexpected_exception_in_the_transport_becomes_internal_error() -> None:
    run = fetch_one(Script(_raising(RuntimeError("kaboom"))))
    assert_failed(run.value, "INTERNAL_ERROR", None)
    assert run.seen.total == 1


def test_cancellation_is_not_swallowed() -> None:
    started = asyncio.Event()

    async def handler(_request: httpx.Request) -> httpx.Response:
        started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def scenario(gateway: HttpGateway, _clock: FakeClock) -> None:
        task = asyncio.create_task(gateway.fetch(get()))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    run_gateway(handler, scenario)


def test_aclose_is_idempotent_and_a_closed_gateway_can_be_used_again() -> None:
    async def main() -> tuple[FetchResult, FetchResult]:
        gateway = HttpGateway(
            CONFIG,
            FakeClock(),
            transport=httpx.MockTransport(lambda _r: json_response({"n": 1})),
        )
        first = await gateway.fetch(get())
        await gateway.aclose()
        await gateway.aclose()
        second = await gateway.fetch(get())
        await gateway.aclose()
        return first, second

    first, second = asyncio.run(main())
    assert_ok(first)
    assert_ok(second)


# ------------------------------------------------------------ userinfo (SRC-SEC-3)

CREDENTIAL_URLS = [
    "https://user:password@api.deps.dev/x",
    "https://user@api.deps.dev/x",
    "https://:password@api.deps.dev/x",
    "https://api.deps.dev@evil.example/x",
    "https://user:password@evil.example/x",
    "user:password@evil.example/x",
    "https://u:pass/word@evil.example/x",
    "https://u:pass?word@evil.example/x",
    "https://a%40b:pass%40word@evil.example/x",
    "https://u:p ass\nword@evil.example/x",
]
CREDENTIAL_WORDS = ("password", "pass", "word")


@pytest.mark.parametrize("url", CREDENTIAL_URLS)
def test_rejected_url_is_stored_without_its_credentials(url: str) -> None:
    run = fetch_one(Script(reply()), get(url))
    failed = assert_failed(run.value, "HOST_NOT_ALLOWED", None)
    assert run.seen.total == 0
    assert "@" not in failed.url
    for word in CREDENTIAL_WORDS:
        assert word not in failed.url
    assert "user" not in failed.url.replace("evil.example", "")


def test_a_long_credential_is_stripped_before_the_url_is_cut_short() -> None:
    # Truncating first would leave the start of the password visible with its "@" cut off.
    url = "https://user:" + "S3CRET" * 100 + "@evil.example/path"
    failed = assert_failed(fetch_one(Script(reply()), get(url)).value, "HOST_NOT_ALLOWED", None)
    assert "S3CRET" not in failed.url
    assert failed.url == "https://evil.example/path"


def test_a_long_credential_with_a_long_tail_is_stripped_and_then_bounded() -> None:
    url = "https://user:" + "S3CRET" * 100 + "@evil.example/" + "p" * 1000
    failed = assert_failed(fetch_one(Script(reply()), get(url)).value, "HOST_NOT_ALLOWED", None)
    assert "S3CRET" not in failed.url and "user" not in failed.url
    assert failed.url.startswith("https://evil.example/ppp")
    assert len(failed.url) <= 600


def test_the_token_is_still_redacted_when_it_sits_in_the_userinfo() -> None:
    url = f"https://{TOKEN}@evil.example/x"
    run = fetch_one(Script(reply()), get(url), token=SecretToken(TOKEN))
    failed = assert_failed(run.value, "HOST_NOT_ALLOWED", None)
    assert TOKEN not in failed.url and "@" not in failed.url


@pytest.mark.parametrize(
    "build",
    [
        lambda url, now: Failed("HTTP_STATUS", url, 500),
        lambda url, now: Ok({}, url, now),
        lambda url, now: NotFound(url, now),
    ],
    ids=["Failed", "Ok", "NotFound"],
)
def test_result_types_strip_userinfo_whatever_built_them(
    build: Callable[[str, Any], Any],
) -> None:
    result = build("https://user:password@api.deps.dev/x", datetime(2026, 11, 3, tzinfo=UTC))
    assert result.url == "https://api.deps.dev/x"
