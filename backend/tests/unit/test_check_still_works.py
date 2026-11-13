"""Unit tests for scripts/check_still_works.py (pure logic only; no Docker)."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
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
        "3 checked: pass=2, pass_install_only=0, fail_install=0, fail_import=0, timeout=1"
    )


def test_classify_install_only() -> None:
    out = f"{csw.IMPORT_MARKER}\n{csw.INSTALL_ONLY_MARKER}: no entry"
    assert csw.classify(0, out, False) == "pass_install_only"
    assert csw.classify(1, out, False) == "fail_import"
    assert csw.classify(None, out, True) == "timeout"


def test_refinements_applied() -> None:
    line = f"{csw.REFINEMENT_PREFIX}install_only: no entry"
    out = f"x\n{line}\n{line}"
    assert csw.refinements_applied("npm", out) == ["legacy-peer-deps", "install_only: no entry"]
    assert csw.refinements_applied("npm", "plain") == ["legacy-peer-deps"]
    qt = f"{csw.REFINEMENT_PREFIX}qt_toolkit:PyQt5"
    assert csw.refinements_applied("pypi", qt) == ["qt_toolkit:PyQt5"]
    assert csw.refinements_applied("pypi", "plain") == []
    assert csw.format_refinements([]) == "refinements: none"
    assert csw.format_refinements(["a", "b"]) == "refinements: a, b"


@pytest.mark.parametrize(
    ("missing", "expected"),
    [
        (["PyQt5"], "PyQt5"),
        (["PySide6", "PySide6"], "PySide6"),
        (["PyQt6"], "PyQt6"),
        (["PySide2"], "PySide2"),
        ([], None),
        (["numpy"], None),
        (["PyQt5", "numpy"], None),
        (["PyQt5", "PyQt6"], None),
        (["pyqt5"], None),
        ([""], None),
    ],
)
def test_qt_toolkit_to_install(missing: list[str], expected: str | None) -> None:
    assert csw.qt_toolkit_to_install(missing) == expected


def test_container_scripts_carry_the_refinements() -> None:
    assert "--legacy-peer-deps" in csw.NODE_SHELL
    assert "qt_toolkit_to_install" in csw.PY_CODE
    for lib in ("libgl1", "libglib2.0-0", "libxkbcommon0", "libdbus-1-3", "libfontconfig1"):
        assert lib in csw.PY_CODE
    assert "--no-install-recommends" in csw.PY_CODE
    assert "QT_QPA_PLATFORM" in csw.PY_CODE
    assert "offscreen" in csw.PY_CODE


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@pytest.mark.parametrize(
    ("pkg", "files", "expected"),
    [
        ({"main": "lib/index.js"}, ["lib/index.js"], True),
        ({"main": "lib/index"}, ["lib/index.js"], True),
        ({"main": "lib"}, ["lib/index.js"], True),
        ({"main": "data.json"}, ["data.json"], True),
        ({}, ["index.js"], True),
        ({}, [], False),
        ({"main": "src/index.ts"}, ["src/index.ts"], False),
        ({"main": "missing.js"}, [], False),
        ({"exports": {".": {"types": "./a.d.ts", "import": "./a.mjs"}}}, ["a.mjs"], True),
        ({"exports": {".": "./a.ts"}}, ["a.ts"], False),
        ({"exports": {"./sub": "./a.js"}}, ["a.js"], False),
        ({"exports": "./a.cjs"}, ["a.cjs"], True),
    ],
)
def test_node_entry_check(
    tmp_path: Path, pkg: dict[str, object], files: list[str], expected: bool
) -> None:
    for rel in files:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("")
    script = csw.NODE_ENTRY_JS + (
        f"console.log(hasJsEntry({json.dumps(str(tmp_path))}, {json.dumps(pkg)}));"
    )
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    assert proc.stdout.strip() == str(expected).lower()


def test_build_command_is_isolated() -> None:
    cmd = csw.build_command("pypi", "torf", "4.3.1", "c1")
    assert cmd[:3] == ["docker", "run", "--rm"]
    assert "python:3.12-slim" in cmd
    assert not {"-v", "--volume", "--mount", "-e", "--env", "--env-file"} & set(cmd)
    assert cmd[cmd.index("sh", cmd.index("sh") + 1) + 1 :][:2] == ["torf", "4.3.1"]
    assert "node:22-slim" in csw.build_command("npm", "ms", "2.1.3", "c2")
