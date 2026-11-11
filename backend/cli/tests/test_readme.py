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
