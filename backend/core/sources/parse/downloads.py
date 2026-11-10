"""Parsers for the weekly-download documents (design §6.3; SRC-S9-1, SRC-S9-2).

* ``parse_npm_single``: ``GET api.npmjs.org/downloads/point/last-week/<name>``, the flat
  form ``{"downloads": int, "start": ..., "end": ..., "package": ...}``;
* ``parse_npm_bulk``: the same endpoint with several names, the form
  ``{"<name>": {"downloads": int, ...} | null, ...}``;
* ``parse_pypistats``: ``GET pypistats.org/api/packages/<name>/recent``, the form
  ``{"data": {"last_week": int, ...}, ...}``.

Each takes any ``object`` (already-decoded JSON) and never raises. A count is accepted
only if ``as_int`` accepts it (``int``, not ``bool``, not negative). Only that count
leaves the module; ``package``, ``start``, ``end`` and every other field are ignored, so
response text cannot reach evidence (D11).

Return conventions:

* ``parse_npm_single`` and ``parse_pypistats`` return ``Downloads(weekly)`` or ``None``
  when the document carries no usable count. The caller turns ``None`` into an
  ``UNEXPECTED_SHAPE`` warning (S9 stays ``None``, never ``0``; D4).
* ``parse_npm_bulk`` returns a read-only mapping whose keys are exactly the distinct
  requested names (response keys that were not requested are ignored, SRC-S9-1). Each
  value is ``Downloads(n)`` for a usable entry, ``Downloads(None)`` for a ``null`` entry
  (npm's way to say "unknown package": not an error, no warning), and ``None`` for an
  unusable entry (missing key, non-mapping, bad ``downloads``), which the caller turns
  into ``UNEXPECTED_SHAPE`` for that name only. The whole result is ``None`` when the
  response is not a mapping at all.

Pure: no I/O, no clock, no environment.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import MappingProxyType

from core.sources.accessors import as_int, as_mapping
from core.sources.facts import Downloads


def _entry_downloads(entry: object) -> Downloads | None:
    """``Downloads`` from a mapping with a usable ``downloads`` count, else ``None``."""
    doc = as_mapping(entry)
    if doc is None:
        return None
    count = as_int(doc.get("downloads"))
    if count is None:
        return None
    return Downloads(weekly=count)


def parse_npm_single(data: object) -> Downloads | None:
    """Reduce the flat single-name npm downloads document."""
    return _entry_downloads(data)


def parse_npm_bulk(data: object, requested: Iterable[str]) -> Mapping[str, Downloads | None] | None:
    """Reduce a bulk npm downloads document for the names in ``requested``.

    The result maps each distinct requested name to ``Downloads(n)``,
    ``Downloads(None)`` (a ``null`` entry: unknown package) or ``None`` (unusable entry).
    It is ``None`` when ``data`` is not a mapping. See the module docstring.
    """
    doc = as_mapping(data)
    if doc is None:
        return None
    out: dict[str, Downloads | None] = {}
    for name in requested:
        if name in out:
            continue
        if name in doc and doc[name] is None:
            out[name] = Downloads(weekly=None)
        else:
            out[name] = _entry_downloads(doc.get(name))
    return MappingProxyType(out)


def parse_pypistats(data: object) -> Downloads | None:
    """Reduce a pypistats ``recent`` document to ``data.last_week``."""
    doc = as_mapping(data)
    if doc is None:
        return None
    inner = as_mapping(doc.get("data"))
    if inner is None:
        return None
    count = as_int(inner.get("last_week"))
    if count is None:
        return None
    return Downloads(weekly=count)
