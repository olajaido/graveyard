"""Unit tests for package_key and registry_name.

Validates: PV-KEY-1 to PV-KEY-4, PV-REG-1, PV-REG-2, PV-SYFT-3.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from core.purl.purl import package_key, parse_purl, registry_name

FIXTURES = Path(__file__).parent / "fixtures"

# (input, package_key, registry_name) from the requirements' purl table.
KEY_CASES = [
    ("pkg:npm/%40babel/core@7.24.0", "npm/%40babel/core@7.24.0", "@babel/core"),
    ("pkg:npm/@babel/core@7.24.0", "npm/%40babel/core@7.24.0", "@babel/core"),
    ("pkg:NPM/left-pad@1.3.0", "npm/left-pad@1.3.0", "left-pad"),
    ("pkg:npm/JSONStream@1.3.5", "npm/jsonstream@1.3.5", "JSONStream"),
    ("pkg:npm/jsonstream@1.3.5", "npm/jsonstream@1.3.5", "jsonstream"),
    ("pkg:npm/%40Babel/Core@7.24.0", "npm/%40babel/core@7.24.0", "@Babel/Core"),
    ("pkg:npm/request@2.88.2?arch=x64#lib", "npm/request@2.88.2", "request"),
    ("pkg:pypi/requests@2.31.0", "pypi/requests@2.31.0", "requests"),
    ("pkg:pypi/Flask_SQLAlchemy@3.1.1", "pypi/flask-sqlalchemy@3.1.1", "flask-sqlalchemy"),
    ("pkg:pypi/zope.interface@6.0", "pypi/zope-interface@6.0", "zope-interface"),
    ("pkg:pypi/requests", "pypi/requests", "requests"),
    ("pkg://npm/left-pad@1.3.0", "npm/left-pad@1.3.0", "left-pad"),
]


def _load_syft_component() -> dict[str, Any]:
    with (FIXTURES / "syft_jsonstream.json").open(encoding="utf-8") as fh:
        return cast("dict[str, Any]", json.load(fh))


@pytest.mark.parametrize(("raw", "key", "_name"), KEY_CASES)
def test_package_key_table(raw: str, key: str, _name: str) -> None:
    """PV-KEY-1, PV-KEY-4: table rows produce the expected package key."""
    assert package_key(parse_purl(raw)) == key


@pytest.mark.parametrize(("raw", "_key", "name"), KEY_CASES)
def test_registry_name_table(raw: str, _key: str, name: str) -> None:
    """PV-REG-1: table rows produce the expected registry name, case preserved."""
    assert registry_name(parse_purl(raw)) == name


def test_registry_name_is_not_percent_encoded() -> None:
    """PV-REG-2: the scope is written @scope, never %40scope."""
    name = registry_name(parse_purl("pkg:npm/%40babel/core@7.24.0"))
    assert name == "@babel/core"
    assert "%" not in name


def test_jsonstream_key_folds_case_but_registry_name_keeps_it() -> None:
    """PV-KEY-4: JSONStream keys as jsonstream; registry_name stays JSONStream."""
    p = parse_purl("pkg:npm/JSONStream@1.3.5")
    assert package_key(p) == "npm/jsonstream@1.3.5"
    assert registry_name(p) == "JSONStream"


def test_scoped_upper_case_key_and_registry_name() -> None:
    """PV-KEY-4: @Babel/Core folds in the key and is preserved in registry_name."""
    p = parse_purl("pkg:npm/%40Babel/Core@7.24.0")
    assert package_key(p) == "npm/%40babel/core@7.24.0"
    assert registry_name(p) == "@Babel/Core"


def test_version_case_not_folded() -> None:
    """PV-KEY-1, D2: upper-case letters in the version are left alone."""
    p = parse_purl("pkg:npm/JSONStream@1.0.0-RC.1")
    assert package_key(p) == "npm/jsonstream@1.0.0-RC.1"
    assert package_key(p) != package_key(parse_purl("pkg:npm/JSONStream@1.0.0-rc.1"))


def test_non_ascii_npm_name_not_folded() -> None:
    """PV-KEY-4, D7: KELVIN SIGN (U+212A) is not folded to `k`."""
    kelvin = parse_purl("pkg:npm/\u212a@1.0.0")
    ascii_k = parse_purl("pkg:npm/k@1.0.0")
    assert package_key(kelvin) != package_key(ascii_k)
    assert package_key(kelvin) == "npm/%E2%84%AA@1.0.0"
    assert registry_name(kelvin) == "\u212a"


def test_non_ascii_upper_case_not_folded() -> None:
    """PV-KEY-4: non-ASCII letters keep their case; only A-Z folds."""
    p = parse_purl("pkg:npm/\u00c9Cole@1.0.0")
    assert package_key(p) == "npm/%C3%89cole@1.0.0"


def test_no_version_key_has_no_at_suffix() -> None:
    """PV-KEY-1: the @version part is omitted when the version is None."""
    assert package_key(parse_purl("pkg:npm/JSONStream")) == "npm/jsonstream"
    assert package_key(parse_purl("pkg:npm/%40Babel/Core")) == "npm/%40babel/core"


def test_pypi_key_unchanged() -> None:
    """PV-KEY-4: a PyPI name is already PEP 503-normalised, so the key keeps it."""
    p = parse_purl("pkg:pypi/Zope__Interface.Foo@1.0")
    assert p.name == "zope-interface-foo"
    assert package_key(p) == "pypi/zope-interface-foo@1.0"


def test_qualifiers_and_subpath_dropped() -> None:
    """PV-KEY-1: qualifiers and subpath do not appear in the key."""
    p = parse_purl("pkg:npm/request@2.88.2?arch=x64&os=linux#lib/index.js")
    assert package_key(p) == "npm/request@2.88.2"


def test_package_key_reversible_up_to_case() -> None:
    """PV-KEY-3: parsing 'pkg:' + key gives the folded purl."""
    p = parse_purl("pkg:npm/%40Babel/Core@7.24.0?arch=x64#lib")
    back = parse_purl("pkg:" + package_key(p))
    assert (back.namespace, back.name, back.version) == ("@babel", "core", "7.24.0")
    assert back.qualifiers == ()
    assert back.subpath is None


class TestSyftJsonStream:
    """PV-SYFT-3: key and registry_name for the purl Syft v1.56.0 emitted.

    Syft preserved the registry case (`pkg:npm/JSONStream@1.3.5`). The
    assertions hold whichever case Syft emits.
    """

    def test_registry_name_is_jsonstream(self) -> None:
        purl = parse_purl(_load_syft_component()["purl"])
        assert registry_name(purl) == "JSONStream"

    def test_package_key_is_lower_case(self) -> None:
        component = _load_syft_component()
        purl = parse_purl(component["purl"])
        assert package_key(purl) == f"npm/jsonstream@{component['version']}"

    def test_lower_case_spelling_has_same_package_key(self) -> None:
        component = _load_syft_component()
        emitted = parse_purl(component["purl"])
        lowered = parse_purl(f"pkg:npm/jsonstream@{component['version']}")
        assert package_key(emitted) == package_key(lowered)
        assert registry_name(lowered) == "jsonstream"
