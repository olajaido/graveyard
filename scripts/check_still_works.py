#!/usr/bin/env python3
"""Review check for finished-healthy rows (T14; eval/LABELLING.md).

For each ``finished-healthy`` row of ``eval/labelled_packages.csv``, check that the
labelled version installs and imports on a current runtime (Python 3.12 for pypi,
Node 22 for npm). Writes ``eval/review/still_works.tsv`` and prints a summary.

Isolation: every check runs in a fresh ``docker run --rm`` container with no volume
mounts and no host environment passed in. Package name and version are passed as
positional arguments, never through the environment. Nothing is ever installed on
the host. Run by hand only; tests never call Docker.

Usage:
    python3 scripts/check_still_works.py [--csv PATH] [--out PATH] [--limit N]
"""

from __future__ import annotations

import argparse
import csv
import inspect
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV = REPO_ROOT / "eval" / "labelled_packages.csv"
DEFAULT_OUT = REPO_ROOT / "eval" / "review" / "still_works.tsv"

LABEL = "finished-healthy"
TIMEOUT_SECONDS = 300
TAIL_LINES = 20

RUNTIMES = {"pypi": "python:3.12-slim", "npm": "node:22-slim"}

PASS = "pass"
FAIL_INSTALL = "fail_install"
FAIL_IMPORT = "fail_import"
TIMEOUT = "timeout"
RESULTS = (PASS, FAIL_INSTALL, FAIL_IMPORT, TIMEOUT)

# Printed by the container once the install step has succeeded.
IMPORT_MARKER = "GRAVEYARD_PHASE=import"

_NAME = re.compile(r"^[A-Za-z0-9@][A-Za-z0-9._/~-]*$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+!-]*$")

Row = tuple[str, str, str]  # (ecosystem, name, version)


# --------------------------------------------------------------------------- #
# Pure logic
# --------------------------------------------------------------------------- #
def filter_rows(rows: list[dict[str, str]]) -> list[Row]:
    """Keep finished-healthy rows with a known ecosystem and safe name/version.

    Raises ``ValueError`` for a finished-healthy row that cannot be checked safely.
    """
    out: list[Row] = []
    for row in rows:
        if (row.get("label") or "").strip() != LABEL:
            continue
        eco = (row.get("ecosystem") or "").strip()
        name = (row.get("name") or "").strip()
        version = (row.get("version") or "").strip()
        if eco not in RUNTIMES:
            raise ValueError(f"unknown ecosystem {eco!r} for {name!r}")
        if not _NAME.match(name) or ".." in name:
            raise ValueError(f"unsafe package name {name!r}")
        if not _VERSION.match(version):
            raise ValueError(f"unsafe version {version!r} for {name!r}")
        out.append((eco, name, version))
    return out


def derive_import_names(top_level_text: str | None, record_text: str | None) -> list[str]:
    """Top-level import names of a distribution.

    Uses ``top_level.txt`` when it has names, else derives them from ``RECORD``.
    Self-contained on purpose: its source is shipped into the container.
    """
    names: list[str] = []

    def add(candidate: str) -> None:
        if candidate.isidentifier() and candidate != "__pycache__" and candidate not in names:
            names.append(candidate)

    for line in (top_level_text or "").splitlines():
        line = line.strip()
        if line and "/" not in line and "\\" not in line:
            add(line)
    if names:
        return sorted(names)

    for line in (record_text or "").splitlines():
        path = line.split(",", 1)[0].strip().replace("\\", "/")
        if not path or path.startswith("../") or path.startswith("/"):
            continue
        parts = path.split("/")
        first = parts[0]
        if first.endswith((".dist-info", ".egg-info", ".data")) or "__pycache__" in parts:
            continue
        if len(parts) == 1:
            if first.endswith(".py"):
                add(first[:-3])
            elif first.endswith((".so", ".pyd")):
                add(first.split(".")[0])
        elif parts[-1].endswith((".py", ".so", ".pyd")):
            add(first)
    return sorted(names)


def tail_lines(text: str, n: int = TAIL_LINES) -> str:
    """Last ``n`` non-empty lines of ``text``."""
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines[-n:])


def classify(returncode: int | None, output: str, timed_out: bool) -> str:
    """Map a container run to one of ``RESULTS``.

    The import marker proves the install step finished; without it the install failed.
    """
    if timed_out:
        return TIMEOUT
    if IMPORT_MARKER not in output:
        return FAIL_INSTALL
    return PASS if returncode == 0 else FAIL_IMPORT


def format_detail(output: str) -> str:
    """One-line TSV-safe form of the last 20 output lines."""
    return tail_lines(output).replace("\t", " ").replace("\r", "").replace("\n", " | ")


def tsv_line(fields: list[str]) -> str:
    return "\t".join(f.replace("\t", " ").replace("\n", " ") for f in fields)


def summarise(results: list[str]) -> str:
    counts = {r: results.count(r) for r in RESULTS}
    parts = ", ".join(f"{r}={counts[r]}" for r in RESULTS)
    return f"{len(results)} checked: {parts}"


# --------------------------------------------------------------------------- #
# Container scripts (run inside docker; arguments are positional: name version code)
# --------------------------------------------------------------------------- #
_PY_DRIVER = """
import importlib, importlib.metadata as md, sys
name = sys.argv[1]
dist = md.distribution(name)
names = derive_import_names(dist.read_text("top_level.txt"), dist.read_text("RECORD"))
print("import names:", names)
if not names:
    print("no importable top-level names found")
    sys.exit(1)
failed = 0
for n in names:
    try:
        importlib.import_module(n)
        print("imported", n)
    except BaseException as exc:
        failed += 1
        print("FAILED", n, type(exc).__name__, exc)
sys.exit(1 if failed else 0)
"""

PY_CODE = inspect.getsource(derive_import_names) + _PY_DRIVER

PY_SHELL = (
    'pip install --no-cache-dir "$1==$2" && echo ' + IMPORT_MARKER + ' && python -c "$3" "$1"'
)

NODE_CODE = """
const name = process.argv[1];
try {
  require(name);
  console.log('required', name);
} catch (e) {
  if (e && e.code === 'ERR_REQUIRE_ESM') {
    import(name).then(() => console.log('imported (esm)', name))
      .catch((err) => { console.log('FAILED', String(err)); process.exit(1); });
  } else {
    console.log('FAILED', String(e)); process.exit(1);
  }
}
"""

NODE_SHELL = (
    'mkdir /tmp/work && cd /tmp/work && npm install --no-audit --no-fund "$1@$2" && echo '
    + IMPORT_MARKER
    + ' && node -e "$3" "$1"'
)


def build_command(eco: str, name: str, version: str, container: str) -> list[str]:
    """The ``docker run`` argv for one check. No mounts, no env passthrough."""
    code, shell = (PY_CODE, PY_SHELL) if eco == "pypi" else (NODE_CODE, NODE_SHELL)
    return [
        "docker",
        "run",
        "--rm",
        "--name",
        container,
        "--memory",
        "1g",
        "--pids-limit",
        "512",
        RUNTIMES[eco],
        "sh",
        "-c",
        shell,
        "sh",
        name,
        version,
        code,
    ]


# --------------------------------------------------------------------------- #
# Docker I/O (not exercised by tests)
# --------------------------------------------------------------------------- #
@dataclass
class Outcome:
    result: str
    detail: str


def run_check(eco: str, name: str, version: str) -> Outcome:
    container = f"graveyard-still-works-{uuid.uuid4().hex[:12]}"
    cmd = build_command(eco, name, version, container)
    timed_out = False
    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
        output = (proc.stdout or "") + "\n" + (proc.stderr or "")
        code: int | None = proc.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        out = exc.stdout or b""
        err = exc.stderr or b""
        output = (
            (out.decode("utf-8", "replace") if isinstance(out, bytes) else out)
            + "\n"
            + (err.decode("utf-8", "replace") if isinstance(err, bytes) else err)
        )
        code = None
        subprocess.run(  # noqa: S603
            ["docker", "rm", "-f", container],
            capture_output=True,
            check=False,
            timeout=60,
        )
    result = classify(code, output, timed_out)
    detail = format_detail(output)
    if timed_out:
        detail = f"timed out after {TIMEOUT_SECONDS}s | {detail}".rstrip(" |")
    return Outcome(result, detail)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--limit", type=int, default=None, help="check only the first N rows")
    args = ap.parse_args(argv)

    with args.csv.open(newline="", encoding="utf-8") as fh:
        rows = filter_rows(list(csv.DictReader(fh)))
    if args.limit is not None:
        rows = rows[: args.limit]

    lines = [tsv_line(["ecosystem", "name", "version", "result", "runtime", "detail"])]
    results: list[str] = []
    for eco, name, version in rows:
        try:
            outcome = run_check(eco, name, version)
        except FileNotFoundError:
            print("docker not found on PATH", file=sys.stderr)
            return 2
        results.append(outcome.result)
        lines.append(tsv_line([eco, name, version, outcome.result, RUNTIMES[eco], outcome.detail]))
        print(f"{outcome.result:13} {eco}/{name}@{version}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(summarise(results))
    print(f"wrote {args.out}")
    return 0 if all(r == PASS for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
