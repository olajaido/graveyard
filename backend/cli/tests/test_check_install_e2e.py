"""End-to-end tests of ``graveyard check-install`` against the recorded cassette (T10.2).

Covers KPW-TEST-7 and KPW-TEST-8. Everything goes through ``app.run`` with
``subset_replay_transport`` (design §9.4), wrapped in ``version_agnostic_osv`` (KPW-TEST-8).

Why the wrapper: the cassette records OSV answers for the recorded versions only, and an
unpinned ``npm install express`` resolves to ``express@5.3.0`` (``dist-tags.latest``), which has
no recorded OSV query. The wrapper answers an OSV query for a recorded *package* at another
version with that package's recorded answer. The cassette is never edited.

Every run asserts ``log.unmatched == []``, except the no-network cases, which assert
``log.matched == [] and log.unmatched == []``.
"""

from __future__ import annotations

import asyncio
import io
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from cli.app import run
from cli.check_install import evaluate
from cli.hook import Checked, blocks
from cli.tests.support import (
    FakeClock,
    OsvAgnosticUse,
    ReplayLog,
    make_env,
    single_repo_github,
    subset_replay_transport,
    version_agnostic_osv,
)
from core.install import parse_install
from core.install.payload import COMMAND_FIELD, CWD_FIELD
from core.scoring.types import BaseState
from core.sources.secret import SecretToken
from core.sources.tests import recorded as rec

TOKEN = "e2e-check-install-token-77"
CLOCK = FakeClock(datetime(2026, 11, 10, 9, 0, tzinfo=UTC))
AS_OF = date(2026, 11, 3)
SIX_NOTE = "graveyard: six@1.17.0 unverified (no GitHub data), not gated\n"
FILE_NOTE = "requirements.txt: 3 lines not checked (unpinned, URL or path, nested -r)"


@dataclass(frozen=True)
class Result:
    code: int
    out: str
    err: str
    log: ReplayLog
    osv: OsvAgnosticUse


def _transport() -> tuple[httpx.MockTransport, ReplayLog, OsvAgnosticUse]:
    cassette = rec.cassette()
    inner, log = subset_replay_transport(cassette)
    wrapped, use = version_agnostic_osv(inner, cassette)
    return single_repo_github(wrapped, log, cassette), log, use


def check(
    command: str,
    *,
    token: bool = False,
    cwd: Path | None = None,
    spy: Callable[[httpx.MockTransport], httpx.MockTransport] | None = None,
    rejected: bool = False,
) -> Result:
    """Run ``check-install`` for ``command``; with ``cwd``, deliver it as a hook payload.

    ``spy`` replaces the transport (the token test wraps the replay one); ``rejected`` runs
    with a token that the environment loader dropped as invalid.
    """
    transport, log, use = _transport()
    if spy is not None:
        transport = spy(transport)
    out, err = io.StringIO(), io.StringIO()
    env = make_env(token=SecretToken(TOKEN) if token else None, token_rejected=rejected)
    argv = ["check-install", "--as-of", "2026-11-03"]
    stdin = None
    if cwd is None:
        argv.insert(1, command)
    else:
        # Shape observed in KP-S1 (docs/SPIKES.md): envelope plus the full tool_input.
        payload = {
            "session_id": "e2e-session-0001",
            "hook_event_name": "PreToolUse",
            CWD_FIELD: str(cwd),
            "tool_name": "execute_bash",
            "tool_input": {
                COMMAND_FIELD: command,
                "description": None,
                CWD_FIELD: None,
                "run_in_background": False,
                "timeout": None,
            },
        }

        def stdin() -> str | None:
            return json.dumps(payload)

    code = run(
        argv,
        env=env,
        out=out,
        err=err,
        stdin=stdin,
        transport=transport,
        clock=CLOCK,
    )
    return Result(code, out.getvalue(), err.getvalue(), log, use)


def assert_clean_log(result: Result) -> None:
    assert result.log.unmatched == []


# ------------------------------------------------------------------------- headline cases


def test_npm_install_request_blocks() -> None:
    r = check("npm install request")
    assert_clean_log(r)
    assert r.code == 2
    assert r.out == ""
    for fragment in ("npm request@2.88.2", "Dead", "Cursed", "declared dead"):
        assert fragment in r.err


def _outcomes(command: str, *, token: bool) -> tuple[list[object], OsvAgnosticUse, ReplayLog]:
    transport, log, use = _transport()
    env = make_env(token=SecretToken(TOKEN) if token else None)
    targets = list(parse_install(command).targets)
    outcomes = asyncio.run(evaluate(targets, env, transport, CLOCK, AS_OF, 10.0))
    return list(outcomes), use, log


def test_npm_install_express_with_token_is_silent_and_not_blocked() -> None:
    r = check("npm install express", token=True)
    assert_clean_log(r)
    assert (r.code, r.out, r.err) == (0, "", "")
    # KPW-TEST-8: the wrapper answered the express@5.3.0 OSV query exactly once
    assert r.osv.rewritten == [("express", "5.3.0", "4.17.1")]

    outcomes, use, log = _outcomes("npm install express", token=True)
    assert log.unmatched == [] and use.uses == 1
    (checked,) = outcomes
    assert isinstance(checked, Checked)
    assert checked.purl == "pkg:npm/express@5.3.0"
    assert not blocks(checked)
    assert checked.cursed is False
    # Observed once at implementation: express@5.3.0 is Alive, fix available, not Cursed.
    assert checked.state is BaseState.ALIVE


def test_pip_install_six_without_token_is_unverified() -> None:
    r = check("pip install six")
    assert_clean_log(r)
    assert (r.code, r.out, r.err) == (0, SIX_NOTE, "")


# ------------------------------------------------------------------------------- ranges


def test_range_request_blocks_on_declared_dead() -> None:
    r = check("npm install request@^2")
    assert_clean_log(r)
    assert r.code == 2 and r.out == ""
    assert "request@2.88.2" in r.err and "declared dead" in r.err
    assert "(range resolved to latest)" in r.err


def test_range_express_allows() -> None:
    r = check("npm install express@^5", token=True)
    assert_clean_log(r)
    assert (r.code, r.out, r.err) == (0, "", "")


def test_range_six_without_token_is_unverified() -> None:
    r = check('pip install "six<2"')
    assert_clean_log(r)
    assert r.code == 0 and r.err == ""
    # KPW-MAP-5 fragment (3) applies to a range that is Dead by score; the token-less
    # "unverified" fragment (4) is for non-range targets only.
    assert r.out == "graveyard: six: range not checked against 1.17.0 (Dead)\n"


def test_range_pycrypto_with_token() -> None:
    """pycrypto is the recorded Cursed, Dead-by-score package and the cassette answers it
    (latest 2.6.1), so this runs the real pipeline; no hand-built seam row is needed."""
    r = check('pip install "pycrypto<3"', token=True)
    assert_clean_log(r)
    assert r.code == 0 and r.err == ""
    assert r.out == "graveyard: pycrypto: range not checked against 2.6.1 (Dead · Cursed)\n"


# ------------------------------------------------------------- compound and wrapper forms


@pytest.mark.parametrize(
    ("command", "token", "code"),
    [
        ("cd web && npm install request", False, 2),
        ("yarn add request@2.88.2 -D", False, 2),
        ("sudo pip install six==1.17.0", False, 0),
        ("pnpm add -D express", True, 0),
    ],
)
def test_compound_and_wrapper_forms(command: str, token: bool, code: int) -> None:
    r = check(command, token=token)
    assert_clean_log(r)
    assert r.code == code
    if code == 2:
        assert r.out == "" and "request@2.88.2" in r.err
    elif "six" in command:
        assert (r.out, r.err) == (SIX_NOTE, "")
    else:
        assert (r.out, r.err) == ("", "")


HEADLINES = [
    ("npm install request", False),
    ("npm install express", True),
    ("pip install six", False),
]


@pytest.mark.parametrize(("command", "token"), HEADLINES)
def test_hook_payload_gives_the_same_results(command: str, token: bool, tmp_path: Path) -> None:
    """KPW-TEST-7: the hook payload matches the positional run and is deterministic."""
    positional = check(command, token=token)
    first = check(command, token=token, cwd=tmp_path)
    second = check(command, token=token, cwd=tmp_path)
    assert_clean_log(positional)
    assert_clean_log(first)
    assert_clean_log(second)
    assert (first.code, first.out, first.err) == (positional.code, positional.out, positional.err)
    assert (second.code, second.out, second.err) == (first.code, first.out, first.err)
    # pin the headline outcomes so "identical" cannot hold vacuously
    expected = {
        "npm install request": (2, ""),
        "npm install express": (0, ""),
        "pip install six": (0, SIX_NOTE),
    }[command]
    assert (first.code, first.out) == expected
    assert (first.err == "") is (first.code == 0)


# --------------------------------------------------------------------- requirements files


def test_requirements_file_without_token(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text(
        "six==1.17.0\n-r other.txt\ngit+https://example.invalid/x.git\nrequests\n# comment\n",
        encoding="utf-8",
    )
    r = check("pip install -r requirements.txt", cwd=tmp_path)
    assert_clean_log(r)
    assert r.code == 0 and r.err == ""
    assert r.out.count("\n") == 1
    assert "six@1.17.0 unverified (no GitHub data), not gated" in r.out
    assert FILE_NOTE in r.out


def test_requirements_file_clean_with_token(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("six==1.17.0\n", encoding="utf-8")
    r = check("pip install -r requirements.txt", token=True, cwd=tmp_path)
    assert_clean_log(r)
    # with a token six is Resting (GitHub data present), so the allow is silent
    assert (r.code, r.out, r.err) == (0, "", "")


def test_requirements_file_outside_the_base_is_not_read(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    (tmp_path / "outside.txt").write_text("six==1.17.0\n", encoding="utf-8")
    r = check("pip install -r ../outside.txt", cwd=work)
    assert r.code == 0 and r.err == ""
    assert "not read (outside)" in r.out
    assert "six" not in r.out
    assert r.log.matched == [] and r.log.unmatched == []


# ----------------------------------------------------------------------------- no network


@pytest.mark.parametrize(
    "command",
    ["npm install", "npm install ./local", "npm install git+https://example.invalid/x.git", "ls"],
)
def test_non_install_and_unsupported_forms_make_no_request(command: str) -> None:
    r = check(command)
    assert (r.code, r.out, r.err) == (0, "", "")
    assert r.log.matched == [] and r.log.unmatched == []


# ------------------------------------------------------------------------------ token (T10.4)


@dataclass
class Spy:
    """What the wrapped transport saw: where the token travelled."""

    authorized: list[tuple[str, str]]  # (host, path) of requests carrying the token
    leaks: list[str]  # anywhere else in a request (url, other headers, body)


def _spy(*, github_status: int | None = None) -> tuple[Spy, Callable[..., httpx.MockTransport]]:
    seen = Spy([], [])

    def wrap(inner: httpx.MockTransport) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            for name, value in request.headers.items():
                if TOKEN in value:
                    if name.lower() == "authorization" and request.url.host == "api.github.com":
                        seen.authorized.append((request.url.host, request.url.path))
                    else:
                        seen.leaks.append(f"header {name} to {request.url.host}")
            if TOKEN in str(request.url):
                seen.leaks.append("url")
            if TOKEN.encode() in request.content:
                seen.leaks.append("body")
            if github_status is not None and request.url.host == "api.github.com":
                return httpx.Response(github_status, json={"message": "Bad credentials"})
            answer = inner.handler(request)
            assert isinstance(answer, httpx.Response)
            return answer

        return httpx.MockTransport(handler)

    return seen, wrap


def _assert_no_token(r: Result, spy: Spy) -> None:
    assert TOKEN not in r.out
    assert TOKEN not in r.err
    assert spy.leaks == []
    assert set(spy.authorized) <= {("api.github.com", "/graphql")}


def test_token_is_never_shown_when_blocking() -> None:
    seen, wrap = _spy()
    r = check("npm install request", token=True, spy=wrap)
    assert r.code == 2
    _assert_no_token(r, seen)
    assert seen.authorized  # the token was used, only as the Authorization header to GitHub


def test_token_is_never_shown_when_allowing_with_a_note() -> None:
    seen, wrap = _spy()
    r = check('pip install "pycrypto<3"', token=True, spy=wrap)
    assert r.code == 0 and "range not checked" in r.out
    _assert_no_token(r, seen)


def test_token_is_never_shown_on_a_silent_allow() -> None:
    seen, wrap = _spy()
    r = check("npm install express", token=True, spy=wrap)
    assert (r.code, r.out, r.err) == (0, "", "")
    _assert_no_token(r, seen)


def test_token_is_never_shown_for_a_requirements_file(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("six==1.17.0\nrequests\n", encoding="utf-8")
    seen, wrap = _spy()
    r = check("pip install -r requirements.txt", token=True, cwd=tmp_path, spy=wrap)
    assert r.code == 0
    assert "not checked" in r.out
    _assert_no_token(r, seen)


@pytest.mark.parametrize("command", ["npm install request", "npm install express"])
def test_token_is_never_shown_in_a_hook_payload_run(command: str, tmp_path: Path) -> None:
    seen, wrap = _spy()
    r = check(command, token=True, cwd=tmp_path, spy=wrap)
    assert r.code in (0, 2)
    _assert_no_token(r, seen)


@pytest.mark.parametrize("status", [401, 403, 500])
def test_token_is_never_shown_when_github_refuses_it(status: int) -> None:
    seen, wrap = _spy(github_status=status)
    r = check("npm install request", token=True, spy=wrap)
    assert r.code in (0, 2)
    _assert_no_token(r, seen)
    assert seen.authorized  # the refused request did carry it, and nothing echoed it back


def test_token_is_never_shown_when_the_token_was_rejected_as_invalid() -> None:
    seen, wrap = _spy()
    r = check("pip install six", rejected=True, spy=wrap)
    assert r.code == 0
    _assert_no_token(r, seen)
    assert seen.authorized == []
