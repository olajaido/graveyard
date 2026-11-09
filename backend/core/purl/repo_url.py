"""GitHub repository-URL normaliser (design section 5, PV-REPO-1..12, EX-9).

``normalise_repo_url`` maps every supported GitHub URL form to
``github.com/<owner>/<repo>`` or ``None``. It is a pure string function: it never
decodes, follows or fetches anything, and it does not use ``urllib.parse`` (which
silently drops tab/CR/LF, raises on bad IPv6 brackets and treats ``\\`` as an
ordinary character). Every rule returns ``None`` on doubt (threat T2).
"""

from __future__ import annotations

import re

from core.purl.model import MAX_INPUT_LEN, REPO_OUT, SEGMENT, WS_OR_CTRL

_ASCII_WS = " \t\r\n\f\v"
_ENCODED_DANGER = re.compile(r"%(2e|2f|5c)", re.IGNORECASE)
_URL_SCHEMES: frozenset[str] = frozenset({"https", "http", "git+https", "git", "git+ssh", "ssh"})
_HOSTS: frozenset[str] = frozenset({"github.com", "www.github.com"})
_SCP_PREFIX = "git@"
_SHORTHAND_PREFIX = "github:"
_GIT_SUFFIX = ".git"


def _host_ok(host: str) -> bool:
    return host.isascii() and host.lower() in _HOSTS


def _authority_ok(authority: str) -> bool:
    """Userinfo must be absent or exactly ``git``; no port; host must be GitHub."""
    userinfo, at, host = authority.rpartition("@")
    if at and userinfo != "git":
        return False
    if ":" in host:
        return False
    return _host_ok(host)


def _owner_repo(path: str) -> str | None:
    segments = path.split("/")
    if any(seg in (".", "..") for seg in segments):
        return None
    if len(segments) < 2:
        return None
    owner, repo = segments[0], segments[1]
    while repo.endswith(_GIT_SUFFIX):
        repo = repo[: -len(_GIT_SUFFIX)]
    for seg in (owner, repo):
        if seg in ("", ".", "..") or not SEGMENT.fullmatch(seg):
            return None
    return f"github.com/{owner}/{repo}"


def normalise_repo_url(raw: str) -> str | None:
    """Return ``github.com/<owner>/<repo>`` for a supported GitHub URL, else ``None``.

    Never raises. Owner and repo keep their case; only the host is compared
    case-insensitively. ``repo_key`` (separate) provides the case-folded key.
    """
    try:
        if not isinstance(raw, str):
            return None
        s = raw.strip(_ASCII_WS)
        if s == "" or len(s) > MAX_INPUT_LEN:
            return None
        if WS_OR_CTRL.search(s) or "\\" in s:
            return None
        if _ENCODED_DANGER.search(s):
            return None

        # Cut fragment first, then query, so "https://evil.com#@github.com/o/r"
        # is judged as "https://evil.com".
        s = s.split("#", 1)[0].split("?", 1)[0]

        lowered = s.lower()
        if "://" in s:
            scheme, _, rest = s.partition("://")
            if scheme.lower() not in _URL_SCHEMES:
                return None
            authority, _, path = rest.partition("/")
            if not _authority_ok(authority):
                return None
        elif lowered.startswith(_SCP_PREFIX):
            # scp-like: git@github.com:<o>/<r>. Only the bare github.com host.
            host, colon, path = s[len(_SCP_PREFIX) :].partition(":")
            if not colon or host.lower() != "github.com":
                return None
        elif lowered.startswith(_SHORTHAND_PREFIX):
            path = s[len(_SHORTHAND_PREFIX) :]
        else:
            # Scheme-less "github.com/<o>/<r>". Anything else with a "<word>:"
            # prefix fails the port check; bare "owner/repo" fails the host check.
            authority, _, path = s.partition("/")
            if not _authority_ok(authority):
                return None

        return _owner_repo(path)
    except Exception:
        return None


def repo_key(repo: str) -> str:
    """Return the case-folded key for a normalised repo (PV-RKEY-1, PV-RKEY-2).

    Use this key for dedupe and caching of repo-level signals: GitHub owner and
    repo names are case-insensitive, while ``normalise_repo_url`` keeps case for
    display and links. Callers must normalise first; the input has to be
    ``normalise_repo_url`` output (``github.com/<owner>/<repo>``).

    Raises ``ValueError`` for anything else, including non-``str`` input. That
    is a programming error, not untrusted-input handling.
    """
    if not isinstance(repo, str) or not REPO_OUT.fullmatch(repo):
        raise ValueError(
            f"repo_key: input is not normalised github.com/<owner>/<repo>: {repr(repo)[:100]}"
        )
    return repo.lower()
