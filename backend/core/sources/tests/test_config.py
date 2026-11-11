"""Unit tests for ``core.sources.config`` (SRC-HTTP-2/5/8, SRC-RATE-1, SRC-SEC-5, SRC-CACHE-5)."""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, cast

import pytest

from core.sources.config import (
    CachePolicy,
    HostPolicy,
    Limits,
    RetryPolicy,
    SourcesConfig,
    Timeouts,
)
from core.sources.urls import ALLOWED_HOSTS

CONTACT = "ops@example.test"
MIB = 1024 * 1024


def hosts() -> dict[str, HostPolicy]:
    return {host: HostPolicy(1, 0.0, MIB) for host in ALLOWED_HOSTS}


# --- defaults (design §4.3) -----------------------------------------------------------------


def test_default_is_valid_and_keeps_contact() -> None:
    config = SourcesConfig.default(contact=CONTACT)
    assert config.contact == CONTACT
    assert set(config.hosts) == ALLOWED_HOSTS


def test_default_host_policies() -> None:
    hosts_ = SourcesConfig.default(contact=CONTACT).hosts
    assert hosts_["api.deps.dev"] == HostPolicy(10, 0.0, 8 * MIB)
    assert hosts_["api.osv.dev"] == HostPolicy(4, 0.0, 8 * MIB)
    assert hosts_["registry.npmjs.org"] == HostPolicy(10, 0.0, 16 * MIB)
    assert hosts_["pypi.org"] == HostPolicy(10, 0.0, 16 * MIB)
    assert hosts_["api.npmjs.org"] == HostPolicy(5, 0.0, 1 * MIB)
    assert hosts_["pypistats.org"] == HostPolicy(1, 1.2, 1 * MIB)
    assert hosts_["api.securityscorecards.dev"] == HostPolicy(4, 0.0, 4 * MIB)
    assert hosts_["api.github.com"] == HostPolicy(1, 0.0, 8 * MIB)


def test_default_scalar_policies() -> None:
    config = SourcesConfig.default(contact=CONTACT)
    assert config.timeouts == Timeouts(5.0, 15.0, 10.0, 10.0, 30.0, 240.0)
    assert config.retry == RetryPolicy(4, 0.5, 8.0, 20.0)
    assert config.cache == CachePolicy(86_400, 604_800)
    assert config.limits == Limits(50, 1_000, 200, 5_000, 10, 200)


def test_default_requires_a_contact_keyword() -> None:
    with pytest.raises(TypeError):
        cast(Any, SourcesConfig.default)()


# --- hosts ----------------------------------------------------------------------------------


def test_missing_host_key_raises() -> None:
    partial = hosts()
    del partial["pypi.org"]
    with pytest.raises(ValueError, match="pypi.org"):
        SourcesConfig(hosts=partial, contact=CONTACT)


def test_extra_host_key_raises() -> None:
    more = hosts()
    more["evil.example"] = HostPolicy(1, 0.0, MIB)
    with pytest.raises(ValueError, match="evil.example"):
        SourcesConfig(hosts=more, contact=CONTACT)


def test_empty_hosts_raises() -> None:
    with pytest.raises(ValueError):
        SourcesConfig(hosts={}, contact=CONTACT)


def test_non_mapping_hosts_raises() -> None:
    bad: Any = list(ALLOWED_HOSTS)
    with pytest.raises(ValueError):
        SourcesConfig(hosts=bad, contact=CONTACT)


def test_non_policy_host_value_raises() -> None:
    wrong: Any = hosts()
    wrong["pypi.org"] = {"max_concurrency": 1}
    with pytest.raises(ValueError):
        SourcesConfig(hosts=wrong, contact=CONTACT)


def test_hosts_mapping_is_read_only_and_copied() -> None:
    source = hosts()
    config = SourcesConfig(hosts=source, contact=CONTACT)
    assert isinstance(config.hosts, MappingProxyType)
    view: Any = config.hosts
    with pytest.raises(TypeError):
        view["pypi.org"] = HostPolicy(2, 0.0, MIB)
    with pytest.raises(TypeError):
        del view["pypi.org"]
    source["pypi.org"] = HostPolicy(9, 0.0, MIB)
    assert config.hosts["pypi.org"].max_concurrency == 1


def test_hosts_are_sorted() -> None:
    config = SourcesConfig(hosts=hosts(), contact=CONTACT)
    assert list(config.hosts) == sorted(ALLOWED_HOSTS)


def test_default_hosts_cannot_be_changed_through_a_config() -> None:
    config = SourcesConfig.default(contact=CONTACT)
    view: Any = config.hosts
    with pytest.raises(TypeError):
        view["api.github.com"] = HostPolicy(9, 0.0, MIB)
    assert SourcesConfig.default(contact=CONTACT).hosts["api.github.com"].max_concurrency == 1


def test_config_and_policy_are_frozen() -> None:
    config: Any = SourcesConfig.default(contact=CONTACT)
    policy: Any = config.hosts["pypi.org"]
    with pytest.raises(AttributeError):
        config.contact = "x"
    with pytest.raises(AttributeError):
        policy.max_concurrency = 5


# --- contact --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    ["", "   ", "\t", "a\nb", "a\rb", "a\x00b", "a\x7fb", "a\u2028b", "a\u2029b", "a\u200bb"],
)
def test_bad_contact_raises(bad: str) -> None:
    with pytest.raises(ValueError):
        SourcesConfig(hosts=hosts(), contact=bad)


def test_non_string_contact_raises() -> None:
    bad: Any = None
    with pytest.raises(ValueError):
        SourcesConfig(hosts=hosts(), contact=bad)


def test_error_messages_do_not_echo_the_contact() -> None:
    secret = "contact-sentinel-7731"
    with pytest.raises(ValueError) as bad_contact:
        SourcesConfig(hosts=hosts(), contact=secret + "\n")
    assert secret not in str(bad_contact.value)
    with pytest.raises(ValueError) as bad_hosts:
        SourcesConfig(hosts={}, contact=secret)
    assert secret not in str(bad_hosts.value)
    other: Any = "not a Timeouts"
    with pytest.raises(ValueError) as bad_timeouts:
        SourcesConfig(hosts=hosts(), contact=secret, timeouts=other)
    assert secret not in str(bad_timeouts.value)


def test_non_policy_nested_values_raise() -> None:
    wrong: Any = object()
    for name in ("timeouts", "retry", "cache", "limits"):
        with pytest.raises(ValueError):
            SourcesConfig(hosts=hosts(), contact=CONTACT, **{name: wrong})


# --- HostPolicy -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_concurrency": 0},
        {"max_concurrency": -1},
        {"max_concurrency": True},
        {"max_concurrency": 1.5},
        {"min_interval_seconds": -0.1},
        {"min_interval_seconds": float("nan")},
        {"min_interval_seconds": float("inf")},
        {"min_interval_seconds": True},
        {"max_response_bytes": 0},
        {"max_response_bytes": -5},
    ],
)
def test_invalid_host_policy_raises(kwargs: dict[str, Any]) -> None:
    fields: dict[str, Any] = {
        "max_concurrency": 1,
        "min_interval_seconds": 0.0,
        "max_response_bytes": 10,
    }
    fields.update(kwargs)
    with pytest.raises(ValueError):
        HostPolicy(**fields)


def test_zero_interval_is_allowed() -> None:
    assert HostPolicy(1, 0, 1).min_interval_seconds == 0


# --- Timeouts / RetryPolicy / CachePolicy / Limits -----------------------------------------


@pytest.mark.parametrize(
    "name", ["connect", "read", "write", "pool", "request_deadline", "batch_deadline"]
)
@pytest.mark.parametrize("value", [0, 0.0, -1.0, float("nan"), float("inf"), True])
def test_invalid_timeout_raises(name: str, value: Any) -> None:
    with pytest.raises(ValueError):
        Timeouts(**{name: value})


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_attempts": 0},
        {"max_attempts": -1},
        {"max_attempts": True},
        {"max_attempts": 2.0},
        {"base": 0},
        {"base": -0.5},
        {"cap": 0},
        {"cap": float("inf")},
        {"max_retry_after_seconds": -1},
        {"max_retry_after_seconds": float("nan")},
    ],
)
def test_invalid_retry_policy_raises(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        RetryPolicy(**kwargs)


def test_retry_policy_boundaries_are_accepted() -> None:
    assert RetryPolicy(max_attempts=1).max_attempts == 1
    assert RetryPolicy(max_retry_after_seconds=0).max_retry_after_seconds == 0


@pytest.mark.parametrize("name", ["default_ttl_seconds", "pypistats_ttl_seconds"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_invalid_ttl_raises(name: str, value: Any) -> None:
    with pytest.raises(ValueError):
        CachePolicy(**{name: value})


@pytest.mark.parametrize(
    "name",
    [
        "max_packages_in_flight",
        "max_packages_per_call",
        "max_vuln_details_per_package",
        "max_vuln_details_per_batch",
        "max_history_pages",
    ],
)
@pytest.mark.parametrize("value", [0, -1, True, 2.0])
def test_invalid_limits_raise(name: str, value: Any) -> None:
    with pytest.raises(ValueError):
        Limits(**{name: value})


def test_github_rate_floor_must_be_at_least_one() -> None:
    # A floor of 0 can never trigger (`remaining < 0` is never true), so it is rejected.
    assert Limits(github_rate_floor=1).github_rate_floor == 1
    assert Limits().github_rate_floor == 200
    for bad in (0, -1, True, 1.0, "1", None):
        kwargs: dict[str, Any] = {"github_rate_floor": bad}
        with pytest.raises(ValueError):
            Limits(**kwargs)
