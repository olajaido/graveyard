"""The one HTTP gateway (design §4.1, §4.4; SRC-HTTP-1…11, SRC-RATE-1/2/4, SRC-SEC-1…3).

Every network request the source clients make goes through ``HttpGateway.fetch`` (SRC-HTTP-1).
It checks the URL against the fixed allow-list before anything is sent, applies the per-host
limiter, retries transient failures with full-jitter backoff, honours ``Retry-After``, enforces
a per-request deadline and a batch deadline, caps the decoded response size, and parses the body
as strict JSON.

``fetch`` never raises except ``asyncio.CancelledError`` (SRC-HTTP-11). Its result is one of
``Ok``, ``NotFound`` or ``Failed``. ``Failed`` carries a ``WARNING_CODES`` member, the URL and
the HTTP status. It never carries a body, a header value or exception text, and every string
it produces passes ``redact()`` (SRC-SEC-3).

All waiting and the batch deadline use the injected ``Clock`` (SRC-RATE-4); jitter comes from an
injectable ``random.Random``. The per-request deadline uses ``asyncio.timeout`` (event-loop
time) so a slow-drip body cannot hold a slot.

The GitHub token is revealed in exactly one place, ``_headers``, and only for ``api.github.com``
(SRC-SEC-2). The client is built with no default auth, ``trust_env=False``,
``follow_redirects=False`` and TLS verification on, and its cookie jar is cleared after every
exchange (SRC-HTTP-4).
"""

from __future__ import annotations

import asyncio
import json
import random
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from types import TracebackType
from typing import Final, Literal
from urllib.parse import urlsplit

import httpx

from core.sources.clock import Clock
from core.sources.config import SourcesConfig
from core.sources.model import WARNING_CODES, JsonValue
from core.sources.secret import SecretToken, redact
from core.sources.urls import ALLOWED_HOSTS, strip_userinfo
from sources.limiter import HostLimiter

GATEWAY_VERSION: Final = "0.1.0"
"""Version string in the ``User-Agent`` (``graveyard/<version> (+<contact>)``)."""

GITHUB_HOST: Final = "api.github.com"

_RETRYABLE_STATUSES: Final = frozenset({429, 500, 502, 503, 504})
_JSON_MEDIA_TYPE: Final = re.compile(
    r"application/(?:json|vnd\.npm\.install-v1\+json|[^/\s;,]+\+json)"
)
_MAX_RETRY_AFTER_DIGITS: Final = 9
_MAX_REJECTED_URL_CHARS: Final = 200


@dataclass(frozen=True)
class ApiRequest:
    """One request to an allow-listed host (design §4.1).

    ``url`` is built by ``core/sources/urls.py``. ``body`` is for ``POST`` only and is sent as
    compact JSON with sorted keys, so identical queries give identical bytes (SRC-HTTP-10).
    ``not_found_ok`` marks a 404 as meaningful (SRC-HTTP-9).
    """

    method: Literal["GET", "POST"]
    url: str
    source: str  # a SOURCE_NAMES member, for the caller's stats and warnings
    body: JsonValue = None
    accept: str = "application/json"
    not_found_ok: bool = False


@dataclass(frozen=True)
class Ok:
    """A successful response with its parsed JSON body."""

    data: object
    url: str
    fetched_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "url", redact(strip_userinfo(self.url)))


@dataclass(frozen=True)
class NotFound:
    """A 404 for a request that marked 404 as meaningful."""

    url: str
    fetched_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "url", redact(strip_userinfo(self.url)))


@dataclass(frozen=True)
class Failed:
    """A failed request. ``kind`` is a ``WARNING_CODES`` member.

    Carries no response body, header value or exception text (SRC-HTTP-11).
    """

    kind: str
    url: str
    status: int | None

    def __post_init__(self) -> None:
        if self.kind not in WARNING_CODES:
            raise ValueError(f"unknown failure kind: {self.kind!r}")
        object.__setattr__(self, "url", redact(strip_userinfo(self.url)))


type FetchResult = Ok | NotFound | Failed


@dataclass(frozen=True)
class _Retry:
    """A retryable outcome of one attempt (internal)."""

    kind: str  # RATE_LIMITED when throttled, else TIMEOUT / CONNECT_ERROR / HTTP_STATUS
    status: int | None
    retry_after: float | None  # seconds requested by the host, if any
    throttled: bool  # 429, a Retry-After, or a GitHub rate-limit 403


def _reject_constant(_name: str) -> object:
    """``parse_constant`` hook: refuse ``NaN``, ``Infinity`` and ``-Infinity`` (SRC-HTTP-7)."""
    raise ValueError("non-finite JSON constant")


def _parse_retry_after(value: str | None, now: datetime) -> float | None:
    """Return the wait in seconds from a ``Retry-After`` value, or ``None`` if unusable.

    Accepts delta-seconds and HTTP-date forms. A date in the past gives zero.
    """
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if text.isascii() and text.isdigit():
        if len(text) > _MAX_RETRY_AFTER_DIGITS:
            return float(10**_MAX_RETRY_AFTER_DIGITS)
        return float(int(text))
    try:
        when = parsedate_to_datetime(text)
    except (ValueError, TypeError, IndexError, OverflowError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - now).total_seconds())


def _content_length(value: str | None) -> int | None:
    """Return a ``Content-Length`` as an int, or ``None`` if absent or malformed."""
    if value is None:
        return None
    text = value.strip()
    if text.isascii() and text.isdigit():
        return int(text)
    return None


def _is_json_media_type(content_type: str | None) -> bool:
    """True for ``application/json``, ``application/*+json`` and the npm install media type."""
    if content_type is None:
        return False
    media_type = content_type.split(";", 1)[0].strip().lower()
    return _JSON_MEDIA_TYPE.fullmatch(media_type) is not None


class HttpGateway:
    """Async HTTP client for the allow-listed hosts.

    Use as ``async with HttpGateway(...) as gateway`` or call ``aclose()`` when done. The
    underlying client is created on first use, and the batch deadline starts then
    (``config.timeouts.batch_deadline`` seconds on the injected clock's ``monotonic``).

    ``transport`` is for tests (``httpx.MockTransport``). ``rng`` makes the jitter
    reproducible. ``token`` is revealed only when building headers for ``api.github.com``.
    """

    def __init__(
        self,
        config: SourcesConfig,
        clock: Clock,
        *,
        token: SecretToken | None = None,
        rng: random.Random | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config
        self._clock = clock
        self._token = token
        self._rng = rng if rng is not None else random.Random()
        self._transport = transport
        self._limiters = {host: HostLimiter(policy, clock) for host, policy in config.hosts.items()}
        self._user_agent = f"graveyard/{GATEWAY_VERSION} (+{config.contact})"
        self._client: httpx.AsyncClient | None = None
        self._deadline_at = float("inf")

    def __repr__(self) -> str:
        return "HttpGateway(...)"

    async def __aenter__(self) -> HttpGateway:
        self._ensure_started()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying client. Safe to call more than once."""
        client, self._client = self._client, None
        if client is not None:
            await client.aclose()

    def start_batch(self) -> None:
        """Start a new batch: the batch deadline runs from now (SRC-HTTP-5).

        A session that serves several ``collect`` calls calls this at the start of each, so
        one call's deadline does not use up the next one's. Limiters and the client are kept.
        """
        self._ensure_started()
        self._deadline_at = self._clock.monotonic() + self._config.timeouts.batch_deadline

    def _ensure_started(self) -> httpx.AsyncClient:
        """Create the client and start the batch deadline on first use."""
        if self._client is None:
            timeouts = self._config.timeouts
            self._client = httpx.AsyncClient(
                transport=self._transport,
                timeout=httpx.Timeout(
                    connect=timeouts.connect,
                    read=timeouts.read,
                    write=timeouts.write,
                    pool=timeouts.pool,
                ),
                follow_redirects=False,
                trust_env=False,
                auth=None,
            )
            self._deadline_at = self._clock.monotonic() + timeouts.batch_deadline
        return self._client

    # ------------------------------------------------------------------ fetch

    async def fetch(self, request: ApiRequest) -> FetchResult:
        """Perform ``request`` and return ``Ok``, ``NotFound`` or ``Failed``.

        Never raises except ``asyncio.CancelledError`` (SRC-HTTP-11).
        """
        try:
            return await self._fetch(request)
        except Exception:
            return Failed(
                "INTERNAL_ERROR", self._describe_rejected(getattr(request, "url", "")), None
            )

    async def _fetch(self, request: ApiRequest) -> FetchResult:
        url = request.url
        host = self._allowed_host(url)
        if host is None:
            return Failed("HOST_NOT_ALLOWED", self._describe_rejected(url), None)
        if request.method not in ("GET", "POST"):
            return self._failed("INTERNAL_ERROR", url, None)
        content = self._encode_body(request)

        client = self._ensure_started()
        limiter = self._limiters[host]
        retry = self._config.retry
        max_attempts = retry.max_attempts
        for attempt in range(1, max_attempts + 1):
            if self._deadline_passed():
                return self._failed("DEADLINE_EXCEEDED", url, None)
            async with limiter.slot():
                if self._deadline_passed():
                    return self._failed("DEADLINE_EXCEEDED", url, None)
                outcome = await self._once(client, request, host, content)
            if not isinstance(outcome, _Retry):
                return outcome

            if outcome.retry_after is not None:
                wait = outcome.retry_after
            else:
                ceiling = min(retry.cap, retry.base * 2 ** (attempt - 1))
                wait = self._rng.uniform(0.0, ceiling)
            if outcome.throttled:
                limiter.penalise(min(wait, retry.max_retry_after_seconds))
            if attempt == max_attempts:
                return self._failed(outcome.kind, url, outcome.status)
            too_long = outcome.retry_after is not None and wait > retry.max_retry_after_seconds
            if too_long or wait > self._deadline_at - self._clock.monotonic():
                return self._failed(outcome.kind, url, outcome.status)
            await self._clock.sleep(wait)
        return self._failed("INTERNAL_ERROR", url, None)  # unreachable: max_attempts >= 1

    def _deadline_passed(self) -> bool:
        return self._clock.monotonic() >= self._deadline_at

    # ------------------------------------------------------------- validation

    @staticmethod
    def _allowed_host(url: object) -> str | None:
        """Return the host if ``url`` is an allow-listed ``https`` URL, else ``None`` (SRC-HTTP-2).

        Rejects other schemes, hosts and ports, userinfo, fragments, whitespace, control
        characters and backslashes.
        """
        if not isinstance(url, str) or "#" in url or "\\" in url:
            return None
        if any(ch <= " " or ch == "\x7f" for ch in url):
            return None
        try:
            parts = urlsplit(url)
        except ValueError:
            return None
        host = parts.hostname
        if parts.scheme != "https" or host is None or host not in ALLOWED_HOSTS:
            return None
        # netloc equal to the bare host means no userinfo, no port and no odd casing.
        if parts.netloc != host:
            return None
        return host

    def _describe_rejected(self, url: object) -> str:
        """A bounded, control-free, redacted form of a rejected URL for ``Failed.url``.

        The userinfo (``user:password@``) goes first, on the whole text: truncating before
        stripping could cut the text between a credential and its ``@`` and leave it visible.
        """
        text = strip_userinfo(url) if isinstance(url, str) else ""
        text = "".join("?" if ch < " " or ch == "\x7f" else ch for ch in text)
        return redact(text[:_MAX_REJECTED_URL_CHARS], self._token)

    @staticmethod
    def _encode_body(request: ApiRequest) -> bytes | None:
        """Compact JSON with sorted keys for ``POST``; ``None`` for ``GET`` (SRC-HTTP-10)."""
        if request.method != "POST":
            return None
        return json.dumps(
            request.body, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")

    # ---------------------------------------------------------------- results

    def _failed(self, kind: str, url: str, status: int | None) -> Failed:
        """A ``Failed`` for a validated URL (kept whole: bulk URLs can be long)."""
        return Failed(kind, redact(url, self._token), status)

    def _ok(self, data: object, url: str) -> Ok:
        return Ok(data, redact(url, self._token), self._clock.now())

    def _not_found(self, url: str) -> NotFound:
        return NotFound(redact(url, self._token), self._clock.now())

    # ------------------------------------------------------------ one attempt

    def _headers(self, request: ApiRequest, host: str) -> dict[str, str]:
        headers = {"User-Agent": self._user_agent, "Accept": request.accept}
        if request.method == "POST":
            headers["Content-Type"] = "application/json"
        if host == GITHUB_HOST and self._token is not None:
            headers["Authorization"] = f"Bearer {self._token.reveal()}"  # SRC-SEC-2
        return headers

    async def _once(
        self,
        client: httpx.AsyncClient,
        request: ApiRequest,
        host: str,
        content: bytes | None,
    ) -> Ok | NotFound | Failed | _Retry:
        """Send the request once, under the per-request deadline (SRC-HTTP-5)."""
        try:
            async with asyncio.timeout(self._config.timeouts.request_deadline):
                return await self._exchange(client, request, host, content)
        except (TimeoutError, httpx.TimeoutException):
            return _Retry("TIMEOUT", None, None, False)
        except httpx.HTTPError:
            return _Retry("CONNECT_ERROR", None, None, False)
        finally:
            client.cookies.clear()

    async def _exchange(
        self,
        client: httpx.AsyncClient,
        request: ApiRequest,
        host: str,
        content: bytes | None,
    ) -> Ok | NotFound | Failed | _Retry:
        url = request.url
        async with client.stream(
            request.method, url, headers=self._headers(request, host), content=content
        ) as response:
            status = response.status_code
            if 300 <= status < 400:
                return self._failed("REDIRECT_REFUSED", url, status)  # Location never read
            if status == 404 and request.not_found_ok:
                return self._not_found(url)

            retry_after = _parse_retry_after(response.headers.get("retry-after"), self._clock.now())
            github_limited = (
                host == GITHUB_HOST
                and status == 403
                and (
                    response.headers.get("retry-after") is not None
                    or response.headers.get("x-ratelimit-remaining", "").strip() == "0"
                )
            )
            if status in _RETRYABLE_STATUSES or github_limited:
                throttled = status == 429 or retry_after is not None or github_limited
                kind = "RATE_LIMITED" if throttled else "HTTP_STATUS"
                return _Retry(kind, status, retry_after, throttled)
            if not 200 <= status < 300:
                return self._failed("HTTP_STATUS", url, status)

            if not _is_json_media_type(response.headers.get("content-type")):
                return self._failed("BAD_CONTENT_TYPE", url, status)
            cap = self._config.hosts[host].max_response_bytes
            declared = _content_length(response.headers.get("content-length"))
            if declared is not None and declared > cap:
                return self._failed("RESPONSE_TOO_LARGE", url, status)

            # httpx decodes gzip/deflate/brotli here, so the count is of decoded bytes.
            buffer = bytearray()
            async for chunk in response.aiter_bytes():
                buffer += chunk
                if len(buffer) > cap:
                    return self._failed("RESPONSE_TOO_LARGE", url, status)

        try:
            data = json.loads(bytes(buffer).decode("utf-8"), parse_constant=_reject_constant)
        except (ValueError, RecursionError):  # UnicodeDecodeError is a ValueError
            return self._failed("INVALID_JSON", url, status)
        return self._ok(data, url)
