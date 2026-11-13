# /// script
# requires-python = "==3.12.*"
# dependencies = [
#   "httpx==0.28.1",
# ]
# ///
"""Capture the eval-harness fixtures (EV-CAP-1..7, EV-NOGH-1). MAINTAINER-RUN ONLY.

Usage:
    GITHUB_TOKEN=... GRAVEYARD_CONTACT=you@example.com \
        uv run scripts/capture_eval.py --as-of YYYY-MM-DD \
        [--only npm/ms pypi/six ...] [--skip-existing | --refetch-unavailable] \
        [--delay 1.0] \
        [--csv PATH] [--out-dir PATH]

Reads ``eval/labelled_packages.csv`` and writes
``eval/fixtures/<ecosystem>/<name>.json`` (atomically) for each
``(ecosystem, name, version)`` row, by reusing ``capture_anchors``. The fixture
format is the anchor format plus a top-level ``s1_parts`` object
(``registry_deprecated``, ``repo_archived``). ``resolved_version`` equals the
CSV version. A value that could not be obtained is ``null``, never 0. A scored
signal whose source was tried and failed also carries ``"unavailable": true``.

Behaviour:
    * ``--as-of`` is required, must not be in the future (UTC), and is written to
      every fixture.
    * ``--skip-existing`` skips rows whose fixture file already exists (resumable).
    * ``--refetch-unavailable`` re-captures (all sources, same ``--as-of``) only the
      packages whose existing fixture has a signal with ``"unavailable": true`` and
      overwrites those fixtures; every other fixture is left untouched.
    * A GitHub batch that fails after the per-request retries (HTTP 5xx or timeout)
      is split in half and each half retried, down to single repos; only a failing
      single repo is marked unavailable.
    * A package that fails is reported with a scrubbed message; the rest are
      still processed and the exit status is 1. Fixtures are never deleted.

Security:
    * ``GITHUB_TOKEN`` is read from the environment only and is sent solely to
      ``api.github.com``. It is never printed, logged, written, or placed in an
      error message (all error text goes through ``capture_anchors.scrub``).
    * Output is checked for the token and token-shaped strings before anything
      is written (``capture_anchors.write_fixture``).
    * Package names are validated before any URL is built; redirects are not
      followed; only the sibling's host allow-list is contacted; no user code is
      executed or installed.
    * Run by hand only: no test, hook or agent runs this script.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import capture_anchors  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV = REPO_ROOT / "eval" / "labelled_packages.csv"
DEFAULT_OUT_DIR = REPO_ROOT / "eval" / "fixtures"

ECOSYSTEMS = ("npm", "pypi")
MIN_DELAY = 0.5

_NAME = capture_anchors._PACKAGE_NAME
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+!-]*$")

Row = tuple[str, str, str]  # (ecosystem, name, version)


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def read_rows(csv_path: Path) -> list[Row]:
    """Read ``(ecosystem, name, version)`` rows, validating only what a URL needs.

    Raises ``ValueError`` (with the CSV line number) for an unknown ecosystem, a
    name that fails the package-name pattern, an empty or odd version, or a
    duplicate ``(ecosystem, name)``.
    """
    rows: list[Row] = []
    seen: set[tuple[str, str]] = set()
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for record in reader:
            line = reader.line_num
            eco = (record.get("ecosystem") or "").strip()
            name = (record.get("name") or "").strip()
            version = (record.get("version") or "").strip()
            if eco not in ECOSYSTEMS:
                raise ValueError(f"line {line}: unsupported ecosystem {eco!r}")
            if not _NAME.match(name):
                raise ValueError(f"line {line}: unexpected package name {name!r}")
            if not version or not _VERSION.match(version):
                raise ValueError(f"line {line}: empty or unexpected version {version!r}")
            if (eco, name) in seen:
                raise ValueError(f"line {line}: duplicate row for {eco}/{name}")
            seen.add((eco, name))
            rows.append((eco, name, version))
    return rows


def parse_only(values: list[str] | None) -> set[tuple[str, str]] | None:
    """Parse ``--only`` values of the form ``<ecosystem>/<name>``; None means all."""
    if not values:
        return None
    parsed: set[tuple[str, str]] = set()
    for value in values:
        eco, sep, name = value.partition("/")
        if not sep or eco not in ECOSYSTEMS or not _NAME.match(name):
            raise ValueError(f"--only expects npm/<name> or pypi/<name>, got {value!r}")
        parsed.add((eco, name))
    return parsed


def build_s1_parts(
    ecosystem: str,
    registry_part: dict[str, Any] | None,
    github_part: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """The two parts of S1 (EV-NOGH-1), both always present as signal dicts.

    ``registry_part`` is the copy of ``partial.signals["_s1_registry"]`` taken
    before ``assemble`` pops it; ``github_part`` is ``gh["_s1_github"]`` for the
    package's repo, or None when no repo was resolved.
    """
    if ecosystem == "pypi":
        registry = capture_anchors.missing("PyPI exposes no deprecation signal")
    elif registry_part is not None:
        registry = registry_part
    else:
        registry = capture_anchors.missing("registry deprecation flag unavailable")
    if github_part is not None:
        archived = github_part
    else:
        archived = capture_anchors.missing("no GitHub repo resolved")
    return {"registry_deprecated": registry, "repo_archived": archived}


def _batch_failed(signals: dict[str, dict[str, Any]]) -> bool:
    """True when these signals came from a GitHub batch that gave up after retries.

    Only retryable failures (HTTP 429/5xx, timeouts, network errors) end in
    "giving up after retries"; a 4xx or bad JSON is not worth splitting for.
    """
    return any(
        v.get("unavailable")
        and str(v.get("note", "")).startswith("GitHub batch failed:")
        and "giving up after retries" in str(v.get("note", ""))
        for v in signals.values()
    )


def fetch_github_bisect(
    http: Any, repos: list[tuple[str, str]], as_of: date
) -> dict[tuple[str, str], dict[str, dict[str, Any]]]:
    """``capture_github`` with split-and-retry for batches that fail after retries.

    Calls the existing batch function with ever smaller lists. A single-repo
    failure is the only thing that leaves that repo's signals unavailable.
    """
    out: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    size = capture_anchors.GITHUB_BATCH
    for start in range(0, len(repos), size):
        out.update(_fetch_split(http, repos[start : start + size], as_of))
    return out


def _fetch_split(
    http: Any, chunk: list[tuple[str, str]], as_of: date
) -> dict[tuple[str, str], dict[str, dict[str, Any]]]:
    result = capture_anchors.capture_github(http, chunk, as_of)
    if len(chunk) <= 1 or not any(_batch_failed(result[r]) for r in chunk):
        return result
    mid = len(chunk) // 2
    print(f"GitHub batch of {len(chunk)} failed; splitting into {mid} + {len(chunk) - mid}")
    result = _fetch_split(http, chunk[:mid], as_of)
    result.update(_fetch_split(http, chunk[mid:], as_of))
    return result


def unavailable_signals(fixture: dict[str, Any]) -> list[str]:
    """Names of signals (including ``s1_parts``) marked ``"unavailable": true``."""
    names: list[str] = []
    for group in ("signals", "s1_parts"):
        section = fixture.get(group)
        if isinstance(section, dict):
            names += [k for k, v in section.items() if isinstance(v, dict) and v.get("unavailable")]
    return names


def select_refetch(rows: list[Row], out_dir: Path) -> list[Row]:
    """Rows whose existing fixture has any unavailable signal. Missing or unreadable
    fixtures are not selected (use a normal capture for those)."""
    selected: list[Row] = []
    for eco, name, version in rows:
        path = out_dir / eco / f"{name}.json"
        try:
            fixture = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(fixture, dict) and unavailable_signals(fixture):
            selected.append((eco, name, version))
    return selected


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture eval-harness fixtures.")
    parser.add_argument("--as-of", required=True, metavar="YYYY-MM-DD", help="capture date (UTC)")
    parser.add_argument("--only", nargs="+", metavar="ECO/NAME", help="subset, e.g. npm/ms")
    parser.add_argument("--skip-existing", action="store_true", help="skip rows with a fixture")
    parser.add_argument(
        "--refetch-unavailable",
        action="store_true",
        help="re-capture only packages whose fixture has an unavailable signal",
    )
    parser.add_argument(
        "--delay", type=float, default=1.0, help="min seconds between requests per host"
    )
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)  # a missing --as-of exits 2 here

    try:
        as_of = date.fromisoformat(args.as_of)
    except ValueError:
        print("error: --as-of must be a date in YYYY-MM-DD form.", file=sys.stderr)
        return 2
    if as_of > datetime.now(UTC).date():
        print("error: --as-of must not be in the future (UTC).", file=sys.stderr)
        return 2
    if args.skip_existing and args.refetch_unavailable:
        print("error: --skip-existing and --refetch-unavailable conflict.", file=sys.stderr)
        return 2
    if args.delay < MIN_DELAY:
        print(f"error: --delay must be at least {MIN_DELAY} seconds.", file=sys.stderr)
        return 2

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        print(
            "error: GITHUB_TOKEN is not set. Export a token with public read access "
            "(no scopes needed) and re-run.",
            file=sys.stderr,
        )
        return 2
    contact = os.environ.get("GRAVEYARD_CONTACT", "").strip()
    if not contact:
        print(
            "error: GRAVEYARD_CONTACT is not set. Export a contact email or URL; "
            "it is included in the User-Agent so API operators can reach us.",
            file=sys.stderr,
        )
        return 2
    capture_anchors._TOKEN = token

    try:
        only = parse_only(args.only)
        rows = read_rows(args.csv)
    except (ValueError, OSError) as exc:
        print(f"error: {capture_anchors.scrub(str(exc))}", file=sys.stderr)
        return 2
    if only is not None:
        known = {(eco, name) for eco, name, _ in rows}
        unknown = sorted(only - known)
        if unknown:
            listed = ", ".join(f"{e}/{n}" for e, n in unknown)
            print(f"error: --only names not in the CSV: {listed}", file=sys.stderr)
            return 2
        rows = [r for r in rows if (r[0], r[1]) in only]

    out_dir: Path = args.out_dir
    todo: list[Row] = []
    if args.refetch_unavailable:
        rows = select_refetch(rows, out_dir)
        print(f"re-capturing {len(rows)} package(s) with unavailable signals:")
        for eco, name, _ in rows:
            print(f"  {eco}/{name}")
    for eco, name, version in rows:
        if args.skip_existing and (out_dir / eco / f"{name}.json").exists():
            print(f"[{eco}/{name}] skipped (fixture exists)")
            continue
        todo.append((eco, name, version))

    http = capture_anchors.Http(f"graveyard-eval-capture/1.0 (+{contact})", args.delay)
    failures = 0
    still_unavailable: list[str] = []
    try:
        captured: list[tuple[capture_anchors.Partial, dict[str, Any] | None]] = []
        for eco, name, version in todo:
            print(f"[{eco}/{name}@{version}] fetching registry, deps.dev, OSV, downloads...")
            try:
                partial = capture_anchors.capture_phase1(http, name, eco, version)
            except capture_anchors.FetchError as exc:
                failures += 1
                print(f"[{eco}/{name}] FAILED: {exc}", file=sys.stderr)
                continue
            # assemble() pops _s1_registry, so copy it first.
            captured.append((partial, partial.signals.get("_s1_registry")))

        repos = sorted({p.repo for p, _ in captured if p.repo})
        print(f"fetching GitHub data for {len(repos)} repos (batched)...")
        gh_data = fetch_github_bisect(http, repos, as_of) if repos else {}

        for partial, registry_part in captured:
            gh = gh_data.get(partial.repo) if partial.repo else None
            github_part = gh.get("_s1_github") if gh else None
            try:
                fixture = capture_anchors.assemble(partial, gh, as_of)
                fixture["s1_parts"] = build_s1_parts(partial.ecosystem, registry_part, github_part)
                path = capture_anchors.write_fixture(out_dir / partial.ecosystem, fixture)
            except capture_anchors.FetchError as exc:
                failures += 1
                print(f"[{partial.ecosystem}/{partial.package}] FAILED: {exc}", file=sys.stderr)
                continue
            signals = fixture["signals"]
            nulls = [k for k, v in signals.items() if v["value"] is None]
            unavailable = [k for k, v in signals.items() if v.get("unavailable")]
            if args.refetch_unavailable:
                for k in unavailable_signals(fixture):
                    still_unavailable.append(f"{partial.ecosystem}/{partial.package}: {k}")
            print(
                f"[{partial.ecosystem}/{partial.package}] wrote {path.name}; "
                f"null signals: {nulls or 'none'}; unavailable: {unavailable or 'none'}"
            )
    finally:
        http.close()
    if args.refetch_unavailable:
        if still_unavailable:
            print("still unavailable after re-capture:")
            for line in still_unavailable:
                print(f"  {line}")
        else:
            print("no signals still unavailable")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
