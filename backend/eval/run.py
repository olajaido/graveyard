"""The eval run: load, validate, score both variants, gate, write, report (EV-RUN-1 to EV-RUN-5).

``run`` is the test seam. It writes only to the streams it is given, reads no environment
variable and no clock, and never exits the process; ``__main__`` turns the return code into an
exit status. Exit codes: 0 gate passed, 1 gate failed, 2 usage error, 3 input error.
"""

from __future__ import annotations

import argparse
import hashlib
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Final, NoReturn, TextIO

from cli.gate import unverified_sources
from core.scoring import score_package
from core.scoring.types import ScoringResult
from core.scoring.weights import DEFAULT_WEIGHTS_PATH
from eval.fixture import FixtureError, load_fixtures, no_github_variant
from eval.gate import GateConfigError, evaluate_gate, frozen_weights_ok, load_gate_config
from eval.labels import LabelsError, load_labels
from eval.outcome import Outcome, outcome_from
from eval.paths import DEFAULT_DATA_DIR
from eval.report import build_results, dumps, render_console

EXIT_PASS: Final = 0
EXIT_GATE_FAILED: Final = 1
EXIT_USAGE: Final = 2
EXIT_INPUT: Final = 3

MODEL_VERSION: Final = "v1"
USAGE: Final = "usage: python -m eval [--out PATH]\n"
FROZEN_MESSAGE: Final = "weights are frozen; a change is a documented v2"


class _UsageError(Exception):
    """Raised by the parser instead of exiting the process."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise _UsageError(message)

    def exit(self, status: int = 0, message: str | None = None) -> NoReturn:
        raise _UsageError(message or "")


def _parse(argv: Sequence[str]) -> Path | None:
    """Return the ``--out`` path (or None for the default); raise ``_UsageError`` otherwise."""
    parser = _Parser(prog="python -m eval", add_help=False, allow_abbrev=False)
    parser.add_argument("--out", type=Path, default=None)
    out: Path | None = parser.parse_args(list(argv)).out
    return out


def _input_error(err: TextIO, message: str) -> int:
    err.write(f"eval: {message}\n")
    return EXIT_INPUT


def _write_atomic(path: Path, text: str) -> None:
    """Write via a temp file in the same directory, then rename over the target."""
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8", newline="\n")
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def run(
    argv: Sequence[str],
    *,
    out: TextIO,
    err: TextIO,
    data_dir: Path = DEFAULT_DATA_DIR,
) -> int:
    """Run the harness on ``data_dir`` and return the exit code."""
    try:
        out_arg = _parse(argv)
    except _UsageError as exc:
        err.write(f"eval: {exc}\n" if str(exc) else "")
        err.write(USAGE)
        return EXIT_USAGE
    results_path = data_dir / "results.json" if out_arg is None else out_arg

    try:
        label_rows, labels_sha = load_labels(data_dir / "labelled_packages.csv")
        config = load_gate_config(data_dir / "gate.yaml")
    except LabelsError as exc:
        details = "; ".join(getattr(exc, "errors", ()) or (str(exc),))
        return _input_error(err, f"invalid labelled set: {details}")
    except (GateConfigError, OSError) as exc:
        return _input_error(err, str(exc))

    if not frozen_weights_ok(DEFAULT_WEIGHTS_PATH, data_dir / "FROZEN_WEIGHTS.sha256"):
        return _input_error(
            err, f"weights.v1.yaml differs from FROZEN_WEIGHTS.sha256; {FROZEN_MESSAGE}"
        )
    weights_sha = hashlib.sha256(DEFAULT_WEIGHTS_PATH.read_bytes()).hexdigest()

    try:
        fixtures = load_fixtures(
            data_dir / "fixtures", {(r.ecosystem, r.name): r.version for r in label_rows}
        )
    except FixtureError as exc:
        return _input_error(err, str(exc))

    results: list[ScoringResult] = []
    outcomes: list[Outcome] = []
    ng_results: list[ScoringResult] = []
    ng_outcomes: list[Outcome] = []
    for row in label_rows:
        fx = fixtures[(row.ecosystem, row.name)]
        res = score_package(fx.signals)
        ng_signals, ng_warnings = no_github_variant(fx)
        ng_res = score_package(ng_signals)
        for r in (res, ng_res):
            if r.model_version != MODEL_VERSION:
                return _input_error(
                    err,
                    f"{row.ecosystem}/{row.name}: model_version {r.model_version!r} "
                    f"is not {MODEL_VERSION!r}; {FROZEN_MESSAGE}",
                )
        results.append(res)
        outcomes.append(outcome_from(row, res, unverified_sources(res, fx.signals, fx.warnings)))
        ng_results.append(ng_res)
        ng_outcomes.append(
            outcome_from(row, ng_res, unverified_sources(ng_res, ng_signals, ng_warnings))
        )

    as_of = next(iter(fixtures.values())).as_of if fixtures else None
    gate = evaluate_gate([o for o in outcomes if o.reviewed], config)
    document = build_results(
        model_version=MODEL_VERSION,
        weights_sha256=weights_sha,
        labels_sha256=labels_sha,
        as_of=as_of,
        config=config,
        gate=gate,
        label_rows=label_rows,
        results=results,
        outcomes=outcomes,
        no_github_results=ng_results,
        no_github_outcomes=ng_outcomes,
    )
    try:
        _write_atomic(results_path, dumps(document))
    except OSError as exc:
        return _input_error(err, f"cannot write {results_path}: {exc.strerror or exc}")

    out.write(render_console(document))
    if gate.passed:
        return EXIT_PASS
    err.write("eval: gate failed\n")
    for check in gate.checks:
        if not check.passed:
            value = "n/a" if check.value is None else f"{check.value:.3f}"
            err.write(
                f"  {check.name}: value {value}, threshold {check.threshold:.3f}, "
                f"n {check.num}/{check.den} ({check.reason})\n"
            )
    err.write(f"eval: {FROZEN_MESSAGE}\n")
    return EXIT_GATE_FAILED
