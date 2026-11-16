"""Command-line parsing of ``python -m eval``: --model, --dataset, --insample (design 11.1)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from eval.heldout.datasets import DATASETS
from eval.models import MODELS
from eval.run import USAGE, _parse, _UsageError, run


def _run(argv: list[str], data: Path) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = run(argv, out=out, err=err, data_dir=data)
    return code, out.getvalue(), err.getvalue()


def test_registries_hold_the_expected_entries() -> None:
    assert set(MODELS) == {"v1"}
    assert MODELS["v1"].manifest_file is None
    assert MODELS["v1"].digest_file == "FROZEN_WEIGHTS.sha256"
    assert set(DATASETS) == {"v1", "heldout"}
    assert DATASETS["v1"].default_out == "results.json"
    assert DATASETS["v1"].write_mode == "replace"
    assert DATASETS["heldout"].default_out == "heldout/results.{model}.json"
    assert DATASETS["heldout"].write_mode == "exclusive"
    for dataset in DATASETS.values():
        for name in (dataset.labels, dataset.fixtures, dataset.gate, dataset.default_out):
            assert not Path(name).is_absolute()


def test_defaults_are_v1_and_v1() -> None:
    args = _parse([])
    assert (args.model.version, args.dataset.name, args.out, args.insample) == (
        "v1",
        "v1",
        None,
        False,
    )


def test_all_options_parse() -> None:
    args = _parse(["--model", "v1", "--dataset", "heldout", "--out", "x.json"])
    assert (args.dataset.name, args.out) == ("heldout", Path("x.json"))


@pytest.mark.parametrize(
    "argv",
    [
        ["--model", "v2"],
        ["--model", "v2", "--insample"],
        ["--model", "v3"],
        ["--dataset", "nope"],
        ["--insample"],
        ["--dataset", "heldout", "--insample"],
        ["--bogus"],
    ],
)
def test_usage_errors_exit_2_with_usage_text(argv: list[str], tmp_path: Path) -> None:
    code, out, err = _run(argv, tmp_path)
    assert (code, out) == (2, "")
    assert err.endswith(USAGE)
    assert list(tmp_path.iterdir()) == []


def test_v2_is_unknown_until_registered() -> None:
    with pytest.raises(_UsageError, match="unknown --model 'v2'"):
        _parse(["--model", "v2"])


def test_heldout_reads_its_own_labels(tmp_path: Path) -> None:
    code, _, err = _run(["--dataset", "heldout"], tmp_path)
    assert code == 3
    assert "heldout" in err
    assert not (tmp_path / "results.json").exists()
