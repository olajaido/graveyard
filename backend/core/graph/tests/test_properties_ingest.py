"""Property tests for CycloneDX ingest, ``core.graph.cyclonedx.parse_service`` (T3.4).

Validates DG-ROOT-5, DG-DUP-1, DG-DUP-2, DG-DUP-3, DG-INV-2 and DG-INV-11 at the
level of one service (design §7.1). Expected values come from the abstract model
in ``tests/strategies.py`` (``AbstractPackage.key``, the abstract edge set and the
purl spellings recorded by ``render``), never from re-running ingest logic.

Profiles (``dev`` = 200 examples, ``ci`` = 500) come from ``conftest.py`` via
``HYPOTHESIS_PROFILE``. No ``max_examples`` is set here. Every test sets an
explicit five-second deadline and none disables it (DG-NFR-7).
"""

from __future__ import annotations

import copy
from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.graph.cyclonedx import IngestLimits, ParsedService, parse_service
from core.graph.tests.strategies import (
    AbstractService,
    AbstractServices,
    RenderFlags,
    abstract_services,
    json_like,
    mutated,
    render,
    render_flags,
    shuffled,
    with_duplicates,
)

pytestmark = pytest.mark.property

DEADLINE = timedelta(seconds=5)
LIMITS = IngestLimits()
SEEDS = st.integers(min_value=0, max_value=2**32 - 1)


def _expected_keys(abstract: AbstractServices, svc: AbstractService) -> set[str]:
    return {abstract.packages[m].key for m in svc.members}


def _expected_directs(abstract: AbstractServices, svc: AbstractService) -> tuple[str, ...]:
    return tuple(sorted(abstract.packages[d].key for d in svc.directs))


def _expected_adj(abstract: AbstractServices, svc: AbstractService) -> dict[str, set[str]]:
    """Successors per key from the abstract edges. Self-edges are dropped (DG-ING-10)."""
    adj: dict[str, set[str]] = {}
    for u, v in svc.edges:
        if u != v:
            adj.setdefault(abstract.packages[u].key, set()).add(abstract.packages[v].key)
    return adj


def _add_extra_roots(bom: dict[str, Any], count: int) -> dict[str, Any]:
    """Return a copy with ``count`` more unreferenced entries that have children.

    Each one is a component plus a ``dependencies`` entry that nothing refers to, so the
    BOM has several root candidates (DG-ROOT-4), or, when the service had no root, exactly
    these (the orphan rule). The children are the generated library components.
    """
    out = copy.deepcopy(bom)
    children = [
        c["bom-ref"]
        for c in out["components"]
        if c.get("type") == "library" and c.get("name") != "graveyard-gen-root"
    ]
    for i in range(count):
        ref = f"pkg:npm/extra-root-{i}@0.0.1?package-id={i:016x}"
        out["components"].append(
            {
                "bom-ref": ref,
                "type": "library",
                "name": f"extra-root-{i}",
                "version": "0.0.1",
                "purl": f"pkg:npm/extra-root-{i}@0.0.1",
            }
        )
        out["dependencies"].append({"ref": ref, "dependsOn": children[i:] or ["dangling"]})
    return out


def _alias_flags(flags: RenderFlags) -> RenderFlags:
    """Force the rendering variants that put one identity into several components."""
    return replace(flags, alias_identities=True, vary_case=True, split_entries=True)


@settings(deadline=DEADLINE)
@given(
    abstract=abstract_services(),
    flags=render_flags(),
    seed=SEEDS,
    extra_roots=st.sampled_from((0, 0, 1, 2)),
)
def test_parse_service_order_independent(
    abstract: AbstractServices, flags: RenderFlags, seed: int, extra_roots: int
) -> None:
    """**Validates: Requirements DG-ROOT-5, DG-INV-1**

    Shuffling every list and mapping of a rendered BOM does not change the result. This
    includes BOMs with extra root candidates (multiple roots, or an orphan entry when the
    service has no root), where the root-selection rule decides what the graph looks like.
    """
    for svc, out in zip(abstract.services, render(abstract, flags), strict=True):
        bom = _add_extra_roots(out.bom, extra_roots) if extra_roots else out.bom
        base = parse_service(out.path, bom, LIMITS)
        assert parse_service(out.path, shuffled(bom, seed), LIMITS) == base
        assert parse_service(out.path, shuffled(shuffled(bom, seed + 1), seed + 2), LIMITS) == base
        if not extra_roots:
            # The result also matches the abstract model, not just itself.
            assert set(base.packages) == _expected_keys(abstract, svc)
            assert base.directs == _expected_directs(abstract, svc)
            # ``render_flags`` sometimes splits one ref's dependsOn across two entries, so the
            # union of entries per ref (DG-DUP-1) must give the abstract edge set exactly.
            assert {k: set(v) for k, v in base.adj.items()} == _expected_adj(abstract, svc)


@settings(deadline=DEADLINE)
@given(abstract=abstract_services(), flags=render_flags(), seed=SEEDS)
def test_parse_service_duplicates_idempotent(
    abstract: AbstractServices, flags: RenderFlags, seed: int
) -> None:
    """**Validates: Requirements DG-DUP-2, DG-INV-2**

    Duplicating components, ``dependencies`` entries and ``dependsOn`` elements leaves the
    result equal, also when the duplicated BOM is shuffled and when it is duplicated twice.
    """
    for svc, out in zip(abstract.services, render(abstract, flags), strict=True):
        original = copy.deepcopy(out.bom)
        base = parse_service(out.path, out.bom, LIMITS)
        doubled = with_duplicates(out.bom)
        assert out.bom == original
        assert parse_service(out.path, doubled, LIMITS) == base
        assert parse_service(out.path, with_duplicates(doubled), LIMITS) == base
        assert parse_service(out.path, shuffled(doubled, seed), LIMITS) == base
        assert set(base.packages) == _expected_keys(abstract, svc)


@settings(deadline=DEADLINE)
@given(abstract=abstract_services(), flags=render_flags(), seed=SEEDS)
def test_one_package_per_identity(
    abstract: AbstractServices, flags: RenderFlags, seed: int
) -> None:
    """**Validates: Requirements DG-DUP-1, DG-INV-2 (D1)**

    Within a service, all components that share an identity (other ``?package-id=`` hash,
    other npm case, other qualifiers) become exactly one package, and the edges of the
    merged bom-refs are unioned: directs and successors equal the abstract ones. Across
    services the packages are the distinct abstract identities present in some service.
    """
    seen: set[str] = set()
    for svc, out in zip(abstract.services, render(abstract, _alias_flags(flags)), strict=True):
        parsed = parse_service(out.path, shuffled(out.bom, seed), LIMITS)
        keys = _expected_keys(abstract, svc)
        assert set(parsed.packages) == keys
        assert len(parsed.packages) == len(svc.members)
        # Every merged component is accounted for: the rendered ones cover the members
        # and the aliases, so more than one component per identity can occur.
        assert out.components == sum(len(v) for v in out.spellings.values())
        assert out.components >= len(svc.members)
        assert parsed.directs == _expected_directs(abstract, svc)
        assert {k: set(v) for k, v in parsed.adj.items()} == _expected_adj(abstract, svc)
        assert all(w.code != "DANGLING_REF" for w in parsed.warnings)
        seen |= set(parsed.packages)
    assert seen == {abstract.packages[m].key for s in abstract.services for m in s.members}


@settings(deadline=DEADLINE)
@given(abstract=abstract_services(), flags=render_flags(), seed=SEEDS)
def test_display_purl_independent_of_order(
    abstract: AbstractServices, flags: RenderFlags, seed: int
) -> None:
    """**Validates: Requirements DG-DUP-3, DG-INV-2**

    The display purl of a package is the lexicographically smallest qualifier-free purl
    string among its merged components, with case preserved (upper case sorts before lower
    case, so a mixed-case spelling wins over the lower-case one), whatever the input order.
    """
    for svc, out in zip(abstract.services, render(abstract, _alias_flags(flags)), strict=True):
        expected = {key: out.expected_display(key) for key in _expected_keys(abstract, svc)}
        first = parse_service(out.path, out.bom, LIMITS)
        mixed = parse_service(out.path, shuffled(out.bom, seed), LIMITS)
        reversed_bom = copy.deepcopy(out.bom)
        reversed_bom["components"].reverse()
        backwards = parse_service(out.path, reversed_bom, LIMITS)
        for parsed in (first, mixed, backwards):
            assert dict(parsed.packages) == expected
        assert all("?" not in purl for purl in expected.values())


@st.composite
def _inputs(draw: st.DrawFn) -> Any:
    """A JSON-like value, a BOM with JSON-like sections, or a mutated valid BOM."""
    kind = draw(st.sampled_from(("json_like", "sections", "mutated")))
    if kind == "json_like":
        return draw(json_like())
    if kind == "sections":
        bom: dict[str, Any] = {"specVersion": draw(st.sampled_from(("1.5", "1.6", "1.7")))}
        for name in ("components", "dependencies", "metadata"):
            if draw(st.booleans()):
                bom[name] = draw(json_like())
        return bom
    abstract = draw(abstract_services())
    flags = _alias_flags(draw(render_flags())) if draw(st.booleans()) else draw(render_flags())
    out = draw(st.sampled_from(render(abstract, flags)))
    return draw(mutated(out.bom))


@settings(deadline=DEADLINE)
@given(candidate=_inputs())
def test_build_inputs_robust(candidate: Any) -> None:
    """**Validates: Requirements DG-INV-11, DG-OUT-4**

    Arbitrary JSON-like values, BOMs whose sections are arbitrary JSON, and valid rendered
    BOMs with one field deleted, retyped or nulled give a ``ParsedService`` or a
    ``ValueError``. Any other exception (``KeyError``, ``TypeError``, ``RecursionError``,
    ...) propagates out of the ``try`` block and fails the test.
    """
    try:
        result = parse_service("svc", candidate, LIMITS)
    except ValueError:
        return
    assert isinstance(result, ParsedService)
