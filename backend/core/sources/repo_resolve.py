"""Repository resolution (SRC-REPO-1..6, D10, design §7).

``choose`` picks a package's GitHub repository from candidate lists that were already
fetched and parsed, and stops at the first accepted candidate:

1. deps.dev: the resolved-version document, then the latest-version document
   (``repo_candidates`` in the order the parser produced) -> via ``"depsdev"``;
2. npm only: the full packument's ``repo_candidates`` -> via ``"registry"``;
3. PyPI only: ``PypiDoc.repo_candidates``, already in label-priority order by the parser
   (SRC-REPO-5) -> via ``"project_urls"``.

The session fetches the npm full packument lazily, only when step 1 found nothing, so
``npm_full`` is ``None`` until then and ``choose`` is called again with it.

A candidate is accepted when ``core.purl.normalise_repo_url`` returns a display form
(SRC-REPO-2) and its owner is not a GitHub reserved path (SRC-REPO-6, D10). Candidates
are untrusted strings; nothing here raises on them.

``group_by_repo_key`` groups packages that share a repository by ``repo_key``
(SRC-REPO-4). The display form of a group is the smallest string among its members, so
it does not depend on input order.

Pure: no I/O, no clock, no environment.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final, Literal

from core.purl import normalise_repo_url, repo_key
from core.sources.facts import DepsDevVersion, NpmFull, PypiDoc

type RepoVia = Literal["depsdev", "registry", "project_urls"]

RESERVED_OWNERS: Final[frozenset[str]] = frozenset(
    {
        "about",
        "account",
        "apps",
        "codespaces",
        "collections",
        "contact",
        "copilot",
        "customer-stories",
        "dashboard",
        "discussions",
        "enterprise",
        "events",
        "explore",
        "features",
        "issues",
        "join",
        "login",
        "marketplace",
        "new",
        "notifications",
        "orgs",
        "organizations",
        "pricing",
        "pulls",
        "readme",
        "search",
        "security",
        "sessions",
        "settings",
        "signup",
        "site",
        "sponsors",
        "stars",
        "topics",
        "trending",
        "users",
        "watching",
    }
)
"""Lower-case GitHub reserved top-level paths. An owner in this set is never a repository
owner, so ``github.com/sponsors/<user>`` is rejected (SRC-REPO-6, D10)."""


def accept(raw: str) -> str | None:
    """Return the display form ``github.com/<owner>/<repo>`` of ``raw``, or ``None``.

    ``None`` when ``normalise_repo_url`` rejects ``raw`` or the owner is a reserved path
    (compared case-insensitively).
    """
    normalised = normalise_repo_url(raw)
    if normalised is None:
        return None
    owner = normalised.split("/", 2)[1]
    if owner.lower() in RESERVED_OWNERS:
        return None
    return normalised


def _first_accepted(candidates: Iterable[str]) -> str | None:
    for raw in candidates:
        repo = accept(raw)
        if repo is not None:
            return repo
    return None


def choose(
    depsdev_resolved: DepsDevVersion | None,
    depsdev_latest: DepsDevVersion | None,
    npm_full: NpmFull | None,
    pypi_doc: PypiDoc | None,
    ecosystem: str,
) -> tuple[str | None, RepoVia | None]:
    """Resolve ``(repo, via)`` in the order of SRC-REPO-1, or ``(None, None)``.

    A missing document (``None``) contributes no candidates. ``ecosystem`` is ``"npm"`` or
    ``"pypi"``; the registry step reads only the document of that ecosystem, and any other
    value resolves from deps.dev alone.
    """
    for doc in (depsdev_resolved, depsdev_latest):
        if doc is not None:
            repo = _first_accepted(doc.repo_candidates)
            if repo is not None:
                return repo, "depsdev"
    if ecosystem == "npm" and npm_full is not None:
        repo = _first_accepted(npm_full.repo_candidates)
        if repo is not None:
            return repo, "registry"
    if ecosystem == "pypi" and pypi_doc is not None:
        repo = _first_accepted(pypi_doc.repo_candidates)
        if repo is not None:
            return repo, "project_urls"
    return None, None


def group_by_repo_key[P](
    items: Iterable[tuple[str, P]],
) -> dict[str, tuple[str, tuple[P, ...]]]:
    """Group ``(display repo, package)`` pairs by ``repo_key`` (SRC-REPO-4).

    Returns ``repo_key -> (smallest display form, packages)``. The packages of a group
    keep their input order. Each display form must be ``normalise_repo_url`` output;
    anything else raises ``ValueError`` from ``repo_key`` (a programming error).
    """
    displays: dict[str, str] = {}
    packages: dict[str, list[P]] = {}
    for repo, package in items:
        key = repo_key(repo)
        current = displays.get(key)
        if current is None or repo < current:
            displays[key] = repo
        packages.setdefault(key, []).append(package)
    return {key: (displays[key], tuple(packages[key])) for key in displays}
