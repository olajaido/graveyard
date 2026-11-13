"""``mcp_server.__main__``: the environment wiring and ``resolve_root`` (T11.3; KPW-MCP-4, -7).

``${NAME}`` is recognised twice: by ``cli.env`` (token and contact) and by ``resolve_root``
(root). The tests below pin both to the same answers, so a change to one pattern fails here.
"""

from __future__ import annotations

import string
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cli.env import environment_from_mapping
from core.sources.secret import SecretToken
from mcp_server import __main__ as entry
from mcp_server.__main__ import ROOT_VARIABLE, resolve_root
from mcp_server.tests.support import TOKEN

UNEXPANDED = ["${GRAVEYARD_MCP_ROOT}", "${X}", "${_a1}", "  ${X}  ", "\t${X}\n"]
NOT_REFERENCES = ["$X", "${}", "${1X}", "${X", "x${X}", "${X}${Y}", "${X-Y}", "${é}"]


# --------------------------------------------------------------------------- resolve_root


def test_a_usable_root_is_used_and_resolved(tmp_path: Path) -> None:
    target = tmp_path / "root"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    assert resolve_root(str(target), cwd) == target.resolve()
    assert resolve_root(f"  {target}  ", cwd) == target.resolve()
    assert resolve_root(str(link), cwd) == target.resolve()


@pytest.mark.parametrize("raw", [None, "", "   ", "\n", *UNEXPANDED])
def test_an_absent_or_unexpanded_root_falls_back_to_the_working_directory(
    raw: str | None, tmp_path: Path
) -> None:
    assert resolve_root(raw, tmp_path) == tmp_path.resolve()


def test_a_missing_or_non_directory_root_falls_back(tmp_path: Path) -> None:
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")
    assert resolve_root(str(tmp_path / "missing"), tmp_path) == tmp_path.resolve()
    assert resolve_root(str(tmp_path / "file.txt"), tmp_path) == tmp_path.resolve()
    assert resolve_root("bad\x00root", tmp_path) == tmp_path.resolve()


@pytest.mark.parametrize("raw", UNEXPANDED)
def test_a_directory_literally_named_like_a_reference_is_not_used(
    raw: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``${X}`` must not be read as the relative directory ``${X}`` that happens to exist."""
    base = tmp_path / "base"
    base.mkdir()
    (base / raw.strip()).mkdir()
    monkeypatch.chdir(base)
    assert resolve_root(raw, tmp_path) == tmp_path.resolve()
    assert resolve_root(raw.strip(), tmp_path) == tmp_path.resolve()


@pytest.mark.parametrize("raw", NOT_REFERENCES)
def test_text_that_is_not_a_whole_reference_is_treated_as_a_path(
    raw: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path / "base"
    (base / raw).mkdir(parents=True)
    monkeypatch.chdir(base)
    other = tmp_path / "other"
    other.mkdir()
    assert resolve_root(raw, other) == (base / raw).resolve()


# ------------------------------------------------ the two patterns agree (cli.env and here)


def _env_says_absent(raw: str) -> bool:
    return environment_from_mapping({"GRAVEYARD_CONTACT": raw}, 100).contact is None


def _root_says_absent(raw: str, tmp_path: Path) -> bool:
    """True when ``raw`` is dropped although it names an existing directory."""
    return resolve_root(raw, tmp_path) == tmp_path.resolve()


@pytest.mark.parametrize("raw", [*UNEXPANDED, *NOT_REFERENCES])
def test_cli_env_and_resolve_root_agree_on_what_a_reference_is(
    raw: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path / "base"
    (base / raw.strip()).mkdir(parents=True)  # a directory exists under that very name
    monkeypatch.chdir(base)
    token_absent = environment_from_mapping({"GITHUB_TOKEN": raw}, 100).token is None
    contact_absent = _env_says_absent(raw)
    root_absent = _root_says_absent(raw, tmp_path)
    assert token_absent == contact_absent == root_absent, raw
    assert token_absent == (raw in UNEXPANDED)


_names = st.text(alphabet=string.ascii_letters + "_", min_size=1, max_size=1) | st.text(
    alphabet=string.ascii_letters + string.digits + "_", min_size=1, max_size=12
).map(lambda t: "A" + t)
_padding = st.text(alphabet=" \t\n", max_size=3)


@pytest.mark.property
@given(name=_names, left=_padding, right=_padding)
def test_property_every_padded_reference_is_absent_for_all_three_variables(
    name: str, left: str, right: str, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """**Validates: Requirements KPW-MCP-7** (the token, the contact and the root)."""
    raw = f"{left}${{{name}}}{right}"
    cwd = tmp_path_factory.mktemp("cwd")
    env = environment_from_mapping(
        {"GITHUB_TOKEN": raw, "GRAVEYARD_CONTACT": raw, ROOT_VARIABLE: raw}, 100
    )
    assert env.token is None
    assert env.token_rejected is False
    assert env.contact is None
    assert resolve_root(raw, cwd) == cwd.resolve()


# ------------------------------------------------------------------------------- main()


class _Spy:
    """Stands in for ``build_server``: records its arguments and what ``run`` was asked."""

    def __init__(self) -> None:
        self.env: Any = None
        self.root: Path | None = None
        self.transport: str | None = None

    def build(self, env: Any, root: Path) -> _Spy:
        self.env, self.root = env, root
        return self

    def run(self, transport: str) -> None:
        self.transport = transport


def _run_main(monkeypatch: pytest.MonkeyPatch, **variables: str) -> _Spy:
    for name in ("GITHUB_TOKEN", "GRAVEYARD_CONTACT", ROOT_VARIABLE):
        monkeypatch.delenv(name, raising=False)
    for name, value in variables.items():
        monkeypatch.setenv(name, value)
    spy = _Spy()
    monkeypatch.setattr(entry, "build_server", spy.build)
    entry.main()
    return spy


def test_main_reads_the_environment_and_runs_on_stdio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    spy = _run_main(
        monkeypatch,
        GITHUB_TOKEN=TOKEN,
        GRAVEYARD_CONTACT="ops@example.org",
        GRAVEYARD_MCP_ROOT=str(root),
    )
    assert isinstance(spy.env.token, SecretToken)
    assert spy.env.token.reveal() == TOKEN
    assert spy.env.contact == "ops@example.org"
    assert spy.root == root.resolve()
    assert spy.transport == "stdio"
    assert TOKEN not in repr(spy.env)


def test_main_treats_unexpanded_references_as_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "${GRAVEYARD_MCP_ROOT}").mkdir()
    spy = _run_main(
        monkeypatch,
        GITHUB_TOKEN="${GITHUB_TOKEN}",
        GRAVEYARD_CONTACT="${GRAVEYARD_CONTACT}",
        GRAVEYARD_MCP_ROOT="${GRAVEYARD_MCP_ROOT}",
    )
    assert spy.env.token is None
    assert spy.env.token_rejected is False
    assert spy.env.contact is None
    assert spy.root == tmp_path.resolve()  # the working directory, not the odd subdirectory
    assert capfd.readouterr().out == ""  # main prints nothing: stdout is the protocol


def test_main_without_variables_uses_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    spy = _run_main(monkeypatch)
    assert spy.env.token is None
    assert spy.root == tmp_path.resolve()
