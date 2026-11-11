"""Tests for the environment handling in ``cli.__main__`` (T8.3; CLI-ENV-1…6, D7).

``_environment`` is a pure function of a mapping, so these tests pass plain dicts and never
touch ``os.environ``. The one test of ``main`` patches ``run`` and sets a variable with
``monkeypatch``, to prove the wiring reads the process environment at that one place.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from typing import Any

import pytest

from cli import __main__ as entry
from cli.env import CliEnvironment
from core.sources.secret import SecretToken

TOKEN = "ghp_sentinelTOKENvalue1234567890"


def _env(**environ: str) -> CliEnvironment:
    return entry._environment(environ, 100)


def test_a_valid_token_is_wrapped_and_never_shown() -> None:
    env = _env(GITHUB_TOKEN=TOKEN)
    assert isinstance(env.token, SecretToken)
    assert env.token.reveal() == TOKEN
    assert env.token_rejected is False
    assert TOKEN not in repr(env)
    assert TOKEN not in str(env)
    assert TOKEN not in repr(env.token)


@pytest.mark.parametrize(
    "bad",
    ["", "   ", "has space", "tab\there", "new\nline", "x" * 300, "esc\x1bchar"],
)
def test_an_invalid_token_is_dropped_and_flagged(bad: str) -> None:
    env = _env(GITHUB_TOKEN=bad)
    assert env.token is None
    assert env.token_rejected is True
    assert bad.strip() == "" or bad not in repr(env)


def test_no_token_is_not_the_same_as_an_invalid_one() -> None:
    env = _env()
    assert env.token is None
    assert env.token_rejected is False


def test_contact_set_blank_and_absent() -> None:
    assert _env(GRAVEYARD_CONTACT="ops@example.org").contact == "ops@example.org"
    assert _env(GRAVEYARD_CONTACT="").contact is None
    assert _env(GRAVEYARD_CONTACT="  \t").contact is None
    assert _env().contact is None


def test_syft_environment_is_an_allow_list_plus_the_update_switch() -> None:
    environ = {
        "PATH": "/usr/bin",
        "HOME": "/home/me",
        "TMPDIR": "/tmp",
        "XDG_CACHE_HOME": "/cache",
        "XDG_CONFIG_HOME": "/config",
        "GITHUB_TOKEN": TOKEN,
        "AWS_SECRET_ACCESS_KEY": "do-not-pass",
        "GRAVEYARD_CONTACT": "ops@example.org",
        "EDITOR": "vim",
    }
    env = entry._environment(environ, 100)
    assert dict(env.syft_env) == {
        "PATH": "/usr/bin",
        "HOME": "/home/me",
        "TMPDIR": "/tmp",
        "XDG_CACHE_HOME": "/cache",
        "XDG_CONFIG_HOME": "/config",
        "SYFT_CHECK_FOR_APP_UPDATE": "false",
    }
    assert TOKEN not in str(dict(env.syft_env))


def test_only_allow_listed_variables_that_are_set_appear() -> None:
    env = _env(PATH="/usr/bin")
    assert dict(env.syft_env) == {"PATH": "/usr/bin", "SYFT_CHECK_FOR_APP_UPDATE": "false"}


def test_width_is_passed_through() -> None:
    assert entry._environment({}, 123).width == 123
    assert entry._environment({}, 1).width == 1  # clamping is the renderer's business


def test_main_reads_the_process_environment_and_exits_with_the_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def fake_run(argv: list[str], *, env: CliEnvironment, out: object, err: object) -> int:
        seen.update(argv=argv, env=env, out=out, err=err)
        return 7

    monkeypatch.setattr(entry, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["graveyard", "autopsy", "--all"])
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    monkeypatch.setenv("GRAVEYARD_CONTACT", "ops@example.org")
    with pytest.raises(SystemExit) as exit_info:
        entry.main()
    assert exit_info.value.code == 7
    assert seen["argv"] == ["autopsy", "--all"]
    env = seen["env"]
    assert isinstance(env.token, SecretToken)
    assert env.token.reveal() == TOKEN
    assert env.contact == "ops@example.org"
    assert seen["out"] is sys.stdout
    assert seen["err"] is sys.stderr


def test_environment_accepts_any_mapping() -> None:
    class Frozen(Mapping[str, str]):
        def __getitem__(self, key: str) -> str:
            return {"GITHUB_TOKEN": TOKEN}[key]

        def __iter__(self) -> Any:
            return iter(["GITHUB_TOKEN"])

        def __len__(self) -> int:
            return 1

    env = entry._environment(Frozen(), 80)
    assert env.token is not None
