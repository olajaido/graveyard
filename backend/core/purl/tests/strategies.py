"""Hypothesis strategies for the purl property tests (design section 6.1).

Valid-domain values are built constructively. ``.filter`` is used only for
cheap rejections so the ``ci`` profile does not trip Hypothesis health checks.
"""

from __future__ import annotations

import dataclasses
import re
import string
import urllib.parse

from hypothesis import strategies as st

from core.purl.model import Ecosystem, Purl, normalise_pypi_name

# Exclude control (Cc), surrogate (Cs) and separator (Zs, Zl, Zp) characters. This
# covers everything ``str.isspace`` accepts, so no value contains whitespace or
# control characters. Non-ASCII characters remain.
_PLAIN_CHARS = st.characters(blacklist_categories=("Cc", "Cs", "Zs", "Zl", "Zp"))
_NAME_CHARS = st.characters(
    blacklist_categories=("Cc", "Cs", "Zs", "Zl", "Zp"), blacklist_characters="/@"
)
_SEGMENT_CHARS = st.characters(
    blacklist_categories=("Cc", "Cs", "Zs", "Zl", "Zp"), blacklist_characters="/"
)
_SPECIALS = "?#%+:"
_ASCII_NAME_CHARS = string.ascii_letters + string.digits + "._-"
_ASCII_ALNUM = string.ascii_letters + string.digits


def _with_interior_spaces(
    chars: st.SearchStrategy[str], max_size: int = 12
) -> st.SearchStrategy[str]:
    """Non-empty text with no leading or trailing whitespace; interior spaces allowed."""
    middle = st.text(st.one_of(chars, st.just(" ")), max_size=max_size)
    return st.builds(lambda a, m, b: a + m + b, chars, middle, chars) | chars


def _name_text() -> st.SearchStrategy[str]:
    """Non-empty text without ``/``, ``@``, whitespace or control characters."""
    chars = st.one_of(_NAME_CHARS, st.sampled_from(_SPECIALS))
    return st.text(chars, min_size=1, max_size=16)


def npm_scopes() -> st.SearchStrategy[str]:
    """npm namespaces: ``"@"`` plus a non-empty scope with no ``/`` or further ``@``."""
    return _name_text().map(lambda s: "@" + s)


def npm_names() -> st.SearchStrategy[str]:
    """npm package names (mixed case, specials ``?#%+:``, non-ASCII)."""
    return _name_text()


def pypi_names() -> st.SearchStrategy[str]:
    """Names matching ``PEP508_NAME`` with random case and separator runs.

    Not yet PEP 503-normalised; ``purls()`` applies ``normalise_pypi_name``.
    """
    alnum_run = st.text(_ASCII_ALNUM, min_size=1, max_size=6)
    separator = st.text(st.sampled_from("-_."), min_size=1, max_size=3)
    return st.builds(
        lambda first, rest: first + "".join(sep + tok for sep, tok in rest),
        alnum_run,
        st.lists(st.tuples(separator, alnum_run), max_size=3),
    )


def versions() -> st.SearchStrategy[str | None]:
    """``None`` or non-empty text without whitespace or control characters."""
    chars = st.one_of(_PLAIN_CHARS, st.sampled_from(_SPECIALS + "@+"))
    text = st.text(chars, min_size=1, max_size=16)
    semver = st.from_regex(r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}", fullmatch=True)
    return st.one_of(st.none(), text, semver)


def _qualifier_keys() -> st.SearchStrategy[str]:
    first = st.sampled_from(string.ascii_lowercase + ".-_")
    rest = st.text(st.sampled_from(string.ascii_lowercase + string.digits + ".-_"), max_size=8)
    return st.builds(lambda a, b: a + b, first, rest)


def qualifiers() -> st.SearchStrategy[tuple[tuple[str, str], ...]]:
    """0-3 canonical qualifiers: unique keys, sorted; values non-empty, trimmed."""
    value_chars = st.one_of(_PLAIN_CHARS, st.sampled_from(_SPECIALS + "@/"))
    value = _with_interior_spaces(value_chars)
    return st.dictionaries(_qualifier_keys(), value, max_size=3).map(
        lambda d: tuple(sorted(d.items()))
    )


def subpaths() -> st.SearchStrategy[str | None]:
    """``None`` or 1-3 segments, none empty, ``.`` or ``..``; interior spaces allowed."""
    chars = st.one_of(_SEGMENT_CHARS, st.sampled_from(_SPECIALS + "@"))
    segment = _with_interior_spaces(chars, max_size=8).filter(lambda s: s not in (".", ".."))
    return st.one_of(
        st.none(),
        st.lists(segment, min_size=1, max_size=3).map("/".join),
    )


@st.composite
def purls(draw: st.DrawFn) -> Purl:
    """Valid ``Purl`` values for both ecosystems."""
    ecosystem: Ecosystem = draw(st.sampled_from(["npm", "pypi"]))
    namespace: str | None
    if ecosystem == "npm":
        namespace = draw(st.one_of(st.none(), npm_scopes()))
        name = draw(npm_names())
    else:
        namespace = None
        name = normalise_pypi_name(draw(pypi_names()))
    return Purl(
        ecosystem=ecosystem,
        namespace=namespace,
        name=name,
        version=draw(versions()),
        qualifiers=draw(qualifiers()),
        subpath=draw(subpaths()),
    )


def _flip_ascii(text: str, flips: list[bool]) -> str:
    return "".join(
        c.swapcase() if flip and c in string.ascii_letters else c
        for c, flip in zip(text, flips, strict=True)
    )


def ascii_case_flip(purl: Purl) -> st.SearchStrategy[Purl]:
    """Copies of an npm ``Purl`` with a per-character ASCII case flip on namespace and name.

    Non-ASCII characters are left untouched.
    """
    ns = purl.namespace or ""
    return st.tuples(
        st.lists(st.booleans(), min_size=len(ns), max_size=len(ns)),
        st.lists(st.booleans(), min_size=len(purl.name), max_size=len(purl.name)),
    ).map(
        lambda t: dataclasses.replace(
            purl,
            namespace=None if purl.namespace is None else _flip_ascii(ns, t[0]),
            name=_flip_ascii(purl.name, t[1]),
        )
    )


# ---------------------------------------------------------------------------
# String strategies (PV-INV-1 to 4). The oracle below deliberately does not use
# ``core.purl``: it builds the canonical string with ``urllib.parse.quote`` and a
# test-local PEP 503.
# ---------------------------------------------------------------------------

_UNRESERVED = string.ascii_letters + string.digits + "_.-~"
_PEP503_SEP = re.compile(r"[-_.]+")


def _canon(text: str) -> str:
    """Canonical percent-encoding: everything but unreserved characters, ``/`` and ``:``."""
    return urllib.parse.quote(text, safe="/:")


def _pep503(name: str) -> str:
    return _PEP503_SEP.sub("-", name).lower()


def _expected_canonical(p: Purl) -> str:
    """Independent oracle: the canonical purl string for ``p``."""
    out = f"pkg:{p.ecosystem}/"
    if p.namespace:
        out += _canon(p.namespace) + "/"
    out += _canon(_pep503(p.name) if p.ecosystem == "pypi" else p.name)
    if p.version is not None:
        out += "@" + _canon(p.version)
    if p.qualifiers:
        out += "?" + "&".join(f"{k}={_canon(v)}" for k, v in sorted(p.qualifiers))
    if p.subpath:
        out += "#" + "/".join(_canon(seg) for seg in p.subpath.split("/"))
    return out


def _render(draw: st.DrawFn, text: str, *, slash_escape: bool = False) -> str:
    """Percent-encode ``text`` validly but non-canonically.

    Mandatory escapes are kept (optionally with lower-case hex); unreserved
    characters, ``:`` and (if allowed) ``/`` are sometimes escaped too.
    """
    modes = draw(st.lists(st.integers(0, 3), min_size=len(text), max_size=len(text)))
    out: list[str] = []
    for ch, mode in zip(text, modes, strict=True):
        piece = _canon(ch)
        if piece == ch:
            if ch in _UNRESERVED and mode == 1:
                piece = f"%{ord(ch):02X}"
            elif ch in _UNRESERVED and mode == 2:
                piece = f"%{ord(ch):02x}"
            elif ch == ":" and mode == 1:
                piece = "%3A"
            elif ch == "/" and slash_escape and mode == 1:
                piece = "%2F"
        elif mode == 2:
            piece = piece.lower()
        out.append(piece)
    return "".join(out)


def _random_case(draw: st.DrawFn, text: str) -> str:
    flips = draw(st.lists(st.booleans(), min_size=len(text), max_size=len(text)))
    return _flip_ascii(text, flips)


def _expand_pypi_name(draw: st.DrawFn, name: str) -> str:
    """Re-spell a PEP 503-normalised name: separator runs and random case."""
    parts = name.split("-")
    seps = [draw(st.text(st.sampled_from("-_."), min_size=1, max_size=3)) for _ in parts[1:]]
    raw = parts[0] + "".join(sep + part for sep, part in zip(seps, parts[1:], strict=True))
    return _random_case(draw, raw)


@st.composite
def purl_strings(draw: st.DrawFn) -> tuple[str, str]:
    """``(s, expected)``: a valid but non-canonical rendering and its canonical form."""
    p = draw(purls())
    expected = _expected_canonical(p)

    s = "pkg:" + draw(st.sampled_from(["", "//"])) + _random_case(draw, p.ecosystem) + "/"
    if p.namespace:
        scope = _render(draw, p.namespace[1:])
        s += draw(st.sampled_from(["@", "%40"])) + scope + "/"
    name = _expand_pypi_name(draw, p.name) if p.ecosystem == "pypi" else p.name
    s += _render(draw, name)
    if p.version is not None:
        s += "@" + _render(draw, p.version)
    if p.qualifiers:
        items = draw(st.permutations(list(p.qualifiers)))
        s += "?" + "&".join(
            f"{_random_case(draw, k)}={_render(draw, v, slash_escape=True)}" for k, v in items
        )
    if p.subpath:
        s += "#" + "/".join(_render(draw, seg) for seg in p.subpath.split("/"))
    return s, expected


_DISALLOWED_TYPES = (
    "maven",
    "github",
    "golang",
    "cargo",
    "gem",
    "nuget",
    "composer",
    "deb",
    "rpm",
    "docker",
    "generic",
    "hex",
    "pub",
    "cocoapods",
    "conan",
    "swift",
)
_SIMPLE_TOKEN = st.text(st.sampled_from(_ASCII_NAME_CHARS), min_size=1, max_size=8).filter(
    lambda t: t[0] in _ASCII_ALNUM and t[-1] in _ASCII_ALNUM
)


@st.composite
def disallowed_type_purls(draw: st.DrawFn) -> str:
    """Grammatically valid purls whose type is neither npm nor pypi."""
    s = "pkg:" + _random_case(draw, draw(st.sampled_from(_DISALLOWED_TYPES))) + "/"
    s += draw(st.one_of(st.just(""), _SIMPLE_TOKEN.map(lambda t: t + "/")))
    s += draw(_SIMPLE_TOKEN)
    version = draw(st.one_of(st.none(), _SIMPLE_TOKEN))
    if version is not None:
        s += "@" + version
    if draw(st.booleans()):
        s += "?" + draw(_SIMPLE_TOKEN).lower() + "=" + draw(_SIMPLE_TOKEN)
    return s


_ARBITRARY_CHARS = st.one_of(
    st.characters(codec=None),
    st.characters(categories=["Cs"]),
    st.characters(categories=["Cc", "Zs"]),
    st.sampled_from("%@/?#&=:+ \t\n"),
)


@st.composite
def _mutation(draw: st.DrawFn, s: str) -> str:
    """One structural mutation of ``s`` (the result may happen to be valid)."""
    kind = draw(st.integers(0, 10))
    i = draw(st.integers(0, max(len(s) - 1, 0)))
    if kind == 0:  # delete a character
        return s[:i] + s[i + 1 :]
    if kind == 1:  # duplicate a character
        return s[:i] + s[i] + s[i:]
    if kind == 2:  # swap adjacent characters
        j = min(i + 1, len(s) - 1)
        return s[:i] + s[j] + s[i] + s[j + 1 :] if j > i else s
    if kind == 3:  # stray %
        return s[:i] + "%" + s[i:]
    if kind == 4:  # stray or truncated escape
        return s[:i] + draw(st.sampled_from(["%", "%4", "%z", "%G1", "%%"])) + s[i:]
    if kind == 5:  # truncated escape at the end
        return s + draw(st.sampled_from(["%", "%2", "%4"]))
    if kind == 6:  # removed scheme
        return s.removeprefix("pkg:")
    if kind == 7:  # duplicate qualifier key
        head, sep, sub = s.partition("#")
        head += ("&" if "?" in head else "?") + "a=1&" + draw(st.sampled_from(["a", "A"])) + "=2"
        return head + sep + sub
    if kind == 8:  # empty version after @
        cut = min((k for k in (s.find("?"), s.find("#")) if k >= 0), default=len(s))
        return s[:cut] + "@" + s[cut:]
    if kind == 9:  # encoded slash inside the name
        return s[:i] + draw(st.sampled_from(["%2F", "%2f"])) + s[i:]
    return s[:i] + draw(_ARBITRARY_CHARS) + s[i:]  # arbitrary character injected


@st.composite
def invalid_purl_strings(draw: st.DrawFn) -> str:
    """Strings for PV-INV-4: ``parse_purl`` returns a ``Purl`` or raises ``ValueError``.

    Some outputs may happen to be valid; that is fine for PV-INV-4.
    """
    kind = draw(st.integers(0, 6))
    if kind == 0:  # arbitrary text, surrogates generated explicitly
        return draw(st.text(_ARBITRARY_CHARS, max_size=40))
    if kind == 1:  # "pkg:" prefix then arbitrary text
        return (
            "pkg:"
            + draw(st.sampled_from(["npm/", "pypi/", ""]))
            + draw(st.text(_ARBITRARY_CHARS, max_size=30))
        )
    if kind == 2:  # a lone surrogate placed inside an otherwise valid purl
        s = draw(purl_strings())[0]
        i = draw(st.integers(0, len(s)))
        return s[:i] + draw(st.characters(categories=["Cs"])) + s[i:]
    if kind == 3:  # longer than the 2,048-character cap
        head = draw(st.sampled_from(["pkg:npm/", "pkg:pypi/", ""]))
        pad = draw(st.sampled_from("abc0-_."))
        return head + pad * draw(st.integers(2049 - len(head), 4000))
    if kind == 4:  # disallowed types
        return draw(disallowed_type_purls())
    # mutations of valid purls, canonical or not
    base = draw(purl_strings())
    s = draw(_mutation(draw(st.sampled_from(base))))
    return s


# ---------------------------------------------------------------------------
# Repository-URL strategies (PV-INV-9 to 13). Built constructively and without
# ``core.purl``: the expected values are computed here, not by the code under test.
# ---------------------------------------------------------------------------

_REPO_CHARS = string.ascii_letters + string.digits + "_.-"
_REPO_ALNUM = string.ascii_letters + string.digits
_URL_SCHEME_CHOICES = ("https", "http", "git+https", "git", "git+ssh", "ssh")
_SSH_SCHEMES = ("git+ssh", "ssh")


def _owner_names() -> st.SearchStrategy[str]:
    """Non-empty ``[A-Za-z0-9_.-]`` owners, never ``.`` or ``..``."""
    return st.text(_REPO_CHARS, min_size=1, max_size=12).map(
        lambda s: "o" + s if s in (".", "..") else s
    )


def _repo_names() -> st.SearchStrategy[str]:
    """Non-empty ``[A-Za-z0-9_.-]`` repos that ``.git`` stripping leaves unchanged.

    Never ``.``, ``..`` or anything ending in ``.git`` (so the expected value is
    the post-strip value).
    """

    def fix(s: str) -> str:
        if s in (".", ".."):
            s = "r" + s
        return s + "x" if s.endswith(".git") else s

    return st.text(_REPO_CHARS, min_size=1, max_size=12).map(fix)


def _path_segments() -> st.SearchStrategy[str]:
    """Extra path segment: never empty, ``.`` or ``..``; no ``%`` or whitespace."""
    return st.builds(
        lambda head, tail: head + tail,
        st.sampled_from(_REPO_ALNUM),
        st.text(_REPO_CHARS, max_size=8),
    )


def _tail_text() -> st.SearchStrategy[str]:
    """Query or fragment body: no ``%``, whitespace, control characters or backslash."""
    return st.text(st.sampled_from(_REPO_ALNUM + "=&-_.~/@:+,;"), max_size=12)


@st.composite
def _github_host(draw: st.DrawFn, *, allow_www: bool) -> str:
    host = draw(st.sampled_from(["github.com", "www.github.com"] if allow_www else ["github.com"]))
    return _random_case(draw, host)


@st.composite
def repo_urls(draw: st.DrawFn) -> tuple[str, str, str]:
    """``(url, owner, repo)``: an accepted form with random PV-REPO-3/4 suffixes.

    ``repo`` is the expected post-``.git``-strip value; the normaliser's result is
    ``f"github.com/{owner}/{repo}"``.
    """
    owner = draw(_owner_names())
    repo = draw(_repo_names())
    form = draw(
        st.sampled_from(["url", "url", "scp", "shorthand", "schemeless"])
    )  # weight URL forms
    path = f"{owner}/{repo}" + ".git" * draw(st.integers(0, 3))

    if form == "url":
        scheme = draw(st.sampled_from(_URL_SCHEME_CHOICES))
        userinfo = "git@" if scheme in _SSH_SCHEMES or draw(st.booleans()) else ""
        if scheme not in _SSH_SCHEMES and scheme != "git":
            userinfo = ""
        head = f"{_random_case(draw, scheme)}://{userinfo}{draw(_github_host(allow_www=True))}/"
    elif form == "scp":
        head = f"git@{draw(_github_host(allow_www=False))}:"
    elif form == "shorthand":
        head = _random_case(draw, "github") + ":"
    else:
        head = draw(_github_host(allow_www=False)) + "/"

    url = head + path
    if draw(st.booleans()):  # trailing slash
        url += "/"
    extras = draw(st.lists(_path_segments(), max_size=3))
    if extras:
        url += ("" if url.endswith("/") else "/") + "/".join(extras)
        if draw(st.booleans()):
            url += "/"
    if draw(st.booleans()):
        url += "?" + draw(_tail_text())
    if draw(st.booleans()):
        url += "#" + draw(_tail_text())
    return url, owner, repo


_BAD_TOKENS = (
    "%2e",
    "%2E",
    "%2f",
    "%2F",
    "%5c",
    "%5C",
    "\\",
    " ",
    "\t",
    "\n",
    "\r",
    "\x0b",
    "\x0c",
    "\x00",
    "\x07",
    "\x1b",
    "\x7f",
    "\x85",
    "\xa0",
    "\u2003",
    "\u2028",
)


@st.composite
def _poisoned_valid_url(draw: st.DrawFn) -> str:
    """A valid URL with a backslash, encoded ``.``/``/``/``\\`` or whitespace/control inserted."""
    url = draw(repo_urls())[0]
    i = draw(st.integers(1, len(url) - 1))  # interior: never stripped away
    return url[:i] + draw(st.sampled_from(_BAD_TOKENS)) + url[i:]


def _label() -> st.SearchStrategy[str]:
    """Lower-case ASCII label starting with a letter that is not ``w`` or ``g``-only risky."""
    return st.text(string.ascii_lowercase + string.digits, min_size=1, max_size=8).map(
        lambda s: "a" + s
    )


_LOOKALIKE_SUBS = (
    ("i", "\u0456"),
    ("i", "\u0131"),
    ("t", "\u0163"),
    ("h", "\u04bb"),
    ("o", "\u043e"),
    ("c", "\u0441"),
    ("g", "\u0261"),
    (".", "\u3002"),
    (".", "\uff0e"),
    ("b", "\u0185"),
)


@st.composite
def _evil_hosts(draw: st.DrawFn) -> str:
    """Hosts that are not exactly ``github.com`` / ``www.github.com`` and carry no port."""
    kind = draw(st.integers(0, 9))
    label = draw(_label())
    tld = draw(st.sampled_from(["org", "net", "io", "dev", "co.uk"]))
    if kind == 0:
        return f"{label}.{tld}"
    if kind == 1:
        return f"github.com.{label}.{tld}"
    if kind == 2:
        return f"{label}github.com"
    if kind == 3:
        return f"{label}.github.com"
    if kind == 4:
        return "github.com."
    if kind == 5:
        octets = draw(st.lists(st.integers(0, 255), min_size=4, max_size=4))
        return ".".join(map(str, octets))
    if kind == 6:
        return draw(st.sampled_from(["[::1]", "[2001:db8::1]", "[::ffff:140.82.112.3]"]))
    if kind == 7:
        old, new = draw(st.sampled_from(_LOOKALIKE_SUBS))
        return "github.com".replace(old, new, 1)
    if kind == 8:
        return draw(
            st.sampled_from(
                [
                    "gist.github.com",
                    "api.github.com",
                    "raw.githubusercontent.com",
                    "gitlab.com",
                    "bitbucket.org",
                    "github.io",
                    "evilgithub.com",
                    "www.github.com.",
                    "www2.github.com",
                    "github.com\u200b",
                ]
            )
        )
    return "github.com" + draw(st.sampled_from(["\u212a", "\u0435", "\u00e9", "\u2024com"]))


@st.composite
def _userinfo_hosts(draw: st.DrawFn) -> str:
    """Authorities using userinfo or fragment/query tricks (no valid ``git@`` plus GitHub)."""
    evil = draw(_evil_hosts())
    user = draw(_label())
    kind = draw(st.integers(0, 7))
    if kind == 0:
        return f"github.com@{evil}"
    if kind == 1:
        return f"{user}:{draw(_label())}@github.com"
    if kind == 2:
        return f"{evil}#@github.com"
    if kind == 3:
        return f"{evil}?@github.com"
    if kind == 4:
        return f"{user}@github.com"
    if kind == 5:
        return f"git@{evil}"
    if kind == 6:
        return draw(st.sampled_from(["Git", "GIT", "git:x", "git@git", "@"])) + "@github.com"
    return f"git@github.com@{evil}"


@st.composite
def _ported_hosts(draw: st.DrawFn) -> str:
    host = draw(_github_host(allow_www=True))
    userinfo = draw(st.sampled_from(["", "git@"]))
    port = draw(st.sampled_from(["", "22", "80", "443", "8443", "0", "99999"]))
    return f"{userinfo}{host}:{port}"


@st.composite
def _traversal_path(draw: st.DrawFn) -> str:
    """Valid owner/repo plus extra segments with at least one ``.``/``..`` segment."""
    segs = [draw(_owner_names()), draw(_repo_names())]
    segs += draw(st.lists(_path_segments(), max_size=2))
    dots = draw(st.lists(st.sampled_from([".", ".."]), min_size=1, max_size=2))
    for dot in dots:
        segs.insert(draw(st.integers(0, len(segs))), dot)
    return "/".join(segs) + draw(st.sampled_from(["", "/"]))


@st.composite
def _bad_segment_path(draw: st.DrawFn) -> str:
    """Paths whose owner or repo is empty, dot-only, or has an illegal character."""
    owner, repo = draw(_owner_names()), draw(_repo_names())
    kind = draw(st.integers(0, 7))
    if kind == 0:
        return owner  # no repo
    if kind == 1:
        return owner + "/"
    if kind == 2:
        return "/" + repo  # empty owner
    if kind == 3:
        return f"{owner}/.git" + ".git" * draw(st.integers(0, 2))  # repo strips to empty
    if kind == 4:
        return ""
    bad = draw(st.sampled_from("!$&'()*+,;=:@~[]{}|<>\"^`\u00e9\u0456\u4e2d"))
    if kind == 5:
        return f"{owner}{bad}/{repo}"
    if kind == 6:
        return f"{owner}/{repo}{bad}"
    return f"{owner}/{bad}{repo}"


@st.composite
def adversarial_repo_urls(draw: st.DrawFn) -> str:
    """URLs that must normalise to ``None`` (PV-INV-11).

    Families: other hosts, userinfo tricks, ports, traversal, encoded ``%2e``/``%2f``/
    ``%5c``, backslash, whitespace/control characters, other schemes and shorthands,
    malformed owner/repo, bare ``owner/repo``, over-long input.
    """
    family = draw(st.integers(0, 10))
    owner, repo = draw(_owner_names()), draw(_repo_names())
    good = f"{owner}/{repo}" + draw(st.sampled_from(["", ".git", "/", "/tree/main"]))
    scheme = _random_case(draw, draw(st.sampled_from(_URL_SCHEME_CHOICES)))

    if family == 0:  # other hosts
        return f"{scheme}://{draw(_evil_hosts())}/{good}"
    if family == 1:  # other hosts, scheme-less and scp-like
        host = draw(_evil_hosts())
        return f"{host}/{good}" if draw(st.booleans()) else f"git@{host}:{good}"
    if family == 2:  # userinfo tricks
        auth = draw(_userinfo_hosts())
        return (f"{scheme}://{auth}/{good}") if draw(st.booleans()) else f"{auth}/{good}"
    if family == 3:  # explicit ports
        auth = draw(_ported_hosts())
        if draw(st.booleans()):
            return f"{scheme}://{auth}/{good}"
        return f"{auth.removeprefix('git@')}/{good}"  # "git@host:22/o/r" would be scp-like
    if family == 4:  # traversal
        path = draw(_traversal_path())
        return draw(st.sampled_from([f"{scheme}://github.com/", "github.com/", "github:"])) + path
    if family == 5:  # encoded . / \, backslash, whitespace, control characters
        return draw(_poisoned_valid_url())
    if family == 6:  # other schemes and shorthands
        prefix = draw(
            st.sampled_from(
                [
                    "ftp://github.com/",
                    "file:///github.com/",
                    "svn://github.com/",
                    "git+file://github.com/",
                    "git+http://github.com/",
                    "javascript://github.com/",
                    "gitlab:",
                    "bitbucket:",
                    "gist:",
                    "file:",
                    "https:/github.com/",
                    "https:github.com/",
                    "//github.com/",
                    "http//github.com/",
                    "git@www.github.com:",
                    "git@github.com/",
                    "https://",
                    "ssh://git@evil.com:",
                ]
            )
        )
        return prefix + good
    if family == 7:  # malformed owner or repo
        path = draw(_bad_segment_path())
        head = draw(
            st.sampled_from(
                [f"{scheme}://github.com/", "github.com/", "github:", "git@github.com:"]
            )
        )
        return head + path
    if family == 8:  # bare owner/repo, no host
        return f"{owner.replace('.', 'o')}/{repo}"
    if family == 9:  # empty, whitespace-only, host only
        return draw(
            st.sampled_from(
                [
                    "",
                    " ",
                    "\t\n",
                    "github.com",
                    "https://github.com",
                    "https://github.com/",
                    "github:",
                ]
            )
        )
    # longer than the 2,048-character cap
    pad = "a" * draw(st.integers(2049, 3000))
    return f"https://github.com/{owner}/{pad}"
