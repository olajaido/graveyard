"""Decision function of the moved-repository probe (MV2-SRC-2, D10, design 12.2).

Pure: no I/O. ``decide`` turns recorded measurements into ``FOLLOWS``, ``FAILS`` or
``INCONCLUSIVE``. Only the ``capture`` path decides; ``library`` measurements are accepted
and ignored here because the held-out fixtures come from the capture path.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Final, Literal

Path = Literal["capture", "library"]
Key = Literal["old", "current"]
Scalar = int | float | bool | str | None

#: Repository-keyed signals compared by the probe, in report order.
SIGNALS: Final[tuple[str, ...]] = (
    "s3",
    "s4",
    "s5",
    "s6_open",
    "s6_closed",
    "s8",
    "archived",
)

#: Source each signal comes from, used to name failing sources. S4 and S8 come from the
#: Scorecard lookup (deps.dev project document, else the Scorecard API); the rest from GitHub.
SOURCE_OF: Final[dict[str, str]] = {
    "s3": "github",
    "s4": "scorecard",
    "s5": "github",
    "s6_open": "github",
    "s6_closed": "github",
    "s8": "scorecard",
    "archived": "github",
}

#: Minimum number of measured, confirmed-moved subjects (design 12.2, step 2).
MIN_MOVED: Final[int] = 2


@dataclass(frozen=True)
class Measurement:
    """One lookup of one subject, keyed by ``(subject, path, key)``.

    ``moved`` is the confirmation result (REST 301 and a different current name); a subject
    that is not confirmed moved never takes part in the decision. Each signal is a scalar,
    or ``None`` when the lookup returned nothing for it.
    """

    subject: str
    path: Path
    key: Key
    moved: bool = True
    s3: Scalar = None
    s4: Scalar = None
    s5: Scalar = None
    s6_open: Scalar = None
    s6_closed: Scalar = None
    s8: Scalar = None
    archived: Scalar = None

    def value(self, signal: str) -> Scalar:
        return getattr(self, signal)  # type: ignore[no-any-return]


class Outcome(Enum):
    FOLLOWS = "FOLLOWS"
    FAILS = "FAILS"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class Failure:
    subject: str
    source: str
    signal: str


@dataclass(frozen=True)
class Verdict:
    outcome: Outcome
    #: Sorted, unique. Empty unless ``outcome`` is ``FAILS``.
    failures: tuple[Failure, ...] = ()
    #: Number of confirmed-moved subjects measured on the capture path.
    moved_subjects: int = 0

    @property
    def failing_sources(self) -> tuple[str, ...]:
        return tuple(sorted({f.source for f in self.failures}))

    @property
    def failing_signals(self) -> tuple[str, ...]:
        return tuple(sorted({f.signal for f in self.failures}, key=SIGNALS.index))


def _same_and_present(old: Scalar, current: Scalar) -> bool:
    # bool is an int subclass: compare types too so True never equals 1.
    return old is not None and current is not None and type(old) is type(current) and old == current


def decide(measurements: Iterable[Measurement]) -> Verdict:
    """Apply the table of design 12.2 to the capture-path measurements."""
    cells: dict[tuple[str, Key], Measurement] = {}
    for m in measurements:
        if m.path == "capture" and m.moved:
            cells[(m.subject, m.key)] = m
    subjects = sorted({s for s, _ in cells if (s, "old") in cells and (s, "current") in cells})
    if len(subjects) < MIN_MOVED:
        return Verdict(Outcome.INCONCLUSIVE, (), len(subjects))
    failures = sorted(
        {
            Failure(subject, SOURCE_OF[signal], signal)
            for subject in subjects
            for signal in SIGNALS
            if not _same_and_present(
                cells[(subject, "old")].value(signal), cells[(subject, "current")].value(signal)
            )
        },
        key=lambda f: (f.subject, SIGNALS.index(f.signal)),
    )
    if failures:
        return Verdict(Outcome.FAILS, tuple(failures), len(subjects))
    return Verdict(Outcome.FOLLOWS, (), len(subjects))
