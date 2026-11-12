"""Example tests for ``parse_install``: the design 4.5 table and the extra rows of T5.2.

Where requirements and design differ, requirements win: KPW-PARSE-9/10 make a
caret specifier a ``Range``, so ``typescript@^5`` and poetry ``requests@^2.0``
are asserted as ``Range`` (the design table says ``Latest``).
"""

from __future__ import annotations

import pytest

from core.install.model import Latest, Pinned, Range, Spec, Target
from core.install.parse import parse_install


def npm(name: str, spec: Spec) -> Target:
    return Target("npm", name, spec)


def pypi(name: str, spec: Spec) -> Target:
    return Target("pypi", name, spec)


# (command, targets, requirement files, skipped)
ROWS: list[tuple[str, list[Target], list[str], int]] = [
    ("npm install request", [npm("request", Latest())], [], 0),
    (
        "npm i -D @types/node@20.1.0 typescript@^5",
        [npm("@types/node", Pinned("20.1.0")), npm("typescript", Range())],
        [],
        0,
    ),
    ("pnpm --filter web add -D express", [npm("express", Latest())], [], 0),
    (
        "yarn workspace api add left-pad@1.3.0",
        [npm("left-pad", Pinned("1.3.0"))],
        [],
        0,
    ),
    ("npm install ./pkg git+https://x/y.git user/repo foo@next", [], [], 4),
    (
        'pip install "six>=1.0" requests[security]==2.31.0 -r req.txt',
        [pypi("six", Latest()), pypi("requests", Pinned("2.31.0"))],
        ["req.txt"],
        0,
    ),
    ('pip install "six<2" "idna~=3.0"', [pypi("six", Range()), pypi("idna", Range())], [], 0),
    (
        "npm i request@^2 express@5.3.0 left-pad@latest",
        [npm("request", Range()), npm("express", Pinned("5.3.0")), npm("left-pad", Latest())],
        [],
        0,
    ),
    ("python3 -m pip install --user -U Flask_Login", [pypi("flask-login", Latest())], [], 0),
    (
        'uv add --dev pytest "httpx==0.28.1"',
        [pypi("pytest", Latest()), pypi("httpx", Pinned("0.28.1"))],
        [],
        0,
    ),
    ("uv pip install -r requirements.txt", [], ["requirements.txt"], 0),
    ("pip install -c constraints.txt six", [pypi("six", Latest())], [], 1),
    (
        "poetry add requests@^2.0 django@4.2.0 --group dev",
        [pypi("requests", Range()), pypi("django", Pinned("4.2.0"))],
        [],
        0,
    ),
    ("cd web && npm install request 2>&1 | tail -5", [npm("request", Latest())], [], 0),
    ("FOO=1 sudo npm install request", [npm("request", Latest())], [], 0),
    ("sudo -E npm install request", [], [], 0),
    ("npm install --registry https://r.example/ internal-pkg", [], [], 0),
    ("npm install --some-new-flag request", [], [], 0),
    ('bash -c "npm i request"', [], [], 0),
    ("npm install $PKG", [], [], 1),
]


@pytest.mark.parametrize(("command", "targets", "refs", "skipped"), ROWS)
def test_design_table_rows(
    command: str, targets: list[Target], refs: list[str], skipped: int
) -> None:
    result = parse_install(command)
    assert list(result.targets) == targets
    assert [r.path for r in result.requirement_files] == refs
    assert result.skipped == skipped
    assert result.truncated is False


@pytest.mark.parametrize(
    "command",
    [
        "npm ci",
        "npm run build",
        "pip uninstall x",
        "uv sync",
        "yarn install",
        "poetry install",
        "npm install",
        "pip install",
    ],
)
def test_non_package_commands_yield_nothing(command: str) -> None:
    result = parse_install(command)
    assert result.targets == ()
    assert result.requirement_files == ()


def test_twenty_first_distinct_target_sets_truncated() -> None:
    names = [f"pkg{i}" for i in range(21)]
    result = parse_install("npm install " + " ".join(names))
    assert result.truncated is True
    assert [t.name for t in result.targets] == names[:20]


def test_exactly_twenty_targets_not_truncated() -> None:
    result = parse_install("npm install " + " ".join(f"pkg{i}" for i in range(20)))
    assert len(result.targets) == 20
    assert result.truncated is False


def test_sixth_requirement_file_is_dropped() -> None:
    command = "pip install " + " ".join(f"-r r{i}.txt" for i in range(6))
    result = parse_install(command)
    assert [r.path for r in result.requirement_files] == [f"r{i}.txt" for i in range(5)]


def test_custom_registry_drops_segment_requirement_files() -> None:
    result = parse_install("pip install -r a.txt --index-url https://r.example/simple six")
    assert result.targets == ()
    assert result.requirement_files == ()
