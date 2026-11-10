"""Parsers for the three deps.dev documents (design §6; SRC-S1, S2, S4, S8, SRC-LAT-1).

* ``parse_version``: ``GET /v3/systems/{s}/packages/{name}/versions/{version}``;
* ``parse_package``: ``GET /v3/systems/{s}/packages/{name}`` (the latest-version fallback);
* ``parse_project``: ``GET /v3/projects/{key}`` (the Scorecard block).

Each takes any ``object`` (already-decoded JSON) and returns a fact or ``None``. ``None``
means the document is not the expected kind (not a mapping, or for ``parse_package``
without a ``versions`` list); a mapping that is merely poor in data gives a fact with
``None`` fields (D3, D4). None of them raises.

Only validated scalars leave this module (D11): descriptions, license text, advisory
keys and every other free-text field are never read. The repo candidates are the one
exception to "validated": they are raw URL-like strings in priority order, bounded in
length, which the consumer reduces through ``core.purl.normalise_repo_url``
(SRC-REPO-1). Ported from the prototype's ``depsdev_repo`` and ``collect_scorecard``
(``scripts/capture_anchors.py``) with explicit type checks.

Pure: no I/O, no clock, no environment.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from core.sources.accessors import (
    as_bool,
    as_date,
    as_list,
    as_mapping,
    as_score,
    as_str,
)
from core.sources.facts import (
    DepsDevPackage,
    DepsDevProject,
    DepsDevVersion,
    is_valid_version,
)

_SOURCE_REPO: Final = "SOURCE_REPO"
_MAINTAINED: Final = "Maintained"
_MAX_CANDIDATE_LENGTH: Final = 2048
"""Longest repo candidate kept. Real repository URLs are far shorter."""


def _candidate(value: object) -> str | None:
    """A non-empty string of bounded length, else ``None``."""
    text = as_str(value)
    if text is None or not text or len(text) > _MAX_CANDIDATE_LENGTH:
        return None
    return text


def _related_project_candidates(data: object) -> list[str]:
    out: list[str] = []
    for item in as_list(data) or []:
        project = as_mapping(item)
        if project is None or project.get("relationType") != _SOURCE_REPO:
            continue
        key = as_mapping(project.get("projectKey"))
        text = _candidate(key.get("id")) if key is not None else None
        if text is not None:
            out.append(text)
    return out


def _link_candidates(data: object) -> list[str]:
    out: list[str] = []
    for item in as_list(data) or []:
        link = as_mapping(item)
        if link is None or link.get("label") != _SOURCE_REPO:
            continue
        text = _candidate(link.get("url"))
        if text is not None:
            out.append(text)
    return out


def parse_version(data: object) -> DepsDevVersion | None:
    """Reduce a deps.dev version document.

    ``is_deprecated`` is set only when ``isDeprecated`` is a ``bool``. ``published_at``
    is ``publishedAt`` as a UTC date. ``repo_candidates`` lists the ``projectKey.id`` of
    each ``relatedProjects`` entry whose ``relationType`` is ``SOURCE_REPO``, then the
    ``url`` of each ``links`` entry whose ``label`` is ``SOURCE_REPO``, in document order.
    """
    doc = as_mapping(data)
    if doc is None:
        return None
    return DepsDevVersion(
        is_deprecated=as_bool(doc.get("isDeprecated")),
        published_at=as_date(doc.get("publishedAt")),
        repo_candidates=tuple(
            _related_project_candidates(doc.get("relatedProjects"))
            + _link_candidates(doc.get("links"))
        ),
    )


def parse_package(data: object) -> DepsDevPackage | None:
    """Reduce a deps.dev package document to its default version (SRC-LAT-1).

    ``default_version`` is the ``versionKey.version`` of the single ``versions[]`` entry
    with ``isDefault`` true. With no default, several defaults, or a default whose version
    is not a valid version string, it is ``None``. A document without a ``versions`` list
    is not a package document and gives ``None``.
    """
    doc = as_mapping(data)
    if doc is None:
        return None
    versions = as_list(doc.get("versions"))
    if versions is None:
        return None
    defaults: list[Mapping[str, object]] = []
    for item in versions:
        entry = as_mapping(item)
        if entry is not None and as_bool(entry.get("isDefault")) is True:
            defaults.append(entry)
    if len(defaults) != 1:
        return DepsDevPackage(default_version=None)
    key = as_mapping(defaults[0].get("versionKey"))
    version = as_str(key.get("version")) if key is not None else None
    if version is None or not is_valid_version(version):
        version = None
    return DepsDevPackage(default_version=version)


def parse_project(data: object) -> DepsDevProject | None:
    """Reduce a deps.dev project document to its Scorecard values (S4, S8).

    ``overall`` is ``scorecard.overallScore`` and ``maintained`` is the ``score`` of the
    first ``scorecard.checks[]`` entry named ``Maintained``, both through ``as_score``
    (so ``-1`` passes through, and out-of-range or non-numeric values become ``None``).
    ``has_scorecard`` is true when the ``scorecard`` block is a mapping.
    """
    doc = as_mapping(data)
    if doc is None:
        return None
    card = as_mapping(doc.get("scorecard"))
    if card is None:
        return DepsDevProject(maintained=None, overall=None, has_scorecard=False)
    maintained: float | None = None
    for item in as_list(card.get("checks")) or []:
        check = as_mapping(item)
        if check is not None and check.get("name") == _MAINTAINED:
            maintained = as_score(check.get("score"))
            break
    return DepsDevProject(
        maintained=maintained,
        overall=as_score(card.get("overallScore")),
        has_scorecard=True,
    )
