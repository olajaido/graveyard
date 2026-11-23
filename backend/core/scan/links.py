"""Human-readable link-outs for the evidence of one package (ui-core B6, UI-B-6).

The evidence of a node keeps the API endpoints it was read from (``api.deps.dev``,
``registry.npmjs.org``, ``api.osv.dev/v1/querybatch``). A reader needs pages, so the certificate
adds ``evidenceLinks``: a few links to the registry page, the repository, deps.dev and one page per
advisory. No text from any source is read or stored.

Safety rules (maintainer decision, 23 Nov 2026):

- A URL is built only from a constant ``https://<host>/`` template and the components of the
  *parsed* purl, the validated repo and the validated advisory IDs. Every component is
  percent-encoded, so it cannot add a path segment, a query, a fragment, user information or
  another host.
- The host is never taken from input. After building, ``_checked`` asserts the scheme is
  ``https``, the host is one of ``HOSTS`` and there is no user information, query or fragment. A
  link that fails the check is dropped.
- Pure: no I/O.
"""

from __future__ import annotations

import re
from typing import Any, Final
from urllib.parse import quote, urlsplit

from core.purl import Purl, parse_purl, registry_name

NPM: Final = "www.npmjs.com"
PYPI: Final = "pypi.org"
GITHUB: Final = "github.com"
OSV: Final = "osv.dev"
DEPS_DEV: Final = "deps.dev"
HOSTS: Final = frozenset({NPM, PYPI, GITHUB, OSV, DEPS_DEV})

KINDS: Final = ("registry", "repository", "deps_dev", "advisory")
MAX_ADVISORIES: Final = 50

_REPO: Final = re.compile(r"github\.com/([A-Za-z0-9-]{1,39})/([A-Za-z0-9._-]{1,100})")
_ADVISORY: Final = re.compile(r"[A-Za-z0-9._:-]{1,100}")

_REGISTRY_SIGNALS: Final = {
    "npm": [
        "s1_declared_death",
        "s1b_version_deprecated",
        "s2_latest_release_at",
        "s9_weekly_downloads",
    ],
    "pypi": ["s2_latest_release_at", "s9_weekly_downloads"],
}
_REPOSITORY_SIGNALS: Final = [
    "s1_declared_death",
    "s3_last_push_at",
    "s5_committers",
    "s6_open_issues",
    "s6_closed_issues",
]
_DEPS_DEV_SIGNALS: Final = ["s4_maintained", "s8_overall"]


def _checked(url: str) -> str | None:
    """The URL when it is ``https`` on an allowed host, with no user info, query or fragment."""
    try:
        parts = urlsplit(url)
        host = parts.hostname
        user_info = parts.username is not None or parts.password is not None
    except ValueError:
        return None
    if (
        parts.scheme != "https"
        or host not in HOSTS
        or user_info
        or parts.query
        or parts.fragment
        or "@" in parts.netloc
        or any(ch in url for ch in " \t\r\n\\")
    ):
        return None
    return url


def _registry_url(p: Purl) -> str:
    if p.ecosystem == "npm":
        scope = f"{quote(p.namespace, safe='@')}/" if p.namespace else ""
        version = f"/v/{quote(p.version, safe='')}" if p.version else ""
        return f"https://{NPM}/package/{scope}{quote(p.name, safe='')}{version}"
    version = f"{quote(p.version, safe='')}/" if p.version else ""
    return f"https://{PYPI}/project/{quote(p.name, safe='')}/{version}"


def _deps_dev_url(p: Purl) -> str:
    version = f"/{quote(p.version, safe='')}" if p.version else ""
    system = quote(p.ecosystem, safe="")
    return f"https://{DEPS_DEV}/{system}/{quote(registry_name(p), safe='')}{version}"


def evidence_links(purl: str, repo: str | None, advisory_ids: list[str]) -> list[dict[str, Any]]:
    """The link-outs of one package, ordered registry, repository, deps.dev, then advisories by ID.

    ``repo`` is the stored ``github.com/<owner>/<name>`` (or ``None``); ``advisory_ids`` are the IDs
    in ``signals.s7_advisories``. Anything malformed is skipped, never repaired.
    """
    try:
        p = parse_purl(purl)
    except ValueError:
        return []
    if p.ecosystem not in _REGISTRY_SIGNALS:
        return []
    links: list[dict[str, Any]] = []

    def add(kind: str, url: str, signals: list[str]) -> None:
        checked = _checked(url)
        if checked is not None:
            links.append({"kind": kind, "url": checked, "signals": list(signals)})

    add("registry", _registry_url(p), _REGISTRY_SIGNALS[p.ecosystem])
    match = _REPO.fullmatch(repo) if isinstance(repo, str) else None
    if match is not None:
        owner, name = match.groups()
        add(
            "repository",
            f"https://{GITHUB}/{quote(owner, safe='')}/{quote(name, safe='')}",
            _REPOSITORY_SIGNALS,
        )
    add("deps_dev", _deps_dev_url(p), _DEPS_DEV_SIGNALS)
    valid = sorted(
        {a for a in advisory_ids if isinstance(a, str) and _ADVISORY.fullmatch(a) is not None}
    )
    for advisory in valid[:MAX_ADVISORIES]:
        add(
            "advisory", f"https://{OSV}/vulnerability/{quote(advisory, safe='')}", ["s7_advisories"]
        )
    return links
