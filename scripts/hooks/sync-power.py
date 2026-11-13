#!/usr/bin/env python3
"""Install the Graveyard Power into this repository's .kiro/ folder (stdlib only).

Sources live in powers/graveyard/. Targets (design 9.3):

* skills check-before-adding-dependency and reading-a-verdict -> .kiro/skills/<name>/SKILL.md (byte copy)
* the dead-install-blocker hook template -> .kiro/hooks/dead-install-blocker.json
  (only hooks[0].action.command is replaced, with the in-repo form)
* server "graveyard" of mcp.json -> .kiro/settings/mcp.json (command and args replaced,
  autoApprove added; other servers and keys of an existing file are kept)

Usage:
    python3 scripts/hooks/sync-power.py           write the targets
    python3 scripts/hooks/sync-power.py --check   write nothing; exit 1 and list differing paths
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
POWER = REPO / "powers" / "graveyard"
KIRO = REPO / ".kiro"

SKILLS = ("check-before-adding-dependency", "reading-a-verdict")
HOOK_SOURCE = POWER / "skills" / "install-blocker-hook" / "references" / "dead-install-blocker.json"
HOOK_TARGET = KIRO / "hooks" / "dead-install-blocker.json"
MCP_SOURCE = POWER / "mcp.json"
MCP_TARGET = KIRO / "settings" / "mcp.json"
SERVER = "graveyard"

IN_REPO_HOOK_COMMAND = (
    "if [ -x backend/.venv/bin/graveyard ]; then "
    "backend/.venv/bin/graveyard check-install; s=$?; [ \"$s\" -eq 2 ] && exit 2; fi; exit 0"
)
IN_REPO_MCP_COMMAND = "uv"
IN_REPO_MCP_ARGS = ["run", "--project", "backend", "--extra", "mcp", "graveyard-mcp"]
AUTO_APPROVE = ["autopsy_package", "autopsy_project"]


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def expected_hook() -> str:
    hook = _load(HOOK_SOURCE)
    hook["hooks"][0]["action"]["command"] = IN_REPO_HOOK_COMMAND
    return _dump(hook)


def expected_mcp() -> str:
    """The in-repo MCP file: the existing content with the graveyard server set."""
    source_server = copy.deepcopy(_load(MCP_SOURCE)["mcpServers"][SERVER])
    source_server["command"] = IN_REPO_MCP_COMMAND
    source_server["args"] = list(IN_REPO_MCP_ARGS)
    source_server["autoApprove"] = list(AUTO_APPROVE)
    # GRAVEYARD_MCP_ROOT stays unset in the repository: the cwd default applies.
    source_server.get("env", {}).pop("GRAVEYARD_MCP_ROOT", None)
    if MCP_TARGET.is_file():
        existing = _load(MCP_TARGET)
        if not isinstance(existing, dict):
            raise ValueError(f"{MCP_TARGET} is not a JSON object")
    else:
        existing = {}
    servers = existing.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise ValueError(f"{MCP_TARGET}: mcpServers is not an object")
    servers[SERVER] = source_server
    return _dump(existing)


def expected_files() -> dict[Path, bytes]:
    files: dict[Path, bytes] = {}
    for name in SKILLS:
        files[KIRO / "skills" / name / "SKILL.md"] = (POWER / "skills" / name / "SKILL.md").read_bytes()
    files[HOOK_TARGET] = expected_hook().encode("utf-8")
    files[MCP_TARGET] = expected_mcp().encode("utf-8")
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="write nothing; exit 1 listing differing paths")
    args = parser.parse_args(argv)

    try:
        files = expected_files()
    except (OSError, ValueError, KeyError, IndexError) as exc:
        print(f"sync-power: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    differing = [p for p, content in files.items() if not p.is_file() or p.read_bytes() != content]
    if args.check:
        for path in differing:
            print(path.relative_to(REPO).as_posix())
        return 1 if differing else 0

    for path in differing:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(files[path])
        print(f"wrote {path.relative_to(REPO).as_posix()}")
    if not differing:
        print("already in sync")
    return 0


if __name__ == "__main__":
    sys.exit(main())
