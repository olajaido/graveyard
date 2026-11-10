"""Token secrecy and untrusted-text tests (SRC-TEST-11, SRC-TEST-12, SRC-SEC-1…4; design §11).

The first half of this module is the gateway half of SRC-TEST-11 (T7.6): a distinctive token
given to ``HttpGateway`` must not appear in any ``Failed`` (``repr``, ``str`` or any field), in
any exception a hostile handler raises, in the ``repr``/``str`` of the gateway or its config, in
log output, or in anything sent to a host other than ``api.github.com``.

The second half (T10.6, from "Session level" below) runs the whole ``SourceSession`` against
adversarial servers: ``fakeweb(adversarial_token=...)`` echoes the token and the received
``Authorization`` header into the free-text fields of every document and into response headers,
puts prompt-injection strings, URLs and control characters there too, and (``hostile_errors``)
answers some requests with errors whose text holds the token. A ``RecordingCache`` wraps the
``MemoryCache`` so cache keys and stored values can be inspected. The assertions:

* SRC-TEST-11: the token and token-shaped strings are in no ``Evidence``, ``SourceWarning``,
  ``ItemError``, cache key or cache value, nor in ``repr``/``str`` of a result or the batch;
* SRC-TEST-12 / SRC-SEC-4 / D11: no response free text (injection markers, URLs from
  descriptions, control characters) is in evidence, notes, warnings or cache values, and the
  only strings an evidence value holds are advisory ids, fixed versions, dates and
  ``github.com/<owner>/<repo>`` names the world really has.

Nothing touches the network. Waiting goes through ``FakeClock``.
"""

from __future__ import annotations

import asyncio
import copy
import dataclasses
import json
import logging
import random
import re
import unicodedata
from collections.abc import AsyncIterator, Callable, Iterator, Mapping, Sequence
from datetime import date, datetime
from typing import Any, Final
from urllib.parse import urlsplit

import httpx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.sources.config import SourcesConfig, Timeouts
from core.sources.facts import is_valid_version
from core.sources.model import (
    EVIDENCE_KEYS,
    SOURCE_NAMES,
    WARNING_CODES,
    BatchResult,
    JsonValue,
    SourceResult,
)
from core.sources.secret import REDACTED, SecretToken, redact
from core.sources.urls import (
    ALLOWED_HOSTS,
    depsdev_version_url,
    github_graphql_url,
    npm_packument_url,
    osv_querybatch_url,
    pypi_json_url,
)
from sources.cache import CacheEntry, MemoryCache, SourceCache
from sources.gateway import GITHUB_HOST, ApiRequest, Failed, FetchResult, HttpGateway, NotFound, Ok
from sources.session import SourceSession
from sources.tests.clock import FakeClock
from sources.tests.fakeweb import INJECTION_STRINGS, FakeWeb, fakeweb
from sources.tests.strategies import PackageSet, package_sets
from sources.tests.transports import Handler, json_response

CONTACT = "ops@example.org"
JSON = "application/json"
GITHUB_REPO_URL = f"https://{GITHUB_HOST}/repos/octocat/hello"
DEPSDEV_URL = "https://api.deps.dev/v3/systems/npm/packages/express"
SMALL_CAP = 1_000

# One opaque token (exact-match redaction) and one shaped like a GitHub token.
OPAQUE_TOKEN: Final = "tokensentinel-9f8e7d6c5b4a3921"
SHAPED_TOKEN: Final = "ghp_" + "Zq3xK9mT" * 5
TOKENS: Final = [OPAQUE_TOKEN, SHAPED_TOKEN]

NON_GITHUB_HOSTS: Final = sorted(ALLOWED_HOSTS - {GITHUB_HOST})

# Token-shaped strings that must be redacted from a URL even when they are not our token.
SHAPED_STRINGS: Final = [
    "ghp_" + "A" * 36,
    "gho_" + "b1" * 15,
    "ghu_" + "C" * 25,
    "ghs_" + "d2" * 20,
    "ghr_" + "E" * 22,
    "github_pat_" + "F_9" * 12,
]


# ---------------------------------------------------------------------- helpers


def make_config(*, max_response_bytes: int | None = None) -> SourcesConfig:
    base = SourcesConfig.default(contact=CONTACT)
    if max_response_bytes is None:
        return base
    hosts = {
        host: dataclasses.replace(policy, max_response_bytes=max_response_bytes)
        for host, policy in base.hosts.items()
    }
    return SourcesConfig(hosts=hosts, contact=CONTACT)


type AnyHandler = Handler


def run(
    handler: AnyHandler,
    requests: Sequence[ApiRequest],
    token: str,
    *,
    config: SourcesConfig | None = None,
) -> tuple[list[FetchResult], HttpGateway]:
    """Fetch each request in order through one gateway holding ``token``."""
    gateway = HttpGateway(
        config or make_config(),
        FakeClock(),
        token=SecretToken(token),
        rng=random.Random(1),
        transport=httpx.MockTransport(handler),
    )

    async def main() -> list[FetchResult]:
        async with gateway:
            return [await gateway.fetch(request) for request in requests]

    return asyncio.run(main()), gateway


def get(url: str = GITHUB_REPO_URL, *, not_found_ok: bool = False) -> ApiRequest:
    return ApiRequest("GET", url, "github", not_found_ok=not_found_ok)


def graphql() -> ApiRequest:
    body: JsonValue = {"query": "{ viewer { login } }"}
    return ApiRequest("POST", github_graphql_url(), "github", body=body)


def texts_of(obj: object) -> list[str]:
    """Every string form of ``obj``: repr, str, format, and repr/str of each dataclass field."""
    out = [repr(obj), str(obj), f"{obj}", f"{obj!s}|{obj!r}"]
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        for fld in dataclasses.fields(obj):
            value = getattr(obj, fld.name)
            out += [repr(value), str(value)]
    return out


def assert_no_token(token: str, *objs: object) -> None:
    """``token`` and anything token-shaped is absent from every string form of ``objs``."""
    for obj in objs:
        for text in texts_of(obj):
            assert token not in text, text
            assert redact(text) == text, text  # no GitHub-token-shaped substring either


def assert_clean_failed(token: str, result: FetchResult) -> Failed:
    assert isinstance(result, Failed), result
    assert result.kind in WARNING_CODES
    assert_no_token(token, result)
    return result


class ChunkStream(httpx.AsyncByteStream):
    """A response body made of ``chunks``, optionally raising ``then`` after the last one."""

    def __init__(self, chunks: Sequence[bytes], then: Exception | None = None) -> None:
        self._chunks = list(chunks)
        self._then = then

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk
        if self._then is not None:
            raise self._then

    async def aclose(self) -> None:
        return None


def raw_token(request: httpx.Request) -> str:
    """The token as the server sees it: the ``Authorization`` header minus ``Bearer``."""
    return request.headers["authorization"].removeprefix("Bearer ")


# ------------------------------------------------------- the gateway does send it


@pytest.mark.parametrize("token", TOKENS)
def test_github_requests_carry_the_token_and_the_client_has_no_default_auth(token: str) -> None:
    """Sanity: the secrecy tests below are not vacuous (SRC-SEC-2)."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={}, headers={"content-type": JSON})

    results, gateway = run(handler, [get(), graphql()], token)

    assert all(isinstance(r, Ok) for r in results)
    assert [r.headers["authorization"] for r in seen] == [f"Bearer {token}"] * 2
    assert gateway._client is None  # closed by the context manager
    # A client built the same way holds no auth or Authorization default.
    probe = HttpGateway(make_config(), FakeClock(), token=SecretToken(token))
    probe_client = probe._ensure_started()
    assert "authorization" not in probe_client.headers
    assert probe_client.auth is None
    assert not probe_client.cookies
    asyncio.run(probe.aclose())


# ------------------------------------------------- repr / str of gateway and config


@pytest.mark.parametrize("token", TOKENS)
def test_repr_and_str_of_gateway_config_and_token_hide_the_token(token: str) -> None:
    secret = SecretToken(token)
    gateway = HttpGateway(make_config(), FakeClock(), token=secret)

    async def started() -> list[object]:
        async with gateway:
            return [repr(gateway), str(gateway), f"{gateway}", repr(vars(gateway))]

    inside = asyncio.run(started())
    objects: list[object] = [
        gateway,
        vars(gateway),
        gateway._config,
        secret,
        *inside,
    ]
    for obj in objects:
        for text in texts_of(obj):
            assert token not in text
    assert repr(secret) == str(secret) == format(secret, ">40") == "SecretToken(***)"
    assert token not in f"{secret!s} {secret!r} {secret:>30}"


# ------------------------------------------ servers that echo the token (api.github.com)


def echo_response(kind: str, request: httpx.Request) -> httpx.Response:
    """A response of ``kind`` that puts the token in the body, headers and ``Location``."""
    token = raw_token(request)
    auth = request.headers["authorization"]
    echo_headers = {
        "x-echo-token": token,
        "x-echo-auth": auth,
        "www-authenticate": f'Bearer realm="{token}"',
        "set-cookie": f"session={token}; Path=/",
        "location": f"https://api.deps.dev/{token}",
    }
    json_ct = {"content-type": JSON}
    echoed_json = f'{{"echo":"{auth}","token":"{token}"}}'.encode()

    if kind.startswith("status-"):
        status = int(kind.removeprefix("status-"))
        return httpx.Response(status, content=echoed_json, headers={**echo_headers, **json_ct})
    if kind == "rate-limit-remaining-0":
        headers = {**echo_headers, **json_ct, "x-ratelimit-remaining": "0"}
        return httpx.Response(403, content=echoed_json, headers=headers)
    if kind == "rate-limit-retry-after":
        headers = {**echo_headers, **json_ct, "retry-after": "2"}
        return httpx.Response(403, content=echoed_json, headers=headers)
    if kind == "rate-limit-retry-after-too-long":
        headers = {**echo_headers, **json_ct, "retry-after": "86400"}
        return httpx.Response(429, content=echoed_json, headers=headers)
    if kind == "wrong-content-type":
        return httpx.Response(
            200, content=echoed_json, headers={**echo_headers, "content-type": "text/html"}
        )
    if kind == "no-content-type":
        return httpx.Response(200, content=echoed_json, headers=echo_headers)
    if kind == "bad-json":
        return httpx.Response(
            200, content=f"<html>{auth}</html>".encode(), headers={**echo_headers, **json_ct}
        )
    if kind == "truncated-json":
        return httpx.Response(
            200, content=f'{{"echo":"{token}","x":['.encode(), headers={**echo_headers, **json_ct}
        )
    if kind == "nan-json":
        return httpx.Response(
            200,
            content=f'{{"echo":"{token}","x":NaN}}'.encode(),
            headers={**echo_headers, **json_ct},
        )
    if kind == "invalid-utf8":
        return httpx.Response(
            200, content=b"\xff\xfe" + token.encode(), headers={**echo_headers, **json_ct}
        )
    if kind == "deep-nesting":
        deep = b"[" * 100_000 + token.encode() + b"]" * 100_000
        return httpx.Response(200, content=deep, headers={**echo_headers, **json_ct})
    if kind == "oversize-declared":
        body = b'"' + token.encode() + b"a" * (2 * SMALL_CAP) + b'"'
        return httpx.Response(200, content=body, headers={**echo_headers, **json_ct})
    if kind == "oversize-streamed":
        stream = ChunkStream([b'"' + token.encode(), b"a" * SMALL_CAP, b"a" * SMALL_CAP, b'"'])
        return httpx.Response(200, headers={**echo_headers, **json_ct}, stream=stream)
    raise AssertionError(f"unknown kind {kind}")


ECHO_KINDS: Final = [
    "status-301",
    "status-302",
    "status-307",
    "status-308",
    "status-400",
    "status-401",
    "status-403",
    "status-404",
    "status-410",
    "status-418",
    "status-422",
    "status-429",
    "status-500",
    "status-502",
    "status-503",
    "status-504",
    "rate-limit-remaining-0",
    "rate-limit-retry-after",
    "rate-limit-retry-after-too-long",
    "wrong-content-type",
    "no-content-type",
    "bad-json",
    "truncated-json",
    "nan-json",
    "invalid-utf8",
    "deep-nesting",
    "oversize-declared",
    "oversize-streamed",
]


@pytest.mark.parametrize("token", TOKENS)
@pytest.mark.parametrize("kind", ECHO_KINDS)
def test_server_echoing_the_token_never_puts_it_in_a_failed(
    token: str, kind: str, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    caplog.set_level(logging.DEBUG)
    seen_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_hosts.append(request.url.host)
        return echo_response(kind, request)

    config = make_config(max_response_bytes=SMALL_CAP)
    # No token in the URL here: httpx logs request URLs itself, and the gateway never puts
    # the token in one. A token in a caller-supplied URL is covered by the URL tests below.
    requests = [get(), graphql(), get(not_found_ok=True)]
    results, gateway = run(handler, requests, token, config=config)

    for result in results:
        if isinstance(result, Failed):
            assert_clean_failed(token, result)
        else:  # a 404 allowed as NotFound still carries a url that must be clean
            assert isinstance(result, NotFound | Ok), result
            assert token not in result.url
    assert any(isinstance(r, Failed) for r in results)
    assert set(seen_hosts) == {GITHUB_HOST}  # a Location never steers a request elsewhere
    assert_no_token(token, gateway)
    assert token not in caplog.text
    captured = capsys.readouterr()
    assert token not in captured.out + captured.err


@pytest.mark.parametrize("token", TOKENS)
def test_cookie_set_by_github_is_not_sent_to_other_hosts(token: str) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        headers = {"content-type": JSON}
        if request.url.host == GITHUB_HOST:
            headers["set-cookie"] = f"session={raw_token(request)}; Path=/"
        return httpx.Response(200, json={}, headers=headers)

    requests = [get(), get(DEPSDEV_URL), get(), get("https://api.osv.dev/v1/vulns/GHSA-aaaa")]
    run(handler, requests, token)

    for request in seen:
        if request.url.host != GITHUB_HOST:
            assert "cookie" not in request.headers
            assert "authorization" not in request.headers
    assert [r.url.host for r in seen].count(GITHUB_HOST) == 2


# --------------------------------------------------------- hostile handlers that raise


def make_exceptions() -> dict[str, Callable[[str, httpx.Request], BaseException]]:
    class Hostile(Exception):
        def __init__(self, message: str) -> None:
            super().__init__(message)
            self.message = message

        def __str__(self) -> str:
            return self.message

        def __repr__(self) -> str:
            return f"Hostile({self.message!r})"

    return {
        "Exception": lambda m, r: Exception(m),
        "RuntimeError": lambda m, r: RuntimeError(m),
        "ValueError": lambda m, r: ValueError(m),
        "KeyError": lambda m, r: KeyError(m),
        "OSError": lambda m, r: OSError(m),
        "TimeoutError": lambda m, r: TimeoutError(m),
        "RecursionError": lambda m, r: RecursionError(m),
        "ExceptionGroup": lambda m, r: ExceptionGroup("group", [ValueError(m)]),
        "Hostile": lambda m, r: Hostile(m),
        "chained": lambda m, r: _chained(m),
        "httpx.HTTPError": lambda m, r: httpx.HTTPError(m),
        "httpx.ConnectError": lambda m, r: httpx.ConnectError(m, request=r),
        "httpx.ConnectTimeout": lambda m, r: httpx.ConnectTimeout(m, request=r),
        "httpx.ReadTimeout": lambda m, r: httpx.ReadTimeout(m, request=r),
        "httpx.ReadError": lambda m, r: httpx.ReadError(m, request=r),
        "httpx.RemoteProtocolError": lambda m, r: httpx.RemoteProtocolError(m, request=r),
        "httpx.UnsupportedProtocol": lambda m, r: httpx.UnsupportedProtocol(m, request=r),
        "httpx.DecodingError": lambda m, r: httpx.DecodingError(m, request=r),
        "httpx.TooManyRedirects": lambda m, r: httpx.TooManyRedirects(m, request=r),
    }


def _chained(message: str) -> Exception:
    try:
        raise ValueError(message)
    except ValueError as inner:
        outer = RuntimeError("wrapper")
        outer.__cause__ = inner
        outer.add_note(message)
        return outer


EXCEPTIONS: Final = make_exceptions()


@pytest.mark.parametrize("token", TOKENS)
@pytest.mark.parametrize("name", sorted(EXCEPTIONS))
@pytest.mark.parametrize("is_async", [False, True])
def test_hostile_handler_raising_the_authorization_header_yields_a_clean_failed(
    token: str, name: str, is_async: bool, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    make = EXCEPTIONS[name]

    def sync_handler(request: httpx.Request) -> httpx.Response:
        auth = request.headers["authorization"]
        raise make(f"boom, headers were Authorization: {auth}", request)

    async def async_handler(request: httpx.Request) -> httpx.Response:
        return sync_handler(request)

    handler: AnyHandler = async_handler if is_async else sync_handler
    results, gateway = run(handler, [get(), graphql(), get(f"{GITHUB_REPO_URL}?q={token}")], token)

    assert len(results) == 3  # fetch returned; nothing propagated
    for result in results:
        assert_clean_failed(token, result)
    assert_no_token(token, gateway)
    assert token not in caplog.text


@pytest.mark.parametrize("token", TOKENS)
@pytest.mark.parametrize("name", ["Exception", "httpx.ReadError", "httpx.ReadTimeout", "Hostile"])
def test_body_stream_raising_the_token_yields_a_clean_failed(token: str, name: str) -> None:
    make = EXCEPTIONS[name]

    def handler(request: httpx.Request) -> httpx.Response:
        error = make(f"stream broke: {request.headers['authorization']}", request)
        assert isinstance(error, Exception)
        stream = ChunkStream([b'{"a":'], then=error)
        return httpx.Response(200, headers={"content-type": JSON}, stream=stream)

    results, gateway = run(handler, [get(), graphql()], token)

    for result in results:
        assert_clean_failed(token, result)
    assert_no_token(token, gateway)


# --------------------------------------------- the token goes to api.github.com only


def echo_request_handler(seen: list[httpx.Request]) -> AnyHandler:
    """Records every request and echoes what the client sent back in the body."""

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        echoed = {
            "headers": dict(request.headers),
            "url": str(request.url),
            "body": request.content.decode("utf-8", errors="replace"),
        }
        return httpx.Response(200, json=echoed, headers={"content-type": JSON})

    return handler


@pytest.mark.parametrize("token", TOKENS)
@pytest.mark.parametrize("host", NON_GITHUB_HOSTS)
def test_requests_to_other_hosts_never_carry_the_token(token: str, host: str) -> None:
    seen: list[httpx.Request] = []
    body: JsonValue = {"query": "x", "packages": ["a", "b"]}
    requests = [
        ApiRequest("GET", f"https://{host}/a/b?x=1", "depsdev"),
        ApiRequest("GET", f"https://{host}/a/b", "depsdev", accept="application/x+json"),
        ApiRequest("POST", f"https://{host}/a/b", "osv", body=body),
    ]
    # Interleave with GitHub requests on the same gateway so connection or header state
    # that leaked between hosts would show up.
    mixed = [get(), requests[0], graphql(), requests[1], get(), requests[2]]

    results, _gateway = run(echo_request_handler(seen), mixed, token)

    assert all(isinstance(r, Ok) for r in results), results
    other = [r for r in seen if r.url.host == host]
    assert len(other) == 3
    for request in other:
        assert "authorization" not in request.headers
        assert "cookie" not in request.headers
        assert token not in str(request.url)
        assert token not in request.content.decode("utf-8", errors="replace")
        for name, value in request.headers.items():
            assert token not in name and token not in value, (name, value)
    # What the other hosts were told came back in the body; it must be token-free too.
    for result in results:
        assert isinstance(result, Ok)
        if isinstance(result.data, dict) and result.data["url"].startswith(f"https://{host}/"):
            assert token not in repr(result.data)
    for request in seen:
        if request.url.host == GITHUB_HOST:
            assert request.headers["authorization"] == f"Bearer {token}"


@pytest.mark.parametrize("token", TOKENS)
@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_github_redirect_to_another_host_is_not_followed(token: str, status: int) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        location = "https://api.deps.dev/leak"
        return httpx.Response(status, headers={"location": location})

    results, _gateway = run(handler, [get()], token)

    failed = assert_clean_failed(token, results[0])
    assert (failed.kind, failed.status) == ("REDIRECT_REFUSED", status)
    assert [r.url.host for r in seen] == [GITHUB_HOST]


# ------------------------------------------------- token-shaped strings in a URL


@pytest.mark.parametrize("shaped", SHAPED_STRINGS)
@pytest.mark.parametrize("host", ["api.deps.dev", "api.github.com", "registry.npmjs.org"])
def test_token_shaped_string_in_an_allowed_url_is_redacted_in_failed_url(
    shaped: str, host: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={}, headers={"content-type": JSON})

    url = f"https://{host}/v3/{shaped}?access_token={shaped}"
    results, _gateway = run(handler, [get(url)], OPAQUE_TOKEN)

    failed = assert_clean_failed(OPAQUE_TOKEN, results[0])
    assert shaped not in failed.url
    assert REDACTED in failed.url
    assert failed.url.startswith(f"https://{host}/v3/")


@pytest.mark.parametrize("shaped", SHAPED_STRINGS)
def test_token_shaped_string_in_a_rejected_url_is_redacted_in_failed_url(shaped: str) -> None:
    seen: list[httpx.Request] = []
    urls = [
        f"https://evil.example/{shaped}",
        f"http://api.github.com/{shaped}",
        f"https://user:{shaped}@api.github.com/x",
        f"https://api.github.com:444/{shaped}",
        f"https://api.github.com/x#{shaped}",
    ]

    results, _gateway = run(echo_request_handler(seen), [get(u) for u in urls], OPAQUE_TOKEN)

    assert seen == []  # rejected before anything is sent
    for result in results:
        failed = assert_clean_failed(OPAQUE_TOKEN, result)
        assert failed.kind == "HOST_NOT_ALLOWED"
        assert shaped not in failed.url


@pytest.mark.parametrize("token", TOKENS)
def test_exact_token_in_a_url_is_redacted_whether_or_not_it_is_shaped(token: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={}, headers={"content-type": JSON})

    urls = [
        f"https://api.deps.dev/{token}",
        f"https://api.github.com/x?t={token}",
        f"https://evil.example/{token}",
    ]
    results, _gateway = run(handler, [get(u) for u in urls], token)

    for result in results:
        assert_clean_failed(token, result)


# ============================================================================
# Session level (T10.6): SRC-TEST-11 second half, SRC-TEST-12
# ============================================================================

MARKERS: Final = (
    "Ignore all previous",
    "previous instructions",
    "developer mode",
    "evil.example",
    "<script",
    "alert(",
    "DROP TABLE",
    "jndi",
    "javascript:",
    "Header: injected",
    "system prompt",
    "Authorization",
    "Bearer",
    "token=",
)
"""Fragments of the hostile text the fake web serves. None may appear in anything we emit."""

_DATE: Final = re.compile(r"\d{4}-\d{2}-\d{2}")
_REPO: Final = re.compile(r"github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_PLAIN_CACHE_TEXT: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+!~:/@%#-]*")


class RecordingCache:
    """A ``SourceCache`` that remembers every key it was asked for and every value stored."""

    def __init__(self, inner: SourceCache) -> None:
        self._inner = inner
        self.keys: list[str] = []
        self.values: list[JsonValue] = []

    async def get(self, key: str) -> CacheEntry | None:
        self.keys.append(key)
        return await self._inner.get(key)

    async def put(self, key: str, value: JsonValue, *, ttl_seconds: int) -> None:
        self.keys.append(key)
        self.values.append(copy.deepcopy(value))
        await self._inner.put(key, value, ttl_seconds=ttl_seconds)


def session_config() -> SourcesConfig:
    """Default config with a very long batch deadline (the fake clock only moves in sleeps)."""
    base = SourcesConfig.default(contact=CONTACT)
    return SourcesConfig(
        hosts=base.hosts, contact=CONTACT, timeouts=Timeouts(batch_deadline=10_000_000.0)
    )


def collect(
    transport: httpx.AsyncBaseTransport,
    requests: Sequence[tuple[Any, Any]],
    token: str,
    cache: RecordingCache | None = None,
) -> tuple[BatchResult, RecordingCache]:
    """Run one ``collect`` on a fresh session whose cache is a ``RecordingCache``."""
    clock = FakeClock()
    recording = cache or RecordingCache(MemoryCache(clock))

    async def main() -> BatchResult:
        async with SourceSession(
            session_config(),
            token=SecretToken(token),
            cache=recording,
            transport=transport,
            clock=clock,
            rng=random.Random(3),
        ) as session:
            return await session.collect(requests)

    return asyncio.run(main()), recording


def strings_in(obj: object) -> Iterator[str]:
    """Every string reachable from ``obj``: values and mapping keys, dataclass fields, dates."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, date | datetime):
        yield obj.isoformat()
    elif dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        for fld in dataclasses.fields(obj):
            yield from strings_in(getattr(obj, fld.name))
    elif isinstance(obj, Mapping):
        for key, value in obj.items():
            yield from strings_in(key)
            yield from strings_in(value)
    elif isinstance(obj, list | tuple | set | frozenset):
        for item in obj:
            yield from strings_in(item)


def assert_clean_text(text: str, token: str) -> None:
    """No token, no token shape, no hostile fragment and no control character in ``text``."""
    assert token not in text, text
    assert redact(text) == text, text
    for marker in MARKERS:
        assert marker not in text, (marker, text)
    for injected in INJECTION_STRINGS:
        assert injected not in text, text
    for char in text:
        assert unicodedata.category(char) not in {"Cc", "Cf", "Zl", "Zp"}, repr(text)


def assert_evidence_strings_allowed(result: SourceResult, ids: set[str], repos: set[str]) -> None:
    """Evidence values hold only what SRC-SEC-4 allows.

    Advisory ids the world really has, fixed-version strings that match the version pattern,
    dates, and ``github.com/<owner>/<repo>`` names the world really has. Every URL is an
    allow-listed https URL.
    """
    for key, evidence in result.evidence.items():
        if key == "s7_advisories" and isinstance(evidence.value, list):
            for entry in evidence.value:
                assert isinstance(entry, dict)
                assert set(entry) <= {"id", "has_fix", "published_at", "fixed_versions"}, entry
                assert entry["id"] in ids, entry
                published = entry.get("published_at")
                assert published is None or _DATE.fullmatch(str(published)), entry
                fixed = entry.get("fixed_versions") or []
                assert isinstance(fixed, list)
                assert all(isinstance(v, str) and is_valid_version(v) for v in fixed), entry
        else:
            for text in strings_in(evidence.value):
                allowed = _DATE.fullmatch(text) is not None or (
                    _REPO.fullmatch(text) is not None and text.lower() in repos
                )
                assert allowed, (key, text)
        for url in (evidence.source_url, *evidence.extra_source_urls):
            if url is not None:
                parts = urlsplit(url)
                assert parts.scheme == "https" and parts.hostname in ALLOWED_HOSTS, url


def assert_nothing_leaked(
    batch: BatchResult,
    cache: RecordingCache,
    token: str,
    *,
    web: FakeWeb | None = None,
    extra_ids: frozenset[str] = frozenset(),
) -> None:
    """The whole of SRC-TEST-11 (results and cache) and SRC-TEST-12 for one batch."""
    # repr / str of the batch and of every result and its parts
    assert_no_token(token, batch, batch.stats)
    for result in batch.results:
        assert_no_token(token, result, result.signals, result.error, *result.warnings)
        for evidence in result.evidence.values():
            assert_no_token(token, evidence)
        for warning in result.warnings:
            assert warning.code in WARNING_CODES and warning.source in SOURCE_NAMES
            assert len(warning.detail) <= 200
    # every string a result holds: evidence, notes, warnings, item errors, URLs, versions
    for text in strings_in(batch.results):
        assert_clean_text(text, token)
    # the cache: keys and stored values
    assert cache.keys, "the run never touched the cache; the test would be vacuous"
    for key in cache.keys:
        assert_clean_text(key, token)
        assert not any(ch.isspace() for ch in key), key
    for value in cache.values:
        for text in strings_in(value):
            assert_clean_text(text, token)
            assert _PLAIN_CACHE_TEXT.fullmatch(text), text
    if web is not None:
        ids = {vuln.id for vuln in web.vulns} | extra_ids
        repos = {f"github.com/{s.lower()}" for repo in web.repos for s in repo.spellings}
        for result in batch.results:
            assert_evidence_strings_allowed(result, ids, repos)
    for result in batch.results:
        if result.signals is not None:
            assert tuple(result.evidence) == EVIDENCE_KEYS


def comparable(result: SourceResult) -> tuple[object, ...]:
    """A result without ``fetched_at`` (it follows the fake clock, not the content)."""
    evidence = {
        key: (e.value, e.source_url, e.extra_source_urls, e.note)
        for key, e in result.evidence.items()
    }
    return (
        result.signals,
        evidence,
        result.warnings,
        result.repo,
        result.repo_via,
        result.resolved_version,
        result.latest_version,
    )


def spying(web: FakeWeb, seen: list[str]) -> httpx.MockTransport:
    """The web's transport, remembering the text (body and headers) of every response."""

    async def handler(request: httpx.Request) -> httpx.Response:
        response = await web.handler(request)
        seen.append(response.text + " ".join(f"{k}: {v}" for k, v in response.headers.items()))
        return response

    return httpx.MockTransport(handler)


@pytest.mark.property
@settings(deadline=None)
@given(
    ps=package_sets(),
    token=st.sampled_from(TOKENS),
    malformed=st.booleans(),
    hostile=st.booleans(),
)
def test_adversarial_server_leaks_nothing_through_the_session(
    ps: PackageSet, token: str, malformed: bool, hostile: bool
) -> None:
    """**Validates: Requirements SRC-TEST-11, SRC-TEST-12, SRC-SEC-3, SRC-SEC-4**"""
    web = ps.web(adversarial_token=token, malformed=malformed, hostile_errors=hostile)
    batch, cache = collect(web.transport, web.inputs, token)

    assert len(batch.results) == len(web.inputs)
    assert_nothing_leaked(batch, cache, token, web=web)
    assert web.leaked_auth == []  # the Authorization header went to api.github.com only
    assert all(r.signals is not None for r in batch.results)
    if not malformed and not hostile:
        # The hostile additions are neutral: they never change a field a parser reads.
        reference_web = ps.web()
        reference, _ = collect(reference_web.transport, reference_web.inputs, token)
        assert [comparable(r) for r in batch.results] == [comparable(r) for r in reference.results]


@pytest.mark.parametrize("token", TOKENS)
@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_adversarial_documents_are_served_and_none_of_it_survives(token: str, seed: int) -> None:
    """The hostile text is really served (non-vacuity) and the results equal a clean run's."""
    web = fakeweb(seed, packages=8, adversarial_token=token)
    bodies: list[str] = []
    batch, cache = collect(spying(web, bodies), web.inputs, token)

    assert any(token in body for body in bodies)  # echoed into documents and headers
    assert any("Ignore all previous instructions" in body for body in bodies)
    assert any("Authorization: " in body for body in bodies)
    assert any("evil.example" in body for body in bodies)
    assert any("\\u202e" in body or "\\x1b" in body or "\\u0000" in body for body in bodies)
    assert_nothing_leaked(batch, cache, token, web=web)

    clean_web = fakeweb(seed, packages=8)
    clean, _ = collect(clean_web.transport, clean_web.inputs, token)
    assert [comparable(r) for r in batch.results] == [comparable(r) for r in clean.results]
    assert any(r.signals and r.signals.s7_advisories for r in batch.results)


@pytest.mark.parametrize("token", TOKENS)
@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_errors_that_contain_the_token_leak_nothing(token: str, seed: int) -> None:
    """``hostile_errors``: connect errors and 500s whose text, headers and JSON hold the token."""
    web = fakeweb(seed, packages=8, adversarial_token=token, hostile_errors=True, malformed=True)
    bodies: list[str] = []
    batch, cache = collect(spying(web, bodies), web.inputs, token)

    assert any(f"Bad credentials: {token}" in body for body in bodies)  # a hostile 500 was served
    assert sum(batch.stats.failures.values()) > 0  # and some request really failed
    codes = {w.code for r in batch.results for w in r.warnings}
    assert codes & {"CONNECT_ERROR", "HTTP_STATUS"}
    assert_nothing_leaked(batch, cache, token, web=web)
    assert web.leaked_auth == []


# ---- hand-built servers: a reserved GitHub path, a hostile deprecation message


class Scripted:
    """A handler over a table of ``url -> JSON`` documents.

    Unknown URLs answer 404. OSV ``querybatch`` answers "no advisories" for each query; the
    GraphQL endpoint answers every alias with ``null`` (repository not found) and records
    the request bodies in ``graphql``.
    """

    def __init__(self, documents: Mapping[str, JsonValue]) -> None:
        self.documents = documents
        self.urls: list[str] = []
        self.graphql: list[Any] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.urls.append(url)
        if request.method == "POST" and url == osv_querybatch_url():
            queries = json.loads(request.content)["queries"]
            return json_response({"results": [{} for _ in queries]})
        if request.method == "POST" and url == github_graphql_url():
            body = json.loads(request.content)
            self.graphql.append(body)
            aliases = {f"r{i}": None for i in range(len(body["variables"]) // 2)}
            return json_response({"data": aliases})
        document = self.documents.get(url)
        return json_response(document) if document is not None else json_response({}, 404)


def pypi_document(project_urls: JsonValue, home_page: JsonValue = None) -> JsonValue:
    return {
        "info": {
            "name": "sponsored",
            "version": "1.0.0",
            "summary": INJECTION_STRINGS[0],
            "project_urls": project_urls,
            "home_page": home_page,
        },
        "urls": [{"upload_time_iso_8601": "2025-01-02T03:04:05Z"}],
        "releases": {"1.0.0": [{"upload_time_iso_8601": "2025-01-02T03:04:05Z"}]},
    }


SPONSOR_URLS: Final = [
    "https://github.com/sponsors/octocat",
    "https://github.com/orgs/acme",
    "https://github.com/topics/python",
    "https://github.com/marketplace/some-action",
    "https://github.com/settings/profile",
    "http://github.com/Sponsors/octocat/",
]


@pytest.mark.parametrize("token", TOKENS)
@pytest.mark.parametrize("reserved", SPONSOR_URLS)
def test_reserved_github_paths_in_project_urls_are_not_taken_for_a_repository(
    token: str, reserved: str
) -> None:
    """D10: ``github.com/sponsors/<user>`` parses as owner/name but is not a repository."""
    documents: dict[str, JsonValue] = {
        pypi_json_url("sponsored"): pypi_document(
            {
                "Funding": reserved,
                "Homepage": f"https://evil.example/{INJECTION_STRINGS[0]}",
                "Docs": INJECTION_STRINGS[1],
            },
            home_page=reserved,
        )
    }
    web = Scripted(documents)
    batch, cache = collect(
        httpx.MockTransport(web), [("pkg:pypi/sponsored@1.0.0", date(2026, 11, 3))], token
    )

    [result] = batch.results
    assert result.signals is not None
    assert (result.repo, result.repo_via) == (None, None)
    assert result.signals.s3_last_push_at is None and result.signals.s5_committers is None
    assert result.evidence["s3_last_push_at"].note == "no GitHub repo resolved"
    assert web.graphql == []  # nothing was asked of GitHub
    assert not any("sponsors" in url.lower() or "orgs" in url for url in web.urls)
    assert_nothing_leaked(batch, cache, token)


@pytest.mark.parametrize("token", TOKENS)
def test_a_real_repository_wins_over_a_reserved_path_and_only_it_is_queried(token: str) -> None:
    documents: dict[str, JsonValue] = {
        pypi_json_url("sponsored"): pypi_document(
            {
                "Funding": "https://github.com/sponsors/octocat",
                "Source": "https://github.com/Acme/Real-Repo",
                "Homepage": "https://github.com/orgs/acme",
            }
        )
    }
    web = Scripted(documents)
    batch, cache = collect(
        httpx.MockTransport(web), [("pkg:pypi/sponsored@1.0.0", date(2026, 11, 3))], token
    )

    [result] = batch.results
    assert (result.repo, result.repo_via) == ("github.com/Acme/Real-Repo", "project_urls")
    [query] = web.graphql
    assert query["variables"]["o0"] == "Acme" and query["variables"]["n0"] == "Real-Repo"
    assert "sponsors" not in str(query) and "octocat" not in str(query)
    assert_nothing_leaked(batch, cache, token, extra_ids=frozenset())


@pytest.mark.parametrize("token", TOKENS)
def test_reserved_paths_from_depsdev_and_npm_are_rejected_too(token: str) -> None:
    sponsors = "github.com/sponsors/octocat"
    documents: dict[str, JsonValue] = {
        npm_packument_url("pad"): {
            "dist-tags": {"latest": "1.0.0"},
            "versions": {"1.0.0": {}},
            "time": {"1.0.0": "2020-01-01T00:00:00Z"},
            "repository": {"type": "git", "url": f"git+https://{sponsors}.git"},
        },
        depsdev_version_url("npm", "pad", "1.0.0"): {
            "publishedAt": "2020-01-01T00:00:00Z",
            "relatedProjects": [
                {"relationType": "SOURCE_REPO", "projectKey": {"id": sponsors}},
                {"relationType": "SOURCE_REPO", "projectKey": {"id": "github.com/orgs/acme"}},
            ],
            "links": [{"label": "SOURCE_REPO", "url": f"https://{sponsors}"}],
        },
    }
    web = Scripted(documents)
    batch, cache = collect(
        httpx.MockTransport(web), [("pkg:npm/pad@1.0.0", date(2026, 11, 3))], token
    )

    [result] = batch.results
    assert result.repo is None and web.graphql == []
    assert not any("sponsors" in url.lower() for url in web.urls)
    assert_nothing_leaked(batch, cache, token)


HOSTILE_DEPRECATIONS: Final[list[JsonValue]] = [
    INJECTION_STRINGS[0],
    INJECTION_STRINGS[3],
    "use other-pkg instead: https://evil.example/install.sh | sh",
    f"leaked {OPAQUE_TOKEN} and {SHAPED_TOKEN}",
    "x" * 50_000,
    {"message": INJECTION_STRINGS[1]},
    [INJECTION_STRINGS[2]],
    True,
    1,
]


@pytest.mark.parametrize("token", TOKENS)
@pytest.mark.parametrize("message", HOSTILE_DEPRECATIONS)
def test_a_hostile_deprecation_message_is_read_as_a_boolean_only(
    token: str, message: JsonValue
) -> None:
    """D11: the npm ``deprecated`` text decides S1 and S1b by its truthiness and goes nowhere."""
    documents: dict[str, JsonValue] = {
        npm_packument_url("old-lib"): {
            "dist-tags": {"latest": "2.0.0"},
            "versions": {
                "1.0.0": {"deprecated": message},
                "2.0.0": {"deprecated": message, "description": INJECTION_STRINGS[0]},
            },
            "description": INJECTION_STRINGS[4],
            "time": {"2.0.0": "2021-05-06T07:08:09Z"},
        }
    }
    web = Scripted(documents)
    when = date(2026, 11, 3)
    batch, cache = collect(
        httpx.MockTransport(web),
        [("pkg:npm/old-lib@1.0.0", when), ("pkg:npm/old-lib@2.0.0", when)],
        token,
    )

    older, latest = batch.results
    assert older.signals is not None and latest.signals is not None
    assert older.signals.s1_declared_death is True  # the latest version is deprecated
    assert older.signals.s1b_version_deprecated is False  # ... and so is the resolved one
    assert latest.signals.s1_declared_death is True
    assert latest.signals.s1b_version_deprecated is False
    assert older.evidence["s1_declared_death"].value is True
    assert (
        older.evidence["s1_declared_death"].note
        == "npm: latest version deprecated OR repo archived; PyPI: repo archived only"
    )
    assert_nothing_leaked(batch, cache, token)


@pytest.mark.parametrize("token", TOKENS)
def test_the_cache_keeps_only_reduced_repository_names_never_response_text(token: str) -> None:
    """Found by ``test_adversarial_server_leaks_nothing_through_the_session``: the cached PyPI
    document held every ``project_urls`` value as a raw repo candidate, so hostile text (and an
    echoed token) was persisted. The cache now stores ``github.com/<owner>/<repo>`` only, and
    a second session served from it resolves the same repository without asking PyPI."""
    documents: dict[str, JsonValue] = {
        pypi_json_url("sponsored"): pypi_document(
            {
                "Source": "git+https://github.com/Acme/Real-Repo.git",
                "Docs": INJECTION_STRINGS[0],
                "Echo": f"Authorization: Bearer {token}",
                "Chat": f"https://chat.example/?t={token}",
                "Control": "https://github.com/Acme/Other\x1b[31m",
            },
            home_page=f"token={token}",
        )
    }
    requests = [("pkg:pypi/sponsored@1.0.0", date(2026, 11, 3))]
    first_web = Scripted(documents)
    first, cache = collect(httpx.MockTransport(first_web), requests, token)

    stored: list[JsonValue] = []
    for item in cache.values:
        data = item.get("data") if isinstance(item, dict) else None
        if isinstance(data, dict) and "repo_candidates" in data:
            stored.append(data["repo_candidates"])
    assert stored, "the PyPI fact was never cached; the test would be vacuous"
    assert all(candidates == ["github.com/Acme/Real-Repo"] for candidates in stored)
    assert_nothing_leaked(first, cache, token)

    second_web = Scripted(documents)
    second, _ = collect(httpx.MockTransport(second_web), requests, token, cache)
    assert pypi_json_url("sponsored") not in second_web.urls  # served from the cache
    assert [comparable(r) for r in second.results] == [comparable(r) for r in first.results]
    assert second.results[0].repo == "github.com/Acme/Real-Repo"
