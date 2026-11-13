"""Hypothesis strategies for the eval package."""

from __future__ import annotations

from hypothesis import strategies as st

from eval.labels import ALLOWED_EVIDENCE_KINDS, Label, LabelRow
from eval.outcome import Outcome, Predicted

_NAME = st.from_regex(r"[a-z0-9][a-z0-9._-]{0,15}", fullmatch=True)
_VERSION = st.from_regex(r"[0-9][0-9A-Za-z.+_-]{0,11}", fullmatch=True)
_HOST = st.from_regex(r"[a-z][a-z0-9]{0,10}\.(com|org|io)", fullmatch=True)
_PATH = st.from_regex(r"(/[a-z0-9_.-]{1,10}){0,3}", fullmatch=True)

# Printable quotes without control characters and without a leading formula character.
# Commas, double quotes and non-ASCII letters are included to exercise CSV quoting.
_QUOTE_CHARS = st.characters(
    whitelist_categories=("Lu", "Ll", "Nd", "Zs", "Po", "Ps", "Pe", "Pd", "Sm"),
    blacklist_characters="\x7f",
)
QUOTES = st.text(_QUOTE_CHARS, min_size=1, max_size=200).filter(
    lambda q: not q.startswith(("=", "+", "-", "@"))
)

_LABELS: list[Label] = ["dead", "finished-healthy", "alive", "ailing"]


@st.composite
def label_rows(
    draw: st.DrawFn, *, name: str | None = None, ecosystem: str | None = None
) -> LabelRow:
    label = draw(st.sampled_from(_LABELS))
    kind = draw(st.sampled_from(sorted(ALLOWED_EVIDENCE_KINDS[label])))
    host = draw(_HOST)
    path = draw(_PATH)
    return LabelRow(
        ecosystem=draw(st.sampled_from(["npm", "pypi"])) if ecosystem is None else ecosystem,  # type: ignore[arg-type]
        name=draw(_NAME) if name is None else name,
        version=draw(_VERSION),
        label=label,
        evidence_kind=kind,
        evidence_url=f"https://{host}{path}",
        evidence_quote=draw(QUOTES),
        labelled_by=draw(st.sampled_from(["coroner", "maintainer"])),
        reviewed=draw(st.booleans()),
    )


@st.composite
def valid_rows(draw: st.DrawFn, *, max_size: int = 12) -> list[LabelRow]:
    """Rows with unique ``(ecosystem, name)`` keys, allowed kinds per label, printable quotes."""
    keys = draw(
        st.lists(
            st.tuples(st.sampled_from(["npm", "pypi"]), _NAME),
            unique=True,
            max_size=max_size,
        )
    )
    return [draw(label_rows(ecosystem=eco, name=name)) for eco, name in keys]


_PREDICTED: list[Predicted] = ["dead", "finished-healthy", "alive", "ailing", "unknown"]
_RISKS = ["r2", "r3", "r4", "r5", "r6", "r7", "r8"]
_SOURCES = ["github", "osv", "deps.dev", "npm", "pypi"]


@st.composite
def outcome(draw: st.DrawFn) -> Outcome:
    """One outcome: dead_reason only when predicted is dead; kind allowed for the label."""
    label = draw(st.sampled_from(_LABELS))
    predicted = draw(st.sampled_from(_PREDICTED))
    reason = draw(st.sampled_from(["declared", "score"])) if predicted == "dead" else None
    missing = tuple(sorted(draw(st.sets(st.sampled_from(_RISKS)))))
    return Outcome(
        ecosystem=draw(st.sampled_from(["npm", "pypi"])),
        name=draw(_NAME),
        label=label,
        predicted=predicted,
        reviewed=draw(st.booleans()),
        evidence_kind=draw(st.sampled_from(sorted(ALLOWED_EVIDENCE_KINDS[label]))),
        dead_reason=reason,  # type: ignore[arg-type]
        confidence=draw(st.floats(min_value=0.0, max_value=1.0)),
        unverified=tuple(draw(st.lists(st.sampled_from(_SOURCES), max_size=2, unique=True))),
        partial_evidence=draw(st.booleans()) if missing else False,
        missing_risks=missing,
    )


outcomes = st.lists(outcome(), max_size=40)
