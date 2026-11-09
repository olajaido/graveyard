"""Sanity checks for the CycloneDX strategies in ``strategies.py`` (T3.2).

These prove only that the strategies work: rendered BOMs parse, and the
perturbations behave as documented. The ingest properties themselves live in
``test_properties_ingest.py``.

Profiles (``dev`` = 200 examples, ``ci`` = 500) come from ``conftest.py`` via
``HYPOTHESIS_PROFILE``; no ``max_examples`` is set here and no test disables
the deadline (DG-NFR-7).
"""

from __future__ import annotations

import copy
import json
from datetime import timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.graph.cyclonedx import IngestLimits, parse_service
from core.graph.tests.strategies import (
    AbstractPackage,
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


@settings(deadline=DEADLINE)
@given(abstract=abstract_services(), flags=render_flags())
def test_rendered_boms_parse_to_the_abstract_graph(
    abstract: AbstractServices, flags: RenderFlags
) -> None:
    rendered = render(abstract, flags)
    assert len(rendered) == len(abstract.services)
    for svc, out in zip(abstract.services, rendered, strict=True):
        parsed = parse_service(out.path, out.bom, LIMITS)
        keys = {abstract.packages[m].key for m in svc.members}
        assert set(parsed.packages) == keys
        assert parsed.directs == tuple(sorted(abstract.packages[d].key for d in svc.directs))
        expected_adj: dict[str, set[str]] = {}
        for u, v in svc.edges:
            if u != v:
                expected_adj.setdefault(abstract.packages[u].key, set()).add(
                    abstract.packages[v].key
                )
        assert {k: set(v) for k, v in parsed.adj.items()} == expected_adj
        # Syft shape: one root, and no warning except a missing root when there are no directs.
        assert [w.code for w in parsed.warnings] == ([] if svc.directs else ["ROOT_NOT_FOUND"])


@settings(deadline=DEADLINE)
@given(
    abstract=abstract_services(),
    flags=render_flags(),
    seed=st.integers(min_value=0, max_value=2**32 - 1),
)
def test_shuffled_and_duplicated_renders_parse_the_same(
    abstract: AbstractServices, flags: RenderFlags, seed: int
) -> None:
    for out in render(abstract, flags):
        original = copy.deepcopy(out.bom)
        base = parse_service(out.path, out.bom, LIMITS)
        mixed = shuffled(out.bom, seed)
        doubled = with_duplicates(out.bom)
        assert out.bom == original  # the inputs are not modified
        assert parse_service(out.path, mixed, LIMITS) == base
        assert parse_service(out.path, doubled, LIMITS) == base
        assert parse_service(out.path, with_duplicates(mixed), LIMITS) == base


@settings(deadline=DEADLINE)
@given(
    abstract=abstract_services(),
    flags=render_flags(),
    seed=st.integers(min_value=0, max_value=2**32 - 1),
)
def test_shuffled_is_deterministic_and_keeps_scope_content(
    abstract: AbstractServices, flags: RenderFlags, seed: int
) -> None:
    rendered = render(abstract, flags)
    first = shuffled(rendered, seed)
    second = shuffled(rendered, seed)
    assert [s.bom for s in first] == [s.bom for s in second]
    assert sorted(s.path for s in first) == sorted(s.path for s in rendered)
    by_path = {s.path: s for s in rendered}
    for out in first:
        before = by_path[out.path].scopes
        if before is None:
            assert out.scopes is None
        else:
            assert out.scopes is not None
            assert dict(out.scopes.package_scopes) == dict(before.package_scopes)
            assert dict(out.scopes.direct_scopes) == dict(before.direct_scopes)


def test_shuffled_reorders_lists_and_mappings() -> None:
    bom = {"a": list(range(30)), "b": {f"k{i}": i for i in range(30)}}
    out = shuffled(bom, 1)
    assert sorted(out["a"]) == bom["a"] and out["a"] != bom["a"]
    assert out["b"] == bom["b"] and list(out["b"]) != list(bom["b"])


@settings(deadline=DEADLINE)
@given(data=st.data())
def test_mutated_leaves_the_input_alone(data: st.DataObject) -> None:
    abstract = data.draw(abstract_services())
    out = render(abstract, data.draw(render_flags()))[0]
    original = copy.deepcopy(out.bom)
    changed = data.draw(mutated(out.bom))
    assert out.bom == original
    json.dumps(changed)  # still plain JSON


def test_split_entries_really_repeats_a_ref_and_keeps_the_union() -> None:
    """``split_entries`` writes one ref's dependsOn as two entries for some seeds, no more."""
    packages = tuple(
        AbstractPackage("pypi", name, "1.0.0") for name in ("requests", "six", "urllib3", "flask")
    )
    svc = AbstractService(
        path="services/svc0",
        members=(0, 1, 2, 3),
        directs=(0, 3),
        scopes={m: "runtime" for m in range(4)},
        edges=((0, 1), (0, 2), (3, 1), (3, 2)),
    )
    abstract = AbstractServices(packages=packages, services=(svc,))
    split_seen = False
    for seed in range(40):
        (plain,) = render(abstract, RenderFlags(seed=seed))
        (split,) = render(abstract, RenderFlags(seed=seed, split_entries=True))
        refs = [e["ref"] for e in split.bom["dependencies"]]
        assert len({e["ref"] for e in plain.bom["dependencies"]}) == len(plain.bom["dependencies"])
        if len(refs) != len(set(refs)):
            split_seen = True
        assert parse_service(split.path, split.bom, LIMITS) == parse_service(
            plain.path, plain.bom, LIMITS
        )
    assert split_seen


@settings(deadline=DEADLINE)
@given(value=json_like())
def test_json_like_values_are_json_types(value: object) -> None:
    def check(v: object) -> None:
        if isinstance(v, list):
            for item in v:
                check(item)
        elif isinstance(v, dict):
            for key, item in v.items():
                assert isinstance(key, str)
                check(item)
        else:
            assert v is None or isinstance(v, bool | int | float | str)

    check(value)
