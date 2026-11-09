"""Unit tests for ``parse_uv_lock`` (DG-SCP-0, DG-SCP-5, DG-SCP-7, DG-WARN-1, DG-EX-21).

Expectations for the real fixtures (``lock_uv_backend.toml``, ``lock_uv.toml``)
are recomputed here from the file with plain ``tomllib`` code and a naive
fixed-point reachability loop; ``parse_uv_lock`` is never used to compute an
expectation. Expected keys come from ``core.graph.keys.pypi_key``. The
synthetic file (``lock_uv_edge.toml``) is checked against the table in
``fixtures/README.md``. Fixtures resolve via ``Path(__file__).parent``.
"""

import json
import re
import tomllib
from collections.abc import Iterable
from pathlib import Path
from typing import Any, cast

import pytest

from core.graph.keys import pypi_key
from core.graph.model import MAX_LOCKFILE_CHARS, WARNING_CODES, Scope, ScopeResult
from core.graph.scopes_uv import parse_uv_lock
from core.purl import package_key, parse_purl

FIXTURES = Path(__file__).parent / "fixtures"
REGISTRY = '{ registry = "https://pypi.org/simple" }'


# --- independent reference implementation (tomllib only) -------------------


def norm(name: str) -> str:
    """PEP 503 name normalisation, written out here rather than imported."""
    return re.sub(r"[-_.]+", "-", name).lower()


def is_project(entry: dict[str, Any]) -> bool:
    source = entry.get("source", {})
    return "virtual" in source or "editable" in source


def expected_scopes(doc: dict[str, Any]) -> tuple[dict[str, Scope], dict[str, Scope]]:
    """Return ``(package_scopes, direct_scopes)`` by naive fixed-point reachability."""
    pkgs: list[dict[str, Any]] = doc["package"]

    def matches(ref: dict[str, Any]) -> set[int]:
        return {
            i
            for i, p in enumerate(pkgs)
            if norm(p["name"]) == norm(ref["name"])
            and ("version" not in ref or p.get("version") == ref["version"])
        }

    def outgoing(p: dict[str, Any]) -> set[int]:
        refs = list(p.get("dependencies", []))
        for group in p.get("optional-dependencies", {}).values():
            refs.extend(group)
        return {i for ref in refs for i in matches(ref)}

    def reach(seeds: set[int]) -> set[int]:
        seen = set(seeds)
        changed = True
        while changed:
            changed = False
            for i in sorted(seen):
                new = outgoing(pkgs[i]) - seen
                if new:
                    seen |= new
                    changed = True
        return seen

    projects = [p for p in pkgs if is_project(p)]
    runtime_seeds = {i for p in projects for i in outgoing(p)}
    dev_seeds = {
        i
        for p in projects
        for group in p.get("dev-dependencies", {}).values()
        for ref in group
        for i in matches(ref)
    }
    runtime, dev = reach(runtime_seeds), reach(dev_seeds)

    package_scopes: dict[str, Scope] = {}
    direct_scopes: dict[str, Scope] = {}
    for i, p in enumerate(pkgs):
        if is_project(p):
            continue
        key = pypi_key(p["name"], p["version"])
        package_scopes[key] = "dev" if i in dev and i not in runtime else "runtime"
        if i in runtime_seeds:
            direct_scopes[key] = "runtime"
        elif i in dev_seeds:
            direct_scopes[key] = "dev"
    return package_scopes, direct_scopes


def syft_library_keys_without_root(bom: dict[str, Any]) -> tuple[str, set[str]]:
    """Return ``(root_key, keys of every other library component)`` of a Syft SBOM."""
    referenced = {t for d in bom["dependencies"] for t in d.get("dependsOn", [])}
    (root_ref,) = {d["ref"] for d in bom["dependencies"]} - referenced
    root_key = ""
    others: set[str] = set()
    for c in bom["components"]:
        if c["type"] != "library":
            continue
        key = package_key(parse_purl(c["purl"]))
        if c["bom-ref"] == root_ref:
            root_key = key
        else:
            others.add(key)
    return root_key, others


# --- helpers ---------------------------------------------------------------


def read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def refs(items: Iterable[str | tuple[str, str]]) -> str:
    """TOML array of ``{ name, version? }`` references."""
    parts = []
    for item in items:
        name, version = (item, None) if isinstance(item, str) else item
        parts.append(
            f'{{ name = "{name}" }}'
            if version is None
            else f'{{ name = "{name}", version = "{version}" }}'
        )
    return "[" + ", ".join(parts) + "]"


def table(
    name: str,
    version: str | None,
    *,
    source: str = REGISTRY,
    deps: Iterable[str | tuple[str, str]] = (),
    optional: Iterable[str | tuple[str, str]] = (),
    dev: Iterable[str | tuple[str, str]] = (),
) -> str:
    out = f'[[package]]\nname = "{name}"\n'
    if version is not None:
        out += f'version = "{version}"\n'
    out += f"source = {source}\n"
    out += f"dependencies = {refs(deps)}\n"
    if optional:
        out += f"[package.optional-dependencies]\nextra = {refs(optional)}\n"
    if dev:
        out += f"[package.dev-dependencies]\ngroup = {refs(dev)}\n"
    return out


def project(
    deps: Iterable[str | tuple[str, str]] = (),
    *,
    optional: Iterable[str | tuple[str, str]] = (),
    dev: Iterable[str | tuple[str, str]] = (),
    source: str = '{ virtual = "." }',
    name: str = "proj",
    version: str | None = "0.0.1",
) -> str:
    return table(name, version, source=source, deps=deps, optional=optional, dev=dev)


def lock(*tables: str) -> str:
    return "version = 1\nrevision = 3\n" + "".join(tables)


def k(name: str, version: str) -> str:
    return pypi_key(name, version)


def codes(result: ScopeResult) -> list[str]:
    return [w.code for w in result.warnings]


def subjects(result: ScopeResult, code: str) -> list[tuple[str, ...]]:
    return [w.subjects for w in result.warnings if w.code == code]


# --- DG-EX-21: real fixture with a dev group -------------------------------

BACKEND_RUNTIME = {"packageurl-python", "pyyaml"}
BACKEND_DEV_DIRECT = {"hypothesis", "mypy", "pytest", "pytest-cov", "ruff", "types-pyyaml"}


def test_backend_package_scopes_recomputed_from_the_file() -> None:
    text = read("lock_uv_backend.toml")
    doc = tomllib.loads(text)
    result = parse_uv_lock(text)

    package_scopes, _ = expected_scopes(doc)
    assert dict(result.package_scopes) == package_scopes
    # Pinned figures, and the independent recomputation agrees with them.
    assert len(doc["package"]) == 21
    assert len(package_scopes) == 20
    assert sum(1 for s in package_scopes.values() if s == "runtime") == 2
    assert sum(1 for s in package_scopes.values() if s == "dev") == 18
    assert len(result.package_scopes) == 20
    assert sum(1 for s in result.package_scopes.values() if s == "runtime") == 2
    assert sum(1 for s in result.package_scopes.values() if s == "dev") == 18
    runtime_names = {
        key.split("/")[1].split("@")[0] for key, s in package_scopes.items() if s == "runtime"
    }
    assert runtime_names == BACKEND_RUNTIME


def test_backend_transitive_packages_are_dev() -> None:
    result = parse_uv_lock(read("lock_uv_backend.toml"))
    for name, version in [
        ("coverage", "7.17.2"),
        ("sortedcontainers", "2.4.0"),
        ("typing-extensions", "4.16.0"),
    ]:
        assert result.package_scopes[k(name, version)] == "dev"


def test_backend_direct_scopes_and_project_package_absent() -> None:
    text = read("lock_uv_backend.toml")
    doc = tomllib.loads(text)
    result = parse_uv_lock(text)

    _, direct_scopes = expected_scopes(doc)
    assert dict(result.direct_scopes) == direct_scopes
    assert len(direct_scopes) == 8
    by_name = {key.split("/")[1].split("@")[0]: s for key, s in direct_scopes.items()}
    assert by_name == {
        **dict.fromkeys(BACKEND_RUNTIME, "runtime"),
        **dict.fromkeys(BACKEND_DEV_DIRECT, "dev"),
    }
    assert sum(1 for s in result.direct_scopes.values() if s == "runtime") == 2
    assert sum(1 for s in result.direct_scopes.values() if s == "dev") == 6
    # The project package is absent from both maps.
    (project_entry,) = [p for p in doc["package"] if is_project(p)]
    assert project_entry["name"] == "graveyard-backend"
    for key in (*result.package_scopes, *result.direct_scopes):
        assert "graveyard-backend" not in key


def test_backend_has_no_warnings() -> None:
    assert parse_uv_lock(read("lock_uv_backend.toml")).warnings == ()


# --- DG-EX-21: real fixture, runtime only ----------------------------------


def test_lock_uv_every_package_is_runtime_and_covers_syft_nodes() -> None:
    text = read("lock_uv.toml")
    doc = tomllib.loads(text)
    result = parse_uv_lock(text)

    package_scopes, direct_scopes = expected_scopes(doc)
    assert set(package_scopes.values()) == {"runtime"}
    assert dict(result.package_scopes) == package_scopes
    assert result.warnings == ()

    root_key, others = syft_library_keys_without_root(json.loads(read("syft_py.cdx.json")))
    assert root_key == "pypi/graveyard-spike-py-fixture@0.0.1"
    assert root_key not in result.package_scopes  # virtual project package (DG-SCP-7)
    assert root_key not in result.direct_scopes
    assert len(others) == 7
    assert others <= set(result.package_scopes)
    assert set(result.package_scopes) == others  # nothing else in the lockfile


def test_lock_uv_direct_scopes_are_nose_requests_six() -> None:
    text = read("lock_uv.toml")
    doc = tomllib.loads(text)
    result = parse_uv_lock(text)

    _, direct_scopes = expected_scopes(doc)
    assert dict(result.direct_scopes) == direct_scopes
    assert set(result.direct_scopes) == {
        k("nose", "1.3.7"),
        k("requests", "2.34.2"),
        k("six", "1.17.0"),
    }
    assert set(result.direct_scopes.values()) == {"runtime"}


# --- DG-EX-21: synthetic edge fixture --------------------------------------

EDGE_TEXT = read("lock_uv_edge.toml")

CERTIFI = k("certifi", "2024.8.30")
CHARSET = k("charset-normalizer", "3.4.0")
HTTPX = k("httpx", "0.27.2")
IDNA = k("idna", "3.10")
PLUGGY = k("pluggy", "1.5.0")
PYSOCKS = k("pysocks", "1.7.1")
PYTEST = k("pytest", "8.3.3")
PYYAML = k("pyyaml", "6.0.2")
REQUESTS = k("requests", "2.32.3")
SIX = k("six", "1.16.0")
TYPING_OLD = k("typing-extensions", "4.10.0")
TYPING_NEW = k("typing-extensions", "4.12.2")
URLLIB3 = k("urllib3", "2.2.3")


def test_edge_whole_file_expectations() -> None:
    result = parse_uv_lock(EDGE_TEXT)
    dev = {HTTPX, PLUGGY, PYTEST, TYPING_OLD}
    runtime = {
        CERTIFI,
        CHARSET,
        IDNA,
        PYSOCKS,
        PYYAML,
        REQUESTS,
        SIX,
        TYPING_NEW,
        URLLIB3,
    }
    assert dict(result.package_scopes) == {
        **dict.fromkeys(runtime, "runtime"),
        **dict.fromkeys(dev, "dev"),
    }
    assert len(result.package_scopes) == 13
    assert dict(result.direct_scopes) == {
        REQUESTS: "runtime",
        PYYAML: "runtime",
        HTTPX: "dev",
        PYTEST: "dev",
    }
    # Independent recomputation from the file agrees (it ignores the unresolved `tomli`).
    package_scopes, direct_scopes = expected_scopes(tomllib.loads(EDGE_TEXT))
    assert dict(result.package_scopes) == package_scopes
    assert dict(result.direct_scopes) == direct_scopes
    # Maps iterate in sorted key order (deterministic output).
    assert list(result.package_scopes) == sorted(result.package_scopes)
    assert list(result.direct_scopes) == sorted(result.direct_scopes)


@pytest.mark.parametrize(
    ("key", "scope"),
    [
        pytest.param(CERTIFI, "runtime", id="both-seeds-certifi"),
        pytest.param(IDNA, "runtime", id="both-seeds-idna"),
        pytest.param(PYSOCKS, "runtime", id="optional-dependency-of-a-package"),
        pytest.param(PYYAML, "runtime", id="optional-dependency-of-the-project"),
        pytest.param(PYTEST, "dev", id="dev-cycle-pytest"),
        pytest.param(PLUGGY, "dev", id="dev-cycle-pluggy"),
        pytest.param(TYPING_NEW, "runtime", id="typing-extensions-via-urllib3"),
        pytest.param(TYPING_OLD, "dev", id="typing-extensions-via-pytest"),
        pytest.param(SIX, "runtime", id="reachable-from-no-seed"),
        pytest.param(REQUESTS, "runtime", id="runtime-closure-requests"),
        pytest.param(CHARSET, "runtime", id="runtime-closure-charset"),
        pytest.param(URLLIB3, "runtime", id="runtime-closure-urllib3"),
        pytest.param(HTTPX, "dev", id="plain-dev-seed"),
    ],
)
def test_edge_package_scope_cases(key: str, scope: str) -> None:
    assert parse_uv_lock(EDGE_TEXT).package_scopes[key] == scope


def test_edge_declared_and_undeclared_keys() -> None:
    result = parse_uv_lock(EDGE_TEXT)
    undeclared = {CERTIFI, IDNA, PYSOCKS, PLUGGY, TYPING_OLD, TYPING_NEW, SIX, CHARSET, URLLIB3}
    assert undeclared.isdisjoint(result.direct_scopes)
    assert result.direct_scopes[PYYAML] == "runtime"  # project's own optional-dependencies


def test_edge_unresolved_tomli_gives_exactly_one_warning() -> None:
    result = parse_uv_lock(EDGE_TEXT)
    (warning,) = [w for w in result.warnings if w.code == "DIRECT_UNRESOLVED"]
    assert warning.subjects == ("tomli",)
    assert warning.service is None
    assert not any("tomli" in key for key in (*result.package_scopes, *result.direct_scopes))


def test_edge_no_other_warnings_and_no_scope_disagreement() -> None:
    result = parse_uv_lock(EDGE_TEXT)
    assert codes(result) == ["DIRECT_UNRESOLVED"]
    assert "SCOPE_DISAGREEMENT" not in codes(result)
    assert all(w.code in WARNING_CODES for w in result.warnings)


def test_edge_project_package_is_absent() -> None:
    result = parse_uv_lock(EDGE_TEXT)
    for key in (*result.package_scopes, *result.direct_scopes):
        assert "edge-fixture" not in key


# --- inline synthetic cases ------------------------------------------------


def test_editable_source_is_a_project_package() -> None:
    text = lock(
        table("a", "1.0"),
        project(["a"], source='{ editable = "." }'),
    )
    result = parse_uv_lock(text)
    assert dict(result.package_scopes) == {k("a", "1.0"): "runtime"}
    assert dict(result.direct_scopes) == {k("a", "1.0"): "runtime"}
    assert result.warnings == ()


def test_registry_source_is_not_a_project_package() -> None:
    text = lock(table("a", "1.0", deps=["b"]), table("b", "1.0"))
    result = parse_uv_lock(text)
    assert set(result.package_scopes) == {k("a", "1.0"), k("b", "1.0")}
    assert dict(result.direct_scopes) == {}  # no project package, so no seeds
    assert result.warnings == ()


def test_project_package_without_version_is_accepted() -> None:
    text = lock(table("a", "1.0"), project(["a"], version=None))
    result = parse_uv_lock(text)
    assert dict(result.direct_scopes) == {k("a", "1.0"): "runtime"}
    assert result.warnings == ()


def test_reference_version_narrows_the_match() -> None:
    text = lock(
        table("a", "1.0"),
        table("a", "2.0"),
        project([("a", "1.0")], dev=[("a", "2.0")]),
    )
    result = parse_uv_lock(text)
    assert dict(result.package_scopes) == {k("a", "1.0"): "runtime", k("a", "2.0"): "dev"}
    assert dict(result.direct_scopes) == {k("a", "1.0"): "runtime", k("a", "2.0"): "dev"}
    assert result.warnings == ()


def test_reference_without_version_matches_every_version() -> None:
    text = lock(table("a", "1.0"), table("a", "2.0"), project(["a"]))
    result = parse_uv_lock(text)
    assert dict(result.direct_scopes) == {k("a", "1.0"): "runtime", k("a", "2.0"): "runtime"}


def test_reference_with_non_string_version_is_ignored() -> None:
    text = lock(
        table("a", "1.0"),
        table("a", "2.0"),
        "[[package]]\n"
        'name = "proj"\nversion = "0.0.1"\nsource = { virtual = "." }\n'
        'dependencies = [{ name = "a", version = 1 }]\n',
    )
    result = parse_uv_lock(text)
    assert dict(result.direct_scopes) == {k("a", "1.0"): "runtime", k("a", "2.0"): "runtime"}
    assert result.warnings == ()


def test_reference_name_is_matched_after_normalisation() -> None:
    text = lock(table("foo-bar", "1.0"), project(["Foo_Bar"]))
    result = parse_uv_lock(text)
    assert dict(result.direct_scopes) == {k("foo-bar", "1.0"): "runtime"}
    assert result.warnings == ()


def test_seed_with_version_that_matches_nothing_is_unresolved() -> None:
    text = lock(table("a", "1.0"), project([("a", "9.9")]))
    result = parse_uv_lock(text)
    assert subjects(result, "DIRECT_UNRESOLVED") == [("a",)]
    assert dict(result.direct_scopes) == {}
    assert dict(result.package_scopes) == {k("a", "1.0"): "runtime"}  # reachable from no seed


def test_unresolved_dev_seed_is_reported() -> None:
    result = parse_uv_lock(lock(project(dev=["ghost"])))
    assert subjects(result, "DIRECT_UNRESOLVED") == [("ghost",)]
    assert dict(result.package_scopes) == {}
    assert dict(result.direct_scopes) == {}


def test_target_in_both_runtime_and_dev_seeds_is_runtime() -> None:
    text = lock(table("a", "1.0"), project(["a"], dev=["a"]))
    result = parse_uv_lock(text)
    assert dict(result.package_scopes) == {k("a", "1.0"): "runtime"}
    assert dict(result.direct_scopes) == {k("a", "1.0"): "runtime"}
    assert result.warnings == ()


def test_dev_group_targets_are_dev_across_all_groups() -> None:
    text = lock(
        table("a", "1.0"),
        table("b", "1.0"),
        "[[package]]\n"
        'name = "proj"\nversion = "0.0.1"\nsource = { virtual = "." }\n'
        "[package.dev-dependencies]\n"
        'lint = [{ name = "a" }]\n'
        'test = [{ name = "b" }]\n',
    )
    result = parse_uv_lock(text)
    assert dict(result.direct_scopes) == {k("a", "1.0"): "dev", k("b", "1.0"): "dev"}
    assert dict(result.package_scopes) == {k("a", "1.0"): "dev", k("b", "1.0"): "dev"}


def test_cycle_among_runtime_packages_terminates() -> None:
    text = lock(
        table("a", "1.0", deps=["b"]),
        table("b", "1.0", deps=["c"]),
        table("c", "1.0", deps=["a"]),
        project(["a"]),
    )
    result = parse_uv_lock(text)
    assert set(result.package_scopes.values()) == {"runtime"}
    assert len(result.package_scopes) == 3


def test_self_dependency_terminates() -> None:
    text = lock(table("a", "1.0", deps=["a"]), project(dev=["a"]))
    result = parse_uv_lock(text)
    assert dict(result.package_scopes) == {k("a", "1.0"): "dev"}


def test_unresolvable_edge_between_non_project_packages_is_silent() -> None:
    text = lock(table("a", "1.0", deps=["ghost", ("b", "9.9")]), table("b", "1.0"), project(["a"]))
    result = parse_uv_lock(text)
    assert dict(result.package_scopes) == {k("a", "1.0"): "runtime", k("b", "1.0"): "runtime"}
    assert dict(result.direct_scopes) == {k("a", "1.0"): "runtime"}
    assert result.warnings == ()


def test_workspace_member_reached_via_seed_adds_nothing_itself() -> None:
    text = lock(
        table("c", "1.0"),
        table("member", "0.1.0", source='{ editable = "member" }', deps=["c"]),
        project(["member"]),
    )
    result = parse_uv_lock(text)
    # The member is a project package: it is never listed, and it raises no warning.
    # Its own dependencies are seeds of their own (every project package seeds, DG-SCP-7).
    assert dict(result.package_scopes) == {k("c", "1.0"): "runtime"}
    assert dict(result.direct_scopes) == {k("c", "1.0"): "runtime"}
    assert result.warnings == ()
    for key in (*result.package_scopes, *result.direct_scopes):
        assert "member" not in key


def test_workspace_member_reached_via_dev_seed_adds_nothing_itself() -> None:
    text = lock(
        table("member", "0.1.0", source='{ virtual = "member" }'),
        project(dev=["member"]),
    )
    result = parse_uv_lock(text)
    assert dict(result.package_scopes) == {}
    assert dict(result.direct_scopes) == {}
    assert result.warnings == ()


def test_duplicate_entries_collapse_to_one_key() -> None:
    text = lock(table("Foo_Bar", "1.0"), table("foo-bar", "1.0"), project(dev=["foo.bar"]))
    result = parse_uv_lock(text)
    assert dict(result.package_scopes) == {k("foo-bar", "1.0"): "dev"}
    assert dict(result.direct_scopes) == {k("foo-bar", "1.0"): "dev"}


def test_duplicate_entries_collapse_to_runtime_when_runtime_reachable() -> None:
    text = lock(
        table("Foo_Bar", "1.0"), table("foo-bar", "1.0"), project(["foo.bar"], dev=["foo.bar"])
    )
    result = parse_uv_lock(text)
    assert dict(result.package_scopes) == {k("foo-bar", "1.0"): "runtime"}


def test_non_table_entry_is_skipped_with_warning() -> None:
    result = parse_uv_lock("package = [1]\n")
    assert dict(result.package_scopes) == {}
    (warning,) = result.warnings
    assert warning.code == "LOCKFILE_ENTRY_SKIPPED"
    assert warning.subjects == ("package[0]",)
    assert warning.service is None


@pytest.mark.parametrize(
    ("body", "position"),
    [
        pytest.param(
            'name = 1\nversion = "1.0"\nsource = { registry = "x" }',
            "package[0]",
            id="name-not-string",
        ),
        pytest.param('version = "1.0"', "package[0]", id="name-missing"),
        pytest.param(
            'name = "a"\nversion = 1\nsource = { registry = "x" }',
            "package[0]",
            id="version-not-string",
        ),
        pytest.param('name = "a"\nsource = { registry = "x" }', "package[0]", id="version-missing"),
    ],
)
def test_non_string_name_or_version_is_skipped_with_warning(body: str, position: str) -> None:
    text = lock(f"[[package]]\n{body}\n", table("good", "2.0"))
    result = parse_uv_lock(text)
    assert dict(result.package_scopes) == {k("good", "2.0"): "runtime"}
    (warning,) = result.warnings
    assert warning.code == "LOCKFILE_ENTRY_SKIPPED"
    assert warning.subjects == (position,)
    assert warning.service is None


@pytest.mark.parametrize(
    ("name", "version"),
    [
        pytest.param("bad name", "1.0", id="space-in-name"),
        pytest.param("a/b", "1.0", id="slash-in-name"),
        pytest.param("ok", "1 0", id="space-in-version"),
        pytest.param("ok", "", id="empty-version"),
    ],
)
def test_unpurlable_name_or_version_is_skipped_with_warning(name: str, version: str) -> None:
    text = lock(table(name, version), table("good", "2.0"), project(["good"]))
    result = parse_uv_lock(text)
    assert dict(result.package_scopes) == {k("good", "2.0"): "runtime"}
    (warning,) = result.warnings
    assert warning.code == "LOCKFILE_ENTRY_SKIPPED"
    assert warning.subjects == (f"{name}@{version}",)
    assert warning.service is None


def test_malformed_dependency_lists_are_skipped_with_warnings() -> None:
    text = lock(
        '[[package]]\nname = "a"\nversion = "1.0"\nsource = { registry = "x" }\ndependencies = 3\n',
        "[[package]]\n"
        'name = "b"\nversion = "1.0"\nsource = { registry = "x" }\n'
        'dependencies = [{ version = "1.0" }, 7]\n',
    )
    result = parse_uv_lock(text)
    assert dict(result.package_scopes) == {k("a", "1.0"): "runtime", k("b", "1.0"): "runtime"}
    assert codes(result) == ["LOCKFILE_ENTRY_SKIPPED"] * 3
    assert sorted(w.subjects[0] for w in result.warnings) == [
        "a@1.0.dependencies",
        "b@1.0.dependencies[0]",
        "b@1.0.dependencies[1]",
    ]
    assert all(w.service is None for w in result.warnings)


def test_missing_package_key_gives_empty_result() -> None:
    result = parse_uv_lock("version = 1\nrevision = 3\n")
    assert dict(result.package_scopes) == {}
    assert dict(result.direct_scopes) == {}
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
        parse_uv_lock(text)


def test_results_are_read_only_sorted_maps_with_unattributed_warnings() -> None:
    text = lock(table("zeta", "1.0"), table("alpha", "1.0"), project(["zeta", "alpha", "ghost"]))
    result = parse_uv_lock(text)
    assert list(result.package_scopes) == [k("alpha", "1.0"), k("zeta", "1.0")]
    assert list(result.direct_scopes) == [k("alpha", "1.0"), k("zeta", "1.0")]
    with pytest.raises(TypeError):
        cast(Any, result.package_scopes)[k("x", "1")] = "dev"
    with pytest.raises(TypeError):
        cast(Any, result.direct_scopes)[k("x", "1")] = "dev"
    assert codes(result) == ["DIRECT_UNRESOLVED"]
    assert all(w.service is None for w in result.warnings)


# --- DG-SCP-0: rejections --------------------------------------------------


@pytest.mark.parametrize("text", ["[[package]", "name = ", "a = = 1", "\x00", "[a]\n[a]"])
def test_invalid_toml_is_rejected(text: str) -> None:
    with pytest.raises(ValueError, match="invalid TOML"):
        parse_uv_lock(text)


def test_oversize_text_is_rejected_before_parsing() -> None:
    with pytest.raises(ValueError, match="exceeds"):
        parse_uv_lock(" " * (MAX_LOCKFILE_CHARS + 1))


def test_deeply_nested_array_is_value_error() -> None:
    depth = 100_000
    with pytest.raises(ValueError, match="nesting too deep"):
        parse_uv_lock("a = " + "[" * depth + "]" * depth)


def test_unbalanced_open_brackets_are_value_error() -> None:
    with pytest.raises(ValueError, match="invalid TOML"):
        parse_uv_lock("[" * 100_000)


@pytest.mark.parametrize("value", [None, b"", 1, ["package"]])
def test_non_str_input_is_rejected(value: object) -> None:
    with pytest.raises(ValueError, match="must be str"):
        parse_uv_lock(cast(Any, value))
