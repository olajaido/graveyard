"""The eval run: load, validate, score both variants, gate, write, report (EV-RUN-1 to EV-RUN-5).

``run`` is the test seam. It writes only to the streams it is given, reads no environment
variable and no clock, and never exits the process; ``__main__`` turns the return code into an
exit status. Exit codes: 0 gate passed (held-out: PASS), 1 gate failed (FAIL), 2 usage error,
3 input error, 4 INCONCLUSIVE (held-out only).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, NoReturn, TextIO

from cli.gate import unverified_sources
from core.scoring.types import ScoringResult
from core.scoring.weights import load_weights
from eval.fixture import FixtureError, load_fixtures, no_github_variant
from eval.gate import (
    GateConfigError,
    evaluate_gate,
    frozen_weights_ok,
    load_gate_config,
    load_min_dead_flagged_rate,
)
from eval.heldout.datasets import DATASETS, DEFAULT_DATASET, Dataset
from eval.heldout.provenance import (
    CaptureLogRow,
    ProvenanceError,
    build_provenance,
    fixture_set_sha256,
    parse_amendments,
    parse_capture_log,
    sha256_bytes,
)
from eval.heldout.report import (
    NotCapturedRow,
    ReportRow,
    build_heldout,
)
from eval.heldout.report import render_console as render_heldout_console
from eval.heldout.strata import StrataError, StratumRow, join_strata, parse_strata
from eval.heldout.verdict import evaluate_verdict
from eval.labels import LabelRow, LabelsError, load_labels
from eval.models import DEFAULT_MODEL, MODELS, ModelSpec
from eval.outcome import Outcome, outcome_from
from eval.paths import DEFAULT_DATA_DIR
from eval.report import build_results, dumps, render_console

EXIT_PASS: Final = 0
EXIT_GATE_FAILED: Final = 1
EXIT_USAGE: Final = 2
EXIT_INPUT: Final = 3
EXIT_INCONCLUSIVE: Final = 4

MODEL_VERSION: Final = DEFAULT_MODEL
USAGE: Final = (
    "usage: python -m eval [--model v1|v2] [--dataset v1|heldout] [--out PATH] [--insample]\n"
)
FROZEN_MESSAGE: Final = "weights are frozen; a change is a documented v2"


class _UsageError(Exception):
    """Raised by the parser instead of exiting the process."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise _UsageError(message)

    def exit(self, status: int = 0, message: str | None = None) -> NoReturn:
        raise _UsageError(message or "")


@dataclass(frozen=True)
class _Args:
    model: ModelSpec
    dataset: Dataset
    out: Path | None
    insample: bool


def _parse(argv: Sequence[str]) -> _Args:
    """Parse the command line; raise ``_UsageError`` on any problem (design 11.1)."""
    parser = _Parser(prog="python -m eval", add_help=False, allow_abbrev=False)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--insample", action="store_true")
    ns = parser.parse_args(list(argv))
    model = MODELS.get(ns.model)
    if model is None:
        raise _UsageError(f"unknown --model {ns.model!r}; known: {', '.join(sorted(MODELS))}")
    dataset = DATASETS.get(ns.dataset)
    if dataset is None:
        raise _UsageError(f"unknown --dataset {ns.dataset!r}; known: {', '.join(sorted(DATASETS))}")
    if ns.insample and dataset.name == "heldout":
        raise _UsageError("--insample cannot be used with --dataset heldout")
    if ns.insample and (model.version != "v2" or dataset.name != "v1"):
        raise _UsageError("--insample needs --model v2 --dataset v1")
    if model.version != "v1" and dataset.name == "v1" and not ns.insample:
        raise _UsageError(f"--model {model.version} --dataset v1 needs --insample")
    return _Args(model=model, dataset=dataset, out=ns.out, insample=bool(ns.insample))


class _InputError(Exception):
    """A held-out input is missing or invalid; the message goes to stderr with exit 3."""


@dataclass(frozen=True)
class _HeldoutInputs:
    strata: Mapping[tuple[str, str], StratumRow]
    draw: Mapping[str, Any]
    snapshot_hashes: Mapping[str, str]
    batch_log_sha256: str
    capture_log_sha256: str
    capture_rows: tuple[CaptureLogRow, ...]
    frozen_harness_sha256: str
    amendments_text: str | None
    amendments_sha256: str | None
    gate_config_sha256: str


def _read_bytes(path: Path, what: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise _InputError(f"cannot read {what}: {exc.strerror or exc}") from None


def _read_json_object(path: Path, what: str) -> dict[str, Any]:
    try:
        loaded = json.loads(_read_bytes(path, what).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise _InputError(f"{what} is not valid JSON") from None
    if not isinstance(loaded, dict):
        raise _InputError(f"{what} is not a JSON object")
    return loaded


def _snapshot_hashes(pins: Mapping[str, Any]) -> dict[str, str]:
    sources = pins.get("sources")
    if not isinstance(sources, dict) or not sources:
        raise _InputError("snapshot/pins.json has no sources")
    hashes: dict[str, str] = {}
    for source_id, entry in sources.items():
        digest = entry.get("trimmed_sha256") if isinstance(entry, dict) else None
        if not isinstance(digest, str):
            raise _InputError(f"snapshot/pins.json: {source_id}: no trimmed_sha256")
        hashes[str(source_id)] = digest
    return hashes


def _read_heldout_inputs(
    base: Path, gate_path: Path, label_rows: Sequence[LabelRow]
) -> _HeldoutInputs:
    """Read and check the held-out inputs next to the labelled set (design 11.2)."""
    unreviewed = [f"{r.ecosystem}/{r.name}" for r in label_rows if not r.reviewed]
    if unreviewed:
        shown = ", ".join(unreviewed[:5]) + (", ..." if len(unreviewed) > 5 else "")
        raise _InputError(f"{len(unreviewed)} labelled rows are not reviewed: {shown}")
    try:
        strata_text = _read_bytes(base / "draw" / "strata.tsv", "draw/strata.tsv").decode("utf-8")
        joined = join_strata(label_rows, parse_strata(strata_text))
    except UnicodeDecodeError:
        raise _InputError("draw/strata.tsv is not valid UTF-8") from None
    except StrataError as exc:
        raise _InputError("strata: " + "; ".join(exc.errors)) from None
    draw = _read_json_object(base / "draw" / "draw.json", "draw/draw.json")
    if not isinstance(draw.get("seed"), str) or not isinstance(draw.get("draw_date"), str):
        raise _InputError("draw/draw.json needs string seed and draw_date")
    pins = _read_json_object(base / "snapshot" / "pins.json", "snapshot/pins.json")
    capture_bytes = _read_bytes(base / "capture-log.tsv", "capture-log.tsv")
    try:
        capture_rows = parse_capture_log(capture_bytes.decode("utf-8"))
    except UnicodeDecodeError:
        raise _InputError("capture-log.tsv is not valid UTF-8") from None
    except ProvenanceError as exc:
        raise _InputError("; ".join(exc.errors)) from None
    amendments_path = base / "AMENDMENTS.md"
    amendments_bytes = (
        _read_bytes(amendments_path, "AMENDMENTS.md") if amendments_path.exists() else None
    )
    try:
        amendments_text = None if amendments_bytes is None else amendments_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise _InputError("AMENDMENTS.md is not valid UTF-8") from None
    return _HeldoutInputs(
        strata={row.key: stratum for row, stratum in joined},
        draw=draw,
        snapshot_hashes=_snapshot_hashes(pins),
        batch_log_sha256=sha256_bytes(
            _read_bytes(base / "draw" / "batch-log.tsv", "draw/batch-log.tsv")
        ),
        capture_log_sha256=sha256_bytes(capture_bytes),
        capture_rows=capture_rows,
        frozen_harness_sha256=sha256_bytes(
            _read_bytes(base / "FROZEN_HARNESS.json", "FROZEN_HARNESS.json")
        ),
        amendments_text=amendments_text,
        amendments_sha256=None if amendments_bytes is None else sha256_bytes(amendments_bytes),
        gate_config_sha256=sha256_bytes(_read_bytes(gate_path, "gate.yaml")),
    )


def _latest_version(raw: Mapping[str, Any]) -> str | None:
    value = raw.get("latest_version")
    return value if isinstance(value, str) else None


def _fixture_set_hash(root: Path) -> str:
    """Hash of every fixture file under ``root``, paths ``<ecosystem>/<name>.json``."""
    hashes = {
        path.relative_to(root).as_posix(): sha256_bytes(path.read_bytes())
        for path in root.rglob("*.json")
        if len(path.relative_to(root).parts) >= 2
    }
    return fixture_set_sha256(hashes)


def _s1_declared(raw: Mapping[str, Any]) -> bool | None:
    """True if registry deprecation or archived repository holds; False if both are false."""
    parts = raw.get("s1_parts")
    values: list[object] = []
    if isinstance(parts, Mapping):
        for key in ("registry_deprecated", "repo_archived"):
            entry = parts.get(key)
            values.append(entry.get("value") if isinstance(entry, Mapping) else None)
    if any(v is True for v in values):
        return True
    if values and all(v is False for v in values):
        return False
    return None


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


def _write_exclusive(path: Path, text: str) -> None:
    """Create ``path`` and write ``text``; raise ``FileExistsError`` if it exists."""
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def run(
    argv: Sequence[str],
    *,
    out: TextIO,
    err: TextIO,
    data_dir: Path = DEFAULT_DATA_DIR,
) -> int:
    """Run the harness on ``data_dir`` and return the exit code."""
    try:
        args = _parse(argv)
    except _UsageError as exc:
        err.write(f"eval: {exc}\n" if str(exc) else "")
        err.write(USAGE)
        return EXIT_USAGE
    spec, dataset = args.model, args.dataset
    results_path = (
        data_dir / dataset.default_out.format(model=spec.version) if args.out is None else args.out
    )

    try:
        label_rows, labels_sha = load_labels(data_dir / dataset.labels)
        config = load_gate_config(data_dir / dataset.gate)
        min_dead_flagged = (
            load_min_dead_flagged_rate(data_dir / dataset.gate)
            if dataset.name == "heldout"
            else None
        )
    except LabelsError as exc:
        details = "; ".join(getattr(exc, "errors", ()) or (str(exc),))
        return _input_error(err, f"invalid labelled set: {details}")
    except (GateConfigError, OSError) as exc:
        return _input_error(err, str(exc))

    heldout = dataset.name == "heldout"
    inputs: _HeldoutInputs | None = None
    if heldout:
        if min_dead_flagged is None:
            return _input_error(err, "heldout gate.yaml needs min_dead_flagged_rate")
        if dataset.write_mode == "exclusive" and results_path.exists():
            return _input_error(err, f"{results_path} already exists; it is never overwritten")
        try:
            inputs = _read_heldout_inputs(
                (data_dir / dataset.labels).parent, data_dir / dataset.gate, label_rows
            )
        except _InputError as exc:
            return _input_error(err, str(exc))

    if not frozen_weights_ok(spec.weights_path, data_dir / spec.digest_file):
        return _input_error(
            err, f"weights.v1.yaml differs from FROZEN_WEIGHTS.sha256; {FROZEN_MESSAGE}"
        )
    weights_sha = hashlib.sha256(spec.weights_path.read_bytes()).hexdigest()

    fixtures_root = data_dir / dataset.fixtures
    scored_rows: Sequence[LabelRow] = label_rows
    missing_rows: list[LabelRow] = []
    if heldout:
        # NOT CAPTURED (MV2-RUN-3): a row with no fixture is listed and not scored.
        scored_rows = [
            r for r in label_rows if (fixtures_root / r.ecosystem / f"{r.name}.json").is_file()
        ]
        missing_rows = [r for r in label_rows if r not in scored_rows]
    try:
        fixtures = load_fixtures(
            fixtures_root, {(r.ecosystem, r.name): r.version for r in scored_rows}
        )
    except FixtureError as exc:
        return _input_error(err, str(exc))

    results: list[ScoringResult] = []
    outcomes: list[Outcome] = []
    ng_results: list[ScoringResult] = []
    ng_outcomes: list[Outcome] = []
    for row in scored_rows:
        fx = fixtures[(row.ecosystem, row.name)]
        res = spec.score(fx.signals)
        ng_signals, ng_warnings = no_github_variant(fx)
        ng_res = spec.score(ng_signals)
        for r in (res, ng_res):
            if r.model_version != spec.version:
                return _input_error(
                    err,
                    f"{row.ecosystem}/{row.name}: model_version {r.model_version!r} "
                    f"is not {spec.version!r}; {FROZEN_MESSAGE}",
                )
        results.append(res)
        outcomes.append(outcome_from(row, res, unverified_sources(res, fx.signals, fx.warnings)))
        ng_results.append(ng_res)
        ng_outcomes.append(
            outcome_from(row, ng_res, unverified_sources(ng_res, ng_signals, ng_warnings))
        )

    as_of = next(iter(fixtures.values())).as_of if fixtures else None
    gate = evaluate_gate(
        [o for o in outcomes if o.reviewed], config, min_dead_flagged_rate=min_dead_flagged
    )
    document = build_results(
        model_version=spec.version,
        weights_sha256=weights_sha,
        labels_sha256=labels_sha,
        as_of=as_of,
        config=config,
        gate=gate,
        label_rows=scored_rows,
        results=results,
        outcomes=outcomes,
        no_github_results=ng_results,
        no_github_outcomes=ng_outcomes,
    )
    verdict = None
    if heldout and inputs is not None:
        try:
            verdict = evaluate_verdict(gate)
            document["provenance"] = build_provenance(
                model_version=spec.version,
                weights_sha256=weights_sha,
                manifest_sha256=None,
                labels_sha256=labels_sha,
                fixture_set_sha256=_fixture_set_hash(fixtures_root),
                gate_config_sha256=inputs.gate_config_sha256,
                seed=str(inputs.draw["seed"]),
                snapshot_hashes=inputs.snapshot_hashes,
                draw_date=str(inputs.draw["draw_date"]),
                as_of=as_of,
                batch_log_sha256=inputs.batch_log_sha256,
                capture_log_sha256=inputs.capture_log_sha256,
                frozen_harness_sha256=inputs.frozen_harness_sha256,
                amendments_sha256=inputs.amendments_sha256,
            )
        except ProvenanceError as exc:
            return _input_error(err, "provenance: " + "; ".join(exc.errors))
        report_rows = [
            ReportRow(
                outcome=outcome,
                stratum=inputs.strata[(row.ecosystem, row.name)].stratum,
                mortality=res.mortality,
                s1_declared=_s1_declared(fixtures[(row.ecosystem, row.name)].raw),
                latest_version=_latest_version(fixtures[(row.ecosystem, row.name)].raw),
                latest_version_at_draw=inputs.strata[
                    (row.ecosystem, row.name)
                ].latest_version_at_draw,
            )
            for row, res, outcome in zip(scored_rows, results, outcomes, strict=True)
        ]
        document["heldout"] = build_heldout(
            verdict=verdict,
            rows=report_rows,
            not_captured=[
                NotCapturedRow(
                    r.ecosystem, r.name, r.label, inputs.strata[(r.ecosystem, r.name)].stratum
                )
                for r in missing_rows
            ],
            threshold_dead=load_weights(spec.weights_path).threshold_dead,
            recaptured=[c for c in inputs.capture_rows if c.form != "not_captured"],
            amendments=parse_amendments(inputs.amendments_text),
            draw=inputs.draw,
        )

    try:
        if dataset.write_mode == "exclusive":
            _write_exclusive(results_path, dumps(document))
        else:
            _write_atomic(results_path, dumps(document))
    except FileExistsError:
        return _input_error(err, f"{results_path} already exists; it is never overwritten")
    except OSError as exc:
        return _input_error(err, f"cannot write {results_path}: {exc.strerror or exc}")

    if heldout and verdict is not None:
        out.write(render_heldout_console(document["heldout"]))
        for nc in document["heldout"]["not_captured"]:
            out.write(
                f"NOT CAPTURED: {nc['ecosystem']}/{nc['name']} ({nc['label']}, {nc['stratum']})\n"
            )
        if verdict.verdict == "PASS":
            return EXIT_PASS
        err.write(f"eval: held-out verdict {verdict.verdict}\n")
        if verdict.not_evaluable:
            err.write(f"  not evaluable: {', '.join(verdict.not_evaluable)}\n")
        for check in verdict.checks:
            if not check.passed:
                value = "n/a" if check.value is None else f"{check.value:.3f}"
                err.write(
                    f"  {check.name}: value {value}, threshold {check.threshold:.3f}, "
                    f"n {check.num}/{check.den} ({check.reason})\n"
                )
        return EXIT_GATE_FAILED if verdict.verdict == "FAIL" else EXIT_INCONCLUSIVE

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
