"""Checks that spike KP-S1 left the repository clean and its findings recorded.

Paths come from this file's location, never the working directory.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
HOOKS_DIR = REPO_ROOT / ".kiro" / "hooks"
SPIKES_MD = REPO_ROOT / "docs" / "SPIKES.md"

# Built from two parts so this file never contains the marker itself.
MARKER = "GRAVEYARD" + "_KP_S1"

OBSERVED_ROWS = (
    "COMMAND_FIELD",
    "CWD_FIELD",
    "tool_name",
    "stdin closed",
    "exit 2 blocks",
    "stderr reaches the model",
)


def _kp_s1_section() -> str:
    text = SPIKES_MD.read_text(encoding="utf-8")
    match = re.search(r"^##\s+KP-S1\b.*?(?=^##\s(?!#)|\Z)", text, re.DOTALL | re.MULTILINE)
    assert match is not None, "docs/SPIKES.md has no KP-S1 section"
    return match.group(0)


def _observed_table(section: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 2:
            rows[cells[0].strip("`")] = cells[1]
    return rows


def test_probe_hook_is_removed() -> None:
    assert not (HOOKS_DIR / "kp-s1-probe.json").exists()


def test_no_hook_file_contains_the_sentinel_marker() -> None:
    offenders = [
        p.name
        for p in HOOKS_DIR.rglob("*")
        if p.is_file() and MARKER in p.read_text(encoding="utf-8", errors="ignore")
    ]
    assert offenders == []


def test_spikes_md_records_observed_fields() -> None:
    rows = _observed_table(_kp_s1_section())
    for name in OBSERVED_ROWS:
        assert name in rows, f"missing Observed-fields row: {name}"
    assert rows["COMMAND_FIELD"].strip("` ") != ""
    assert rows["CWD_FIELD"].strip("` ") != ""
