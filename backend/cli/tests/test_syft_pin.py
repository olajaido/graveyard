"""The Syft pin is stated in code and in the spike notes (T5.5; CLI-TEST-8)."""

from __future__ import annotations

from pathlib import Path

from cli.syft import SYFT_VERSION

SPIKES = Path(__file__).resolve().parents[3] / "docs" / "SPIKES.md"


def test_pin_value() -> None:
    assert SYFT_VERSION == "1.56.0"


def test_spikes_names_the_same_version() -> None:
    assert f"Syft v{SYFT_VERSION}" in SPIKES.read_text(encoding="utf-8")
