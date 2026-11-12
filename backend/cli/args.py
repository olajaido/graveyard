"""Command-line parsing (CLI-CMD-1..6, CLI-PURL-1..3; design 4).

Nothing here touches process streams, ``sys.exit`` or the environment. ``--help`` and
``--version`` raise ``ExitRequest(0, text)``; usage problems raise ``UsageError``.
"""

from __future__ import annotations

import argparse
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from importlib import metadata
from pathlib import Path
from typing import Any, Final, Literal, NoReturn, cast, get_args

from cli.errors import EXIT_CODE_TABLE, ExitRequest, UsageError
from cli.purls import validate_purls

__all__ = ["GateClass", "Options", "build_parser", "parse_args", "parse_fail_on"]

GateClass = Literal["dead", "cursed", "ailing"]
_GATE_WORDS: Final[tuple[str, ...]] = get_args(GateClass)

DEFAULT_SYFT_TIMEOUT: Final[float] = 120.0
_DIST_NAME: Final[str] = "graveyard-backend"
_ISO_DATE: Final[re.Pattern[str]] = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


@dataclass(frozen=True)
class Options:
    path: Path | None
    purls: tuple[str, ...]
    sbom: Path | None
    json_out: Path | None
    fail_on: frozenset[GateClass]
    as_of: date | None
    show_all: bool
    syft: str | None
    syft_timeout: float = DEFAULT_SYFT_TIMEOUT


def _one_line(text: str) -> str:
    return " ".join(text.split())


class _Parser(argparse.ArgumentParser):
    """Parser that never exits or writes to the process streams."""

    def error(self, message: str) -> NoReturn:
        raise UsageError(_one_line(message))

    def exit(self, status: int = 0, message: str | None = None) -> NoReturn:
        raise ExitRequest(status, message or "")

    def print_help(self, file: Any = None) -> None:
        raise ExitRequest(0, self.format_help())


class _VersionAction(argparse.Action):
    def __init__(self, option_strings: Sequence[str], dest: str, **kwargs: Any) -> None:
        super().__init__(option_strings, dest, nargs=0, **kwargs)

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Any,
        option_string: str | None = None,
    ) -> NoReturn:
        raise ExitRequest(0, f"graveyard {_version()}\n")


def _version() -> str:
    try:
        return metadata.version(_DIST_NAME)
    except metadata.PackageNotFoundError:
        return "unknown"


def parse_fail_on(text: str) -> frozenset[GateClass]:
    """Parse ``dead,cursed,ailing`` (comma separated, case-insensitive, trimmed)."""
    allowed = ", ".join(_GATE_WORDS)
    words: list[GateClass] = []
    for item in text.split(","):
        word = item.strip().lower()
        if word not in _GATE_WORDS:
            raise UsageError(
                f"--fail-on: expected a comma-separated list of {allowed}; "
                "empty items and other words are not allowed"
            )
        words.append(cast(GateClass, word))
    return frozenset(words)


def _parse_as_of(text: str, today: date) -> date:
    if _ISO_DATE.fullmatch(text) is None:
        raise UsageError("--as-of: expected a date as YYYY-MM-DD")
    try:
        value = date.fromisoformat(text)
    except ValueError:
        raise UsageError("--as-of: not a valid calendar date (YYYY-MM-DD)") from None
    if value > today:
        raise UsageError("--as-of: the date is in the future")
    return value


def _parse_timeout(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise UsageError("--syft-timeout: expected a positive number of seconds") from None
    if not math.isfinite(value) or value <= 0:
        raise UsageError("--syft-timeout: expected a positive, finite number of seconds")
    return value


def build_parser() -> argparse.ArgumentParser:
    # Imported here: cli.hook imports cli.model, which imports this module.
    from cli.hook import HOOK_EXIT_TABLE

    parser = _Parser(
        prog="graveyard",
        description="Graveyard: find the dead dependencies in a project.",
        epilog=(
            "exit codes (autopsy):\n"
            + EXIT_CODE_TABLE
            + "\n\nexit codes (check-install):\n"
            + HOOK_EXIT_TABLE
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
    )
    parser.add_argument("--version", action=_VersionAction, help="show the version and exit")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    autopsy = commands.add_parser(
        "autopsy",
        help="autopsy every dependency of a project, or of the given packages",
        description=(
            "Autopsy the dependencies of PATH (a directory), or of one or more --purl "
            "packages, and print them ranked by priority."
        ),
        epilog="exit codes:\n" + EXIT_CODE_TABLE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
    )
    autopsy.add_argument("path", nargs="?", metavar="PATH", help="project directory")
    autopsy.add_argument(
        "--purl",
        action="append",
        default=[],
        metavar="PURL",
        help="package URL with a version; repeatable; replaces PATH",
    )
    autopsy.add_argument("--sbom", metavar="FILE", help="CycloneDX SBOM to use instead of Syft")
    autopsy.add_argument("--json", dest="json_out", metavar="FILE", help="write the JSON report")
    autopsy.add_argument(
        "--fail-on",
        metavar="LIST",
        help="exit 1 when a package is in any class: dead,cursed,ailing",
    )
    autopsy.add_argument("--as-of", metavar="YYYY-MM-DD", help="score as of this date")
    autopsy.add_argument("--all", dest="show_all", action="store_true", help="list every package")
    autopsy.add_argument("--syft", metavar="PATH", help="path to the Syft executable")
    autopsy.add_argument(
        "--syft-timeout",
        metavar="SECONDS",
        default=None,
        help=f"timeout for each Syft run (default {DEFAULT_SYFT_TIMEOUT:g})",
    )
    # Listed for --help only: ``app.run`` dispatches ``check-install`` before parsing.
    commands.add_parser(
        "check-install",
        help="check the packages an install command would add (hook command)",
        add_help=False,
    )
    return parser


def parse_args(argv: Sequence[str], *, today: date) -> Options:
    ns = build_parser().parse_args(list(argv))
    purls: list[str] = ns.purl
    raw_path: str | None = ns.path

    if raw_path is None and not purls:
        raise UsageError("give a PATH to a project directory, or at least one --purl")
    if raw_path is not None and purls:
        raise UsageError("PATH and --purl cannot be used together")
    if ns.sbom is not None and raw_path is None:
        raise UsageError("--sbom needs a PATH and cannot be used with --purl")

    path: Path | None = None
    if raw_path is not None:
        path = Path(raw_path).resolve()
        if not path.is_dir():
            raise UsageError("PATH is not a directory that exists")

    sbom: Path | None = None
    if ns.sbom is not None:
        sbom = Path(ns.sbom)
        if not sbom.is_file():
            raise UsageError("--sbom: the file does not exist")

    fail_on = parse_fail_on(ns.fail_on) if ns.fail_on is not None else frozenset[GateClass]()
    as_of = _parse_as_of(ns.as_of, today) if ns.as_of is not None else None
    timeout = (
        _parse_timeout(ns.syft_timeout) if ns.syft_timeout is not None else DEFAULT_SYFT_TIMEOUT
    )

    return Options(
        path=path,
        purls=validate_purls(purls) if purls else (),
        sbom=sbom,
        json_out=Path(ns.json_out) if ns.json_out is not None else None,
        fail_on=fail_on,
        as_of=as_of,
        show_all=bool(ns.show_all),
        syft=ns.syft,
        syft_timeout=timeout,
    )
