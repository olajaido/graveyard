"""Unit tests for service discovery (CLI-DISC-1…3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cli.discover import find_services
from cli.errors import CliError
from core.graph.model import DEFAULT_MAX_SERVICES


def _touch(root: Path, relative: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")


def _paths(root: Path) -> list[str]:
    return [service.path for service in find_services(root)]


def test_root_only(tmp_path: Path) -> None:
    _touch(tmp_path, "package-lock.json")
    services = find_services(tmp_path)
    assert [s.path for s in services] == ["."]
    assert services[0].directory == tmp_path
    assert services[0].lockfiles == ("package-lock.json",)


def test_two_services(tmp_path: Path) -> None:
    _touch(tmp_path, "api/uv.lock")
    _touch(tmp_path, "web/package-lock.json")
    assert _paths(tmp_path) == ["api", "web"]


def test_nested_service_under_another(tmp_path: Path) -> None:
    _touch(tmp_path, "uv.lock")
    _touch(tmp_path, "svc/poetry.lock")
    assert _paths(tmp_path) == [".", "svc"]


def test_ignored_directories(tmp_path: Path) -> None:
    _touch(tmp_path, "node_modules/x/package-lock.json")
    _touch(tmp_path, ".venv/uv.lock")
    _touch(tmp_path, ".git/hooks/uv.lock")
    _touch(tmp_path, "venv/uv.lock")
    _touch(tmp_path, "__pycache__/uv.lock")
    _touch(tmp_path, "lib/site-packages/uv.lock")
    _touch(tmp_path, "real/uv.lock")
    assert _paths(tmp_path) == ["real"]


def test_symlinked_lockfile_ignored(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("x", encoding="utf-8")
    (tmp_path / "svc").mkdir()
    (tmp_path / "svc" / "uv.lock").symlink_to(target)
    _touch(tmp_path, "ok/uv.lock")
    assert _paths(tmp_path) == ["ok"]


def test_symlinked_directory_not_followed(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    _touch(outside, "uv.lock")
    root = tmp_path / "root"
    root.mkdir()
    _touch(root, "package-lock.json")
    (root / "link").symlink_to(outside, target_is_directory=True)
    assert _paths(root) == ["."]


def test_requirements_names(tmp_path: Path) -> None:
    for name in (
        "requirements.txt",
        "requirements-dev.txt",
        "requirements.txt.bak",
        "my-requirements.txt",
    ):
        _touch(tmp_path, name)
    services = find_services(tmp_path)
    assert services[0].lockfiles == ("requirements-dev.txt", "requirements.txt")


def test_output_sorted(tmp_path: Path) -> None:
    for name in ("zeta", "alpha", "mid/inner", "beta"):
        _touch(tmp_path, f"{name}/uv.lock")
    paths = _paths(tmp_path)
    assert paths == sorted(paths)
    assert paths == ["alpha", "beta", "mid/inner", "zeta"]


def test_lockfiles_sorted_within_service(tmp_path: Path) -> None:
    for name in ("uv.lock", "poetry.lock", "package-lock.json"):
        _touch(tmp_path, name)
    assert find_services(tmp_path)[0].lockfiles == ("package-lock.json", "poetry.lock", "uv.lock")


def test_limit_is_accepted_and_one_more_is_refused(tmp_path: Path) -> None:
    for i in range(DEFAULT_MAX_SERVICES):
        _touch(tmp_path, f"s{i:02d}/uv.lock")
    assert len(find_services(tmp_path)) == DEFAULT_MAX_SERVICES
    _touch(tmp_path, "s99/uv.lock")
    with pytest.raises(CliError):
        find_services(tmp_path)


def test_51_services_refused(tmp_path: Path) -> None:
    for i in range(51):
        _touch(tmp_path, f"s{i:02d}/uv.lock")
    with pytest.raises(CliError):
        find_services(tmp_path)


def test_glob_character_in_path_refused(tmp_path: Path) -> None:
    _touch(tmp_path, "a[1]/uv.lock")
    with pytest.raises(CliError):
        find_services(tmp_path)


def test_empty_tree_mentions_sbom(tmp_path: Path) -> None:
    with pytest.raises(CliError, match="--sbom"):
        find_services(tmp_path)
