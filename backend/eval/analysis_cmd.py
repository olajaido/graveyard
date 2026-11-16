"""The ``analysis`` subcommand: read the v1 inputs, write the failure report (design 6, MV2-FA-2).

Reads through the loaders ``run()`` uses, so the same input problems give the same exit 3.
Hash computation and file I/O live here; ``eval.analysis`` stays pure. Writes only
``analysis/v1-failures.json`` and ``analysis/v1-failures.md`` under the data folder, each by a
temporary file and rename. Exit codes: 0 written, 2 usage error, 3 input error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final, NoReturn, TextIO

from core.scoring.weights import DEFAULT_WEIGHTS_PATH, load_weights
from eval.analysis import build_analysis, render_markdown
from eval.fixture import FixtureError, load_fixtures
from eval.gate import frozen_weights_ok
from eval.labels import LabelsError, load_labels
from eval.paths import DEFAULT_DATA_DIR
from eval.run import EXIT_INPUT, EXIT_USAGE, FROZEN_MESSAGE, _write_atomic

EXIT_OK: Final = 0
USAGE: Final = "usage: python -m eval analysis [--all]\n"
ANALYSIS_DIR: Final = "analysis"
JSON_NAME: Final = "v1-failures.json"
MD_NAME: Final = "v1-failures.md"


class _UsageError(Exception):
    """Raised by the parser instead of exiting the process."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise _UsageError(message)

    def exit(self, status: int = 0, message: str | None = None) -> NoReturn:
        raise _UsageError(message or "")


def _input_error(err: TextIO, message: str) -> int:
    err.write(f"eval: {message}\n")
    return EXIT_INPUT


def _load_results(path: Path) -> dict[str, Any]:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError(f"{path.name} is not a JSON object")
    return parsed


def run_analysis(
    argv: Sequence[str],
    *,
    out: TextIO,
    err: TextIO,
    data_dir: Path = DEFAULT_DATA_DIR,
) -> int:
    """Write the v1 failure report for ``data_dir`` and return the exit code."""
    parser = _Parser(prog="python -m eval analysis", add_help=False, allow_abbrev=False)
    parser.add_argument("--all", action="store_true", dest="all_rows")
    try:
        all_rows: bool = parser.parse_args(list(argv)).all_rows
    except _UsageError as exc:
        err.write(f"eval: {exc}\n" if str(exc) else "")
        err.write(USAGE)
        return EXIT_USAGE

    try:
        label_rows, labels_sha = load_labels(data_dir / "labelled_packages.csv")
    except LabelsError as exc:
        details = "; ".join(getattr(exc, "errors", ()) or (str(exc),))
        return _input_error(err, f"invalid labelled set: {details}")
    except OSError as exc:
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
        results = _load_results(data_dir / "results.json")
    except FixtureError as exc:
        return _input_error(err, str(exc))
    except (OSError, ValueError) as exc:
        return _input_error(err, f"cannot read results.json: {exc}")

    doc = build_analysis(
        label_rows,
        fixtures,
        load_weights(),
        all_rows,
        weights_sha256=weights_sha,
        labels_sha256=labels_sha,
        results=results,
    )
    json_text = json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    target = data_dir / ANALYSIS_DIR
    try:
        target.mkdir(parents=True, exist_ok=True)
        _write_atomic(target / JSON_NAME, json_text)
        _write_atomic(target / MD_NAME, render_markdown(doc))
    except OSError as exc:
        return _input_error(err, f"cannot write {target}: {exc.strerror or exc}")

    out.write(f"eval: wrote {ANALYSIS_DIR}/{JSON_NAME} and {ANALYSIS_DIR}/{MD_NAME}\n")
    return EXIT_OK
