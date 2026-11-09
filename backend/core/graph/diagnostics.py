"""Warning construction and finalisation (design §5.6, DG-WARN-1…5).

``GraphWarning`` is the only diagnostics channel of this package (D14). This
module builds warnings with bounded text and turns an unordered collection of
them into the final sorted, de-duplicated, capped tuple. It does no I/O and
imports neither ``logging`` nor ``warnings``.
"""

from __future__ import annotations

from collections.abc import Iterable

from core.graph.model import (
    MAX_SUBJECTS,
    MAX_TEXT,
    MAX_WARNINGS_PER_CODE,
    WARNING_CODES,
    GraphWarning,
)

_ELLIPSIS = "…"
_TRUNCATED_CODE = "WARNINGS_TRUNCATED"


def _clip(text: str, limit: int) -> str:
    """Return ``text`` unchanged if it fits in ``limit`` characters, else cut with an ellipsis."""
    if len(text) <= limit:
        return text
    return text[: limit - 1] + _ELLIPSIS


def _normalise(
    code: str,
    detail: str,
    service: str | None,
    subjects: Iterable[str],
) -> GraphWarning:
    """Bound the text of a warning. Applying this twice gives the same result as once.

    ``detail`` and each subject are cut to ``MAX_TEXT`` characters. Subjects are
    sorted and de-duplicated (after cutting). When more than ``MAX_SUBJECTS``
    remain, the first ``MAX_SUBJECTS`` are kept and the total is appended to
    ``detail``. The base text shrinks to make room for that suffix, so the
    final ``detail`` never exceeds ``MAX_TEXT`` and a second pass leaves it
    alone.
    """
    unique = sorted({_clip(s, MAX_TEXT) for s in subjects})
    total = len(unique)
    if total > MAX_SUBJECTS:
        suffix = f" {_ELLIPSIS} ({total} in total)"
        detail = _clip(detail, MAX_TEXT - len(suffix)) + suffix
        unique = unique[:MAX_SUBJECTS]
    else:
        detail = _clip(detail, MAX_TEXT)
    return GraphWarning(code=code, detail=detail, service=service, subjects=tuple(unique))


def make_warning(
    code: str,
    detail: str,
    service: str | None = None,
    subjects: Iterable[str] = (),
) -> GraphWarning:
    """Build a ``GraphWarning`` with bounded text.

    Raises ``ValueError`` if ``code`` is not a member of ``WARNING_CODES``.
    """
    if code not in WARNING_CODES:
        raise ValueError(f"unknown warning code: {_clip(code, MAX_TEXT)!r}")
    return _normalise(code, detail, service, subjects)


def _sort_key(w: GraphWarning) -> tuple[str, str, str, tuple[str, ...], bool]:
    # The trailing flag separates service=None from service="" so ties cannot
    # depend on input order.
    return (w.service or "", w.code, w.detail, w.subjects, w.service is not None)


def finalise_warnings(warnings: Iterable[GraphWarning]) -> tuple[GraphWarning, ...]:
    """Return the final warning list: bounded, de-duplicated, sorted and capped.

    Each ``(service, code)`` group keeps its first ``MAX_WARNINGS_PER_CODE``
    warnings in sorted order and gains one ``WARNINGS_TRUNCATED`` warning when
    any were dropped. ``WARNINGS_TRUNCATED`` warnings are exempt from the cap.
    The result does not depend on input order, and the function is idempotent.
    """
    normalised = {_normalise(w.code, w.detail, w.service, w.subjects) for w in warnings}
    ordered = sorted(normalised, key=_sort_key)

    kept: list[GraphWarning] = []
    seen: dict[tuple[str | None, str], int] = {}
    omitted: dict[tuple[str | None, str], int] = {}
    for w in ordered:
        if w.code == _TRUNCATED_CODE:
            kept.append(w)
            continue
        group = (w.service, w.code)
        count = seen.get(group, 0)
        if count < MAX_WARNINGS_PER_CODE:
            seen[group] = count + 1
            kept.append(w)
        else:
            omitted[group] = omitted.get(group, 0) + 1

    for (service, code), n in omitted.items():
        kept.append(_normalise(_TRUNCATED_CODE, f"{code}: {n} more omitted", service, ()))

    return tuple(sorted(set(kept), key=_sort_key))
