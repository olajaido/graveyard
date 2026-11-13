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
# Amendment 4.1: npm package whose entry point is not JavaScript; installed only.
PASS_INSTALL_ONLY = "pass_install_only"
FAIL_INSTALL = "fail_install"
FAIL_IMPORT = "fail_import"
TIMEOUT = "timeout"
RESULTS = (PASS, PASS_INSTALL_ONLY, FAIL_INSTALL, FAIL_IMPORT, TIMEOUT)
PASSING = (PASS, PASS_INSTALL_ONLY)

# Printed by the container once the install step has succeeded.
IMPORT_MARKER = "GRAVEYARD_PHASE=import"
# Printed by the container when a refinement of Amendment 4 applied.
REFINEMENT_PREFIX = "GRAVEYARD_REFINEMENT="
INSTALL_ONLY_MARKER = REFINEMENT_PREFIX + "install_only"
# Amendment 5.2: require/import failed only because the package needs a bundler.
BUNDLER_ONLY_MARKER = REFINEMENT_PREFIX + "bundler_only:"
BUNDLER_ONLY_CODES = ("ERR_UNSUPPORTED_DIR_IMPORT", "ERR_UNKNOWN_FILE_EXTENSION")
# Amendment 5.1: the plain npm install hit ERESOLVE and was retried.
ERESOLVE_REFINEMENT = "eresolve_retry"
# Container platform for every run (Amendment 5.3).
PLATFORM = "linux/amd64"

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
    if returncode != 0:
        return FAIL_IMPORT
    if INSTALL_ONLY_MARKER in output or BUNDLER_ONLY_MARKER in output:
        return PASS_INSTALL_ONLY
    return PASS


def refinements_applied(eco: str, output: str) -> list[str]:
    """Amendment 4 and 5 refinements that applied to one check, for the detail column."""
    found: list[str] = []
    for line in output.splitlines():
        line = line.strip()
        if line.startswith(REFINEMENT_PREFIX):
            value = line[len(REFINEMENT_PREFIX) :].strip()
            if value and value not in found:
                found.append(value)
    return found


def qt_toolkit_to_install(missing: list[str]) -> str | None:
    """The one GUI toolkit that may be installed for a failed import, else ``None``.

    ``missing`` holds top-level names of ModuleNotFoundError failures. Only when they
    are exactly one distinct name from the fixed list is that name returned; any
    other missing module means nothing is installed. Self-contained on purpose: its
    source is shipped into the container.
    """
    toolkits = ("PyQt5", "PyQt6", "PySide2", "PySide6")
    distinct = {m for m in missing if m}
    if len(distinct) == 1:
        only = next(iter(distinct))
        if only in toolkits:
            return only
    return None


def format_refinements(refinements: list[str]) -> str:
    return "refinements: " + (", ".join(refinements) if refinements else "none")


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
import importlib, importlib.metadata as md, os, subprocess, sys
APT = ["libgl1", "libglib2.0-0", "libxkbcommon0", "libdbus-1-3", "libfontconfig1"]
name = sys.argv[1]
dist = md.distribution(name)
names = derive_import_names(dist.read_text("top_level.txt"), dist.read_text("RECORD"))
print("import names:", names)
if not names:
    print("no importable top-level names found")
    sys.exit(1)

def try_imports():
    failures = []
    for n in names:
        try:
            importlib.import_module(n)
            print("imported", n)
        except BaseException as exc:
            print("FAILED", n, type(exc).__name__, exc)
            failures.append(exc)
    return failures

failures = try_imports()
missing = [
    (e.name or "").split(".")[0] for e in failures if isinstance(e, ModuleNotFoundError)
]
toolkit = qt_toolkit_to_install(missing) if failures else None
if toolkit:
    print("GRAVEYARD_REFINEMENT=qt_toolkit:" + toolkit)
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    steps = [
        ["apt-get", "update"],
        ["apt-get", "install", "-y", "--no-install-recommends"] + APT,
        [sys.executable, "-m", "pip", "install", "--no-cache-dir", toolkit],
    ]
    ready = True
    for step in steps:
        res = subprocess.run(step, capture_output=True, text=True)
        if res.returncode != 0:
            print("toolkit setup failed:", " ".join(step), (res.stderr or res.stdout)[-300:])
            ready = False
            break
    if ready:
        importlib.invalidate_caches()
        for mod in list(sys.modules):
            if any(mod == n or mod.startswith(n + ".") for n in names):
                del sys.modules[mod]
        failures = try_imports()
sys.exit(1 if failures else 0)
"""

PY_CODE = (
    inspect.getsource(derive_import_names) + inspect.getsource(qt_toolkit_to_install) + _PY_DRIVER
)

PY_SHELL = (
    'pip install --no-cache-dir "$1==$2" && echo ' + IMPORT_MARKER + ' && python -c "$3" "$1"'
)

# Amendment 4.1: does the installed package have a resolvable JavaScript entry point?
NODE_ENTRY_JS = """
const fs = require('fs');
const path = require('path');
const JS_EXT = new Set(['.js', '.cjs', '.mjs', '.json']);
function exportTargets(exp) {
  const out = [];
  const walk = (v) => {
    if (typeof v === 'string') out.push(v);
    else if (Array.isArray(v)) v.forEach(walk);
    else if (v && typeof v === 'object') {
      for (const [k, x] of Object.entries(v)) if (k !== 'types') walk(x);
    }
  };
  const subpaths = exp && typeof exp === 'object' && !Array.isArray(exp)
    && Object.keys(exp).some((k) => k.startsWith('.'));
  walk(subpaths ? exp['.'] : exp);
  return out;
}
function resolveFile(dir, rel, loose) {
  const base = path.join(dir, rel);
  const tries = loose
    ? [base, base + '.js', base + '.json', path.join(base, 'index.js'),
       path.join(base, 'index.json')]
    : [base];
  return tries.find((f) => fs.existsSync(f) && fs.statSync(f).isFile()) || null;
}
function hasJsEntry(dir, pkg) {
  let found;
  if (pkg.exports !== undefined && pkg.exports !== null) {
    found = exportTargets(pkg.exports).map((t) => resolveFile(dir, t, false));
  } else if (typeof pkg.main === 'string' && pkg.main) {
    found = [resolveFile(dir, pkg.main, true)];
  } else {
    found = [resolveFile(dir, 'index', true)];
  }
  return found.some((f) => f && JS_EXT.has(path.extname(f)));
}
"""

NODE_CODE = (
    NODE_ENTRY_JS
    + """
const name = process.argv[1];
const pkgDir = path.join(process.cwd(), 'node_modules', name);
const BUNDLER_CODES = ['ERR_UNSUPPORTED_DIR_IMPORT', 'ERR_UNKNOWN_FILE_EXTENSION'];
function fail(err) {
  const code = err && err.code;
  if (BUNDLER_CODES.includes(code)) {
    console.log('"""
    + BUNDLER_ONLY_MARKER
    + """' + code);
    process.exit(0);
  }
  console.log('FAILED', String(err));
  process.exit(1);
}
let entryOk = false;
try {
  entryOk = hasJsEntry(pkgDir, JSON.parse(fs.readFileSync(path.join(pkgDir, 'package.json'))));
} catch (e) {
  entryOk = false;
}
if (!entryOk) {
  console.log('"""
    + INSTALL_ONLY_MARKER
    + """: no resolvable .js/.cjs/.mjs/.json entry point');
  process.exit(0);
}
try {
  require(name);
  console.log('required', name);
} catch (e) {
  if (e && e.code === 'ERR_REQUIRE_ESM') {
    import(name).then(() => console.log('imported (esm)', name)).catch(fail);
  } else {
    fail(e);
  }
}
"""
)

# Amendment 5.1: install each declared peer dependency at its declared range.
NODE_PEERS_JS = """
const { spawnSync } = require('child_process');
const pkg = require(process.cwd() + '/node_modules/' + process.argv[1] + '/package.json');
for (const [dep, range] of Object.entries(pkg.peerDependencies || {})) {
  console.log('installing peer', dep + '@' + range);
  const res = spawnSync(
    'npm', ['install', '--legacy-peer-deps', '--no-audit', '--no-fund', dep + '@' + range],
    { stdio: 'inherit' });
  if (res.status !== 0) { console.log('peer install failed', dep); process.exit(1); }
}
"""

# $1 name, $2 version, $3 import code, $4 peers code. Plain install first; only an
# ERESOLVE failure triggers the --legacy-peer-deps retry plus explicit peer installs.
NODE_SHELL = (
    "mkdir /tmp/work && cd /tmp/work && "
    '{ npm install --no-audit --no-fund "$1@$2" > /tmp/npm.log 2>&1; rc=$?; cat /tmp/npm.log; '
    "if [ $rc -ne 0 ] && grep -q ERESOLVE /tmp/npm.log; then "
    "echo " + REFINEMENT_PREFIX + ERESOLVE_REFINEMENT + "; "
    'npm install --legacy-peer-deps --no-audit --no-fund "$1@$2" && node -e "$4" "$1"; '
    "rc=$?; fi; [ $rc -eq 0 ]; } && echo " + IMPORT_MARKER + ' && node -e "$3" "$1"'
)


def build_command(eco: str, name: str, version: str, container: str) -> list[str]:
    """The ``docker run`` argv for one check. No mounts, no env passthrough."""
    code, shell = (PY_CODE, PY_SHELL) if eco == "pypi" else (NODE_CODE, NODE_SHELL)
    extra = [NODE_PEERS_JS] if eco == "npm" else []
    return [
        "docker",
        "run",
        "--rm",
        "--platform",
        PLATFORM,
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
        *extra,
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
    detail = format_refinements(refinements_applied(eco, output)) + " | " + format_detail(output)
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
        print(f"{outcome.result:17} {eco}/{name}@{version}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(summarise(results))
    print(f"wrote {args.out}")
    return 0 if all(r in PASSING for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
