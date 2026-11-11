"""Test support for the CLI suite (design §9.3, §9.4; CLI-TEST-5, CLI-TEST-11).

* ``make_stub_syft`` writes an executable Python script that stands in for Syft.
* ``subset_replay_transport`` replays the recorded cassette and derives the two single-package
  requests that cannot have a recording from the recorded batch answers. It reads only the
  recorded JSON, never the parsers under test.
* ``make_source_result``, ``FakeClock`` and ``shape`` are small builders for the other tests.

Not part of the ``cli`` wheel (it lives under ``tests/``). No network, no environment reads.
"""

from __future__ import annotations

import json
import stat
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal
from urllib.parse import unquote

import httpx

from core.scoring.types import Signals
from core.sources.cassette import Cassette, CassetteEntry, thaw_json
from core.sources.model import EVIDENCE_KEYS, Evidence, SourceResult, SourceWarning
from sources.tests.clock import FakeClock
from sources.tests.transports import ReplayLog, UnmatchedRequest, json_response, key_of

__all__ = [
    "DEFAULT_SBOM_DIR",
    "FakeClock",
    "ReplayLog",
    "StubSyft",
    "make_source_result",
    "make_stub_syft",
    "shape",
    "subset_replay_transport",
]

DEFAULT_SBOM_DIR: Final = Path(__file__).resolve().parent / "fixtures" / "sboms"

StubMode = Literal["ok", "fail", "sleep", "garbage", "array", "big"]

STUB_STDERR_SENTINEL: Final = "STUB-SYFT-SECRET-STDERR"

_STUB_TEMPLATE: Final = """#!{python}
import json
import os
import sys
import time

SBOM_DIR = {sbom_dir!r}
LOG_PATH = {log_path!r}
VERSION = {version!r}
MODE = {mode!r}
SENTINEL = {sentinel!r}

args = sys.argv[1:]
if args == ["--version"]:
    sys.stdout.write("syft " + VERSION + "\\n")
    sys.exit(0)

with open(LOG_PATH, "a", encoding="utf-8") as log:
    log.write(json.dumps({{"argv": args, "env_keys": sorted(os.environ)}}) + "\\n")

if MODE == "ok":
    segment = ""
    for arg in args:
        if arg.startswith("dir:"):
            segment = arg[len("dir:"):].rstrip("/").rsplit("/", 1)[-1]
            break
    with open(os.path.join(SBOM_DIR, segment + ".cdx.json"), encoding="utf-8") as handle:
        sys.stdout.write(handle.read())
elif MODE == "fail":
    sys.stderr.write(SENTINEL + "\\n")
    sys.exit(2)
elif MODE == "sleep":
    time.sleep(30)
elif MODE == "garbage":
    sys.stdout.write("not json\\n")
elif MODE == "array":
    sys.stdout.write("[]\\n")
elif MODE == "big":
    sys.stdout.write(json.dumps({{"pad": "x" * (1024 * 1024 + 16)}}))
else:
    sys.exit(3)
"""


@dataclass(frozen=True)
class StubSyft:
    """A stub Syft executable and the log of its calls."""

    path: Path
    log_path: Path

    def calls(self) -> list[dict[str, object]]:
        """Every recorded non-``--version`` call: ``{"argv": [...], "env_keys": [...]}``."""
        if not self.log_path.exists():
            return []
        lines = self.log_path.read_text(encoding="utf-8").splitlines()
        out: list[dict[str, object]] = []
        for line in lines:
            loaded = json.loads(line)
            assert isinstance(loaded, dict)
            out.append(loaded)
        return out


def make_stub_syft(
    tmp_path: Path,
    *,
    version: str = "1.56.0",
    mode: StubMode = "ok",
    sbom_dir: Path = DEFAULT_SBOM_DIR,
) -> StubSyft:
    """Write the stub script into ``tmp_path`` and return it with its log path."""
    path = tmp_path / "syft"
    log_path = tmp_path / "syft-calls.log"
    path.write_text(
        _STUB_TEMPLATE.format(
            python=sys.executable,
            sbom_dir=str(sbom_dir),
            log_path=str(log_path),
            version=version,
            mode=mode,
            sentinel=STUB_STDERR_SENTINEL,
        ),
        encoding="utf-8",
    )
    path.chmod(0o755)
    assert path.stat().st_mode & stat.S_IXUSR
    return StubSyft(path=path, log_path=log_path)


# ------------------------------------------------------------------ cassette-derived transport

_OSV_URL: Final = "https://api.osv.dev/v1/querybatch"
_NPM_DOWNLOADS: Final = "https://api.npmjs.org/downloads/point/last-week/"


def _recorded_osv(cassette: Cassette) -> tuple[Sequence[object], Sequence[object]] | None:
    """The queries and results of the recorded OSV batch, as plain JSON."""
    for item in cassette.entries:
        if item.method == "POST" and item.url == _OSV_URL:
            request = thaw_json(item.request_body)
            response = thaw_json(item.response_body)
            if isinstance(request, dict) and isinstance(response, dict):
                queries, results = request.get("queries"), response.get("results")
                if isinstance(queries, list) and isinstance(results, list):
                    return queries, results
    return None


def _recorded_bulk(cassette: Cassette) -> Mapping[str, object]:
    """The recorded bulk npm downloads answer (flat entry per name)."""
    for item in cassette.entries:
        if item.method == "GET" and item.url.startswith(_NPM_DOWNLOADS) and "," in item.url:
            body = thaw_json(item.response_body)
            if isinstance(body, dict):
                return body
    return {}


def subset_replay_transport(cassette: Cassette) -> tuple[httpx.MockTransport, ReplayLog]:
    """Replay ``cassette``, deriving single-package OSV and npm downloads answers (§9.4).

    Anything else without a recording is appended to ``log.unmatched`` and fails with
    ``httpx.ConnectError``.
    """
    index: dict[str, CassetteEntry] = dict(cassette.index())
    osv = _recorded_osv(cassette)
    bulk = _recorded_bulk(cassette)
    log = ReplayLog()

    def unmatched(request: httpx.Request, key: str) -> httpx.Response:
        log.unmatched.append(UnmatchedRequest(request.method, str(request.url), key))
        raise httpx.ConnectError("no recorded response for this request", request=request)

    def derive_osv(request: httpx.Request, key: str) -> httpx.Response:
        if osv is None:
            return unmatched(request, key)
        try:
            body = json.loads(request.content)
        except ValueError:
            return unmatched(request, key)
        queries = body.get("queries") if isinstance(body, dict) else None
        if not isinstance(queries, list) or not queries:
            return unmatched(request, key)
        recorded_queries, recorded_results = osv
        answers: list[object] = []
        for query in queries:
            if not isinstance(query, dict) or "page_token" in query:
                return unmatched(request, key)
            found = [i for i, rec in enumerate(recorded_queries) if rec == query]
            if not found:
                return unmatched(request, key)
            answers.append(recorded_results[found[0]])
        log.matched.append(key)
        return json_response({"results": answers})

    def derive_npm(request: httpx.Request, key: str) -> httpx.Response:
        name = unquote(str(request.url)[len(_NPM_DOWNLOADS) :])
        if "," in name or name not in bulk:
            return unmatched(request, key)
        log.matched.append(key)
        return json_response(bulk[name])

    def handler(request: httpx.Request) -> httpx.Response:
        key = key_of(request)
        entry = index.get(key)
        if entry is not None:
            log.matched.append(key)
            return json_response(
                entry.response_body,
                entry.status,
                content_type=entry.content_type,
                retry_after=entry.retry_after,
            )
        url = str(request.url)
        if request.method == "POST" and url == _OSV_URL:
            return derive_osv(request, key)
        if request.method == "GET" and url.startswith(_NPM_DOWNLOADS):
            return derive_npm(request, key)
        return unmatched(request, key)

    return httpx.MockTransport(handler), log


# --------------------------------------------------------------------------------- builders


def make_source_result(signals: Signals, *, warnings: Iterable[SourceWarning] = ()) -> SourceResult:
    """A ``SourceResult`` for ``signals`` with all 11 evidence keys empty."""
    return SourceResult(
        input_purl=signals.purl,
        signals=signals,
        error=None,
        evidence={key: Evidence(None, None, None) for key in EVIDENCE_KEYS},
        warnings=tuple(warnings),
    )


def shape(value: object) -> object:
    """The key/type skeleton of a JSON value.

    Objects map each key to its shape; arrays to the shape of the first element or
    ``"empty"``; scalars to their JSON type name (``string``, ``number``, ``boolean``,
    ``null``).
    """
    if isinstance(value, dict):
        return {key: shape(item) for key, item in value.items()}
    if isinstance(value, list):
        return shape(value[0]) if value else "empty"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str):
        return "string"
    raise TypeError(f"not a JSON value: {type(value).__name__}")
