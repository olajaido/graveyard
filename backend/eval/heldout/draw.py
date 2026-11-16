"""Name syntax, draw order, quiet filter and the lazy Q walk (design 8.2; MV2-POP-4, MV2-SMP-1).

The order comes from SHA-256, not a random number generator, so it is the same on every
Python version. This module is pure: the caller supplies the seed, the draw date and the
registry lookup.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Iterable
from datetime import date

_VALID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_PEP503_RUN = re.compile(r"[-_.]+")
QUIET_YEARS = 2


def normalise_name(ecosystem: str, name: str) -> str | None:
    """Return the name in draw form, or None when it fails the syntax (a counted rejection).

    npm: the name as given, valid only if unscoped and lowercase-matching the pattern.
    PyPI: PEP 503 form (runs of `-_.` become `-`, lowercased), then the same pattern.
    """
    if ecosystem == "npm":
        candidate = name
    elif ecosystem == "pypi":
        candidate = _PEP503_RUN.sub("-", name).lower()
    else:
        return None
    return candidate if _VALID.fullmatch(candidate) else None


def draw_key(seed: str, stratum: str, ecosystem: str, name: str) -> str:
    """SHA-256 hex digest of `<seed>:<stratum>:<ecosystem>:<name>` as UTF-8."""
    return hashlib.sha256(f"{seed}:{stratum}:{ecosystem}:{name}".encode()).hexdigest()


def draw_order(seed: str, stratum: str, ecosystem: str, names: Iterable[str]) -> list[str]:
    """Names sorted ascending by `(draw_key, name)`; duplicates collapse to one entry."""
    return sorted(set(names), key=lambda n: (draw_key(seed, stratum, ecosystem, n), n))


def quiet_cutoff(draw_date: date) -> date:
    """Same month and day two years earlier; 29 February maps to 28 February."""
    year = draw_date.year - QUIET_YEARS
    if draw_date.month == 2 and draw_date.day == 29:
        return date(year, 2, 28)
    return date(year, draw_date.month, draw_date.day)


def is_quiet(released_on: date, draw_date: date) -> bool:
    """True when the release is strictly before the cutoff (more than 24 months before D)."""
    return released_on < quiet_cutoff(draw_date)


def select_q(
    ordered_names: Iterable[str],
    quiet_of: Callable[[str], bool],
    budget: int,
) -> list[str]:
    """Walk `ordered_names`, keep names where `quiet_of` is true, stop at `budget`.

    `quiet_of` is not called once the budget is reached.
    """
    chosen: list[str] = []
    if budget <= 0:
        return chosen
    for name in ordered_names:
        if quiet_of(name):
            chosen.append(name)
            if len(chosen) >= budget:
                break
    return chosen
