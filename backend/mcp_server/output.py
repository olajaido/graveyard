"""Result shaping for the MCP tools (KPW-MCP-5, KPW-MCP-6). Pure: no I/O."""

from __future__ import annotations

import json
from typing import Any, Final

from cli.text import sanitise

__all__ = ["MAX_CHARS", "MAX_PACKAGES", "cap_packages", "sanitise_tree"]

MAX_CHARS: Final = 200_000
MAX_PACKAGES: Final = 50


def sanitise_tree(value: Any) -> Any:
    """Return a copy of ``value`` with ``cli.text.sanitise`` applied to every string.

    Dict keys are sanitised too. Lists and tuples become lists; other values are unchanged.
    """
    if isinstance(value, str):
        return sanitise(value)
    if isinstance(value, dict):
        return {sanitise(str(key)): sanitise_tree(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitise_tree(item) for item in value]
    return value


def _compact_length(doc: dict[str, Any]) -> int:
    return len(json.dumps(doc, separators=(",", ":"), ensure_ascii=False))


def _with_packages(doc: dict[str, Any], rows: list[Any], kept: int) -> dict[str, Any]:
    return {
        **doc,
        "packages": rows[:kept],
        "truncated": True,
        "packages_total": len(rows),
        "packages_returned": kept,
    }


def _empty_like(value: Any) -> Any:
    if isinstance(value, list):
        return []
    if isinstance(value, dict):
        return {}
    if isinstance(value, str):
        return ""
    return value


def cap_packages(doc: dict[str, Any]) -> dict[str, Any]:
    """Return ``doc`` plus the top-level boolean ``truncated`` (KPW-MCP-6).

    The size is the compact JSON length of the document as it would be returned. At most
    ``MAX_CHARS``: ``truncated`` is ``False`` and nothing else changes. Above it:
    ``packages`` is cut to the largest prefix (rank order, at most ``MAX_PACKAGES``) that
    brings the result within ``MAX_CHARS``, ``truncated`` is ``True`` and ``packages_total``
    and ``packages_returned`` are added. If even an empty ``packages`` does not fit, the
    largest remaining top-level values (``warnings``, ``errors``, ``input``, ``summary``, ...)
    are emptied one at a time until it does, so the cap is hard. The input is not modified.
    """
    whole = {**doc, "truncated": False}
    if _compact_length(whole) <= MAX_CHARS:
        return whole
    packages = doc.get("packages")
    rows = list(packages) if isinstance(packages, list) else []
    low, high = 0, min(len(rows), MAX_PACKAGES)
    # Largest prefix length that fits; 0 is the floor even when it does not fit.
    while low < high:
        mid = (low + high + 1) // 2
        if _compact_length(_with_packages(doc, rows, mid)) <= MAX_CHARS:
            low = mid
        else:
            high = mid - 1
    result = _with_packages(doc, rows, low)
    protected = {"truncated", "packages", "packages_total", "packages_returned"}
    while _compact_length(result) > MAX_CHARS:
        candidates = [
            key
            for key, value in result.items()
            if key not in protected and value != _empty_like(value)
        ]
        if not candidates:
            break
        biggest = max(candidates, key=lambda key: len(json.dumps(result[key], ensure_ascii=False)))
        result[biggest] = _empty_like(result[biggest])
    return result
