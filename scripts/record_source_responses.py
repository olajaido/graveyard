#!/usr/bin/env python3
"""Record the real source responses behind the nine mortality anchors. MAINTAINER-RUN ONLY.

Spec ``autopsy-sources``, T11 (SRC-REC-1…5, SRC-SEC-7, D7). The agent writes this script and
its tests; the maintainer runs it once (T12) and commits what it writes.

Usage (from ``backend/``)::

    read -rs GITHUB_TOKEN; export GITHUB_TOKEN        # public read-only, no scopes needed
    export GRAVEYARD_CONTACT=you@example.org
    uv run python ../scripts/record_source_responses.py [--fallbacks] [--probe-pypistats] [--strict]

What it does
    It runs the **production** clients (``sources.autopsy_async``) against the live sources for
    the nine anchor purls at ``as_of = 2026-11-03``, as one batch, through a
    ``RecordingTransport`` that keeps every exchange. The purls come from the committed anchor
    fixtures (``core/scoring/tests/fixtures/anchors``). It then scores each result with
    ``core.scoring.score_package`` and compares it with the table of MM-ANC-1…9 below.

The refusal rule (review decision Q3)
    If any anchor's base state, ``dead_reason``, ``cursed``, ``wounded``, or the extras
    (``left-pad`` mortality equals ``s1_min_score``; ``pycrypto`` and ``nose`` confidence
    0.25; ``six`` mortality within 0.5 of 43.7; exposure 1.0 and assumed) differ from the
    table, the script prints the anchor and the field, exits with status 1 and **writes
    nothing**: no cassette, no README row, no probe file. Do not edit the table to make it
    pass; changing an MM-ANC expectation is a separate decision.

Other checks (all before anything is written)
    * parity with the committed anchor fixtures (SRC-ANC-3) is printed as warnings, and
      blocks only with ``--strict``;
    * every recorded body is at most 2 MiB and the bodies together at most 6 MiB;
    * a response that is not JSON and has a 2xx status is a refusal (a cassette stores JSON
      only); a non-2xx response that is not JSON is listed and left out;
    * the output text must contain neither the token nor anything shaped like a GitHub token.

Parity tolerances (SRC-ANC-3). The fixtures were captured on 8 Nov, this run is later, so
the live counters may move. They must still be present (or absent) in both, and within:
    s3 last push: 14 days   s4, s8 Scorecard: 0.5   s5 committers: 1
    s6 issues: max(10, 5 %)   s9 npm downloads: max(1,000, 25 %)
Equal required: repo, resolved and latest version, S1b, S2, and every fixture advisory (same
``has_fix``, same date; extra advisories are listed). S1 may be ``None`` where the fixture has
``False`` (D5). PyPI S9 is not compared when it was not fetched because the package cannot be
Resting (D14).

Options
    ``--fallbacks``       also record endpoints the happy path does not touch: the Scorecard API
                          for each resolved repo, the full packuments of ``left-pad`` and
                          ``node-uuid``, the deps.dev package endpoint for ``left-pad`` and
                          ``six``, and one 404 probe each for deps.dev and the Scorecard API.
    ``--probe-pypistats`` send 12 polite sequential requests to pypistats.org (3 each at 3.0,
                          2.0, 1.0 and 0.5 s, stopping at the first 429) and write
                          ``pypistats_probe.json``. It never changes configuration.
    ``--strict``          treat parity differences as a refusal.
    ``--out-dir DIR``     where to write (default: ``core/sources/tests/fixtures/recorded``).

Security (D7, T6)
    ``GITHUB_TOKEN`` and ``GRAVEYARD_CONTACT`` are read from the environment **here and only
    here**, in ``main``, and passed on as arguments. The token goes only to ``api.github.com``
    (the gateway adds it, per request). Nothing this script prints is allowed to contain it:
    all output goes through ``redact``, error messages are the exception type name only, and
    the cassette stores no request header at all. Run with ``--help`` to see the options.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import tempfile
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final, TextIO

import httpx

REPO_ROOT: Final = Path(__file__).resolve().parent.parent
BACKEND: Final = REPO_ROOT / "backend"
if str(BACKEND) not in sys.path:  # `python ../scripts/...` puts scripts/, not backend/, first
    sys.path.insert(0, str(BACKEND))

from core.purl import repo_key  # noqa: E402
from core.scoring import score_package  # noqa: E402
from core.scoring.types import BaseState, ScoringResult  # noqa: E402
from core.scoring.weights import load_weights  # noqa: E402
from core.sources import assemble as asm  # noqa: E402
from core.sources.cassette import (  # noqa: E402
    Cassette,
    CassetteEntry,
    FrozenJson,
    cassette_to_obj,
    freeze_json,
    thaw_json,
)
from core.sources.config import SourcesConfig  # noqa: E402
from core.sources.model import JsonValue, SourceResult  # noqa: E402
from core.sources.secret import SecretToken, redact  # noqa: E402
from core.sources.urls import (  # noqa: E402
    depsdev_package_url,
    depsdev_version_url,
    npm_packument_url,
    pypistats_recent_url,
    scorecard_url,
)
from sources.api import autopsy_async  # noqa: E402
from sources.clock import SystemClock  # noqa: E402
from sources.gateway import ApiRequest, HttpGateway  # noqa: E402

AS_OF: Final = date(2026, 11, 3)
RECORDED_DIR: Final = BACKEND / "core" / "sources" / "tests" / "fixtures" / "recorded"
ANCHOR_FIXTURES: Final = BACKEND / "core" / "scoring" / "tests" / "fixtures" / "anchors"
CASSETTE_NAME: Final = "anchors.cassette.json"
PROBE_NAME: Final = "pypistats_probe.json"
README_NAME: Final = "README.md"

MAX_BODY_BYTES: Final = 2 * 1024 * 1024
MAX_TOTAL_BYTES: Final = 6 * 1024 * 1024

ANCHOR_ORDER: Final[tuple[str, ...]] = (
    "request",
    "node-uuid",
    "left-pad",
    "express",
    "uuid",
    "moment",
    "pycrypto",
    "nose",
    "six",
)
"""MM-ANC-1…9 in order."""

MORTALITY_TOLERANCE: Final = 0.5
SIX_SENTINEL: Final = 43.7
CONFIDENCE_S2_ONLY: Final = 0.25


# --------------------------------------------------------------------------- #
# The MM-ANC-1…9 table (do not edit to make a run pass)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Expected:
    """One row of MM-ANC-1…9 (``.kiro/specs/mortality-model/requirements.md``)."""

    base_state: BaseState
    dead_reason: str | None
    cursed: bool
    wounded: bool
    confidence: float | None = None  # exact value when the spec states one
    mortality_is_s1_min: bool = False  # left-pad: mortality == thresholds.s1_min_score
    mortality_near: float | None = None  # six: the borderline sentinel, within 0.5


EXPECTED: Final[Mapping[str, Expected]] = {
    "request": Expected(BaseState.DEAD, "declared", cursed=True, wounded=False),
    "node-uuid": Expected(BaseState.DEAD, "declared", cursed=False, wounded=False),
    "left-pad": Expected(
        BaseState.DEAD, "declared", cursed=False, wounded=False, mortality_is_s1_min=True
    ),
    "express": Expected(BaseState.ALIVE, None, cursed=False, wounded=True),
    "uuid": Expected(BaseState.ALIVE, None, cursed=False, wounded=True),
    "moment": Expected(BaseState.ALIVE, None, cursed=False, wounded=True),
    "pycrypto": Expected(
        BaseState.DEAD, "score", cursed=True, wounded=False, confidence=CONFIDENCE_S2_ONLY
    ),
    "nose": Expected(
        BaseState.DEAD, "score", cursed=False, wounded=False, confidence=CONFIDENCE_S2_ONLY
    ),
    "six": Expected(
        BaseState.RESTING, None, cursed=False, wounded=False, mortality_near=SIX_SENTINEL
    ),
}


def check_expectations(name: str, scored: ScoringResult) -> list[str]:
    """Return one message per field of ``scored`` that differs from the MM-ANC row of ``name``.

    Empty means the anchor still has its expected state. Messages name the anchor and the field
    and carry only enum names, flags and numbers.
    """
    expected = EXPECTED[name]
    weights = load_weights()
    problems: list[str] = []

    def differ(field_name: str, got: object, want: object) -> None:
        problems.append(f"{name}: {field_name} is {got}, expected {want}")

    if scored.base_state != expected.base_state:
        differ("base_state", scored.base_state.value, expected.base_state.value)
    if scored.dead_reason != expected.dead_reason:
        differ("dead_reason", scored.dead_reason, expected.dead_reason)
    if scored.cursed is not expected.cursed:
        differ("cursed", scored.cursed, expected.cursed)
    if scored.wounded is not expected.wounded:
        differ("wounded", scored.wounded, expected.wounded)
    if scored.exposure != 1.0:
        differ("exposure", scored.exposure, 1.0)
    if scored.exposure_assumed is not True:
        differ("exposure_assumed", scored.exposure_assumed, True)
    if expected.confidence is not None and abs(scored.confidence - expected.confidence) > 1e-9:
        differ("confidence", scored.confidence, expected.confidence)
    if expected.mortality_is_s1_min and scored.mortality != weights.threshold_s1_min_score:
        differ("mortality", scored.mortality, f"s1_min_score {weights.threshold_s1_min_score}")
    if expected.mortality_near is not None:
        mortality = scored.mortality
        near = (
            mortality is not None
            and abs(mortality - expected.mortality_near) <= MORTALITY_TOLERANCE
        )
        if not near:
            differ("mortality", mortality, f"{expected.mortality_near} +/- {MORTALITY_TOLERANCE}")
        in_band = (
            mortality is not None and weights.threshold_ailing <= mortality < weights.threshold_dead
        )
        if not in_band:
            differ(
                "mortality", mortality, f"[{weights.threshold_ailing}, {weights.threshold_dead})"
            )
    return problems


# --------------------------------------------------------------------------- #
# Parity with the committed anchor fixtures (SRC-ANC-3)
# --------------------------------------------------------------------------- #
_DATE_TOLERANCE_DAYS: Final = 14
_SCORE_TOLERANCE: Final = 0.5
_COMMITTERS_TOLERANCE: Final = 1
_ISSUES_ABS: Final = 10
_ISSUES_REL: Final = 0.05
_DOWNLOADS_ABS: Final = 1_000
_DOWNLOADS_REL: Final = 0.25


def _within(key: str, old: object, new: object) -> bool:
    """True if the live value ``new`` is within the stated tolerance of the fixture's ``old``."""
    if isinstance(old, str) and isinstance(new, date):
        return abs((new - date.fromisoformat(old)).days) <= _DATE_TOLERANCE_DAYS
    if not isinstance(old, int | float) or not isinstance(new, int | float):
        return False
    if key in ("s4_maintained", "s8_overall"):
        return abs(new - old) <= _SCORE_TOLERANCE
    if key == "s5_committers":
        return abs(new - old) <= _COMMITTERS_TOLERANCE
    if key in ("s6_open_issues", "s6_closed_issues"):
        return abs(new - old) <= max(_ISSUES_ABS, _ISSUES_REL * abs(old))
    if key == "s9_weekly_downloads":
        return abs(new - old) <= max(_DOWNLOADS_ABS, _DOWNLOADS_REL * abs(old))
    return new == old


def parity_differences(name: str, result: SourceResult, fixture: Mapping[str, Any]) -> list[str]:
    """Differences between the live ``result`` and the committed anchor ``fixture`` (SRC-ANC-3)."""
    signals = result.signals
    if signals is None:
        return [f"{name}: not analysed"]
    out: list[str] = []
    fixture_signals: Mapping[str, Any] = fixture["signals"]

    def value(key: str) -> Any:
        return fixture_signals[key]["value"]

    old_repo = fixture["repo"]
    new_repo = result.repo
    if (None if old_repo is None else repo_key(old_repo)) != (
        None if new_repo is None else repo_key(new_repo)
    ):
        out.append(f"{name}: repo is {new_repo}, fixture has {old_repo}")
    for label, got in (
        ("resolved_version", result.resolved_version),
        ("latest_version", result.latest_version),
    ):
        if got != fixture[label]:
            out.append(f"{name}: {label} is {got}, fixture has {fixture[label]}")

    if signals.s1b_version_deprecated != value("s1b_version_deprecated"):
        out.append(
            f"{name}: s1b_version_deprecated is {signals.s1b_version_deprecated}, "
            f"fixture has {value('s1b_version_deprecated')}"
        )
    s2 = None if signals.s2_latest_release_at is None else signals.s2_latest_release_at.isoformat()
    if s2 != value("s2_latest_release_at"):
        out.append(
            f"{name}: s2_latest_release_at is {s2}, fixture has {value('s2_latest_release_at')}"
        )

    old_s1, new_s1 = value("s1_declared_death"), signals.s1_declared_death
    if new_s1 != old_s1 and not (old_s1 is False and new_s1 is None):  # D5
        out.append(f"{name}: s1_declared_death is {new_s1}, fixture has {old_s1}")

    out.extend(_advisory_differences(name, signals.s7_advisories, value("s7_advisories")))

    live: Mapping[str, object] = {
        "s3_last_push_at": signals.s3_last_push_at,
        "s4_maintained": signals.s4_maintained,
        "s5_committers": signals.s5_committers,
        "s6_open_issues": signals.s6_open_issues,
        "s6_closed_issues": signals.s6_closed_issues,
        "s8_overall": signals.s8_overall,
        "s9_weekly_downloads": signals.s9_weekly_downloads,
    }
    for key, new in live.items():
        old = value(key)
        if key == "s9_weekly_downloads" and result.evidence[key].note == asm.NOTE_S9_SKIPPED:
            continue  # D14: a PyPI package that cannot be Resting is not asked
        if (old is None) != (new is None):
            out.append(f"{name}: {key} is {_show(new)}, fixture has {_show(old)} (presence)")
        elif old is not None and not _within(key, old, new):
            out.append(
                f"{name}: {key} is {_show(new)}, fixture has {_show(old)} (outside tolerance)"
            )
    return out


def _show(value: object) -> str:
    return "missing" if value is None else str(value)


def _advisory_differences(
    name: str, new: Sequence[Any] | None, old: Sequence[Any] | None
) -> list[str]:
    if old is None:
        return []
    if new is None:
        return [f"{name}: s7_advisories is missing, fixture has {len(old)}"]
    live = {advisory.id: advisory for advisory in new}
    out: list[str] = []
    for item in old:
        advisory = live.get(item["id"])
        if advisory is None:
            out.append(f"{name}: advisory {item['id']} is no longer listed")
            continue
        published = None if advisory.published_at is None else advisory.published_at.isoformat()
        if advisory.has_fix != item["has_fix"]:
            out.append(f"{name}: advisory {item['id']} has_fix is {advisory.has_fix}")
        if published != item["published_at"]:
            out.append(f"{name}: advisory {item['id']} published_at is {published}")
    known = {item["id"] for item in old}
    out.extend(
        f"{name}: extra advisory {advisory_id}"
        for advisory_id in sorted(live)
        if advisory_id not in known
    )
    return out


# --------------------------------------------------------------------------- #
# Recording transport
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Exchange:
    """One recorded request and response; bodies are parsed JSON, no header is kept."""

    method: str
    url: str
    request_body: JsonValue
    status: int
    content_type: str | None
    retry_after: str | None
    response_body: JsonValue


@dataclass(frozen=True)
class Unrecorded:
    """An exchange that cannot be stored (a cassette holds JSON only)."""

    method: str
    url: str
    status: int
    reason: str


def _reject_constant(_: str) -> Any:
    raise ValueError("NaN and infinity are not JSON")


def parse_json_bytes(data: bytes) -> tuple[bool, JsonValue]:
    """``(True, value)`` if ``data`` is a JSON document, else ``(False, None)``. Never raises."""
    try:
        return True, json.loads(data.decode("utf-8"), parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        return False, None


_DROPPED_RESPONSE_HEADERS: Final = frozenset(
    {"content-encoding", "content-length", "transfer-encoding"}
)


class RecordingTransport(httpx.AsyncBaseTransport):
    """Wrap a real transport and keep every exchange as ``Exchange`` values.

    The response is read in full, decoded, and handed on as a plain in-memory response, so the
    client sees the same status, headers (minus the encoding headers) and body. Request headers
    are never read, so an ``Authorization`` header cannot reach the record (SRC-SEC-7).
    """

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self._inner = inner
        self.exchanges: list[Exchange] = []
        self.unrecorded: list[Unrecorded] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._inner.handle_async_request(request)
        body = await response.aread()
        content_type = response.headers.get("content-type")
        retry_after = response.headers.get("retry-after")
        method, url = request.method.upper(), str(request.url)

        request_ok, request_body = (True, None)
        if request.content:
            request_ok, request_body = parse_json_bytes(request.content)
        response_ok, response_body = parse_json_bytes(body) if body else (False, None)
        if not request_ok:
            self.unrecorded.append(
                Unrecorded(method, url, response.status_code, "request body is not JSON")
            )
        elif not response_ok:
            self.unrecorded.append(
                Unrecorded(method, url, response.status_code, "response body is not JSON")
            )
        else:
            self.exchanges.append(
                Exchange(
                    method,
                    url,
                    request_body,
                    response.status_code,
                    content_type,
                    retry_after,
                    response_body,
                )
            )
        headers = [
            (key, value)
            for key, value in response.headers.multi_items()
            if key.lower() not in _DROPPED_RESPONSE_HEADERS
        ]
        return httpx.Response(
            response.status_code,
            headers=headers,
            content=body,
            extensions=response.extensions,
            request=request,
        )

    async def aclose(self) -> None:
        await self._inner.aclose()


# --------------------------------------------------------------------------- #
# Building, checking and writing the cassette
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Built:
    """A cassette plus how many earlier exchanges a later identical request replaced."""

    cassette: Cassette
    superseded: int


def build_cassette(exchanges: Sequence[Exchange]) -> Built:
    """Build the cassette; of several identical requests (retries) the last answer wins."""
    by_key: dict[str, CassetteEntry] = {}
    superseded = 0
    for exchange in exchanges:
        entry = CassetteEntry(
            method=exchange.method,
            url=exchange.url,
            request_body=freeze_json(exchange.request_body),
            status=exchange.status,
            content_type=exchange.content_type,
            retry_after=exchange.retry_after,
            response_body=freeze_json(exchange.response_body),
        )
        if entry.key in by_key:
            superseded += 1
        by_key[entry.key] = entry
    return Built(Cassette(entries=tuple(by_key.values())), superseded)


def _compact_size(body: FrozenJson) -> int:
    text = json.dumps(thaw_json(body), separators=(",", ":"), ensure_ascii=False)
    return len(text.encode("utf-8"))


def check_sizes(cassette: Cassette) -> list[str]:
    """Messages for a body over 2 MiB and for bodies together over 6 MiB (SRC-REC-4)."""
    problems: list[str] = []
    total = 0
    for entry in cassette.entries:
        size = _compact_size(entry.response_body)
        total += size
        if size > MAX_BODY_BYTES:
            problems.append(
                f"body of {entry.method} {entry.url} is {size} bytes, over {MAX_BODY_BYTES}"
            )
    if total > MAX_TOTAL_BYTES:
        problems.append(f"bodies total {total} bytes, over {MAX_TOTAL_BYTES}")
    return problems


def render_cassette(cassette: Cassette) -> str:
    """The cassette file text: stable order, one trailing newline."""
    return json.dumps(cassette_to_obj(cassette), indent=1, ensure_ascii=False) + "\n"


def find_secrets(text: str, token: str | None) -> list[str]:
    """Descriptions of secrets in ``text``; the secrets themselves are never returned."""
    found: list[str] = []
    if token and token in text:
        found.append("the GitHub token")
    if redact(text) != text:
        found.append("a GitHub-token-shaped string")
    return found


def write_atomic(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` through a temporary file in the same directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


_README_HEADER: Final = """# Recorded source responses

Written by `scripts/record_source_responses.py` (spec `autopsy-sources`, T11/T12). Bodies are
stored verbatim as parsed JSON; no request header is stored. Do not edit by hand.

| File | Source | Command | httpx | Recorded on | Notes |
|---|---|---|---|---|---|
"""


@dataclass(frozen=True)
class ProvenanceRow:
    file: str
    source: str
    command: str
    recorded_on: date
    notes: str

    def render(self, httpx_version: str) -> str:
        cells = (
            self.file,
            self.source,
            self.command,
            httpx_version,
            self.recorded_on.isoformat(),
            self.notes,
        )
        return (
            "| " + " | ".join(cell.replace("|", "/").replace("\n", " ") for cell in cells) + " |\n"
        )


def append_provenance(readme: Path, rows: Sequence[ProvenanceRow], httpx_version: str) -> None:
    """Add ``rows`` to the README table, creating the README with its header if it is absent."""
    existing = readme.read_text(encoding="utf-8") if readme.exists() else _README_HEADER
    if not existing.endswith("\n"):
        existing += "\n"
    write_atomic(readme, existing + "".join(row.render(httpx_version) for row in rows))


# --------------------------------------------------------------------------- #
# Evaluation of one run
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Evaluation:
    """Mismatches against MM-ANC-1…9 (a refusal), parity warnings, and the scored results."""

    mismatches: tuple[str, ...]
    parity: tuple[str, ...]
    scored: Mapping[str, ScoringResult]


def evaluate(
    results: Mapping[str, SourceResult], fixtures: Mapping[str, Mapping[str, Any]]
) -> Evaluation:
    """Score every anchor and compare it with the table and with its committed fixture."""
    mismatches: list[str] = []
    parity: list[str] = []
    scored: dict[str, ScoringResult] = {}
    for name in ANCHOR_ORDER:
        result = results.get(name)
        if result is None or result.signals is None:
            code = None if result is None or result.error is None else result.error.code
            mismatches.append(f"{name}: not analysed ({code or 'no result'})")
            continue
        scored[name] = score_package(result.signals)
        mismatches.extend(check_expectations(name, scored[name]))
        parity.extend(parity_differences(name, result, fixtures[name]))
    return Evaluation(tuple(mismatches), tuple(parity), scored)


def load_anchor_fixtures(directory: Path) -> dict[str, dict[str, Any]]:
    """Read the nine committed anchor fixtures; ``ValueError`` if one is missing or off."""
    fixtures: dict[str, dict[str, Any]] = {}
    for name in ANCHOR_ORDER:
        path = directory / f"{name}.json"
        if not path.is_file():
            raise ValueError(f"anchor fixture {name}.json is missing")
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("as_of") != AS_OF.isoformat() or not isinstance(document.get("purl"), str):
            raise ValueError(f"anchor fixture {name}.json does not have as_of {AS_OF.isoformat()}")
        fixtures[name] = document
    return fixtures


# --------------------------------------------------------------------------- #
# Fallback requests (--fallbacks)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class FallbackRequest:
    label: str
    request: ApiRequest


def fallback_requests(repos: Sequence[str]) -> list[FallbackRequest]:
    """The endpoints the happy path does not touch (SRC-REC-2), built by ``urls.py`` only."""
    out: list[FallbackRequest] = []
    for repo in sorted(set(repos)):
        _, owner, name = repo.split("/")
        out.append(
            FallbackRequest(
                f"scorecard {repo}",
                ApiRequest("GET", scorecard_url(owner, name), "scorecard", not_found_ok=True),
            )
        )
    for package in ("left-pad", "node-uuid"):
        out.append(
            FallbackRequest(
                f"npm full packument {package}",
                ApiRequest("GET", npm_packument_url(package), "npm_registry", not_found_ok=True),
            )
        )
    for ecosystem, package in (("npm", "left-pad"), ("pypi", "six")):
        out.append(
            FallbackRequest(
                f"deps.dev package {ecosystem}/{package}",
                ApiRequest(
                    "GET", depsdev_package_url(ecosystem, package), "depsdev", not_found_ok=True
                ),
            )
        )
    out.append(
        FallbackRequest(
            "deps.dev 404 probe",
            ApiRequest(
                "GET",
                depsdev_version_url("npm", "graveyard-no-such-package-404", "0.0.0"),
                "depsdev",
                not_found_ok=True,
            ),
        )
    )
    out.append(
        FallbackRequest(
            "Scorecard 404 probe",
            ApiRequest(
                "GET",
                scorecard_url("graveyard-no-such-owner", "no-such-repo-404"),
                "scorecard",
                not_found_ok=True,
            ),
        )
    )
    return out


# --------------------------------------------------------------------------- #
# pypistats probe (--probe-pypistats, SRC-REC-5)
# --------------------------------------------------------------------------- #
PROBE_PACKAGES: Final[tuple[str, ...]] = (
    "requests",
    "numpy",
    "pandas",
    "boto3",
    "urllib3",
    "setuptools",
    "certifi",
    "idna",
    "charset-normalizer",
    "typing-extensions",
    "python-dateutil",
    "pyyaml",
)
PROBE_INTERVALS: Final[tuple[float, ...]] = (3.0, 2.0, 1.0, 0.5)
PROBE_PER_INTERVAL: Final = 3
_RATE_HEADER: Final = re.compile(r"^(x-)?ratelimit-[a-z0-9-]+$|^retry-after$")


@dataclass(frozen=True)
class ProbeRecord:
    """One probe request: the pause before it, the answer, and its rate-limit headers."""

    interval_seconds: float
    package: str
    status: int | None
    error: str | None
    retry_after: str | None
    ratelimit_headers: Mapping[str, str] = field(default_factory=dict)


def _clean_header_value(value: str) -> str:
    return "".join(ch if " " <= ch <= "~" else "?" for ch in value)[:100]


async def run_probe(
    client: httpx.AsyncClient,
    sleep: Callable[[float], Awaitable[None]],
    *,
    packages: Sequence[str] = PROBE_PACKAGES,
    intervals: Sequence[float] = PROBE_INTERVALS,
    per_interval: int = PROBE_PER_INTERVAL,
) -> list[ProbeRecord]:
    """Send ``per_interval`` sequential requests at each interval; stop at the first 429."""
    records: list[ProbeRecord] = []
    names = iter(packages)
    for interval in intervals:
        for _ in range(per_interval):
            package = next(names, None)
            if package is None:
                return records
            await sleep(interval)
            try:
                response = await client.get(pypistats_recent_url(package))
            except httpx.HTTPError as exc:
                records.append(ProbeRecord(interval, package, None, type(exc).__name__, None))
                continue
            kept = {
                key.lower(): _clean_header_value(value)
                for key, value in response.headers.items()
                if _RATE_HEADER.match(key.lower())
            }
            retry_after = kept.pop("retry-after", None)
            records.append(
                ProbeRecord(
                    interval,
                    package,
                    response.status_code,
                    None,
                    retry_after,
                    dict(sorted(kept.items())),
                )
            )
            if response.status_code == 429:
                return records
    return records


def safe_interval_seconds(records: Sequence[ProbeRecord]) -> float | None:
    """The smallest tested interval reached without a 429 (``None`` if even the first failed).

    Intervals are tried from the largest down and the probe stops at the first 429, so the
    answer is the last interval group that completed with no 429; a group that saw a 429, and
    any group after it, does not count. Errors other than 429 are ignored.
    """
    safe: float | None = None
    seen: list[float] = []
    for record in records:
        if record.interval_seconds not in seen:
            seen.append(record.interval_seconds)
    for interval in seen:
        group = [r for r in records if r.interval_seconds == interval]
        if any(r.status == 429 for r in group):
            break
        safe = interval
    return safe


def probe_document(
    records: Sequence[ProbeRecord], recorded_on: date, configured: float
) -> dict[str, Any]:
    """The ``pypistats_probe.json`` content: per-request facts and the computed safe interval."""
    return {
        "host": "pypistats.org",
        "recorded_on": recorded_on.isoformat(),
        "configured_interval_seconds": configured,
        "stopped_at_429": any(r.status == 429 for r in records),
        "safe_interval_seconds": safe_interval_seconds(records),
        "requests": [
            {
                "interval_seconds": r.interval_seconds,
                "package": r.package,
                "status": r.status,
                "error": r.error,
                "retry_after": r.retry_after,
                "ratelimit_headers": dict(r.ratelimit_headers),
            }
            for r in records
        ],
    }


# --------------------------------------------------------------------------- #
# Environment, options and the run
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Environment:
    token: str
    contact: str


def read_environment(environ: Mapping[str, str]) -> Environment | str:
    """The two variables, or an error message that names them and never shows a value."""
    token = environ.get("GITHUB_TOKEN", "").strip()
    contact = environ.get("GRAVEYARD_CONTACT", "").strip()
    missing = [
        name
        for name, value in (("GITHUB_TOKEN", token), ("GRAVEYARD_CONTACT", contact))
        if not value
    ]
    if missing:
        return (
            f"{' and '.join(missing)} {'is' if len(missing) == 1 else 'are'} not set. "
            "Export a public read-only GitHub token (no scopes needed) as GITHUB_TOKEN, e.g. "
            "`read -rs GITHUB_TOKEN; export GITHUB_TOKEN`, and a contact email or URL as "
            "GRAVEYARD_CONTACT (it goes into the User-Agent)."
        )
    return Environment(token, contact)


@dataclass(frozen=True)
class Options:
    fallbacks: bool = False
    probe_pypistats: bool = False
    strict: bool = False
    out_dir: Path = RECORDED_DIR
    anchors_dir: Path = ANCHOR_FIXTURES


def parse_args(argv: Sequence[str] | None) -> Options:
    parser = argparse.ArgumentParser(
        prog="record_source_responses.py",
        description="Record the real source responses behind the nine anchors (maintainer-run).",
    )
    parser.add_argument(
        "--fallbacks", action="store_true", help="also record the fallback endpoints"
    )
    parser.add_argument(
        "--probe-pypistats", action="store_true", help="measure the pypistats limit"
    )
    parser.add_argument("--strict", action="store_true", help="parity differences are a refusal")
    parser.add_argument("--out-dir", type=Path, default=RECORDED_DIR, help="where to write")
    parser.add_argument("--anchors-dir", type=Path, default=ANCHOR_FIXTURES, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    return Options(
        args.fallbacks, args.probe_pypistats, args.strict, args.out_dir, args.anchors_dir
    )


def command_line(options: Options) -> str:
    parts = ["uv run python ../scripts/record_source_responses.py"]
    if options.fallbacks:
        parts.append("--fallbacks")
    if options.probe_pypistats:
        parts.append("--probe-pypistats")
    if options.strict:
        parts.append("--strict")
    return " ".join(parts)


async def record(
    options: Options,
    env: Environment,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    emit: Callable[[str], None],
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    today: date | None = None,
) -> int:
    """Run the recording. Returns 0, or 1 for a refusal (nothing written)."""
    fixtures = load_anchor_fixtures(options.anchors_dir)
    config = SourcesConfig.default(contact=env.contact)
    token = SecretToken(env.token)
    recorder = RecordingTransport(
        transport if transport is not None else httpx.AsyncHTTPTransport()
    )
    requests = [(fixtures[name]["purl"], AS_OF) for name in ANCHOR_ORDER]

    emit(f"Recording {len(requests)} anchors at as_of {AS_OF.isoformat()} (one batch)...")
    batch = await autopsy_async(requests, config=config, token=token, transport=recorder)
    results = dict(zip(ANCHOR_ORDER, batch.results, strict=True))

    if options.fallbacks:
        repos = [r.repo for r in batch.results if r.repo is not None]
        emit("Recording fallback endpoints...")
        async with HttpGateway(config, SystemClock(), token=token, transport=recorder) as gateway:
            for item in fallback_requests(repos):
                outcome = await gateway.fetch(item.request)
                emit(f"  {item.label}: {type(outcome).__name__}")

    evaluation = evaluate(results, fixtures)
    for name in ANCHOR_ORDER:
        scored = evaluation.scored.get(name)
        if scored is not None:
            reason = f" ({scored.dead_reason})" if scored.dead_reason else ""
            emit(f"  [{name}] {scored.base_state.value}{reason}")

    refusals: list[str] = list(evaluation.mismatches)
    if refusals:
        emit("REFUSING: an anchor's expected state would change (MM-ANC-1…9).")
    for line in evaluation.parity:
        emit(f"  parity: {line}")
    if evaluation.parity and options.strict:
        refusals.append(f"{len(evaluation.parity)} parity difference(s) and --strict is set")

    refusals.extend(
        f"{u.method} {u.url}: {u.reason} (status {u.status})"
        for u in recorder.unrecorded
        if 200 <= u.status < 300
    )
    for u in recorder.unrecorded:
        if not 200 <= u.status < 300:
            emit(f"  left out: {u.method} {u.url}: {u.reason} (status {u.status})")

    built = build_cassette(recorder.exchanges)
    refusals.extend(check_sizes(built.cassette))
    text = render_cassette(built.cassette)
    refusals.extend(f"output contains {what}" for what in find_secrets(text, env.token))

    if refusals:
        for line in refusals:
            emit(f"  refused: {line}")
        emit("Nothing was written.")
        return 1

    when = today if today is not None else datetime.now(UTC).date()
    version = httpx.__version__
    command = command_line(options)
    write_atomic(options.out_dir / CASSETTE_NAME, text)
    rows = [
        ProvenanceRow(
            CASSETTE_NAME,
            "deps.dev, OSV, npm, PyPI, pypistats, Scorecard, GitHub GraphQL (live)",
            command,
            when,
            f"{len(built.cassette.entries)} exchanges, nine anchors at as_of {AS_OF.isoformat()}"
            + (
                f", {built.superseded} retried request(s) keep the last answer"
                if built.superseded
                else ""
            ),
        )
    ]
    emit(f"Wrote {CASSETTE_NAME}: {len(built.cassette.entries)} exchanges.")

    if options.probe_pypistats:
        emit("Probing pypistats.org (at most 12 sequential requests)...")
        async with httpx.AsyncClient(
            transport=transport,
            timeout=15.0,
            follow_redirects=False,
            trust_env=False,
            headers={
                "User-Agent": f"graveyard-record/1.0 (+{env.contact})",
                "Accept": "application/json",
            },
        ) as client:
            records = await run_probe(client, sleep)
        document = probe_document(records, when, config.hosts["pypistats.org"].min_interval_seconds)
        write_atomic(options.out_dir / PROBE_NAME, json.dumps(document, indent=1) + "\n")
        safe = document["safe_interval_seconds"]
        stopped = document["stopped_at_429"]
        emit(f"Wrote {PROBE_NAME}: safe_interval_seconds = {safe}, stopped_at_429 = {stopped}.")
        note = f"{len(records)} requests; safe interval {safe}; stopped at 429: {stopped}"
        rows.append(ProvenanceRow(PROBE_NAME, "pypistats.org (live)", command, when, note))
    append_provenance(options.out_dir / README_NAME, rows, version)
    emit(f"Updated {README_NAME}. Review the files for secrets, then commit them (T12.4).")
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> int:
    """Entry point. 0 ok, 1 refused or failed, 2 for a usage or environment problem."""
    stdout = out if out is not None else sys.stdout
    stderr = err if err is not None else sys.stderr
    options = parse_args(argv)
    env = read_environment(environ if environ is not None else os.environ)
    if isinstance(env, str):
        print(f"error: {env}", file=stderr)
        return 2
    secret = env.token

    def emit(message: str) -> None:
        print(redact(message, secret), file=stdout)

    try:
        SecretToken(env.token)
        SourcesConfig.default(contact=env.contact)
    except ValueError:
        print(
            "error: GITHUB_TOKEN or GRAVEYARD_CONTACT has an invalid form (value not shown).",
            file=stderr,
        )
        return 2
    try:
        return asyncio.run(record(options, env, transport=transport, emit=emit, sleep=sleep))
    except Exception as exc:  # the type name only: no message, no token, no response text
        print(redact(f"error: {type(exc).__name__}", secret), file=stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
