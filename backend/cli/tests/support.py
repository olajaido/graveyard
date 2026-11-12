"""Test support for the CLI suite (design §9.3, §9.4; CLI-TEST-5, CLI-TEST-11).

* ``make_stub_syft`` writes an executable Python script that stands in for Syft.
* ``subset_replay_transport`` replays the recorded cassette and derives the two single-package
  requests that cannot have a recording from the recorded batch answers. It reads only the
  recorded JSON, never the parsers under test.
* ``version_agnostic_osv`` and ``single_repo_github`` wrap that transport for the
  ``check-install`` end-to-end tests (KPW-TEST-7, KPW-TEST-8).
* ``make_source_result``, ``FakeClock`` and ``shape`` are small builders for the other tests.

Not part of the ``cli`` wheel (it lives under ``tests/``). No network, no environment reads.
"""

from __future__ import annotations

import json
import stat
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Final, Literal
from urllib.parse import unquote

import httpx

from cli.args import GateClass
from cli.env import CliEnvironment
from cli.errors import ExitCode
from cli.gate import evaluate, unverified_sources
from cli.model import CliWarning, InputMode, Report, Row
from cli.why import why
from core.graph import GraphNode, GraphWarning
from core.scoring import score_package, sort_results
from core.scoring.tests.test_anchors import signals_from_fixture
from core.scoring.types import Signals
from core.sources.cassette import Cassette, CassetteEntry, thaw_json
from core.sources.model import (
    EVIDENCE_KEYS,
    Evidence,
    ItemError,
    SourceResult,
    SourceStats,
    SourceWarning,
)
from core.sources.tests import recorded as rec
from sources.tests.clock import FakeClock
from sources.tests.transports import ReplayLog, UnmatchedRequest, json_response, key_of

__all__ = [
    "DEFAULT_SBOM_DIR",
    "FakeClock",
    "OsvAgnosticUse",
    "ReplayLog",
    "StubSyft",
    "anchor_signals",
    "make_env",
    "make_report",
    "make_source_result",
    "make_stub_syft",
    "recorded_github",
    "shape",
    "single_repo_github",
    "subset_replay_transport",
    "version_agnostic_osv",
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
VERSION_LOG_PATH = {version_log_path!r}
VERSION = {version!r}
MODE = {mode!r}
SENTINEL = {sentinel!r}

args = sys.argv[1:]
SYFT_ENV = {{k: v for k, v in os.environ.items() if k.startswith("SYFT_")}}
if args == ["--version"]:
    with open(VERSION_LOG_PATH, "a", encoding="utf-8") as log:
        log.write(json.dumps({{"syft_env": SYFT_ENV}}) + "\\n")
    sys.stdout.write("syft " + VERSION + "\\n")
    sys.exit(0)

with open(LOG_PATH, "a", encoding="utf-8") as log:
    entry = {{"argv": args, "env_keys": sorted(os.environ), "syft_env": SYFT_ENV}}
    log.write(json.dumps(entry) + "\\n")

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
    version_log_path: Path

    def version_calls(self) -> list[dict[str, str]]:
        """The ``SYFT_*`` variables seen by every ``--version`` call."""
        if not self.version_log_path.exists():
            return []
        out: list[dict[str, str]] = []
        for line in self.version_log_path.read_text(encoding="utf-8").splitlines():
            loaded = json.loads(line)
            out.append(dict(loaded["syft_env"]))
        return out

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
    version_log_path = tmp_path / "syft-version-calls.log"
    path.write_text(
        _STUB_TEMPLATE.format(
            python=sys.executable,
            sbom_dir=str(sbom_dir),
            log_path=str(log_path),
            version_log_path=str(version_log_path),
            version=version,
            mode=mode,
            sentinel=STUB_STDERR_SENTINEL,
        ),
        encoding="utf-8",
    )
    path.chmod(0o755)
    assert path.stat().st_mode & stat.S_IXUSR
    return StubSyft(path=path, log_path=log_path, version_log_path=version_log_path)


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
        names = unquote(str(request.url)[len(_NPM_DOWNLOADS) :]).split(",")
        if not all(name in bulk for name in names):
            return unmatched(request, key)
        log.matched.append(key)
        # one name: the flat single-name document; several: a subset of the recorded bulk one
        if len(names) == 1:
            return json_response(bulk[names[0]])
        return json_response({name: bulk[name] for name in names})

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


# ------------------------------------------------------------- version-agnostic OSV (KPW-TEST-8)


@dataclass
class OsvAgnosticUse:
    """What the version-agnostic OSV wrapper did.

    ``rewritten`` holds one ``(package name, asked version, recorded version)`` entry per
    query that was answered with the recorded answer of another version.
    """

    rewritten: list[tuple[str, str, str]]

    @property
    def uses(self) -> int:
        return len(self.rewritten)


def version_agnostic_osv(
    inner: httpx.MockTransport, cassette: Cassette
) -> tuple[httpx.MockTransport, OsvAgnosticUse]:
    """Wrap ``inner`` so an OSV query for a recorded package at another version works.

    Test-only (KPW-TEST-8): the cassette records OSV answers for the recorded versions only,
    while an unpinned ``npm install express`` resolves to ``express@5.3.0``. A query whose
    ecosystem and name match a recorded query but whose version differs is rewritten to the
    recorded query, so ``inner`` answers it with that package's recorded answer. Exact
    matches, unknown packages and paginated queries pass through untouched. The cassette is
    never edited. The returned ``OsvAgnosticUse`` counts the rewrites.
    """
    osv = _recorded_osv(cassette)
    exact = [q for q in (osv[0] if osv else ()) if isinstance(q, dict)]
    recorded: dict[tuple[str, str], dict[str, Any]] = {}
    for query in exact:
        package = query.get("package")
        if isinstance(package, dict):
            ident = (str(package.get("ecosystem")), str(package.get("name")))
            recorded.setdefault(ident, query)
    use = OsvAgnosticUse(rewritten=[])

    def rewrite(query: object) -> object:
        if not isinstance(query, dict) or "page_token" in query or query in exact:
            return query
        package = query.get("package")
        if not isinstance(package, dict):
            return query
        match = recorded.get((str(package.get("ecosystem")), str(package.get("name"))))
        if match is None:
            return query
        use.rewritten.append(
            (str(package.get("name")), str(query.get("version")), str(match.get("version")))
        )
        return match

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and str(request.url) == _OSV_URL:
            try:
                body = json.loads(request.content)
            except ValueError:
                body = None
            queries = body.get("queries") if isinstance(body, dict) else None
            if isinstance(queries, list):
                request = httpx.Request(
                    "POST", request.url, json={"queries": [rewrite(q) for q in queries]}
                )
        answer = inner.handler(request)
        assert isinstance(answer, httpx.Response)  # subset_replay_transport's handler is sync
        return answer

    return httpx.MockTransport(handler), use


# ------------------------------------------------------- single-repository GitHub (KPW-TEST-7)

_GRAPHQL: Final = "https://api.github.com/graphql"


def recorded_github(cassette: Cassette) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """The variables and ``data`` of the recorded GitHub batch (read as plain JSON)."""
    for item in cassette.entries:
        if item.method == "POST" and item.url == _GRAPHQL:
            request = thaw_json(item.request_body)
            response = thaw_json(item.response_body)
            if isinstance(request, dict) and isinstance(response, dict):
                variables, data = request.get("variables"), response.get("data")
                if isinstance(variables, dict) and isinstance(data, dict):
                    return variables, data
    return None


def single_repo_github(
    inner: httpx.MockTransport, log: ReplayLog, cassette: Cassette
) -> httpx.MockTransport:
    """Answer a one-repository GitHub query from the recorded seven-repository batch.

    A single ``check-install`` target sends a one-repo GraphQL body, which has no recording
    (same reason as the single-query OSV body, design §9.4). When ``owner/name`` is one of the
    recorded repositories its recorded ``rN`` object is returned as ``r0``. Anything else is
    left to ``inner``, which logs it as unmatched. The cassette is not edited.
    """
    recorded = recorded_github(cassette)

    def handler(request: httpx.Request) -> httpx.Response:
        if recorded is not None and request.method == "POST" and str(request.url) == _GRAPHQL:
            body = json.loads(request.content)
            variables = body.get("variables") if isinstance(body, dict) else None
            if isinstance(variables, dict) and "o1" not in variables and "o0" in variables:
                rvars, data = recorded
                for index in range(len(rvars)):
                    if (rvars.get(f"o{index}"), rvars.get(f"n{index}")) == (
                        variables["o0"],
                        variables["n0"],
                    ) and f"r{index}" in data:
                        log.matched.append(f"github-single:{variables['o0']}/{variables['n0']}")
                        return json_response(
                            {"data": {"rateLimit": data["rateLimit"], "r0": data[f"r{index}"]}}
                        )
        answer = inner.handler(request)
        assert isinstance(answer, httpx.Response)  # the replay handlers are sync
        return answer

    return httpx.MockTransport(handler)


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


def anchor_signals(name: str) -> Signals:
    """The committed anchor fixture as scoring input (exposure unset)."""
    return signals_from_fixture(rec.anchor_fixture(name))


def make_env(**overrides: Any) -> CliEnvironment:
    """A ``CliEnvironment`` with no token and a plain Syft environment."""
    values: dict[str, Any] = {
        "token": None,
        "token_rejected": False,
        "contact": None,
        "syft_env": {"PATH": "/usr/bin:/bin", "SYFT_CHECK_FOR_APP_UPDATE": "false"},
        "width": 100,
    }
    values.update(overrides)
    return CliEnvironment(**values)


def make_report(
    signals_list: Sequence[Signals],
    *,
    nodes: Mapping[str, GraphNode] | None = None,
    sources: Mapping[str, SourceResult] | None = None,
    input_mode: InputMode = "purl",
    fail_on: frozenset[GateClass] = frozenset(),
    cli_warnings: Sequence[CliWarning] = (),
    item_errors: Sequence[tuple[str, ItemError]] = (),
    graph_warnings: Sequence[GraphWarning] = (),
    services: Sequence[str] = (),
    lockfiles: Sequence[tuple[str, str, bool]] = (),
    as_of: date = rec.AS_OF,
) -> Report:
    """Score ``signals_list``, rank it and wrap it in a ``Report`` (no pipeline involved)."""
    by_purl = {s.purl: s for s in signals_list}
    ordered = sort_results([score_package(s) for s in signals_list])
    rows: list[Row] = []
    for position, result in enumerate(ordered, start=1):
        source = (sources or {}).get(result.purl) or make_source_result(by_purl[result.purl])
        unverified = unverified_sources(result, by_purl[result.purl], source.warnings)
        rows.append(
            Row(
                rank=position,
                node=(nodes or {}).get(result.purl),
                source=source,
                scoring=result,
                signals=by_purl[result.purl],
                why=why(result, by_purl[result.purl], unverified),
                unverified=unverified,
            )
        )
    matches = evaluate(tuple(rows), fail_on)
    return Report(
        as_of=as_of,
        input_mode=input_mode,
        syft_version="1.56.0" if input_mode == "syft" else None,
        services=tuple(services),
        lockfiles=tuple(lockfiles),
        model_version=ordered[0].model_version if ordered else None,
        rows=tuple(rows),
        item_errors=tuple(item_errors),
        graph_warnings=tuple(graph_warnings),
        cli_warnings=tuple(cli_warnings),
        stats=SourceStats(requests={}, failures={}, cache_hits=0, cache_misses=0, s9_skipped=0),
        fail_on=fail_on,
        matches=matches,
        exit_code=ExitCode.GATE_TRIPPED if matches else ExitCode.OK,
    )


def shape(value: object) -> object:
    """The key/type skeleton of a JSON value.

    Objects map each key to its shape; arrays to the shape of the first element or
    ``"empty"``; scalars to their JSON type name (``string``, ``integer``, ``number``,
    ``boolean``, ``null``). ``bool`` is tested before ``int`` because it is a subclass of
    ``int``; ``integer`` is an ``int`` and ``number`` a ``float``.
    """
    if isinstance(value, dict):
        return {key: shape(item) for key, item in value.items()}
    if isinstance(value, list):
        return shape(value[0]) if value else "empty"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    raise TypeError(f"not a JSON value: {type(value).__name__}")
