"""Extract the shell command from a Pre Tool Use hook payload (design 5.1).

Pure and total: ``extract_payload`` never raises. Field names were measured in
spike KP-S1 (``docs/SPIKES.md``, Kiro 1.4.86).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Final

COMMAND_FIELD: Final = "command"  # tool_input.command, measured in KP-S1
CWD_FIELD: Final = "cwd"  # envelope cwd (tool_input.cwd is ignored), measured in KP-S1

MAX_PAYLOAD_CHARS: Final = 1_048_576
MAX_COMMAND_CHARS: Final = 65_536
MAX_CWD_CHARS: Final = 4_096
MAX_DEPTH: Final = 16

_TOOL_INPUT: Final = "tool_input"


@dataclass(frozen=True)
class HookPayload:
    """What the hook needs from the payload."""

    command: str
    cwd: str | None  # kept only if a str of at most MAX_CWD_CHARS without NUL


def _too_deep(value: object) -> bool:
    """True when ``value`` nests containers deeper than ``MAX_DEPTH`` (iterative)."""
    stack: list[tuple[object, int]] = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        if isinstance(item, dict):
            children: list[object] = list(item.values())
        elif isinstance(item, list):
            children = list(item)
        else:
            continue
        if depth > MAX_DEPTH:
            return True
        stack.extend((child, depth + 1) for child in children)
    return False


def extract_payload(text: str) -> HookPayload | None:
    """Return the command and cwd from a hook payload, or ``None`` if unusable."""
    if not isinstance(text, str) or len(text) > MAX_PAYLOAD_CHARS:
        return None
    try:
        value: object = json.loads(text)
    except (ValueError, RecursionError):
        return None
    if not isinstance(value, dict) or _too_deep(value):
        return None
    tool_input = value.get(_TOOL_INPUT)
    if not isinstance(tool_input, dict):
        return None
    command = tool_input.get(COMMAND_FIELD)
    if not isinstance(command, str) or not 0 < len(command) <= MAX_COMMAND_CHARS:
        return None
    cwd = value.get(CWD_FIELD)
    if not isinstance(cwd, str) or len(cwd) > MAX_CWD_CHARS or "\x00" in cwd:
        cwd = None
    return HookPayload(command=command, cwd=cwd)
