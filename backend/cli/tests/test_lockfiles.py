"""Unit tests for lockfile reading and scope merging (CLI-SCOPE-1…5)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

from cli.lockfiles import MAX_LOCKFILE_BYTES, merge_scopes, read_scopes
from cli.model import CliWarning, ServiceDir
from core.graph import GraphWarning, ScopeResult
from core.graph.model import MAX_LOCKFILE_CHARS, Scope

FIXTURES = Path(__file__).resolve().parents[2] / "core" / "graph" / "tests" / "fixtures"


def _service(directory: Path, *names: str) -> ServiceDir:
    return ServiceDir(path="svc", directory=directory, lockfiles=tuple(sorted(names)))


def _copy(directory: Path, fixture: str, name: str) -> None:
    (directory / name).write_bytes((FIXTURES / fixture).read_bytes())


def _assert_one_unreadable(
    service: ServiceDir,
    used: tuple[tuple[str, bool], ...],
    warnings: tuple[CliWarning, ...],
    name: str,
) -> None:
    assert len(warnings) == 1
    warning = warnings[0]
    assert warning.code == "LOCKFILE_UNREADABLE"
    assert name in warning.detail
    assert warning.service == service.path
    assert used == ((name, False),)


def _scope(package: Mapping[str, Scope], direct: Mapping[str, Scope] | None = None) -> ScopeResult:
    return ScopeResult(
        package_scopes=MappingProxyType(dict(package)),
        direct_scopes=MappingProxyType(dict(direct or {})),
        warnings=(),
    )


# --- the four parsers ---------------------------------------------------------------------


def test_each_parser_is_used_for_its_file_name(tmp_path: Path) -> None:
    cases = (
        ("lock_npm.json", "package-lock.json"),
        ("lock_uv.toml", "uv.lock"),
        ("lock_poetry.toml", "poetry.lock"),
        ("requirements.txt", "requirements.txt"),
    )
    for fixture, name in cases:
        directory = tmp_path / name.replace(".", "_")
        directory.mkdir()
        _copy(directory, fixture, name)
        service = _service(directory, name)
        scopes, warnings, used = read_scopes(service)
        assert scopes is not None, name
        assert scopes.package_scopes, name
        assert used == ((name, True),)
        assert not [w for w in warnings if w.code == "LOCKFILE_UNREADABLE"]


def test_requirements_dev_name_is_parsed(tmp_path: Path) -> None:
    _copy(tmp_path, "requirements.txt", "requirements-dev.txt")
    scopes, _, used = read_scopes(_service(tmp_path, "requirements-dev.txt"))
    assert scopes is not None
    assert used == (("requirements-dev.txt", True),)


def test_npm_dev_package_is_dev(tmp_path: Path) -> None:
    _copy(tmp_path, "lock_npm_dev.json", "package-lock.json")
    scopes, warnings, used = read_scopes(_service(tmp_path, "package-lock.json"))
    assert scopes is not None
    assert scopes.package_scopes["npm/is-number@7.0.0"] == "dev"
    assert scopes.package_scopes["npm/left-pad@1.3.0"] == "runtime"
    assert warnings == ()
    assert used == (("package-lock.json", True),)


# --- failure cases ------------------------------------------------------------------------


def test_invalid_toml_uv_lock(tmp_path: Path) -> None:
    (tmp_path / "uv.lock").write_text("this is = = not toml [", encoding="utf-8")
    service = _service(tmp_path, "uv.lock")
    scopes, warnings, used = read_scopes(service)
    assert scopes is None
    _assert_one_unreadable(service, used, warnings, "uv.lock")


def test_non_utf8_package_lock(tmp_path: Path) -> None:
    (tmp_path / "package-lock.json").write_bytes(b'{"a": "\xff\xfe"}')
    service = _service(tmp_path, "package-lock.json")
    scopes, warnings, used = read_scopes(service)
    assert scopes is None
    _assert_one_unreadable(service, used, warnings, "package-lock.json")


def test_file_over_parser_char_limit(tmp_path: Path) -> None:
    (tmp_path / "package-lock.json").write_text("a" * (MAX_LOCKFILE_CHARS + 1), encoding="utf-8")
    service = _service(tmp_path, "package-lock.json")
    scopes, warnings, used = read_scopes(service)
    assert scopes is None
    _assert_one_unreadable(service, used, warnings, "package-lock.json")


def test_file_over_max_lockfile_bytes_sparse(tmp_path: Path) -> None:
    with open(tmp_path / "uv.lock", "wb") as handle:
        handle.truncate(MAX_LOCKFILE_BYTES + 1)
    service = _service(tmp_path, "uv.lock")
    scopes, warnings, used = read_scopes(service)
    assert scopes is None
    _assert_one_unreadable(service, used, warnings, "uv.lock")


def test_json_v1_lockfile(tmp_path: Path) -> None:
    doc = {"name": "old", "version": "1.0.0", "lockfileVersion": 1, "dependencies": {}}
    (tmp_path / "package-lock.json").write_text(json.dumps(doc), encoding="utf-8")
    service = _service(tmp_path, "package-lock.json")
    scopes, warnings, used = read_scopes(service)
    assert scopes is None
    _assert_one_unreadable(service, used, warnings, "package-lock.json")


def test_good_uv_lock_with_bad_requirements(tmp_path: Path) -> None:
    _copy(tmp_path, "lock_uv.toml", "uv.lock")
    (tmp_path / "requirements.txt").write_bytes(b"\xff\xfe\x00bad")
    service = _service(tmp_path, "requirements.txt", "uv.lock")
    scopes, warnings, used = read_scopes(service)
    assert scopes is not None
    assert any(key.endswith("six@1.17.0") for key in scopes.package_scopes)
    unreadable = [w for w in warnings if w.code == "LOCKFILE_UNREADABLE"]
    assert len(unreadable) == 1
    assert "requirements.txt" in unreadable[0].detail
    assert used == (("requirements.txt", False), ("uv.lock", True))


def test_all_unusable_returns_none(tmp_path: Path) -> None:
    (tmp_path / "uv.lock").write_text("= =", encoding="utf-8")
    (tmp_path / "package-lock.json").write_bytes(b"\xff")
    service = _service(tmp_path, "package-lock.json", "uv.lock")
    scopes, warnings, used = read_scopes(service)
    assert scopes is None
    assert len(warnings) == 2
    assert used == (("package-lock.json", False), ("uv.lock", False))


# --- merge --------------------------------------------------------------------------------


def test_merge_runtime_wins_either_order() -> None:
    runtime = _scope({"a@1": "runtime", "b@1": "dev"}, {"a@1": "runtime"})
    dev = _scope({"a@1": "dev", "b@1": "dev", "c@1": "dev"}, {"a@1": "dev"})
    for order in ((runtime, dev), (dev, runtime)):
        merged = merge_scopes(order)
        assert merged.package_scopes["a@1"] == "runtime"
        assert merged.package_scopes["b@1"] == "dev"
        assert merged.direct_scopes["a@1"] == "runtime"
        assert list(merged.package_scopes) == ["a@1", "b@1", "c@1"]


def test_merge_warnings_sorted_union() -> None:
    w1 = GraphWarning(code="REQUIREMENT_SKIPPED", detail="x", subjects=("b",))
    w2 = GraphWarning(code="DIRECT_UNRESOLVED", detail="y", subjects=("a",))
    first = ScopeResult(MappingProxyType({}), MappingProxyType({}), (w1, w2))
    second = ScopeResult(MappingProxyType({}), MappingProxyType({}), (w1,))
    merged = merge_scopes([first, second])
    assert merged.warnings == (w2, w1)
