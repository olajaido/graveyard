"""Hypothesis strategies for the install-command parser property tests (design 10.1).

The generator works backwards from the answer: it draws the expected targets first
and renders a command from them, so the oracle is the input and not a second parser.
The option tables in ``core.install.profiles`` supply the options to insert; the
spellings of each spec come from KPW-PARSE-9 and KPW-PARSE-10 (a caret is a ``Range``).

Nothing here parses a command line.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal

from hypothesis import strategies as st

from core.install.model import Latest, Pinned, Range, Spec, Target
from core.install.profiles import (
    NPM,
    PIP,
    PNPM,
    POETRY,
    PROFILES,
    UV_ADD,
    UV_PIP,
    YARN,
    Kind,
    Profile,
)

Ecosystem = Literal["npm", "pypi"]
Where = Literal["global", "verb"]

ECOSYSTEMS: Final[tuple[Ecosystem, Ecosystem]] = ("npm", "pypi")
WHERES: Final[tuple[Where, Where]] = ("global", "verb")

# --- shapes: program, head spellings and verb spellings --------------------------------


@dataclass(frozen=True)
class Shape:
    """One program family: how its command starts and which tokens carry the verb."""

    label: str
    profile: Profile
    ecosystem: Ecosystem
    heads: tuple[tuple[str, ...], ...]  # tokens before the global options
    verbs: tuple[tuple[str, ...], ...]  # tokens from the verb on

    @property
    def poetry(self) -> bool:
        return self.profile is POETRY

    @property
    def has_reqfile(self) -> bool:
        return Kind.REQFILE in self.profile.verb_options.values()


SHAPES: Final[tuple[Shape, ...]] = (
    Shape("npm", NPM, "npm", (("npm",), ("/usr/local/bin/npm",)), (("install",), ("i",), ("add",))),
    Shape("pnpm", PNPM, "npm", (("pnpm",),), (("add",), ("install",), ("i",))),
    Shape("yarn", YARN, "npm", (("yarn",),), (("add",), ("workspace", "web", "add"))),
    Shape(
        "pip",
        PIP,
        "pypi",
        (
            ("pip",),
            ("pip3",),
            ("pip3.11",),
            ("/usr/bin/pip",),
            ("python", "-m", "pip"),
            ("python3", "-m", "pip"),
            ("python3.12", "-m", "pip"),
            ("py", "-m", "pip"),
        ),
        (("install",),),
    ),
    Shape("uv_add", UV_ADD, "pypi", (("uv",),), (("add",),)),
    Shape("uv_pip", UV_PIP, "pypi", (("uv",),), (("pip", "install"),)),
    Shape("poetry", POETRY, "pypi", (("poetry",),), (("add",),)),
)

assert [s.profile.name for s in SHAPES] == [p.name for p in PROFILES]


def shape_for(profile: Profile) -> Shape:
    return next(s for s in SHAPES if s.profile is profile)


# --- names, versions and specs ---------------------------------------------------------

_PART: Final = st.from_regex(r"[a-z][a-z0-9]{0,5}", fullmatch=True)
_WORD_PART: Final = st.from_regex(r"[a-z0-9]{1,5}", fullmatch=True)


@st.composite
def _joined(draw: st.DrawFn, seps: Sequence[str]) -> str:
    parts = draw(st.lists(_PART, min_size=1, max_size=3))
    out = parts[0]
    for part in parts[1:]:
        out += draw(st.sampled_from(seps)) + part
    return out


@st.composite
def npm_names(draw: st.DrawFn) -> str:
    """A plain or scoped npm name that ``core.purl`` accepts."""
    plain = draw(_joined(("-", ".", "_")))
    if draw(st.integers(0, 2)) == 0:
        return "@" + draw(_joined(("-",))) + "/" + plain
    return plain


@st.composite
def pypi_canonical_names(draw: st.DrawFn) -> str:
    """A PEP 503 normalised name (lower case, single hyphens)."""
    first = draw(_PART)
    rest = draw(st.lists(_WORD_PART, max_size=2))
    return "-".join([first, *rest])


@st.composite
def _spell_pypi_name(draw: st.DrawFn, canonical: str) -> str:
    """Respell a normalised name with random separators and case (same name after PEP 503)."""
    pieces = canonical.split("-")
    out = ""
    for index, piece in enumerate(pieces):
        case = draw(st.integers(0, 2))
        out += piece.upper() if case == 1 else piece.capitalize() if case == 2 else piece
        if index < len(pieces) - 1:
            out += draw(st.sampled_from(("-", "_", ".", "--", "_.")))
    return out


_INT: Final = st.integers(0, 30)
_TRIPLE: Final = st.tuples(_INT, _INT, _INT).map(lambda t: f"{t[0]}.{t[1]}.{t[2]}")
_NPM_PINNED: Final = st.tuples(
    _TRIPLE, st.sampled_from(("", "", "-beta.1", "-rc.2", "-alpha"))
).map(lambda t: t[0] + t[1])
_PY_RELEASE: Final = st.lists(_INT, min_size=1, max_size=3).map(
    lambda xs: ".".join(str(x) for x in xs)
)
_PY_VERSION: Final = st.tuples(
    _PY_RELEASE, st.sampled_from(("", "", "rc1", ".post2", ".dev0", "a1"))
).map(lambda t: t[0] + t[1])


def npm_spec_texts(spec: Spec) -> st.SearchStrategy[str]:
    """Spellings of ``spec`` after an npm name (KPW-PARSE-9): ``""`` or ``"@..."``."""
    if isinstance(spec, Pinned):
        return st.sampled_from(("", "=", "v")).map(lambda p: "@" + p + spec.version)
    if isinstance(spec, Latest):
        return st.one_of(
            st.sampled_from(("", "@latest", "@*")),
            _TRIPLE.map(lambda v: "@>=" + v),
            _TRIPLE.map(lambda v: "@>" + v),
            _TRIPLE.map(lambda v: "@>= " + v),
        )
    return st.one_of(
        _TRIPLE.map(lambda v: "@^" + v),
        _TRIPLE.map(lambda v: "@~" + v),
        st.tuples(_INT, _INT).map(lambda t: f"@~{t[0]}.{t[1]}"),
        _TRIPLE.map(lambda v: "@<" + v),
        _TRIPLE.map(lambda v: "@<=" + v),
        _INT.map(lambda m: f"@{m}.x"),
        st.tuples(_INT, _INT).map(lambda t: f"@{t[0]}.{t[1]}.x"),
        _INT.map(lambda m: f"@{m}"),
        st.tuples(_INT, _INT).map(lambda t: f"@{t[0]}.{t[1]}"),
        st.tuples(_INT, _INT).map(lambda t: f"@{t[0]} || {t[1]}"),
        st.tuples(_INT, _INT).map(lambda t: f"@^{t[0]} || ^{t[1]}"),
        st.tuples(_TRIPLE, _TRIPLE).map(lambda t: f"@{t[0]} - {t[1]}"),
        st.tuples(_TRIPLE, _TRIPLE).map(lambda t: f"@>={t[0]} <{t[1]}"),
    )


_MARKERS: Final = (
    "",
    "",
    '; python_version < "3.9"',
    ';sys_platform=="linux"',
    "; os_name != 'nt'",
)
_EXTRAS: Final = ("", "", "[security]", "[a,b]", "[socks, extra]")


@st.composite
def pypi_arg_text(draw: st.DrawFn, target: Target, *, poetry: bool) -> str:
    """One PEP 508 argument for ``target`` (KPW-PARSE-10), with extras and markers."""
    name = draw(_spell_pypi_name(target.name))
    extras = draw(st.sampled_from(_EXTRAS))
    spec = target.spec
    if poetry and draw(st.booleans()):
        # poetry's ``name@SPEC`` spellings
        if isinstance(spec, Pinned):
            return f"{name}{extras}@{spec.version}"
        if isinstance(spec, Latest):
            return f"{name}{extras}@" + draw(st.sampled_from(("latest", "*")))
        return f"{name}{extras}@" + draw(
            st.one_of(
                _TRIPLE.map(lambda v: "^" + v),
                _TRIPLE.map(lambda v: "~" + v),
                st.tuples(_INT, _INT).map(lambda t: f"^{t[0]}.{t[1]}"),
            )
        )
    pad = draw(st.sampled_from(("", " ")))
    body: str
    if isinstance(spec, Pinned):
        body = draw(st.sampled_from(("==", "==="))) + pad + spec.version
    elif isinstance(spec, Latest):
        body = draw(
            st.one_of(
                st.just(""),
                _PY_VERSION.map(lambda v: ">=" + pad + v),
                _PY_VERSION.map(lambda v: ">" + pad + v),
            )
        )
    else:
        body = draw(
            st.one_of(
                _PY_VERSION.map(lambda v: "<" + pad + v),
                _PY_VERSION.map(lambda v: "<=" + pad + v),
                _PY_VERSION.map(lambda v: "~=" + pad + v),
                _PY_VERSION.map(lambda v: "!=" + pad + v),
                _PY_RELEASE.map(lambda v: "==" + pad + v + ".*"),
                st.tuples(_PY_VERSION, _PY_VERSION).map(lambda t: f">={t[0]},{pad}<{t[1]}"),
                st.tuples(_PY_VERSION, _PY_VERSION).map(lambda t: f"<{t[0]},!={t[1]}"),
            )
        )
    marker = draw(st.sampled_from(_MARKERS))
    lead = pad if body else ""
    return f"{name}{extras}{lead}{body}{marker}"


@st.composite
def render_target(draw: st.DrawFn, target: Target, *, poetry: bool = False) -> str:
    """One argument for ``target`` in a spelling allowed for its ``Spec``."""
    if target.ecosystem == "npm":
        return target.name + draw(npm_spec_texts(target.spec))
    return draw(pypi_arg_text(target, poetry=poetry))


@st.composite
def target(draw: st.DrawFn, ecosystem: Ecosystem) -> Target:
    """One expected target: a valid name and a ``Pinned``, ``Latest`` or ``Range`` spec."""
    spec_kind = draw(st.integers(0, 2))
    spec: Spec
    if spec_kind == 0:
        spec = Pinned(draw(_NPM_PINNED if ecosystem == "npm" else _PY_VERSION))
    elif spec_kind == 1:
        spec = Latest()
    else:
        spec = Range()
    name = draw(npm_names() if ecosystem == "npm" else pypi_canonical_names())
    return Target(ecosystem, name, spec)


def _distinct(
    ecosystem: Ecosystem, min_size: int, max_size: int
) -> st.SearchStrategy[list[Target]]:
    return st.lists(
        target(ecosystem), min_size=min_size, max_size=max_size, unique_by=lambda t: t.name
    )


@st.composite
def expected_targets(
    draw: st.DrawFn, *, ecosystem: Ecosystem | None = None, min_size: int = 1, max_size: int = 4
) -> tuple[Target, ...]:
    """1..4 targets with distinct keys; mixed npm and PyPI lists when ``ecosystem`` is ``None``."""
    if ecosystem is not None:
        return tuple(draw(_distinct(ecosystem, min_size, max_size)))
    pick = draw(st.integers(0, 3))
    if pick < 2:
        return tuple(draw(_distinct(ECOSYSTEMS[pick], min_size, max_size)))
    first, second = ECOSYSTEMS if pick == 2 else (ECOSYSTEMS[1], ECOSYSTEMS[0])
    return tuple(draw(_distinct(first, 1, 2))) + tuple(draw(_distinct(second, 1, 2)))


# --- quoting ---------------------------------------------------------------------------

_SAFE: Final = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789@%+=:,./_-")
_DOUBLE_UNSAFE: Final = frozenset('$`"\\!')


@st.composite
def quoted(draw: st.DrawFn, text: str) -> str:
    """``text`` as one shell word: bare, single or double quoted where its characters allow."""
    style = draw(st.sampled_from(("none", "single", "double")))
    if style == "none" and text and all(c in _SAFE for c in text):
        return text
    if style == "double" and not any(c in _DOUBLE_UNSAFE for c in text):
        return f'"{text}"'
    return "'" + text.replace("'", "'\\''") + "'"


# --- options ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OptGroup:
    """The tokens of one rendered option and what it contributes to the result."""

    tokens: tuple[str, ...]
    ref: str | None = None  # expected RequirementRef path
    skipped: int = 0  # expected skipped count


_VALUES: Final = st.from_regex(r"v[a-z0-9]{2,5}", fullmatch=True)
_REF_PATHS: Final = st.sampled_from(("requirements.txt", "req/dev.txt", "a-b.txt", "r.txt"))
_CONSTRAINT_PATHS: Final = st.sampled_from(("constraints.txt", "c/pins.txt"))
_EDITABLE_PATHS: Final = st.sampled_from((".", "./local", "../sibling"))


@st.composite
def render_option(draw: st.DrawFn, name: str, kind: Kind, *, only_eq: bool = False) -> OptGroup:
    """Render one option in a spelling its kind allows: ``--o v``, ``--o=v`` or ``-Ov``."""
    if kind is Kind.BOOL:
        return OptGroup((name,))
    if kind is Kind.REGISTRY:
        value = "https://registry.example/simple"
    elif kind is Kind.REQFILE:
        value = draw(_REF_PATHS)
    elif kind is Kind.CONSTRAINT:
        value = draw(_CONSTRAINT_PATHS)
    elif kind is Kind.EDITABLE:
        value = draw(_EDITABLE_PATHS)
    else:
        value = draw(_VALUES)
    forms = ["eq"] if only_eq else ["sep"]
    if not only_eq and name.startswith("--"):
        forms.append("eq")
    if not only_eq and len(name) == 2 and name[0] == "-" and name[1] != "-":
        forms.append("attached")
    form = draw(st.sampled_from(forms))
    shown = draw(quoted(value))
    tokens = (
        (name, shown)
        if form == "sep"
        else (f"{name}={shown}",)
        if form == "eq"
        else (f"{name}{shown}",)
    )
    return OptGroup(
        tokens,
        ref=value if kind is Kind.REQFILE else None,
        skipped=1 if kind in (Kind.CONSTRAINT, Kind.EDITABLE) else 0,
    )


def _candidates(profile: Profile, where: Where, kinds: frozenset[Kind]) -> list[tuple[str, Kind]]:
    table = profile.global_options if where == "global" else profile.verb_options
    out = [(n, k) for n, k in table.items() if k in kinds]
    if Kind.VALUE in kinds:
        out += [(p, Kind.VALUE) for p in profile.value_prefixes]
    return out


_PLAIN_KINDS: Final = frozenset({Kind.VALUE, Kind.BOOL})
_SPECIAL_KINDS: Final = frozenset({Kind.REQFILE, Kind.CONSTRAINT, Kind.EDITABLE})


@st.composite
def _option_from(draw: st.DrawFn, candidates: Sequence[tuple[str, Kind]]) -> OptGroup:
    name, kind = draw(st.sampled_from(candidates))
    if name.endswith("."):  # a value prefix such as ``--config.``
        name += draw(st.from_regex(r"[a-z]{2,5}", fullmatch=True))
        return draw(render_option(name, kind, only_eq=True))
    return draw(render_option(name, kind))


def option_group(profile: Profile, where: Where) -> st.SearchStrategy[OptGroup]:
    """A boolean or value option from the profile's table (before the verb, or after it)."""
    return _option_from(_candidates(profile, where, _PLAIN_KINDS))


def special_group(profile: Profile, *, ref_only: bool = False) -> st.SearchStrategy[OptGroup]:
    """A ``-r`` / ``-c`` / ``-e`` option, when the profile has one."""
    kinds = frozenset({Kind.REQFILE}) if ref_only else _SPECIAL_KINDS
    return _option_from(_candidates(profile, "verb", kinds))


def registry_group(profile: Profile) -> st.SearchStrategy[tuple[OptGroup, Where]]:
    """A custom-registry option and where it may stand."""

    @st.composite
    def build(draw: st.DrawFn) -> tuple[OptGroup, Where]:
        name, kind = draw(st.sampled_from(_candidates(profile, "verb", frozenset({Kind.REGISTRY}))))
        where: Where = "global" if name in profile.global_options else "verb"
        if where == "global" and draw(st.booleans()):
            where = "verb"
        return draw(render_option(name, kind)), where

    return build()


_UNKNOWN: Final = (("--no-such-flag",), ("--no-such-flag=x",), ("-Z",), ("-Z", "vval"), ("-Zvval",))
for _profile in PROFILES:
    for _tokens in _UNKNOWN:
        _head = _tokens[0].split("=", 1)[0]
        assert _head not in _profile.verb_options and _head[:2] not in _profile.verb_options


def unknown_group() -> st.SearchStrategy[OptGroup]:
    """An option that is in no table of any profile."""
    return st.sampled_from(_UNKNOWN).map(OptGroup)


# --- segments and command lines --------------------------------------------------------

PREFIXES: Final[tuple[tuple[str, ...], ...]] = (
    (),
    (),
    ("FOO=1",),
    ("sudo",),
    ("FOO=1", "sudo"),
    ("sudo", "FOO=1"),
    ("env", "A=b"),
    ("env",),
    ("time",),
    ("nohup",),
    ("command",),
    ("exec",),
)
TAILS: Final[tuple[str, ...]] = (
    "",
    "",
    "",
    " > out.txt",
    " >> out.log",
    " 2>&1",
    " 2>/dev/null",
    " &> all.log",
    " < in.txt",
    " 2>&1 | tail -5",
    " | tail -n 3",
    " | tee out.log",
)
NOISE: Final[tuple[str, ...]] = (
    "cd web",
    "cd /tmp/x",
    "echo hello",
    "echo 'npm install evil'",
    'echo "pip install evil"',
    "ls -la",
    "git status",
    "make build",
    "mkdir -p out",
    "true",
    "npm run build",
    "npm ci",
    "export FOO=1",
    "git commit -m 'pip install y'",
)
JOINERS: Final[tuple[str, ...]] = (" && ", " || ", "; ", " | ", "\n", " & ")


@dataclass(frozen=True)
class Segment:
    """A rendered install segment and what it must yield."""

    text: str
    refs: tuple[str, ...] = ()
    skipped: int = 0


@dataclass(frozen=True)
class Rendered:
    """A rendered command line and what ``parse_install`` must return for it."""

    command: str
    targets: tuple[Target, ...]
    refs: tuple[str, ...] = ()
    skipped: int = 0


@st.composite
def install_segment(
    draw: st.DrawFn,
    shape: Shape,
    items: Sequence[Target | str],
    *,
    head: tuple[str, ...] | None = None,
    verb: tuple[str, ...] | None = None,
    special: bool = False,
    require_ref: bool = False,
    inject: OptGroup | None = None,
    inject_where: Where = "verb",
    decorate: bool = True,
) -> Segment:
    """Render one install segment for ``items`` (targets, or raw skipped-form arguments).

    ``inject`` places one more option group, before the verb or among the arguments.
    """
    profile = shape.profile
    head = head if head is not None else draw(st.sampled_from(shape.heads))
    verb = verb if verb is not None else draw(st.sampled_from(shape.verbs))
    prefix = draw(st.sampled_from(PREFIXES)) if decorate else ()
    tail = draw(st.sampled_from(TAILS)) if decorate else ""
    dashdash = bool(items) and draw(st.integers(0, 4)) == 0
    slot_count = 1 if dashdash else len(items) + 1
    slots: list[list[OptGroup]] = [[] for _ in range(slot_count)]
    if decorate:
        for slot in slots:
            slot.extend(draw(st.lists(option_group(profile, "verb"), max_size=2)))
    specials: list[OptGroup] = []
    if require_ref:
        specials.append(draw(special_group(profile, ref_only=True)))
    if special and Kind.REQFILE in profile.verb_options.values():
        specials.extend(draw(st.lists(special_group(profile), max_size=2)))
    if inject is not None and inject_where == "verb":
        specials.append(inject)
    for group in specials:
        slots[draw(st.integers(0, slot_count - 1))].append(group)
    global_groups: list[OptGroup] = []
    if decorate:
        global_groups.extend(draw(st.lists(option_group(profile, "global"), max_size=2)))
    if inject is not None and inject_where == "global":
        global_groups.append(inject)

    tokens: list[str] = [*prefix, *head]
    emitted: list[OptGroup] = list(global_groups)
    for group in global_groups:
        tokens.extend(group.tokens)
    tokens.extend(verb)
    arguments: list[str] = []
    for item in items:
        raw = draw(render_target(item, poetry=shape.poetry)) if isinstance(item, Target) else item
        arguments.append(draw(quoted(raw)))
    for index in range(slot_count):
        for group in slots[index]:
            emitted.append(group)
            tokens.extend(group.tokens)
        if dashdash and index == 0:
            tokens.append("--")
            tokens.extend(arguments)
        elif not dashdash and index < len(arguments):
            tokens.append(arguments[index])
    refs = tuple(g.ref for g in emitted if g.ref is not None)
    return Segment(" ".join(tokens) + tail, refs, sum(g.skipped for g in emitted))


@st.composite
def noise_segments(draw: st.DrawFn, *, max_size: int = 2) -> list[str]:
    return draw(st.lists(st.sampled_from(NOISE), max_size=max_size))


def join_segments(draw: st.DrawFn, texts: Sequence[str]) -> str:
    """Join ``texts`` with random command operators."""
    out = texts[0]
    for text in texts[1:]:
        out += draw(st.sampled_from(JOINERS)) + text
    return out


@st.composite
def commands(
    draw: st.DrawFn,
    targets: Sequence[Target],
    skipped_forms: Sequence[str] = (),
    *,
    ecosystem: Ecosystem | None = None,
    shape: Shape | None = None,
    head: tuple[str, ...] | None = None,
    verb: tuple[str, ...] | None = None,
    special: bool = False,
    require_ref: bool = False,
    decorate: bool = True,
) -> Rendered:
    """Render ``targets`` (and raw skipped forms in the first run) as a command line.

    Consecutive targets of one ecosystem share a segment; an ecosystem change starts a new
    segment. Noise segments (``cd``, ``echo``...) may surround and separate them.
    """
    runs: list[list[Target]] = []
    for item in targets:
        if runs and runs[-1][0].ecosystem == item.ecosystem:
            runs[-1].append(item)
        else:
            runs.append([item])
    if not runs:
        runs = [[]]
    first_eco: Ecosystem
    if runs[0]:
        first_eco = runs[0][0].ecosystem
    elif shape is not None:
        first_eco = shape.ecosystem
    else:
        first_eco = ecosystem if ecosystem is not None else draw(st.sampled_from(ECOSYSTEMS))
    texts: list[str] = []
    refs: list[str] = []
    skipped = 0
    for index, run in enumerate(runs):
        eco = first_eco if index == 0 else run[0].ecosystem
        if index == 0 and shape is not None:
            chosen = shape
        else:
            options = [
                s for s in SHAPES if s.ecosystem == eco and (s.has_reqfile or not require_ref)
            ]
            chosen = draw(st.sampled_from(options))
        items: list[Target | str] = list(run)
        if index == 0:
            for form in skipped_forms:
                items.insert(draw(st.integers(0, len(items))), form)
        seg = draw(
            install_segment(
                chosen,
                items,
                head=head if index == 0 else None,
                verb=verb if index == 0 else None,
                special=special,
                require_ref=require_ref and index == 0,
                decorate=decorate,
            )
        )
        texts.append(seg.text)
        refs.extend(seg.refs)
        skipped += seg.skipped
    if decorate:
        texts = [*draw(noise_segments()), *texts, *draw(noise_segments())]
        # a noise segment between two install segments
        if len(runs) > 1 and draw(st.booleans()):
            at = len(texts) - len(runs) + 1
            texts.insert(at, draw(st.sampled_from(NOISE)))
    return Rendered(join_segments(draw, texts), tuple(targets), tuple(refs), skipped)


# --- skipped forms (KPW-PARSE-7) --------------------------------------------------------

_SKIP_NAME: Final = st.from_regex(r"[a-z][a-z0-9]{0,5}", fullmatch=True)


def _forms(name: str, ecosystem: Ecosystem) -> list[str]:
    common = [
        ".",
        f"./{name}",
        f"../{name}",
        f"/opt/{name}",
        f"~/{name}",
        f"git+https://github.com/o/{name}.git",
        f"https://example.com/{name}.tar.gz",
        f"http://example.com/{name}.zip",
        f"o/{name}",
        f"${name.upper()}",
        f"`{name}`",
        f"{name}?",
        f"{{{name},x}}",
        "@scope",
        "@/x",
        "a b",
        "x\x01y",
    ]
    if ecosystem == "npm":
        return common + [
            f"file:../{name}",
            f"git://example.com/{name}.git",
            f"git@github.com:o/{name}.git",
            f"github:o/{name}",
            f"gitlab:o/{name}",
            f"bitbucket:o/{name}",
            f"gist:{name}",
            f"{name}@npm:real@1",
            f"{name}.tgz",
            f"{name}@next",
            f"{name}@beta",
            f"{name}*",
            f"[{name}]",
            f"!{name}",
            "@a/b/c",
        ]
    return common + [
        f"{name}-1.0-py3-none-any.whl",
        f"{name}.tar.gz",
        f"{name}.zip",
        f"https://example.com/{name}.whl",
        f"{name} @ https://example.com/{name}.zip",
        f"{name}!x",
        f"{name}==",
        f"{name}=1.0",
        f"{name}<>2",
        f"{name} 1.0",
        f"_{name}",
        f"{name}[",
        f"{name}*",
    ]


@st.composite
def skipped_forms(draw: st.DrawFn, ecosystem: Ecosystem, *, max_size: int = 3) -> list[str]:
    """Raw arguments that must be counted and skipped for ``ecosystem``."""
    count = draw(st.integers(1, max_size))
    out: list[str] = []
    for _ in range(count):
        name = draw(_SKIP_NAME)
        out.append(draw(st.sampled_from(_forms(name, ecosystem))))
    return out


# --- non-install commands (KPW-TEST-3) --------------------------------------------------

NON_INSTALL_VERBS: Final[dict[str, tuple[str, ...]]] = {
    "npm": ("ci", "run build", "update", "uninstall", "rm", "test", "ls", "audit", "exec", "view"),
    "pnpm": ("remove", "update", "run build", "exec", "dlx", "up", "audit"),
    "yarn": ("install", "remove", "upgrade", "run build", "dlx", "up"),
    "pip": ("uninstall -y", "download", "list", "show", "freeze", "wheel", "check", "config list"),
    "uv": ("sync", "run", "tool install", "lock", "remove", "venv", "pip uninstall", "pip compile"),
    "poetry": ("install", "remove", "update", "lock", "run", "show", "build"),
    "npx": ("",),
    "pipx": ("install",),
}
WRAPPERS_NOT_PARSED: Final[tuple[str, ...]] = (
    "bash -c",
    "sh -c",
    "zsh -c",
    "eval",
    "xargs",
    "docker run img",
    "ssh host",
    "echo",
    "printf",
    "git commit -m",
    "cat",
    "watch",
    "nice",
)
