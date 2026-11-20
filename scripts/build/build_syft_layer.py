#!/usr/bin/env python3
"""Build ``syft-layer.zip``: the pinned Syft arm64 binary at ``bin/syft`` (SB-SBOM-3).

The tarball is downloaded at build time and checked against the SHA-256 in ``syft-pin.json``
before anything is read from it. Only the member named ``syft`` is taken; the archive is never
extracted. Usage: ``build_syft_layer.py OUT.zip`` (prints the SHA-256 of the zip).
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
import tarfile
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from zipping import EXEC_MODE, write_zip  # noqa: E402

PIN = Path(__file__).resolve().parent / "syft-pin.json"
MAX_TARBALL_BYTES = 200 * 1024 * 1024
MAX_BINARY_BYTES = 400 * 1024 * 1024


class PinMismatch(Exception):
    pass


def load_pin(path: Path = PIN) -> dict[str, str]:
    pin = json.loads(path.read_text())
    host = urlparse(pin["url"])
    if host.scheme != "https" or host.hostname != "github.com":
        raise ValueError("the Syft URL must be https://github.com/...")
    return {k: str(v) for k, v in pin.items()}


def build_layer(tarball: bytes, expected_sha256: str, out: Path) -> str:
    """Verify ``tarball`` and write the layer zip. Raises ``PinMismatch`` and writes nothing."""
    actual = hashlib.sha256(tarball).hexdigest()
    if actual != expected_sha256:
        raise PinMismatch(f"Syft tarball SHA-256 is {actual}, the pin says {expected_sha256}")
    with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as archive:
        member = archive.getmember("syft")
        if not member.isfile() or member.size > MAX_BINARY_BYTES:
            raise ValueError("unexpected 'syft' member")
        handle = archive.extractfile(member)
        if handle is None:
            raise ValueError("unexpected 'syft' member")
        binary = handle.read()
    return write_zip({"bin/syft": (binary, EXEC_MODE)}, out)


def download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310 (https, host checked)
        data: bytes = response.read(MAX_TARBALL_BYTES + 1)
    if len(data) > MAX_TARBALL_BYTES:
        raise ValueError("the Syft download is larger than expected")
    return data


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: build_syft_layer.py OUT.zip", file=sys.stderr)
        return 2
    pin = load_pin()
    try:
        print(build_layer(download(pin["url"]), pin["sha256"], Path(argv[1])))
    except PinMismatch as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
