"""Static guard for ``.kiro/agents/coroner.json`` (EV-AGT-8).

One checker, ``check_agent``, returns one message per violation. The real file
must give ``[]``; every bad sample must give a non-empty list, so the guard
cannot pass vacuously.
"""

from __future__ import annotations

import copy
import json
import re
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
# Permissions page: web patterns are "*"-only globs. An allow entry is either scheme + host
# + "/*" (URL form) or the exact bare host with no scheme and no wildcard (Kiro matched the
# bare form in a live probe, so the agent file keeps both). Either way a longer host
# (github.com.evil.example), userinfo or a port cannot match. Hosts not listed fall through
# to the default, which prompts.
EVIDENCE_HOSTS = [
    "registry.npmjs.org",
    "www.npmjs.com",
    "pypi.org",
    "github.com",
    "raw.githubusercontent.com",
    "endoflife.date",
]
EXPECTED_FETCH_URL_MATCH = [f"https://{h}/*" for h in EVIDENCE_HOSTS]
ALLOWED_FETCH_PATTERNS = {*EXPECTED_FETCH_URL_MATCH, *EVIDENCE_HOSTS}
# Deny rule for private and internal targets, in https and http forms (deny beats allow).
# "*" is the only wildcard and it also spans "/", so the two ".internal" and ".local"
# patterns are written as host-end, host-then-path and host-then-port forms.
_DENY_TARGETS = [
    "localhost*",
    "127.*",
    "0.0.0.0*",
    "169.254.*",
    "10.*",
    *[f"172.{n}.*" for n in range(16, 32)],
    "192.168.*",
    "[::1]*",
    "[fc*",
    "[fd*",
    "[fe8*",
    "[fe9*",
    "[fea*",
    "[feb*",
    "*.internal",
    "*.internal/*",
    "*.internal:*",
    "*.local",
    "*.local/*",
    "*.local:*",
]
# Bare-host forms of the same targets (no scheme), kept beside the URL forms.
_DENY_BARE = [
    "localhost",
    "localhost:*",
    "*.localhost",
    "*.localhost:*",
    "127.*",
    "0.0.0.0",
    "0.0.0.0:*",
    "10.*",
    "169.254.*",
    "192.168.*",
    *[f"172.{n}.*" for n in range(16, 32)],
    "*.internal",
    "*.internal:*",
    "*.local",
    "*.local:*",
    "::1",
    "[::1]",
    "[::1]:*",
    "fc*:*",
    "fd*:*",
    "fe8*:*",
    "fe9*:*",
    "fea*:*",
    "feb*:*",
    "[fc*",
    "[fd*",
    "[fe8*",
    "[fe9*",
    "[fea*",
    "[feb*",
]
EXPECTED_FETCH_DENY_MATCH = [
    *[f"{scheme}://{t}" for scheme in ("https", "http") for t in _DENY_TARGETS],
    *_DENY_BARE,
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
        patterns: list[Any] = fetches[0].get("match") or []
        if len(set(map(str, patterns))) != len(patterns):
            out.append("web_fetch allow match must have no duplicates")
        for pattern in patterns:
            if pattern not in ALLOWED_FETCH_PATTERNS:
                out.append(
                    f"web_fetch allow pattern {pattern!r} must be 'https://<host>/*' or an "
                    f"exact bare host (no scheme, no wildcard), host one of {EVIDENCE_HOSTS}"
                )
        for url_form in EXPECTED_FETCH_URL_MATCH:
            if url_form not in patterns:
                out.append(f"web_fetch allow match must include {url_form!r}")
        if "exclude" in fetches[0]:
            out.append("web_fetch allow must have no exclude (the host list is the scope)")
    fetch_denies = _rules_for(doc, "web_fetch", "deny")
    if len(fetch_denies) != 1:
        out.append(f"expected exactly one web_fetch deny rule, got {len(fetch_denies)}")
    elif fetch_denies[0].get("match") != EXPECTED_FETCH_DENY_MATCH or "exclude" in fetch_denies[0]:
        out.append("web_fetch deny must match exactly the private and internal targets, no exclude")
    if _rules_for(doc, "web_fetch", "ask"):
        out.append("unexpected web_fetch ask rule")

    total = len(doc.get("permissions", {}).get("rules", []))
    if total != 11:
        out.append(f"expected exactly 11 rules, got {total}")

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


@pytest.mark.parametrize("index", range(11))
def test_removing_any_rule_fails(index: int) -> None:
    doc = copy.deepcopy(_load())
    rules = doc["permissions"]["rules"]
    assert len(rules) == 11
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


@pytest.mark.parametrize(
    "mutate",
    [
        lambda m: m.append("https://*"),
        lambda m: m.append("https://evil.example/*"),
        lambda m: m.__setitem__(3, "https://github.com*"),
        lambda m: m.__setitem__(2, "https://*.org/*"),
        lambda m: m.pop(0),
        lambda m: m.append("github.com*"),
        lambda m: m.append("*.github.com"),
        lambda m: m.append("*"),
        lambda m: m.append("evil.example"),
        lambda m: m.append("https://github.com"),
        lambda m: m.append("pypi.org"),
    ],
)
def test_fetch_host_list_change_fails(mutate: Any) -> None:
    doc = copy.deepcopy(_load())
    (rule,) = _rules_for(doc, "web_fetch", "allow")
    mutate(rule["match"])
    assert check_agent(doc) != []


def test_bare_host_allow_entries_are_optional_and_exact() -> None:
    doc = copy.deepcopy(_load())
    (rule,) = _rules_for(doc, "web_fetch", "allow")
    rule["match"] = list(EXPECTED_FETCH_URL_MATCH)
    assert check_agent(doc) == []
    rule["match"] = [*EXPECTED_FETCH_URL_MATCH, "github.com"]
    assert check_agent(doc) == []


@pytest.mark.parametrize("bad", ["github.com*", "*.github.com", "git*hub.com", "*github.com"])
def test_wildcard_or_prefix_bare_allow_rejected(bad: str) -> None:
    doc = copy.deepcopy(_load())
    (rule,) = _rules_for(doc, "web_fetch", "allow")
    rule["match"].append(bad)
    assert check_agent(doc) != []


def _glob(pattern: str, text: str) -> bool:
    """Web-pattern semantics from the permissions page: "*" matches any characters."""
    return re.fullmatch(".*".join(re.escape(p) for p in pattern.split("*")), text) is not None


ALLOWED_SAMPLES = [
    "https://registry.npmjs.org/ms",
    "https://www.npmjs.com/package/ms",
    "https://pypi.org/pypi/requests/json",
    "https://github.com/org/repo/blob/main/README.md",
    "https://raw.githubusercontent.com/org/repo/main/README.md",
    "https://endoflife.date/python",
]
DENIED_SAMPLES = [
    f"{scheme}://{host}{tail}"
    for scheme in ("https", "http")
    for host in (
        "localhost",
        "127.0.0.1",
        "127.255.255.254",
        "0.0.0.0",
        "169.254.169.254",
        "10.1.2.3",
        "172.16.0.1",
        "172.31.255.255",
        "192.168.1.1",
        "[::1]",
        "[fc00::1]",
        "[fd12::1]",
        "[fe80::1]",
        "[febf::1]",
        "db.internal",
        "printer.local",
    )
    for tail in ("", "/", "/x", ":8080/x")
]


def test_deny_matches_private_targets_and_spares_allowed_hosts() -> None:
    (deny,) = _rules_for(_load(), "web_fetch", "deny")
    (allow,) = _rules_for(_load(), "web_fetch", "allow")
    for url in DENIED_SAMPLES:
        assert any(_glob(p, url) for p in deny["match"]), url
    for url in ALLOWED_SAMPLES:
        assert not any(_glob(p, url) for p in deny["match"]), url
        assert any(_glob(p, url) for p in allow["match"]), url


@pytest.mark.parametrize(
    "mutate",
    [
        lambda m: m.append("https://*"),
        lambda m: m.append("https://github.com/*"),
        lambda m: m.pop(),
        lambda m: m.remove("http://169.254.*"),
        lambda m: m.remove("https://*.local:*"),
    ],
)
def test_fetch_deny_change_fails(mutate: Any) -> None:
    doc = copy.deepcopy(_load())
    (rule,) = _rules_for(doc, "web_fetch", "deny")
    mutate(rule["match"])
    assert check_agent(doc) != []


def test_fetch_deny_with_exclude_or_second_deny_fails() -> None:
    doc = copy.deepcopy(_load())
    (rule,) = _rules_for(doc, "web_fetch", "deny")
    rule["exclude"] = ["https://10.*"]
    assert check_agent(doc) != []
    doc = copy.deepcopy(_load())
    doc["permissions"]["rules"].append({"capability": "web_fetch", "effect": "deny"})
    assert check_agent(doc) != []


def test_fetch_exclude_or_ask_rule_fails() -> None:
    doc = copy.deepcopy(_load())
    (rule,) = _rules_for(doc, "web_fetch", "allow")
    rule["exclude"] = ["https://10.*"]
    assert check_agent(doc) != []
    doc = copy.deepcopy(_load())
    doc["permissions"]["rules"].append({"capability": "web_fetch", "effect": "ask"})
    assert check_agent(doc) != []


def test_fetch_patterns_are_host_anchored() -> None:
    (rule,) = _rules_for(_load(), "web_fetch", "allow")
    for pattern in rule["match"]:
        if pattern.startswith("https://"):
            assert pattern.endswith("/*")
            assert pattern.count("*") == 1
        else:
            assert pattern in EVIDENCE_HOSTS
            assert "*" not in pattern
            assert "://" not in pattern
