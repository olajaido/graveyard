"""Offline tests for scripts/heldout_batch.py `next` and `status` (T5.13; design 10.1).

The registry is a fake; every file lives under `tmp_path`. No network.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from eval.tests.support import csv_text, valid_row

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "heldout_batch.py"
TODAY = date(2026, 11, 20)
LOG_HEADER = "batch_id\tstratum\tecosystem\torder_range\ttriples\tsha256\trelease_date\n"

LATEST = {
    ("npm", "zeta"): "3.0.0",
    ("npm", "alpha"): "1.2.0",
    ("pypi", "mid"): "0.4.1",
    ("npm", "fone"): "5.0.0",
    ("pypi", "ftwo"): "2.0.0",
    ("npm", "fthree"): "1.0.0",
}


@pytest.fixture(scope="module")
def script() -> Iterator[Any]:
    spec = importlib.util.spec_from_file_location("heldout_batch", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["heldout_batch"] = module
    spec.loader.exec_module(module)
    try:
        yield module
    finally:
        sys.modules.pop("heldout_batch", None)


def fake_registry(script: Any, calls: list[str] | None = None) -> Any:
    def fetch(url: str) -> tuple[int, bytes]:
        if calls is not None:
            calls.append(url)
        for (eco, name), version in LATEST.items():
            if url == script.registry_url(eco, name):
                if eco == "npm":
                    return 200, f'{{"version": "{version}"}}'.encode()
                return 200, f'{{"info": {{"version": "{version}"}}}}'.encode()
        return 404, b""

    return fetch


def heldout(tmp_path: Path) -> Path:
    root = tmp_path / "eval" / "heldout"
    draw = root / "draw"
    draw.mkdir(parents=True)
    (draw / "q-candidates.tsv").write_text(
        "ecosystem\torder\tname\tlatest_version\treleased_at\tdraw_key\n"
        "npm\t1\tzeta\t0\t2024-01-01\tk1\n"
        "npm\t2\talpha\t0\t2024-01-01\tk2\n"
        "pypi\t1\tmid\t0\t2024-01-01\tk3\n",
        encoding="utf-8",
    )
    (draw / "f-pool.tsv").write_text(
        "order\tecosystem\tname\trepo\towner\tquery_id\tdraw_key\n"
        "1\tnpm\tfone\tgithub.com/o/a\to\tq1\tk4\n"
        "2\tpypi\tftwo\tgithub.com/o/b\to\tq1\tk5\n"
        "3\tnpm\tfthree\tgithub.com/p/c\tp\tq1\tk6\n",
        encoding="utf-8",
    )
    staging = tmp_path / "eval" / "staging"
    staging.mkdir()
    (staging / "coroner_rows.csv").write_text(csv_text([]), encoding="utf-8")
    return root


def run(script: Any, root: Path, *args: str, calls: list[str] | None = None) -> int:
    return int(
        script.main(
            [*args, "--heldout-dir", str(root)],
            fetch=fake_registry(script, calls),
            today=TODAY,
        )
    )


def label(eco: str, name: str, *, reviewed: bool = True, kind: str = "alive") -> dict[str, str]:
    evidence = "feature_complete_readme" if kind == "finished-healthy" else "release_notes"
    return valid_row(
        ecosystem=eco,
        name=name,
        version=LATEST[(eco, name)],
        label=kind,
        evidence_kind=evidence,
        evidence_url=f"https://example.org/{name}",
        evidence_quote=f"evidence for {name}",
        reviewed="true" if reviewed else "false",
    )


def write_labels(root: Path, rows: list[dict[str, str]]) -> None:
    (root / "labelled_packages.csv").write_text(csv_text(rows), encoding="utf-8", newline="")


def test_first_q_release_prints_sorted_triples_and_logs_the_hash(
    script: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = heldout(tmp_path)
    assert run(script, root, "next") == 0
    out = capsys.readouterr().out
    assert out == "npm,alpha,1.2.0\npypi,mid,0.4.1\nnpm,zeta,3.0.0\n"
    for forbidden in ("Q", "F", "rank", "order", "source", "stratum", "k1"):
        assert forbidden not in out
    log = (root / "draw" / "batch-log.tsv").read_text(encoding="utf-8")
    lines = log.splitlines()
    assert lines[0] == LOG_HEADER.strip()
    digest = hashlib.sha256(out.encode()).hexdigest()
    assert lines[1:] == [
        f"Q1\tQ\tnpm\t1-2\tnpm,alpha,1.2.0;npm,zeta,3.0.0\t{digest}\t2026-11-20",
        f"Q1\tQ\tpypi\t1-1\tpypi,mid,0.4.1\t{digest}\t2026-11-20",
    ]


def test_blocked_release_prints_the_reason_and_changes_nothing(
    script: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = heldout(tmp_path)
    assert run(script, root, "next") == 0
    capsys.readouterr()
    log_before = (root / "draw" / "batch-log.tsv").read_text(encoding="utf-8")
    calls: list[str] = []
    assert run(script, root, "next", calls=calls) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "blocked: rule 1" in captured.err
    assert calls == []
    assert (root / "draw" / "batch-log.tsv").read_text(encoding="utf-8") == log_before


def test_unreviewed_row_and_full_staging_block_with_their_rules(
    script: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = heldout(tmp_path)
    assert run(script, root, "next") == 0
    capsys.readouterr()
    write_labels(
        root,
        [label("npm", "zeta"), label("npm", "alpha"), label("pypi", "mid", reviewed=False)],
    )
    assert run(script, root, "next") == 1
    assert "rule 2: pypi/mid is not reviewed" in capsys.readouterr().err
    write_labels(root, [label("npm", n) for n in ("zeta", "alpha")] + [label("pypi", "mid")])
    staging = tmp_path / "eval" / "staging" / "coroner_rows.csv"
    staging.write_text(csv_text([label("npm", "fone")]), encoding="utf-8", newline="")
    assert run(script, root, "next") == 1
    assert "rule 3" in capsys.readouterr().err


def test_fetch_failure_writes_and_prints_nothing(
    script: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = heldout(tmp_path)
    del_key = ("npm", "alpha")
    saved = LATEST.pop(del_key)
    try:
        assert run(script, root, "next") == 2
    finally:
        LATEST[del_key] = saved
    captured = capsys.readouterr()
    assert captured.out == "" and "npm/alpha" in captured.err
    assert not (root / "draw" / "batch-log.tsv").exists()


def test_f_batch_follows_q_with_a_removal_and_pool_order(
    script: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = heldout(tmp_path)
    assert run(script, root, "next") == 0
    capsys.readouterr()
    write_labels(root, [label("npm", "zeta"), label("npm", "alpha")])
    review = root / "review"
    review.mkdir()
    (review / "decisions.tsv").write_text(
        "ecosystem\tname\taction\treason\npypi\tmid\tremove\tfailed evidence check\n",
        encoding="utf-8",
    )
    assert run(script, root, "next") == 0
    out = capsys.readouterr().out
    assert out == "npm,fone,5.0.0\nnpm,fthree,1.0.0\npypi,ftwo,2.0.0\n"
    lines = (root / "draw" / "batch-log.tsv").read_text(encoding="utf-8").splitlines()
    assert [ln.split("\t")[:4] for ln in lines[3:]] == [
        ["F1", "F", "npm", "1-3"],
        ["F1", "F", "pypi", "2-2"],
    ]


def test_status_counts_floors_and_stop_rule(
    script: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = heldout(tmp_path)
    (root / "gate.yaml").write_text(
        "min_dead_precision: 0.90\nmax_finished_healthy_fpr: 0.10\n"
        "min_reviewed_dead: 25\nmin_reviewed_finished_healthy: 20\n",
        encoding="utf-8",
    )
    assert run(script, root, "next") == 0
    assert run(script, root, "next", "--stratum", "F") == 1  # blocked: nothing labelled
    capsys.readouterr()
    write_labels(
        root,
        [
            label("npm", "zeta"),
            label("npm", "alpha"),
            label("pypi", "mid", kind="finished-healthy"),
        ],
    )
    review = root / "review"
    review.mkdir()
    (review / "still_works.tsv").write_text(
        "ecosystem\tname\tversion\tresult\truntime\tdetail\n"
        "pypi\tmid\t0.4.1\tpass\tpython:3.12-slim\tok\n",
        encoding="utf-8",
    )
    assert run(script, root, "status") == 0
    out = capsys.readouterr().out
    assert "released: 3 (Q 3, F 0)" in out
    assert "labelled: 3 rows (Q 3, F 0)" in out
    assert "reviewed: 3 of 3 rows" in out
    assert "effective F rows: 0/20; F released 0/120; pool remaining 3" in out
    assert "F stopping rule: not fired" in out
    assert "floor reviewed dead rows: 0/25" in out
    assert "floor effective finished-healthy rows (pooled): 1/20" in out
    assert "staging empty: yes" in out
