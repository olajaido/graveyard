"""Unit tests for parse_purl, format_purl and normalise_purl (PV-PURL-1 to PV-PURL-13)."""

from __future__ import annotations

from typing import Any, NoReturn, cast

import pytest
from packageurl import PackageURL

from core.purl.model import Purl
from core.purl.purl import format_purl, normalise_purl, parse_purl

# (input, normalise_purl) from the requirements' purl table.
NORMALISE_CASES = [
    ("pkg:npm/%40babel/core@7.24.0", "pkg:npm/%40babel/core@7.24.0"),
    ("pkg:npm/@babel/core@7.24.0", "pkg:npm/%40babel/core@7.24.0"),
    ("pkg:NPM/left-pad@1.3.0", "pkg:npm/left-pad@1.3.0"),
    ("pkg:npm/JSONStream@1.3.5", "pkg:npm/JSONStream@1.3.5"),
    ("pkg:npm/jsonstream@1.3.5", "pkg:npm/jsonstream@1.3.5"),
    ("pkg:npm/%40Babel/Core@7.24.0", "pkg:npm/%40Babel/Core@7.24.0"),
    ("pkg:npm/request@2.88.2?arch=x64#lib", "pkg:npm/request@2.88.2?arch=x64#lib"),
    ("pkg:pypi/requests@2.31.0", "pkg:pypi/requests@2.31.0"),
    ("pkg:pypi/Flask_SQLAlchemy@3.1.1", "pkg:pypi/flask-sqlalchemy@3.1.1"),
    ("pkg:pypi/zope.interface@6.0", "pkg:pypi/zope-interface@6.0"),
    ("pkg:pypi/requests", "pkg:pypi/requests"),
    ("pkg://npm/left-pad@1.3.0", "pkg:npm/left-pad@1.3.0"),
]

INVALID_CASES = [
    "pkg:maven/org.apache/commons@1.0",
    "pkg:github/psf/requests",
    "pkg:pypi/acme/requests@1.0",
    "pkg:npm/scope/name@1.0",
    "pkg:npm/@scope",
    "pkg:npm/left-pad@",
    "pkg:npm/x%2Fy@1",
    "pkg:npm/x@@1",
    "pkg:npm/%zz@1",
    "pkg:npm/ x @1",
    "pkg:npm/x?a=1&a=2",
    "PKG:npm/x@1",
    "npm/left-pad@1.3.0",
    "",
]

SURROGATE_INPUTS = [
    "pkg:npm/\ud800@1",
    "pkg:npm/na\ud800me@1",
    "pkg:npm/x@1\udc00",
    "pkg:npm/x@1?a=\ud800",
    "pkg:npm/x@1#sub\ud800path",
]


def _library_must_not_run(*_args: object, **_kwargs: object) -> NoReturn:
    raise AssertionError("packageurl-python must not be called")


@pytest.mark.parametrize(("raw", "expected"), NORMALISE_CASES)
def test_normalise_purl_table(raw: str, expected: str) -> None:
    """PV-PURL-1, PV-PURL-10: table rows normalise to the canonical string."""
    assert normalise_purl(raw) == expected


@pytest.mark.parametrize("raw", INVALID_CASES)
def test_invalid_purls_raise_value_error(raw: str) -> None:
    """PV-PURL-2/3/5/7/8/11: each listed input raises ValueError."""
    with pytest.raises(ValueError):
        parse_purl(raw)
    with pytest.raises(ValueError):
        normalise_purl(raw)


def test_npm_case_preserved() -> None:
    """PV-PURL-4: npm namespace and name keep their case."""
    p = parse_purl("pkg:npm/%40Babel/Core@1.0.0")
    assert p.namespace == "@Babel"
    assert p.name == "Core"
    assert format_purl(p) == "pkg:npm/%40Babel/Core@1.0.0"


def test_scope_written_percent_40() -> None:
    """PV-PURL-6: scope is written %40scope when formatting."""
    p = Purl("npm", "@scope", "name", "1.0.0")
    assert format_purl(p) == "pkg:npm/%40scope/name@1.0.0"


def test_double_slash_scheme_accepted() -> None:
    """PV-PURL-2: pkg:// is accepted."""
    assert parse_purl("pkg://pypi/requests@2.0") == parse_purl("pkg:pypi/requests@2.0")


def test_qualifiers_and_subpath_canonicalised() -> None:
    """PV-PURL-8: keys lower-cased and sorted; subpath dot segments dropped."""
    p = parse_purl("pkg:npm/x@1?B=2&A=1#a/./b//c")
    assert p.qualifiers == (("a", "1"), ("b", "2"))
    assert p.subpath == "a/b/c"
    assert format_purl(p) == "pkg:npm/x@1?a=1&b=2#a/b/c"


def test_length_boundary() -> None:
    """PV-PURL-12: 2,048 characters accepted, 2,049 rejected."""
    prefix = "pkg:npm/"
    ok = prefix + "a" * (2048 - len(prefix))
    assert len(ok) == 2048
    assert parse_purl(ok).name == "a" * (2048 - len(prefix))
    with pytest.raises(ValueError):
        parse_purl(ok + "a")
    with pytest.raises(ValueError):
        normalise_purl(ok + "a")


def test_library_not_called_above_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """PV-PURL-12: over-long input is rejected before the library is invoked."""
    monkeypatch.setattr(PackageURL, "from_string", _library_must_not_run)
    with pytest.raises(ValueError, match="PV-PURL-12"):
        parse_purl("pkg:npm/" + "a" * 2049)


@pytest.mark.parametrize("bad", [None, 123, b"pkg:npm/x@1", ["pkg:npm/x"]])
def test_non_str_argument_raises_value_error(bad: object) -> None:
    """PV-PURL-13: a non-str argument raises ValueError."""
    with pytest.raises(ValueError):
        parse_purl(cast(Any, bad))


def test_library_exceptions_wrapped_and_chained(monkeypatch: pytest.MonkeyPatch) -> None:
    """PV-PURL-13: unexpected library errors become ValueError with the cause chained."""

    def boom(*_args: object, **_kwargs: object) -> NoReturn:
        raise RuntimeError("boom")

    monkeypatch.setattr(PackageURL, "from_string", boom)
    with pytest.raises(ValueError) as info:
        parse_purl("pkg:npm/left-pad@1.3.0")
    assert isinstance(info.value.__cause__, RuntimeError)


@pytest.mark.parametrize("raw", SURROGATE_INPUTS)
def test_surrogates_rejected_before_library(raw: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """PV-PURL-13: lone surrogates raise ValueError without calling the library."""
    monkeypatch.setattr(PackageURL, "from_string", _library_must_not_run)
    with pytest.raises(ValueError):
        parse_purl(raw)


@pytest.mark.parametrize(
    "p",
    [
        Purl("npm", None, "na\ud800me", "1"),
        Purl("npm", "@sc\ud800ope", "name", "1"),
        Purl("npm", None, "name", "1\ud800"),
        Purl("npm", None, "name", "1", qualifiers=(("a", "\ud800"),)),
        Purl("npm", None, "name", "1", subpath="sub\ud800path"),
    ],
)
def test_format_purl_surrogate_raises_value_error(p: Purl) -> None:
    """PV-PURL-13: format_purl wraps UnicodeEncodeError as ValueError."""
    with pytest.raises(ValueError) as info:
        format_purl(p)
    assert not isinstance(info.value, UnicodeEncodeError)
