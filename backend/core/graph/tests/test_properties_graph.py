"""Property tests for the dependency-graph package.

Profiles (``dev`` = 200 examples, ``ci`` = 500) come from ``conftest.py`` via
``HYPOTHESIS_PROFILE``. No ``max_examples`` is set here and no test disables
the Hypothesis deadline (DG-NFR-7).

Sections are appended per task: warnings (T1.5), path-info order (T1.5) and
package keys (T1.5). Later tasks add their properties below.
"""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from datetime import timedelta
from urllib.parse import quote

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from core.graph.build import build_graph
from core.graph.diagnostics import finalise_warnings, make_warning
from core.graph.keys import npm_key, pypi_key
from core.graph.model import (
    MAX_SUBJECTS,
    MAX_TEXT,
    MAX_WARNINGS_PER_CODE,
    WARNING_CODES,
    DependencyGraph,
    GraphWarning,
    ServiceInput,
    path_info_sort_key,
)
from core.graph.tests import oracle
from core.graph.tests.strategies import (
    AbstractService,
    AbstractServices,
    RenderedService,
    RenderFlags,
    _repair_unreferenced,
    abstract_services,
    render,
    render_flags,
    shuffled,
    with_duplicates,
)
from core.purl import package_key, parse_purl
from core.scoring.types import PathInfo

pytestmark = pytest.mark.property

DEADLINE = timedelta(seconds=5)
SEEDS = st.integers(min_value=0, max_value=2**32 - 1)

_TRUNCATED = "WARNINGS_TRUNCATED"
_CAPPABLE_CODES = sorted(WARNING_CODES - {_TRUNCATED})
_ALL_CODES = sorted(WARNING_CODES)

# --------------------------------------------------------------------------
# Strategies: warnings
# --------------------------------------------------------------------------

_CHARS = st.characters(blacklist_categories=["Cs"])
_SERVICES = st.sampled_from([None, "", "svc/a", "svc/b"])

# Short texts collide often (exercising de-duplication); long texts exceed MAX_TEXT.
_texts = st.one_of(
    st.text(st.sampled_from("abc"), max_size=4),
    st.text(_CHARS, max_size=12),
    st.text(st.sampled_from("xy"), min_size=MAX_TEXT - 5, max_size=MAX_TEXT + 250),
)
_subject_lists = st.lists(_texts, max_size=MAX_SUBJECTS + 25).map(tuple)


def _raw_warnings(codes: list[str]) -> st.SearchStrategy[GraphWarning]:
    """Un-normalised warnings, as an ingest step or parser could produce them."""
    return st.builds(
        GraphWarning,
        code=st.sampled_from(codes),
        detail=_texts,
        service=_SERVICES,
        subjects=_subject_lists,
    )


@st.composite
def _bulk_group(draw: st.DrawFn, codes: list[str]) -> list[GraphWarning]:
    """0..120 distinct warnings in one ``(service, code)`` group, to cross the cap."""
    service = draw(_SERVICES)
    code = draw(st.sampled_from(codes))
    n = draw(st.integers(0, 2 * MAX_WARNINGS_PER_CODE + 20))
    return [make_warning(code, f"item-{i}", service) for i in range(n)]


@st.composite
def _warning_lists(draw: st.DrawFn, codes: list[str]) -> list[GraphWarning]:
    noise = draw(st.lists(_raw_warnings(codes), max_size=25))
    bulk = draw(_bulk_group(codes))
    return draw(st.permutations(noise + bulk))


# --------------------------------------------------------------------------
# Warnings (DG-WARN-4)
# --------------------------------------------------------------------------


@given(_warning_lists(_ALL_CODES))
def test_finalise_warnings_idempotent(ws: list[GraphWarning]) -> None:
    """``finalise_warnings(finalise_warnings(ws)) == finalise_warnings(ws)``.

    **Validates: Requirements DG-WARN-4**
    """
    once = finalise_warnings(ws)
    assert finalise_warnings(once) == once


@given(_warning_lists(_ALL_CODES), st.data())
def test_finalise_warnings_order_independent(ws: list[GraphWarning], data: st.DataObject) -> None:
    """Any permutation of the input, with any duplicates added, gives the same result.

    **Validates: Requirements DG-WARN-4**
    """
    expected = finalise_warnings(ws)
    repeated = ws + data.draw(st.lists(st.sampled_from(ws), max_size=10) if ws else st.just([]))
    shuffled = data.draw(st.permutations(repeated))
    assert finalise_warnings(shuffled) == expected


@given(_warning_lists(_CAPPABLE_CODES))
def test_finalise_warnings_respects_caps(ws: list[GraphWarning]) -> None:
    """Per-group cap, one truncation notice per truncated group, bounded text.

    **Validates: Requirements DG-WARN-4**
    """
    # ``make_warning`` outputs are already bounded, so the distinct input
    # warnings of a group are counted without using the code under test.
    expected_groups: dict[tuple[str | None, str], set[GraphWarning]] = {}
    for w in ws:
        bounded = make_warning(w.code, w.detail, w.service, w.subjects)
        expected_groups.setdefault((w.service, w.code), set()).add(bounded)

    out = finalise_warnings(ws)

    kept: dict[tuple[str | None, str], int] = {}
    notices: list[GraphWarning] = []
    for w in out:
        if w.code == _TRUNCATED:
            notices.append(w)
        else:
            kept[(w.service, w.code)] = kept.get((w.service, w.code), 0) + 1

    expected_notices = {
        GraphWarning(
            _TRUNCATED, f"{code}: {len(members) - MAX_WARNINGS_PER_CODE} more omitted", service
        )
        for (service, code), members in expected_groups.items()
        if len(members) > MAX_WARNINGS_PER_CODE
    }
    assert len(notices) == len(expected_notices)  # one per truncated group
    assert set(notices) == expected_notices
    for group, members in expected_groups.items():
        assert kept.get(group, 0) == min(len(members), MAX_WARNINGS_PER_CODE)

    for w in out:
        assert len(w.detail) <= MAX_TEXT
        assert len(w.subjects) <= MAX_SUBJECTS
        assert list(w.subjects) == sorted(set(w.subjects))
        assert all(len(s) <= MAX_TEXT for s in w.subjects)

    sort_keys = [(w.service or "", w.code, w.detail, w.subjects) for w in out]
    assert sort_keys == sorted(sort_keys)
    assert len(set(out)) == len(out)


# --------------------------------------------------------------------------
# Path-info order (DG-EXP-5)
# --------------------------------------------------------------------------

_path_infos = st.builds(PathInfo, runtime=st.booleans(), direct=st.booleans())

_EXPECTED_ORDER = [
    PathInfo(runtime=True, direct=True),
    PathInfo(runtime=True, direct=False),
    PathInfo(runtime=False, direct=True),
    PathInfo(runtime=False, direct=False),
]


@given(st.lists(_path_infos, max_size=30), st.data())
def test_path_info_sort_key_is_total_order(infos: list[PathInfo], data: st.DataObject) -> None:
    """Sorting is permutation-invariant and orders the four members as DG-EXP-5 states.

    **Validates: Requirements DG-EXP-5**
    """
    expected = sorted(infos, key=path_info_sort_key)
    shuffled = data.draw(st.permutations(infos))
    assert sorted(shuffled, key=path_info_sort_key) == expected


@given(st.permutations(_EXPECTED_ORDER))
def test_path_info_sort_key_orders_the_four_members(perm: list[PathInfo]) -> None:
    """The four members sort to (runtime, direct), (runtime, transitive), (dev, ...).

    **Validates: Requirements DG-EXP-5**
    """
    assert sorted(perm, key=path_info_sort_key) == _EXPECTED_ORDER


# --------------------------------------------------------------------------
# Package keys (DG-DEP-2)
# --------------------------------------------------------------------------

_NAME_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
_alnum = st.text(_NAME_CHARS, min_size=1, max_size=6)
_npm_part = st.lists(
    st.one_of(_alnum, st.sampled_from(["-", ".", "_"])), min_size=1, max_size=5
).map("".join)
_versions = st.text(_NAME_CHARS + ".-+_~", min_size=1, max_size=12)
_SCOPE_OR_NONE = st.one_of(st.none(), _npm_part)


@st.composite
def _pypi_names(draw: st.DrawFn) -> str:
    """PEP 508 names: alphanumeric runs joined by random runs of ``-``, ``_`` and ``.``."""
    parts = draw(st.lists(_alnum, min_size=1, max_size=4))
    seps = [draw(st.text(st.sampled_from("-_."), min_size=1, max_size=3)) for _ in parts[1:]]
    out = parts[0]
    for sep, part in zip(seps, parts[1:], strict=True):
        out += sep + part
    return out


@st.composite
def _key_cases(draw: st.DrawFn) -> tuple[tuple[str, str, str], str]:
    """Return ``((ecosystem, name, rendered purl), version)``; the purl is rendered here."""
    version = draw(_versions)
    v = quote(version, safe="")
    if draw(st.booleans()):
        name = draw(_pypi_names())
        return ("pypi", name, f"pkg:pypi/{quote(name, safe='')}@{v}"), version
    name = draw(_npm_part)
    scope = draw(_SCOPE_OR_NONE)
    if scope is None:
        return ("npm", name, f"pkg:npm/{quote(name, safe='')}@{v}"), version
    purl = f"pkg:npm/%40{quote(scope, safe='')}/{quote(name, safe='')}@{v}"
    return ("npm", f"@{scope}/{name}", purl), version


@given(_key_cases())
def test_keys_match_package_key(case: tuple[tuple[str, str, str], str]) -> None:
    """``npm_key`` and ``pypi_key`` agree with ``package_key`` of an independently rendered purl.

    **Validates: Requirements DG-DEP-2**
    """
    (ecosystem, name, purl), version = case
    key = npm_key(name, version) if ecosystem == "npm" else pypi_key(name, version)
    assert key == package_key(parse_purl(purl))


# --------------------------------------------------------------------------
# Whole-graph properties (DG-INV-1, 2, 4, 5, 6, 7, 9)
# --------------------------------------------------------------------------


def _inputs(rendered: tuple[RenderedService, ...]) -> list[ServiceInput]:
    return [ServiceInput(r.path, r.bom, r.scopes) for r in rendered]


def _build(rendered: tuple[RenderedService, ...]) -> DependencyGraph:
    return build_graph(_inputs(rendered))


def _dump(graph: DependencyGraph) -> str:
    """Serialise without sorting keys, so field and element order are part of the bytes."""
    return json.dumps(asdict(graph))


def _infos(pairs: frozenset[oracle.InfoPair]) -> set[PathInfo]:
    return {PathInfo(runtime=runtime, direct=direct) for runtime, direct in pairs}


def _present_keys(abstract: AbstractServices) -> set[str]:
    return {abstract.packages[m].key for svc in abstract.services for m in svc.members}


@settings(deadline=DEADLINE)
@given(abstract=abstract_services(), flags=render_flags(), seed_a=SEEDS, seed_b=SEEDS)
def test_deterministic_under_reordering(
    abstract: AbstractServices, flags: RenderFlags, seed_a: int, seed_b: int
) -> None:
    """Two shufflings of the input (services, lists, object keys, ScopeResult maps) agree.

    Nodes, warnings, ``graph_to_dict`` -equivalent bytes and display purls are all equal.

    **Validates: Requirements DG-INV-1**
    """
    rendered = render(abstract, flags)
    first = _build(shuffled(rendered, seed_a))
    second = _build(shuffled(rendered, seed_b))
    assert first.nodes == second.nodes
    assert first.warnings == second.warnings
    assert first == second
    assert _dump(first) == _dump(second)
    assert first == _build(rendered)


@settings(deadline=DEADLINE)
@given(abstract=abstract_services(), flags=render_flags())
def test_dedupe_idempotent(abstract: AbstractServices, flags: RenderFlags) -> None:
    """Duplicated components, dependency entries and ``dependsOn`` elements change nothing.

    **Validates: Requirements DG-INV-2**
    """
    rendered = render(abstract, flags)
    doubled = tuple(replace(r, bom=with_duplicates(r.bom)) for r in rendered)
    assert _build(doubled) == _build(rendered)


@settings(deadline=DEADLINE)
@given(abstract=abstract_services(), flags=render_flags())
def test_dedupe_one_node_per_identity(abstract: AbstractServices, flags: RenderFlags) -> None:
    """One node per abstract identity present in some service, whatever the spelling.

    Covers bom-ref suffixes, npm case and aliased components. The display purl is the
    smallest qualifier-free spelling over all services (DG-DUP-3).

    **Validates: Requirements DG-INV-2**
    """
    rendered = render(abstract, flags)
    graph = _build(rendered)
    keys = _present_keys(abstract)
    assert [n.key for n in graph.nodes] == sorted(keys)
    assert len(graph.nodes) == len(keys)
    for node in graph.nodes:
        spellings = [s for r in rendered if node.key in r.spellings for s in r.spellings[node.key]]
        assert node.purl == min(spellings)


@settings(deadline=DEADLINE)
@given(abstract=abstract_services(), flags=render_flags())
def test_path_infos_match_oracle(abstract: AbstractServices, flags: RenderFlags) -> None:
    """``path_infos`` equals the brute-force simple-path oracle for every node.

    **Validates: Requirements DG-INV-4**
    """
    graph = _build(render(abstract, flags))
    want = oracle.expected(abstract, flags.scope_mode)
    assert {n.key for n in graph.nodes} == set(want)
    for node in graph.nodes:
        assert set(node.path_infos) == _infos(want[node.key].infos), node.key


def _cyclic(abstract: AbstractServices, shape: str, pick: int) -> AbstractServices:
    """Rewrite every service's edges into one cyclic shape over its members.

    ``complete``: every ordered pair, self-loops included. ``ring``: one cycle through the
    members. ``loops``: a self-loop on each member plus the ring. In all three every member
    is referenced, so none looks like a second root (DG-ROOT-1).
    """
    out: list[AbstractService] = []
    for svc in abstract.services:
        members = svc.members
        if not members:
            out.append(svc)
            continue
        ring = {(m, members[(i + 1) % len(members)]) for i, m in enumerate(members)}
        if shape == "complete":
            edges = {(u, v) for u in members for v in members}
        elif shape == "ring":
            edges = ring
        else:
            edges = ring | {(m, m) for m in members}
        directs = svc.directs or (members[pick % len(members)],)
        out.append(replace(svc, directs=tuple(sorted(directs)), edges=tuple(sorted(edges))))
    return replace(abstract, services=tuple(out))


@settings(deadline=DEADLINE)
@given(
    abstract=abstract_services(),
    flags=render_flags(),
    shape=st.sampled_from(("complete", "ring", "loops")),
    pick=st.integers(min_value=0, max_value=7),
)
def test_termination_on_cyclic_graphs(
    abstract: AbstractServices, flags: RenderFlags, shape: str, pick: int
) -> None:
    """Strongly connected graphs, self-loops and complete digraphs build within the deadline.

    The deadline is the assertion; the result must also cover every member and, because
    every member is on a cycle through a direct, give every member of a service a path.

    **Validates: Requirements DG-INV-5**
    """
    cyclic = _cyclic(abstract, shape, pick)
    graph = _build(render(cyclic, flags))
    assert {n.key for n in graph.nodes} == _present_keys(cyclic)
    for svc in cyclic.services:
        for m in svc.members:
            node = graph.node(cyclic.packages[m].key)
            assert node is not None
            assert node.path_infos


@settings(deadline=DEADLINE)
@given(abstract=abstract_services(), flags=render_flags())
def test_unreachable_has_no_exposure(abstract: AbstractServices, flags: RenderFlags) -> None:
    """A node no simple path reaches carries no exposure data at all.

    **Validates: Requirements DG-INV-6**
    """
    graph = _build(render(abstract, flags))
    want = oracle.expected(abstract, flags.scope_mode)
    for node in graph.nodes:
        if want[node.key].infos:
            continue
        assert node.path_infos == ()
        assert node.services_affected == 0
        assert node.example_paths == ()
        assert node.path_witnesses == ()
        assert not node.direct
        assert not node.transitive
        assert node.scope is None


@settings(deadline=DEADLINE)
@given(abstract=abstract_services(), flags=render_flags())
def test_services_affected_and_manifests(abstract: AbstractServices, flags: RenderFlags) -> None:
    """``services_affected`` counts services with a path; ``manifests`` lists SBOM services.

    **Validates: Requirements DG-INV-7**
    """
    graph = _build(render(abstract, flags))
    want = oracle.expected(abstract, flags.scope_mode)
    for node in graph.nodes:
        assert node.services_affected == len(want[node.key].services)
        assert node.services_affected <= len(abstract.services)
        assert (node.services_affected == 0) == (not node.path_infos)
        present = sorted(
            svc.path
            for svc in abstract.services
            if any(abstract.packages[m].key == node.key for m in svc.members)
        )
        assert list(node.manifests) == present


@st.composite
def _mutations(draw: st.DrawFn) -> tuple[AbstractServices, AbstractServices, str, RenderFlags]:
    """Draw an abstract graph and a variant with one edge, direct or scope change applied."""
    abstract = draw(abstract_services())
    flags = draw(render_flags())
    index = draw(st.sampled_from(range(len(abstract.services))))
    svc = abstract.services[index]
    assume(svc.members)
    op = draw(st.sampled_from(("edge", "direct", "scope")))
    if op == "edge":
        u = draw(st.sampled_from(svc.members))
        v = draw(st.sampled_from(svc.members))
        edges = _repair_unreferenced(svc.members, svc.directs, set(svc.edges) | {(u, v)})
        changed = replace(svc, edges=tuple(sorted(edges)))
    elif op == "direct":
        d = draw(st.sampled_from(svc.members))
        changed = replace(svc, directs=tuple(sorted(set(svc.directs) | {d})))
    else:
        devs = [d for d in svc.directs if svc.scopes[d] == "dev"]
        assume(devs)
        d = draw(st.sampled_from(devs))
        changed = replace(svc, scopes={**svc.scopes, d: "runtime"})
    services = tuple(changed if i == index else s for i, s in enumerate(abstract.services))
    return abstract, replace(abstract, services=services), op, flags


@settings(deadline=DEADLINE)
@given(case=_mutations())
def test_monotone_in_edges_and_scope(
    case: tuple[AbstractServices, AbstractServices, str, RenderFlags],
) -> None:
    """More edges or directs never remove a ``PathInfo``; dev to runtime keeps runtime members.

    **Validates: Requirements DG-INV-9**
    """
    before_abstract, after_abstract, op, flags = case
    before = _build(render(before_abstract, flags))
    after = _build(render(after_abstract, flags))
    assert [n.key for n in before.nodes] == [n.key for n in after.nodes]
    for old, new in zip(before.nodes, after.nodes, strict=True):
        if op == "scope":
            assert {p for p in old.path_infos if p.runtime} <= set(new.path_infos), old.key
        else:
            assert set(old.path_infos) <= set(new.path_infos), old.key
            assert new.services_affected >= old.services_affected, old.key
