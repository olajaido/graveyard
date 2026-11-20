#!/usr/bin/env python3
"""Path filter for ci.yml: print `infra=true` or `infra=false` (INF-CI-1, design 8.1).

    changed_paths.py --base <sha> --head <sha> [--merge-base]

`infra` is true when a file under infra/, .github/, scripts/ci/, scripts/build/, docs/runbooks/ or a backend package that goes into lambda.zip changed
between the two commits. It is also true, so that nothing is skipped by mistake, when the base
is empty or all zeros (a new branch or a first push) or when git cannot produce the diff.
`--merge-base` diffs `base...head` (pull requests); without it `base head` (pushes).
Rename detection is off, so moving a file out of a watched directory still counts.

Standard library only. The output line is meant for `>> "$GITHUB_OUTPUT"`. Exit 0, or 2 on bad usage.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence

# scan-backend: the Lambda zips are built from the backend packages and scripts/build, so a change there changes the plan.
PATTERNS = (
    "infra/", ".github/", "scripts/ci/", "scripts/build/", "docs/runbooks/",
    "backend/core/", "backend/sources/", "backend/cli/", "backend/exhume/", "backend/scan/",
    "backend/workflow/", "backend/api/", "backend/pyproject.toml", "backend/uv.lock",
)
ZERO = "0" * 40


def changed(root: Path, base: str, head: str, merge_base: bool = False) -> bool:
    if not base or base == ZERO or not head:
        return True
    spec = [f"{base}...{head}"] if merge_base else [base, head]
    done = subprocess.run(["git", "diff", "--name-only", "--no-renames", "-z", *spec, "--"], cwd=root, capture_output=True, check=False)
    if done.returncode != 0:
        return True
    names = [n for n in done.stdout.decode("utf-8", errors="surrogateescape").split("\0") if n]
    return any(name.startswith(PATTERNS) for name in names)


def main(argv: Optional[Sequence[str]] = None, root: Optional[Path] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="", help="base commit; empty or all zeros means 'run everything'")
    parser.add_argument("--head", default="HEAD", help="head commit (default HEAD)")
    parser.add_argument("--merge-base", action="store_true", help="diff base...head (pull requests)")
    args = parser.parse_args(argv)
    repo = root if root is not None else Path.cwd()
    sys.stdout.write(f"infra={'true' if changed(repo, args.base, args.head, args.merge_base) else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
