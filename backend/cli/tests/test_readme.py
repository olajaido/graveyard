"""The README matches the code (T11.2; CLI-GATE-4, CLI-JSON-9)."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from cli.args import build_parser
from cli.errors import EXIT_CODE_TABLE, ExitCode

README = Path(__file__).resolve().parents[1] / "README.md"


def _text() -> str:
    return README.read_text(encoding="utf-8")


def _section(title: str) -> str:
    text = _text()
    start = text.index(f"## {title}")
    nxt = text.find("\n## ", start + 1)
    return text[start : nxt if nxt != -1 else len(text)]


def _exit_rows() -> dict[int, str]:
    rows: dict[int, str] = {}
    for line in _section("Exit codes").splitlines():
        match = re.fullmatch(r"\|\s*(\d+)\s*\|\s*(.+?)\s*\|", line)
        if match:
            rows[int(match.group(1))] = match.group(2)
    return rows


def test_the_exit_code_table_equals_exitcode() -> None:
    rows = _exit_rows()
    assert set(rows) == {int(code) for code in ExitCode} == {0, 1, 2, 3, 4}
    described = dict(
        (int(left), right)
        for left, right in (line.split("  ", 1) for line in EXIT_CODE_TABLE.splitlines())
    )
    assert rows == described  # the README rows are exactly the --help rows


def test_the_check_install_exit_table_equals_hookexit() -> None:
    from cli.hook import HOOK_EXIT_TABLE, HookExit

    section = _section("`check-install`")
    rows: dict[int, str] = {}
    for line in section.splitlines():
        match = re.fullmatch(r"\|\s*(\d+)\s*\|\s*(.+?)\s*\|", line)
        if match:
            rows[int(match.group(1))] = match.group(2)
    assert set(rows) == {int(code) for code in HookExit} == {0, 2}
    described = dict(
        (int(left), right)
        for left, right in (line.split("  ", 1) for line in HOOK_EXIT_TABLE.splitlines())
    )
    assert rows == described
    for needle in ("fails open", "range rule", "declared", "`-r`", "never exits 1"):
        assert needle in section or needle.lower() in section.lower(), needle


def test_the_help_epilog_has_the_same_table() -> None:
    assert EXIT_CODE_TABLE in build_parser().format_help()


def _autopsy_parser() -> argparse.ArgumentParser:
    for action in build_parser()._actions:
        if isinstance(action, argparse._SubParsersAction):
            parser = action.choices["autopsy"]
            assert isinstance(parser, argparse.ArgumentParser)
            return parser
    raise AssertionError("no autopsy subcommand")


def test_the_readme_mentions_every_option() -> None:
    options = {
        option
        for action in [*build_parser()._actions, *_autopsy_parser()._actions]
        for option in action.option_strings
        if option.startswith("--")  # `-h` is covered by `--help`
    }
    assert {"--purl", "--sbom", "--json", "--fail-on", "--as-of", "--all", "--syft"} <= options
    assert "--syft-timeout" in options
    text = _text()
    missing = sorted(option for option in options if f"`{option}" not in text)
    assert missing == []


def test_the_readme_documents_the_schema_and_its_versioning_rule() -> None:
    text = _text()
    for needle in (
        "graveyard.autopsy",
        "schema_version",
        "Versioning rule",
        "report_v1_shape.json",
    ):
        assert needle in text
    for key in (
        "schema",
        "model_version",
        "as_of",
        "input",
        "summary",
        "packages",
        "errors",
        "warnings",
    ):
        assert f"`{key}`" in text


def test_the_readme_links_the_hook_documentation_it_relies_on() -> None:
    text = _text()
    assert "https://kiro.dev/docs/hooks/actions/" in text
    assert "https://kiro.dev/docs/hooks/types/" in text
    assert "never exits 1" in text


def test_the_readme_names_the_pinned_syft_version() -> None:
    from cli.syft import SYFT_VERSION

    assert f"**{SYFT_VERSION}**" in _text()


def test_the_readme_documents_the_review_round_2_behaviour() -> None:
    from cli.model import WARNING_CODES
    from cli.syft import SYFT_FIXED_ENV

    text = _text()
    for name, value in SYFT_FIXED_ENV.items():
        assert f"{name}={value}" in text, name
    for code in sorted(WARNING_CODES):
        assert f"`{code}`" in text, code
    for needle in (
        "gate_eligible",
        "unverified_reason",
        "summary.stats.direct_edges_added",
        "unverified, not gated",
        "pytest -m syft",
        'pytest -m "not syft"',
        "Dev dependencies and direct edges",
    ):
        assert needle in text, needle


def test_the_readme_keeps_the_aug_9_limits_and_the_short_unverified_text() -> None:
    """CLI-AUG-9 stays a documented limit; CLI-EVID-5 / CLI-EVID-3 wording is present."""
    text = _text()
    assert "If a service's lockfile cannot be read" in text
    assert "`MULTIPLE_ROOTS`" in text
    assert "cannot be found when several unexplained orphan roots exist" in text
    assert "unverified: no GitHub data" in text
    assert "Ailing" in text.split("Only evidence that was seen is gated.")[1].split("\n")[0]
    assert "age rule" in text
