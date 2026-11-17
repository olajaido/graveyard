# /// script
# requires-python = "==3.12.*"
# dependencies = [
#   "httpx==0.28.1",
# ]
# ///
"""Draw the held-out Q stratum (design 8.5, 8.6; MV2-POP-4, MV2-SMP-1). MAINTAINER-RUN ONLY.

Usage:
    uv run scripts/heldout_draw.py --draw-date YYYY-MM-DD [--heldout-dir PATH] [--budget N]

For each ecosystem (npm, then PyPI) the script reads the pinned snapshot, normalises names,
removes the exclusion list, orders the rest with ``eval.heldout.draw.draw_order`` (stratum Q)
and walks that order lazily. Each name costs one registry request (npm ``time[<latest>]``;
PyPI latest release ``upload_time_iso_8601``). The walk stops at the budget (75) or at the end
of the list; a short list is recorded as ``short_of_budget``.

Outputs under ``<heldout-dir>``: ``exclusions.tsv``, ``draw/q-examined.tsv`` (appended one row
per examined name, so the walk resumes), ``draw/q-candidates.tsv`` and ``draw/draw.json``.

Failure rule: a 404 is ``unpublished``. Any other failure is retried 3 times with back-off,
then the script stops with a non-zero exit. A name is never skipped on a network error. Run
the same command again to resume from ``q-examined.tsv``.

Security: only ``registry.npmjs.org`` and ``pypi.org`` over https, no redirects, response size
cap. ``GITHUB_TOKEN`` is never read. No test, hook or agent runs this against the network.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from eval.heldout.draw import (  # noqa: E402
    draw_key,
    draw_order,
    is_quiet,
    normalise_name,
    select_q,
)
from eval.heldout.exclusions import (  # noqa: E402
    EXPECTED_ANCHORS,
    Exclusions,
    build_exclusions,
    exclusions_tsv,
    missing_labelled,
)
from eval.heldout.pins import verify_pins  # noqa: E402

SEED = "graveyard-mortality-v2-heldout-1"
BUDGET = 75
STRATUM = "Q"
ECOSYSTEMS = ("npm", "pypi")
ALLOWED_HOSTS = frozenset({"registry.npmjs.org", "pypi.org"})
MAX_RESPONSE_BYTES = 64 * 1024 * 1024  # counts decoded bytes (iter_bytes), npm and PyPI JSON
MIN_GAP = 0.5
RETRIES = 3
BACKOFF = (1.0, 2.0, 4.0)

SNAPSHOT_SOURCE = {"npm": "npm-high-impact", "pypi": "pypi-top-5000"}
EXAMINED_HEADER = (
    "ecosystem",
    "position",
    "name",
    "status",
    "latest_version",
    "released_at",
    "draw_key",
)
CANDIDATES_HEADER = (
    "ecosystem",
    "order",
    "name",
    "latest_version",
    "released_at",
    "draw_key",
)
STATUSES = ("quiet", "not_quiet", "unpublished", "no_release_date")

PLAN_PATH = "eval/LABELLING.md"
ANCHOR_DIR = "backend/core/scoring/tests/fixtures/anchors"
POOL_PATHS = ("eval/addition1/pools.tsv", "eval/addition2/pool.tsv", "eval/addition3/pool.tsv")
LABELLED_PATH = "eval/labelled_packages.csv"

Fetch = Callable[[str], tuple[int, bytes]]


class DrawStopped(Exception):
    """The draw cannot continue; the message is printed and the exit code is non-zero."""


class FetchError(Exception):
    """A transport failure or an unusable response (retried, then the draw stops)."""


@dataclass(frozen=True)
class Examined:
    ecosystem: str
    position: int
    name: str
    status: str
    latest_version: str
    released_at: str
    draw_key: str

    def fields(self) -> tuple[str, ...]:
        return (
            self.ecosystem,
            str(self.position),
            self.name,
            self.status,
            self.latest_version,
            self.released_at,
            self.draw_key,
        )


# --------------------------------------------------------------------------- #
# Registry documents (pure)
# --------------------------------------------------------------------------- #
def to_date(value: object) -> date | None:
    """UTC calendar date of an ISO timestamp, or None when it is not one."""
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    if moment.tzinfo is not None:
        moment = moment.astimezone(UTC)
    return moment.date()


def parse_npm(doc: object) -> tuple[str, date] | None:
    """`(latest, release date)` from the full npm document, or None."""
    if not isinstance(doc, dict):
        return None
    tags, times = doc.get("dist-tags"), doc.get("time")
    latest = tags.get("latest") if isinstance(tags, dict) else None
    if not isinstance(latest, str) or not latest or not isinstance(times, dict):
        return None
    released = to_date(times.get(latest))
    return None if released is None else (latest, released)


def parse_pypi(doc: object) -> tuple[str, date] | None:
    """`(latest, newest upload date of that release)` from the PyPI JSON, or None."""
    if not isinstance(doc, dict):
        return None
    info = doc.get("info")
    latest = info.get("version") if isinstance(info, dict) else None
    if not isinstance(latest, str) or not latest:
        return None
    releases = doc.get("releases")
    files = releases.get(latest) if isinstance(releases, dict) else None
    if not isinstance(files, list):
        files = doc.get("urls")
    dates = [
        d
        for f in (files if isinstance(files, list) else [])
        if isinstance(f, dict)
        for d in [to_date(f.get("upload_time_iso_8601"))]
        if d is not None
    ]
    return (latest, max(dates)) if dates else None


def registry_url(ecosystem: str, name: str) -> str:
    if ecosystem == "npm":
        return f"https://registry.npmjs.org/{quote(name, safe='')}"
    return f"https://pypi.org/pypi/{quote(name, safe='')}/json"


def classify(
    ecosystem: str,
    position: int,
    name: str,
    key: str,
    found: tuple[str, date] | None,
    draw_date: date,
) -> Examined:
    """Build the examined row for a published name (`found` None means no version or date)."""
    if found is None:
        return Examined(ecosystem, position, name, "no_release_date", "", "", key)
    version, released = found
    status = "quiet" if is_quiet(released, draw_date) else "not_quiet"
    return Examined(ecosystem, position, name, status, version, released.isoformat(), key)


# --------------------------------------------------------------------------- #
# Population (pure)
# --------------------------------------------------------------------------- #
def snapshot_names(ecosystem: str, data: bytes) -> list[str]:
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise DrawStopped(f"{ecosystem} snapshot is not valid JSON") from exc
    if ecosystem == "npm" and isinstance(doc, list) and all(isinstance(n, str) for n in doc):
        return list(doc)
    rows = doc.get("rows") if isinstance(doc, dict) else None
    if ecosystem == "pypi" and isinstance(rows, list):
        projects = [r.get("project") if isinstance(r, dict) else None for r in rows]
        if all(isinstance(p, str) for p in projects):
            return [p for p in projects if isinstance(p, str)]
    raise DrawStopped(f"{ecosystem} snapshot has an unexpected shape")


def prepare_order(
    ecosystem: str, names: list[str], excluded: frozenset[str], seed: str
) -> tuple[list[str], dict[str, int]]:
    """Draw order of the remaining names and the registry-free counts (whole snapshot)."""
    scoped = sum(1 for n in names if ecosystem == "npm" and n.startswith("@"))
    valid: set[str] = set()
    rejected = 0
    for raw in names:
        if ecosystem == "npm" and raw.startswith("@"):
            continue
        norm = normalise_name(ecosystem, raw)
        if norm is None:
            rejected += 1
        else:
            valid.add(norm)
    removed = valid & excluded
    ordered = draw_order(seed, STRATUM, ecosystem, valid - removed)
    counts = {
        "snapshot_size": len(names),
        "scoped": scoped,
        "syntax_rejected": rejected,
        "excluded": len(removed),
    }
    return ordered, counts


def walk(
    ecosystem: str,
    ordered: list[str],
    lookup: Callable[[int, str], Examined],
    budget: int,
) -> tuple[list[Examined], list[Examined]]:
    """Lazy walk via `select_q`; returns `(examined, selected)` in draw order."""
    examined: list[Examined] = []

    def quiet_of(name: str) -> bool:
        row = lookup(len(examined) + 1, name)
        examined.append(row)
        return row.status == "quiet"

    select_q(ordered, quiet_of, budget)
    return examined, [r for r in examined if r.status == "quiet"]


def tsv(header: tuple[str, ...], rows: list[tuple[str, ...]]) -> str:
    lines = ["\t".join(header)] + ["\t".join(r) for r in rows]
    return "\n".join(lines) + "\n"


def render_candidates(selected: Mapping[str, list[Examined]]) -> str:
    rows: list[tuple[str, ...]] = []
    for eco in ECOSYSTEMS:
        for order, r in enumerate(selected.get(eco, []), start=1):
            rows.append((eco, str(order), r.name, r.latest_version, r.released_at, r.draw_key))
    return tsv(CANDIDATES_HEADER, rows)


def parse_examined(text: str) -> list[Examined]:
    lines = text.split("\n")
    if text and not text.endswith("\n"):
        raise DrawStopped("q-examined.tsv ends without a newline (partial write); fix by hand")
    lines = [ln for ln in lines if ln]
    if not lines or tuple(lines[0].split("\t")) != EXAMINED_HEADER:
        raise DrawStopped("q-examined.tsv has a wrong header")
    out: list[Examined] = []
    for number, line in enumerate(lines[1:], start=2):
        cols = line.split("\t")
        if len(cols) != len(EXAMINED_HEADER) or not cols[1].isdigit() or cols[3] not in STATUSES:
            raise DrawStopped(f"q-examined.tsv line {number} is malformed")
        out.append(Examined(cols[0], int(cols[1]), *cols[2:]))
    return out


def replay_candidates(
    examined_text: str,
    exclusions_text: str,
    snapshots: Mapping[str, list[str]],
    seed: str,
    draw_date: date,
    budget: int,
) -> str:
    """Offline replay: rebuild `q-candidates.tsv` from `q-examined.tsv` (no registry call)."""
    table = {(r.ecosystem, r.name): r for r in parse_examined(examined_text)}
    excluded: dict[str, set[str]] = {eco: set() for eco in ECOSYSTEMS}
    for line in exclusions_text.splitlines()[1:]:
        cols = line.split("\t")
        if len(cols) >= 2 and cols[0] in excluded:
            excluded[cols[0]].add(cols[1])
    selected: dict[str, list[Examined]] = {}
    for eco in ECOSYSTEMS:
        ordered, _ = prepare_order(eco, snapshots[eco], frozenset(excluded[eco]), seed)

        def lookup(position: int, name: str, eco: str = eco) -> Examined:
            row = table.get((eco, name))
            if row is None:
                raise DrawStopped(f"replay: {eco}/{name} is not in q-examined.tsv")
            released = to_date(row.released_at)
            if released is not None:
                quiet = is_quiet(released, draw_date)
                if (row.status == "quiet") != quiet:
                    raise DrawStopped(f"replay: {eco}/{name} status disagrees with the draw date")
            return row

        selected[eco] = walk(eco, ordered, lookup, budget)[1]
    return render_candidates(selected)


# --------------------------------------------------------------------------- #
# Network (guarded, retried, rate-limited)
# --------------------------------------------------------------------------- #
def make_http_fetch(client: httpx.Client) -> Fetch:
    def fetch(url: str) -> tuple[int, bytes]:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS or parsed.port:
            raise FetchError(f"refusing to fetch {url}: not an allow-listed https host")
        chunks: list[bytes] = []
        total = 0
        try:
            with client.stream("GET", url, follow_redirects=False) as resp:
                if resp.status_code != 200:
                    return resp.status_code, b""
                for chunk in resp.iter_bytes():
                    total += len(chunk)
                    if total > MAX_RESPONSE_BYTES:
                        raise FetchError(f"response from {url} is over the size cap")
                    chunks.append(chunk)
        except httpx.HTTPError as exc:
            raise FetchError(f"{type(exc).__name__} requesting {url}") from exc
        return 200, b"".join(chunks)

    return fetch


class Registry:
    """Looks up one name: rate gap per host, 3 retries with back-off, 404 is unpublished."""

    def __init__(
        self,
        fetch: Fetch,
        sleep: Callable[[float], None],
        clock: Callable[[], float],
        draw_date: date,
        seed: str,
    ) -> None:
        self._fetch = fetch
        self._sleep = sleep
        self._clock = clock
        self._draw_date = draw_date
        self._seed = seed
        self._last: dict[str, float] = {}

    def _wait(self, url: str) -> None:
        host = urlparse(url).hostname or ""
        last = self._last.get(host)
        if last is not None:
            gap = MIN_GAP - (self._clock() - last)
            if gap > 0:
                self._sleep(gap)
        self._last[host] = self._clock()

    def _get(self, ecosystem: str, name: str) -> object | None:
        """Parsed JSON, or None for a 404. Raises DrawStopped after the retries."""
        url = registry_url(ecosystem, name)
        problem = ""
        for attempt in range(RETRIES + 1):
            if attempt:
                self._sleep(BACKOFF[attempt - 1])
            self._wait(url)
            try:
                status, body = self._fetch(url)
                if status == 404:
                    return None
                if status != 200:
                    problem = f"HTTP {status}"
                    continue
                parsed: object = json.loads(body.decode("utf-8"))
                return parsed
            except (FetchError, OSError) as exc:
                problem = str(exc) or type(exc).__name__
            except (UnicodeDecodeError, ValueError, RecursionError):
                problem = "invalid JSON"
        raise DrawStopped(
            f"{ecosystem}/{name}: {problem} after {RETRIES} retries; stopping, "
            "run again to resume (nothing is skipped)"
        )

    def examine(self, ecosystem: str, position: int, name: str) -> Examined:
        key = draw_key(self._seed, STRATUM, ecosystem, name)
        doc = self._get(ecosystem, name)
        if doc is None:
            return Examined(ecosystem, position, name, "unpublished", "", "", key)
        parse = parse_npm if ecosystem == "npm" else parse_pypi
        return classify(ecosystem, position, name, key, parse(doc), self._draw_date)


# --------------------------------------------------------------------------- #
# Files
# --------------------------------------------------------------------------- #
def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise DrawStopped(f"cannot read {path}: {type(exc).__name__}") from exc


def load_exclusions(root: Path) -> Exclusions:
    anchors = {p.name: read_text(p) for p in sorted((root / ANCHOR_DIR).glob("*.json"))}
    if len(anchors) != EXPECTED_ANCHORS:
        raise DrawStopped(f"found {len(anchors)} anchor files, expected {EXPECTED_ANCHORS}")
    pools = {p: read_text(root / p) for p in POOL_PATHS}
    try:
        exclusions = build_exclusions(read_text(root / PLAN_PATH), anchors, pools)
        missed = missing_labelled(exclusions, read_text(root / LABELLED_PATH))
    except ValueError as exc:
        raise DrawStopped(f"exclusions: {exc}") from exc
    if missed:
        listing = ", ".join(f"{e}/{n}" for e, n in missed)
        raise DrawStopped(f"labelled packages missing from the exclusion list: {listing}")
    return exclusions


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def load_snapshots(snapshot_dir: Path) -> tuple[dict[str, list[str]], dict[str, Any]]:
    try:
        pins = json.loads(read_text(snapshot_dir / "pins.json"))
    except ValueError as exc:
        raise DrawStopped("snapshot/pins.json is not valid JSON") from exc
    sources = pins.get("sources") if isinstance(pins, dict) else None
    if not isinstance(sources, dict):
        raise DrawStopped("snapshot/pins.json has no `sources`")
    files: dict[str, bytes] = {}
    for entry in sources.values():
        name = entry.get("file") if isinstance(entry, dict) else None
        if isinstance(name, str) and "/" not in name and (snapshot_dir / name).is_file():
            files[name] = (snapshot_dir / name).read_bytes()
    problems = verify_pins(pins, files)
    if problems:
        raise DrawStopped("snapshot pins do not verify: " + "; ".join(problems))
    names: dict[str, list[str]] = {}
    recorded: dict[str, Any] = {}
    for eco in ECOSYSTEMS:
        entry = sources.get(SNAPSHOT_SOURCE[eco])
        if not isinstance(entry, dict) or entry.get("file") not in files:
            raise DrawStopped(f"snapshot/pins.json has no usable {SNAPSHOT_SOURCE[eco]} source")
        names[eco] = snapshot_names(eco, files[entry["file"]])
        keep = ("file", "trimmed_sha256", "downloaded_sha256", "commit_sha", "version")
        recorded[SNAPSHOT_SOURCE[eco]] = {k: entry[k] for k in keep if k in entry}
    return names, recorded


class ExaminedLog:
    """`q-examined.tsv`: loaded for resume, appended one flushed row at a time."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.rows: dict[str, list[Examined]] = {eco: [] for eco in ECOSYSTEMS}
        if path.exists():
            for row in parse_examined(read_text(path)):
                if row.ecosystem not in self.rows:
                    raise DrawStopped(f"q-examined.tsv has unknown ecosystem {row.ecosystem}")
                self.rows[row.ecosystem].append(row)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\t".join(EXAMINED_HEADER) + "\n", encoding="utf-8")

    def append(self, row: Examined) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write("\t".join(row.fields()) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self.rows[row.ecosystem].append(row)


def build_lookup(
    ecosystem: str,
    log: ExaminedLog,
    registry: Registry,
    seed: str,
    draw_date: date,
) -> Callable[[int, str], Examined]:
    existing = list(log.rows[ecosystem])

    def lookup(position: int, name: str) -> Examined:
        if position <= len(existing):
            row = existing[position - 1]
            key = draw_key(seed, STRATUM, ecosystem, name)
            if (row.position, row.name, row.draw_key) != (position, name, key):
                raise DrawStopped(
                    f"q-examined.tsv row {position} for {ecosystem} does not match the draw "
                    "order (different seed, snapshot or exclusions?)"
                )
            released = to_date(row.released_at)
            if released is not None and (row.status == "quiet") != is_quiet(released, draw_date):
                raise DrawStopped("q-examined.tsv was written with a different --draw-date")
            return row
        row = registry.examine(ecosystem, position, name)
        log.append(row)
        return row

    return lookup


def parse_draw_date(text: str, today: date) -> date:
    try:
        value = date.fromisoformat(text)
    except ValueError as exc:
        raise DrawStopped(f"--draw-date {text!r} is not YYYY-MM-DD") from exc
    if value > today:
        raise DrawStopped(f"--draw-date {text} is in the future")
    return value


def run_draw(
    heldout_dir: Path,
    root: Path,
    draw_date: date,
    budget: int,
    seed: str,
    registry: Registry,
) -> None:
    draw_dir = heldout_dir / "draw"
    if (draw_dir / "draw.json").exists():
        raise DrawStopped(f"{draw_dir / 'draw.json'} already exists; it is not overwritten")
    exclusions = load_exclusions(root)
    ex_text = exclusions_tsv(exclusions)
    ex_path = heldout_dir / "exclusions.tsv"
    if ex_path.exists() and read_text(ex_path) != ex_text:
        raise DrawStopped(f"{ex_path} differs from the rebuilt exclusion list; not overwritten")
    write_atomic(ex_path, ex_text)
    if exclusions.rejected:
        print(f"note: {len(exclusions.rejected)} excluded name(s) fail the draw syntax")
    snapshots, pins = load_snapshots(heldout_dir / "snapshot")
    log = ExaminedLog(draw_dir / "q-examined.tsv")
    selected: dict[str, list[Examined]] = {}
    counts: dict[str, dict[str, Any]] = {}
    for eco in ECOSYSTEMS:
        excluded = frozenset(n for e, n in exclusions.keys() if e == eco)  # noqa: SIM118
        ordered, base = prepare_order(eco, snapshots[eco], excluded, seed)
        lookup = build_lookup(eco, log, registry, seed, draw_date)
        examined, chosen = walk(eco, ordered, lookup, budget)
        selected[eco] = chosen
        tally = {s: sum(1 for r in examined if r.status == s) for s in STATUSES}
        counts[eco] = {
            **base,
            "examined": len(examined),
            "unpublished": tally["unpublished"],
            "no_release_date": tally["no_release_date"],
            "not_quiet": tally["not_quiet"],
            "selected": len(chosen),
            "short_of_budget": len(chosen) < budget,
        }
    write_atomic(draw_dir / "q-candidates.tsv", render_candidates(selected))
    queries = heldout_dir / "f" / "queries.tsv"
    queries_sha = hashlib.sha256(queries.read_bytes()).hexdigest() if queries.is_file() else None
    doc = {
        "seed": seed,
        "draw_date": draw_date.isoformat(),
        "q_budget_per_ecosystem": budget,
        "pins": pins,
        "queries_sha256": queries_sha,
        "counts": counts,
    }
    write_atomic(draw_dir / "draw.json", json.dumps(doc, indent=2, sort_keys=True) + "\n")


def main(
    argv: list[str] | None = None,
    fetch: Fetch | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    today: date | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--draw-date", required=True, help="YYYY-MM-DD, not in the future")
    parser.add_argument("--heldout-dir", type=Path, default=REPO_ROOT / "eval" / "heldout")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--budget", type=int, default=BUDGET)
    parser.add_argument("--seed", default=SEED)
    args = parser.parse_args(argv)
    try:
        draw_date = parse_draw_date(args.draw_date, today or datetime.now(UTC).date())
        if args.budget <= 0:
            raise DrawStopped("--budget must be positive")
        with contextlib.ExitStack() as stack:
            if fetch is None:
                contact = os.environ.get("GRAVEYARD_CONTACT", "")
                agent = "graveyard-heldout-draw" + (f" ({contact})" if contact else "")
                client = stack.enter_context(
                    httpx.Client(
                        timeout=30.0, follow_redirects=False, headers={"User-Agent": agent}
                    )
                )
                fetch = make_http_fetch(client)
            registry = Registry(fetch, sleep, clock, draw_date, args.seed)
            run_draw(args.heldout_dir, args.repo_root, draw_date, args.budget, args.seed, registry)
    except DrawStopped as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"draw written to {args.heldout_dir / 'draw'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
