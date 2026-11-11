"""Parsers for the OSV documents (design §6.1; SRC-OSV-1, 3, 4, 5, 7).

* ``parse_query_results``: ``POST /v1/querybatch``, the form
  ``{"results": [{"vulns": [{"id": ...}, ...], "next_page_token": "..."}, ...]}``;
* ``parse_vuln``: ``GET /v1/vulns/<id>``, reduced to an ``OsvVuln`` for one package;
* ``to_advisory``: the scoring-side ``Advisory`` for an ``OsvVuln``.

Each parser takes any ``object`` (already-decoded JSON) and never raises. Only validated
scalars leave the module: advisory ids that pass ``is_valid_osv_id``, fixed versions that
pass ``is_valid_version`` (through ``osv_fix``), a flag and a date. ``summary``,
``details``, ``aliases``, ``references`` and every other field are ignored, so response
text cannot reach evidence (SRC-SEC-4, D11).

``parse_query_results`` contract
--------------------------------
Returns ``None`` when the document is not a mapping, ``results`` is missing or not a
list, ``len(results) != expected_count`` (SRC-OSV-1: the caller marks every query in the
chunk as failed), an element of ``results`` is not a mapping, ``vulns`` is present but
not a list, or ``next_page_token`` is present but neither ``null`` nor a ``str``. The last
case matters: reading an unusable token as "no more pages" could drop advisories and hide
a Cursed state (SRC-OSV-6), so the whole chunk is treated as malformed instead.

Otherwise it returns one ``OsvQueryResult`` per query, in query order:

* ``ids``: valid advisory ids in first-seen order, duplicates removed. A missing ``vulns``
  key (OSV's answer for "no advisories") gives ``()``;
* ``next_page_token``: the token as a ``str``, or ``None`` when absent, ``null`` or empty
  (no further page);
* ``malformed``: true when any ``vulns`` entry of this query was unusable: not a mapping,
  without a ``str`` ``id``, or with an ``id`` failing ``is_valid_osv_id`` (SRC-OSV-3). An
  unusable entry is never skipped. What it names might be a no-fix advisory, so a list built
  without it is incomplete and reading it as complete could hide a Cursed state; the client
  turns ``malformed`` into ``Failed(UNEXPECTED_SHAPE)`` for that package's S7 (SRC-OSV-6).
  Other queries of the same response are not affected: each ``results`` element is judged on
  its own (unlike a wrong ``next_page_token`` or a wrong ``results`` shape, which spoil the
  whole chunk).

``parse_vuln`` contract
-----------------------
Returns ``None`` when the document is not a mapping, its ``id`` is missing, not a ``str``,
or invalid, or ``published`` is **present and unusable** (not ``null``, and not a string that
parses as a date). ``withdrawn`` is true iff the field is present and a non-empty ``str``
(OSV's value is a timestamp); the caller skips withdrawn advisories (SRC-OSV-5).
``published_at`` is the date of ``published``, or ``None`` when ``published`` is absent or
``null`` (an honest unknown: the advisory never satisfies the Cursed age condition). A
``published`` that is there but unusable is not read as "unknown": the Cursed rule depends on
that date, and a value that silently became ``None`` would change the verdict with no
warning, so the document is rejected and the package's S7 is unknown (SRC-OSV-5, SRC-OSV-6).
``fixed_versions`` and ``has_fix`` come from ``core.sources.osv_fix`` for the queried
``ecosystem`` and ``name``.

Pure: no I/O, no clock, no environment.
"""

from __future__ import annotations

from typing import NamedTuple

from core.scoring.types import Advisory
from core.sources.accessors import as_date, as_list, as_mapping, as_str
from core.sources.facts import OsvVuln
from core.sources.osv_fix import fixed_versions
from core.sources.urls import is_valid_osv_id


class OsvQueryResult(NamedTuple):
    """The reduced answer to one query of a ``querybatch`` request."""

    ids: tuple[str, ...]
    next_page_token: str | None
    malformed: bool


def _query_result(item: object) -> OsvQueryResult | None:
    """Reduce one element of ``results``, or ``None`` if its shape is wrong."""
    doc = as_mapping(item)
    if doc is None:
        return None

    token_raw = doc.get("next_page_token")
    if token_raw is not None and not isinstance(token_raw, str):
        return None
    token = token_raw or None

    ids: list[str] = []
    malformed = False
    if "vulns" in doc and doc["vulns"] is not None:
        vulns = as_list(doc["vulns"])
        if vulns is None:
            return None
        seen: set[str] = set()
        for entry in vulns:
            entry_doc = as_mapping(entry)
            vuln_id = as_str(entry_doc.get("id")) if entry_doc is not None else None
            if vuln_id is None or not is_valid_osv_id(vuln_id):
                malformed = True
            elif vuln_id not in seen:
                seen.add(vuln_id)
                ids.append(vuln_id)
    return OsvQueryResult(ids=tuple(ids), next_page_token=token, malformed=malformed)


def parse_query_results(data: object, expected_count: int) -> list[OsvQueryResult] | None:
    """Reduce a ``querybatch`` response to one ``OsvQueryResult`` per query.

    ``None`` on a wrong shape or when ``results`` does not have ``expected_count``
    elements. See the module docstring for the full contract.
    """
    doc = as_mapping(data)
    if doc is None:
        return None
    results = as_list(doc.get("results"))
    if results is None or len(results) != expected_count:
        return None
    out: list[OsvQueryResult] = []
    for item in results:
        reduced = _query_result(item)
        if reduced is None:
            return None
        out.append(reduced)
    return out


def parse_vuln(data: object, ecosystem: str, name: str) -> OsvVuln | None:
    """Reduce one OSV advisory document for ``ecosystem``/``name``."""
    doc = as_mapping(data)
    if doc is None:
        return None
    vuln_id = as_str(doc.get("id"))
    if vuln_id is None or not is_valid_osv_id(vuln_id):
        return None
    withdrawn_raw = as_str(doc.get("withdrawn"))
    published_raw = doc.get("published")
    published = as_date(published_raw)
    if published_raw is not None and published is None:
        return None  # present but unusable: not an honest "unknown" (SRC-OSV-5)
    fixed = fixed_versions(doc, ecosystem, name)
    return OsvVuln(
        id=vuln_id,
        withdrawn=withdrawn_raw is not None and withdrawn_raw != "",
        published_at=published,
        fixed_versions=fixed,
        has_fix=bool(fixed),
    )


def to_advisory(vuln: OsvVuln) -> Advisory:
    """The scoring ``Advisory`` for ``vuln`` (SRC-OSV-7).

    Does not filter: the caller skips ``vuln.withdrawn`` advisories before converting and
    sorts the result by id.
    """
    return Advisory(id=vuln.id, has_fix=vuln.has_fix, published_at=vuln.published_at)
