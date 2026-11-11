"""Parsers for the npm and PyPI registry documents (design §6, §7).

* ``parse_npm_abbreviated``: the npm abbreviated packument (S1, S1b, latest version);
* ``parse_npm_full``: the npm full packument (S2 and repo fallbacks);
* ``parse_pypi``: the PyPI project JSON (latest version, S2, repo candidates).

Each takes any ``object`` (already-decoded JSON) and returns a fact or ``None``. ``None``
means the document is not the expected kind (not a mapping); a mapping that is merely
poor in data gives a fact with ``None`` fields (D3, D4). None of them raises.

Only validated scalars leave this module (D11). The npm ``deprecated`` field is read for
its truthiness only; its message text, like every description, README and other free-text
field, is never read or copied. Version strings pass ``is_valid_version`` and dates are
UTC dates (``as_date``), else ``None``. The repo candidates are raw URL-like strings,
bounded in length, which the consumer reduces through ``core.purl.normalise_repo_url``
(SRC-REPO-1, SRC-REPO-2).

PyPI ``releases`` (design §6): PyPI has deprecated the key. The latest release date comes
from the top-level ``urls`` first and from ``releases[latest]`` only as a fallback;
``resolved_found`` is ``None`` (unknown) when ``releases`` is absent.

Ported from the prototype's ``collect_registry_npm``, ``collect_registry_pypi``,
``pypi_release_date`` and ``pypi_repo`` (``scripts/capture_anchors.py``) with explicit
type checks.

Pure: no I/O, no clock, no environment.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from typing import Final

from core.sources.accessors import as_date, as_list, as_mapping, as_str
from core.sources.facts import NpmFull, NpmRegistry, PypiDoc, is_valid_version

_MAX_CANDIDATE_LENGTH: Final = 2048
"""Longest repo candidate kept. Real repository URLs are far shorter."""

_PYPI_LABEL_PRIORITY: Final = (
    "source",
    "source code",
    "repository",
    "code",
    "github",
    "homepage",
    "home",
)
"""Lower-case ``project_urls`` labels tried first, in this order (SRC-REPO-5)."""


def _candidate(value: object) -> str | None:
    """A non-empty string of bounded length, else ``None``."""
    text = as_str(value)
    if text is None or not text or len(text) > _MAX_CANDIDATE_LENGTH:
        return None
    return text


def _version(value: object) -> str | None:
    """A string that passes ``is_valid_version``, else ``None``."""
    text = as_str(value)
    if text is None or not is_valid_version(text):
        return None
    return text


def _deprecated(versions: Mapping[str, object], version: str | None) -> bool | None:
    """Truthiness of ``versions[version].deprecated``; ``None`` if the entry is unusable.

    A version entry without a ``deprecated`` key is not deprecated. The value itself
    (npm puts the message there) is only tested for truthiness, never read.
    """
    if version is None or version not in versions:
        return None
    entry = as_mapping(versions[version])
    if entry is None:
        return None
    return bool(entry.get("deprecated"))


def _dedupe(items: Iterable[str | None]) -> tuple[str, ...]:
    """Drop ``None`` and repeats; the first occurrence keeps its position."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item is not None and item not in seen:
            seen.add(item)
            out.append(item)
    return tuple(out)


def parse_npm_abbreviated(data: object, resolved: str) -> NpmRegistry | None:
    """Reduce an npm abbreviated packument.

    ``latest`` is ``dist-tags.latest`` when it is a valid version string.
    ``latest_deprecated`` and ``resolved_deprecated`` are the truthiness of ``deprecated``
    on ``versions[latest]`` and ``versions[resolved]`` (``None`` when that entry is
    absent or not a mapping). ``resolved_found`` is whether ``resolved`` is a key of
    ``versions``.
    """
    doc = as_mapping(data)
    if doc is None:
        return None
    tags = as_mapping(doc.get("dist-tags"))
    latest = _version(tags.get("latest")) if tags is not None else None
    versions = as_mapping(doc.get("versions")) or {}
    return NpmRegistry(
        latest=latest,
        latest_deprecated=_deprecated(versions, latest),
        resolved_deprecated=_deprecated(versions, resolved),
        resolved_found=resolved in versions,
    )


def parse_npm_full(data: object, latest: str | None) -> NpmFull | None:
    """Reduce an npm full packument.

    ``latest_published`` is ``time[latest]`` as a UTC date (``None`` without a latest
    version). ``repo_candidates`` holds ``repository`` when it is a string, or its
    ``url`` when it is a mapping.

    ``None`` is also returned when, with a ``latest`` to look up, ``time`` is present and not
    an object, or ``time[latest]`` is present (not ``null``) and not a date string (D17):
    S2 depends on it, and a damaged value read as "absent" would drop S2 with no warning.
    """
    doc = as_mapping(data)
    if doc is None:
        return None
    published: date | None = None
    raw_times = doc.get("time")
    if latest is not None and raw_times is not None:
        times = as_mapping(raw_times)
        if times is None:
            return None
        raw_published = times.get(latest)
        published = as_date(raw_published)
        if raw_published is not None and published is None:
            return None
    repository = doc.get("repository")
    mapping = as_mapping(repository)
    raw = _candidate(mapping.get("url")) if mapping is not None else _candidate(repository)
    return NpmFull(latest_published=published, repo_candidates=_dedupe([raw]))


def _earliest_upload(files: object) -> tuple[date | None, bool]:
    """``(earliest date, readable)`` of the ``upload_time_iso_8601`` of a list of release files.

    ``files`` absent or ``null`` is an absence: ``(None, True)``. A list that is not a list, a
    file that is not an object, or an upload time that is present (not ``null``) and not a
    date string makes it unreadable, ``(None, False)`` (D17): skipping that file could pick a
    later date than the real earliest one.
    """
    if files is None:
        return None, True
    items = as_list(files)
    if items is None:
        return None, False
    earliest: date | None = None
    for item in items:
        entry = as_mapping(item)
        if entry is None:
            return None, False
        raw = entry.get("upload_time_iso_8601")
        if raw is None:
            continue
        uploaded = as_date(raw)
        if uploaded is None:
            return None, False
        if earliest is None or uploaded < earliest:
            earliest = uploaded
    return earliest, True


def _label_rank(label: str) -> tuple[int, str, str]:
    """Sort key for a ``project_urls`` label: priority labels first, then alphabetical."""
    lowered = label.lower()
    if lowered in _PYPI_LABEL_PRIORITY:
        return (_PYPI_LABEL_PRIORITY.index(lowered), lowered, label)
    return (len(_PYPI_LABEL_PRIORITY), lowered, label)


def _pypi_candidates(info: Mapping[str, object]) -> tuple[str, ...]:
    """``project_urls`` by label priority, then ``home_page``, then ``download_url``."""
    ordered: list[str | None] = []
    urls = as_mapping(info.get("project_urls"))
    if urls is not None:
        labels = [label for label in urls if isinstance(label, str)]
        ordered.extend(_candidate(urls[label]) for label in sorted(labels, key=_label_rank))
    ordered.append(_candidate(info.get("home_page")))
    ordered.append(_candidate(info.get("download_url")))
    return _dedupe(ordered)


def parse_pypi(data: object, resolved: str) -> PypiDoc | None:
    """Reduce a PyPI project JSON document.

    ``latest`` is ``info.version`` when it is a valid version string.
    ``latest_published`` is the earliest ``upload_time_iso_8601`` date among the top-level
    ``urls`` (the files of the latest release), else among ``releases[latest]``; it is
    ``None`` without a latest version. ``resolved_found`` is whether ``resolved`` is a key
    of ``releases``, or ``None`` when ``releases`` is absent or not a mapping.
    ``repo_candidates`` are label-ordered per SRC-REPO-5.

    ``None`` is also returned when the release files that ``latest_published`` is read from are
    unreadable (``_earliest_upload``, D17): a damaged upload time must not silently become a
    later date, or an absent one.
    """
    doc = as_mapping(data)
    if doc is None:
        return None
    info = as_mapping(doc.get("info")) or {}
    latest = _version(info.get("version"))
    releases = as_mapping(doc.get("releases"))
    published: date | None = None
    if latest is not None:
        published, readable = _earliest_upload(doc.get("urls"))
        if not readable:
            return None
        if published is None and releases is not None:
            published, readable = _earliest_upload(releases.get(latest))
            if not readable:
                return None
    return PypiDoc(
        latest=latest,
        latest_published=published,
        resolved_found=None if releases is None else resolved in releases,
        repo_candidates=_pypi_candidates(info),
    )
