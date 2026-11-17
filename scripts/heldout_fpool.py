# /// script
# requires-python = "==3.12.*"
# dependencies = [
#   "packageurl-python==0.17.6",
# ]
# ///
"""Held-out F pool: size calibration and code search (design 9.2; MV2-SMP-2). MAINTAINER-RUN ONLY.

Usage:
    uv run scripts/heldout_fpool.py calibrate [--heldout-dir PATH]
    uv run scripts/heldout_fpool.py search    [--heldout-dir PATH]

    uv run scripts/heldout_fpool.py map       [--heldout-dir PATH]
    uv run scripts/heldout_fpool.py build     [--heldout-dir PATH]

Subcommands are registered in ``COMMANDS``.

``calibrate`` runs one query per size band (phrase ``feature-complete``, filename ``README.md``),
reads the byte size of up to 5 hits per band from the contents API and writes
``f/raw/calibration.tsv``. Any hit outside its band (or a band with no hit to check) is a
failure: the script exits non-zero and the bands need a requirements amendment.

``search`` refuses to run until ``calibration.tsv`` records a pass. It then runs each cell of
``eval.heldout.fpool.build_grid()`` as the argument list (no shell)::

    gh search code "<phrase>" size:<band> --filename <file> --limit 100 --json repository,path,url

writes the unique repositories to ``f/raw/repos_<id>.txt`` and then one line to
``f/raw/query-log.tsv`` (zero-result cells included; ``saturated`` is true at 100 hits). A failing
call is retried 3 times with back-off, then the script stops with a non-zero exit. A cell is
never skipped; run again to resume from the log. Calls to code search are 7 s apart.

Auth: ``gh`` uses its own login (``gh auth login``). This script never reads ``GITHUB_TOKEN`` or
any other environment variable. No test or hook runs this against the network.

``map`` (design 9.3) reads the complete ``f/raw/query-log.tsv`` and ``f/raw/repos_<id>.txt``. For
each unique repository it forms candidate package names (repo name, its PEP 503 form, the name
without a ``python-`` or ``py`` prefix), fetches the registry metadata (npm latest document, PyPI
JSON) through an injectable fetch, and keeps a package only when a GitHub URL in the metadata
parses (``core.purl.normalise_repo_url``) to the same repository under ``repo_key``. A URL for
``foo/bar-baz`` never matches ``foo/bar``. Scoped and syntactically invalid names are skipped and
counted. Output: ``f/raw/mapped.tsv`` and ``f/raw/map-summary.json``. Not resumable: a failed
lookup stops the run (after 3 retries) and nothing is written.

``build`` (design 9.4) is offline: ``mapped.tsv``, ``exclusions.tsv``, ``draw/q-candidates.tsv`` and
the seed in ``draw/draw.json`` give ``draw/f-pool.tsv`` and ``draw/strata.tsv`` (Q rows, then F
rows). It then merges one new key, ``f_counts``, into ``draw.json``; every other field is left
as written by ``heldout_draw.py``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from core.purl import normalise_repo_url, repo_key  # noqa: E402
from eval.heldout.draw import normalise_name  # noqa: E402
from eval.heldout.fpool import (  # noqa: E402
    BANDS,
    GridRow,
    MappedRow,
    build_grid,
    build_pool,
    pool_tsv,
)
from eval.heldout.strata import StratumRow, serialise_strata  # noqa: E402

LIMIT = 100
GAP_SECONDS = 7.0
RETRIES = 3
BACKOFF = (10.0, 20.0, 40.0)
SAMPLES_PER_BAND = 5
CALIBRATION_PHRASE = "feature-complete"
CALIBRATION_FILENAME = "README.md"
TIMEOUT_SECONDS = 120

CALIBRATION_HEADER = ("band", "repo", "path", "size_bytes", "in_band")
LOG_HEADER = (
    "id",
    "phrase",
    "filename",
    "band",
    "run_date",
    "file_hits",
    "unique_repos",
    "limit",
    "saturated",
    "status",
)
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

MAP_GAP_SECONDS = 0.5
MAX_METADATA_BYTES = 25 * 1024 * 1024
ALLOWED_HOSTS = frozenset({"registry.npmjs.org", "pypi.org"})
ECOSYSTEMS = ("npm", "pypi")
MAPPED_HEADER = ("query_id", "repo", "ecosystem", "name", "version")
_PEP503_RUN = re.compile(r"[-_.]+")

# A runner takes an argument list (never a shell string) and returns (exit code, stdout).
Runner = Callable[[list[str]], tuple[int, str]]
Sleep = Callable[[float], None]
Hit = tuple[str, str]  # (owner/repo, path)
# A fetch takes an https URL and returns (HTTP status, body); OSError on a transport failure.
Fetch = Callable[[str], tuple[int, bytes]]


class SearchStopped(Exception):
    """The run cannot continue; the message is printed and the exit code is non-zero."""


# --------------------------------------------------------------------------- #
# gh calls
# --------------------------------------------------------------------------- #
def subprocess_runner(args: list[str]) -> tuple[int, str]:
    """Run `gh` with an argument list and no shell."""
    try:
        done = subprocess.run(  # noqa: S603
            args, capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, type(exc).__name__
    return done.returncode, done.stdout


def search_args(phrase: str, filename: str, band: str) -> list[str]:
    """The `gh search code` argument list for one cell (size in bytes, in the query text)."""
    return [
        "gh",
        "search",
        "code",
        f'"{phrase}"',
        f"size:{band}",
        "--filename",
        filename,
        "--limit",
        str(LIMIT),
        "--json",
        "repository,path,url",
    ]


def contents_args(repo: str, path: str) -> list[str]:
    return ["gh", "api", f"repos/{repo}/contents/{quote(path, safe='/')}"]


def parse_hits(stdout: str) -> list[Hit]:
    """`(owner/repo, path)` per hit from the `--json` output; ValueError when unusable."""
    doc = json.loads(stdout)
    if not isinstance(doc, list):
        raise ValueError("search output is not a list")
    hits: list[Hit] = []
    for item in doc:
        repository = item.get("repository") if isinstance(item, dict) else None
        path = item.get("path") if isinstance(item, dict) else None
        repo = None
        if isinstance(repository, dict):
            repo = repository.get("nameWithOwner") or repository.get("fullName")
        if not isinstance(repo, str) or not REPO_RE.match(repo) or not isinstance(path, str):
            raise ValueError("search hit has no usable repository or path")
        hits.append((repo, path))
    return hits


def parse_size(stdout: str) -> int:
    doc = json.loads(stdout)
    size = doc.get("size") if isinstance(doc, dict) else None
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise ValueError("contents response has no integer size")
    return size


def with_retries[T](
    label: str,
    runner: Runner,
    args: list[str],
    parse: Callable[[str], T],
    sleep: Sleep,
) -> T:
    """Run and parse; on failure retry 3 times with back-off, then raise SearchStopped."""
    problem = ""
    for attempt in range(RETRIES + 1):
        if attempt:
            sleep(BACKOFF[attempt - 1])
        code, out = runner(args)
        if code != 0:
            problem = f"gh exited {code}"
            continue
        try:
            return parse(out)
        except (ValueError, RecursionError):
            problem = "unusable response"
    raise SearchStopped(
        f"{label}: {problem} after {RETRIES} retries; stopping, run again to resume "
        "(nothing is skipped)"
    )


# --------------------------------------------------------------------------- #
# calibrate
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CalibrationRow:
    band: str
    repo: str
    path: str
    size: int | None  # None: the band returned no hit to check
    in_band: bool

    def fields(self) -> tuple[str, ...]:
        size = "" if self.size is None else str(self.size)
        return (
            self.band,
            self.repo or "-",
            self.path or "-",
            size,
            "true" if self.in_band else "false",
        )


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def calibration_text(rows: Sequence[CalibrationRow]) -> str:
    lines = ["\t".join(CALIBRATION_HEADER)] + ["\t".join(r.fields()) for r in rows]
    return "\n".join(lines) + "\n"


def calibrate(raw_dir: Path, runner: Runner, sleep: Sleep) -> list[CalibrationRow]:
    """Sample hits per band, check byte sizes, write `calibration.tsv`. Returns the rows."""
    rows: list[CalibrationRow] = []
    for index, band in enumerate(BANDS):
        if index:
            sleep(GAP_SECONDS)
        label = f"calibration band {band.label}"
        hits = with_retries(
            label,
            runner,
            search_args(CALIBRATION_PHRASE, CALIBRATION_FILENAME, band.label),
            parse_hits,
            sleep,
        )
        if not hits:
            rows.append(CalibrationRow(band.label, "", "", None, False))
            continue
        for repo, path in hits[:SAMPLES_PER_BAND]:
            size = with_retries(
                f"{label} {repo}/{path}", runner, contents_args(repo, path), parse_size, sleep
            )
            rows.append(CalibrationRow(band.label, repo, path, size, band.contains(size)))
    write_atomic(raw_dir / "calibration.tsv", calibration_text(rows))
    return rows


def calibration_passed(path: Path) -> bool:
    """True only when the file has the header, every band, and every row is in band."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return False
    if not lines or tuple(lines[0].split("\t")) != CALIBRATION_HEADER:
        return False
    seen: set[str] = set()
    for line in lines[1:]:
        cols = line.split("\t")
        if len(cols) != len(CALIBRATION_HEADER) or cols[4] != "true" or not cols[3].isdigit():
            return False
        seen.add(cols[0])
    return seen == {b.label for b in BANDS}


def cmd_calibrate(
    args: argparse.Namespace, runner: Runner, sleep: Sleep, today: str, fetch: Fetch
) -> int:
    raw_dir = args.heldout_dir / "f" / "raw"
    rows = calibrate(raw_dir, runner, sleep)
    bad = [r for r in rows if not r.in_band]
    if bad:
        for r in bad:
            what = "no hit to check" if r.size is None else f"{r.repo}/{r.path} is {r.size} bytes"
            print(f"calibration FAILED: band {r.band}: {what}", file=sys.stderr)
        print(
            "the bands need a requirements amendment before any query runs",
            file=sys.stderr,
        )
        return 1
    print(f"calibration passed ({len(rows)} sampled hits); wrote {raw_dir / 'calibration.tsv'}")
    return 0


# --------------------------------------------------------------------------- #
# search
# --------------------------------------------------------------------------- #
def log_line(cell: GridRow, run_date: str, hits: Sequence[Hit]) -> str:
    repos = {repo for repo, _ in hits}
    cols = (
        str(cell.id),
        cell.phrase,
        cell.filename,
        cell.band,
        run_date,
        str(len(hits)),
        str(len(repos)),
        str(LIMIT),
        "true" if len(hits) >= LIMIT else "false",
        "ok",
    )
    return "\t".join(cols) + "\n"


def load_log(path: Path, grid: Sequence[GridRow]) -> int:
    """Number of completed cells (a prefix of the grid); creates the log when missing."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\t".join(LOG_HEADER) + "\n", encoding="utf-8")
        return 0
    text = path.read_text(encoding="utf-8")
    if text and not text.endswith("\n"):
        raise SearchStopped("query-log.tsv ends without a newline (partial write); fix by hand")
    lines = text.splitlines()
    if not lines or tuple(lines[0].split("\t")) != LOG_HEADER:
        raise SearchStopped("query-log.tsv has a wrong header")
    body = lines[1:]
    if len(body) > len(grid):
        raise SearchStopped("query-log.tsv has more rows than the grid")
    for cell, line in zip(grid, body, strict=False):
        cols = line.split("\t")
        if len(cols) != len(LOG_HEADER) or cols[:4] != [
            str(cell.id),
            cell.phrase,
            cell.filename,
            cell.band,
        ]:
            raise SearchStopped(f"query-log.tsv row for cell {cell.id} does not match the grid")
        if cols[9] != "ok":
            raise SearchStopped(f"query-log.tsv row for cell {cell.id} is not ok")
    return len(body)


def run_search(raw_dir: Path, runner: Runner, sleep: Sleep, run_date: str) -> tuple[int, int]:
    """Run the pending cells in grid order. Returns `(cells run now, cells already done)`."""
    if not calibration_passed(raw_dir / "calibration.tsv"):
        raise SearchStopped(
            "calibration.tsv does not record a pass; run `heldout_fpool.py calibrate` first"
        )
    grid = build_grid()
    log_path = raw_dir / "query-log.tsv"
    done = load_log(log_path, grid)
    ran = 0
    for cell in grid[done:]:
        if ran:
            sleep(GAP_SECONDS)
        hits = with_retries(
            f"cell {cell.id} ({cell.phrase!r}, {cell.filename}, {cell.band})",
            runner,
            search_args(cell.phrase, cell.filename, cell.band),
            parse_hits,
            sleep,
        )
        repos = sorted({repo for repo, _ in hits})
        write_atomic(raw_dir / f"repos_{cell.id}.txt", "".join(f"{r}\n" for r in repos))
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(log_line(cell, run_date, hits))
            handle.flush()
            os.fsync(handle.fileno())
        ran += 1
    return ran, done


def cmd_search(
    args: argparse.Namespace, runner: Runner, sleep: Sleep, today: str, fetch: Fetch
) -> int:
    raw_dir = args.heldout_dir / "f" / "raw"
    ran, done = run_search(raw_dir, runner, sleep, today)
    print(f"search complete: {ran} cells run now, {done} already done; log in {raw_dir}")
    return 0


# --------------------------------------------------------------------------- #
# map
# --------------------------------------------------------------------------- #
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


def urllib_fetch(url: str) -> tuple[int, bytes]:
    """Default fetch: https to the two registries only, no redirects, capped body."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS or parsed.port:
        raise OSError(f"refusing to fetch {url}: not an allow-listed https host")
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(url, headers={"Accept": "application/json"})  # noqa: S310
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as resp:  # noqa: S310
            body: bytes = resp.read(MAX_METADATA_BYTES + 1)
    except urllib.error.HTTPError as exc:
        return exc.code, b""
    if len(body) > MAX_METADATA_BYTES:
        raise OSError("response is over the size cap")
    return 200, body


def metadata_url(ecosystem: str, name: str) -> str:
    if ecosystem == "npm":
        return f"https://registry.npmjs.org/{quote(name, safe='')}/latest"
    return f"https://pypi.org/pypi/{quote(name, safe='')}/json"


def candidate_names(repo: str) -> list[str]:
    """Raw candidates from the repo name: itself, its PEP 503 form, and without a prefix."""
    base = repo.split("/", 1)[1]
    forms = [base, _PEP503_RUN.sub("-", base).lower()]
    for prefix in ("python-", "py"):  # the first that applies; "python-x" is not also "thon-x"
        if base.lower().startswith(prefix):
            stripped = base[len(prefix) :]
            forms.extend((stripped, _PEP503_RUN.sub("-", stripped).lower()))
            break
    return list(dict.fromkeys(forms))


def _as_url(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict) and isinstance(value.get("url"), str):
        return [value["url"]]
    return []


def metadata_urls_and_version(ecosystem: str, doc: object) -> tuple[list[str], str]:
    """The URL strings that may name the GitHub repository, and the latest version."""
    if not isinstance(doc, dict):
        return [], ""
    if ecosystem == "npm":
        version = doc.get("version")
        urls = [u for key in ("repository", "homepage", "bugs") for u in _as_url(doc.get(key))]
        return urls, version if isinstance(version, str) else ""
    info = doc.get("info")
    if not isinstance(info, dict):
        return [], ""
    urls = _as_url(info.get("home_page")) + _as_url(info.get("download_url"))
    project_urls = info.get("project_urls")
    if isinstance(project_urls, dict):
        urls.extend(v for v in project_urls.values() if isinstance(v, str))
    version = info.get("version")
    return urls, version if isinstance(version, str) else ""


def points_at(repo: str, urls: Iterable[str]) -> bool:
    """True when some URL parses to exactly `repo` (whole `owner/repo`, case-folded)."""
    wanted = normalise_repo_url(f"github.com/{repo}")
    if wanted is None:
        return False
    target = repo_key(wanted)
    for url in urls:
        parsed = normalise_repo_url(url)
        if parsed is not None and repo_key(parsed) == target:
            return True
    return False


def read_repos(raw_dir: Path) -> dict[str, int]:
    """Unique repositories (case-folded key) with the lowest query id that found them."""
    grid = build_grid()
    done = load_log(raw_dir / "query-log.tsv", grid)
    if done != len(grid):
        raise SearchStopped(
            f"query-log.tsv has {done} of {len(grid)} cells; run `search` to the end before `map`"
        )
    first: dict[str, tuple[int, str]] = {}
    for cell in grid:
        path = raw_dir / f"repos_{cell.id}.txt"
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            raise SearchStopped(f"cannot read {path.name}: {type(exc).__name__}") from exc
        for repo in lines:
            if repo and repo.lower() not in first:
                first[repo.lower()] = (cell.id, repo)
    return {repo: qid for qid, repo in sorted(first.values())}


def run_map(raw_dir: Path, fetch: Fetch, sleep: Sleep) -> tuple[list[MappedRow], dict[str, int]]:
    repos = read_repos(raw_dir)
    counts = {
        "repositories": len(repos),
        "repositories_unusable": 0,
        "skipped_scoped": 0,
        "skipped_invalid": 0,
        "lookups": 0,
        "unpublished": 0,
    }
    cache: dict[tuple[str, str], tuple[list[str], str] | None] = {}
    requests = 0

    def lookup(eco: str, name: str) -> tuple[list[str], str] | None:
        nonlocal requests
        if (eco, name) in cache:
            return cache[(eco, name)]
        url = metadata_url(eco, name)
        problem = ""
        for attempt in range(RETRIES + 1):
            if attempt:
                sleep(BACKOFF[attempt - 1])
            elif requests:
                sleep(MAP_GAP_SECONDS)
            requests += 1
            try:
                status, body = fetch(url)
                if status == 404:
                    cache[(eco, name)] = None
                    return None
                if status != 200:
                    problem = f"HTTP {status}"
                    continue
                parsed = metadata_urls_and_version(eco, json.loads(body.decode("utf-8")))
            except OSError as exc:
                problem = str(exc) or type(exc).__name__
                continue
            except (UnicodeDecodeError, ValueError, RecursionError):
                problem = "invalid JSON"
                continue
            cache[(eco, name)] = parsed
            return parsed
        raise SearchStopped(
            f"{eco}/{name}: {problem} after {RETRIES} retries; stopping, run again "
            "(nothing was written)"
        )

    rows: dict[tuple[str, str], MappedRow] = {}
    for repo, query_id in repos.items():
        if normalise_repo_url(f"github.com/{repo}") is None:
            counts["repositories_unusable"] += 1
            continue
        for eco in ECOSYSTEMS:
            for raw_name in candidate_names(repo):
                name = normalise_name(eco, raw_name)
                if name is None:
                    counts["skipped_scoped" if raw_name.startswith("@") else "skipped_invalid"] += 1
                    continue
                found = lookup(eco, name)
                counts["lookups"] = requests
                if found is None:
                    counts["unpublished"] += 1
                    continue
                urls, version = found
                if version and points_at(repo, urls):
                    rows.setdefault((eco, name), MappedRow(query_id, repo, eco, name, version))
    counts["lookups"] = requests
    ordered = sorted(rows.values(), key=lambda r: (r.query_id, r.repo.lower(), r.ecosystem, r.name))
    return ordered, counts


def mapped_text(rows: Iterable[MappedRow]) -> str:
    lines = ["\t".join(MAPPED_HEADER)]
    lines.extend(f"{r.query_id}\t{r.repo}\t{r.ecosystem}\t{r.name}\t{r.version}" for r in rows)
    return "\n".join(lines) + "\n"


def cmd_map(
    args: argparse.Namespace, runner: Runner, sleep: Sleep, today: str, fetch: Fetch
) -> int:
    raw_dir = args.heldout_dir / "f" / "raw"
    rows, counts = run_map(raw_dir, fetch, sleep)
    write_atomic(raw_dir / "mapped.tsv", mapped_text(rows))
    summary = {**counts, "mapped_packages": len(rows)}
    write_atomic(raw_dir / "map-summary.json", json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(
        f"map complete: {len(rows)} packages from {counts['repositories']} repositories; "
        f"skipped {counts['skipped_scoped']} scoped, {counts['skipped_invalid']} invalid names"
    )
    return 0


# --------------------------------------------------------------------------- #
# build
# --------------------------------------------------------------------------- #
def _table(path: Path, header: Sequence[str]) -> list[list[str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SearchStopped(f"cannot read {path}: {type(exc).__name__}") from exc
    lines = text.splitlines()
    if not lines or tuple(lines[0].split("\t")) != tuple(header):
        raise SearchStopped(f"{path.name} has a wrong header")
    rows = [line.split("\t") for line in lines[1:] if line]
    if any(len(r) != len(header) for r in rows):
        raise SearchStopped(f"{path.name} has a malformed row")
    return rows


def _log_counts(raw_dir: Path) -> dict[str, int]:
    grid = build_grid()
    done = load_log(raw_dir / "query-log.tsv", grid)
    if done != len(grid):
        raise SearchStopped(f"query-log.tsv has {done} of {len(grid)} cells")
    lines = (raw_dir / "query-log.tsv").read_text(encoding="utf-8").splitlines()[1:]
    cols = [line.split("\t") for line in lines]
    return {
        "grid_size": len(grid),
        "cells_run": len(cols),
        "cells_zero_hits": sum(1 for c in cols if c[5] == "0"),
        "cells_saturated": sum(1 for c in cols if c[8] == "true"),
        "total_file_hits": sum(int(c[5]) for c in cols),
    }


def cmd_build(
    args: argparse.Namespace, runner: Runner, sleep: Sleep, today: str, fetch: Fetch
) -> int:
    root: Path = args.heldout_dir
    raw_dir, draw_dir = root / "f" / "raw", root / "draw"
    draw_path = draw_dir / "draw.json"
    try:
        doc = json.loads(draw_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SearchStopped(f"cannot read {draw_path}: {type(exc).__name__}") from exc
    seed = doc.get("seed") if isinstance(doc, dict) else None
    if not isinstance(seed, str) or not seed:
        raise SearchStopped("draw.json has no seed")
    mapped = [
        MappedRow(int(r[0]), r[1], r[2], r[3], r[4])
        for r in _table(raw_dir / "mapped.tsv", MAPPED_HEADER)
        if r[0].isdigit()
    ]
    exclusions = [
        (r[0], r[1])
        for r in _table(
            root / "exclusions.tsv", ("ecosystem", "name", "source_file", "source_kind")
        )
    ]
    q_rows = _table(
        draw_dir / "q-candidates.tsv",
        ("ecosystem", "order", "name", "latest_version", "released_at", "draw_key"),
    )
    pool = build_pool(mapped, exclusions, [(r[0], r[2]) for r in q_rows], seed)
    version_of = {(m.ecosystem, m.name): m.version for m in mapped}
    strata = [StratumRow(r[0], r[2], "Q", int(r[1]), r[3]) for r in q_rows]
    strata.extend(
        StratumRow(p.ecosystem, p.name, "F", p.order, version_of[(p.ecosystem, p.name)])
        for p in pool
    )
    try:
        strata_text = serialise_strata(strata)
    except ValueError as exc:
        raise SearchStopped(f"strata.tsv: {exc}") from exc

    log_counts = _log_counts(raw_dir)
    repos = read_repos(raw_dir)
    summary_path = raw_dir / "map-summary.json"
    try:
        map_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SearchStopped(f"cannot read {summary_path}: {type(exc).__name__}") from exc
    f_counts = {
        **log_counts,
        "unique_repositories": len(repos),
        "mapped_packages": len({(m.ecosystem, m.name) for m in mapped}),
        "skipped_scoped": map_summary.get("skipped_scoped", 0),
        "skipped_invalid": map_summary.get("skipped_invalid", 0),
        "pool_size": len(pool),
    }
    write_atomic(draw_dir / "f-pool.tsv", pool_tsv(pool))
    write_atomic(draw_dir / "strata.tsv", strata_text)
    merged = {**doc, "f_counts": f_counts}  # only adds one key; no Q field is touched
    write_atomic(draw_path, json.dumps(merged, indent=2, sort_keys=True) + "\n")
    print(f"build complete: pool of {len(pool)}; wrote f-pool.tsv, strata.tsv, draw.json f_counts")
    return 0


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
Command = Callable[[argparse.Namespace, Runner, Sleep, str, Fetch], int]
COMMANDS: dict[str, Command] = {
    "calibrate": cmd_calibrate,
    "search": cmd_search,
    "map": cmd_map,
    "build": cmd_build,
}


def main(
    argv: list[str] | None = None,
    runner: Runner = subprocess_runner,
    sleep: Sleep = time.sleep,
    today: str | None = None,
    fetch: Fetch = urllib_fetch,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0] if __doc__ else "")
    parser.add_argument("--heldout-dir", type=Path, default=REPO_ROOT / "eval" / "heldout")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in COMMANDS:
        sub.add_parser(name)
    args = parser.parse_args(argv)
    run_date = today or datetime.now(UTC).date().isoformat()
    try:
        return COMMANDS[args.command](args, runner, sleep, run_date, fetch)
    except SearchStopped as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
