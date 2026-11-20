"""Deterministic zip writing, shared by the two build scripts (SB-CI-1)."""

from __future__ import annotations

import hashlib
import zipfile
from collections.abc import Mapping
from pathlib import Path

FIXED_TIME = (2026, 1, 1, 0, 0, 0)
FILE_MODE = 0o100644 << 16
EXEC_MODE = 0o100755 << 16


def write_zip(entries: Mapping[str, tuple[bytes, int]], out: Path) -> str:
    """Write ``entries`` (name to (content, mode bits)) sorted, with fixed times; return the SHA-256."""
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(entries):
            content, mode = entries[name]
            info = zipfile.ZipInfo(name, FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = mode
            info.create_system = 3
            archive.writestr(info, content, compresslevel=9)
    return hashlib.sha256(out.read_bytes()).hexdigest()
