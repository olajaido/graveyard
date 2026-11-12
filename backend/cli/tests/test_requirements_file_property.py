"""Property tests for ``cli.requirements_file.load_requirements`` (KPW-REQ-6, KPW-TEST-11).

Totality: no file content and no path text makes it raise, and every target it returns is a
``Pinned`` PyPI target whose name and version ``core.purl`` accepts.

Profiles come from ``conftest.py`` via ``HYPOTHESIS_PROFILE``; no ``max_examples`` is set here.
A fresh ``TemporaryDirectory`` is used per example instead of the function-scoped ``tmp_path``.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cli.requirements_file import MAX_NAME_CHARS, RequirementLoad, load_requirements
from core.install import Pinned, RequirementRef, Target

pytestmark = pytest.mark.property

_REASONS = {"ok", "outside", "missing", "not-file", "too-large", "unreadable", "unsafe-path"}

_NAME = st.text(alphabet="abcXYZ019._-[]", min_size=0, max_size=12)
_VERSION = st.text(alphabet="0123456789.abrc!+*-_ ", min_size=0, max_size=10)
_PIN_LINE = st.builds("{}=={}".format, _NAME, _VERSION)
_NOISE_LINE = st.one_of(
    st.text(max_size=40),
    st.sampled_from(
        ["-r other.txt", "-c c.txt", "--requirement=x", "# c", "-e .", "git+https://x/y", ""]
    ),
    st.builds("{}>={}".format, _NAME, _VERSION),
    st.builds("{} ; python_version<'3.9'".format, _PIN_LINE),
    st.builds("{} \\".format, _PIN_LINE),
)
_LINES = st.lists(st.one_of(_PIN_LINE, _PIN_LINE, _NOISE_LINE), max_size=30)
_SEPARATOR = st.sampled_from(["\n", "\r\n", "\r"])

_TEXT_CONTENT = st.one_of(
    st.text(max_size=400),
    st.builds(lambda lines, sep: sep.join(lines), _LINES, _SEPARATOR),
)
_CONTENT = st.one_of(
    st.binary(max_size=400),
    _TEXT_CONTENT.map(lambda s: s.encode("utf-8", errors="replace")),
)

_FILE_NAME = "requirements.txt"
_PATH_TEXT = st.one_of(
    st.text(max_size=60),
    st.sampled_from(
        [_FILE_NAME, "./" + _FILE_NAME, "sub/../" + _FILE_NAME, "../" + _FILE_NAME, "/etc/passwd"]
    ),
    st.lists(
        st.sampled_from(["", ".", "..", "a", "sub", _FILE_NAME, "~", "$HOME", "*", "x:y", "\\"]),
        max_size=6,
    ).map("/".join),
)


def _check(load: RequirementLoad) -> None:
    assert isinstance(load, RequirementLoad)
    assert load.reason in _REASONS
    assert load.not_checked >= 0
    assert len(load.name) <= MAX_NAME_CHARS
    if load.reason != "ok":
        assert load.targets == ()
    for target in load.targets:
        assert isinstance(target, Target)
        assert target.ecosystem == "pypi"
        assert isinstance(target.spec, Pinned)
        assert target.spec.version
        target.purl_text(target.spec.version)  # must not raise


@given(content=_CONTENT)
def test_arbitrary_file_content(content: bytes) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        (base / _FILE_NAME).write_bytes(content)
        _check(load_requirements(RequirementRef(_FILE_NAME), base))


@given(lines=_LINES, sep=_SEPARATOR)
def test_pinned_heavy_content(lines: list[str], sep: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        (base / _FILE_NAME).write_text(sep.join(lines), encoding="utf-8", newline="")
        load = load_requirements(RequirementRef(_FILE_NAME), base)
        _check(load)
        assert load.reason == "ok"


@given(path_text=_PATH_TEXT, content=st.binary(max_size=100))
def test_arbitrary_path_text(path_text: str, content: bytes) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "base"
        base.mkdir()
        (base / _FILE_NAME).write_bytes(content)
        (base / "sub").mkdir()
        (base / "sub" / _FILE_NAME).write_bytes(content)
        _check(load_requirements(RequirementRef(path_text), base))
