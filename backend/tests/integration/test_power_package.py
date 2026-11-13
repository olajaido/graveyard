"""Power package tests (KPW-TEST-13, KPW-PWR-1..8, KPW-INST-5 schema half).

Paths come from ``__file__``; nothing here touches the network.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from tests.integration.power_files import (
    HOOK_IN_REPO,
    HOOK_TEMPLATE,
    PLACEHOLDER,
    POWER,
    RELEASE_PIN_REQUIRED,
    SKILL_NAMES,
    load_json,
)

REQUIRED_KEYWORDS = {
    "dependency", "package", "install", "npm", "pip", "library", "deprecated", "abandoned",
    "pnpm", "yarn", "uv", "poetry", "unmaintained",
}  # fmt: skip
ALLOWED_ENV = {"GITHUB_TOKEN", "GRAVEYARD_CONTACT", "GRAVEYARD_MCP_ROOT"}
SHA_SOURCE = re.compile(
    r"@ git\+https://github\.com/[\w.-]+/[\w.-]+\.git@([0-9a-f]{40})#subdirectory=backend$"
)
PLACEHOLDER_SOURCE = re.compile(
    r"@ git\+https://github\.com/[\w.-]+/[\w.-]+\.git@<COMMIT_SHA>#subdirectory=backend$"
)
TOKEN_LIKE = re.compile(
    r"(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}"
    r"|xox[abprs]-[A-Za-z0-9-]{10,}|sk-[A-Za-z0-9]{20,}|[A-Za-z0-9+/_-]{40,}={0,2}(?<!\w)(?=$))"
)
REFERENCE = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*\}$")
SKILL_MAX_BYTES = 8000
DESCRIPTION_MAX = 1024


# --- reusable checkers (each has a bad-sample test below) --------------------------------------


def pin_problem(source: str) -> str | None:
    """None when the ``--from`` requirement is commit-pinned (or the allowed placeholder)."""
    if SHA_SOURCE.search(source):
        return None
    if PLACEHOLDER_SOURCE.search(source):
        return "placeholder pin not allowed" if RELEASE_PIN_REQUIRED else None
    return "source is not pinned to a 40-hex commit"


def env_problems(env: dict[str, Any]) -> list[str]:
    problems = []
    for key, value in env.items():
        if key not in ALLOWED_ENV:
            problems.append(f"unexpected env key {key}")
        if not isinstance(value, str) or not REFERENCE.match(value):
            problems.append(f"{key} is not a ${{VAR}} reference")
        if isinstance(value, str) and TOKEN_LIKE.search(value):
            problems.append(f"{key} looks like a token")
    return problems


def front_matter(text: str) -> dict[str, str]:
    match = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, "missing front matter"
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(": ")
        assert sep, f"bad front matter line: {line!r}"
        fields[key] = value
    return fields


# --- plugin.json --------------------------------------------------------------------------------


def test_plugin_json_fields() -> None:
    plugin = load_json(POWER / "plugin.json")
    assert plugin["$schema"] == "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
    assert plugin["name"] == "graveyard"
    assert plugin["version"] == "0.1.0"
    assert plugin["license"] == "Apache-2.0"
    assert isinstance(plugin["description"], str) and plugin["description"]
    assert set(plugin["author"]) >= {"name", "url"}
    for key in ("homepage", "repository"):
        assert plugin[key].startswith("https://")


def test_plugin_json_keyword_set() -> None:
    keywords = load_json(POWER / "plugin.json")["keywords"]
    assert len(keywords) == len(set(keywords))
    assert set(keywords) >= REQUIRED_KEYWORDS


def test_layout_has_no_power_md() -> None:
    assert not list(POWER.rglob("POWER.md"))
    for relative in (
        "plugin.json",
        "mcp.json",
        "README.md",
        "skills/install-blocker-hook/references/dead-install-blocker.json",
    ):
        assert (POWER / relative).is_file(), relative
    for name in SKILL_NAMES:
        assert (POWER / "skills" / name / "SKILL.md").is_file(), name


# --- mcp.json -----------------------------------------------------------------------------------


def test_mcp_json_rules() -> None:
    raw = (POWER / "mcp.json").read_text(encoding="utf-8")
    mcp = load_json(POWER / "mcp.json")
    assert mcp["$schema"] == "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
    assert list(mcp["mcpServers"]) == ["graveyard"]
    server = mcp["mcpServers"]["graveyard"]
    assert server["type"] == "stdio"
    assert server["command"] == "uvx"
    assert "autoApprove" not in server
    assert "autoApprove" not in raw
    args = server["args"]
    assert args[0] == "--from" and args[-1] == "graveyard-mcp" and len(args) == 3
    assert args[1].startswith("graveyard-backend[mcp] ")
    assert pin_problem(args[1]) is None
    assert env_problems(server["env"]) == []
    assert set(server["env"]) == ALLOWED_ENV
    assert not TOKEN_LIKE.search(raw.replace("agent-plugins.org", ""))


def test_hook_template_pin_matches_mcp_pin() -> None:
    mcp_args = load_json(POWER / "mcp.json")["mcpServers"]["graveyard"]["args"]
    command = load_json(HOOK_TEMPLATE)["hooks"][0]["action"]["command"]
    mcp_ref = mcp_args[1].split(" @ ", 1)[1]
    assert mcp_ref in command
    readme = (POWER / "README.md").read_text(encoding="utf-8")
    assert mcp_ref in readme


def test_placeholder_is_an_error_only_when_release_pin_required() -> None:
    placeholder = (
        f"graveyard-backend @ git+https://github.com/o/r.git@{PLACEHOLDER}#subdirectory=backend"
    )
    assert (pin_problem(placeholder) is not None) is RELEASE_PIN_REQUIRED


def test_pin_checker_bad_samples() -> None:
    base = "graveyard-backend @ git+https://github.com/o/r.git"
    sha = "a" * 40
    assert pin_problem(f"{base}@{sha}#subdirectory=backend") is None
    for bad in (
        f"{base}@main#subdirectory=backend",
        f"{base}@v1.0.0#subdirectory=backend",
        f"{base}@latest#subdirectory=backend",
        f"{base}@{'a' * 39}#subdirectory=backend",
        f"{base}#subdirectory=backend",
        f"{base}@{sha}",
        "graveyard-backend",
    ):
        assert pin_problem(bad), bad


def test_env_checker_bad_samples() -> None:
    assert env_problems({"GITHUB_TOKEN": "${GITHUB_TOKEN}"}) == []
    assert env_problems({"GITHUB_TOKEN": "ghp_" + "a" * 36})
    assert env_problems({"GITHUB_TOKEN": "github_pat_" + "A1_" * 10})
    assert env_problems({"GITHUB_TOKEN": "literal"})
    assert env_problems({"GRAVEYARD_CONTACT": "me@example.com"})
    assert env_problems({"OTHER": "${OTHER}"})
    assert env_problems({"GITHUB_TOKEN": 5})


# --- skills -------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_skill_front_matter_and_size(name: str) -> None:
    path = POWER / "skills" / name / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    fields = front_matter(text)
    assert set(fields) == {"name", "description"}
    assert fields["name"] == name == path.parent.name
    assert 0 < len(fields["description"]) <= DESCRIPTION_MAX
    assert len(text.encode("utf-8")) <= SKILL_MAX_BYTES


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_skills_state_no_model_numbers(name: str) -> None:
    body = (POWER / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
    assert not re.search(r"\d\s*%", body)
    assert not re.search(r"\b(weight|threshold)", body, re.IGNORECASE)


def test_front_matter_checker_bad_samples() -> None:
    with pytest.raises(AssertionError):
        front_matter("no front matter")
    with pytest.raises(AssertionError):
        front_matter("---\nbroken\n---\n")


def test_skills_name_the_trigger_words() -> None:
    description = front_matter(
        (POWER / "skills" / "check-before-adding-dependency" / "SKILL.md").read_text("utf-8")
    )["description"]
    for word in ("npm", "pnpm", "yarn", "pip", "uv", "poetry"):
        assert word in description


# --- hook template and in-repo hook schema ------------------------------------------------------


def hook_schema_problems(data: dict[str, Any]) -> list[str]:
    problems = []
    if data.get("version") != "v1":
        problems.append("version")
    hooks = data.get("hooks")
    if not isinstance(hooks, list) or len(hooks) != 1:
        return [*problems, "hooks"]
    hook = hooks[0]
    if not isinstance(hook.get("name"), str) or not hook["name"]:
        problems.append("name")
    if hook.get("trigger") != "PreToolUse":
        problems.append("trigger")
    if hook.get("matcher") != "shell":
        problems.append("matcher")
    if hook.get("timeout") != 20:
        problems.append("timeout")
    action = hook.get("action")
    if not isinstance(action, dict) or action.get("type") != "command":
        problems.append("action.type")
    elif not isinstance(action.get("command"), str) or not action["command"]:
        problems.append("action.command")
    return problems


@pytest.mark.parametrize("path", [HOOK_TEMPLATE, HOOK_IN_REPO], ids=["template", "in-repo"])
def test_hook_schema_fields(path: Path) -> None:
    data = load_json(path)
    assert hook_schema_problems(data) == []
    assert data["hooks"][0]["name"] == "dead-install-blocker"
    assert path.name == "dead-install-blocker.json"


def test_hook_schema_checker_bad_samples() -> None:
    good = load_json(HOOK_TEMPLATE)
    assert hook_schema_problems(good) == []
    for path, value, expected in (
        (("version",), "v2", "version"),
        (("hooks", 0, "trigger"), "PostToolUse", "trigger"),
        (("hooks", 0, "matcher"), "write", "matcher"),
        (("hooks", 0, "timeout"), 60, "timeout"),
        (("hooks", 0, "action", "type"), "agent", "action.type"),
        (("hooks", 0, "action", "command"), "", "action.command"),
    ):
        data = load_json(HOOK_TEMPLATE)
        node: Any = data
        for step in path[:-1]:
            node = node[step]
        node[path[-1]] = value
        assert expected in hook_schema_problems(data), path
    assert hook_schema_problems({"version": "v1", "hooks": []}) == ["hooks"]


def test_hook_commands_only_exit_zero_or_two_by_construction() -> None:
    for path in (HOOK_TEMPLATE, HOOK_IN_REPO):
        command = load_json(path)["hooks"][0]["action"]["command"]
        assert command.endswith("exit 0")
        assert '[ "$s" -eq 2 ] && exit 2' in command
        assert "uv run" not in command  # D4: uv reports its own failures with status 2


# --- README (KPW-PWR-7) -------------------------------------------------------------------------

README_LIMITS = {
    "token": "GITHUB_TOKEN",
    "windows": "Windows",
    "build-dependent payload delivery": "Build-dependent payload delivery",
    "stdout note": "stdout note",
    "latest-version approximation": "Latest-version approximation",
    "range rule": "range rule",
    "redirections": "Redirections",
    "-r handling": "`-r` requirements files",
    "-r confinement": "confinement",
    "fail open": "Fail open",
    "uv tool install": "uv tool install",
    "first uvx run": "First `uvx` run",
    "dry run": 'graveyard check-install "npm install request"',
    "exit-code table": "| 2 | Block.",
    "import from folder": "Import power from a folder",
    "import from GitHub": "Import power from GitHub",
    "install-blocker-hook skill": "install-blocker-hook",
    "Install powers page": "https://kiro.dev/docs/powers/installation/",
}


@pytest.mark.parametrize("limit", sorted(README_LIMITS))
def test_readme_mentions_each_limit(limit: str) -> None:
    readme = (POWER / "README.md").read_text(encoding="utf-8").lower()
    assert README_LIMITS[limit].lower() in readme, limit
