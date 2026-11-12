"""Map install-check outcomes to a hook decision (KPW-MAP-1…7, design §7.4). Pure: no I/O.

``blocks`` is the one place that decides to block; ``decide`` builds the stderr block message or
the one-line stdout note. Everything dynamic passes ``sanitise``; text is built from fixed
templates and validated fields only.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING, Final

from cli.gate import matches
from cli.model import unverified_short
from cli.text import sanitise
from core.scoring.types import BaseState, ScoringResult

if TYPE_CHECKING:
    from cli.args import GateClass

__all__ = [
    "Checked",
    "Decision",
    "FileNote",
    "Failed",
    "HOOK_EXIT_TABLE",
    "HookExit",
    "Outcome",
    "TimedOut",
    "Unresolved",
    "blocks",
    "block_message",
    "decide",
    "note",
]

MAX_LINE: Final = 200
MAX_BLOCK_LINES: Final = 10
SHOWN_PER_KIND: Final = 2
DEFAULT_BUDGET_SECONDS: Final = 10.0
CHECK_LIMIT: Final = 20
NOTE_PREFIX: Final = "graveyard: "
CLOSING: Final = (
    "The install was not run. Choose a maintained alternative, or ask the user how to "
    "proceed; do not retry the install through another package manager."
)
REASON_UNRESOLVED: Final = "no latest version found"
REASON_FAILED: Final = "sources unavailable"


class HookExit(IntEnum):
    """The only two exit codes the hook ever returns (KPW-CMD-2)."""

    ALLOW = 0
    BLOCK = 2


_EXIT_DESCRIPTIONS: Final[dict[HookExit, str]] = {
    HookExit.ALLOW: "allow: nothing to check, nothing to block, or the check could not finish",
    HookExit.BLOCK: "block: a dead or cursed package is in the install command",
}

# One line per code, generated from ``HookExit`` (KPW-CMD-2); used by ``--help`` and the docs.
HOOK_EXIT_TABLE: Final[str] = "\n".join(
    f"{int(code)}  {_EXIT_DESCRIPTIONS[code]}" for code in HookExit
)


@dataclass(frozen=True)
class Checked:
    purl: str
    state: BaseState
    dead_reason: str | None
    cursed: bool
    gate_eligible: bool
    is_range: bool
    why: str
    unverified: tuple[str, ...] = ()


@dataclass(frozen=True)
class Unresolved:
    name: str


@dataclass(frozen=True)
class Failed:
    purl: str


@dataclass(frozen=True)
class TimedOut:
    name: str


type Outcome = Checked | Unresolved | Failed | TimedOut


@dataclass(frozen=True)
class FileNote:
    """A requirements-file fragment (KPW-REQ-7), already sanitised and cut by its producer."""

    text: str


@dataclass(frozen=True)
class Decision:
    exit: HookExit
    stdout: str
    stderr: str


_ALL_FAIL_ON: Final[frozenset[GateClass]] = frozenset({"dead", "cursed"})


def _gate_matches(o: Checked) -> bool:
    """Reuse ``cli.gate.matches``; it reads only ``base_state`` and ``cursed``."""
    scoring = ScoringResult(
        purl=o.purl,
        model_version="",
        mortality=None,
        confidence=0.0,
        base_state=o.state,
        dead_reason=None,
        cursed=o.cursed,
        wounded=False,
        exposure=1.0,
        exposure_assumed=True,
        priority=None,
        normalised_risks={},
        contributions={},
        services_affected=None,
    )
    return matches(scoring, _ALL_FAIL_ON)


def blocks(o: Outcome) -> bool:
    """KPW-MAP-2: the block rule for one outcome."""
    if not isinstance(o, Checked) or not o.gate_eligible:
        return False
    if o.is_range:
        return o.state is BaseState.DEAD and o.dead_reason == "declared"
    return _gate_matches(o)


def _clean(text: str) -> str:
    """``sanitise`` plus the Unicode line separators, so a value can never add a line, and
    defanged URL separators (``://``), so no output holds a clickable or fetchable URL
    (KPW-SEC-3)."""
    cleaned = sanitise(text).replace("\u2028", "\ufffd").replace("\u2029", "\ufffd")
    return cleaned.replace("://", ":\ufffd/")


def _cut(text: str, limit: int = MAX_LINE) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _unquote(text: str) -> str:
    """Decode the one escape a purl name carries: the scope ``@`` (``%40``)."""
    return text.replace("%40", "@")


def _split_purl(purl: str) -> tuple[str, str, str]:
    """``(ecosystem, name, version)`` from ``pkg:<eco>/<name>[@<version>]``; total."""
    rest = purl[4:] if purl.startswith("pkg:") else purl
    ecosystem, _, path = rest.partition("/")
    path = path.split("?", 1)[0].split("#", 1)[0]
    name, sep, version = path.rpartition("@")
    if not sep or not name:
        name, version = path, ""
    return ecosystem, _unquote(name), version


def _state_text(o: Checked) -> str:
    return f"{o.state.value} · Cursed" if o.cursed else o.state.value


def _block_line(o: Checked) -> str:
    ecosystem, name, version = _split_purl(o.purl)
    tail = " (range resolved to latest)" if o.is_range else ""
    return _cut(_clean(f"  {ecosystem} {name}@{version}: {_state_text(o)}: {o.why}{tail}"))


def block_message(blocking: Sequence[Checked]) -> str:
    """KPW-MAP-4: the stderr text for a non-empty list of blocking packages."""
    count = len(blocking)
    noun = "package" if count == 1 else "packages"
    lines = [f"graveyard: blocked: {count} dead or cursed {noun} in this install command"]
    lines.extend(_block_line(o) for o in blocking[:MAX_BLOCK_LINES])
    if count > MAX_BLOCK_LINES:
        lines.append(f"  … and {count - MAX_BLOCK_LINES} more")
    lines.append(CLOSING)
    return "\n".join(lines) + "\n"


def _shown(fragments: Sequence[str]) -> list[str]:
    """The first two fragments of a kind, then ``and N more`` for the rest."""
    shown = list(fragments[:SHOWN_PER_KIND])
    if len(fragments) > SHOWN_PER_KIND:
        shown.append(f"and {len(fragments) - SHOWN_PER_KIND} more")
    return shown


def _name_version(purl: str) -> tuple[str, str]:
    _, name, version = _split_purl(purl)
    return name, version


def _kind(outcomes: Sequence[Outcome], pick: Callable[[Outcome], str | None]) -> list[str]:
    return [text for o in outcomes if (text := pick(o)) is not None]


def _dead_or_cursed(o: Checked) -> bool:
    return o.state is BaseState.DEAD or o.cursed


def _unresolved_failed(o: Outcome) -> str | None:
    if isinstance(o, Unresolved):
        return f"could not check {_clean(o.name)} ({REASON_UNRESOLVED})"
    if isinstance(o, Failed):
        return f"could not check {_clean(o.purl)} ({REASON_FAILED})"
    return None


def _range_unchecked(o: Outcome) -> str | None:
    if isinstance(o, Checked) and o.is_range and not blocks(o) and _dead_or_cursed(o):
        name, version = _name_version(o.purl)
        return _clean(f"{name}: range not checked against {version} ({_state_text(o)})")
    return None


def _unverified(o: Outcome) -> str | None:
    if isinstance(o, Checked) and not o.is_range and not blocks(o) and _dead_or_cursed(o):
        name, version = _name_version(o.purl)
        what = unverified_short(o.unverified) if o.unverified else "no data"
        return _clean(f"{name}@{version} unverified ({what}), not gated")
    return None


def _packages(count: int) -> str:
    return f"{count} package" if count == 1 else f"{count} packages"


def note(
    outcomes: Sequence[Outcome],
    *,
    truncated: bool,
    files: Sequence[FileNote],
    total_targets: int,
    budget_seconds: float = DEFAULT_BUDGET_SECONDS,
) -> str:
    """KPW-MAP-5: the one-line stdout note, or ``""`` when no fragment applies.

    ``total_targets`` is the number of targets found before the check limit; the caller knows it.
    """
    fragments: list[str] = []
    timed_out = sum(1 for o in outcomes if isinstance(o, TimedOut))
    if timed_out:
        fragments.append(
            f"check timed out after {budget_seconds:g}s ({_packages(timed_out)} not checked)"
        )
    fragments.extend(_shown(_kind(outcomes, _unresolved_failed)))
    fragments.extend(_shown(_kind(outcomes, _range_unchecked)))
    fragments.extend(_shown(_kind(outcomes, _unverified)))
    fragments.extend(_shown([_clean(f.text) for f in files]))
    if truncated:
        fragments.append(f"checked the first {CHECK_LIMIT} of {_packages(total_targets)}")
    if not fragments:
        return ""
    return _cut(_clean(NOTE_PREFIX + "; ".join(fragments)))


def decide(
    outcomes: Sequence[Outcome],
    *,
    truncated: bool,
    files: Sequence[FileNote],
    total_targets: int,
    budget_seconds: float = DEFAULT_BUDGET_SECONDS,
) -> Decision:
    """KPW-MAP-1…5: exit 2 with a stderr message, or exit 0 with an optional one-line note."""
    blocking = [o for o in outcomes if isinstance(o, Checked) and blocks(o)]
    if blocking:
        return Decision(HookExit.BLOCK, "", block_message(blocking))
    text = note(
        outcomes,
        truncated=truncated,
        files=files,
        total_targets=total_targets,
        budget_seconds=budget_seconds,
    )
    return Decision(HookExit.ALLOW, text + "\n" if text else "", "")
