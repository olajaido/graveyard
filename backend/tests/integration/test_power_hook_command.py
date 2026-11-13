"""Hook command tests (KPW-TEST-9, KPW-INST-5): the command strings run through ``sh -c``.

Fakes are shell scripts in a temporary ``bin``; no network, no real graveyard/uvx.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from tests.integration.power_files import HOOK_IN_REPO, HOOK_TEMPLATE, hook_command

EXIT_CODES = [0, 1, 2, 3, 126, 127, 139]
STDIN_TEXT = '{"tool_input":{"command":"npm install request"}}'

FAKE = """#!/bin/sh
IFS= read -r line
echo "stdin:$line"
echo "args:$*"
echo "marker-out"
echo "marker-err" >&2
exit {code}
"""


def write_fake(path: Path, code: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(FAKE.format(code=code), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def run_sh(command: str, cwd: Path, path_dirs: list[Path]) -> subprocess.CompletedProcess[str]:
    env = {"PATH": os.pathsep.join(str(d) for d in path_dirs)}
    return subprocess.run(
        ["/bin/sh", "-c", command],
        cwd=cwd,
        env=env,
        input=STDIN_TEXT + "\n",
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


class Case:
    """One hook command and how to put a fake (or nothing) where it looks for the executable."""

    def __init__(self, name: str, command: str) -> None:
        self.name = name
        self.command = command

    def install(self, root: Path, code: int | None) -> list[Path]:
        bin_dir = root / "bin"
        bin_dir.mkdir()
        if self.name == "in-repo":
            if code is not None:
                write_fake(root / "backend" / ".venv" / "bin" / "graveyard", code)
            return [bin_dir]
        if code is not None:
            write_fake(bin_dir / "uvx", code)
        return [bin_dir]


CASES = [
    Case("in-repo", hook_command(HOOK_IN_REPO)),
    Case("template", hook_command(HOOK_TEMPLATE)),
]


@pytest.fixture(params=CASES, ids=lambda c: c.name)
def case(request: pytest.FixtureRequest) -> Case:
    assert isinstance(request.param, Case)
    return request.param


@pytest.mark.parametrize("code", EXIT_CODES)
def test_exit_two_only_when_the_fake_exits_two(case: Case, tmp_path: Path, code: int) -> None:
    dirs = case.install(tmp_path, code)
    result = run_sh(case.command, tmp_path, dirs)
    assert result.returncode == (2 if code == 2 else 0)
    # Output passes through, and stdin reaches the fake.
    assert "marker-out" in result.stdout
    assert "marker-err" in result.stderr
    assert f"stdin:{STDIN_TEXT}" in result.stdout
    assert "check-install" in result.stdout


def test_missing_executable_allows(case: Case, tmp_path: Path) -> None:
    dirs = case.install(tmp_path, None)
    result = run_sh(case.command, tmp_path, dirs)
    assert result.returncode == 0
    assert result.stdout == "" and result.stderr == ""


def test_non_executable_in_repo_file_allows(tmp_path: Path) -> None:
    exe = tmp_path / "backend" / ".venv" / "bin" / "graveyard"
    write_fake(exe, 2)
    exe.chmod(0o644)
    result = run_sh(hook_command(HOOK_IN_REPO), tmp_path, [])
    assert result.returncode == 0


@pytest.mark.parametrize("code", [126, 127])
def test_unrunnable_executable_allows(case: Case, tmp_path: Path, code: int) -> None:
    dirs = case.install(tmp_path, 0)
    target = (
        tmp_path / "backend" / ".venv" / "bin" / "graveyard"
        if case.name == "in-repo"
        else tmp_path / "bin" / "uvx"
    )
    target.write_text("#!/nonexistent/interpreter\n", encoding="utf-8")
    result = run_sh(case.command, tmp_path, dirs)
    assert result.returncode == 0, (code, result.stderr)


def test_template_passes_check_install_after_the_pinned_source(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    write_fake(bin_dir / "uvx", 0)
    result = run_sh(hook_command(HOOK_TEMPLATE), tmp_path, [bin_dir])
    args = next(line for line in result.stdout.splitlines() if line.startswith("args:"))
    assert args.startswith("args:--from graveyard-backend @ git+https://github.com/")
    assert args.endswith("graveyard check-install")


def test_in_repo_hook_never_reads_the_cwd_executable_outside_backend(tmp_path: Path) -> None:
    write_fake(tmp_path / "graveyard", 2)  # wrong place: must be ignored
    result = run_sh(hook_command(HOOK_IN_REPO), tmp_path, [tmp_path])
    assert result.returncode == 0


# --- D4: why the in-repo hook avoids `uv run` ---------------------------------------------------

UV_RUN_HOOK = (
    'uv run graveyard check-install; s=$?; [ "$s" -eq 2 ] && exit 2; exit 0'  # hypothetical hook
)


def test_fake_uv_run_failure_exit_two_would_block(tmp_path: Path) -> None:
    """A uv that fails to start the program exits 2, which the snippet cannot tell from a block."""
    uv = tmp_path / "bin" / "uv"
    uv.parent.mkdir()
    uv.write_text("#!/bin/sh\necho 'error: Failed to spawn' >&2\nexit 2\n", encoding="utf-8")
    uv.chmod(0o755)
    result = run_sh(UV_RUN_HOOK, tmp_path, [uv.parent])
    assert result.returncode == 2  # a false block: this is why neither hook calls uv run
    for path in (HOOK_IN_REPO, HOOK_TEMPLATE):
        assert "uv run" not in hook_command(path)


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not installed")
def test_real_uv_run_exits_two_when_it_cannot_spawn(tmp_path: Path) -> None:
    """Recorded observation (uv 0.11.8): offline `uv run` of a missing program exits 2."""
    result = subprocess.run(
        ["uv", "run", "--offline", "--no-project", "--", "graveyard-definitely-missing-cmd"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env={**os.environ, "UV_NO_CONFIG": "1"},
    )
    assert result.returncode == 2
    assert "Failed to spawn" in result.stderr
