"""Unit tests for ``parse_poetry_lock`` (DG-SCP-0, DG-SCP-6, DG-WARN-1, DG-EX-20).

Expectations for the generated fixture (``lock_poetry.toml``) are recomputed
here from the file with plain ``tomllib`` code; ``parse_poetry_lock`` is never
used to compute an expectation. Expected keys come from
``core.graph.keys.pypi_key``. The synthetic file (``lock_poetry_edge.toml``) is
checked against the table in ``fixtures/README.md``. Fixtures resolve via
``Path(__file__).parent``.
"""

import tomllib
from pathlib import Path
from typing import Any, cast

import pytest

from core.graph.keys import pypi_key
from core.graph.model import MAX_LOCKFILE_CHARS, WARNING_CODES, Scope, ScopeResult
from core.graph.scopes_poetry import parse_poetry_lock

FIXTURES = Path(__file__).parent / "fixtures"


# --- helpers ---------------------------------------------------------------


def read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def lock_text(*tables: str) -> str:
    """A poetry.lock made of the given ``[[package]]`` bodies."""
    return "".join(f"[[package]]\n{body}\n" for body in tables)


def pkg(name: str, version: str, extra: str = "") -> str:
    return f'name = "{name}"\nversion = "{version}"\n{extra}'


def marker_scope(entry: dict[str, Any]) -> Scope:
    """Scope from the markers the tool wrote: ``groups`` first, then ``category``, else runtime."""
    if "groups" in entry:
        return "runtime" if "main" in entry["groups"] else "dev"
    if "category" in entry:
        return "runtime" if entry["category"] == "main" else "dev"
    return "runtime"


def expected_package_scopes(doc: dict[str, Any]) -> dict[str, Scope]:
    return {pypi_key(p["name"], p["version"]): marker_scope(p) for p in doc["package"]}


def codes(result: ScopeResult) -> list[str]:
    return [w.code for w in result.warnings]


# --- DG-EX-20: real fixture ------------------------------------------------


def test_lock_poetry_scopes_follow_the_markers_in_the_file() -> None:
    text = read("lock_poetry.toml")
    doc = tomllib.loads(text)
    result = parse_poetry_lock(text)

    expected = expected_package_scopes(doc)
    assert expected == {
        pypi_key("six", "1.17.0"): "runtime",
        pypi_key("iniconfig", "2.3.1"): "dev",
    }
    assert dict(result.package_scopes) == expected
    # The expectation really is tied to the markers the tool wrote.
    by_name = {p["name"]: p for p in doc["package"]}
    assert by_name["six"]["groups"] == ["main"]
    assert by_name["iniconfig"]["groups"] == ["dev"]
    assert all("category" not in p for p in doc["package"])


def test_lock_poetry_direct_scopes_empty_and_no_warnings() -> None:
    result = parse_poetry_lock(read("lock_poetry.toml"))
    assert dict(result.direct_scopes) == {}
    assert result.warnings == ()


# --- DG-EX-20: synthetic edge fixture --------------------------------------

EDGE_TEXT = read("lock_poetry_edge.toml")

REQUESTS = pypi_key("requests", "2.31.0")
PYTEST = pypi_key("pytest", "7.4.4")
CERTIFI = pypi_key("certifi", "2023.11.17")
COVERAGE = pypi_key("coverage", "7.4.0")
IDNA = pypi_key("idna", "3.6")
FLASK_SQLALCHEMY = pypi_key("Flask_SQLAlchemy", "3.1.1")


def test_edge_whole_file_expectations() -> None:
    result = parse_poetry_lock(EDGE_TEXT)
    assert dict(result.package_scopes) == {
        CERTIFI: "runtime",
        COVERAGE: "dev",
        FLASK_SQLALCHEMY: "runtime",
        IDNA: "runtime",
        PYTEST: "dev",
        REQUESTS: "runtime",
    }
    assert dict(result.direct_scopes) == {}
    assert result.warnings == ()
    # Maps iterate in sorted key order (deterministic output).
    assert list(result.package_scopes) == sorted(result.package_scopes)
    # The whole-file expectation agrees with the markers independently read from the file.
    assert dict(result.package_scopes) == expected_package_scopes(tomllib.loads(EDGE_TEXT))


@pytest.mark.parametrize(
    ("key", "scope"),
    [
        pytest.param(REQUESTS, "runtime", id="legacy-category-main"),
        pytest.param(PYTEST, "dev", id="legacy-category-dev"),
        pytest.param(CERTIFI, "runtime", id="groups-main-and-dev"),
        pytest.param(COVERAGE, "dev", id="groups-dev-and-test"),
        pytest.param(IDNA, "runtime", id="neither-field-is-runtime"),
        pytest.param(FLASK_SQLALCHEMY, "runtime", id="groups-main"),
    ],
)
def test_edge_package_scope_cases(key: str, scope: str) -> None:
    assert parse_poetry_lock(EDGE_TEXT).package_scopes[key] == scope


def test_edge_name_is_normalised() -> None:
    result = parse_poetry_lock(EDGE_TEXT)
    assert FLASK_SQLALCHEMY == "pypi/flask-sqlalchemy@3.1.1"
    assert FLASK_SQLALCHEMY in result.package_scopes
    assert not any("Flask_SQLAlchemy" in key for key in result.package_scopes)


# --- inline synthetic cases ------------------------------------------------


@pytest.mark.parametrize(
    "markers",
    [
        pytest.param(('groups = ["dev"]', 'groups = ["main"]'), id="dev-first"),
        pytest.param(('groups = ["main"]', 'groups = ["dev"]'), id="runtime-first"),
        pytest.param(('category = "dev"', 'category = "main"'), id="legacy-dev-first"),
    ],
)
def test_runtime_wins_on_duplicate_keys(markers: tuple[str, str]) -> None:
    first, second = markers
    tables = (pkg("a", "1.0", first), pkg("a", "1.0", second))
    result = parse_poetry_lock(lock_text(*tables))
    assert dict(result.package_scopes) == {pypi_key("a", "1.0"): "runtime"}
    assert result.warnings == ()


def test_duplicate_dev_copies_stay_dev() -> None:
    tables = (pkg("a", "1.0", 'groups = ["dev"]'), pkg("A", "1.0", 'groups = ["test"]'))
    result = parse_poetry_lock(lock_text(*tables))
    assert dict(result.package_scopes) == {pypi_key("a", "1.0"): "dev"}


def test_groups_takes_precedence_over_category() -> None:
    tables = (
        pkg("a", "1.0", 'groups = ["dev"]\ncategory = "main"'),
        pkg("b", "1.0", 'groups = ["main"]\ncategory = "dev"'),
    )
    result = parse_poetry_lock(lock_text(*tables))
    assert dict(result.package_scopes) == {
        pypi_key("a", "1.0"): "dev",
        pypi_key("b", "1.0"): "runtime",
    }


@pytest.mark.parametrize(
    "extra",
    [
        pytest.param("groups = []", id="empty-groups"),
        pytest.param('groups = "main"', id="groups-not-a-list"),
        pytest.param('category = "other"', id="unknown-category"),
    ],
)
def test_unrecognised_marker_shapes_are_dev(extra: str) -> None:
    result = parse_poetry_lock(lock_text(pkg("a", "1.0", extra)))
    assert dict(result.package_scopes) == {pypi_key("a", "1.0"): "dev"}


def test_non_table_entry_is_skipped_with_warning() -> None:
    text = "package = [1]\n"
    result = parse_poetry_lock(text)
    assert dict(result.package_scopes) == {}
    (warning,) = result.warnings
    assert warning.code == "LOCKFILE_ENTRY_SKIPPED"
    assert warning.subjects == ("package[0]",)
    assert warning.service is None


@pytest.mark.parametrize(
    "body",
    [
        pytest.param('name = 1\nversion = "1.0"', id="name-not-string"),
        pytest.param('name = "a"\nversion = 1', id="version-not-string"),
        pytest.param('name = "a"', id="version-missing"),
        pytest.param('version = "1.0"', id="name-missing"),
    ],
)
def test_non_string_name_or_version_is_skipped_with_warning(body: str) -> None:
    text = lock_text(body, pkg("good", "2.0"))
    result = parse_poetry_lock(text)
    assert dict(result.package_scopes) == {pypi_key("good", "2.0"): "runtime"}
    (warning,) = result.warnings
    assert warning.code == "LOCKFILE_ENTRY_SKIPPED"
    assert warning.subjects == ("package[0]",)
    assert warning.service is None


@pytest.mark.parametrize(
    ("name", "version"),
    [
        pytest.param("bad name", "1.0", id="space-in-name"),
        pytest.param("a/b", "1.0", id="slash-in-name"),
        pytest.param("", "1.0", id="empty-name"),
        pytest.param("ok", "", id="empty-version"),
        pytest.param("ok", "1 0", id="space-in-version"),
    ],
)
def test_unpurlable_name_or_version_is_skipped_with_warning(name: str, version: str) -> None:
    text = lock_text(pkg(name, version), pkg("good", "2.0"))
    result = parse_poetry_lock(text)
    assert dict(result.package_scopes) == {pypi_key("good", "2.0"): "runtime"}
    (warning,) = result.warnings
    assert warning.code == "LOCKFILE_ENTRY_SKIPPED"
    assert warning.code in WARNING_CODES
    assert warning.subjects == (f"{name}@{version}",)
    assert warning.service is None


def test_missing_package_key_gives_empty_result() -> None:
    result = parse_poetry_lock('[metadata]\nlock-version = "2.1"\n')
    assert dict(result.package_scopes) == {}
    assert dict(result.direct_scopes) == {}
    assert result.warnings == ()


def test_empty_text_gives_empty_result() -> None:
    result = parse_poetry_lock("")
    assert dict(result.package_scopes) == {}
    assert result.warnings == ()


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("package = 1", id="integer"),
        pytest.param('package = "a"', id="string"),
        pytest.param('[package]\nname = "a"\nversion = "1"', id="single-table"),
    ],
)
def test_non_list_package_is_rejected(text: str) -> None:
    with pytest.raises(ValueError, match="package"):
        parse_poetry_lock(text)


def test_results_are_read_only_sorted_maps_with_unattributed_warnings() -> None:
    text = lock_text(
        pkg("zeta", "1.0"), pkg("alpha", "1.0", 'groups = ["dev"]'), pkg("bad name", "1")
    )
    result = parse_poetry_lock(text)
    assert list(result.package_scopes) == [pypi_key("alpha", "1.0"), pypi_key("zeta", "1.0")]
    with pytest.raises(TypeError):
        cast(Any, result.package_scopes)[pypi_key("x", "1")] = "dev"
    with pytest.raises(TypeError):
        cast(Any, result.direct_scopes)[pypi_key("x", "1")] = "dev"
    assert codes(result) == ["LOCKFILE_ENTRY_SKIPPED"]
    assert all(w.service is None for w in result.warnings)


# --- DG-SCP-0: rejections --------------------------------------------------


@pytest.mark.parametrize("text", ["[[package]", "name = ", "a = = 1", "\x00", "[a]\n[a]"])
def test_invalid_toml_is_rejected(text: str) -> None:
    with pytest.raises(ValueError, match="invalid TOML"):
        parse_poetry_lock(text)


def test_oversize_text_is_rejected_before_parsing() -> None:
    with pytest.raises(ValueError, match="exceeds"):
        parse_poetry_lock(" " * (MAX_LOCKFILE_CHARS + 1))


def test_deeply_nested_array_is_value_error() -> None:
    depth = 100_000
    with pytest.raises(ValueError, match="nesting too deep"):
        parse_poetry_lock("a = " + "[" * depth + "]" * depth)


def test_unbalanced_open_brackets_are_value_error() -> None:
    with pytest.raises(ValueError, match="invalid TOML"):
        parse_poetry_lock("[" * 100_000)


@pytest.mark.parametrize("value", [None, b"", 1, ["package"]])
def test_non_str_input_is_rejected(value: object) -> None:
    with pytest.raises(ValueError, match="must be str"):
        parse_poetry_lock(cast(Any, value))
