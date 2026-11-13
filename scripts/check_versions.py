#!/usr/bin/env python3
"""Check every labelled row's version against its registry (eval/LABELLING.md, Amendment 4.4).

For each row of ``eval/labelled_packages.csv`` this makes read-only GET requests from
the host to the public registries (https://pypi.org/pypi/<name>/json and
https://registry.npmjs.org/<name>) and records whether the row's version exists, what
the current latest version is, and when both were published. Writes
``eval/review/versions.tsv`` and prints the rows whose version does not exist or
differs from the current latest. Nothing is installed or executed.

Usage:
    python3 scripts/check_versions.py [--csv PATH] [--out PATH] [--limit N]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV = REPO_ROOT / "eval" / "labelled_packages.csv"
DEFAULT_OUT = REPO_ROOT / "eval" / "review" / "versions.tsv"

TIMEOUT_SECONDS = 30
USER_AGENT = "graveyard-eval-versions (read-only registry check)"

YES, NO, ERROR = "yes", "no", "error"

COLUMNS = (
    "ecosystem",
    "name",
    "row_version",
    "exists_on_registry",
    "current_latest",
    "row_version_published_at",
    "latest_published_at",
)

_NAME = re.compile(r"^[A-Za-z0-9@][A-Za-z0-9._/~-]*$")


@dataclass(frozen=True)
class RegistryInfo:
    """What a registry says about one package. ``error`` is set if it could not be read."""

    found: bool  # package exists on the registry at all
    latest: str = ""
    versions: dict[str, str] | None = None  # version -> published_at ("" if unknown)
    error: str = ""


@dataclass(frozen=True)
class VersionRow:
    ecosystem: str
    name: str
    row_version: str
    exists: str  # YES / NO / ERROR
    latest: str
    row_published: str
    latest_published: str

    def fields(self) -> list[str]:
        return [
            self.ecosystem,
            self.name,
            self.row_version,
            self.exists,
            self.latest,
            self.row_published,
            self.latest_published,
        ]


# --------------------------------------------------------------------------- #
# Pure logic
# --------------------------------------------------------------------------- #
def normalise_version(version: str) -> str:
    """Loose equality key: lower-case, no leading ``v``, trailing ``.0`` parts dropped."""
    parts = version.strip().lower().removeprefix("v").split(".")
    while len(parts) > 1 and parts[-1] == "0":
        parts.pop()
    return ".".join(parts)


def find_version(versions: dict[str, str], wanted: str) -> str | None:
    """The registry's own spelling of ``wanted`` (exact first, then normalised), or None."""
    if wanted in versions:
        return wanted
    key = normalise_version(wanted)
    for candidate in versions:
        if normalise_version(candidate) == key:
            return candidate
    return None


def parse_pypi(data: dict[str, Any]) -> RegistryInfo:
    """Parse ``https://pypi.org/pypi/<name>/json``."""
    latest = str((data.get("info") or {}).get("version") or "")
    versions: dict[str, str] = {}
    for version, files in (data.get("releases") or {}).items():
        times = sorted(
            str(f["upload_time_iso_8601"])
            for f in files or []
            if isinstance(f, dict) and f.get("upload_time_iso_8601")
        )
        if files:  # a release with no files was never published
            versions[str(version)] = times[0] if times else ""
    return RegistryInfo(found=True, latest=latest, versions=versions)


def parse_npm(data: dict[str, Any]) -> RegistryInfo:
    """Parse ``https://registry.npmjs.org/<name>``."""
    latest = str((data.get("dist-tags") or {}).get("latest") or "")
    times = data.get("time") or {}
    versions = {str(v): str(times.get(v) or "") for v in (data.get("versions") or {})}
    return RegistryInfo(found=True, latest=latest, versions=versions)


def compare(ecosystem: str, name: str, row_version: str, info: RegistryInfo) -> VersionRow:
    """Compare a row's version with what the registry reports."""
    if info.error:
        return VersionRow(ecosystem, name, row_version, ERROR, "", "", "")
    if not info.found or info.versions is None:
        return VersionRow(ecosystem, name, row_version, NO, "", "", "")
    spelled = find_version(info.versions, row_version)
    latest_published = info.versions.get(info.latest, "") if info.latest else ""
    return VersionRow(
        ecosystem,
        name,
        row_version,
        YES if spelled is not None else NO,
        info.latest,
        info.versions[spelled] if spelled is not None else "",
        latest_published,
    )


def needs_attention(row: VersionRow) -> bool:
    """True if the version does not exist, could not be checked, or differs from latest."""
    if row.exists != YES:
        return True
    return normalise_version(row.row_version) != normalise_version(row.latest)


def registry_url(ecosystem: str, name: str) -> str:
    """The read-only registry URL for a package. Raises ``ValueError`` if unsafe."""
    if not _NAME.match(name) or ".." in name:
        raise ValueError(f"unsafe package name {name!r}")
    if ecosystem == "pypi":
        return f"https://pypi.org/pypi/{urllib.parse.quote(name, safe='')}/json"
    if ecosystem == "npm":
        return f"https://registry.npmjs.org/{urllib.parse.quote(name, safe='@')}"
    raise ValueError(f"unknown ecosystem {ecosystem!r} for {name!r}")


def parse_registry(ecosystem: str, data: dict[str, Any]) -> RegistryInfo:
    return parse_pypi(data) if ecosystem == "pypi" else parse_npm(data)


def tsv_line(fields: list[str]) -> str:
    return "\t".join(f.replace("\t", " ").replace("\n", " ") for f in fields)


def render_tsv(rows: list[VersionRow]) -> str:
    return "\n".join([tsv_line(list(COLUMNS)), *(tsv_line(r.fields()) for r in rows)]) + "\n"


# --------------------------------------------------------------------------- #
# Network I/O (not exercised by tests)
# --------------------------------------------------------------------------- #
def fetch_info(ecosystem: str, name: str) -> RegistryInfo:
    """One read-only GET. A 404 means the package is not on the registry."""
    try:
        url = registry_url(ecosystem, name)
        req = urllib.request.Request(  # noqa: S310
            url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}, method="GET"
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return RegistryInfo(found=False)
        return RegistryInfo(found=False, error=f"HTTP {exc.code}")
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        return RegistryInfo(found=False, error=f"{type(exc).__name__}: {exc}")
    return parse_registry(ecosystem, data)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--limit", type=int, default=None, help="check only the first N rows")
    args = ap.parse_args(argv)

    with args.csv.open(newline="", encoding="utf-8") as fh:
        source = list(csv.DictReader(fh))
    if args.limit is not None:
        source = source[: args.limit]

    cache: dict[tuple[str, str], RegistryInfo] = {}
    rows: list[VersionRow] = []
    for rec in source:
        eco = (rec.get("ecosystem") or "").strip()
        name = (rec.get("name") or "").strip()
        version = (rec.get("version") or "").strip()
        key = (eco, name)
        if key not in cache:
            cache[key] = fetch_info(eco, name)
        rows.append(compare(eco, name, version, cache[key]))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render_tsv(rows), encoding="utf-8")

    flagged = [r for r in rows if needs_attention(r)]
    print(tsv_line(list(COLUMNS)))
    for row in flagged:
        print(tsv_line(row.fields()))
    print(f"{len(rows)} rows checked, {len(flagged)} flagged")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
