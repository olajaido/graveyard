"""The F pool: query grid and offline build (design 9.1, 9.4; MV2-SMP-2).

Pure: the caller supplies the mapped rows, the exclusion keys, the Q candidates and the seed.
The search and map phases (network) live in `scripts/heldout_fpool.py`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from eval.heldout.draw import draw_key

STRATUM = "F"
DEFAULT_OWNER_CAP = 3

PHRASES = (
    "feature-complete",
    "feature complete",
    "considered complete",
    "complete and stable",
    "stable and complete",
    "is feature complete",
    "considered feature complete",
    "no new features planned",
)
FILENAMES = ("README.md", "README.rst", "README", "README.txt", "README.markdown")


@dataclass(frozen=True)
class Band:
    """A file-size band in bytes: `low <= size <= high`; `high` None means unbounded."""

    label: str
    low: int
    high: int | None

    def contains(self, size: int) -> bool:
        return size >= self.low and (self.high is None or size <= self.high)


BANDS = (
    Band("<1000", 0, 999),
    Band("1000..2999", 1000, 2999),
    Band("3000..5999", 3000, 5999),
    Band("6000..11999", 6000, 11999),
    Band(">=12000", 12000, None),
)


@dataclass(frozen=True)
class GridRow:
    id: int
    phrase: str
    filename: str
    band: str


@dataclass(frozen=True)
class MappedRow:
    query_id: int
    repo: str  # "owner/repo"
    ecosystem: str
    name: str
    version: str = ""


@dataclass(frozen=True)
class PoolRow:
    order: int
    ecosystem: str
    name: str
    repo: str
    owner: str
    query_id: int
    draw_key: str


def build_grid() -> list[GridRow]:
    """The 200-cell product, ids 1..200 in phrase, filename, band order (stable)."""
    rows: list[GridRow] = []
    for phrase in PHRASES:
        for filename in FILENAMES:
            for band in BANDS:
                rows.append(GridRow(len(rows) + 1, phrase, filename, band.label))
    return rows


def grid_tsv(rows: Iterable[GridRow]) -> str:
    lines = ["id\tphrase\tfilename\tband"]
    lines.extend(f"{r.id}\t{r.phrase}\t{r.filename}\t{r.band}" for r in rows)
    return "\n".join(lines) + "\n"


def owner_of(repo: str) -> str:
    """Lower-cased GitHub owner of `owner/repo`."""
    return repo.split("/", 1)[0].lower()


def build_pool(
    mapped: Iterable[MappedRow],
    exclusions: Iterable[tuple[str, str]],
    q_candidates: Iterable[tuple[str, str]],
    seed: str,
    owner_cap: int = DEFAULT_OWNER_CAP,
) -> list[PoolRow]:
    """Dedupe, exclude, order by draw key (one order for both ecosystems), apply the owner cap."""
    removed = set(exclusions) | set(q_candidates)
    best: dict[tuple[str, str], MappedRow] = {}
    for row in mapped:
        key = (row.ecosystem, row.name)
        if key in removed:
            continue
        kept = best.get(key)
        if kept is None or row.query_id < kept.query_id:
            best[key] = row
    keyed = sorted(
        ((draw_key(seed, STRATUM, eco, name), eco, name) for eco, name in best),
    )
    per_owner: dict[str, int] = {}
    pool: list[PoolRow] = []
    for dkey, eco, name in keyed:
        row = best[(eco, name)]
        owner = owner_of(row.repo)
        if per_owner.get(owner, 0) >= owner_cap:
            continue
        per_owner[owner] = per_owner.get(owner, 0) + 1
        pool.append(PoolRow(len(pool) + 1, eco, name, row.repo, owner, row.query_id, dkey))
    return pool


def pool_tsv(rows: Iterable[PoolRow]) -> str:
    """The text of `draw/f-pool.tsv` (header, rows in order, LF)."""
    lines = ["order\tecosystem\tname\trepo\towner\tquery_id\tdraw_key"]
    lines.extend(
        f"{r.order}\t{r.ecosystem}\t{r.name}\t{r.repo}\t{r.owner}\t{r.query_id}\t{r.draw_key}"
        for r in rows
    )
    return "\n".join(lines) + "\n"
