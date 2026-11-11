"""Configuration types for the source clients.

Covers SRC-HTTP-2, -5, -8, SRC-RATE-1, SRC-SEC-5 and SRC-CACHE-5.

Every type is a frozen dataclass that validates itself on construction and raises
``ValueError`` for a programmer error (D3). ``SourcesConfig.hosts`` must have exactly
the keys of ``ALLOWED_HOSTS``, so configuration can tune a host but never add one.
The mapping is stored as a read-only ``MappingProxyType`` (SRC-PURE-3).

``SourcesConfig.default(contact=...)`` returns the design §4.3 fallbacks. A handler
builds the real config from SSM and passes it in; this module reads no environment.
Error messages never include the ``contact`` value.
"""

from __future__ import annotations

import math
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from core.sources.urls import ALLOWED_HOSTS

_MIB: Final = 1024 * 1024


def _require_int(owner: str, name: str, value: object, *, minimum: int) -> None:
    """Raise ``ValueError`` unless ``value`` is an ``int`` (not ``bool``) >= ``minimum``."""
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{owner}.{name} must be an integer >= {minimum}")


def _require_seconds(owner: str, name: str, value: object, *, allow_zero: bool) -> None:
    """Raise ``ValueError`` unless ``value`` is a finite number (not ``bool``), positive or zero."""
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError(f"{owner}.{name} must be a finite number")
    if value < 0 or (value == 0 and not allow_zero):
        bound = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{owner}.{name} must be {bound}")


def _is_clean_contact(value: object) -> bool:
    """True for a string with a non-blank character and no control or line-separator characters."""
    if not isinstance(value, str) or not value.strip():
        return False
    for ch in value:
        category = unicodedata.category(ch)
        if category.startswith("C") or category in ("Zl", "Zp"):
            return False
    return True


@dataclass(frozen=True)
class HostPolicy:
    """Per-host limits: in-flight requests, start spacing and body cap (SRC-RATE-1)."""

    max_concurrency: int
    min_interval_seconds: float
    max_response_bytes: int

    def __post_init__(self) -> None:
        _require_int("HostPolicy", "max_concurrency", self.max_concurrency, minimum=1)
        _require_seconds(
            "HostPolicy", "min_interval_seconds", self.min_interval_seconds, allow_zero=True
        )
        _require_int("HostPolicy", "max_response_bytes", self.max_response_bytes, minimum=1)


@dataclass(frozen=True)
class Timeouts:
    """Phase timeouts, the overall per-request deadline and the batch deadline (SRC-HTTP-5)."""

    connect: float = 5.0
    read: float = 15.0
    write: float = 10.0
    pool: float = 10.0
    request_deadline: float = 30.0
    batch_deadline: float = 240.0

    def __post_init__(self) -> None:
        for name in ("connect", "read", "write", "pool", "request_deadline", "batch_deadline"):
            _require_seconds("Timeouts", name, getattr(self, name), allow_zero=False)


@dataclass(frozen=True)
class RetryPolicy:
    """Retry count, backoff bounds and the longest ``Retry-After`` honoured (SRC-HTTP-8)."""

    max_attempts: int = 4
    base: float = 0.5
    cap: float = 8.0
    max_retry_after_seconds: float = 20.0

    def __post_init__(self) -> None:
        _require_int("RetryPolicy", "max_attempts", self.max_attempts, minimum=1)
        _require_seconds("RetryPolicy", "base", self.base, allow_zero=False)
        _require_seconds("RetryPolicy", "cap", self.cap, allow_zero=False)
        _require_seconds(
            "RetryPolicy", "max_retry_after_seconds", self.max_retry_after_seconds, allow_zero=True
        )


@dataclass(frozen=True)
class CachePolicy:
    """Cache lifetimes in seconds (SRC-CACHE-5): 24 h by default, 7 days for pypistats."""

    default_ttl_seconds: int = 86_400
    pypistats_ttl_seconds: int = 604_800

    def __post_init__(self) -> None:
        _require_int("CachePolicy", "default_ttl_seconds", self.default_ttl_seconds, minimum=1)
        _require_int("CachePolicy", "pypistats_ttl_seconds", self.pypistats_ttl_seconds, minimum=1)


@dataclass(frozen=True)
class Limits:
    """Cost and abuse bounds (SRC-SEC-5, SRC-RATE-3, SRC-GH-5).

    ``github_rate_floor`` is the GraphQL points remaining below which no further
    GitHub request starts (SRC-GH-6). It must be at least 1, like every other limit
    here: with a floor of 0 the check ``remaining < floor`` can never be true, so the
    guard would silently do nothing. Callers who want the least protection set a low
    positive floor.
    """

    max_packages_in_flight: int = 50
    max_packages_per_call: int = 1_000
    max_vuln_details_per_package: int = 200
    max_vuln_details_per_batch: int = 5_000
    max_history_pages: int = 10
    github_rate_floor: int = 200

    def __post_init__(self) -> None:
        for name in (
            "max_packages_in_flight",
            "max_packages_per_call",
            "max_vuln_details_per_package",
            "max_vuln_details_per_batch",
            "max_history_pages",
            "github_rate_floor",
        ):
            _require_int("Limits", name, getattr(self, name), minimum=1)


_DEFAULT_HOSTS: Final[Mapping[str, HostPolicy]] = MappingProxyType(
    {
        "api.deps.dev": HostPolicy(10, 0.0, 8 * _MIB),
        "api.osv.dev": HostPolicy(4, 0.0, 8 * _MIB),
        "registry.npmjs.org": HostPolicy(10, 0.0, 16 * _MIB),
        "pypi.org": HostPolicy(10, 0.0, 16 * _MIB),
        "api.npmjs.org": HostPolicy(5, 0.0, 1 * _MIB),
        # Above 2x the 0.5 s safe_interval_seconds measured on 2026-11-11 (pypistats_probe.json).
        # The host advertises x-ratelimit-limit: 60; read as per minute (the probe does not record
        # the window length), 1.2 s is at most 50 a minute.
        "pypistats.org": HostPolicy(1, 1.2, 1 * _MIB),
        "api.securityscorecards.dev": HostPolicy(4, 0.0, 4 * _MIB),
        "api.github.com": HostPolicy(1, 0.0, 8 * _MIB),
    }
)


@dataclass(frozen=True)
class SourcesConfig:
    """Everything the gateway, clients and session are tuned by.

    ``hosts`` must have exactly the keys of ``ALLOWED_HOSTS``. It is copied into a
    read-only mapping sorted by host, so later changes to the caller's dict do not
    reach the config. ``contact`` goes into the ``User-Agent`` (SRC-HTTP-10) and is
    required: non-blank, with no control characters.
    """

    hosts: Mapping[str, HostPolicy]
    contact: str
    timeouts: Timeouts = Timeouts()
    retry: RetryPolicy = RetryPolicy()
    cache: CachePolicy = CachePolicy()
    limits: Limits = Limits()

    def __post_init__(self) -> None:
        if not _is_clean_contact(self.contact):
            raise ValueError("contact must be a non-blank string without control characters")
        if not isinstance(self.hosts, Mapping):
            raise ValueError("hosts must be a mapping of host name to HostPolicy")
        keys = set(self.hosts)
        if keys != ALLOWED_HOSTS:
            missing = sorted(ALLOWED_HOSTS - keys)
            extra = sorted(str(key) for key in keys - ALLOWED_HOSTS)
            raise ValueError(
                f"hosts must have exactly the allowed hosts (missing: {missing}, extra: {extra})"
            )
        for host, policy in self.hosts.items():
            if not isinstance(policy, HostPolicy):
                raise ValueError(f"hosts[{host!r}] must be a HostPolicy")
        for name, expected in (
            ("timeouts", Timeouts),
            ("retry", RetryPolicy),
            ("cache", CachePolicy),
            ("limits", Limits),
        ):
            if not isinstance(getattr(self, name), expected):
                raise ValueError(f"{name} must be a {expected.__name__}")
        object.__setattr__(
            self, "hosts", MappingProxyType({host: self.hosts[host] for host in sorted(self.hosts)})
        )

    @classmethod
    def default(cls, *, contact: str) -> SourcesConfig:
        """Return the design §4.3 fallbacks with the given ``contact`` (required, no default)."""
        return cls(hosts=_DEFAULT_HOSTS, contact=contact)
