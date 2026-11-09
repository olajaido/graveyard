"""Property tests for the lockfile scope parsers (DG-INV-10).

Sections, in order: ``package-lock.json`` (T4.6), then ``poetry.lock`` and ``uv.lock``
(T5.7) and ``requirements.txt`` (T6) as they land. Each section's tests compute their
expected values from the abstract lockfile in ``tests/strategies.py`` (``LockEntry``,
``expected_package_lock``, ``npm_expected_key``) or from the flags of the generated
entries, never by calling a parser or one of its helpers. The one ``core.purl`` call is
``package_key(parse_purl(...))`` in the key-parity test, where it is the specification.

Profiles (``dev`` = 200 examples, ``ci`` = 500) come from ``conftest.py`` via
``HYPOTHESIS_PROFILE``. No ``max_examples`` is set here. Every test sets an explicit
five-second deadline and none disables it (DG-NFR-7).
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.graph.model import ScopeResult
from core.graph.scopes_npm import parse_package_lock
from core.graph.scopes_poetry import parse_poetry_lock
from core.graph.scopes_requirements import parse_requirements_txt
from core.graph.scopes_uv import parse_uv_lock
from core.graph.tests.strategies import (
    LOCK_NODE_MODULES,
    PYPI_LOCK_VERSIONS,
    AbstractLock,
    LockEntry,
    PoetryEntry,
    UvPackage,
    UvRef,
    expected_package_lock,
    expected_poetry_lock,
    expected_uv_lock,
    json_like,
    lock_document,
    mutated,
    npm_expected_key,
    npm_expected_purl,
    package_locks,
    poetry_document,
    poetry_locks,
    pypi_expected_key,
    pypi_expected_norm,
    pypi_expected_purl,
    pypi_names,
    render_toml,
    shuffled,
    shuffled_poetry,
    shuffled_uv,
    spelled_names,
    toml_like_documents,
    uv_document,
    uv_locks,
    uv_ref_matches,
    uv_refs,
)
from core.purl import package_key, parse_purl

pytestmark = pytest.mark.property

DEADLINE = timedelta(seconds=5)
SEEDS = st.integers(min_value=0, max_value=2**32 - 1)


def _as_dicts(result: ScopeResult) -> tuple[dict[str, str], dict[str, str]]:
    return dict(result.package_scopes), dict(result.direct_scopes)


def _disagreements(result: ScopeResult) -> list[Any]:
    return [w for w in result.warnings if w.code == "SCOPE_DISAGREEMENT"]


# ==========================================================================
# package-lock.json (DG-SCP-0…5)
# ==========================================================================


@settings(deadline=DEADLINE)
@given(package_locks())
def test_package_lock_round_trip(lock: AbstractLock) -> None:
    """**Validates: Requirements DG-SCP-1, DG-SCP-2, DG-SCP-3, DG-SCP-4, DG-SCP-5, DG-INV-10**

    A rendered lockfile parses to the maps and warnings computed from the abstract lock.
    """
    expected = expected_package_lock(lock)
    result = parse_package_lock(json.dumps(lock_document(lock)))
    packages, directs = _as_dicts(result)
    assert packages == expected.package_scopes
    assert directs == expected.direct_scopes
    unresolved = [w for w in result.warnings if w.code == "DIRECT_UNRESOLVED"]
    assert sorted(s for w in unresolved for s in w.subjects) == list(expected.unresolved)
    assert [s for w in _disagreements(result) for s in w.subjects] == list(expected.disagreements)
    assert len(result.warnings) == len(unresolved) + len(expected.disagreements)


@st.composite
def _duplicated_identities(draw: st.DrawFn) -> tuple[list[LockEntry], dict[str, bool]]:
    """Identities installed 1-4 times each at distinct nested paths, in a random order.

    Returns the entries and, per expected key, whether any copy is runtime.
    """
    identities = draw(
        st.lists(
            st.tuples(spelled_names(), st.sampled_from(("1.0.0", "2.3.1"))),
            min_size=1,
            max_size=3,
            unique_by=lambda t: npm_expected_key(t[0], t[1]),
        )
    )
    entries: list[LockEntry] = []
    any_runtime: dict[str, bool] = {}
    for i, (name, version) in enumerate(identities):
        spellings = st.sampled_from((name, name.lower(), name.swapcase()))
        copies = draw(st.lists(st.tuples(spellings, st.booleans()), min_size=1, max_size=4))
        key = npm_expected_key(name, version)
        any_runtime[key] = False
        for j, (spelling, dev) in enumerate(copies):
            # Every copy folds to the same key; the host differs, so the paths are unique.
            path = f"{LOCK_NODE_MODULES}host{i}_{j}/{LOCK_NODE_MODULES}{spelling}"
            entries.append(
                LockEntry(path, version, dev=True if dev else draw(st.sampled_from((False, None))))
            )
            any_runtime[key] = any_runtime[key] or not dev
    return draw(st.permutations(entries)), any_runtime


@settings(deadline=DEADLINE)
@given(_duplicated_identities())
def test_package_lock_any_wins(case: tuple[list[LockEntry], dict[str, bool]]) -> None:
    """**Validates: Requirements DG-SCP-3, DG-INV-10**

    With duplicated entries, a key is ``runtime`` iff any copy is runtime, in any order.
    """
    entries, any_runtime = case
    lock = AbstractLock(tuple(entries), None)
    result = parse_package_lock(json.dumps(lock_document(lock)))
    assert dict(result.package_scopes) == {
        key: "runtime" if runtime else "dev" for key, runtime in any_runtime.items()
    }


@st.composite
def _locks_with_marked_entries(draw: st.DrawFn) -> tuple[AbstractLock, list[LockEntry]]:
    """A lock where a random subset of installed entries gets ``devOptional`` and no ``dev``.

    Returns the lock and the marked entries, so the test checks them directly.
    """
    lock = draw(package_locks())
    installed = [i for i, e in enumerate(lock.entries) if e.installed]
    chosen = draw(st.sets(st.sampled_from(installed))) if installed else set()
    entries = tuple(
        replace(e, dev_optional=True, dev=draw(st.sampled_from((False, None))))
        if i in chosen
        else e
        for i, e in enumerate(lock.entries)
    )
    return replace(lock, entries=entries), [entries[i] for i in sorted(chosen)]


@settings(deadline=DEADLINE)
@given(_locks_with_marked_entries())
def test_dev_optional_is_runtime(case: tuple[AbstractLock, list[LockEntry]]) -> None:
    """**Validates: Requirements DG-SCP-1, DG-INV-10**

    An entry flagged ``devOptional`` and not ``dev`` is never ``dev``.
    """
    lock, marked = case
    result = parse_package_lock(json.dumps(lock_document(lock)))
    for entry in marked:
        assert result.package_scopes[entry.key] == "runtime"


@st.composite
def _locks_with_optional_entries(draw: st.DrawFn) -> tuple[AbstractLock, list[LockEntry]]:
    """A lock where some installed entries are ``optional`` (and not ``dev``).

    The top-level ones are also declared under ``optionalDependencies`` (and sometimes
    under ``devDependencies`` too). Returns the lock and the marked entries.
    """
    lock = draw(package_locks())
    installed = [i for i, e in enumerate(lock.entries) if e.installed]
    chosen = draw(st.sets(st.sampled_from(installed))) if installed else set()
    entries = tuple(
        replace(e, optional=True, dev=draw(st.sampled_from((False, None)))) if i in chosen else e
        for i, e in enumerate(lock.entries)
    )
    marked = [entries[i] for i in sorted(chosen)]
    top_names = tuple(
        e.path.removeprefix(LOCK_NODE_MODULES)
        for e in marked
        if e.path.count(LOCK_NODE_MODULES) == 1
    )
    root = {g: list(names) for g, names in (lock.root or {}).items()}
    root["optionalDependencies"] = sorted({*root.get("optionalDependencies", []), *top_names})
    if draw(st.booleans()):
        root["devDependencies"] = sorted({*root.get("devDependencies", []), *top_names})
    return (
        AbstractLock(entries, {g: tuple(names) for g, names in root.items()}),
        marked,
    )


@settings(deadline=DEADLINE)
@given(_locks_with_optional_entries())
def test_optional_dependency_is_runtime(case: tuple[AbstractLock, list[LockEntry]]) -> None:
    """**Validates: Requirements DG-SCP-1, DG-SCP-4, DG-INV-10**

    An ``optional`` entry is runtime, and a top-level one named in ``optionalDependencies``
    is declared runtime, even when ``devDependencies`` also lists it.
    """
    lock, marked = case
    result = parse_package_lock(json.dumps(lock_document(lock)))
    for entry in marked:
        assert result.package_scopes[entry.key] == "runtime"
        if entry.path.count(LOCK_NODE_MODULES) == 1 and entry.version is not None:
            assert result.direct_scopes[entry.key] == "runtime"


@settings(deadline=DEADLINE)
@given(package_locks())
def test_disagreement_iff_declared_runtime_and_package_dev(lock: AbstractLock) -> None:
    """**Validates: Requirements DG-SCP-5, DG-INV-10**

    A key gets exactly one ``SCOPE_DISAGREEMENT`` iff it is declared ``runtime`` in
    ``packages[""]`` and ``dev`` per package. A key declared ``dev`` gets none, whatever
    its per-package scope. The declaration wins in ``direct_scopes``.
    """
    expected = expected_package_lock(lock)
    result = parse_package_lock(json.dumps(lock_document(lock)))
    warnings = _disagreements(result)
    assert [w.subjects for w in warnings] == [(key,) for key in expected.disagreements]
    for w in warnings:
        assert "runtime" in w.detail
        assert "dev" in w.detail
        assert result.direct_scopes[w.subjects[0]] == "runtime"
        assert result.package_scopes[w.subjects[0]] == "dev"
    for key, declared in expected.direct_scopes.items():
        if declared == "dev":
            assert key not in {w.subjects[0] for w in warnings}


def _lock_texts() -> st.SearchStrategy[str]:
    """Arbitrary text, JSON-shaped text, truncated lockfiles and mutated lockfiles."""
    valid = package_locks().map(lambda lock: lock_document(lock))
    return st.one_of(
        st.text(alphabet=st.characters(exclude_categories=()), max_size=200),
        st.builds(json.dumps, json_like()),
        valid.map(json.dumps),
        st.tuples(valid.map(json.dumps), st.floats(min_value=0, max_value=1)).map(
            lambda t: t[0][: int(len(t[0]) * t[1])]
        ),
        valid.flatmap(mutated).map(json.dumps),
        st.integers(min_value=1, max_value=3000).map(lambda n: '{"packages":' * n),
        st.integers(min_value=1, max_value=3000).map(lambda n: "[" * n),
    )


@settings(deadline=DEADLINE)
@given(_lock_texts())
def test_package_lock_total(text: str) -> None:
    """**Validates: Requirements DG-SCP-0, DG-INV-10**

    Any ``str`` gives a ``ScopeResult`` or ``ValueError``, and nothing else.
    """
    try:
        result = parse_package_lock(text)
    except ValueError:
        return
    assert isinstance(result, ScopeResult)


@settings(deadline=DEADLINE)
@given(package_locks(), SEEDS)
def test_package_lock_order_independent(lock: AbstractLock, seed: int) -> None:
    """**Validates: Requirements DG-SCP-3, DG-SCP-4, DG-INV-10**

    Shuffling the ``packages`` entries, the root's group names and the names inside each
    group does not change the result.
    """
    document = lock_document(lock)
    plain = parse_package_lock(json.dumps(document))
    reordered = parse_package_lock(json.dumps(shuffled(document, seed)))
    assert _as_dicts(reordered) == _as_dicts(plain)
    assert reordered.warnings == plain.warnings
    assert reordered == plain


@settings(deadline=DEADLINE)
@given(package_locks())
def test_package_lock_key_parity(lock: AbstractLock) -> None:
    """**Validates: Requirements DG-SCP-2, DG-INV-10**

    Every installed entry's key equals ``package_key(parse_purl(...))`` of the equivalent
    purl, written independently with the name's case kept and a scope's ``@`` as ``%40``.
    Upper-case names fold and scoped names encode.
    """
    result = parse_package_lock(json.dumps(lock_document(lock)))
    expected = {
        package_key(parse_purl(npm_expected_purl(e.package_name, e.version)))
        for e in lock.entries
        if e.installed and e.version is not None
    }
    assert set(result.package_scopes) == expected
    for key in result.package_scopes:
        assert key.startswith("npm/")
        assert key == key.lower()
        assert "@" not in key.split("@", 1)[0]  # a scope is encoded as %40
        assert "/%40" in key or key.count("/") == 1


# ==========================================================================
# poetry.lock (DG-SCP-6) and uv.lock (DG-SCP-7)
# ==========================================================================


def _poetry_text(entries: tuple[PoetryEntry, ...]) -> str:
    return render_toml(poetry_document(entries))


def _uv_text(packages: tuple[UvPackage, ...]) -> str:
    return render_toml(uv_document(packages))


@settings(deadline=DEADLINE)
@given(poetry_locks())
def test_poetry_round_trip(entries: tuple[PoetryEntry, ...]) -> None:
    """**Validates: Requirements DG-SCP-6, DG-INV-10**

    A rendered ``poetry.lock`` (``groups`` lists with or without ``"main"``, legacy
    ``category``, both fields, neither) parses to the scopes computed per entry, with
    runtime winning for a repeated key, an empty ``direct_scopes`` and no warnings.
    """
    result = parse_poetry_lock(_poetry_text(entries))
    assert dict(result.package_scopes) == expected_poetry_lock(entries)
    assert dict(result.direct_scopes) == {}
    assert result.warnings == ()


@settings(deadline=DEADLINE)
@given(uv_locks())
def test_uv_closure_matches_independent_closure(packages: tuple[UvPackage, ...]) -> None:
    """**Validates: Requirements DG-SCP-7, DG-INV-10**

    ``package_scopes`` and ``direct_scopes`` equal the maps from a fixed-point closure written
    in the strategies. Unresolved seeds are the only warnings, one per name as written.
    """
    expected = expected_uv_lock(packages)
    result = parse_uv_lock(_uv_text(packages))
    packages_out, directs_out = _as_dicts(result)
    assert packages_out == expected.package_scopes
    assert directs_out == expected.direct_scopes
    assert {w.code for w in result.warnings} <= {"DIRECT_UNRESOLVED"}
    assert {s for w in result.warnings for s in w.subjects} == expected.unresolved


@st.composite
def _locks_with_extra_seed(
    draw: st.DrawFn,
) -> tuple[tuple[UvPackage, ...], int, UvRef]:
    packages = draw(uv_locks(require_project=True))
    projects = [i for i, p in enumerate(packages) if p.project is not None]
    return packages, draw(st.sampled_from(projects)), draw(uv_refs())


@settings(deadline=DEADLINE)
@given(_locks_with_extra_seed())
def test_uv_adding_runtime_seed_never_demotes(
    case: tuple[tuple[UvPackage, ...], int, UvRef],
) -> None:
    """**Validates: Requirements DG-SCP-7, DG-INV-10**

    Adding a runtime seed (a reference in a project package's ``dependencies``) keeps the
    package set, never turns a ``runtime`` package or direct into ``dev``, and makes every
    package the reference matches ``runtime``.
    """
    packages, index, ref = case
    project = packages[index]
    grown = (
        *packages[:index],
        replace(project, dependencies=(*project.dependencies, ref)),
        *packages[index + 1 :],
    )
    before = parse_uv_lock(_uv_text(packages))
    after = parse_uv_lock(_uv_text(grown))
    assert set(after.package_scopes) == set(before.package_scopes)
    for key, scope in before.package_scopes.items():
        if scope == "runtime":
            assert after.package_scopes[key] == "runtime"
    for key, scope in before.direct_scopes.items():
        if scope == "runtime":
            assert after.direct_scopes[key] == "runtime"
    for package in grown:
        if package.project is None and uv_ref_matches(ref, package):
            assert package.version is not None
            key = pypi_expected_key(package.name, package.version)
            assert after.package_scopes[key] == "runtime"
            assert after.direct_scopes[key] == "runtime"


@settings(deadline=DEADLINE)
@given(uv_locks())
def test_uv_never_disagrees(packages: tuple[UvPackage, ...]) -> None:
    """**Validates: Requirements DG-SCP-5, DG-SCP-7, DG-INV-10**

    ``cross_check`` is silent for every generated ``uv.lock``: no ``SCOPE_DISAGREEMENT``, and
    no key is declared ``runtime`` while ``dev`` per package.
    """
    result = parse_uv_lock(_uv_text(packages))
    assert _disagreements(result) == []
    for key, declared in result.direct_scopes.items():
        if declared == "runtime":
            assert result.package_scopes[key] == "runtime"


def _toml_texts() -> st.SearchStrategy[str]:
    """Arbitrary text with surrogates, TOML-shaped text, truncated and edited lockfiles,
    and deeply nested arrays and tables.
    """
    valid = st.one_of(poetry_locks().map(_poetry_text), uv_locks().map(_uv_text))
    edited = st.tuples(valid, st.integers(min_value=0), st.text(max_size=2)).map(
        lambda t: t[0][: t[1] % (len(t[0]) + 1)] + t[2] + t[0][t[1] % (len(t[0]) + 1) + 1 :]
    )
    return st.one_of(
        st.text(alphabet=st.characters(exclude_categories=()), max_size=200),
        valid,
        toml_like_documents().map(render_toml),
        st.tuples(valid, st.floats(min_value=0, max_value=1)).map(
            lambda t: t[0][: int(len(t[0]) * t[1])]
        ),
        edited,
        st.integers(min_value=1, max_value=3000).map(lambda n: "a = " + "[" * n),
        st.integers(min_value=1, max_value=3000).map(lambda n: "a = " + "{ a = " * n),
        st.integers(min_value=1, max_value=3000).map(
            lambda n: "[[package]]\ndependencies = " + "[" * n
        ),
    )


@settings(deadline=DEADLINE)
@given(_toml_texts())
def test_poetry_uv_total(text: str) -> None:
    """**Validates: Requirements DG-SCP-0, DG-INV-10**

    Any ``str`` gives a ``ScopeResult`` or ``ValueError`` from each parser, and nothing else.
    """
    for parse in (parse_poetry_lock, parse_uv_lock):
        try:
            result = parse(text)
        except ValueError:
            continue
        assert isinstance(result, ScopeResult)


@settings(deadline=DEADLINE)
@given(poetry_locks(), uv_locks(), SEEDS)
def test_poetry_uv_order_independent(
    entries: tuple[PoetryEntry, ...], packages: tuple[UvPackage, ...], seed: int
) -> None:
    """**Validates: Requirements DG-SCP-6, DG-SCP-7, DG-INV-10**

    Shuffling the ``[[package]]`` tables (and, for ``uv.lock``, every dependency list and
    group) does not change the maps or the warnings.
    """
    poetry_plain = parse_poetry_lock(_poetry_text(entries))
    poetry_mixed = parse_poetry_lock(_poetry_text(shuffled_poetry(entries, seed)))
    assert _as_dicts(poetry_mixed) == _as_dicts(poetry_plain)
    assert poetry_mixed.warnings == poetry_plain.warnings
    assert poetry_mixed == poetry_plain

    uv_plain = parse_uv_lock(_uv_text(packages))
    uv_mixed = parse_uv_lock(_uv_text(shuffled_uv(packages, seed)))
    assert _as_dicts(uv_mixed) == _as_dicts(uv_plain)
    assert uv_mixed.warnings == uv_plain.warnings
    assert uv_mixed == uv_plain


@st.composite
def _parity_identities(draw: st.DrawFn) -> list[tuple[str, str]]:
    return draw(
        st.lists(
            st.tuples(pypi_names(), st.sampled_from(("1.0", "2.0.1", "0.9.0rc1"))),
            min_size=1,
            max_size=6,
        )
    )


@settings(deadline=DEADLINE)
@given(_parity_identities())
def test_poetry_uv_key_parity(identities: list[tuple[str, str]]) -> None:
    """**Validates: Requirements DG-SCP-6, DG-SCP-7, DG-INV-10**

    Names with mixed case and runs of ``-``, ``_`` and ``.`` give keys equal to
    ``package_key(parse_purl(...))`` of a purl written independently, both with the raw name
    and with the PEP 503 name, and equal to the key spelled out in the strategies.
    """
    expected = {
        package_key(parse_purl(f"pkg:pypi/{name}@{version}")) for name, version in identities
    }
    assert expected == {
        package_key(parse_purl(pypi_expected_purl(name, version))) for name, version in identities
    }
    assert expected == {pypi_expected_key(name, version) for name, version in identities}

    poetry = parse_poetry_lock(
        _poetry_text(tuple(PoetryEntry(name, version) for name, version in identities))
    )
    uv = parse_uv_lock(_uv_text(tuple(UvPackage(name, version) for name, version in identities)))
    for result in (poetry, uv):
        assert set(result.package_scopes) == expected
        for key in result.package_scopes:
            name_part = key.removeprefix("pypi/").split("@", 1)[0]
            assert name_part == pypi_expected_norm(name_part)
            assert "_" not in name_part and "." not in name_part and "--" not in name_part


# ==========================================================================
# requirements.txt (DG-SCP-8)
# ==========================================================================

_EXTRAS = ("", "", "[security]", "[security,socks]", "[a_b]")
_MARKERS = ("", "", 'python_version < "3.9"', 'sys_platform == "win32" and os_name == "nt"')
_COMMENTS = ("", "", "pinned for CVE", "see https://example.org/x", "name==9.9")
_OPERATORS = ("==", "===")
_PADDING = ("", " ", "  ")
_SILENT_LINES = (
    "",
    "   ",
    "# a comment ==1.0",
    "-r other.txt",
    "-c constraints.txt",
    "-e .",
    "--index-url https://pypi.org/simple",
)
_SKIPPED_LINES = (
    "flask>=1.0",
    "requests~=2.0",
    "flask==1.*",
    "numpy",
    "git+https://github.com/a/b.git#egg=b",
    "pkg @ https://example.org/pkg.whl",
    "./local/pkg",
    "/abs/pkg",
)
_HEX = st.text(alphabet="0123456789abcdef", min_size=4, max_size=12)


@st.composite
def _pinned_block(draw: st.DrawFn) -> tuple[tuple[str, ...], str | None]:
    """One pinned requirement as 1-4 physical lines, and its expected key."""
    name = draw(pypi_names())
    version = draw(st.sampled_from(PYPI_LOCK_VERSIONS))
    pad = draw(st.sampled_from(_PADDING))
    extras = draw(st.sampled_from(_EXTRAS))
    operator = draw(st.sampled_from(_OPERATORS))
    head = f"{name}{extras}{pad}{operator}{pad}{version}"
    marker = draw(st.sampled_from(_MARKERS))
    if marker:
        head += f" ; {marker}"
    hashes = [f"--hash=sha256:{h}" for h in draw(st.lists(_HEX, max_size=3))]
    comment = draw(st.sampled_from(_COMMENTS))
    tail = f"  # {comment}" if comment else ""
    continued = draw(st.booleans())
    if hashes and continued:
        # pip's layout: every piece but the last ends in a backslash continuation.
        pieces = [head, *(f"    {h}" for h in hashes)]
        lines = [f"{piece} \\" for piece in pieces[:-1]] + [pieces[-1] + tail]
    else:
        lines = [" ".join([head, *hashes]) + tail]
    return tuple(lines), pypi_expected_key(name, version)


@st.composite
def _requirement_blocks(draw: st.DrawFn) -> tuple[tuple[tuple[str, ...], str | None], ...]:
    """Pinned, silent and skipped blocks in random order; a block is its physical lines."""
    block = st.one_of(
        _pinned_block(),
        st.sampled_from(_SILENT_LINES).map(lambda line: ((line,), None)),
        st.sampled_from(_SKIPPED_LINES).map(lambda line: ((line,), "skipped")),
    )
    return tuple(draw(st.lists(block, max_size=12)))


def _render_requirements(
    blocks: tuple[tuple[tuple[str, ...], str | None], ...],
    eol: str = "\n",
    bom: bool = False,
) -> str:
    lines = [line for lines, _ in blocks for line in lines]
    return ("\ufeff" if bom else "") + eol.join(lines) + (eol if lines else "")


def _expected_requirements(
    blocks: tuple[tuple[tuple[str, ...], str | None], ...],
) -> tuple[set[str], int]:
    keys = {key for _, key in blocks if key not in (None, "skipped")}
    # Identical skipped lines give one warning: warnings are de-duplicated (DG-WARN).
    return keys, len({lines for lines, key in blocks if key == "skipped"})


@settings(deadline=DEADLINE)
@given(_requirement_blocks(), st.booleans())
def test_requirements_round_trip(
    blocks: tuple[tuple[tuple[str, ...], str | None], ...], bom: bool
) -> None:
    """**Validates: Requirements DG-SCP-8, DG-INV-10**

    Rendered lines with random extras, markers, comments, hashes (inline or continued),
    spacing and ``==``/``===`` parse to runtime scopes for exactly the pinned keys, in both
    maps, with one ``REQUIREMENT_SKIPPED`` per unpinned, URL or path line and nothing else.
    """
    keys, skipped = _expected_requirements(blocks)
    result = parse_requirements_txt(_render_requirements(blocks, bom=bom))
    expected = {key: "runtime" for key in keys}
    packages, directs = _as_dicts(result)
    assert packages == expected
    assert directs == expected
    assert [w.code for w in result.warnings] == ["REQUIREMENT_SKIPPED"] * skipped


def _requirement_texts() -> st.SearchStrategy[str]:
    """Arbitrary text with surrogates, rendered files, truncations and odd characters."""
    rendered = _requirement_blocks().map(_render_requirements)
    return st.one_of(
        st.text(alphabet=st.characters(exclude_categories=()), max_size=300),
        st.text(alphabet="=[]#;\\-@ \t\r\n\ufeff\ud800a0.*", max_size=300),
        rendered,
        st.tuples(rendered, st.floats(min_value=0, max_value=1)).map(
            lambda t: t[0][: int(len(t[0]) * t[1])]
        ),
    )


@settings(deadline=DEADLINE)
@given(_requirement_texts())
def test_requirements_never_raises(text: str) -> None:
    """**Validates: Requirements DG-SCP-0, DG-SCP-8, DG-INV-10**

    Any ``str`` under ``MAX_LOCKFILE_CHARS``, lone surrogates included, gives a
    ``ScopeResult`` whose scopes are all ``runtime``, and never raises.
    """
    result = parse_requirements_txt(text)
    assert isinstance(result, ScopeResult)
    assert set(result.package_scopes.values()) <= {"runtime"}
    assert dict(result.package_scopes) == dict(result.direct_scopes)


@settings(deadline=DEADLINE)
@given(_requirement_blocks(), SEEDS)
def test_requirements_line_ending_and_order_independent(
    blocks: tuple[tuple[tuple[str, ...], str | None], ...], seed: int
) -> None:
    """**Validates: Requirements DG-SCP-8, DG-INV-10**

    ``\\n``, ``\\r\\n`` and ``\\r`` line endings, and any reordering of the requirements,
    give the same maps and the same set of warnings.
    """

    def summary(text: str) -> tuple[dict[str, str], dict[str, str], list[tuple[str, ...]]]:
        result = parse_requirements_txt(text)
        warnings = sorted((w.code, w.detail, *w.subjects) for w in result.warnings)
        return (*_as_dicts(result), warnings)

    plain = summary(_render_requirements(blocks))
    assert summary(_render_requirements(blocks, eol="\r\n")) == plain
    assert summary(_render_requirements(blocks, eol="\r")) == plain
    order = list(blocks)
    random.Random(seed).shuffle(order)
    assert summary(_render_requirements(tuple(order))) == plain


_LINEAR_CHARS = 100_000
_LINEAR_SHAPES = (
    "a" * _LINEAR_CHARS,
    "a" + " " * _LINEAR_CHARS + "x",
    "a==" + "1" * _LINEAR_CHARS,
    "a[" + "[" * _LINEAR_CHARS,
    "a[" + "x" * _LINEAR_CHARS,
    "a==1" + " --" * (_LINEAR_CHARS // 3),
    "#" + " #" * (_LINEAR_CHARS // 2),
    "a==1" + ";" * _LINEAR_CHARS,
    " " * _LINEAR_CHARS + "--",
    "\\" * _LINEAR_CHARS,
    "a \\\n" * (_LINEAR_CHARS // 4),
    "a-" * (_LINEAR_CHARS // 2) + "==",
    "=" * _LINEAR_CHARS,
)
# DG-NFR-1 gives the largest build_graph budget as 2 s; ×4 margin as for the timing tests.
_LINEAR_BUDGET_SECONDS = 2.0 * 4


@settings(deadline=timedelta(seconds=30))
@given(st.sampled_from(_LINEAR_SHAPES))
def test_requirements_linear_time(text: str) -> None:
    """**Validates: Requirements DG-SCP-8, DG-NFR-1, DG-INV-10**

    Pathological 100,000-character lines (long names, spaces, brackets, option and comment
    markers, continuations) parse within the DG-NFR-1 budget with a ×4 margin, which a
    quadratic or backtracking parser would not.
    """
    assert len(text) <= _LINEAR_CHARS + 10
    start = time.perf_counter()
    result = parse_requirements_txt(text)
    elapsed = time.perf_counter() - start
    assert isinstance(result, ScopeResult)
    assert elapsed <= _LINEAR_BUDGET_SECONDS
