"""URL constants and builders for the pure half of the source clients (SRC-HTTP-2, SRC-HTTP-3).

``ALLOWED_HOSTS`` is the fixed allow-list of hosts the gateway may contact. It is a
code constant: configuration can tune a host (``core.sources.config``) but never add
one.

Every URL the source clients request is formatted here, from already-validated
components (callers use ``core.purl``; the builders do not parse purls). Every path
segment is percent-encoded with ``quote(segment, safe="")``, so the ``/`` in
``@scope/name`` and in a project key becomes ``%2F``. The only literal separator is the
comma between names in the npm bulk downloads URL (SRC-S9-1). Empty segments, and the
dot segments ``.`` and ``..`` (which clients may normalise away), raise ``ValueError``.

This module reads no environment.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Final
from urllib.parse import quote

ALLOWED_HOSTS: Final[frozenset[str]] = frozenset(
    {
        "api.deps.dev",
        "api.osv.dev",
        "registry.npmjs.org",
        "pypi.org",
        "api.npmjs.org",
        "pypistats.org",
        "api.securityscorecards.dev",
        "api.github.com",
    }
)

NPM_BULK_MAX: Final = 128
"""Most names in one npm bulk downloads request (SRC-S9-1)."""

_DEPSDEV_ECOSYSTEMS: Final[frozenset[str]] = frozenset({"npm", "pypi"})
_BULK_SAFE: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._~-]*")
_OSV_ID: Final = re.compile(r"[A-Za-z0-9_.:-]{1,100}")


def is_bulk_safe(name: str) -> bool:
    """True if ``name`` may be one entry of an npm bulk downloads request."""
    return _BULK_SAFE.fullmatch(name) is not None


def is_valid_osv_id(value: str) -> bool:
    """True if ``value`` matches ``[A-Za-z0-9_.:-]{1,100}`` (SRC-HTTP-3)."""
    return _OSV_ID.fullmatch(value) is not None


def _q(segment: str, what: str) -> str:
    """Quote one path segment; reject empty and dot segments."""
    if not isinstance(segment, str) or segment in ("", ".", ".."):
        raise ValueError(f"invalid {what}")
    return quote(segment, safe="")


def _depsdev_ecosystem(ecosystem: str) -> str:
    if ecosystem not in _DEPSDEV_ECOSYSTEMS:
        raise ValueError("invalid ecosystem")
    return ecosystem


# deps.dev -------------------------------------------------------------------


def depsdev_version_url(ecosystem: str, name: str, version: str) -> str:
    """``GET /v3/systems/{npm|pypi}/packages/{name}/versions/{version}``."""
    eco = _depsdev_ecosystem(ecosystem)
    return (
        f"https://api.deps.dev/v3/systems/{eco}/packages/{_q(name, 'name')}"
        f"/versions/{_q(version, 'version')}"
    )


def depsdev_package_url(ecosystem: str, name: str) -> str:
    """``GET /v3/systems/{npm|pypi}/packages/{name}``."""
    eco = _depsdev_ecosystem(ecosystem)
    return f"https://api.deps.dev/v3/systems/{eco}/packages/{_q(name, 'name')}"


def depsdev_project_url(owner: str, repo: str) -> str:
    """``GET /v3/projects/github.com%2F{owner}%2F{repo}`` (the key is one segment)."""
    key = f"github.com%2F{_q(owner, 'owner')}%2F{_q(repo, 'repo')}"
    return f"https://api.deps.dev/v3/projects/{key}"


# Scorecard ------------------------------------------------------------------


def scorecard_url(owner: str, repo: str) -> str:
    """``GET /projects/github.com/{owner}/{repo}`` on the Scorecard API."""
    return (
        "https://api.securityscorecards.dev/projects/github.com/"
        f"{_q(owner, 'owner')}/{_q(repo, 'repo')}"
    )


# Registries -----------------------------------------------------------------


def npm_packument_url(name: str) -> str:
    """``GET /{name}`` on the npm registry (``@scope/name`` becomes ``%40scope%2Fname``)."""
    return f"https://registry.npmjs.org/{_q(name, 'name')}"


def pypi_json_url(name: str) -> str:
    """``GET /pypi/{name}/json`` on PyPI."""
    return f"https://pypi.org/pypi/{_q(name, 'name')}/json"


# Downloads ------------------------------------------------------------------


def npm_downloads_single_url(name: str) -> str:
    """``GET /downloads/point/last-week/{name}`` (single-name form, scoped names allowed)."""
    return f"https://api.npmjs.org/downloads/point/last-week/{_q(name, 'name')}"


def npm_downloads_bulk_url(names: Sequence[str]) -> str:
    """``GET /downloads/point/last-week/{n1},{n2},...`` for bulk-safe names.

    Raises ``ValueError`` for an empty list, more than ``NPM_BULK_MAX`` names, or any
    name that is not bulk-safe. Names are quoted and joined by literal commas.
    """
    if not names:
        raise ValueError("no names")
    if len(names) > NPM_BULK_MAX:
        raise ValueError("too many names")
    if not all(isinstance(n, str) and is_bulk_safe(n) for n in names):
        raise ValueError("name is not bulk-safe")
    joined = ",".join(quote(n, safe="") for n in names)
    return f"https://api.npmjs.org/downloads/point/last-week/{joined}"


def pypistats_recent_url(normalised_name: str) -> str:
    """``GET /api/packages/{name}/recent`` on pypistats (name already PEP 503 normalised)."""
    return f"https://pypistats.org/api/packages/{_q(normalised_name, 'name')}/recent"


# OSV ------------------------------------------------------------------------


def osv_querybatch_url() -> str:
    """``POST /v1/querybatch``."""
    return "https://api.osv.dev/v1/querybatch"


def osv_vuln_url(vuln_id: str) -> str:
    """``GET /v1/vulns/{id}``.

    Raises ``ValueError`` unless the id is a ``str`` that passes ``is_valid_osv_id``, and
    also for the dot segments ``"."`` and ``".."``. Those two pass the id pattern (``.`` is
    an allowed character) but are path-traversal segments that a client may normalise
    away, so they are rejected like every other path segment (see ``_q``).
    """
    if not isinstance(vuln_id, str) or not is_valid_osv_id(vuln_id):
        raise ValueError("invalid OSV id")
    return f"https://api.osv.dev/v1/vulns/{_q(vuln_id, 'OSV id')}"


# GitHub ---------------------------------------------------------------------


def github_graphql_url() -> str:
    """``POST /graphql``."""
    return "https://api.github.com/graphql"
