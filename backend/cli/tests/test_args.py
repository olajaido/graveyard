"""Unit tests for cli.args (CLI-CMD-1..6, CLI-PURL-1)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from cli.args import Options, build_parser, parse_args
from cli.errors import EXIT_CODE_TABLE, ExitRequest, UsageError

TODAY = date(2026, 6, 15)
PURL = "pkg:npm/request@2.88.2"


def parse(*argv: str) -> Options:
    return parse_args(argv, today=TODAY)


def assert_usage(*argv: str) -> UsageError:
    with pytest.raises(UsageError) as info:
        parse(*argv)
    assert info.value.message
    assert "\n" not in info.value.message
    return info.value


def test_path_only(tmp_path: Path) -> None:
    opts = parse("autopsy", str(tmp_path))
    assert opts.path == tmp_path.resolve()
    assert opts.purls == ()
    assert opts.sbom is None
    assert opts.json_out is None
    assert opts.fail_on == frozenset()
    assert opts.as_of is None
    assert opts.show_all is False
    assert opts.syft is None
    assert opts.syft_timeout == 120.0


def test_path_with_sbom(tmp_path: Path) -> None:
    sbom = tmp_path / "bom.json"
    sbom.write_text("{}")
    opts = parse("autopsy", str(tmp_path), "--sbom", str(sbom))
    assert opts.sbom == sbom


def test_single_and_repeated_purl() -> None:
    assert parse("autopsy", "--purl", PURL).purls == (PURL,)
    opts = parse("autopsy", "--purl", "pkg:pypi/six@1.17.0", "--purl", PURL)
    assert opts.purls == (PURL, "pkg:pypi/six@1.17.0")
    assert opts.path is None


def test_all_options(tmp_path: Path) -> None:
    out = tmp_path / "out.json"
    opts = parse(
        "autopsy",
        str(tmp_path),
        "--json",
        str(out),
        "--fail-on",
        "dead,ailing",
        "--as-of",
        "2026-01-31",
        "--all",
        "--syft",
        "/usr/bin/syft",
        "--syft-timeout",
        "2.5",
    )
    assert opts.json_out == out
    assert opts.fail_on == {"dead", "ailing"}
    assert opts.as_of == date(2026, 1, 31)
    assert opts.show_all is True
    assert opts.syft == "/usr/bin/syft"
    assert opts.syft_timeout == 2.5


def test_as_of_today_is_accepted() -> None:
    assert parse("autopsy", "--purl", PURL, "--as-of", "2026-06-15").as_of == TODAY


def test_fail_on_is_case_insensitive_and_trimmed() -> None:
    assert parse("autopsy", "--purl", PURL, "--fail-on", "Dead, CURSED").fail_on == {
        "dead",
        "cursed",
    }


@pytest.mark.parametrize("value", ["", "dead,", "dead,zombie", ",", "zombie"])
def test_fail_on_rejected(value: str) -> None:
    error = assert_usage("autopsy", "--purl", PURL, "--fail-on", value)
    assert "dead, cursed, ailing" in error.message


@pytest.mark.parametrize(
    "value", ["2026-06-15T10:00:00", "2026-06-16", "2026-13-01", "2026-6-1", "yesterday"]
)
def test_as_of_rejected(value: str) -> None:
    assert_usage("autopsy", "--purl", PURL, "--as-of", value)


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "abc"])
def test_syft_timeout_rejected(value: str) -> None:
    assert_usage("autopsy", "--purl", PURL, "--syft-timeout", value)


def test_missing_input_rejected() -> None:
    assert_usage("autopsy")


def test_path_not_a_directory_rejected(tmp_path: Path) -> None:
    assert_usage("autopsy", str(tmp_path / "missing"))
    file = tmp_path / "f.txt"
    file.write_text("x")
    assert_usage("autopsy", str(file))


def test_path_with_purl_rejected(tmp_path: Path) -> None:
    assert_usage("autopsy", str(tmp_path), "--purl", PURL)


def test_sbom_with_purl_rejected(tmp_path: Path) -> None:
    sbom = tmp_path / "bom.json"
    sbom.write_text("{}")
    assert_usage("autopsy", "--purl", PURL, "--sbom", str(sbom))


def test_missing_sbom_file_rejected(tmp_path: Path) -> None:
    assert_usage("autopsy", str(tmp_path), "--sbom", str(tmp_path / "nope.json"))


def test_unknown_option_rejected() -> None:
    assert_usage("autopsy", "--purl", PURL, "--bogus")


def test_invalid_purl_rejected() -> None:
    assert_usage("autopsy", "--purl", "pkg:maven/a/b@1")


def test_no_option_takes_a_secret() -> None:
    parser = build_parser()
    parsers = [parser]
    for action in parser._actions:
        choices = getattr(action, "choices", None)
        if isinstance(choices, dict):
            parsers.extend(choices.values())
    dests = [action.dest.lower() for p in parsers for action in p._actions]
    assert "json_out" in dests  # the introspection really saw the subcommand options
    for word in ("token", "secret", "password"):
        assert not [d for d in dests if word in d]


def test_help_raises_exit_request_with_exit_codes() -> None:
    for argv in (["--help"], ["autopsy", "--help"]):
        with pytest.raises(ExitRequest) as info:
            parse_args(argv, today=TODAY)
        assert info.value.code == 0
        assert EXIT_CODE_TABLE in info.value.output


def test_version_raises_exit_request() -> None:
    with pytest.raises(ExitRequest) as info:
        parse("--version")
    assert info.value.code == 0
    assert info.value.output.startswith("graveyard ")
