"""``check-install`` never raises, end to end (T9.5; KPW-TEST-6, KPW-CMD-4).

Arbitrary payloads and argv run through ``run`` with a transport that fails every request.
Fault injection makes each internal step raise ``RuntimeError("secret-text")``; the text of the
exception must never reach any output. Profiles come from ``HYPOTHESIS_PROFILE`` (``conftest``).
"""

from __future__ import annotations

import io
import json
import sys
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import cli.__main__ as entry
import cli.check_install as check_install
from cli.check_install import run
from cli.tests.support import make_env, subset_replay_transport
from cli.tests.test_e2e_project import CLOCK_START
from core.install.payload import COMMAND_FIELD, CWD_FIELD
from core.sources.tests import recorded as rec
from sources.tests.clock import FakeClock

SECRET = "secret-text"
INTERNAL_ERROR = "graveyard check-install: internal error (RuntimeError); nothing was checked\n"
INTERNAL_ERROR_KI = (
    "graveyard check-install: internal error (KeyboardInterrupt); nothing was checked\n"
)

# ------------------------------------------------------------------------------ strategies

_PREFIXES = ["npm install ", "pip install ", "pip install -r ", "yarn add ", "uv pip install "]
_command = st.one_of(
    st.text(),
    st.builds(lambda p, t: p + t, st.sampled_from(_PREFIXES), st.text(max_size=200)),
)
_json_scalar = st.one_of(
    st.none(), st.booleans(), st.integers(), st.floats(allow_nan=False), st.text()
)
_json_value = st.recursive(
    _json_scalar,
    lambda inner: st.one_of(
        st.lists(inner, max_size=4), st.dictionaries(st.text(), inner, max_size=4)
    ),
    max_leaves=12,
)


def _envelope(command: str, cwd: str | None) -> str:
    envelope: dict[str, Any] = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {COMMAND_FIELD: command},
    }
    if cwd is not None:
        envelope[CWD_FIELD] = cwd
    return json.dumps(envelope)


_payload = st.one_of(
    st.text(),
    st.binary().map(lambda b: b.decode("utf-8", "replace")),
    _json_value.map(json.dumps),
    st.builds(_envelope, _command, st.one_of(st.none(), st.text())),
)

_ARGV_BLOCKED = {"--help", "-h", "--version"}  # these print several lines by design
_argv = st.lists(
    st.one_of(
        st.sampled_from(["--budget", "--as-of", "--", "-", "0.5", "2026-11-03", "npm install x"]),
        _command,
        st.text(),
    ),
    max_size=6,
).filter(lambda tokens: not _ARGV_BLOCKED.intersection(tokens))

# ------------------------------------------------------------------------------- helpers


def _failing_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    return httpx.MockTransport(handler)


def _go(
    argv: list[str],
    *,
    stdin: Callable[[], str | None] | None = None,
    transport: httpx.MockTransport | None = None,
) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = run(
        argv,
        env=make_env(),
        out=out,
        err=err,
        stdin=stdin,
        transport=transport if transport is not None else _failing_transport(),
        clock=FakeClock(CLOCK_START),
    )
    return code, out.getvalue(), err.getvalue()


def _assert_quiet_contract(code: int, out: str, err: str) -> None:
    assert code in (0, 2)
    if code == 2:
        assert err != ""
    else:
        assert err == ""
    assert out == "" or (out.endswith("\n") and "\n" not in out[:-1] and len(out) - 1 <= 200)


# ------------------------------------------------------------------------ property tests


@pytest.mark.property
@settings(deadline=None)
@given(payload=_payload)
def test_arbitrary_payloads_never_raise(payload: str) -> None:
    code, out, err = _go([], stdin=lambda: payload)
    _assert_quiet_contract(code, out, err)
    assert code == 0  # the transport fails every request, so nothing can block


@pytest.mark.property
@settings(deadline=None)
@given(argv=_argv)
def test_arbitrary_argv_never_raises(argv: list[str]) -> None:
    code, out, err = _go(argv)
    _assert_quiet_contract(code, out, err)


# ------------------------------------------------------------------- fault injection


def _boom(*_args: object, **_kwargs: object) -> Any:
    raise RuntimeError(SECRET)


class _BrokenClock:
    def now(self) -> Any:
        raise RuntimeError(SECRET)


_PIN_COMMAND = "npm install request@2.88.2"
_FILE_COMMAND = "pip install -r requirements.txt six==1.17.0"


@pytest.mark.parametrize(
    ("target", "command"),
    [
        ("parse_install", _PIN_COMMAND),
        ("load_requirements", _FILE_COMMAND),
        ("evaluate", _PIN_COMMAND),
        ("rank", _PIN_COMMAND),
        ("decide", _PIN_COMMAND),
        ("clock", _PIN_COMMAND),
    ],
)
def test_internal_faults_exit_0_with_the_note_and_no_secret(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, target: str, command: str
) -> None:
    transport, _ = subset_replay_transport(rec.cassette())
    out, err = io.StringIO(), io.StringIO()
    payload = _envelope(command, str(tmp_path))
    clock: Any = FakeClock(CLOCK_START)
    if target == "clock":
        clock = _BrokenClock()
    else:
        monkeypatch.setattr(check_install, target, _boom)
    code = run(
        [],
        env=make_env(),
        out=out,
        err=err,
        stdin=lambda: payload,
        transport=transport,
        clock=clock,
    )
    assert code == 0
    assert out.getvalue() == INTERNAL_ERROR
    assert err.getvalue() == ""
    assert SECRET not in out.getvalue() + err.getvalue()


# --------------------------------------------------------------------- entry point guard


def test_keyboard_interrupt_through_the_entry_point_exits_0(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdin = io.TextIOWrapper(io.BytesIO(_envelope(_PIN_COMMAND, None).encode()))
    stdout, stderr = io.StringIO(), io.StringIO()
    monkeypatch.setattr(sys, "argv", ["graveyard", "check-install"])
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    def interrupt(*_args: object, **_kwargs: object) -> Any:
        raise KeyboardInterrupt

    monkeypatch.setattr(check_install, "parse_install", interrupt)
    with pytest.raises(SystemExit) as exited:
        entry.main()
    assert exited.value.code == 0
    assert stdout.getvalue() == INTERNAL_ERROR_KI
    assert stderr.getvalue() == ""
