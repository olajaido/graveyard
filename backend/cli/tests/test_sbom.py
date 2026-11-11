"""Tests for ``cli.sbom`` (T5.4; CLI-SBOM-1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cli import sbom
from cli.errors import CliError

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sboms" / "all.cdx.json"


def test_valid_file_returns_the_document() -> None:
    document = sbom.load_sbom(FIXTURE)
    assert document["specVersion"] == "1.7"


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(CliError):
        sbom.load_sbom(tmp_path / "nope.json")


def test_directory(tmp_path: Path) -> None:
    with pytest.raises(CliError):
        sbom.load_sbom(tmp_path)


def test_file_above_the_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "big.json"
    path.write_text("{" + " " * 2048 + "}", encoding="utf-8")
    monkeypatch.setattr(sbom, "MAX_SBOM_BYTES", 1024)
    with pytest.raises(CliError) as caught:
        sbom.load_sbom(path)
    assert "32 MiB" in caught.value.message


@pytest.mark.parametrize(
    "content",
    [b"not json", b"", b"\xff\xfe\x00", b"[1, 2, 3]", b'"text"', b"null", b"12"],
)
def test_not_a_json_object(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / "x.json"
    path.write_bytes(content)
    with pytest.raises(CliError):
        sbom.load_sbom(path)


def test_deeply_nested_array(tmp_path: Path) -> None:
    path = tmp_path / "deep.json"
    path.write_text("[" * 10_000 + "]" * 10_000, encoding="utf-8")
    with pytest.raises(CliError):
        sbom.load_sbom(path)


def test_messages_do_not_echo_the_path(tmp_path: Path) -> None:
    path = tmp_path / "secret-name.json"
    path.write_text("nope", encoding="utf-8")
    with pytest.raises(CliError) as caught:
        sbom.load_sbom(path)
    assert "secret-name" not in caught.value.message
