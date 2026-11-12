"""``graveyard check-install``: the install-blocking hook command (KPW-CMD-*, KPW-BUD-*, design §7).

``run`` is the seam. It returns only 0 (allow) or 2 (block), never raises for a problem in the
input or the sources, and never prints exception text. A usage error, an internal error and an
incomplete check all exit 0 with a one-line note on stdout (KPW-CMD-3, KPW-CMD-4).

This module reads no environment and no file itself (``requirements_file`` does), starts no
thread or process and holds no HTTP client; the payload arrives through the ``stdin`` callable.
"""

from __future__ import annotations

import asyncio
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date
from typing import Final, TextIO

from cli.args import _parse_as_of, _version, parse_args
from cli.env import CliEnvironment
from cli.errors import UsageError
from cli.hook import (
    CHECK_LIMIT,
    DEFAULT_BUDGET_SECONDS,
    HOOK_EXIT_TABLE,
    Checked,
    Failed,
    FileNote,
    Outcome,
    TimedOut,
    Unresolved,
    decide,
)
from cli.pipeline import PURL_INPUTS, Transport, make_config, rank
from cli.requirements_file import RequirementLoad, base_directory, load_requirements
from cli.text import sanitise
from core.install import (
    HookPayload,
    Pinned,
    Range,
    RequirementRef,
    Target,
    extract_payload,
    parse_install,
)
from core.sources.clock import Clock
from core.sources.model import LatestResult
from sources import SourceSession
from sources.clock import SystemClock

__all__ = [
    "CheckOptions",
    "CheckUsage",
    "evaluate",
    "parse_check_args",
    "run",
]

MIN_BUDGET: Final = 0.5
MAX_BUDGET: Final = 60.0
_IDENTIFIER: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,60}")

HELP_TEXT: Final = (
    "usage: graveyard check-install [COMMAND] [--budget SECONDS] [--as-of YYYY-MM-DD]\n"
    "\n"
    "Check the packages an install command would add. Without COMMAND, read a hook payload\n"
    "from standard input. Prints nothing when there is nothing to report.\n"
    "\n"
    "options:\n"
    "  --budget SECONDS    time limit for the whole check, 0.5 to 60 (default 10)\n"
    "  --as-of YYYY-MM-DD  score as of this date (for tests)\n"
    "  --help, --version   show this text or the version and exit 0\n"
    "\n"
    "exit codes:\n" + HOOK_EXIT_TABLE + "\n"
)


class CheckUsage(Exception):
    """A usage problem; the reason is a fixed string (KPW-CMD-3)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class CheckOptions:
    command: str | None = None
    budget: float = DEFAULT_BUDGET_SECONDS
    as_of: date | None = None
    action: str = "check"  # "check", "help" or "version"


def _parse_budget(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise CheckUsage("--budget: expected a number of seconds from 0.5 to 60") from None
    if not math.isfinite(value) or not MIN_BUDGET <= value <= MAX_BUDGET:
        raise CheckUsage("--budget: expected a number of seconds from 0.5 to 60")
    return value


def _option_value(argv: Sequence[str], index: int, name: str) -> tuple[str, int]:
    """The value of option ``name`` (``--name=v`` or ``--name v``) and the next index."""
    token = argv[index]
    if token.startswith(name + "="):
        return token[len(name) + 1 :], index + 1
    if index + 1 >= len(argv):
        raise CheckUsage(f"{name}: a value is required")
    return argv[index + 1], index + 2


def parse_check_args(argv: Sequence[str], *, today: date) -> CheckOptions:
    """Parse the arguments after ``check-install``. Raises ``CheckUsage`` with a fixed reason."""
    command: str | None = None
    budget = DEFAULT_BUDGET_SECONDS
    as_of: date | None = None
    only_positionals = False
    i = 0
    while i < len(argv):
        token = argv[i]
        if only_positionals or not token.startswith("-") or token == "-":
            if command is not None:
                raise CheckUsage("only one COMMAND is allowed")
            command = token
            i += 1
        elif token == "--":
            only_positionals = True
            i += 1
        elif token in ("--help", "-h"):
            return CheckOptions(action="help")
        elif token == "--version":
            return CheckOptions(action="version")
        elif token == "--budget" or token.startswith("--budget="):
            value, i = _option_value(argv, i, "--budget")
            budget = _parse_budget(value)
        elif token == "--as-of" or token.startswith("--as-of="):
            value, i = _option_value(argv, i, "--as-of")
            try:
                as_of = _parse_as_of(value, today)
            except UsageError as error:
                raise CheckUsage(sanitise(error.message)[:80]) from None
        else:
            raise CheckUsage("unknown option")
    return CheckOptions(command=command, budget=budget, as_of=as_of)


# ----------------------------------------------------------------------------- evaluate


def _remaining(deadline: float, loop: asyncio.AbstractEventLoop) -> float:
    return max(0.0, deadline - loop.time())


async def _resolve(
    session: SourceSession, targets: Sequence[Target], deadline: float
) -> Mapping[str, LatestResult] | None:
    """Latest versions of the non-pinned targets, or ``None`` if the deadline passed."""
    texts: list[str] = []
    for target in targets:
        if isinstance(target.spec, Pinned):
            continue
        try:
            texts.append(target.purl_text(None))
        except ValueError:
            continue
    if not texts:
        return {}
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(session.resolve_latest(texts), _remaining(deadline, loop))
    except TimeoutError:
        return None


async def _one(
    target: Target,
    session: SourceSession,
    latest: Mapping[str, LatestResult],
    as_of: date,
) -> Outcome:
    """Resolve, autopsy and rank one target (design §7.3)."""
    try:
        if isinstance(target.spec, Pinned):
            version: str | None = target.spec.version
        else:
            found = latest.get(target.purl_text(None))
            version = found.version if found is not None else None
        if version is None:
            return Unresolved(target.name)
        purl = target.purl_text(version)
    except ValueError:
        return Failed(target.name)
    batch = await session.collect([(purl, as_of)])
    result = batch.results[0]
    if result.error is not None or result.signals is None:
        return Failed(purl)
    opts = parse_args(["autopsy", "--purl", purl, "--fail-on", "dead,cursed"], today=as_of)
    report = rank([None], [result], batch.stats, None, PURL_INPUTS, opts, as_of)
    if not report.rows:
        return Failed(purl)
    row = report.rows[0]
    return Checked(
        purl=purl,
        state=row.scoring.base_state,
        dead_reason=row.scoring.dead_reason,
        cursed=row.scoring.cursed,
        gate_eligible=row.gate_eligible,
        is_range=isinstance(target.spec, Range),
        why=row.why,
        unverified=row.unverified,
    )


async def evaluate(
    targets: Sequence[Target],
    env: CliEnvironment,
    transport: Transport | None,
    clock: Clock,
    as_of: date,
    budget: float,
) -> list[Outcome]:
    """One outcome per target, in order, under a single deadline (KPW-BUD-1, KPW-BUD-2)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + budget
    outcomes: dict[int, Outcome] = {}
    tasks: dict[asyncio.Task[Outcome], int] = {}
    async with SourceSession(
        make_config(env), token=env.token, transport=transport, clock=clock
    ) as session:
        try:
            # Pinned targets need no resolution: start them first so a slow resolve step
            # cannot use up the time they need (KPW-BUD-2).
            for index, target in enumerate(targets):
                if isinstance(target.spec, Pinned):
                    tasks[asyncio.create_task(_one(target, session, {}, as_of))] = index
            latest = await _resolve(session, targets, deadline)
            for index, target in enumerate(targets):
                if isinstance(target.spec, Pinned):
                    continue
                if latest is None:
                    outcomes[index] = TimedOut(target.name)
                    continue
                tasks[asyncio.create_task(_one(target, session, latest, as_of))] = index
            if tasks:
                await asyncio.wait(tasks, timeout=_remaining(deadline, loop))
            for task, index in tasks.items():
                if task.done():
                    outcomes[index] = task.result()  # a bug in a task surfaces to the guard
                else:
                    outcomes[index] = TimedOut(targets[index].name)
        finally:
            pending = [task for task in tasks if not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
    return [outcomes[index] for index in range(len(targets))]


# --------------------------------------------------------------------------------- run


def _file_note(load: RequirementLoad) -> FileNote | None:
    """The KPW-REQ-7 fragment for one loaded file, or ``None`` when there is nothing to say."""
    if load.reason != "ok":
        return FileNote(f"{load.name}: not read ({load.reason})")
    if load.not_checked > 0:
        return FileNote(
            f"{load.name}: {load.not_checked} lines not checked (unpinned, URL or path, nested -r)"
        )
    return None


def _gather_targets(
    payload: HookPayload, refs: Sequence[RequirementRef], command_targets: Sequence[Target]
) -> tuple[list[Target], list[FileNote], bool, int]:
    """Command-line targets, then file targets; de-duplicated; capped at 20 (KPW-REQ-5).

    The last item is the number of distinct targets found before the cap.
    """
    targets: list[Target] = list(command_targets)
    seen = {(t.ecosystem, t.name) for t in targets}
    notes: list[FileNote] = []
    truncated = False
    if refs:
        base = base_directory(payload.cwd)
        for ref in refs:
            load = load_requirements(ref, base)
            note = _file_note(load)
            if note is not None:
                notes.append(note)
            for target in load.targets:
                key = (target.ecosystem, target.name)
                if key not in seen:
                    seen.add(key)
                    targets.append(target)
    total = len(targets)
    if total > CHECK_LIMIT:
        targets = targets[:CHECK_LIMIT]
        truncated = True
    return targets, notes, truncated, total


def _internal_error_note(exc: Exception) -> str:
    name = type(exc).__name__
    name = name if _IDENTIFIER.fullmatch(name) else "Error"
    return f"graveyard check-install: internal error ({sanitise(name)}); nothing was checked\n"


def run(
    argv: Sequence[str],
    *,
    env: CliEnvironment,
    out: TextIO,
    err: TextIO,
    stdin: Callable[[], str | None] | None = None,
    transport: Transport | None = None,
    clock: Clock | None = None,
) -> int:
    """Run ``check-install`` for ``argv`` (after the subcommand name); return 0 or 2 only."""
    try:
        clk: Clock = clock if clock is not None else SystemClock()
        today = clk.now().astimezone(UTC).date()
        opts = parse_check_args(argv, today=today)
        if opts.action == "help":
            out.write(HELP_TEXT)
            return 0
        if opts.action == "version":
            out.write(f"graveyard {_version()}\n")
            return 0
        if opts.command is not None:
            payload: HookPayload | None = HookPayload(opts.command, None)
        else:
            payload = extract_payload((stdin() if stdin is not None else None) or "")
        if payload is None:
            return 0
        parsed = parse_install(payload.command)
        if not parsed.targets and not parsed.requirement_files:
            return 0
        targets, notes, capped, total = _gather_targets(
            payload, parsed.requirement_files, parsed.targets
        )
        truncated = parsed.truncated or capped
        if parsed.truncated:
            # the parser stops at 20 distinct targets and does not count the rest: at least 21
            total = max(total, CHECK_LIMIT + 1)
        outcomes: list[Outcome] = []
        if targets:
            as_of = opts.as_of or today
            outcomes = asyncio.run(evaluate(targets, env, transport, clk, as_of, opts.budget))
        decision = decide(
            outcomes,
            truncated=truncated,
            files=notes,
            total_targets=total,
            budget_seconds=opts.budget,
        )
        out.write(decision.stdout)
        err.write(decision.stderr)
        return int(decision.exit)
    except CheckUsage as usage:
        out.write(f"graveyard check-install: {usage.reason}; nothing was checked\n")
        return 0
    except Exception as exc:  # noqa: BLE001 - KPW-CMD-4: nothing may turn into a block
        out.write(_internal_error_note(exc))
        return 0
