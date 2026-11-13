"""Unit tests for scripts/check_versions.py (pure logic only; no network)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "check_versions.py"
_spec = importlib.util.spec_from_file_location("check_versions", _SCRIPT)
assert _spec and _spec.loader
cv = importlib.util.module_from_spec(_spec)
sys.modules["check_versions"] = cv
_spec.loader.exec_module(cv)

PYPI = {
    "info": {"version": "2.0.0"},
    "releases": {
        "1.0": [{"upload_time_iso_8601": "2020-01-02T00:00:00Z"}],
        "1.5.0": [
            {"upload_time_iso_8601": "2021-05-06T00:00:00Z"},
            {"upload_time_iso_8601": "2021-05-05T00:00:00Z"},
        ],
        "1.6.0": [],
        "2.0.0": [{"upload_time_iso_8601": "2022-03-04T00:00:00Z"}],
    },
}
NPM = {
    "dist-tags": {"latest": "3.1.0"},
    "versions": {"3.0.0": {}, "3.1.0": {}},
    "time": {
        "created": "x",
        "3.0.0": "2019-01-01T00:00:00.000Z",
        "3.1.0": "2020-02-02T00:00:00.000Z",
    },
}


def test_parse_pypi_uses_earliest_upload_and_skips_empty_releases() -> None:
    info = cv.parse_pypi(PYPI)
    assert info.latest == "2.0.0"
    assert info.versions == {
        "1.0": "2020-01-02T00:00:00Z",
        "1.5.0": "2021-05-05T00:00:00Z",
        "2.0.0": "2022-03-04T00:00:00Z",
    }


def test_parse_npm() -> None:
    info = cv.parse_npm(NPM)
    assert info.latest == "3.1.0"
    assert info.versions == {
        "3.0.0": "2019-01-01T00:00:00.000Z",
        "3.1.0": "2020-02-02T00:00:00.000Z",
    }


def test_compare_current_latest() -> None:
    row = cv.compare("npm", "p", "3.1.0", cv.parse_npm(NPM))
    assert row.exists == "yes"
    assert row.row_published == row.latest_published == "2020-02-02T00:00:00.000Z"
    assert not cv.needs_attention(row)


def test_compare_older_version_is_flagged() -> None:
    row = cv.compare("npm", "p", "3.0.0", cv.parse_npm(NPM))
    assert row.exists == "yes"
    assert row.latest == "3.1.0"
    assert row.row_published == "2019-01-01T00:00:00.000Z"
    assert cv.needs_attention(row)


def test_compare_missing_version_is_flagged() -> None:
    row = cv.compare("pypi", "p", "1.6.0", cv.parse_pypi(PYPI))
    assert row.exists == "no"
    assert row.latest == "2.0.0"
    assert row.row_published == ""
    assert row.latest_published == "2022-03-04T00:00:00Z"
    assert cv.needs_attention(row)


def test_compare_normalised_spelling() -> None:
    row = cv.compare("pypi", "p", "1.0.0", cv.parse_pypi(PYPI))
    assert row.exists == "yes"
    assert row.row_published == "2020-01-02T00:00:00Z"
    latest = cv.compare("pypi", "p", "2", cv.parse_pypi(PYPI))
    assert latest.exists == "yes"
    assert not cv.needs_attention(latest)


def test_compare_unknown_package_and_error() -> None:
    gone = cv.compare("npm", "nope", "1.0.0", cv.RegistryInfo(found=False))
    assert gone.exists == "no" and cv.needs_attention(gone)
    err = cv.compare("npm", "p", "1.0.0", cv.RegistryInfo(found=False, error="HTTP 500"))
    assert err.exists == "error" and cv.needs_attention(err)


def test_registry_urls() -> None:
    assert cv.registry_url("pypi", "torf") == "https://pypi.org/pypi/torf/json"
    assert cv.registry_url("npm", "ms") == "https://registry.npmjs.org/ms"
    assert cv.registry_url("npm", "@a/b") == "https://registry.npmjs.org/@a%2Fb"


@pytest.mark.parametrize(("eco", "name"), [("cargo", "a"), ("pypi", "a b"), ("npm", "../x")])
def test_registry_url_rejects_unsafe(eco: str, name: str) -> None:
    with pytest.raises(ValueError):
        cv.registry_url(eco, name)


def test_render_tsv_columns() -> None:
    row = cv.compare("npm", "p", "3.1.0", cv.parse_npm(NPM))
    lines = cv.render_tsv([row]).splitlines()
    assert lines[0].split("\t") == list(cv.COLUMNS)
    assert lines[1].split("\t")[:5] == ["npm", "p", "3.1.0", "yes", "3.1.0"]
