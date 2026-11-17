"""Batch release rules of the held-out draw (design 10.1; MV2-SMP-3 to 5).

Pure: the caller reads the files and passes values in. Batch layout: Q releases 25 candidates per
ecosystem in draw order; F releases up to 20 in the single pool order. `can_release` returns the
reason that blocks the next release, or `None`. The F stopping rule counts F-stratum effective
finished-healthy rows only (decision 1 of design 16.1).

Review removals come from `review/decisions.tsv` rows with action `remove` (10.1 amendment); the
caller passes them as a collection of keys, with the `keep_manual` keys beside them.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from eval.labels import LabelRow

Key = tuple[str, str]
Stratum = Literal["Q", "F"]

Q_PER_ECOSYSTEM_BATCH: Final = 25
F_BATCH_SIZE: Final = 20
F_EFFECTIVE_TARGET: Final = 20
F_RELEASE_CAP: Final = 120
FINISHED_HEALTHY: Final = "finished-healthy"
PASSING_RESULTS: Final = frozenset({"pass", "pass_install_only"})

STOP_TARGET: Final = "F stopping rule fired: 20 effective finished-healthy F rows"
STOP_CAP: Final = "F stopping rule fired: 120 F candidates released"
STOP_EXHAUSTED: Final = "F stopping rule fired: the F pool is exhausted"


def next_q_batch(candidates: Iterable[Key], released: Collection[Key]) -> tuple[Key, ...]:
    """Next Q batch: per ecosystem, the first 25 unreleased candidates in draw order.

    The result is grouped by ecosystem (sorted), each group in draw order.
    """
    taken = set(released)
    per_eco: dict[str, list[Key]] = {}
    for key in candidates:
        if key in taken:
            continue
        group = per_eco.setdefault(key[0], [])
        if len(group) < Q_PER_ECOSYSTEM_BATCH and key not in group:
            group.append(key)
    return tuple(key for eco in sorted(per_eco) for key in per_eco[eco])


def next_f_batch(
    pool: Iterable[Key],
    released: Collection[Key],
    *,
    f_released: Collection[Key] | None = None,
) -> tuple[Key, ...]:
    """Next F batch: up to 20 unreleased pool keys in pool order, never past 120 F releases.

    `released` holds every released key (all strata) and is what excludes keys. `f_released`
    holds only the released F keys and is what the 120 cap counts. When it is `None`, the cap
    counts `released`, which matches callers that release F keys only.
    """
    taken = set(released)
    cap_count = len(taken) if f_released is None else len(set(f_released))
    room = min(F_BATCH_SIZE, F_RELEASE_CAP - cap_count)
    batch: list[Key] = []
    for key in pool:
        if len(batch) >= room:
            break
        if key not in taken and key not in batch:
            batch.append(key)
    return tuple(batch)


def effective_finished_healthy(
    rows: Iterable[LabelRow],
    still_works: Mapping[Key, str],
    *,
    kept_manual: Collection[Key] = frozenset(),
    removed: Collection[Key] = frozenset(),
) -> int:
    """Count `reviewed=true` finished-healthy rows with a passing check or a hand check.

    `rows` are the F-stratum rows (see `f_effective_count`). A row passes when its still-works
    result is `pass` or `pass_install_only`, or its key has a `keep_manual` decision. A key
    recorded as removed never counts.
    """
    return sum(
        1
        for row in rows
        if row.label == FINISHED_HEALTHY
        and row.reviewed
        and row.key not in removed
        and (still_works.get(row.key) in PASSING_RESULTS or row.key in kept_manual)
    )


def f_effective_count(
    rows: Iterable[LabelRow],
    f_keys: Collection[Key],
    still_works: Mapping[Key, str],
    *,
    kept_manual: Collection[Key] = frozenset(),
    removed: Collection[Key] = frozenset(),
) -> int:
    """`effective_finished_healthy` over rows whose key is an F candidate; Q rows are ignored."""
    return effective_finished_healthy(
        (r for r in rows if r.key in f_keys),
        still_works,
        kept_manual=kept_manual,
        removed=removed,
    )


def f_stop_reason(effective: int, f_released: int, pool_remaining: int) -> str | None:
    """The F stopping rule: the first condition that holds, or `None` to go on.

    `f_released` counts every released F candidate, including any removed at review.
    """
    if effective >= F_EFFECTIVE_TARGET:
        return STOP_TARGET
    if f_released >= F_RELEASE_CAP:
        return STOP_CAP
    if pool_remaining <= 0:
        return STOP_EXHAUSTED
    return None


@dataclass(frozen=True)
class ReleaseState:
    """Everything `can_release` reads, for the batch about to be released."""

    stratum: Stratum
    previous_batch: Sequence[Key]
    labelled: Sequence[LabelRow]
    no_label: Collection[Key]
    removed: Collection[Key]
    kept_manual: Collection[Key]
    still_works: Mapping[Key, str]
    staging_data_rows: int
    f_keys: Collection[Key]
    f_released: int
    f_pool_remaining: int


def can_release(state: ReleaseState) -> str | None:
    """`None` when the next batch may be released, else the reason of the first blocking rule."""
    by_key = {row.key: row for row in state.labelled}

    # Rule 1: every candidate of the previous batch has a CSV row, a no-label line or a removal.
    unlabelled = [
        key
        for key in state.previous_batch
        if key not in by_key and key not in state.no_label and key not in state.removed
    ]
    if unlabelled:
        return f"rule 1: {len(unlabelled)} candidate(s) of the previous batch have no label: " + (
            ", ".join(f"{e}/{n}" for e, n in unlabelled[:5])
        )

    # Rule 2: every remaining row of the previous batch is reviewed; finished-healthy rows have
    # a still-works result or a hand check.
    for key in state.previous_batch:
        row = by_key.get(key)
        if row is None or key in state.removed:
            continue
        if not row.reviewed:
            return f"rule 2: {key[0]}/{key[1]} is not reviewed"
        if (
            row.label == FINISHED_HEALTHY
            and key not in state.still_works
            and key not in state.kept_manual
        ):
            return f"rule 2: {key[0]}/{key[1]} has no still-works result"

    # Rule 3: the staging file holds only the header.
    if state.staging_data_rows != 0:
        return f"rule 3: staging holds {state.staging_data_rows} row(s)"

    # Rule 4: for an F batch, the stopping rule has not fired.
    if state.stratum == "F":
        effective = f_effective_count(
            state.labelled,
            state.f_keys,
            state.still_works,
            kept_manual=state.kept_manual,
            removed=state.removed,
        )
        stop = f_stop_reason(effective, state.f_released, state.f_pool_remaining)
        if stop is not None:
            return f"rule 4: {stop}"
    return None
