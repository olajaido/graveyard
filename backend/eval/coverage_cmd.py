"""The ``coverage`` subcommand: write the held-out coverage report (design 10.5, MV2-SMP-6).

Reads five files under ``<data dir>/heldout`` and writes exactly ``coverage.json`` and
``coverage.md`` there, each by a temporary file and rename. Exit codes: 0 written, 2 usage
error, 3 input error.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final, TextIO

from eval.heldout.coverage import (
    CoverageError,
    build_coverage,
    parse_no_label,
    parse_query_log,
    render_json,
    render_markdown,
)
from eval.heldout.strata import StrataError, parse_strata
from eval.labels import LabelsError, parse_labels
from eval.paths import DEFAULT_DATA_DIR

EXIT_OK: Final = 0
EXIT_USAGE: Final = 2
EXIT_INPUT: Final = 3
USAGE: Final = "usage: python -m eval coverage\n"
HELDOUT_DIR: Final = "heldout"
OUTPUTS: Final = ("coverage.json", "coverage.md")


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8", newline="\n")
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def run_coverage(
    argv: Sequence[str],
    *,
    out: TextIO,
    err: TextIO,
    data_dir: Path = DEFAULT_DATA_DIR,
) -> int:
    """Write the coverage report into ``data_dir/heldout`` and return the exit code."""
    if argv:
        err.write(USAGE)
        return EXIT_USAGE
    base = data_dir / HELDOUT_DIR
    try:
        draw: Any = json.loads((base / "draw" / "draw.json").read_text(encoding="utf-8"))
        if not isinstance(draw, dict):
            raise CoverageError(["draw.json is not a JSON object"])
        doc = build_coverage(
            draw,
            parse_strata((base / "draw" / "strata.tsv").read_text(encoding="utf-8")),
            parse_labels((base / "labelled_packages.csv").read_text(encoding="utf-8")),
            parse_no_label((base / "draw" / "no-label.tsv").read_text(encoding="utf-8")),
            parse_query_log((base / "f" / "raw" / "query-log.tsv").read_text(encoding="utf-8")),
        )
    except (CoverageError, StrataError, LabelsError) as exc:
        err.write(f"eval: coverage input error: {'; '.join(exc.errors)}\n")
        return EXIT_INPUT
    except (OSError, ValueError) as exc:
        err.write(f"eval: cannot read coverage inputs: {exc}\n")
        return EXIT_INPUT
    try:
        _write_atomic(base / OUTPUTS[0], render_json(doc))
        _write_atomic(base / OUTPUTS[1], render_markdown(doc))
    except OSError as exc:
        err.write(f"eval: cannot write {base}: {exc.strerror or exc}\n")
        return EXIT_INPUT
    out.write(f"eval: wrote {HELDOUT_DIR}/{OUTPUTS[0]} and {HELDOUT_DIR}/{OUTPUTS[1]}\n")
    return EXIT_OK
