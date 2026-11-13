"""Shared locations and loaders for the Power tests (paths from ``__file__``, not the cwd)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
POWER = REPO / "powers" / "graveyard"
KIRO = REPO / ".kiro"
SKILL_NAMES = ("check-before-adding-dependency", "reading-a-verdict", "install-blocker-hook")
HOOK_TEMPLATE = (
    POWER / "skills" / "install-blocker-hook" / "references" / "dead-install-blocker.json"
)
HOOK_IN_REPO = KIRO / "hooks" / "dead-install-blocker.json"
SYNC_SCRIPT = REPO / "scripts" / "hooks" / "sync-power.py"

# KPW-PWR-8: the commit pin is a placeholder until the release commit exists. The release task
# flips this to True, which turns the placeholder into a test failure.
RELEASE_PIN_REQUIRED = False
PLACEHOLDER = "<COMMIT_SHA>"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def hook_command(path: Path) -> str:
    data = load_json(path)
    command = data["hooks"][0]["action"]["command"]
    assert isinstance(command, str)
    return command
