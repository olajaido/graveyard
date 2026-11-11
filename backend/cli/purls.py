"""``--purl`` validation (CLI-PURL-2, CLI-PURL-3; design 5.2a). Pure: no I/O."""

from __future__ import annotations

from collections.abc import Sequence

from cli.errors import UsageError
from cli.text import sanitise
from core.purl import format_purl, package_key, parse_purl

__all__ = ["validate_purls"]

_SHOWN_LEN = 100


def _shown(text: str) -> str:
    return sanitise(text)[:_SHOWN_LEN]


def validate_purls(raw: Sequence[str]) -> tuple[str, ...]:
    """Validate, canonicalise, de-duplicate by ``package_key`` and sort the purls.

    ``parse_purl`` already rejects any ecosystem other than npm and PyPI. Its error
    text is never echoed: the message is a fixed template plus the sanitised,
    truncated argument. For duplicates the smallest canonical purl is kept.
    """
    seen: dict[str, str] = {}
    for position, text in enumerate(raw, start=1):
        try:
            parsed = parse_purl(text)
        except ValueError:
            raise UsageError(
                f"--purl #{position}: not a valid npm or PyPI package URL: {_shown(text)}"
            ) from None
        if parsed.version is None:
            raise UsageError(f"--purl #{position}: the package URL needs a version: {_shown(text)}")
        key = package_key(parsed)
        canonical = format_purl(parsed)
        seen[key] = min(seen.get(key, canonical), canonical)
    return tuple(sorted(seen.values()))
