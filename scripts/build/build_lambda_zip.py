#!/usr/bin/env python3
"""Build ``lambda.zip``: the backend code and its Lambda dependencies, byte-for-byte reproducible.

Dependencies come from ``backend/uv.lock`` (extra ``aws``) for ``aarch64-manylinux2014`` and
Python 3.12, wheels only. boto3 and botocore are left out: the Lambda runtime provides them.
Usage: ``build_lambda_zip.py OUT.zip`` (prints the SHA-256 of the zip).
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from zipping import FILE_MODE, write_zip  # noqa: E402

BACKEND = Path(__file__).resolve().parents[2] / "backend"
CODE_PACKAGES = ("core", "sources", "cli", "exhume", "scan", "workflow", "api")
SKIP_DIRS = {"tests", "__pycache__"}
SKIP_FILES = {"fakes.py", "conftest.py"}
RUNTIME_PROVIDED = ("boto3", "botocore", "s3transfer", "jmespath")


def code_files(root: Path) -> Iterator[tuple[str, Path]]:
    for package in CODE_PACKAGES:
        for path in sorted((root / package).rglob("*")):
            relative = path.relative_to(root)
            if (
                path.is_file()
                and not (set(relative.parts) & SKIP_DIRS)
                and path.name not in SKIP_FILES
                and path.suffix != ".pyc"
            ):
                yield relative.as_posix(), path


def tree_files(root: Path) -> Iterator[tuple[str, Path]]:
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if path.is_file() and "__pycache__" not in relative.parts and path.suffix != ".pyc":
            yield relative.as_posix(), path


def build(out: Path, backend: Path = BACKEND) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        exported = subprocess.run(
            ["uv", "export", "--frozen", "--no-dev", "--extra", "aws", "--no-emit-project", "--no-hashes"],
            cwd=backend, check=True, capture_output=True, text=True,
        ).stdout
        wanted = [
            line for line in exported.splitlines()
            if line and not line.startswith("#")
            and not any(line.lower().startswith(f"{name}==") for name in RUNTIME_PROVIDED)
        ]
        (work / "requirements.txt").write_text("\n".join(wanted) + "\n")
        target = work / "site"
        subprocess.run(
            ["uv", "pip", "install", "--target", str(target), "--python-platform", "aarch64-manylinux2014",
             "--python-version", "3.12", "--only-binary", ":all:", "--no-deps", "-r", str(work / "requirements.txt")],
            check=True, capture_output=True,
        )
        entries = {name: (path.read_bytes(), FILE_MODE) for name, path in tree_files(target)}
        entries.update({name: (path.read_bytes(), FILE_MODE) for name, path in code_files(backend)})
        return write_zip(entries, out)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: build_lambda_zip.py OUT.zip", file=sys.stderr)
        return 2
    print(build(Path(argv[1])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
