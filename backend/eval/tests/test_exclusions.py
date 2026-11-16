"""Tests for ``eval.heldout.exclusions`` (MV2-POP-1; design 8.4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.heldout.exclusions import (
    EXPECTED_ANCHORS,
    EXPECTED_NPM,
    EXPECTED_PYPI,
    EXPECTED_RESERVE,
    build_exclusions,
    exclusions_tsv,
    missing_labelled,
    parse_plan,
    read_pool,
)

REPO = Path(__file__).resolve().parents[3]


def _plan(npm: int = EXPECTED_NPM, pypi: int = EXPECTED_PYPI, rn: int = 8, rp: int = 7) -> str:
    def names(prefix: str, n: int) -> str:
        return ", ".join(f"{prefix}{i}" for i in range(n))

    return (
        "# Labelling\n\n## 9. Candidate plan\n\n"
        f"### npm ({npm})\n\n{names('n', npm)}\n\n"
        f"### PyPI ({pypi})\n\n{names('Py', pypi)}\n\n"
        "### Reserve list (fixed)\n\nprose\n\n"
        f"npm: {names('rn', rn)}\nPyPI: {names('rp', rp)}\n\n"
        "### Additions\n\nnpm: later, other\n\n## 10. Next\n"
    )


def _anchor(purl: str) -> str:
    return json.dumps({"package": "x", "purl": purl})


def test_parse_plan_synthetic() -> None:
    plan = parse_plan(_plan())
    assert (len(plan.npm), len(plan.pypi)) == (EXPECTED_NPM, EXPECTED_PYPI)
    assert len(plan.reserve_npm) + len(plan.reserve_pypi) == EXPECTED_RESERVE
    assert plan.reserve_npm[0] == "rn0"


@pytest.mark.parametrize(
    "text",
    [_plan(npm=53), _plan(pypi=48), _plan(rn=7), "no section here\n"],
)
def test_parse_plan_wrong_count_raises(text: str) -> None:
    with pytest.raises(ValueError):
        parse_plan(text)


def test_pool_missing_column_raises() -> None:
    with pytest.raises(ValueError, match="name"):
        read_pool("ecosystem\trepo\nnpm\ta/b\n", "pool.tsv")
    with pytest.raises(ValueError, match="ecosystem"):
        build_exclusions(_plan(), {}, {"p.tsv": "name\nfoo\n"})


def test_pool_read_by_header_any_order() -> None:
    assert read_pool("rank\tname\tx\tecosystem\n1\tfoo\t-\tnpm\n", "p") == [("npm", "foo")]


def test_invalid_names_reported_and_valid_normalised() -> None:
    pool = "ecosystem\tname\nnpm\t@scope/pkg\nnpm\tUpper\npypi\tFoo_Bar\n"
    result = build_exclusions(
        _plan(), {"a.json": _anchor("pkg:npm/request@2.88.2")}, {"p.tsv": pool}
    )
    assert {(r.ecosystem, r.name, r.source_file) for r in result.rejected} == {
        ("npm", "@scope/pkg", "p.tsv"),
        ("npm", "Upper", "p.tsv"),
    }
    assert ("pypi", "foo-bar", "p.tsv", "pool") in result.rows
    assert ("pypi", "py0", "eval/LABELLING.md", "plan") in result.rows
    assert ("npm", "request", "a.json", "anchor") in result.rows
    assert list(result.rows) == sorted(result.rows)


def test_exclusions_tsv_header_and_rows() -> None:
    result = build_exclusions(_plan(), {}, {})
    lines = exclusions_tsv(result).splitlines()
    assert lines[0] == "ecosystem\tname\tsource_file\tsource_kind"
    assert len(lines) == 1 + EXPECTED_NPM + EXPECTED_PYPI + EXPECTED_RESERVE


def test_anchor_without_purl_raises() -> None:
    with pytest.raises(ValueError, match="purl"):
        build_exclusions(_plan(), {"a.json": "{}"}, {})


def test_real_data_covers_every_labelled_key() -> None:
    label_text = (REPO / "eval/LABELLING.md").read_text(encoding="utf-8")
    plan = parse_plan(label_text)
    assert (len(plan.npm), len(plan.pypi)) == (54, 47)
    assert len(plan.reserve_npm) + len(plan.reserve_pypi) == 15

    anchor_dir = REPO / "backend/core/scoring/tests/fixtures/anchors"
    anchors = {
        f"backend/core/scoring/tests/fixtures/anchors/{p.name}": p.read_text(encoding="utf-8")
        for p in sorted(anchor_dir.glob("*.json"))
    }
    assert len(anchors) == EXPECTED_ANCHORS == 9

    pools = {
        rel: (REPO / rel).read_text(encoding="utf-8")
        for rel in (
            "eval/addition1/pools.tsv",
            "eval/addition2/pool.tsv",
            "eval/addition3/pool.tsv",
        )
    }
    result = build_exclusions(label_text, anchors, pools)
    kinds = [r[3] for r in result.rows]
    assert kinds.count("anchor") == 9
    assert kinds.count("plan") == 54 + 47
    assert kinds.count("reserve") == 15

    labelled = (REPO / "eval/labelled_packages.csv").read_text(encoding="utf-8")
    assert missing_labelled(result, labelled) == []
