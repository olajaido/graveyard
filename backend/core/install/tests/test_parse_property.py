"""Property tests for ``parse_install`` (KPW-TEST-1 to KPW-TEST-4, design 10.1).

Each property renders a command from the answer (see ``strategies``), so the oracle is
the input and not a second parser. Hypothesis profiles (``dev`` = 200 examples, ``ci`` = 500)
come from the shared ``conftest.py`` via ``HYPOTHESIS_PROFILE``; no ``max_examples`` is set here.

**Validates: Requirements KPW-TEST-1 to KPW-TEST-4, KPW-PARSE-1 to KPW-PARSE-12**
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from core.install.model import Latest, ParseResult, Pinned, Target
from core.install.parse import MAX_REQUIREMENT_FILES, MAX_TARGETS, parse_install
from core.install.profiles import Kind
from core.install.tests.strategies import (
    ECOSYSTEMS,
    NOISE,
    NON_INSTALL_VERBS,
    PREFIXES,
    SHAPES,
    WHERES,
    WRAPPERS_NOT_PARSED,
    Ecosystem,
    Rendered,
    Shape,
    commands,
    expected_targets,
    install_segment,
    join_segments,
    quoted,
    registry_group,
    skipped_forms,
    unknown_group,
)

pytestmark = pytest.mark.property


def assert_rendered(rendered: Rendered) -> None:
    """The parse of ``rendered.command`` is exactly what it was rendered from."""
    result = parse_install(rendered.command)
    assert result.targets == rendered.targets, rendered.command
    assert tuple(r.path for r in result.requirement_files) == rendered.refs, rendered.command
    assert result.skipped == rendered.skipped, rendered.command
    assert result.truncated is False, rendered.command


# --- KPW-TEST-1: round trip ------------------------------------------------------------


@given(st.data())
def test_roundtrip(data: st.DataObject) -> None:
    expected = data.draw(expected_targets())
    assert_rendered(data.draw(commands(expected, special=True)))


COMBOS = [
    pytest.param(shape, head, verb, id=f"{shape.label}:{' '.join(head)}:{' '.join(verb)}")
    for shape in SHAPES
    for head in shape.heads
    for verb in shape.verbs
]


@pytest.mark.parametrize(("shape", "head", "verb"), COMBOS)
@given(st.data())
def test_every_program_head_and_verb(
    shape: Shape, head: tuple[str, ...], verb: tuple[str, ...], data: st.DataObject
) -> None:
    expected = data.draw(expected_targets(ecosystem=shape.ecosystem))
    assert_rendered(data.draw(commands(expected, shape=shape, head=head, verb=verb, special=True)))


def test_double_dash_ends_options() -> None:
    """After ``--`` an option-looking word is a positional argument, not an unknown option."""
    result = parse_install("pip install -- -x six")
    assert result.targets == (Target("pypi", "six", Latest()),)
    assert result.skipped == 1


@given(st.data())
def test_order_preserved(data: st.DataObject) -> None:
    expected = data.draw(expected_targets(max_size=4))
    shuffled = data.draw(st.permutations(expected))
    rendered = data.draw(commands(shuffled))
    assert parse_install(rendered.command).targets == tuple(shuffled)


@given(st.data())
def test_prefix_and_noise_contribute_nothing(data: st.DataObject) -> None:
    """The same targets with and without prefixes, tails and noise segments parse alike."""
    expected = data.draw(expected_targets(ecosystem=data.draw(st.sampled_from(ECOSYSTEMS))))
    plain = data.draw(commands(expected, decorate=False))
    decorated = data.draw(commands(expected, decorate=True))
    assert parse_install(plain.command).targets == parse_install(decorated.command).targets


# --- KPW-TEST-1: the option tables ------------------------------------------------------

NPM_BASE = ("alpha", "beta@1.2.3")
PYPI_BASE = ("alpha", "beta==1.2.3")


@dataclass(frozen=True)
class OptionCase:
    shape: Shape
    where: str
    name: str
    kind: Kind


def _cases() -> list[pytest.ParameterSet]:
    out: list[pytest.ParameterSet] = []
    for shape in SHAPES:
        for where, table in (
            ("global", shape.profile.global_options),
            ("verb", shape.profile.verb_options),
        ):
            for name, kind in table.items():
                out.append(
                    pytest.param(
                        OptionCase(shape, where, name, kind), id=f"{shape.label}:{where}:{name}"
                    )
                )
    return out


def _spellings(name: str, kind: Kind) -> list[tuple[str, ...]]:
    """Every way to write the option: ``--o v``, ``--o=v`` and ``-Ov``."""
    if kind is Kind.BOOL:
        return [(name,)]
    value = {
        Kind.REQFILE: "req.txt",
        Kind.CONSTRAINT: "pins.txt",
        Kind.EDITABLE: "./local",
        Kind.REGISTRY: "https://registry.example/simple",
    }.get(kind, "vval")
    out: list[tuple[str, ...]] = [(name, value)]
    if name.startswith("--"):
        out.append((f"{name}={value}",))
    elif len(name) == 2:
        out.append((f"{name}{value}",))
    return out


def _build(shape: Shape, option: tuple[str, ...], where: str, position: int) -> str:
    """Insert ``option`` before the verb (``where == 'global'``) or at ``position`` among args."""
    head = list(shape.heads[0])
    verb = list(shape.verbs[0])
    packages = list(NPM_BASE if shape.ecosystem == "npm" else PYPI_BASE)
    if where == "global":
        return " ".join([*head, *option, *verb, *packages])
    packages[position:position] = list(option)
    return " ".join([*head, *verb, *packages])


@pytest.mark.parametrize("case", _cases())
def test_every_option_parses_like_its_absence(case: OptionCase) -> None:
    shape = case.shape
    eco = shape.ecosystem
    expected = (Target(eco, "alpha", Latest()), Target(eco, "beta", Pinned("1.2.3")))
    base = NPM_BASE if eco == "npm" else PYPI_BASE
    without = parse_install(" ".join([*shape.heads[0], *shape.verbs[0], *base]))
    assert without.targets == expected
    positions = [0] if case.where == "global" else [0, 1, 2]
    for spelling in _spellings(case.name, case.kind):
        for position in positions:
            command = _build(shape, spelling, case.where, position)
            result = parse_install(command)
            if case.kind is Kind.REGISTRY:
                assert result == ParseResult(), command
                continue
            assert result.targets == expected, command
            if case.kind is Kind.REQFILE:
                assert [r.path for r in result.requirement_files] == ["req.txt"], command
            else:
                assert result.requirement_files == (), command
            skipped = 1 if case.kind in (Kind.CONSTRAINT, Kind.EDITABLE) else 0
            assert result.skipped == skipped, command


def test_the_option_coverage_test_sees_every_table_entry() -> None:
    """Guard: the parametrisation really walks both tables of every profile."""
    cases = _cases()
    assert len(cases) == sum(
        len(s.profile.global_options) + len(s.profile.verb_options) for s in SHAPES
    )
    kinds = {p.values[0].kind for p in cases}  # type: ignore[union-attr]
    assert kinds == set(Kind)


# --- KPW-TEST-2: skipped forms, -r files, registries, unknown options -------------------


@given(st.data())
def test_skipped_forms_alone_yield_no_target(data: st.DataObject) -> None:
    eco = data.draw(st.sampled_from(ECOSYSTEMS))
    forms = data.draw(skipped_forms(eco))
    rendered = data.draw(commands((), forms, ecosystem=eco, special=True))
    result = parse_install(rendered.command)
    assert result.targets == (), rendered.command
    assert result.skipped >= len(forms), rendered.command
    assert tuple(r.path for r in result.requirement_files) == rendered.refs


@given(st.data())
def test_skipped_forms_mixed_with_packages_leave_only_the_packages(data: st.DataObject) -> None:
    eco = data.draw(st.sampled_from(ECOSYSTEMS))
    expected = data.draw(expected_targets(ecosystem=eco))
    forms = data.draw(skipped_forms(eco))
    rendered = data.draw(commands(expected, forms, special=True))
    result = parse_install(rendered.command)
    assert result.targets == expected, rendered.command
    assert result.skipped == len(forms) + rendered.skipped, rendered.command
    assert tuple(r.path for r in result.requirement_files) == rendered.refs


@given(st.data())
def test_requirement_file_alone_and_with_packages(data: st.DataObject) -> None:
    alone = data.draw(commands((), ecosystem="pypi", require_ref=True))
    result = parse_install(alone.command)
    assert result.targets == ()
    assert len(result.requirement_files) >= 1
    assert tuple(r.path for r in result.requirement_files) == alone.refs
    expected = data.draw(expected_targets(ecosystem="pypi"))
    mixed = data.draw(commands(expected, require_ref=True))
    assert_rendered(mixed)
    assert len(parse_install(mixed.command).requirement_files) >= 1


def _good_and_bad(data: st.DataObject, kind: str) -> tuple[str, Rendered]:
    """A segment that must yield nothing and a good command, in either order."""
    shape = data.draw(st.sampled_from(SHAPES))
    items = list(data.draw(expected_targets(ecosystem=shape.ecosystem)))
    forms = data.draw(skipped_forms(shape.ecosystem, max_size=1))
    if kind == "registry":
        group, where = data.draw(registry_group(shape.profile))
    else:
        group, where = data.draw(unknown_group()), data.draw(st.sampled_from(WHERES))
    bad = data.draw(
        install_segment(
            shape,
            [*items, *forms],
            special=True,
            inject=group,
            inject_where=where,
        )
    )
    good_targets = data.draw(expected_targets(ecosystem=data.draw(st.sampled_from(ECOSYSTEMS))))
    good = data.draw(commands(good_targets, special=True))
    first_bad = data.draw(st.booleans())
    texts = [bad.text, good.command] if first_bad else [good.command, bad.text]
    joined = texts[0] + data.draw(st.sampled_from((" && ", "; ", "\n", " || "))) + texts[1]
    return joined, good


@given(st.data())
@pytest.mark.parametrize("kind", ["registry", "unknown"])
def test_registry_or_unknown_option_unchecks_only_its_segment(
    kind: str, data: st.DataObject
) -> None:
    command, good = _good_and_bad(data, kind)
    result = parse_install(command)
    assert result.targets == good.targets, command
    assert tuple(r.path for r in result.requirement_files) == good.refs, command


# --- KPW-TEST-3: non-install commands ---------------------------------------------------

NON_INSTALL_EXAMPLES = [
    "ls",
    "ls -la",
    'git commit -m "npm install x"',
    'echo "pip install y"',
    "npm ci",
    "npm run build",
    "pip uninstall x",
    "bash -c 'npm i x'",
    'sh -c "pip install y"',
    "eval npm install x",
    "xargs npm install x",
    "docker run img npm install x",
    "ssh host 'npm i x'",
    "npx create-react-app app",
    "pipx install x",
    "uv tool install ruff",
    "uv run pytest",
    "uv sync",
    "poetry install",
    "yarn install",
    "pip download x",
    "",
    "   ",
]


@pytest.mark.parametrize("command", NON_INSTALL_EXAMPLES)
def test_non_install_examples_yield_nothing(command: str) -> None:
    assert parse_install(command) == ParseResult()


@given(st.data())
def test_other_verbs_yield_nothing(data: st.DataObject) -> None:
    program = data.draw(st.sampled_from(sorted(NON_INSTALL_VERBS)))
    verb = data.draw(st.sampled_from(NON_INSTALL_VERBS[program]))
    eco: Ecosystem = "pypi" if program in ("pip", "uv", "poetry", "pipx") else "npm"
    names = [t.name for t in data.draw(expected_targets(ecosystem=eco))]
    prefix = data.draw(st.sampled_from(PREFIXES))
    command = " ".join([*prefix, program, verb, *names])
    assert parse_install(command) == ParseResult(), command


@given(st.data())
def test_wrapped_install_commands_yield_nothing(data: st.DataObject) -> None:
    eco = data.draw(st.sampled_from(ECOSYSTEMS))
    inner = data.draw(
        commands(data.draw(expected_targets(ecosystem=eco)), decorate=False).filter(
            lambda r: "'" not in r.command
        )
    )
    wrapper = data.draw(st.sampled_from(WRAPPERS_NOT_PARSED))
    argument = data.draw(quoted(inner.command)) if data.draw(st.booleans()) else inner.command
    command = f"{wrapper} {argument}"
    assert parse_install(command) == ParseResult(), command


@given(st.data())
def test_noise_alone_yields_nothing(data: st.DataObject) -> None:
    texts = data.draw(st.lists(st.sampled_from(NOISE), min_size=1, max_size=4))
    command = join_segments(data.draw, texts)  # type: ignore[arg-type]
    assert parse_install(command) == ParseResult(), command


# --- KPW-TEST-4: totality, determinism, bounds ------------------------------------------

_SHELLISH = "npmiyarnsudo pipvx-@^~<>=!;&|()'\"\\$`*?[]{}#\n\t\x00/.:,0123456789"
_ANY_TEXT = st.one_of(
    st.text(max_size=300),
    st.text(alphabet=st.characters(blacklist_categories=()), max_size=200),
    st.text(alphabet=_SHELLISH, max_size=400),
)


def assert_bounded(result: ParseResult) -> None:
    assert isinstance(result, ParseResult)
    assert len(result.targets) <= MAX_TARGETS
    assert len(result.requirement_files) <= MAX_REQUIREMENT_FILES
    assert result.skipped >= 0
    keys = [(t.ecosystem, t.name.lower()) for t in result.targets]
    assert len(keys) == len(set(keys))


@given(_ANY_TEXT)
@example("npm i " + "a " * 10_000)
@example("(" * 5_000 + "npm i x" + ")" * 5_000)
@example("'" * 10_001)
@example("$(" * 3_000)
@example("npm i x " + ">" * 5_000)
@example("pip install " + "-r r.txt " * 2_000)
@example("\ud800 npm i \udfff x")
@example("npm i \x00 x\x00")
def test_parse_install_is_total_and_deterministic(text: str) -> None:
    first = parse_install(text)
    assert_bounded(first)
    assert parse_install(text) == first


@given(st.data())
def test_mutated_commands_never_raise(data: st.DataObject) -> None:
    rendered = data.draw(commands(data.draw(expected_targets()), special=True))
    text = rendered.command
    cut = data.draw(st.integers(0, len(text)))
    insert = data.draw(st.text(alphabet=_SHELLISH, max_size=5))
    for mutated in (text[:cut], text[:cut] + insert + text[cut:], text[cut:]):
        result = parse_install(mutated)
        assert_bounded(result)
        assert parse_install(mutated) == result


@given(st.integers(21, 30), st.sampled_from(ECOSYSTEMS))
def test_cap_keeps_the_first_twenty_and_sets_truncated(count: int, eco: str) -> None:
    names = [f"pkg{i}" for i in range(count)]
    program = "npm install" if eco == "npm" else "pip install"
    result = parse_install(f"{program} {' '.join(names)}")
    assert [t.name for t in result.targets] == names[:MAX_TARGETS]
    assert result.truncated is True
