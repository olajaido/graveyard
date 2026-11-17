# /// script
# requires-python = "==3.12.*"
# dependencies = [
#   "pyyaml==6.0.3",
# ]
# ///
"""Release held-out batches and report progress (design 10.1; MV2-SMP-3 to 5, MV2-LAB-2).

Usage:
    uv run scripts/heldout_batch.py next   [--stratum Q|F] [--heldout-dir PATH] [--staging PATH]
    uv run scripts/heldout_batch.py status [--heldout-dir PATH] [--staging PATH]

``next`` releases the next batch only when ``eval.heldout.batches.can_release`` allows it. With no
``--stratum`` it releases Q batches until every Q candidate is released, then F batches. It fetches
the current registry latest version of each candidate, appends one line per ecosystem to
``draw/batch-log.tsv`` (``batch_id, stratum, ecosystem, order_range, triples, sha256,
release_date``; triples are ``ecosystem,name,version`` joined by ``;``; ``sha256`` is that of the
printed text) and prints ``ecosystem,name,version`` lines sorted by name on stdout, with no
stratum, rank or source. A blocked release prints the reason on stderr and exits 1; nothing is
written. If any version cannot be fetched nothing is written or printed.

``status`` prints counts: released, labelled, reviewed, effective F rows, the two floors, staging.

State files, under ``--heldout-dir`` (default ``eval/heldout``): ``draw/q-candidates.tsv``,
``draw/f-pool.tsv``, ``draw/batch-log.tsv``, ``draw/no-label.tsv``, ``labelled_packages.csv``,
``review/decisions.tsv`` (action ``remove`` or ``keep_manual``), ``review/still_works.tsv`` and
``gate.yaml`` (floors). The staging file defaults to ``<heldout-dir>/../staging/coroner_rows.csv``.
Missing review, no-label and staging files count as empty; a missing batch log is created.

Network: only https to ``registry.npmjs.org`` and ``pypi.org``, no redirects, response size cap.
No token is read. No test or hook runs this against the network.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from eval.gate import GateConfig, GateConfigError, load_gate_config  # noqa: E402
from eval.heldout.batches import (  # noqa: E402
    ReleaseState,
    can_release,
    effective_finished_healthy,
    f_effective_count,
    f_stop_reason,
    next_f_batch,
    next_q_batch,
)
from eval.heldout.coverage import CoverageError, parse_no_label  # noqa: E402
from eval.labels import LabelRow, LabelsError, parse_labels  # noqa: E402

Key = tuple[str, str]
Fetch = Callable[[str], tuple[int, bytes]]

ALLOWED_HOSTS = frozenset({"registry.npmjs.org", "pypi.org"})
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
TIMEOUT_SECONDS = 30
LOG_HEADER = (
    "batch_id",
    "stratum",
    "ecosystem",
    "order_range",
    "triples",
    "sha256",
    "release_date",
)
DECISIONS_HEADER = ("ecosystem", "name", "action", "reason")
STILL_WORKS_COLUMNS = ("ecosystem", "name", "version", "result")
Q_COLUMNS = ("ecosystem", "order", "name")
F_COLUMNS = ("order", "ecosystem", "name")
REMOVE = "remove"
KEEP_MANUAL = "keep_manual"


class BatchError(Exception):
    """A state file is unusable or a fetch failed; the message goes to stderr, exit 2."""


@dataclass(frozen=True)
class Candidate:
    ecosystem: str
    name: str
    order: int

    @property
    def key(self) -> Key:
        return (self.ecosystem, self.name)


@dataclass(frozen=True)
class LogLine:
    batch_id: str
    stratum: str
    ecosystem: str
    triples: tuple[tuple[str, str, str], ...]


# --------------------------------------------------------------------------- #
# Parsing (pure)
# --------------------------------------------------------------------------- #
def _rows(text: str, what: str) -> list[list[str]]:
    if "\r" in text:
        raise BatchError(f"{what}: CR not allowed, use LF line endings")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return [line.split("\t") for line in lines]


def _table(text: str, what: str, required: Sequence[str]) -> list[dict[str, str]]:
    """Rows of a TSV with a header that holds at least `required`, as dicts."""
    rows = _rows(text, what)
    if not rows or any(col not in rows[0] for col in required):
        raise BatchError(f"{what}: header must contain " + ", ".join(required))
    header = rows[0]
    out: list[dict[str, str]] = []
    for number, cells in enumerate(rows[1:], start=2):
        if len(cells) != len(header):
            raise BatchError(f"{what} line {number}: expected {len(header)} columns")
        out.append(dict(zip(header, cells, strict=True)))
    return out


def parse_candidates(text: str, what: str, required: Sequence[str]) -> tuple[Candidate, ...]:
    out: list[Candidate] = []
    for number, row in enumerate(_table(text, what, required), start=2):
        order = row["order"]
        if not (order.isascii() and order.isdigit()):
            raise BatchError(f"{what} line {number}: order {order!r} is not an integer")
        out.append(Candidate(row["ecosystem"], row["name"], int(order)))
    return tuple(out)


def parse_log(text: str) -> tuple[LogLine, ...]:
    """The batch log; a first line whose first cell is `batch_id` is the header."""
    out: list[LogLine] = []
    for number, cells in enumerate(_rows(text, "batch-log.tsv"), start=1):
        if number == 1 and cells[0] == LOG_HEADER[0]:
            continue
        if len(cells) != len(LOG_HEADER):
            raise BatchError(f"batch-log.tsv line {number}: expected {len(LOG_HEADER)} columns")
        triples: list[tuple[str, str, str]] = []
        for triple in cells[4].split(";"):
            parts = triple.strip().split(",")
            if len(parts) != 3 or not all(parts):
                raise BatchError(f"batch-log.tsv line {number}: malformed triple")
            triples.append((parts[0], parts[1], parts[2]))
        out.append(LogLine(cells[0], cells[1], cells[2], tuple(triples)))
    return tuple(out)


def parse_decisions(text: str) -> tuple[frozenset[Key], frozenset[Key]]:
    """`(removed, kept_manual)` keys from `review/decisions.tsv`."""
    rows = _rows(text, "decisions.tsv")
    if not rows or tuple(rows[0]) != DECISIONS_HEADER:
        raise BatchError("decisions.tsv: header must be " + "\t".join(DECISIONS_HEADER))
    removed: set[Key] = set()
    kept: set[Key] = set()
    for number, cells in enumerate(rows[1:], start=2):
        if len(cells) != len(DECISIONS_HEADER) or cells[2] not in (REMOVE, KEEP_MANUAL):
            raise BatchError(f"decisions.tsv line {number}: malformed row or unknown action")
        (removed if cells[2] == REMOVE else kept).add((cells[0], cells[1]))
    return frozenset(removed), frozenset(kept)


def parse_still_works(text: str) -> dict[tuple[str, str, str], str]:
    return {
        (r["ecosystem"], r["name"], r["version"]): r["result"]
        for r in _table(text, "still_works.tsv", STILL_WORKS_COLUMNS)
    }


def staging_data_rows(text: str) -> int:
    """Records after the header of the staging CSV (quoted newlines are one record)."""
    records = [r for r in csv.reader(io.StringIO(text, newline="")) if r]
    return max(len(records) - 1, 0)


def still_works_by_key(
    rows: Sequence[LabelRow], results: Mapping[tuple[str, str, str], str]
) -> dict[Key, str]:
    """Result per key, taken at the version the row is labelled with."""
    return {
        row.key: results[(row.ecosystem, row.name, row.version)]
        for row in rows
        if (row.ecosystem, row.name, row.version) in results
    }


def render_batch(triples: Sequence[tuple[str, str, str]]) -> str:
    """The printed text: `ecosystem,name,version`, sorted by name (then ecosystem)."""
    ordered = sorted(triples, key=lambda t: (t[1], t[0], t[2]))
    return "".join(f"{e},{n},{v}\n" for e, n, v in ordered)


def log_lines(
    batch_id: str,
    stratum: str,
    triples: Sequence[tuple[str, str, str]],
    orders: Mapping[Key, int],
    sha256: str,
    released_on: str,
) -> list[str]:
    """One log line per ecosystem of the batch."""
    lines: list[str] = []
    for eco in sorted({t[0] for t in triples}):
        mine = sorted((t for t in triples if t[0] == eco), key=lambda t: (t[1], t[2]))
        numbers = [orders[(t[0], t[1])] for t in mine]
        cells = (
            batch_id,
            stratum,
            eco,
            f"{min(numbers)}-{max(numbers)}",
            ";".join(",".join(t) for t in mine),
            sha256,
            released_on,
        )
        lines.append("\t".join(cells))
    return lines


# --------------------------------------------------------------------------- #
# Registry (guarded)
# --------------------------------------------------------------------------- #
def registry_url(ecosystem: str, name: str) -> str:
    if ecosystem == "npm":
        return f"https://registry.npmjs.org/{quote(name, safe='')}/latest"
    if ecosystem == "pypi":
        return f"https://pypi.org/pypi/{quote(name, safe='')}/json"
    raise BatchError(f"unknown ecosystem {ecosystem!r}")


def latest_version(ecosystem: str, doc: object) -> str | None:
    """Latest version from an npm `/latest` document or a PyPI JSON document."""
    if not isinstance(doc, dict):
        return None
    holder: object = doc.get("info") if ecosystem == "pypi" else doc
    version = holder.get("version") if isinstance(holder, dict) else None
    return version if isinstance(version, str) and version else None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def http_fetch(url: str) -> tuple[int, bytes]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS or parsed.port:
        raise BatchError(f"refusing to fetch {url}: not an allow-listed https host")
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(url, headers={"User-Agent": "graveyard-heldout-batch"})  # noqa: S310
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as resp:
            body: bytes = resp.read(MAX_RESPONSE_BYTES + 1)
            status: int = resp.status
    except urllib.error.HTTPError as exc:
        return exc.code, b""
    except (urllib.error.URLError, OSError) as exc:
        raise BatchError(f"{type(exc).__name__} requesting {url}") from exc
    if len(body) > MAX_RESPONSE_BYTES:
        raise BatchError(f"response from {url} is over the size cap")
    return status, body


def fetch_versions(keys: Sequence[Key], fetch: Fetch) -> list[tuple[str, str, str]]:
    """Latest version of every key, or `BatchError` (all or nothing)."""
    out: list[tuple[str, str, str]] = []
    for eco, name in keys:
        url = registry_url(eco, name)
        status, body = fetch(url)
        if status != 200:
            raise BatchError(f"{eco}/{name}: registry answered HTTP {status}")
        try:
            version = latest_version(eco, json.loads(body.decode("utf-8")))
        except (UnicodeDecodeError, ValueError, RecursionError):
            version = None
        if version is None:
            raise BatchError(f"{eco}/{name}: no latest version in the registry answer")
        out.append((eco, name, version))
    return out


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class State:
    q: tuple[Candidate, ...]
    pool: tuple[Candidate, ...]
    log: tuple[LogLine, ...]
    log_text: str
    no_label: frozenset[Key]
    rows: tuple[LabelRow, ...]
    removed: frozenset[Key]
    kept_manual: frozenset[Key]
    still_works: dict[Key, str]
    staging_rows: int
    gate: GateConfig | None

    @property
    def released(self) -> frozenset[Key]:
        return frozenset((e, n) for line in self.log for e, n, _ in line.triples)

    def released_in(self, stratum: str) -> frozenset[Key]:
        return frozenset(
            (e, n) for line in self.log if line.stratum == stratum for e, n, _ in line.triples
        )

    @property
    def f_keys(self) -> frozenset[Key]:
        return frozenset(c.key for c in self.pool)

    @property
    def previous_batch(self) -> tuple[Key, ...]:
        if not self.log:
            return ()
        last = self.log[-1].batch_id
        return tuple(
            (e, n) for line in self.log if line.batch_id == last for e, n, _ in line.triples
        )

    def f_effective(self) -> int:
        return f_effective_count(
            self.rows,
            self.f_keys,
            self.still_works,
            kept_manual=self.kept_manual,
            removed=self.removed,
        )

    def f_pool_remaining(self) -> int:
        return len(self.f_keys - self.released)


def _read(path: Path, *, required: bool) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        if required:
            raise BatchError(f"{path}: file is missing") from None
        return None
    except (OSError, UnicodeDecodeError) as exc:
        raise BatchError(f"cannot read {path}: {type(exc).__name__}") from exc


def load_state(heldout: Path, staging: Path) -> State:
    draw, review = heldout / "draw", heldout / "review"
    q = parse_candidates(
        _read(draw / "q-candidates.tsv", required=True) or "", "q-candidates.tsv", Q_COLUMNS
    )
    pool = parse_candidates(
        _read(draw / "f-pool.tsv", required=True) or "", "f-pool.tsv", F_COLUMNS
    )
    log_text = _read(draw / "batch-log.tsv", required=False) or ""
    no_label_text = _read(draw / "no-label.tsv", required=False)
    labels_text = _read(heldout / "labelled_packages.csv", required=False)
    decisions_text = _read(review / "decisions.tsv", required=False)
    still_text = _read(review / "still_works.tsv", required=False)
    staging_text = _read(staging, required=False)
    gate_text = _read(heldout / "gate.yaml", required=False)
    try:
        no_label = (
            frozenset(r.key for r in parse_no_label(no_label_text))
            if no_label_text
            else frozenset()
        )
        rows = parse_labels(labels_text) if labels_text else ()
        gate = load_gate_config(heldout / "gate.yaml") if gate_text is not None else None
    except (CoverageError, LabelsError, GateConfigError) as exc:
        raise BatchError(str(exc)) from exc
    removed, kept = (
        parse_decisions(decisions_text) if decisions_text else (frozenset(), frozenset())
    )
    results = parse_still_works(still_text) if still_text else {}
    return State(
        q=q,
        pool=pool,
        log=parse_log(log_text),
        log_text=log_text,
        no_label=no_label,
        rows=tuple(rows),
        removed=removed,
        kept_manual=kept,
        still_works=still_works_by_key(rows, results),
        staging_rows=staging_data_rows(staging_text) if staging_text else 0,
        gate=gate,
    )


def release_state(state: State, stratum: str) -> ReleaseState:
    return ReleaseState(
        stratum="F" if stratum == "F" else "Q",
        previous_batch=state.previous_batch,
        labelled=state.rows,
        no_label=state.no_label,
        removed=state.removed,
        kept_manual=state.kept_manual,
        still_works=state.still_works,
        staging_data_rows=state.staging_rows,
        f_keys=state.f_keys,
        f_released=len(state.released & state.f_keys),
        f_pool_remaining=state.f_pool_remaining(),
    )


def choose_stratum(state: State, wanted: str | None) -> str:
    if wanted:
        return wanted
    q_keys = [c.key for c in state.q]
    return "Q" if next_q_batch(q_keys, state.released) else "F"


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def cmd_next(
    heldout: Path, staging: Path, wanted: str | None, fetch: Fetch, today: date
) -> tuple[int, str]:
    """`(exit code, text for stdout)`. A blocked release returns 1 and a reason for stderr."""
    state = load_state(heldout, staging)
    stratum = choose_stratum(state, wanted)
    reason = can_release(release_state(state, stratum))
    if reason is not None:
        return 1, f"blocked: {reason}\n"
    if stratum == "Q":
        keys = next_q_batch([c.key for c in state.q], state.released)
        orders = {c.key: c.order for c in state.q}
    else:
        keys = next_f_batch(
            [c.key for c in state.pool], state.released, f_released=state.released_in("F")
        )
        orders = {c.key: c.order for c in state.pool}
    if not keys:
        return 1, f"blocked: no unreleased {stratum} candidates remain\n"
    triples = fetch_versions(keys, fetch)
    text = render_batch(triples)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    ids = {line.batch_id for line in state.log if line.stratum == stratum}
    batch_id = f"{stratum}{len(ids) + 1}"
    lines = log_lines(batch_id, stratum, triples, orders, digest, today.isoformat())
    old = state.log_text or "\t".join(LOG_HEADER) + "\n"
    if not old.endswith("\n"):
        old += "\n"
    write_atomic(heldout / "draw" / "batch-log.tsv", old + "\n".join(lines) + "\n")
    return 0, text


def cmd_status(heldout: Path, staging: Path) -> str:
    s = load_state(heldout, staging)
    f_keys = s.f_keys
    released_q, released_f = s.released_in("Q"), s.released_in("F")
    by_label = {r.key: r for r in s.rows}
    effective_all = effective_finished_healthy(
        s.rows, s.still_works, kept_manual=s.kept_manual, removed=s.removed
    )
    dead = sum(1 for r in s.rows if r.label == "dead" and r.reviewed)
    f_labelled = sum(1 for k in by_label if k in f_keys)
    f_eff = s.f_effective()
    stop = f_stop_reason(f_eff, len(s.released & f_keys), s.f_pool_remaining())
    min_dead = s.gate.min_reviewed_dead if s.gate else None
    min_fh = s.gate.min_reviewed_finished_healthy if s.gate else None

    def floor(value: int, minimum: int | None) -> str:
        return f"{value}" if minimum is None else f"{value}/{minimum}"

    return (
        "\n".join(
            [
                f"released: {len(s.released)} (Q {len(released_q)}, F {len(released_f)})",
                f"labelled: {len(s.rows)} rows (Q {len(s.rows) - f_labelled}, F {f_labelled}), "
                f"{len(s.no_label)} no label, {len(s.removed)} removed at review",
                f"reviewed: {sum(1 for r in s.rows if r.reviewed)} of {len(s.rows)} rows",
                f"effective F rows: {f_eff}/20; F released {len(s.released & f_keys)}/120; "
                f"pool remaining {s.f_pool_remaining()}",
                f"F stopping rule: {stop or 'not fired'}",
                f"floor reviewed dead rows: {floor(dead, min_dead)}",
                f"floor effective finished-healthy rows (pooled): {floor(effective_all, min_fh)}",
                f"staging empty: {'yes' if s.staging_rows == 0 else f'no ({s.staging_rows} rows)'}",
            ]
        )
        + "\n"
    )


def main(
    argv: list[str] | None = None,
    fetch: Fetch | None = None,
    today: date | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("next", "status"):
        p = sub.add_parser(name)
        p.add_argument("--heldout-dir", type=Path, default=REPO_ROOT / "eval" / "heldout")
        p.add_argument("--staging", type=Path, default=None)
        if name == "next":
            p.add_argument("--stratum", choices=("Q", "F"), default=None)
    args = parser.parse_args(argv)
    heldout: Path = args.heldout_dir
    staging: Path = args.staging or heldout.parent / "staging" / "coroner_rows.csv"
    try:
        if args.command == "status":
            sys.stdout.write(cmd_status(heldout, staging))
            return 0
        code, text = cmd_next(
            heldout,
            staging,
            args.stratum,
            fetch or http_fetch,
            today or datetime.now(UTC).date(),
        )
    except BatchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if code == 0:
        sys.stdout.write(text)
    else:
        sys.stderr.write(text)
    return code


if __name__ == "__main__":
    sys.exit(main())
