"""``extract_payload`` (KPW-PAY-3): extraction rules and totality."""

from __future__ import annotations

import json

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.install.payload import (
    COMMAND_FIELD,
    CWD_FIELD,
    MAX_COMMAND_CHARS,
    MAX_CWD_CHARS,
    HookPayload,
    extract_payload,
)


def _payload(command: object = "npm i x", cwd: object = "/repo", **extra: object) -> str:
    body: dict[str, object] = {"tool_input": {COMMAND_FIELD: command}, CWD_FIELD: cwd}
    body.update(extra)
    return json.dumps(body)


def test_observed_names() -> None:
    text = '{"hook_event_name":"preToolUse","cwd":"/r","tool_name":"shell",'
    text += '"tool_input":{"command":"npm i x"}}'
    assert extract_payload(text) == HookPayload(command="npm i x", cwd="/r")


def test_built_from_constants() -> None:
    assert extract_payload(_payload()) == HookPayload(command="npm i x", cwd="/repo")


def test_tool_name_is_not_used() -> None:
    assert extract_payload(_payload(tool_name="anything")) is not None


@pytest.mark.parametrize(
    "text",
    [
        json.dumps({CWD_FIELD: "/r"}),
        json.dumps({"tool_input": "ls"}),
        json.dumps({"tool_input": ["ls"]}),
        json.dumps({"tool_input": None}),
        json.dumps({"tool_input": {}}),
        "[]",
        '[{"tool_input": {"command": "x"}}]',
        '"text"',
        "123",
        "null",
        "",
        "{",
        "not json",
    ],
)
def test_unusable_payloads(text: str) -> None:
    assert extract_payload(text) is None


@pytest.mark.parametrize(
    "command",
    [
        None,
        5,
        ["a"],
        {"a": 1},
        True,
        "",
    ],
)
def test_bad_command(command: object) -> None:
    assert extract_payload(_payload(command)) is None


def test_command_size_limit() -> None:
    assert extract_payload(_payload("a" * MAX_COMMAND_CHARS)) is not None
    assert extract_payload(_payload("a" * (MAX_COMMAND_CHARS + 1))) is None


@pytest.mark.parametrize("cwd", [5, None, ["x"], "a\x00b", "a" * (MAX_CWD_CHARS + 1)])
def test_bad_cwd_is_dropped(cwd: object) -> None:
    result = extract_payload(_payload(cwd=cwd))
    assert result == HookPayload(command="npm i x", cwd=None)


def test_cwd_limit_and_missing() -> None:
    long_ok = "a" * MAX_CWD_CHARS
    assert extract_payload(_payload(cwd=long_ok)) == HookPayload("npm i x", long_ok)
    text = json.dumps({"tool_input": {COMMAND_FIELD: "x"}})
    assert extract_payload(text) == HookPayload("x", None)


def _nest(levels: int) -> str:
    """An object whose own nesting is ``levels`` containers deep, holding a valid command."""
    inner: object = 1
    for _ in range(levels - 1):
        inner = [inner]
    return json.dumps({"tool_input": {COMMAND_FIELD: "x"}, "extra": inner})


def test_depth_limit() -> None:
    assert extract_payload(_nest(16)) is not None
    assert extract_payload(_nest(17)) is None


def test_very_deep_nesting_does_not_raise() -> None:
    assert extract_payload('{"a":' + "[" * 100_000 + "]" * 100_000 + "}") is None


def test_very_large_text() -> None:
    assert extract_payload(_payload("x", extra="y" * 2_000_000)) is None
    assert extract_payload("a" * 3_000_000) is None


def test_non_str_input() -> None:
    assert extract_payload(None) is None  # type: ignore[arg-type]


# --- totality -------------------------------------------------------------------

_JSON = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False) | st.text(),
    lambda kids: (
        st.lists(kids, max_size=4) | st.dictionaries(st.text(max_size=12), kids, max_size=4)
    ),
    max_leaves=30,
)


@pytest.mark.property
@given(st.text())
def test_extract_total_over_text(text: str) -> None:
    result = extract_payload(text)
    assert result is None or isinstance(result, HookPayload)


@pytest.mark.property
@given(_JSON)
def test_extract_total_over_json(value: object) -> None:
    result = extract_payload(json.dumps(value))
    assert result is None or (0 < len(result.command) <= MAX_COMMAND_CHARS)


@pytest.mark.property
@given(st.text(min_size=1, max_size=200), st.one_of(st.none(), st.text(max_size=50)))
def test_valid_envelope_round_trips(command: str, cwd: str | None) -> None:
    result = extract_payload(_payload(command, cwd))
    assert result is not None
    assert result.command == command
    assert result.cwd == (cwd if cwd is not None and "\x00" not in cwd else None)
