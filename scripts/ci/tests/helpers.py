"""Shared test helpers: throwaway git repositories and a hermetic git environment."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from typing import Dict, Optional

CI_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(CI_DIR) not in sys.path:
    sys.path.insert(0, str(CI_DIR))

# 12 digits, built at run time so that no test file contains a literal account ID.
FAKE_ACCOUNT = "9" * 12
PLACEHOLDER = "123456789" + "012"


def git_env() -> Dict[str, str]:
    """A minimal environment: no user, global or system git config, and no cloud variables."""
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": tempfile.gettempdir(),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, env=git_env(), capture_output=True, text=True, check=check)


class RepoCase(unittest.TestCase):
    """Creates a fresh git repository per test. Use `self.repo` and `self.write(...)`."""

    def setUp(self) -> None:
        # Hermetic: the code under test runs git in this process, so replace the whole environment
        # (no user git config, no cloud variables) for the duration of the test.
        patcher = mock.patch.dict(os.environ, git_env(), clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name).resolve()
        git(self.repo, "init", "-q", "-b", "main")

    def write(self, path: str, text: str = "", add: bool = True, force: bool = False) -> Path:
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        if add:
            git(self.repo, "add", *(["-f"] if force else []), "--", path)
        return target

    def commit(self, message: str = "c") -> None:
        git(self.repo, "commit", "-q", "--allow-empty", "-m", message)

    def head(self) -> str:
        return git(self.repo, "rev-parse", "HEAD").stdout.strip()


def run_script(script: Path, *args: str, cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), *args], cwd=cwd, env=git_env(), capture_output=True, text=True, check=False
    )
