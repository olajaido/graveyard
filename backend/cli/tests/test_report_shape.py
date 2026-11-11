"""The JSON report keeps its shape (T9.5; CLI-JSON-9, D12).

``fixtures/report_v1_shape.json`` lists, for every key of the report, the JSON types it may
hold. A change to the report that adds, removes, renames or retypes a key fails here, which
is the cue to decide whether it needs a new ``schema_version``.

The checker is exercised on deliberately damaged reports so it cannot pass vacuously.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from cli.tests.support import shape
from cli.tests.test_e2e_project import PURLS, Run, run_cli
from cli.tests.test_e2e_purl import run_purl

SCHEMA_PATH = Path(__file__).resolve().parent / "fixtures" / "report_v1_shape.json"
ANY = "any"


def load_schema() -> dict[str, Any]:
    loaded = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    loaded.pop("$comment")
    return loaded


def check(value: object, schema: object, path: str = "$") -> list[str]:
    """Return one message per mismatch between ``value`` and ``schema``."""
    if isinstance(schema, list):  # a leaf: the allowed type names
        allowed = {str(name) for name in schema}
        if ANY in allowed:
            return []
        if isinstance(value, (dict, list)):
            return [f"{path}: expected {sorted(allowed)}, got {type(value).__name__}"]
        actual = shape(value)
        if actual in allowed or (actual == "integer" and "number" in allowed):
            return []
        return [f"{path}: expected {sorted(allowed)}, got {actual}"]
    assert isinstance(schema, dict)
    if "$items" in schema:
        if not isinstance(value, list):
            return [f"{path}: expected an array, got {type(value).__name__}"]
        return [
            problem
            for index, item in enumerate(value)
            for problem in check(item, schema["$items"], f"{path}[{index}]")
        ]
    if "$values" in schema:
        if not isinstance(value, dict):
            return [f"{path}: expected an object, got {type(value).__name__}"]
        return [
            problem
            for key, item in value.items()
            for problem in check(item, schema["$values"], f"{path}.{key}")
        ]
    if not isinstance(value, dict):
        return [f"{path}: expected an object, got {type(value).__name__}"]
    problems: list[str] = []
    if list(value) != list(schema):
        missing = [k for k in schema if k not in value]
        extra = [k for k in value if k not in schema]
        if missing or extra:
            problems.append(f"{path}: missing keys {missing}, unexpected keys {extra}")
        else:
            problems.append(f"{path}: keys are in a different order: {list(value)}")
    for key, sub in schema.items():
        if key in value:
            problems.extend(check(value[key], sub, f"{path}.{key}"))
    return problems


@pytest.fixture(scope="module")
def report(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    result: Run = run_cli(tmp_path_factory.mktemp("shape"), "run")
    assert result.code == 0
    return result.report


# --------------------------------------------------------------------- the real report


def test_project_mode_report_matches_the_shape(report: dict[str, Any]) -> None:
    assert check(report, load_schema()) == []


def test_the_shape_file_covers_every_key_of_the_report(report: dict[str, Any]) -> None:
    schema = load_schema()
    assert list(schema) == list(report)
    assert list(schema["packages"]["$items"]) == list(report["packages"][0])
    assert list(schema["summary"]) == list(report["summary"])


def test_purl_mode_report_matches_the_same_shape(tmp_path: Path) -> None:
    """T10.5: one shape file covers both modes; the graph fields are null in --purl mode."""
    result = run_purl(tmp_path, "--purl", PURLS["request"], "--fail-on", "dead")
    assert result.code == 1
    assert check(result.report, load_schema()) == []
    package = result.report["packages"][0]
    assert (package["services_affected"], package["direct"], package["scope"]) == (None, None, None)


def test_purl_and_project_reports_have_the_same_keys(
    report: dict[str, Any], tmp_path: Path
) -> None:
    purl_report = run_purl(tmp_path, "--purl", PURLS["express"]).report
    assert list(purl_report) == list(report)
    assert list(purl_report["packages"][0]) == list(report["packages"][0])
    assert list(purl_report["summary"]) == list(report["summary"])
    assert list(purl_report["input"]) == list(report["input"])


# ----------------------------------------------------- the checker catches damage (not vacuous)


def _damaged(report: dict[str, Any], mutate: Any) -> list[str]:
    copied = copy.deepcopy(report)
    mutate(copied)
    return check(copied, load_schema())


def test_an_extra_top_level_key_is_caught(report: dict[str, Any]) -> None:
    problems = _damaged(report, lambda r: r.update(extra=1))
    assert any("unexpected keys ['extra']" in p for p in problems)


def test_a_missing_package_key_is_caught(report: dict[str, Any]) -> None:
    problems = _damaged(report, lambda r: r["packages"][0].pop("why"))
    assert any("missing keys ['why']" in p for p in problems)


def test_a_renamed_key_is_caught(report: dict[str, Any]) -> None:
    def rename(r: dict[str, Any]) -> None:
        r["summary"]["exit"] = r["summary"].pop("exit_code")

    problems = _damaged(report, rename)
    assert any("exit_code" in p for p in problems)


def test_a_retyped_value_is_caught(report: dict[str, Any]) -> None:
    def retype(r: dict[str, Any]) -> None:
        r["packages"][0]["rank"] = "1"

    problems = _damaged(report, retype)
    assert problems == ["$.packages[0].rank: expected ['integer'], got string"]


def test_a_bool_is_not_an_integer(report: dict[str, Any]) -> None:
    def retype(r: dict[str, Any]) -> None:
        r["summary"]["packages"] = True

    assert _damaged(report, retype) == ["$.summary.packages: expected ['integer'], got boolean"]


def test_a_float_is_not_an_integer_but_an_integer_is_a_number(report: dict[str, Any]) -> None:
    def floaty(r: dict[str, Any]) -> None:
        r["summary"]["packages"] = 9.0

    def inty(r: dict[str, Any]) -> None:
        r["packages"][0]["confidence"] = 1

    assert _damaged(report, floaty)
    assert _damaged(report, inty) == []


def test_null_where_null_is_not_allowed_is_caught(report: dict[str, Any]) -> None:
    def nullify(r: dict[str, Any]) -> None:
        r["packages"][0]["why"] = None

    assert _damaged(report, nullify) == ["$.packages[0].why: expected ['string'], got null"]


def test_nullable_fields_accept_null(report: dict[str, Any]) -> None:
    def purl_mode(r: dict[str, Any]) -> None:
        for package in r["packages"]:
            package.update(services_affected=None, direct=None, scope=None)
            package.update(manifests=[], path_infos=[], example_paths=[])
        r["input"].update(mode="purl", syft_version=None, services=[], lockfiles=[])

    assert _damaged(report, purl_mode) == []


def test_key_order_is_part_of_the_shape(report: dict[str, Any]) -> None:
    def reorder(r: dict[str, Any]) -> None:
        first = r["packages"][0]
        r["packages"][0] = dict(reversed(list(first.items())))

    problems = _damaged(report, reorder)
    assert any("different order" in p for p in problems)


def test_a_bad_evidence_entry_is_caught(report: dict[str, Any]) -> None:
    def bad(r: dict[str, Any]) -> None:
        r["packages"][0]["evidence"]["s2_latest_release_at"]["fetched_at"] = 5

    problems = _damaged(report, bad)
    assert problems == [
        "$.packages[0].evidence.s2_latest_release_at.fetched_at: "
        "expected ['null', 'string'], got integer"
    ]
