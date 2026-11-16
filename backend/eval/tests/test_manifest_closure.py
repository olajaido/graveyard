"""Tests for ``eval.manifest.closure`` on synthetic package trees (mortality-model-v2 T1.1)."""

from __future__ import annotations

import random
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from eval.manifest import ManifestError, closure


def make_tree(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def rels(root: Path, paths: tuple[Path, ...]) -> list[str]:
    return [p.relative_to(root).as_posix() for p in paths]


BASE = {"core/__init__.py": "", "core/pkg/__init__.py": ""}


def test_parent_inits_are_included(tmp_path: Path) -> None:
    make_tree(tmp_path, {**BASE, "core/pkg/sub/__init__.py": "", "core/pkg/sub/leaf.py": "X = 1\n"})
    result = closure("core.pkg.sub.leaf", tmp_path)
    assert rels(tmp_path, result) == [
        "core/__init__.py",
        "core/pkg/__init__.py",
        "core/pkg/sub/__init__.py",
        "core/pkg/sub/leaf.py",
    ]


def test_relative_imports_are_followed(tmp_path: Path) -> None:
    make_tree(
        tmp_path,
        {
            **BASE,
            "core/pkg/a.py": "from . import b\nfrom .c import Y\nfrom ..other import Z\n",
            "core/pkg/b.py": "",
            "core/pkg/c.py": "Y = 1\n",
            "core/other.py": "Z = 1\n",
            "core/unused.py": "",
        },
    )
    result = rels(tmp_path, closure("core.pkg.a", tmp_path))
    assert result == [
        "core/__init__.py",
        "core/other.py",
        "core/pkg/__init__.py",
        "core/pkg/a.py",
        "core/pkg/b.py",
        "core/pkg/c.py",
    ]


def test_absolute_imports_and_from_name_attributes(tmp_path: Path) -> None:
    make_tree(
        tmp_path,
        {
            **BASE,
            "core/pkg/a.py": "import core.pkg.b\nfrom core.pkg.c import helper\n",
            "core/pkg/b.py": "",
            "core/pkg/c.py": "def helper() -> None: ...\n",
        },
    )
    result = rels(tmp_path, closure("core.pkg.a", tmp_path))
    assert "core/pkg/b.py" in result and "core/pkg/c.py" in result


def test_third_party_and_stdlib_are_not_followed(tmp_path: Path) -> None:
    make_tree(
        tmp_path,
        {
            **BASE,
            "core/pkg/a.py": "import os\nimport yaml\nfrom pathlib import Path\nimport sources.x\n",
            "sources/x.py": "",
            "os.py": "",
        },
    )
    assert rels(tmp_path, closure("core.pkg.a", tmp_path)) == [
        "core/__init__.py",
        "core/pkg/__init__.py",
        "core/pkg/a.py",
    ]


def test_package_entry_module(tmp_path: Path) -> None:
    make_tree(tmp_path, {**BASE, "core/pkg/m.py": ""})
    assert rels(tmp_path, closure("core.pkg", tmp_path)) == [
        "core/__init__.py",
        "core/pkg/__init__.py",
    ]


def test_imports_inside_functions_are_followed(tmp_path: Path) -> None:
    make_tree(
        tmp_path,
        {
            **BASE,
            "core/pkg/a.py": "def f() -> None:\n    from core.pkg import b\n",
            "core/pkg/b.py": "",
        },
    )
    assert "core/pkg/b.py" in rels(tmp_path, closure("core.pkg.a", tmp_path))


@pytest.mark.parametrize(
    "source",
    [
        "from core.pkg.b import *\n",
        "import importlib\n",
        "import importlib.util\n",
        "from importlib import import_module\n",
        "__import__('os')\n",
        "exec('x = 1')\n",
        "eval('1')\n",
        "compile('1', 'f', 'eval')\n",
    ],
    ids=[
        "star",
        "importlib",
        "importlib-submodule",
        "from-importlib",
        "dunder-import",
        "exec",
        "eval",
        "compile",
    ],
)
def test_rejected_constructs(tmp_path: Path, source: str) -> None:
    make_tree(tmp_path, {**BASE, "core/pkg/a.py": source, "core/pkg/b.py": ""})
    with pytest.raises(ManifestError):
        closure("core.pkg.a", tmp_path)


def test_rejected_construct_in_a_transitive_module(tmp_path: Path) -> None:
    make_tree(
        tmp_path, {**BASE, "core/pkg/a.py": "import core.pkg.b\n", "core/pkg/b.py": "eval('1')\n"}
    )
    with pytest.raises(ManifestError):
        closure("core.pkg.a", tmp_path)


def test_rejected_construct_in_a_parent_init(tmp_path: Path) -> None:
    make_tree(
        tmp_path,
        {"core/__init__.py": "", "core/pkg/__init__.py": "exec('1')\n", "core/pkg/a.py": ""},
    )
    with pytest.raises(ManifestError):
        closure("core.pkg.a", tmp_path)


def test_attribute_named_compile_is_allowed(tmp_path: Path) -> None:
    make_tree(tmp_path, {**BASE, "core/pkg/a.py": "import re\nP = re.compile('x')\n"})
    assert closure("core.pkg.a", tmp_path)


def test_unresolvable_first_party_import(tmp_path: Path) -> None:
    make_tree(tmp_path, {**BASE, "core/pkg/a.py": "import core.pkg.missing\n"})
    with pytest.raises(ManifestError):
        closure("core.pkg.a", tmp_path)


def test_missing_parent_init_is_unresolvable(tmp_path: Path) -> None:
    make_tree(tmp_path, {"core/__init__.py": "", "core/pkg/a.py": ""})
    with pytest.raises(ManifestError):
        closure("core.pkg.a", tmp_path)


def test_relative_import_beyond_top_package(tmp_path: Path) -> None:
    make_tree(tmp_path, {**BASE, "core/pkg/a.py": "from ... import x\n"})
    with pytest.raises(ManifestError):
        closure("core.pkg.a", tmp_path)


def test_entry_must_be_first_party(tmp_path: Path) -> None:
    make_tree(tmp_path, {"sources/__init__.py": ""})
    with pytest.raises(ManifestError):
        closure("sources", tmp_path)


def test_unparsable_file(tmp_path: Path) -> None:
    make_tree(tmp_path, {**BASE, "core/pkg/a.py": "def (:\n"})
    with pytest.raises(ManifestError):
        closure("core.pkg.a", tmp_path)


@pytest.mark.property
@settings(max_examples=100, deadline=None)
@given(
    edges=st.lists(st.tuples(st.integers(0, 5), st.integers(0, 5)), max_size=20),
    seed_a=st.integers(0, 10_000),
    seed_b=st.integers(0, 10_000),
)
def test_result_independent_of_file_listing_and_import_order(
    tmp_path_factory: pytest.TempPathFactory, edges: list[tuple[int, int]], seed_a: int, seed_b: int
) -> None:
    """**Validates: Requirements MV2-ISO-4**"""

    def build(seed: int) -> list[str]:
        rng = random.Random(seed)
        root = tmp_path_factory.mktemp("tree")
        files = {"core/__init__.py": "", "core/pkg/__init__.py": ""}
        for i in range(6):
            lines = [
                f"from core.pkg import m{j}" if rng.random() < 0.5 else f"import core.pkg.m{j}"
                for (src, j) in edges
                if src == i
            ]
            rng.shuffle(lines)
            files[f"core/pkg/m{i}.py"] = "\n".join(lines) + "\n"
        names = list(files)
        rng.shuffle(names)
        make_tree(root, {name: files[name] for name in names})
        return rels(root, closure("core.pkg.m0", root))

    assert build(seed_a) == build(seed_b)
