"""Unit tests for scripts/check_still_works.py (pure logic only; no Docker)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "check_still_works.py"
_spec = importlib.util.spec_from_file_location("check_still_works", _SCRIPT)
assert _spec and _spec.loader
csw = importlib.util.module_from_spec(_spec)
sys.modules["check_still_works"] = csw
_spec.loader.exec_module(csw)


def _row(eco: str, name: str, version: str, label: str) -> dict[str, str]:
    return {"ecosystem": eco, "name": name, "version": version, "label": label}


def test_filter_keeps_only_finished_healthy() -> None:
    rows = [
        _row("pypi", "torf", "4.3.1", "finished-healthy"),
        _row("npm", "ms", "2.1.3", "alive"),
        _row("npm", "graphql-list-fields", "2.0.4", "finished-healthy"),
        _row("pypi", "x", "1", "dead"),
    ]
    assert csw.filter_rows(rows) == [
        ("pypi", "torf", "4.3.1"),
        ("npm", "graphql-list-fields", "2.0.4"),
    ]


@pytest.mark.parametrize(
    "row",
    [
        _row("cargo", "a", "1", "finished-healthy"),
        _row("pypi", "a; rm -rf /", "1", "finished-healthy"),
        _row("pypi", "a", "1 && id", "finished-healthy"),
    ],
)
def test_filter_rejects_unsafe_rows(row: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        csw.filter_rows([row])


def test_filter_ignores_unsafe_rows_with_other_labels() -> None:
    assert csw.filter_rows([_row("cargo", "a", "1", "dead")]) == []


def test_import_names_from_top_level() -> None:
    assert csw.derive_import_names("zeta\nalpha\n\n", "x/y.py,,") == ["alpha", "zeta"]


def test_import_names_from_record() -> None:
    record = "\n".join(
        [
            "torf/__init__.py,sha256=a,1",
            "torf/_utils.py,sha256=b,2",
            "torf/__pycache__/x.cpython-312.pyc,,",
            "single.py,sha256=c,3",
            "native.cpython-312-x86_64-linux-gnu.so,sha256=d,4",
            "torf-4.3.1.dist-info/METADATA,sha256=e,5",
            "torf-4.3.1.data/scripts/torf,sha256=f,6",
            "../../bin/torf,,",
            "README.md,sha256=g,7",
            "docs/readme.txt,,",
        ]
    )
    assert csw.derive_import_names(None, record) == ["native", "single", "torf"]


def test_import_names_skips_non_identifiers_and_empty() -> None:
    assert csw.derive_import_names("foo-bar\n", "my-pkg/a.py,,") == []
    assert csw.derive_import_names("", "") == []


def test_import_names_top_level_with_slash_falls_back_to_record() -> None:
    assert csw.derive_import_names("a/b\n", "pkg/m.py,,") == ["pkg"]


def test_derive_source_is_self_contained() -> None:
    ns: dict[str, object] = {}
    exec(csw.PY_CODE.split("import importlib")[0], ns)  # noqa: S102
    assert callable(ns["derive_import_names"])


@pytest.mark.parametrize(
    ("code", "output", "timed_out", "expected"),
    [
        (None, "whatever", True, "timeout"),
        (1, "ERROR: no matching distribution", False, "fail_install"),
        (0, "no marker", False, "fail_install"),
        (0, f"ok\n{csw.IMPORT_MARKER}\nimported torf", False, "pass"),
        (1, f"{csw.IMPORT_MARKER}\nFAILED torf ImportError", False, "fail_import"),
    ],
)
def test_classify(code: int | None, output: str, timed_out: bool, expected: str) -> None:
    assert csw.classify(code, output, timed_out) == expected


def test_tail_lines_and_detail() -> None:
    text = "\n".join(f"line{i}" for i in range(50)) + "\n\n"
    tail = csw.tail_lines(text)
    assert tail.splitlines() == [f"line{i}" for i in range(30, 50)]
    detail = csw.format_detail("a\tb\nc")
    assert "\n" not in detail and "\t" not in detail
    assert detail == "a b | c"


def test_summarise() -> None:
    assert csw.summarise(["pass", "pass", "timeout"]) == (
        "3 checked: pass=2, fail_install=0, fail_import=0, timeout=1"
    )


def test_build_command_is_isolated() -> None:
    cmd = csw.build_command("pypi", "torf", "4.3.1", "c1")
    assert cmd[:3] == ["docker", "run", "--rm"]
    assert "python:3.12-slim" in cmd
    assert not {"-v", "--volume", "--mount", "-e", "--env", "--env-file"} & set(cmd)
    assert cmd[cmd.index("sh", cmd.index("sh") + 1) + 1 :][:2] == ["torf", "4.3.1"]
    assert "node:22-slim" in csw.build_command("npm", "ms", "2.1.3", "c2")
