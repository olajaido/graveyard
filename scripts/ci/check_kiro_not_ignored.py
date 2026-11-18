#!/usr/bin/env python3
"""Fail if .kiro/ is git-ignored or has no tracked files (INF-KIRO-1, PRD 2.4, structure.md).

`.kiro/` is part of the hackathon submission and must be committed. The check:

  1. `git ls-files .kiro` is not empty;
  2. `git check-ignore --no-index` reports no ignore rule for `.kiro`, `.kiro/` or any tracked
     file under it. `--no-index` makes git apply ignore rules to tracked files too, which is how
     a newly added `.kiro/` or `.kiro/*` line is caught. It reads .gitignore files, the
     repository's .git/info/exclude and the user's global excludes file.

Standard library only. Exit codes: 0 pass, 1 fail, 2 git error. Messages go to stderr.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Sequence


def _git(root: Path, *args: str, stdin: Optional[bytes] = None, ok: Sequence[int] = (0,)) -> bytes:
    done = subprocess.run(["git", *args], cwd=root, input=stdin, capture_output=True, check=False)
    if done.returncode not in ok:
        raise RuntimeError(f"git {' '.join(args)} failed: {done.stderr.decode(errors='replace').strip()}")
    return done.stdout


def _root(start: Path) -> Path:
    return Path(_git(start, "rev-parse", "--show-toplevel").decode().strip())


def problems(root: Path) -> List[str]:
    found: List[str] = []
    raw = _git(root, "ls-files", "-z", "--", ".kiro")
    tracked = [name for name in raw.decode("utf-8", errors="surrogateescape").split("\0") if name]
    if not tracked:
        found.append(".kiro/ has no tracked files; it must be committed")
    candidates = [".kiro", ".kiro/", *tracked]
    stdin = ("\0".join(candidates) + "\0").encode("utf-8", errors="surrogateescape")
    # exit 0: at least one path is ignored; 1: none is; anything else is an error.
    out = _git(root, "check-ignore", "--no-index", "-v", "-z", "--stdin", stdin=stdin, ok=(0, 1))
    fields = out.decode("utf-8", errors="surrogateescape").split("\0")
    if fields and fields[-1] == "":
        fields.pop()
    for i in range(0, len(fields) - 3, 4):
        source, line, pattern, path = fields[i : i + 4]
        if pattern.startswith("!"):
            continue  # a negation: the path is explicitly not ignored
        where = f"{source}:{line}" if source else "a global or built-in rule"
        found.append(f"{path} is git-ignored by {where} (pattern {pattern!r}); .kiro/ must never be ignored")
    return found


def main(argv: Optional[Sequence[str]] = None, root: Optional[Path] = None) -> int:
    _ = argv
    try:
        repo = root if root is not None else _root(Path(__file__).resolve().parent)
        found = problems(repo)
    except RuntimeError as error:
        sys.stderr.write(f"{error}\n")
        return 2
    for message in found:
        sys.stderr.write(f"kiro-not-ignored: {message}\n")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
