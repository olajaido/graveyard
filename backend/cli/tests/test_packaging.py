"""Packaging guard for backend/pyproject.toml (CLI-DEP-3, CLI-DEP-6)."""

from __future__ import annotations

import copy
import re
import tomllib
from pathlib import Path
from typing import Any

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"

_HATCHLING_PIN = re.compile(r"^hatchling==\d+(\.\d+)*$")
_REQUIRED_PACKAGES = ("core", "sources", "cli")


def _table(data: object, *keys: str) -> dict[str, Any]:
    """Walk nested tables; return an empty dict if any step is missing or not a table."""
    current: object = data
    for key in keys:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    return current if isinstance(current, dict) else {}


def check_packaging(data: dict[str, Any]) -> list[str]:
    """Return the list of packaging problems found in parsed pyproject data."""
    problems: list[str] = []

    build = _table(data, "build-system")
    requires = build.get("requires")
    entries = requires if isinstance(requires, list) else []
    hatchling = [e for e in entries if isinstance(e, str) and e.startswith("hatchling")]
    if not hatchling:
        problems.append("build-system.requires has no hatchling entry")
    elif not all(_HATCHLING_PIN.match(e) for e in hatchling):
        problems.append(f"hatchling must be pinned exactly with '==', got {hatchling}")

    if build.get("build-backend") != "hatchling.build":
        problems.append("build-system.build-backend must be 'hatchling.build'")

    if _table(data, "tool", "uv").get("package") is not True:
        problems.append("tool.uv.package must be true")

    if _table(data, "project", "scripts").get("graveyard") != "cli.__main__:main":
        problems.append("project.scripts.graveyard must be 'cli.__main__:main'")

    packages = _table(data, "tool", "hatch", "build", "targets", "wheel").get("packages")
    listed = packages if isinstance(packages, list) else []
    for name in _REQUIRED_PACKAGES:
        if name not in listed:
            problems.append(f"wheel packages is missing '{name}'")

    return problems


def _good() -> dict[str, Any]:
    return {
        "build-system": {"requires": ["hatchling==1.33.0"], "build-backend": "hatchling.build"},
        "project": {"scripts": {"graveyard": "cli.__main__:main"}},
        "tool": {
            "uv": {"package": True},
            "hatch": {"build": {"targets": {"wheel": {"packages": ["core", "sources", "cli"]}}}},
        },
    }


def test_real_pyproject_has_no_packaging_problems() -> None:
    with PYPROJECT.open("rb") as handle:
        data = tomllib.load(handle)
    assert check_packaging(data) == []


def test_checker_accepts_good_sample() -> None:
    assert check_packaging(_good()) == []


def test_checker_rejects_range_pin() -> None:
    data = _good()
    data["build-system"]["requires"] = ["hatchling>=1.33.0"]
    assert any("hatchling" in p for p in check_packaging(data))


def test_checker_rejects_missing_hatchling() -> None:
    data = _good()
    data["build-system"]["requires"] = ["setuptools==70.0.0"]
    assert any("no hatchling" in p for p in check_packaging(data))


def test_checker_rejects_wrong_backend() -> None:
    data = _good()
    data["build-system"]["build-backend"] = "setuptools.build_meta"
    assert any("build-backend" in p for p in check_packaging(data))


def test_checker_rejects_package_false() -> None:
    data = _good()
    data["tool"]["uv"]["package"] = False
    assert any("tool.uv.package" in p for p in check_packaging(data))


def test_checker_rejects_missing_script() -> None:
    data = _good()
    del data["project"]["scripts"]["graveyard"]
    assert any("project.scripts" in p for p in check_packaging(data))


def test_checker_rejects_wrong_script_target() -> None:
    data = _good()
    data["project"]["scripts"]["graveyard"] = "cli:main"
    assert any("project.scripts" in p for p in check_packaging(data))


def test_checker_rejects_each_missing_wheel_package() -> None:
    for name in _REQUIRED_PACKAGES:
        data = copy.deepcopy(_good())
        wheel = data["tool"]["hatch"]["build"]["targets"]["wheel"]
        wheel["packages"] = [p for p in wheel["packages"] if p != name]
        assert check_packaging(data) == [f"wheel packages is missing '{name}'"]


def test_checker_reports_everything_on_empty_data() -> None:
    assert len(check_packaging({})) == 7
