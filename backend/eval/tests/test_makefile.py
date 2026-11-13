"""EV-RUN-1: the root Makefile defines `eval` and `eval-merge` exactly, with no PYTHONPATH.

The `.PHONY` line must list `eval`, `eval-merge` and every target the Makefile defines.
"""

from __future__ import annotations

import re
from pathlib import Path

MAKEFILE = Path(__file__).resolve().parents[3] / "Makefile"

REQUIRED_PHONY = ("eval", "eval-merge")
_TARGET_RE = re.compile(r"([A-Za-z0-9_][A-Za-z0-9_.-]*)\s*:(?!=)")
EVAL_RECIPE = "\tcd backend && uv run python -m eval"
MERGE_RECIPE = "\tcd backend && uv run python -m eval merge $(ARGS)"


def defined_targets(lines: list[str]) -> list[str]:
    """Targets defined at column 0 (recipes, comments and special `.X` targets are skipped)."""
    return [m.group(1) for line in lines if (m := _TARGET_RE.match(line))]


def phony_targets(lines: list[str]) -> set[str]:
    """Every name listed on any `.PHONY:` line."""
    names: set[str] = set()
    for line in lines:
        if line.startswith(".PHONY:"):
            names.update(line.removeprefix(".PHONY:").split())
    return names


def check_makefile(text: str) -> list[str]:
    """Return the problems found in the Makefile text (empty when it is correct)."""
    problems: list[str] = []
    lines = text.splitlines()
    phony = phony_targets(lines)
    for target in dict.fromkeys([*REQUIRED_PHONY, *defined_targets(lines)]):
        if target not in phony:
            problems.append(f"{target!r} is not listed on the .PHONY line")
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
        ".PHONY: eval eval-merge\n"
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
        ".PHONY: eval eval-merge\n"
        "eval:\n"
        "    cd backend && uv run python -m eval\n"
        "\n"
        "eval-merge:\n"
        f"{MERGE_RECIPE}\n"
    )
    assert any("recipe of 'eval:'" in p for p in check_makefile(bad))


def test_checker_requires_every_defined_target_to_be_phony() -> None:
    text = (
        ".PHONY: eval eval-merge\n"
        "eval:\n"
        f"{EVAL_RECIPE}\n"
        "eval-merge:\n"
        f"{MERGE_RECIPE}\n"
        "eval-other:\n"
        "\ttrue\n"
    )
    assert check_makefile(text) == ["'eval-other' is not listed on the .PHONY line"]


def test_checker_requires_eval_and_eval_merge_on_phony_line() -> None:
    text = f".PHONY: eval-other\neval:\n{EVAL_RECIPE}\neval-merge:\n{MERGE_RECIPE}\n"
    problems = check_makefile(text)
    assert "'eval' is not listed on the .PHONY line" in problems
    assert "'eval-merge' is not listed on the .PHONY line" in problems


def test_checker_accepts_extra_phony_targets() -> None:
    text = (
        ".PHONY: eval eval-merge eval-other\n"
        "eval:\n"
        f"{EVAL_RECIPE}\n"
        "eval-merge:\n"
        f"{MERGE_RECIPE}\n"
        "eval-other:\n"
        "\ttrue\n"
    )
    assert check_makefile(text) == []
