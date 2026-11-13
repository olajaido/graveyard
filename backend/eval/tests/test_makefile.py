"""EV-RUN-1: the root Makefile defines `eval` and `eval-merge` exactly, with no PYTHONPATH."""

from __future__ import annotations

from pathlib import Path

MAKEFILE = Path(__file__).resolve().parents[3] / "Makefile"

PHONY_LINE = ".PHONY: eval eval-merge"
EVAL_RECIPE = "\tcd backend && uv run python -m eval"
MERGE_RECIPE = "\tcd backend && uv run python -m eval merge $(ARGS)"


def check_makefile(text: str) -> list[str]:
    """Return the problems found in the Makefile text (empty when it is correct)."""
    problems: list[str] = []
    lines = text.splitlines()
    if PHONY_LINE not in lines:
        problems.append(f"missing line {PHONY_LINE!r}")
    for target, recipe in (("eval:", EVAL_RECIPE), ("eval-merge:", MERGE_RECIPE)):
        if target not in lines:
            problems.append(f"missing target line {target!r}")
            continue
        following = lines[lines.index(target) + 1 :]
        if not following or following[0] != recipe:
            problems.append(f"recipe of {target!r} is not exactly {recipe!r}")
    if "PYTHONPATH" in text:
        problems.append("contains PYTHONPATH")
    return problems


def test_makefile_recipes_are_literal() -> None:
    assert MAKEFILE.is_file()
    assert check_makefile(MAKEFILE.read_text(encoding="utf-8")) == []


def test_makefile_has_no_pythonpath() -> None:
    assert "PYTHONPATH" not in MAKEFILE.read_text(encoding="utf-8")


def test_checker_rejects_pythonpath_recipe() -> None:
    bad = (
        f"{PHONY_LINE}\n"
        "eval:\n"
        "\tcd backend && PYTHONPATH=.. uv run python -m eval\n"
        "\n"
        "eval-merge:\n"
        f"{MERGE_RECIPE}\n"
    )
    problems = check_makefile(bad)
    assert "contains PYTHONPATH" in problems
    assert any("recipe of 'eval:'" in p for p in problems)


def test_checker_rejects_space_indented_recipe() -> None:
    bad = (
        f"{PHONY_LINE}\n"
        "eval:\n"
        "    cd backend && uv run python -m eval\n"
        "\n"
        "eval-merge:\n"
        f"{MERGE_RECIPE}\n"
    )
    assert any("recipe of 'eval:'" in p for p in check_makefile(bad))
