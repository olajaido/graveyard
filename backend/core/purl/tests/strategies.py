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
