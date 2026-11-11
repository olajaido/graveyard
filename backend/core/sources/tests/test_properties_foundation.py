"""Property tests for the pure foundation of ``core.sources`` (T1.1 to T1.6).

Profiles (``dev`` = 200 examples, ``ci`` = 500) come from ``conftest.py`` via
``HYPOTHESIS_PROFILE``. No ``max_examples`` is set here.

Token-shaped strings are built at run time by ``tests/strategies.py``, so no
token-shaped literal sits in this file (gitleaks).
"""

from __future__ import annotations

import dataclasses
import json
import math
import random
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from types import MappingProxyType
from typing import Any, Literal, cast
from urllib.parse import quote, unquote, urlsplit

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from core.purl import normalise_repo_url
from core.purl.model import normalise_pypi_name
from core.purl.tests.strategies import npm_names, npm_scopes, pypi_names, repo_urls, versions
from core.sources import accessors
from core.sources.cassette import (
    Cassette,
    CassetteEntry,
    cassette_from_obj,
    cassette_to_obj,
    freeze_json,
    request_key,
    thaw_json,
)
from core.sources.config import (
    CachePolicy,
    HostPolicy,
    Limits,
    RetryPolicy,
    SourcesConfig,
    Timeouts,
)
from core.sources.model import Evidence, JsonValue, SourceWarning
from core.sources.secret import REDACTED, SecretToken, redact
from core.sources.tests.strategies import embedded_token, json_like, noise
from core.sources.urls import (
    ALLOWED_HOSTS,
    NPM_BULK_MAX,
    depsdev_package_url,
    depsdev_project_url,
    depsdev_version_url,
    github_graphql_url,
    npm_downloads_bulk_url,
    npm_downloads_single_url,
    npm_packument_url,
    osv_querybatch_url,
    osv_vuln_url,
    pypi_json_url,
    pypistats_recent_url,
    scorecard_url,
    strip_userinfo,
)

pytestmark = pytest.mark.property

# An independent copy of the token-shape pattern (secret.py's is private).
SHAPE = re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}")

# ---------------------------------------------------------------------------
# redact
# ---------------------------------------------------------------------------

_VALID_TOKEN_CHARS = st.characters(
    blacklist_categories=("Cc", "Cf", "Cs", "Co", "Cn", "Zs", "Zl", "Zp")
)
# A tiny alphabet drawn from the placeholder, so tokens, text and the placeholder
# overlap and re-form often.
_TINY = st.text(alphabet="[REDACTED]a", min_size=1, max_size=6)


@st.composite
def _placeholder_fragment(draw: st.DrawFn) -> str:
    start = draw(st.integers(0, len(REDACTED) - 1))
    stop = draw(st.integers(start + 1, len(REDACTED)))
    return REDACTED[start:stop]


_TOKEN_TEXTS = st.one_of(
    st.text(_VALID_TOKEN_CHARS, min_size=1, max_size=40),
    _TINY,
    _placeholder_fragment(),
    st.builds(lambda a, b: a + b, _placeholder_fragment(), _TINY),
    st.builds(lambda a, b: a + b, _TINY, _placeholder_fragment()),
    st.builds(lambda a, b, c: a + b + c, _TINY, _placeholder_fragment(), _TINY),
)


@st.composite
def _token_and_text(draw: st.DrawFn) -> tuple[str, str]:
    """A valid token and a text that contains it, surrounded by re-forming material."""
    token = draw(_TOKEN_TEXTS)
    assume(len(token) <= 255)
    cut = draw(st.integers(0, len(token)))
    material = st.one_of(
        st.just(token),
        st.just(token[:cut]),
        st.just(token[cut:]),
        st.just(REDACTED),
        _placeholder_fragment(),
        _TINY,
        noise(),
        st.text(max_size=6),
    )
    pieces = draw(st.lists(material, max_size=8))
    pieces.insert(draw(st.integers(0, len(pieces))), token)
    return token, "".join(pieces)


@given(_token_and_text())
def test_redact_removes_token(case: tuple[str, str]) -> None:
    """**Validates: Requirements SRC-SEC-1, SRC-SEC-3**"""
    token, text = case
    assert token not in redact(text, token)
    assert token not in redact(text, SecretToken(token))


@given(_token_and_text(), st.data())
def test_redact_removes_token_next_to_shapes(case: tuple[str, str], data: st.DataObject) -> None:
    """Exact-token removal and shape removal together leave neither behind."""
    token, text = case
    shape = data.draw(embedded_token())
    out = redact(shape + text + shape, token)
    assert token not in out
    assert SHAPE.search(out) is None


# ---------------------------------------------------------------------------
# Evidence and SourceWarning never hold a token shape
# ---------------------------------------------------------------------------

_FETCHED_AT = datetime(2026, 11, 3, tzinfo=UTC)

_EVIDENCE_VALUES: st.SearchStrategy[JsonValue] = st.recursive(
    st.one_of(st.none(), st.integers(), embedded_token()),
    lambda children: st.one_of(
        st.lists(children, max_size=3),
        st.dictionaries(embedded_token(), children, max_size=3),
    ),
    max_leaves=8,
)


def _strings(value: JsonValue) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _strings(item)


@given(
    value=_EVIDENCE_VALUES,
    source_url=embedded_token(),
    note=st.none() | embedded_token(),
    extra=st.lists(embedded_token(), max_size=3),
)
def test_evidence_never_holds_token_shape(
    value: JsonValue, source_url: str, note: str | None, extra: list[str]
) -> None:
    """**Validates: Requirements SRC-SEC-3**"""
    evidence = Evidence(
        value=value,
        source_url=source_url,
        fetched_at=_FETCHED_AT,
        extra_source_urls=tuple(extra),
        note=note,
    )
    fields = [
        *_strings(evidence.value),
        evidence.source_url or "",
        evidence.note or "",
        *evidence.extra_source_urls,
    ]
    for text in fields:
        assert SHAPE.search(text) is None
    assert SHAPE.search(repr(evidence)) is None


@given(detail=embedded_token(), tail=st.text(max_size=300))
def test_warning_detail_never_holds_token_shape(detail: str, tail: str) -> None:
    """**Validates: Requirements SRC-SEC-3, SRC-WARN-3**"""
    for text in (detail, detail + tail, tail + detail):
        warning = SourceWarning(code="INTERNAL_ERROR", source="internal", signals=(), detail=text)
        assert SHAPE.search(warning.detail) is None
        assert len(warning.detail) <= 200
        assert SHAPE.search(repr(warning)) is None


# ---------------------------------------------------------------------------
# URL builders
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Seg:
    """A component that a builder must percent-encode into a path segment."""

    value: str


Piece = str | Seg

_BAD_SEGMENTS = ("", ".", "..")


def _plain_segment(text: st.SearchStrategy[str]) -> st.SearchStrategy[str]:
    return text.filter(lambda s: s not in _BAD_SEGMENTS)


_NPM_NAMES = st.one_of(
    npm_names(),
    st.builds(lambda scope, name: f"{scope}/{name}", npm_scopes(), npm_names()),
)
_PYPI_NAMES = pypi_names().map(normalise_pypi_name)
# Anything at all, minus the segments the builders refuse.
_ADVERSARIAL = _plain_segment(st.text(max_size=30))

_PACKAGE_NAMES = _plain_segment(st.one_of(_NPM_NAMES, _PYPI_NAMES, _ADVERSARIAL))
_VERSIONS = _plain_segment(
    st.one_of(versions().filter(lambda v: v is not None).map(str), _ADVERSARIAL)
)


def _owner_repo(url: str) -> tuple[str, str]:
    normalised = normalise_repo_url(url)
    assert normalised is not None
    _, owner, repo = normalised.split("/")
    return owner, repo


_OWNER_REPOS = st.one_of(
    repo_urls().map(lambda parts: _owner_repo(parts[0])),
    st.tuples(_ADVERSARIAL, _ADVERSARIAL),
)
_OSV_IDS = st.from_regex(r"[A-Za-z0-9_.:-]{1,100}", fullmatch=True).filter(
    lambda s: s not in _BAD_SEGMENTS
)
_BULK_NAMES = st.lists(
    st.from_regex(r"[A-Za-z0-9][A-Za-z0-9._~-]*", fullmatch=True),
    min_size=1,
    max_size=20,
    unique=True,
)


@dataclass(frozen=True)
class UrlComponents:
    ecosystem: str
    name: str
    version: str
    owner: str
    repo: str
    osv_id: str


@st.composite
def _components(draw: st.DrawFn) -> UrlComponents:
    owner, repo = draw(_OWNER_REPOS)
    return UrlComponents(
        ecosystem=draw(st.sampled_from(["npm", "pypi"])),
        name=draw(_PACKAGE_NAMES),
        version=draw(_VERSIONS),
        owner=owner,
        repo=repo,
        osv_id=draw(_OSV_IDS),
    )


def _all_urls(c: UrlComponents) -> list[tuple[str, tuple[Piece, ...]]]:
    """Every fixed-shape builder's URL with the literal and encoded pieces it must have."""
    return [
        (
            depsdev_version_url(c.ecosystem, c.name, c.version),
            (
                "https://api.deps.dev/v3/systems/",
                c.ecosystem,
                "/packages/",
                Seg(c.name),
                "/versions/",
                Seg(c.version),
            ),
        ),
        (
            depsdev_package_url(c.ecosystem, c.name),
            ("https://api.deps.dev/v3/systems/", c.ecosystem, "/packages/", Seg(c.name)),
        ),
        (
            depsdev_project_url(c.owner, c.repo),
            ("https://api.deps.dev/v3/projects/", Seg(f"github.com/{c.owner}/{c.repo}")),
        ),
        (
            scorecard_url(c.owner, c.repo),
            (
                "https://api.securityscorecards.dev/projects/github.com/",
                Seg(c.owner),
                "/",
                Seg(c.repo),
            ),
        ),
        (npm_packument_url(c.name), ("https://registry.npmjs.org/", Seg(c.name))),
        (pypi_json_url(c.name), ("https://pypi.org/pypi/", Seg(c.name), "/json")),
        (
            npm_downloads_single_url(c.name),
            ("https://api.npmjs.org/downloads/point/last-week/", Seg(c.name)),
        ),
        (
            pypistats_recent_url(c.name),
            ("https://pypistats.org/api/packages/", Seg(c.name), "/recent"),
        ),
        (osv_querybatch_url(), ("https://api.osv.dev/v1/querybatch",)),
        (osv_vuln_url(c.osv_id), ("https://api.osv.dev/v1/vulns/", Seg(c.osv_id))),
        (github_graphql_url(), ("https://api.github.com/graphql",)),
    ]


def _assert_safe_url(url: str) -> None:
    parts = urlsplit(url)
    assert parts.scheme == "https"
    assert parts.hostname in ALLOWED_HOSTS
    assert parts.netloc == parts.hostname  # no userinfo and no port
    assert parts.username is None
    assert parts.password is None
    assert parts.port is None
    assert parts.query == ""
    assert parts.fragment == ""
    assert "?" not in url
    assert "#" not in url
    assert "@" not in url
    assert url.isascii()
    assert not any(ch.isspace() or ord(ch) < 0x20 or ord(ch) == 0x7F for ch in url)


@given(_components(), _BULK_NAMES)
def test_url_hostname_always_allowed(c: UrlComponents, bulk: list[str]) -> None:
    """**Validates: Requirements SRC-HTTP-2, SRC-HTTP-3**"""
    for url, _ in _all_urls(c):
        _assert_safe_url(url)
    _assert_safe_url(npm_downloads_bulk_url(bulk))


_SEGMENT_CHARS = re.compile(r"[A-Za-z0-9_.~%-]*")


@given(_components())
def test_url_segments_are_quoted(c: UrlComponents) -> None:
    """**Validates: Requirements SRC-HTTP-3**"""
    for url, pieces in _all_urls(c):
        literals = "".join(piece for piece in pieces if isinstance(piece, str))
        expected = "".join(
            piece if isinstance(piece, str) else quote(piece.value, safe="") for piece in pieces
        )
        assert url == expected
        # Components add no path separator: the URL has exactly the literals' slashes.
        assert url.count("/") == literals.count("/")
        for piece in pieces:
            if isinstance(piece, Seg):
                encoded = quote(piece.value, safe="")
                assert _SEGMENT_CHARS.fullmatch(encoded)
                assert unquote(encoded) == piece.value
        # Splitting the path on "/" yields the expected segments, each one a whole component.
        path_segments = urlsplit(url).path.split("/")
        assert len(path_segments) == literals.count("/") - 2 + 1  # minus "//" of the scheme
        for piece in pieces:
            if isinstance(piece, Seg):
                assert quote(piece.value, safe="") in path_segments


@given(_BULK_NAMES)
def test_bulk_url_joins_quoted_names_with_commas(names: list[str]) -> None:
    """**Validates: Requirements SRC-HTTP-3, SRC-S9-1**"""
    url = npm_downloads_bulk_url(names)
    last = urlsplit(url).path.rsplit("/", 1)[1]
    assert last.count(",") == len(names) - 1
    assert [unquote(part) for part in last.split(",")] == names
    assert urlsplit(url).path.count("/") == 4  # /downloads/point/last-week/<names>
    assert len(names) <= NPM_BULK_MAX


# ---------------------------------------------------------------------------
# Accessors
# ---------------------------------------------------------------------------


@given(json_like(), st.integers(-5, 5))
def test_accessors_total(value: object, minimum: int) -> None:
    """**Validates: Requirements SRC-SEC-4, SRC-API-6**"""
    mapping = accessors.as_mapping(value)
    assert mapping is None or mapping is value
    assert (mapping is not None) == isinstance(value, Mapping)

    items = accessors.as_list(value)
    assert items is None or items is value
    assert (items is not None) == isinstance(value, list)

    text = accessors.as_str(value)
    assert text is None or text is value

    flag = accessors.as_bool(value)
    assert flag is None or flag is value

    number = accessors.as_int(value, minimum)
    if number is not None:
        assert type(number) is int
        assert number >= minimum
        assert number is value
    expect_int = isinstance(value, int) and not isinstance(value, bool) and value >= minimum
    assert (number is not None) == expect_int
    assert accessors.as_int(value) == accessors.as_int(value, 0)

    score = accessors.as_score(value)
    if score is not None:
        assert type(score) is float
        assert math.isfinite(score)
        assert score == -1 or 0 <= score <= 10
        assert isinstance(value, int | float) and not isinstance(value, bool)
    if isinstance(value, int) and not isinstance(value, bool):
        assert (score is not None) == (value == -1 or 0 <= value <= 10)

    parsed = accessors.as_date(value)
    if parsed is not None:
        assert type(parsed) is date
        assert isinstance(value, str)


@given(
    st.datetimes(timezones=st.just(UTC)),
    st.integers(-1439, 1439),
)
def test_as_date_converts_offsets_to_utc(moment: datetime, minutes: int) -> None:
    """A timestamp written with any offset gives the same UTC date as its instant."""
    local = moment.astimezone(timezone(timedelta(minutes=minutes)))
    assert accessors.as_date(local.isoformat()) == moment.date()


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_POS_INT = st.integers(1, 10**9)
_POS_SECONDS = st.one_of(st.floats(min_value=1e-3, max_value=1e6), st.integers(1, 1000))
_NONNEG_SECONDS = st.one_of(st.floats(min_value=0.0, max_value=1e6), st.integers(0, 1000))


def _bad_int(minimum: int) -> st.SearchStrategy[object]:
    return st.one_of(
        st.integers(max_value=minimum - 1),
        st.floats(),
        st.booleans(),
        st.text(max_size=5),
        st.none(),
    )


def _bad_seconds(*, allow_zero: bool) -> st.SearchStrategy[object]:
    bad: st.SearchStrategy[object] = st.one_of(
        st.floats(max_value=-1e-300, allow_nan=False, allow_infinity=False),
        st.integers(max_value=-1),
        st.sampled_from([math.nan, math.inf, -math.inf]),
        st.booleans(),
        st.text(max_size=5),
        st.none(),
    )
    return bad if allow_zero else st.one_of(bad, st.sampled_from([0, 0.0, -0.0]))


_HOST_POLICY_KWARGS: st.SearchStrategy[dict[str, Any]] = st.fixed_dictionaries(
    {
        "max_concurrency": _POS_INT,
        "min_interval_seconds": _NONNEG_SECONDS,
        "max_response_bytes": _POS_INT,
    }
)
_TIMEOUT_NAMES = ("connect", "read", "write", "pool", "request_deadline", "batch_deadline")
_LIMIT_POSITIVE = (
    "max_packages_in_flight",
    "max_packages_per_call",
    "max_vuln_details_per_package",
    "max_vuln_details_per_batch",
    "max_history_pages",
)

# (class, valid kwargs, {field: invalid values for that field})
_SPECS: list[tuple[type[Any], st.SearchStrategy[dict[str, Any]], dict[str, Any]]] = [
    (
        HostPolicy,
        _HOST_POLICY_KWARGS,
        {
            "max_concurrency": _bad_int(1),
            "min_interval_seconds": _bad_seconds(allow_zero=True),
            "max_response_bytes": _bad_int(1),
        },
    ),
    (
        Timeouts,
        st.fixed_dictionaries({name: _POS_SECONDS for name in _TIMEOUT_NAMES}),
        {name: _bad_seconds(allow_zero=False) for name in _TIMEOUT_NAMES},
    ),
    (
        RetryPolicy,
        st.fixed_dictionaries(
            {
                "max_attempts": st.integers(1, 50),
                "base": _POS_SECONDS,
                "cap": _POS_SECONDS,
                "max_retry_after_seconds": _NONNEG_SECONDS,
            }
        ),
        {
            "max_attempts": _bad_int(1),
            "base": _bad_seconds(allow_zero=False),
            "cap": _bad_seconds(allow_zero=False),
            "max_retry_after_seconds": _bad_seconds(allow_zero=True),
        },
    ),
    (
        CachePolicy,
        st.fixed_dictionaries({"default_ttl_seconds": _POS_INT, "pypistats_ttl_seconds": _POS_INT}),
        {"default_ttl_seconds": _bad_int(1), "pypistats_ttl_seconds": _bad_int(1)},
    ),
    (
        Limits,
        st.fixed_dictionaries(
            {
                **{name: _POS_INT for name in _LIMIT_POSITIVE},
                "github_rate_floor": st.integers(1, 10**6),
            }
        ),
        {
            **{name: _bad_int(1) for name in _LIMIT_POSITIVE},
            "github_rate_floor": _bad_int(1),
        },
    ),
]


@given(st.sampled_from(range(len(_SPECS))), st.data())
def test_config_roundtrip_validation(index: int, data: st.DataObject) -> None:
    """**Validates: Requirements SRC-HTTP-5, SRC-HTTP-8, SRC-RATE-1, SRC-SEC-5, SRC-CACHE-5**"""
    cls, valid, invalid = _SPECS[index]
    kwargs = data.draw(valid)
    built = cls(**kwargs)
    for name, value in kwargs.items():
        assert getattr(built, name) == value
    assert dataclasses.replace(built) == built

    field = data.draw(st.sampled_from(sorted(invalid)))
    bad = data.draw(invalid[field])
    with pytest.raises(ValueError):
        cls(**{**kwargs, field: bad})


_SENTINEL = "zq9x-contact-7731"
_CONTACT_CHARS = st.characters(
    blacklist_categories=("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"),
)
_CLEAN_CONTACTS = st.text(_CONTACT_CHARS, min_size=1, max_size=40).filter(lambda s: s.strip() != "")
_ALLOWED = sorted(ALLOWED_HOSTS)


@st.composite
def _valid_config_kwargs(draw: st.DrawFn, contact: st.SearchStrategy[str]) -> dict[str, Any]:
    return {
        "hosts": {host: HostPolicy(**draw(_HOST_POLICY_KWARGS)) for host in _ALLOWED},
        "contact": draw(contact),
        "timeouts": Timeouts(**draw(_SPECS[1][1])),
        "retry": RetryPolicy(**draw(_SPECS[2][1])),
        "cache": CachePolicy(**draw(_SPECS[3][1])),
        "limits": Limits(**draw(_SPECS[4][1])),
    }


@given(_valid_config_kwargs(_CLEAN_CONTACTS))
def test_sources_config_roundtrip(kwargs: dict[str, Any]) -> None:
    """**Validates: Requirements SRC-HTTP-2, SRC-PURE-3**"""
    hosts = kwargs["hosts"]
    config = SourcesConfig(**kwargs)
    assert dict(config.hosts) == hosts
    assert list(config.hosts) == sorted(hosts)
    assert isinstance(config.hosts, MappingProxyType)
    assert config.contact == kwargs["contact"]
    for name in ("timeouts", "retry", "cache", "limits"):
        assert getattr(config, name) == kwargs[name]
    # Read-only, and cut off from the caller's dict.
    with pytest.raises(TypeError):
        cast(Any, config.hosts)["api.osv.dev"] = hosts["api.osv.dev"]
    hosts.pop("api.osv.dev")
    assert "api.osv.dev" in config.hosts


_BAD_CONTROL = st.sampled_from(["\x00", "\n", "\r", "\x1b", "\x7f", "\x85", "\u2028", "\u2029"])
_BAD_HOST_VALUES: list[object] = [None, 5, "x", {"max_concurrency": 1}, object()]


@given(
    _valid_config_kwargs(st.just(_SENTINEL + "-ok")),
    st.sampled_from(
        [
            "contact_control",
            "contact_blank",
            "contact_type",
            "hosts_missing",
            "hosts_extra",
            "hosts_value",
            "hosts_type",
            "sub_type",
        ]
    ),
    st.data(),
)
def test_sources_config_invalid_raises_without_echo(
    kwargs: dict[str, Any], variant: str, data: st.DataObject
) -> None:
    """**Validates: Requirements SRC-HTTP-2, SRC-SEC-5**"""
    hosts: dict[Any, Any] = dict(kwargs["hosts"])
    if variant == "contact_control":
        kwargs["contact"] = _SENTINEL + data.draw(_BAD_CONTROL) + "tail"
    elif variant == "contact_blank":
        kwargs["contact"] = data.draw(st.sampled_from(["", " ", "\t ", "\u00a0"]))
    elif variant == "contact_type":
        kwargs["contact"] = data.draw(st.sampled_from([None, 5, b"x"]))
    elif variant == "hosts_missing":
        del hosts[data.draw(st.sampled_from(_ALLOWED))]
        kwargs["hosts"] = hosts
    elif variant == "hosts_extra":
        extra = data.draw(st.text(min_size=1, max_size=20))
        assume(extra not in ALLOWED_HOSTS)
        hosts[extra] = HostPolicy(1, 0.0, 1)
        kwargs["hosts"] = hosts
    elif variant == "hosts_value":
        hosts[data.draw(st.sampled_from(_ALLOWED))] = data.draw(st.sampled_from(_BAD_HOST_VALUES))
        kwargs["hosts"] = hosts
    elif variant == "hosts_type":
        kwargs["hosts"] = data.draw(st.sampled_from([list(_ALLOWED), None, "hosts"]))
    else:
        kwargs[data.draw(st.sampled_from(["timeouts", "retry", "cache", "limits"]))] = data.draw(
            st.sampled_from([None, 5, HostPolicy(1, 0.0, 1)])
        )
    with pytest.raises(ValueError) as caught:
        SourcesConfig(**kwargs)
    assert _SENTINEL not in str(caught.value)
    assert _SENTINEL not in repr(caught.value)


# ---------------------------------------------------------------------------
# Cassette
# ---------------------------------------------------------------------------

_JSON_LEAVES = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=12),
)
_JSON_BODIES: st.SearchStrategy[JsonValue] = st.recursive(
    _JSON_LEAVES,
    lambda children: st.one_of(
        st.lists(children, max_size=4),
        st.dictionaries(st.text(max_size=6), children, max_size=4),
    ),
    max_leaves=15,
)
_METHODS = st.sampled_from(["GET", "POST", "get", "Post"])
_URLS = st.text(min_size=1, max_size=40)

_HEX64 = re.compile(r"[0-9a-f]{64}")


def _reordered(value: JsonValue, rnd: random.Random) -> JsonValue:
    """Rebuild ``value`` with every dict's insertion order shuffled."""
    if isinstance(value, dict):
        items = list(value.items())
        rnd.shuffle(items)
        return {key: _reordered(item, rnd) for key, item in items}
    if isinstance(value, list):
        return [_reordered(item, rnd) for item in value]
    return value


def _random_case(text: str, rnd: random.Random) -> str:
    return "".join(ch.upper() if rnd.random() < 0.5 else ch.lower() for ch in text)


def _changed(body: JsonValue, choice: int) -> JsonValue:
    """A JSON-level modification that always gives a different document."""
    if choice == 0:
        return [body]
    if choice == 1:
        return {"wrapped": body}
    if isinstance(body, dict):
        extra = "added"
        while extra in body:
            extra += "_"
        return {**body, extra: None}
    if isinstance(body, list):
        return [*body, None]
    return [body, body]


@given(
    method=_METHODS,
    url=_URLS,
    body=_JSON_BODIES,
    rnd=st.randoms(use_true_random=False),
    choice=st.integers(0, 3),
)
def test_request_key_stable(
    method: str, url: str, body: JsonValue, rnd: random.Random, choice: int
) -> None:
    """**Validates: Requirements SRC-REC-3**"""
    key = request_key(method, url, body)
    assert _HEX64.fullmatch(key)

    assert request_key(method, url, _reordered(body, rnd)) == key
    assert request_key(_random_case(method, rnd), url, body) == key
    assert request_key(method, url, freeze_json(body)) == key
    assert request_key(method, url, thaw_json(freeze_json(body))) == key

    assert request_key(method, url, _changed(body, choice)) != key
    assert request_key(method, url + "x", body) != key
    other_method = "POST" if method.upper() == "GET" else "GET"
    assert request_key(other_method, url, body) != key


_ENTRIES = st.builds(
    CassetteEntry,
    method=_METHODS,
    url=_URLS,
    request_body=_JSON_BODIES,
    status=st.integers(100, 599),
    content_type=st.none() | st.text(max_size=20),
    retry_after=st.none() | st.text(max_size=10),
    response_body=_JSON_BODIES,
)


@given(st.lists(_ENTRIES, max_size=5), st.randoms(use_true_random=False))
def test_cassette_roundtrip(entries: list[CassetteEntry], rnd: random.Random) -> None:
    """**Validates: Requirements SRC-REC-3**"""
    unique = list({entry.key: entry for entry in entries}.values())
    cassette = Cassette(entries=tuple(unique))
    obj = cassette_to_obj(cassette)
    assert cassette_from_obj(obj) == cassette
    # The same through a real JSON text round trip, as a recorded file would be.
    assert cassette_from_obj(json.loads(json.dumps(obj))) == cassette
    # Entry order in the input does not matter.
    shuffled = list(unique)
    rnd.shuffle(shuffled)
    assert Cassette(entries=tuple(shuffled)) == cassette
    assert [entry.key for entry in cassette.entries] == [
        entry.key for entry in sorted(unique, key=lambda e: (e.url, e.key))
    ]


# ---------------------------------------------------------------------------
# strip_userinfo (SRC-SEC-3)
# ---------------------------------------------------------------------------

_SCHEMES = st.sampled_from(["https", "http", "git+ssh", "HTTPS", "ftp"])
_USERINFO = st.text(min_size=0, max_size=40).filter(lambda s: "@" not in s)
_NO_AT = st.text(max_size=60).filter(lambda s: "@" not in s)


@given(st.text(max_size=120))
def test_strip_userinfo_leaves_no_at_sign_and_never_grows(text: str) -> None:
    """**Validates: Requirements SRC-SEC-3**"""
    out = strip_userinfo(text)
    assert "@" not in out
    assert len(out) <= len(text)
    assert strip_userinfo(out) == out


@given(_NO_AT)
def test_strip_userinfo_is_the_identity_without_an_at_sign(text: str) -> None:
    """**Validates: Requirements SRC-SEC-3**"""
    assert strip_userinfo(text) == text


@given(_SCHEMES, st.lists(_USERINFO, min_size=1, max_size=3), _NO_AT, _NO_AT)
def test_strip_userinfo_removes_any_credential_before_the_host(
    scheme: str, userinfo_parts: list[str], host: str, rest: str
) -> None:
    """**Validates: Requirements SRC-SEC-3**

    However the credential is spelled (several ``@``, ``/``, ``?``, ``#``, control
    characters, ``://`` inside it), what is left is the scheme and what follows the last ``@``.
    """
    url = f"{scheme}://" + "@".join(userinfo_parts) + "@" + host + rest
    assert strip_userinfo(url) == f"{scheme}://" + host + rest
    for part in userinfo_parts:
        # a secret must not survive unless it is also a substring of the kept host/rest
        if part and part not in host + rest and part not in f"{scheme}://":
            assert part not in strip_userinfo(url)


# `parse_purl` rejects a lone surrogate (PV-PURL-13), so no parsed purl reaches a builder with
# one; `quote` would raise UnicodeEncodeError, a ValueError (see test_urls.py).
_SURROGATES: list[Literal["Cs"]] = ["Cs"]
_NAME_TEXT = st.text(
    alphabet=st.characters(blacklist_characters="@", blacklist_categories=_SURROGATES),
    max_size=80,
)


@given(_NAME_TEXT)
def test_every_built_url_is_unchanged(name: str) -> None:
    """**Validates: Requirements SRC-SEC-3** Quoted segments never contain a raw ``@``."""
    assume(name not in ("", ".", ".."))
    for url in (npm_packument_url(name), pypi_json_url(name), npm_downloads_single_url(name)):
        assert "@" not in url
        assert strip_userinfo(url) == url
    scoped = npm_packument_url("@" + name)
    assert "@" not in scoped and strip_userinfo(scoped) == scoped
