# /// script
# requires-python = "==3.12.*"
# dependencies = [
#   "httpx==0.28.1",
# ]
# ///
"""Pin the held-out population snapshots (design 8.3; MV2-POP-2, MV2-POP-3). MAINTAINER-RUN ONLY.

Usage:
    uv run scripts/heldout_pin.py [--out-dir PATH]      # download, check, write
    uv run scripts/heldout_pin.py --verify [--out-dir PATH]   # re-hash committed files only

Download mode:
    * PyPI: resolves the latest commit of ``hugovk/top-pypi-packages`` that touches
      ``top-pypi-packages.min.json`` (api.github.com, unauthenticated), downloads the
      commit-pinned raw URL, keeps the first 5,000 rows.
    * npm: reads ``registry.npmjs.org/npm-high-impact/latest``, downloads the tarball from the
      same host, checks ``dist.integrity`` (sha512), reads the single member
      ``package/lib/top.js`` in memory with ``tarfile``. Nothing is extracted, installed,
      imported or executed.
    * Everything is held in memory and checked first. Files are written only when every check
      passed, ``pins.json`` last. An existing ``pins.json`` is never overwritten.

``--verify`` downloads nothing: it re-hashes the files in the snapshot directory against
``pins.json``.

Security:
    * Hosts allow-listed (https only); redirects are never followed; every response is
      size-capped while streaming; strict JSON only (see ``eval.heldout.pins``).
    * ``GITHUB_TOKEN`` is never read. Run by hand only: no test, hook or agent runs this
      script against the network.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import io
import json
import os
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from eval.heldout.pins import (  # noqa: E402
    MAX_BYTES,
    PinError,
    parse_hugovk,
    parse_npm_top_js,
    sha256_hex,
    verify_pins,
)

DEFAULT_OUT_DIR = REPO_ROOT / "eval" / "heldout" / "snapshot"

ALLOWED_HOSTS = frozenset({"api.github.com", "raw.githubusercontent.com", "registry.npmjs.org"})
TARBALL_MAX_BYTES = 20 * 1024 * 1024
JSON_MAX_BYTES = MAX_BYTES
MAX_TAR_MEMBERS = 1000

PYPI_REPO = "hugovk/top-pypi-packages"
PYPI_FILE = "top-pypi-packages.min.json"
PYPI_TOP_N = 5000
PYPI_SNAPSHOT = "pypi-top-5000.json"
NPM_PACKAGE = "npm-high-impact"
NPM_MEMBER = "package/lib/top.js"
NPM_SNAPSHOT = "npm-high-impact.json"
PINS_FILE = "pins.json"


# --------------------------------------------------------------------------- #
# Guarded HTTP
# --------------------------------------------------------------------------- #
def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def get_bytes(client: httpx.Client, url: str, max_bytes: int) -> bytes:
    """GET `url` from an allow-listed https host; no redirects; abort past `max_bytes`."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS or parsed.port:
        raise PinError(f"refusing to fetch {url}: not an allow-listed https host")
    chunks: list[bytes] = []
    total = 0
    try:
        with client.stream("GET", url, follow_redirects=False) as resp:
            if 300 <= resp.status_code < 400:
                raise PinError(f"HTTP {resp.status_code} redirect from {url}; not followed")
            if resp.status_code != 200:
                raise PinError(f"HTTP {resp.status_code} from {url}")
            for chunk in resp.iter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise PinError(f"response from {url} is over the {max_bytes} byte cap")
                chunks.append(chunk)
    except httpx.HTTPError as exc:
        raise PinError(f"{type(exc).__name__} requesting {url}") from exc
    return b"".join(chunks)


def get_json(client: httpx.Client, url: str) -> Any:
    data = get_bytes(client, url, JSON_MAX_BYTES)
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise PinError(f"invalid JSON from {url}") from exc


def canonical(doc: Any) -> bytes:
    return (json.dumps(doc, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


# --------------------------------------------------------------------------- #
# PyPI
# --------------------------------------------------------------------------- #
def pin_pypi(client: httpx.Client) -> tuple[bytes, dict[str, Any]]:
    commits_url = (
        f"https://api.github.com/repos/{PYPI_REPO}/commits?path={quote(PYPI_FILE)}&per_page=1"
    )
    commits = get_json(client, commits_url)
    sha = commits[0].get("sha") if isinstance(commits, list) and commits else None
    if not isinstance(sha, str) or len(sha) != 40 or set(sha) - set("0123456789abcdef"):
        raise PinError("commit lookup did not return a 40-hex commit sha")
    raw_url = f"https://raw.githubusercontent.com/{PYPI_REPO}/{sha}/{PYPI_FILE}"
    raw = get_bytes(client, raw_url, JSON_MAX_BYTES)
    rows = parse_hugovk(raw, PYPI_TOP_N)
    last_update = json.loads(raw.decode("utf-8")).get("last_update")
    if not isinstance(last_update, str):
        raise PinError("hugovk file has no string `last_update`")
    trimmed = canonical(
        {
            "last_update": last_update,
            "rows": [{"download_count": count, "project": name} for name, count in rows],
        }
    )
    entry = {
        "file": PYPI_SNAPSHOT,
        "url": raw_url,
        "source_file": PYPI_FILE,
        "commit_sha": sha,
        "last_update": last_update,
        "downloaded_sha256": sha256_hex(raw),
        "trimmed_sha256": sha256_hex(trimmed),
        "row_count": len(rows),
        "fetched_at": now_iso(),
    }
    return trimmed, entry


# --------------------------------------------------------------------------- #
# npm
# --------------------------------------------------------------------------- #
def check_integrity(data: bytes, integrity: str) -> None:
    """Check an SRI string `sha512-<base64>` against `data`."""
    algorithm, _, encoded = integrity.partition("-")
    if algorithm != "sha512":
        raise PinError("dist.integrity is not a sha512 value")
    try:
        expected = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise PinError("dist.integrity is not valid base64") from exc
    if hashlib.sha512(data).digest() != expected:
        raise PinError("tarball does not match dist.integrity")


def read_member(tarball: bytes, member_name: str) -> bytes:
    """Return the bytes of exactly one member; every other member is skipped unread."""
    try:
        with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as tar:
            found: tarfile.TarInfo | None = None
            for count, info in enumerate(tar, start=1):
                if count > MAX_TAR_MEMBERS:
                    raise PinError("tarball has too many members")
                if info.name == member_name:
                    found = info
                    break
            if found is None or not found.isfile():
                raise PinError(f"tarball has no regular file {member_name}")
            if found.size > MAX_BYTES:
                raise PinError(f"{member_name} is over the {MAX_BYTES} byte cap")
            handle = tar.extractfile(found)
            if handle is None:
                raise PinError(f"{member_name} cannot be read")
            return handle.read(MAX_BYTES + 1)
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise PinError(f"tarball is not a readable gzip tar: {type(exc).__name__}") from exc


def pin_npm(client: httpx.Client) -> tuple[bytes, dict[str, Any]]:
    latest_url = f"https://registry.npmjs.org/{NPM_PACKAGE}/latest"
    doc = get_json(client, latest_url)
    if not isinstance(doc, dict) or not isinstance(doc.get("dist"), dict):
        raise PinError("npm latest document has no `dist` object")
    version, dist = doc.get("version"), doc["dist"]
    integrity, tarball_url = dist.get("integrity"), dist.get("tarball")
    if not (
        isinstance(version, str) and isinstance(integrity, str) and isinstance(tarball_url, str)
    ):
        raise PinError("npm latest document lacks version, dist.integrity or dist.tarball")
    tarball = get_bytes(client, tarball_url, TARBALL_MAX_BYTES)
    check_integrity(tarball, integrity)
    member = read_member(tarball, NPM_MEMBER)
    names = parse_npm_top_js(member)
    trimmed = canonical(names)
    entry = {
        "file": NPM_SNAPSHOT,
        "url": tarball_url,
        "package": NPM_PACKAGE,
        "version": version,
        "member": NPM_MEMBER,
        "integrity": integrity,
        "downloaded_sha256": sha256_hex(tarball),
        "member_sha256": sha256_hex(member),
        "trimmed_sha256": sha256_hex(trimmed),
        "row_count": len(names),
        "fetched_at": now_iso(),
    }
    return trimmed, entry


# --------------------------------------------------------------------------- #
# Write and verify
# --------------------------------------------------------------------------- #
def write_all(out_dir: Path, files: dict[str, bytes]) -> None:
    """Write every file via a temp name and rename; `pins.json` must be last in `files`."""
    out_dir.mkdir(parents=True, exist_ok=True)
    temps: list[tuple[Path, Path]] = []
    try:
        for name, content in files.items():
            tmp = out_dir / f".{name}.tmp"
            tmp.write_bytes(content)
            temps.append((tmp, out_dir / name))
    except OSError:
        for tmp, _ in temps:
            tmp.unlink(missing_ok=True)
        raise
    for tmp, final in temps:
        os.replace(tmp, final)


def run_pin(client: httpx.Client, out_dir: Path) -> int:
    if (out_dir / PINS_FILE).exists():
        print(
            f"error: {out_dir / PINS_FILE} already exists; it is not overwritten", file=sys.stderr
        )
        return 1
    try:
        pypi_bytes, pypi_entry = pin_pypi(client)
        npm_bytes, npm_entry = pin_npm(client)
    except PinError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    pins = {"sources": {"pypi-top-5000": pypi_entry, "npm-high-impact": npm_entry}}
    files = {
        PYPI_SNAPSHOT: pypi_bytes,
        NPM_SNAPSHOT: npm_bytes,
        PINS_FILE: (json.dumps(pins, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    }
    write_all(out_dir, files)
    print(f"wrote {', '.join(files)} to {out_dir}")
    return 0


def run_verify(out_dir: Path) -> int:
    try:
        pins = json.loads((out_dir / PINS_FILE).read_bytes())
    except (OSError, ValueError) as exc:
        print(f"error: cannot read {PINS_FILE}: {type(exc).__name__}", file=sys.stderr)
        return 1
    files: dict[str, bytes] = {}
    sources = pins.get("sources") if isinstance(pins, dict) else None
    for entry in sources.values() if isinstance(sources, dict) else []:
        name = entry.get("file") if isinstance(entry, dict) else None
        if isinstance(name, str) and "/" not in name and name not in files:
            path = out_dir / name
            if path.is_file():
                files[name] = path.read_bytes()
    problems = verify_pins(pins, files)
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if not problems:
        print("pins verified")
    return 1 if problems else 0


def main(argv: list[str] | None = None, transport: httpx.BaseTransport | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--verify", action="store_true", help="re-hash committed files only")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)
    if args.verify:
        return run_verify(args.out_dir)
    contact = os.environ.get("GRAVEYARD_CONTACT", "")
    agent = "graveyard-heldout-pin" + (f" ({contact})" if contact else "")
    with httpx.Client(
        timeout=30.0,
        follow_redirects=False,
        transport=transport,
        headers={"User-Agent": agent},
    ) as client:
        return run_pin(client, args.out_dir)


if __name__ == "__main__":
    sys.exit(main())
