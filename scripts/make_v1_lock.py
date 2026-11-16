#!/usr/bin/env python3
"""Write eval/V1_LOCK.json: SHA-256 of every frozen v1 file at the tag (mortality-model-v2, 3.1).

Every file is read with ``git show <tag>:<path>``, so the lock records the tagged bytes and
not the working tree. File lists come from ``git ls-tree`` on the tag. The v1 import closure
of ``core.scoring`` is computed from the working tree with ``eval.manifest``; the script aborts
if any closure file is absent from the tag or differs between the working tree and the tag.
The output is created exclusively and never overwritten. Local git only; no network.

Usage:
    python3 scripts/make_v1_lock.py [--repo PATH] [--tag TAG] [--out PATH]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TAG = "eval-v1-result"
DEFAULT_OUT_NAME = "eval/V1_LOCK.json"
SCHEMA = "graveyard.v1-lock"
SCHEMA_VERSION = 1
CLOSURE_ENTRY = "core.scoring"
LABELLING_PATH = "eval/LABELLING.md"
LABELLING_SECTIONS = (1, 2, 6)
FROZEN_FILES = (
    "backend/core/scoring/weights.v1.yaml",
    "eval/FROZEN_WEIGHTS.sha256",
    "eval/labelled_packages.csv",
    "eval/gate.yaml",
    "eval/results.json",
)
FROZEN_DIRS = ("eval/fixtures/", "eval/review/")
ANCHOR_DIR = "backend/core/scoring/tests/fixtures/anchors/"

# The eval package lives under backend/ of the script's own checkout.
sys.path.insert(0, str(REPO_ROOT / "backend"))
from eval.manifest import ManifestError, closure, labelling_section  # noqa: E402


class LockError(Exception):
    """The lock cannot be built; nothing is written."""


def _git(repo: Path, *args: str) -> bytes:
    try:
        done = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        raise LockError(f"cannot run git: {exc}") from exc
    if done.returncode != 0:
        detail = done.stderr.decode("utf-8", "replace").strip()
        raise LockError(f"git {' '.join(args)} failed: {detail}")
    return done.stdout


def tag_commit(repo: Path, tag: str) -> str:
    """Commit SHA the tag points at; raises LockError when the tag is absent."""
    out = _git(repo, "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}^{{commit}}")
    return out.decode("ascii").strip()


def tagged_bytes(repo: Path, tag: str, path: str) -> bytes:
    return _git(repo, "show", f"{tag}:{path}")


def tagged_files(repo: Path, tag: str, prefix: str) -> list[str]:
    """Paths of every file at the tag under ``prefix`` (a directory ending in /)."""
    out = _git(repo, "ls-tree", "-r", "-z", "--name-only", tag, "--", prefix)
    names = sorted(n for n in out.decode("utf-8").split("\0") if n)
    if not names:
        raise LockError(f"no files under {prefix} at tag {tag}")
    return names


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def closure_paths(repo: Path) -> list[str]:
    """Repo-relative paths of the v1 closure, from the working tree."""
    backend = repo / "backend"
    try:
        files = closure(CLOSURE_ENTRY, backend)
    except ManifestError as exc:
        raise LockError(f"closure of {CLOSURE_ENTRY}: {exc}") from exc
    return sorted(f"backend/{p.relative_to(backend).as_posix()}" for p in files)


def build_lock(repo: Path, tag: str) -> dict[str, object]:
    commit = tag_commit(repo, tag)

    paths: set[str] = set(FROZEN_FILES)
    for directory in FROZEN_DIRS:
        paths.update(tagged_files(repo, tag, directory))
    paths.update(tagged_files(repo, tag, ANCHOR_DIR))

    closure_files = closure_paths(repo)
    for rel in closure_files:
        tagged = tagged_bytes(repo, tag, rel)
        if (repo / rel).read_bytes() != tagged:
            raise LockError(f"{rel}: working tree differs from tag {tag}")
    paths.update(closure_files)

    files = {rel: _sha256(tagged_bytes(repo, tag, rel)) for rel in sorted(paths)}

    labelling = tagged_bytes(repo, tag, LABELLING_PATH).decode("utf-8")
    try:
        sections = {
            str(n): _sha256(labelling_section(labelling, n).encode("utf-8"))
            for n in LABELLING_SECTIONS
        }
    except ManifestError as exc:
        raise LockError(str(exc)) from exc

    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "source_tag": tag,
        "source_commit": commit,
        "files": files,
        "labelling_sections": sections,
    }


def render(lock: dict[str, object]) -> bytes:
    return (json.dumps(lock, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def write_exclusive(out: Path, data: bytes) -> None:
    try:
        with out.open("xb") as handle:
            handle.write(data)
    except FileExistsError as exc:
        raise LockError(f"{out} already exists; refusing to overwrite") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--repo", type=Path, default=REPO_ROOT)
    parser.add_argument("--tag", default=DEFAULT_TAG)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    repo: Path = args.repo.resolve()
    out: Path = args.out if args.out is not None else repo / DEFAULT_OUT_NAME
    try:
        if out.exists():
            raise LockError(f"{out} already exists; refusing to overwrite")
        data = render(build_lock(repo, args.tag))
        write_exclusive(out, data)
    except LockError as exc:
        print(f"make_v1_lock: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {out} ({len(data)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
