"""Drift tests (KPW-INST-4, KPW-TEST-13): the .kiro copies equal their Power sources.

The comparison is the script's own (``sync-power.py --check``), run on the real files and,
with the script's path constants redirected, on temporary trees for the negative cases.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from tests.integration.power_files import (
    HOOK_IN_REPO,
    HOOK_TEMPLATE,
    KIRO,
    POWER,
    REPO,
    SYNC_SCRIPT,
    hook_command,
    load_json,
)

SYNCED_SKILLS = ("check-before-adding-dependency", "reading-a-verdict")


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sync_power_under_test", SYNC_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[ModuleType, Path]:
    """The script pointed at a copy of the Power and an empty .kiro."""
    module = load_script()
    power = tmp_path / "powers" / "graveyard"
    shutil.copytree(POWER, power)
    kiro = tmp_path / ".kiro"
    monkeypatch.setattr(module, "REPO", tmp_path)
    monkeypatch.setattr(module, "POWER", power)
    monkeypatch.setattr(module, "KIRO", kiro)
    monkeypatch.setattr(
        module,
        "HOOK_SOURCE",
        power / "skills" / "install-blocker-hook" / "references" / "dead-install-blocker.json",
    )
    monkeypatch.setattr(module, "HOOK_TARGET", kiro / "hooks" / "dead-install-blocker.json")
    monkeypatch.setattr(module, "MCP_SOURCE", power / "mcp.json")
    monkeypatch.setattr(module, "MCP_TARGET", kiro / "settings" / "mcp.json")
    return module, tmp_path


def test_real_files_are_in_sync() -> None:
    result = subprocess.run(
        [sys.executable, str(SYNC_SCRIPT), "--check"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, f"drifted files:\n{result.stdout}{result.stderr}"
    assert result.stdout == ""


def test_skills_are_byte_identical() -> None:
    for name in SYNCED_SKILLS:
        source = (POWER / "skills" / name / "SKILL.md").read_bytes()
        assert (KIRO / "skills" / name / "SKILL.md").read_bytes() == source
    assert not (KIRO / "skills" / "install-blocker-hook").exists()


def test_in_repo_hook_equals_template_except_command() -> None:
    template = load_json(HOOK_TEMPLATE)
    in_repo = load_json(HOOK_IN_REPO)
    assert hook_command(HOOK_TEMPLATE) != hook_command(HOOK_IN_REPO)
    template["hooks"][0]["action"]["command"] = in_repo["hooks"][0]["action"]["command"]
    assert template == in_repo


def test_in_repo_mcp_equals_power_except_command_args_and_approve() -> None:
    source = load_json(POWER / "mcp.json")["mcpServers"]["graveyard"]
    target = load_json(KIRO / "settings" / "mcp.json")["mcpServers"]["graveyard"]
    assert target["type"] == source["type"]
    assert target["command"] == "uv"
    assert target["args"] == ["run", "--project", "backend", "--extra", "mcp", "graveyard-mcp"]
    assert target["autoApprove"] == ["autopsy_package", "autopsy_project"]
    assert target["env"] == {k: v for k, v in source["env"].items() if k != "GRAVEYARD_MCP_ROOT"}
    assert set(target) == {"type", "command", "args", "env", "autoApprove"}


def test_kiro_hooks_folder_has_only_the_expected_files() -> None:
    names = sorted(p.name for p in (KIRO / "hooks").iterdir() if p.is_file())
    assert names == ["dead-install-blocker.json", "kiro-journal.json"]


# --- the check detects drift (negative cases on a sandbox) --------------------------------------


def test_check_lists_everything_missing_then_write_then_clean(
    sandbox: tuple[ModuleType, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    module, root = sandbox
    assert module.main(["--check"]) == 1
    listed = capsys.readouterr().out.split()
    assert listed == [
        ".kiro/skills/check-before-adding-dependency/SKILL.md",
        ".kiro/skills/reading-a-verdict/SKILL.md",
        ".kiro/hooks/dead-install-blocker.json",
        ".kiro/settings/mcp.json",
    ]
    assert not (root / ".kiro").exists()  # --check writes nothing
    assert module.main([]) == 0
    capsys.readouterr()
    assert module.main(["--check"]) == 0
    assert capsys.readouterr().out == ""


def test_check_names_the_drifted_skill(
    sandbox: tuple[ModuleType, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    module, root = sandbox
    module.main([])
    capsys.readouterr()
    skill = root / ".kiro" / "skills" / "reading-a-verdict" / "SKILL.md"
    skill.write_bytes(skill.read_bytes() + b"x")
    assert module.main(["--check"]) == 1
    assert capsys.readouterr().out.split() == [".kiro/skills/reading-a-verdict/SKILL.md"]


def test_check_names_a_hook_with_a_changed_field(
    sandbox: tuple[ModuleType, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    module, root = sandbox
    module.main([])
    capsys.readouterr()
    hook = root / ".kiro" / "hooks" / "dead-install-blocker.json"
    data = json.loads(hook.read_text("utf-8"))
    data["hooks"][0]["timeout"] = 5
    hook.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    assert module.main(["--check"]) == 1
    assert capsys.readouterr().out.split() == [".kiro/hooks/dead-install-blocker.json"]


def test_mcp_merge_keeps_other_servers(sandbox: tuple[ModuleType, Path]) -> None:
    module, root = sandbox
    target = root / ".kiro" / "settings" / "mcp.json"
    target.parent.mkdir(parents=True)
    target.write_text(
        json.dumps({"mcpServers": {"other": {"command": "x"}}, "extra": 1}), encoding="utf-8"
    )
    assert module.main([]) == 0
    merged = json.loads(target.read_text("utf-8"))
    assert merged["mcpServers"]["other"] == {"command": "x"}
    assert merged["extra"] == 1
    assert merged["mcpServers"]["graveyard"]["command"] == "uv"
    assert module.main(["--check"]) == 0


def test_repo_root_is_the_expected_checkout() -> None:
    assert (REPO / ".kiro").is_dir() and (REPO / "backend" / "pyproject.toml").is_file()
