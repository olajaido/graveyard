"""Static guard for ``.kiro/agents/coroner.json`` (EV-AGT-8).

One checker, ``check_agent``, returns one message per violation. The real file
must give ``[]``; every bad sample must give a non-empty list, so the guard
cannot pass vacuously.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
AGENT_PATH = REPO_ROOT / ".kiro" / "agents" / "coroner.json"

EXPECTED_TOOLS = [
    "read_file",
    "list_directory",
    "file_search",
    "grep_search",
    "fs_append",
    "web_fetch",
]
EXPECTED_READ_EXCLUDE = [
    "eval/LABELLING.md",
    "eval/labelled_packages.csv",
    "eval/staging/coroner_rows.csv",
]
EXPECTED_WRITE_EXCLUDE = ["eval/staging/coroner_rows.csv"]
EXPECTED_WRITE_ALLOW = ["eval/staging/coroner_rows.csv"]
EXPECTED_NO_MATCH_DENIES = ["shell", "mcp", "power", "skill", "subagent", "web_search"]
EXPECTED_FETCH_MATCH = ["https://*"]
EXPECTED_FETCH_EXCLUDE = [
    "https://localhost*",
    "https://127.*",
    "https://[::1]*",
    "https://169.254.*",
    "https://10.*",
    "https://192.168.*",
    "https://172.16.*",
    "https://172.17.*",
    "https://172.18.*",
    "https://172.19.*",
    "https://172.20.*",
    "https://172.21.*",
    "https://172.22.*",
    "https://172.23.*",
    "https://172.24.*",
    "https://172.25.*",
    "https://172.26.*",
    "https://172.27.*",
    "https://172.28.*",
    "https://172.29.*",
    "https://172.30.*",
    "https://172.31.*",
]
EXPECTED_RESOURCES = ["file://eval/LABELLING.md"]


def _rules_for(doc: dict[str, Any], capability: str, effect: str) -> list[dict[str, Any]]:
    rules = doc.get("permissions", {}).get("rules", [])
    return [r for r in rules if r.get("capability") == capability and r.get("effect") == effect]


def check_agent(doc: dict[str, Any], repo_root: Path = REPO_ROOT) -> list[str]:
    """Return one message per violation of EV-AGT-1 to EV-AGT-5."""
    out: list[str] = []

    if doc.get("name") != "coroner":
        out.append("name must be 'coroner'")
    if doc.get("tools") != EXPECTED_TOOLS:
        out.append(f"tools must be exactly {EXPECTED_TOOLS}, got {doc.get('tools')!r}")
    if doc.get("includeMcpJson") is not False:
        out.append("includeMcpJson must be false")
    if doc.get("includePowers") is not False:
        out.append("includePowers must be false")
    if doc.get("mcpServers") != {}:
        out.append("mcpServers must be {}")
    if doc.get("resources") != EXPECTED_RESOURCES:
        out.append(f"resources must be {EXPECTED_RESOURCES}")

    for cap in EXPECTED_NO_MATCH_DENIES:
        denies = _rules_for(doc, cap, "deny")
        if len(denies) != 1:
            out.append(f"expected exactly one {cap} deny rule, got {len(denies)}")
        elif "match" in denies[0] or "exclude" in denies[0]:
            out.append(f"{cap} deny rule must have no match or exclude")

    reads = _rules_for(doc, "fs_read", "deny")
    if len(reads) != 1:
        out.append(f"expected exactly one fs_read deny rule, got {len(reads)}")
    else:
        if reads[0].get("match") != ["**"]:
            out.append("fs_read deny match must be ['**']")
        if reads[0].get("exclude") != EXPECTED_READ_EXCLUDE:
            out.append(f"fs_read deny exclude must be {EXPECTED_READ_EXCLUDE}")

    writes = _rules_for(doc, "fs_write", "deny")
    if len(writes) != 1:
        out.append(f"expected exactly one fs_write deny rule, got {len(writes)}")
    else:
        if writes[0].get("match") != ["**"]:
            out.append("fs_write deny match must be ['**']")
        if writes[0].get("exclude") != EXPECTED_WRITE_EXCLUDE:
            out.append(f"fs_write deny exclude must be {EXPECTED_WRITE_EXCLUDE}")

    allows = _rules_for(doc, "fs_write", "allow")
    if len(allows) != 1:
        out.append(f"expected exactly one fs_write allow rule, got {len(allows)}")
    elif allows[0].get("match") != EXPECTED_WRITE_ALLOW or "exclude" in allows[0]:
        out.append(f"fs_write allow must match only {EXPECTED_WRITE_ALLOW}")

    fetches = _rules_for(doc, "web_fetch", "allow")
    if len(fetches) != 1:
        out.append(f"expected exactly one web_fetch allow rule, got {len(fetches)}")
    else:
        if fetches[0].get("match") != EXPECTED_FETCH_MATCH:
            out.append(f"web_fetch allow match must be {EXPECTED_FETCH_MATCH}")
        if fetches[0].get("exclude") != EXPECTED_FETCH_EXCLUDE:
            out.append("web_fetch allow exclude list differs from the expected 22 entries")
    if _rules_for(doc, "web_fetch", "deny"):
        out.append("unexpected web_fetch deny rule")

    total = len(doc.get("permissions", {}).get("rules", []))
    if total != 10:
        out.append(f"expected exactly 10 rules, got {total}")

    entries: list[Any] = [
        *doc.get("tools", []),
        *doc.get("mcpServers", {}),
        *doc.get("resources", []),
    ]
    for entry in entries:
        if "graveyard" in str(entry).lower():
            out.append(f"'graveyard' must not appear in tool/MCP/resource entry {entry!r}")

    named: set[str] = set()
    for rule in doc.get("permissions", {}).get("rules", []):
        if rule.get("capability") in ("fs_read", "fs_write"):
            named.update(p for p in rule.get("exclude", []))
            named.update(p for p in rule.get("match", []) if "*" not in p)
    for rel in sorted(named):
        if not (repo_root / rel).is_file():
            out.append(f"file named in the rules does not exist: {rel}")

    return out


def _load() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(AGENT_PATH.read_text(encoding="utf-8"))
    return loaded


def test_real_file_passes_checker() -> None:
    assert check_agent(_load()) == []


@pytest.mark.parametrize("index", range(10))
def test_removing_any_rule_fails(index: int) -> None:
    doc = copy.deepcopy(_load())
    rules = doc["permissions"]["rules"]
    assert len(rules) == 10
    del rules[index]
    assert check_agent(doc) != []


@pytest.mark.parametrize("extra", ["execute_bash", "@graveyard", "fs_write"])
def test_extra_tool_fails(extra: str) -> None:
    doc = copy.deepcopy(_load())
    doc["tools"].append(extra)
    assert check_agent(doc) != []


def test_include_mcp_json_true_fails() -> None:
    doc = copy.deepcopy(_load())
    doc["includeMcpJson"] = True
    assert check_agent(doc) != []


def test_graveyard_in_resource_or_mcp_fails() -> None:
    doc = copy.deepcopy(_load())
    doc["mcpServers"] = {"Graveyard": {}}
    assert any("graveyard" in m.lower() for m in check_agent(doc))


def test_missing_named_file_fails(tmp_path: Path) -> None:
    assert check_agent(_load(), repo_root=tmp_path) != []
