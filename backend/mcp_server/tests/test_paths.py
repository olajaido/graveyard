"""Path confinement for ``autopsy_project`` (T11.3; KPW-MCP-4).

``check_confine`` runs the whole case table against a ``confine`` function and returns one
message per wrong outcome. It is run on the real function (no problems) and on two naive
variants (problems), so the table cannot pass vacuously.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pytest

from mcp_server.paths import OUTSIDE_ROOT_MESSAGE, confine

Confine = Callable[[str, Path], Path]

SECRET_NAME = "distinctive-secret-dir-name-7d41"


class Layout:
    """A root with an inside tree and an outside sibling, built in ``tmp_path``."""

    def __init__(self, base: Path) -> None:
        self.root = base / "root"
        self.outside = base / "outside"
        (self.root / "project" / "sub").mkdir(parents=True)
        (self.root / "other").mkdir()
        self.outside.mkdir()
        (self.root / "a_file.txt").write_text("x", encoding="utf-8")
        (self.root / "escape").symlink_to(self.outside, target_is_directory=True)
        (self.root / "project" / "up").symlink_to(self.outside, target_is_directory=True)
        (self.root / "inside_link").symlink_to(self.root / "project", target_is_directory=True)
        (self.root / "loop").symlink_to(self.root / "loop")
        (self.root / "file_link").symlink_to(self.root / "a_file.txt")


def expected_ok(layout: Layout) -> dict[str, Path]:
    """Inputs that must be accepted, with the resolved directory each must give."""
    root = layout.root.resolve()
    return {
        "project": root / "project",
        "project/sub": root / "project" / "sub",
        "./project/": root / "project",
        ".": root,
        "": root,
        "project/../other": root / "other",
        "project/sub/..": root / "project",
        str(layout.root / "project"): root / "project",  # absolute and inside
        "inside_link": root / "project",  # a symlink that stays inside
    }


def expected_rejected(layout: Layout) -> list[str]:
    """Inputs that must be rejected."""
    return [
        str(layout.outside),  # absolute, outside
        str(layout.root.parent),  # the parent of the root
        "..",
        "../outside",
        "project/../../outside",
        "escape",  # symlink to an outside directory
        "escape/",
        "project/up",  # a symlink further down
        "a_file.txt",  # a file
        "file_link",  # a link to a file
        "missing",  # does not exist
        "project/missing/..",
        "loop",  # symlink loop
        "bad\x00name",  # NUL byte
        "/",
        "/etc",
    ]


def check_confine(fn: Confine, layout: Layout) -> list[str]:
    problems: list[str] = []
    for text, want in expected_ok(layout).items():
        try:
            got = fn(text, layout.root)
        except ValueError as error:
            problems.append(f"{text!r} should be accepted but raised {error}")
            continue
        if got != want:
            problems.append(f"{text!r} gave {got}, expected {want}")
    for text in expected_rejected(layout):
        try:
            got = fn(text, layout.root)
        except ValueError as error:
            if str(error) != OUTSIDE_ROOT_MESSAGE:
                problems.append(f"{text!r} raised a different message: {error}")
        else:
            problems.append(f"{text!r} should be rejected but gave {got}")
    return problems


@pytest.fixture
def layout(tmp_path: Path) -> Layout:
    return Layout(tmp_path)


# ------------------------------------------------------------------------- the real function


def test_confine_accepts_and_rejects_every_case(layout: Layout) -> None:
    assert check_confine(confine, layout) == []


def test_the_result_is_resolved_and_inside_the_root(layout: Layout) -> None:
    result = confine("inside_link", layout.root)
    assert result == (layout.root / "project").resolve()
    assert not result.is_symlink()


def test_a_root_given_through_a_symlink_is_resolved(layout: Layout, tmp_path: Path) -> None:
    link = tmp_path / "root_link"
    link.symlink_to(layout.root, target_is_directory=True)
    assert confine("project", link) == (layout.root / "project").resolve()
    with pytest.raises(ValueError, match=OUTSIDE_ROOT_MESSAGE):
        confine("escape", link)


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read any directory")
def test_an_unreadable_directory_is_rejected(layout: Layout) -> None:
    locked = layout.root / "locked"
    locked.mkdir()
    locked.chmod(0o000)
    try:
        with pytest.raises(ValueError) as caught:
            confine("locked", layout.root)
        assert str(caught.value) == OUTSIDE_ROOT_MESSAGE
    finally:
        locked.chmod(0o755)


def test_a_missing_root_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=OUTSIDE_ROOT_MESSAGE):
        confine(".", tmp_path / "no-such-root")


@pytest.mark.parametrize(
    "text",
    [
        f"missing/{SECRET_NAME}",
        f"../{SECRET_NAME}",
        f"a_file.txt/{SECRET_NAME}",
        f"/etc/{SECRET_NAME}",
        f"{SECRET_NAME}\x00",
        "escape",
        "loop",
    ],
)
def test_the_error_never_contains_the_path(layout: Layout, text: str) -> None:
    with pytest.raises(ValueError) as caught:
        confine(text, layout.root)
    error = caught.value
    assert error.args == (OUTSIDE_ROOT_MESSAGE,)
    assert str(error) == OUTSIDE_ROOT_MESSAGE
    assert repr(error) == f"ValueError({OUTSIDE_ROOT_MESSAGE!r})"
    assert SECRET_NAME not in str(error) + repr(error)
    assert str(layout.root) not in str(error) + repr(error)
    assert error.__cause__ is None  # no chained system error text
    assert error.__suppress_context__ is True


def test_the_fixed_message_names_no_path() -> None:
    assert "/" not in OUTSIDE_ROOT_MESSAGE
    assert OUTSIDE_ROOT_MESSAGE == "path is not a directory inside the allowed root"


# ------------------------------------------------------------------------ bad samples


def _string_prefix_confine(path: str, root: Path) -> Path:
    """Bad: checks the text, never resolves, so ``..`` and symlinks escape."""
    candidate = root / path
    if not str(candidate).startswith(str(root)) or not candidate.is_dir():
        raise ValueError(OUTSIDE_ROOT_MESSAGE)
    return candidate


def _no_symlink_confine(path: str, root: Path) -> Path:
    """Bad: resolves ``..`` lexically but checks containment before following symlinks."""
    lexical = Path(os.path.normpath(root / path))
    if root != lexical and root not in lexical.parents or not lexical.is_dir():
        raise ValueError(OUTSIDE_ROOT_MESSAGE)
    return lexical


def _leaky_confine(path: str, root: Path) -> Path:
    """Bad: right decisions, but the message carries the path."""
    try:
        return confine(path, root)
    except ValueError:
        raise ValueError(f"not allowed: {path}") from None


@pytest.mark.parametrize("bad", [_string_prefix_confine, _no_symlink_confine, _leaky_confine])
def test_the_case_table_catches_a_naive_implementation(layout: Layout, bad: Confine) -> None:
    assert check_confine(bad, layout) != []


def test_the_leak_check_catches_a_message_with_the_path(layout: Layout) -> None:
    with pytest.raises(ValueError) as caught:
        _leaky_confine(f"missing/{SECRET_NAME}", layout.root)
    assert SECRET_NAME in str(caught.value)
