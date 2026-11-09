"""Unit tests for ``parse_requirements_txt`` (DG-SCP-0, DG-SCP-8, DG-EX-22).

Expected keys come from ``core.graph.keys.pypi_key``. The hand-written fixture
(``requirements.txt``) has a leading BOM and CRLF line endings; it is read as
bytes and decoded as UTF-8 so the BOM is preserved. Fixtures resolve via
``Path(__file__).parent``.
"""

from pathlib import Path

from core.graph.keys import pypi_key
from core.graph.scopes_requirements import parse_requirements_txt

FIXTURES = Path(__file__).parent / "fixtures"


def _skipped_subjects(text: str) -> list[str]:
    result = parse_requirements_txt(text)
    assert all(w.code == "REQUIREMENT_SKIPPED" for w in result.warnings)
    return [s for w in result.warnings for s in w.subjects]


def test_fixture_dg_ex_22() -> None:
    """DG-EX-22, DG-SCP-8: BOM, CRLF, pins, continuations, silent and warned skips."""
    raw = (FIXTURES / "requirements.txt").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf") and b"\r\n" in raw
    result = parse_requirements_txt(raw.decode("utf-8"))

    expected = {
        pypi_key("requests", "2.31.0"),
        pypi_key("flask", "3.0.0"),
        pypi_key("numpy", "1.26.4"),
        pypi_key("urllib3", "2.2.1"),
        pypi_key("six", "1.16.0"),
        pypi_key("certifi", "2024.2.2"),
    }
    assert set(result.package_scopes) == expected
    assert set(result.direct_scopes) == expected
    assert set(result.package_scopes.values()) == {"runtime"}
    assert set(result.direct_scopes.values()) == {"runtime"}

    assert [w.code for w in result.warnings] == ["REQUIREMENT_SKIPPED"] * 4
    assert all(w.service is None for w in result.warnings)
    # Warnings are emitted in a deterministic order, not file order: compare as a set.
    assert sorted(w.subjects for w in result.warnings) == sorted(
        [
            ("git+https://github.com/psf/requests.git@main#egg=requests",),
            ("requests>=2",),
            ("flask==1.*",),
            ("./local",),
        ]
    )


def test_triple_equals_is_pinned() -> None:
    """DG-SCP-8: ``name === version`` is pinned."""
    result = parse_requirements_txt("six===1.16.0\n")
    assert result.package_scopes == {pypi_key("six", "1.16.0"): "runtime"}
    assert result.warnings == ()


def test_spaces_around_operator() -> None:
    """DG-SCP-8: spaces around ``==`` are accepted."""
    result = parse_requirements_txt("numpy   ==   1.26.4\n")
    assert result.direct_scopes == {pypi_key("numpy", "1.26.4"): "runtime"}
    assert result.warnings == ()


def test_extras_marker_hashes_and_comment_on_one_line() -> None:
    """DG-SCP-8: extras, marker, hashes and trailing comment together."""
    line = (
        'Foo_Bar[a,b] == 2.0 ; python_version < "3.9" '
        "--hash=sha256:abc --hash=sha256:def  # why we pin"
    )
    result = parse_requirements_txt(line)
    assert result.package_scopes == {pypi_key("Foo_Bar", "2.0"): "runtime"}
    assert result.direct_scopes == result.package_scopes
    assert result.warnings == ()


def test_wildcard_version_skipped_with_warning() -> None:
    """DG-SCP-8: ``flask==1.*`` is skipped with ``REQUIREMENT_SKIPPED``."""
    result = parse_requirements_txt("flask==1.*\n")
    assert result.package_scopes == {}
    assert result.direct_scopes == {}
    assert _skipped_subjects("flask==1.*\n") == ["flask==1.*"]


def test_include_option_skipped_silently() -> None:
    """DG-SCP-8: ``-r other.txt`` (and other options) produce no warning."""
    result = parse_requirements_txt("-r other.txt\n-c c.txt\n-e .\n--index-url https://x.example\n")
    assert result.package_scopes == {}
    assert result.direct_scopes == {}
    assert result.warnings == ()


def test_empty_text() -> None:
    """DG-SCP-8: empty (and blank-only) text yields empty maps and no warnings."""
    for text in ("", "\n\r\n  \n", "\ufeff"):
        result = parse_requirements_txt(text)
        assert result.package_scopes == {}
        assert result.direct_scopes == {}
        assert result.warnings == ()
