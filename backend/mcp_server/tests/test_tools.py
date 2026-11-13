"""The tool bodies ``run_package`` and ``run_project`` (T11.3; KPW-MCP-3, -4, -5).

These run without the MCP SDK. Rejected inputs use a transport that fails the test if it is
called at all. The bad-sample tests run the same checks on deliberately wrong runners (one that
puts exception text in the message, one that leaks the token) so the checks cannot pass
vacuously.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from cli.args import parse_args
from cli.env import CliEnvironment
from cli.errors import UsageError
from cli.pipeline import analyse
from cli.report import report_to_dict
from cli.tests.support import make_env
from cli.tests.test_e2e_purl import _MustNotBeCalled
from cli.text import sanitise
from core.sources.secret import SecretToken
from mcp_server import tools
from mcp_server.paths import OUTSIDE_ROOT_MESSAGE
from mcp_server.tests.support import (
    ANCHORS_PROJECT,
    FIXTURES_ROOT,
    REQUEST_PURL,
    TOKEN,
    cassette_transport,
    fresh_clock,
    make_token_env,
    use_stub_syft,
)
from mcp_server.tools import ToolFailure, run_package, run_project

SECRET_TEXT = "SECRET-EXCEPTION-TEXT /home/someone/private.key"


def cli_message(purl: str) -> str:
    """The message the CLI gives for ``--purl purl`` (what the tool must repeat)."""
    with pytest.raises(UsageError) as caught:
        parse_args(["autopsy", "--purl", purl, "--all"], today=fresh_clock().now().date())
    return sanitise(caught.value.message)


def failure_of(purl: str, env: CliEnvironment | None = None) -> ToolFailure:
    with pytest.raises(ToolFailure) as caught:
        run_package(purl, env or make_env(), _MustNotBeCalled(), fresh_clock())
    return caught.value


# ------------------------------------------------------------------- input errors, CLI text


@pytest.mark.parametrize(
    ("purl", "phrase"),
    [
        ("not a purl", "not a valid npm or PyPI package URL"),
        ("", "not a valid npm or PyPI package URL"),
        ("pkg:npm/request", "needs a version"),
        ("pkg:pypi/requests", "needs a version"),
        ("pkg:maven/org.example/thing@1.0.0", "not a valid npm or PyPI package URL"),
        ("pkg:cargo/serde@1.0.0", "not a valid npm or PyPI package URL"),
    ],
)
def test_invalid_versionless_and_unsupported_purls_give_the_cli_message(
    purl: str, phrase: str
) -> None:
    failure = failure_of(purl)
    assert failure.message == cli_message(purl)
    assert phrase in failure.message
    assert str(failure) == failure.message


def test_the_maven_message_is_the_one_the_cli_prints() -> None:
    maven = "pkg:maven/org.example/thing@1.0.0"
    assert failure_of(maven).message == f"--purl #1: not a valid npm or PyPI package URL: {maven}"


@pytest.mark.parametrize(
    "purl",
    ["--json=/tmp/graveyard-mcp-evil.json", "--syft=/bin/sh", "--help", "--version", "-h", "--all"],
)
def test_an_option_shaped_purl_is_a_usage_error_and_changes_nothing(
    purl: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    failure = failure_of(purl)
    assert failure.message == "argument --purl: expected one argument"
    assert list(tmp_path.iterdir()) == []


def test_control_and_bidi_characters_in_the_purl_do_not_reach_the_message() -> None:
    failure = failure_of("pkg:npm/a@1\x1b[31m\u202e\x00evil")
    assert "\x1b" not in failure.message
    assert "\u202e" not in failure.message
    assert "\x00" not in failure.message
    assert "\ufffd" in failure.message
    assert "\n" not in failure.message


def test_a_tool_failure_sanitises_its_own_message() -> None:
    assert ToolFailure("a\x1bb\u202ec").message == "a\ufffdb\ufffdc"


# --------------------------------------------------------------------- success, and its shape


def test_a_package_run_returns_the_cli_report_plus_truncated_false() -> None:
    seen = cassette_transport()
    doc = run_package(REQUEST_PURL, make_env(), seen.transport, fresh_clock())
    assert seen.log.unmatched == []
    clock = fresh_clock()
    opts = parse_args(["autopsy", "--purl", REQUEST_PURL, "--all"], today=clock.now().date())
    report = analyse(opts, make_env(), cassette_transport().transport, clock)
    expected = json.loads(json.dumps(report_to_dict(report)))
    assert doc == {**expected, "truncated": False}
    assert doc["packages"][0]["purl"] == REQUEST_PURL
    assert doc["packages"][0]["state"] == "Dead"


# --------------------------------------------------------------------------- internal errors


@pytest.mark.parametrize("exc", [RuntimeError, ValueError, KeyError, OSError])
def test_an_internal_error_gives_only_the_type_name(
    exc: type[Exception], monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*args: Any, **kwargs: Any) -> Any:
        raise exc(SECRET_TEXT)

    monkeypatch.setattr(tools, "analyse", explode)
    with pytest.raises(ToolFailure) as caught:
        run_package(REQUEST_PURL, make_env(), _MustNotBeCalled(), fresh_clock())
    assert caught.value.message == f"internal error: {exc.__name__}"
    assert "SECRET" not in str(caught.value) + repr(caught.value)
    assert "/home" not in str(caught.value) + repr(caught.value)
    assert caught.value.__cause__ is None


def test_an_internal_error_in_the_report_step_is_also_reduced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(*args: Any, **kwargs: Any) -> Any:
        raise ValueError(SECRET_TEXT)

    seen = cassette_transport()
    monkeypatch.setattr(tools, "report_to_dict", explode)
    with pytest.raises(ToolFailure) as caught:
        run_package(REQUEST_PURL, make_env(), seen.transport, fresh_clock())
    assert caught.value.message == "internal error: ValueError"


def test_a_cli_input_error_keeps_the_cli_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ``CliError`` (here: Syft not found) is the CLI's fixed template, not an internal error."""
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))
    with pytest.raises(ToolFailure) as caught:
        run_project(".", FIXTURES_ROOT, make_env(), _MustNotBeCalled(), fresh_clock())
    assert caught.value.message.startswith("Syft was not found on PATH")
    assert not caught.value.message.startswith("internal error")


# --------------------------------------------------------------------- run_project confinement


def test_a_path_outside_the_root_is_refused_before_anything_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = use_stub_syft(monkeypatch, tmp_path)
    outside = tmp_path / "outside-dir-4c1f"
    outside.mkdir()
    for text in (str(outside), "..", "missing"):
        with pytest.raises(ToolFailure) as caught:
            run_project(text, FIXTURES_ROOT / "anchors-project", make_env(), _MustNotBeCalled())
        assert caught.value.message == OUTSIDE_ROOT_MESSAGE
        assert "outside-dir-4c1f" not in caught.value.message
    assert stub.calls() == []  # Syft never ran


def test_a_file_path_and_an_escaping_symlink_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = use_stub_syft(monkeypatch, tmp_path)
    root = tmp_path / "root"
    root.mkdir()
    (root / "file.txt").write_text("x", encoding="utf-8")
    (root / "escape").symlink_to(ANCHORS_PROJECT, target_is_directory=True)
    for text in ("file.txt", "escape"):
        with pytest.raises(ToolFailure) as caught:
            run_project(text, root, make_env(), _MustNotBeCalled(), fresh_clock())
        assert caught.value.message == OUTSIDE_ROOT_MESSAGE
    assert stub.calls() == []


# ------------------------------------------------------------------------------- the token

Runner = Callable[[], str]


def _scenarios(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Runner]:
    """Every way a call can end, each returning all text a client could see."""
    use_stub_syft(monkeypatch, tmp_path)
    token_env = make_token_env()

    def success() -> str:
        seen = cassette_transport()
        doc = run_package(REQUEST_PURL, token_env, seen.transport, fresh_clock())
        assert seen.authorization_sent  # the token really was used for the GitHub request
        return json.dumps(doc)

    def failing(call: Callable[[], Any]) -> str:
        with pytest.raises(ToolFailure) as caught:
            call()
        return caught.value.message + repr(caught.value) + str(caught.value.args)

    def internal() -> str:
        def explode(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError(f"token={TOKEN}")

        with monkeypatch.context() as patch:
            patch.setattr(tools, "analyse", explode)
            return failing(
                lambda: run_package(REQUEST_PURL, token_env, _MustNotBeCalled(), fresh_clock())
            )

    def no_syft() -> str:
        with monkeypatch.context() as patch:
            patch.setenv("PATH", str(tmp_path))
            return failing(
                lambda: run_project(
                    ".", FIXTURES_ROOT, token_env, _MustNotBeCalled(), fresh_clock()
                )
            )

    return {
        "success": success,
        "invalid purl": lambda: failing(
            lambda: run_package("nope", token_env, _MustNotBeCalled(), fresh_clock())
        ),
        "versionless": lambda: failing(
            lambda: run_package("pkg:npm/request", token_env, _MustNotBeCalled(), fresh_clock())
        ),
        "maven": lambda: failing(
            lambda: run_package("pkg:maven/a/b@1", token_env, _MustNotBeCalled(), fresh_clock())
        ),
        "outside path": lambda: failing(
            lambda: run_project("..", FIXTURES_ROOT, token_env, _MustNotBeCalled(), fresh_clock())
        ),
        "internal": internal,
        "no syft": no_syft,
    }


def test_the_token_is_in_no_result_error_or_repr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    texts = {name: run() for name, run in _scenarios(tmp_path, monkeypatch).items()}
    assert set(texts) == {
        "success",
        "invalid purl",
        "versionless",
        "maven",
        "outside path",
        "internal",
        "no syft",
    }
    assert leaking(texts) == []
    env = make_token_env()
    assert TOKEN not in repr(env) + str(env) + repr(env.token) + str(env.token)
    assert isinstance(env.token, SecretToken)


def leaking(texts: dict[str, str]) -> list[str]:
    """The names of the scenarios whose text contains the token."""
    return [name for name, text in texts.items() if TOKEN in text]


def echoes_exception_text(message: str) -> bool:
    return "SECRET" in message


def test_the_leak_scan_flags_a_text_with_the_token() -> None:
    assert leaking({"ok": "fine", "bad": f"auth failed for {TOKEN}"}) == ["bad"]


def test_the_exception_text_check_flags_a_message_that_echoes_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(SECRET_TEXT)

    monkeypatch.setattr(tools, "analyse", explode)
    with pytest.raises(ToolFailure) as caught:
        run_package(REQUEST_PURL, make_env(), _MustNotBeCalled(), fresh_clock())
    assert not echoes_exception_text(caught.value.message)
    assert echoes_exception_text(f"internal error: {SECRET_TEXT}")
