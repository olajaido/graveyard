"""The ``compare`` subcommand: write the v1 to v2 held-out comparison (design 11.5).

Reads ``heldout/results.v1.json`` and ``heldout/results.v2.json`` and writes ``comparison.json``
and ``comparison.md`` beside them, each by a temporary file and rename (it may be regenerated).
Exit codes: 0 written, 2 usage error, 3 input error or mismatched provenance.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final, TextIO

from eval.heldout.compare import CompareError, build_comparison, render_json, render_markdown
from eval.paths import DEFAULT_DATA_DIR

EXIT_OK: Final = 0
EXIT_USAGE: Final = 2
EXIT_INPUT: Final = 3
USAGE: Final = "usage: python -m eval compare\n"
HELDOUT_DIR: Final = "heldout"
INPUTS: Final = ("results.v1.json", "results.v2.json")
OUTPUTS: Final = ("comparison.json", "comparison.md")


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8", newline="\n")
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def _load(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path.name} is not a JSON object")
    return loaded


def run_compare(
    argv: Sequence[str],
    *,
    out: TextIO,
    err: TextIO,
    data_dir: Path = DEFAULT_DATA_DIR,
) -> int:
    """Write the comparison into ``data_dir/heldout`` and return the exit code."""
    if argv:
        err.write(USAGE)
        return EXIT_USAGE
    base = data_dir / HELDOUT_DIR
    try:
        doc = build_comparison(_load(base / INPUTS[0]), _load(base / INPUTS[1]))
    except CompareError as exc:
        err.write(f"eval: compare refused: {'; '.join(exc.errors)}\n")
        return EXIT_INPUT
    except (OSError, ValueError) as exc:
        err.write(f"eval: cannot read comparison inputs: {exc}\n")
        return EXIT_INPUT
    try:
        _write_atomic(base / OUTPUTS[0], render_json(doc))
        _write_atomic(base / OUTPUTS[1], render_markdown(doc))
    except OSError as exc:
        err.write(f"eval: cannot write {base}: {exc.strerror or exc}\n")
        return EXIT_INPUT
    out.write(f"eval: wrote {HELDOUT_DIR}/{OUTPUTS[0]} and {HELDOUT_DIR}/{OUTPUTS[1]}\n")
    return EXIT_OK
