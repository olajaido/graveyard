"""The ``python -m cli`` entry point (T8.3; CLI-DEP-3).

These tests start a real interpreter, so they exercise ``main()`` with the real process
environment and streams. No test here reaches the network: every command ends before any
HTTP request (version, usage error).
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

from cli.app import run
from cli.tests.support import make_env

BACKEND = Path(__file__).resolve().parents[2]


def _module(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "cli", *args],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_version_matches_app_run() -> None:
    out = io.StringIO()
    assert run(["--version"], env=make_env(), out=out, err=io.StringIO()) == 0
    completed = _module("--version")
    assert completed.returncode == 0
    assert completed.stdout == out.getvalue()
    assert completed.stdout.startswith("graveyard ")
    assert completed.stderr == ""


def test_usage_error_through_the_real_main() -> None:
    completed = _module("autopsy")
    assert completed.returncode == 2
    assert completed.stdout == ""
    assert completed.stderr.startswith("graveyard: error: give a PATH")
    assert "usage:" in completed.stderr


def test_a_blank_token_in_the_process_environment_does_not_crash() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "cli", "autopsy"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env={"PATH": "/usr/bin:/bin", "GITHUB_TOKEN": ""},
    )
    assert completed.returncode == 2
