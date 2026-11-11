"""Tests for ``cli.pipeline`` (T7.4; CLI-PIPE-1…7, CLI-PURL-4, CLI-SCOPE-2, CLI-ENV-4, D8, D19).

Network is replaced by ``httpx.MockTransport``: a transport that fails every request (sources
never raise, so every package still comes back), and the cassette replay where the real
recorded answers are needed. Syft is the stub executable.
"""

from __future__ import annotations

import asyncio
import copy
import json
import shutil
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from cli.args import Options, parse_args
from cli.env import DEFAULT_CONTACT
from cli.errors import CliError, ExitCode
from cli.model import InputMode, Report
from cli.pipeline import (
    Inputs,
    analyse,
    autopsy_requests,
    collect_inputs,
    make_config,
    merge_stats,
    rank,
)
from cli.syft import check_version
from cli.tests.support import (
    DEFAULT_SBOM_DIR,
    FakeClock,
    anchor_signals,
    make_env,
    make_source_result,
    make_stub_syft,
)
from core.graph import ExamplePath, GraphNode, build_graph
from core.scoring.types import PathInfo, Signals
from core.sources.config import Limits, RetryPolicy, SourcesConfig
from core.sources.model import ItemError, SourceResult, SourceStats
from core.sources.secret import SecretToken

HERE = Path(__file__).resolve().parent
PROJECT = HERE / "fixtures" / "anchors-project"
TODAY = date(2026, 11, 10)
START = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
NO_STATS = SourceStats(requests={}, failures={}, cache_hits=0, cache_misses=0, s9_skipped=0)


def _opts(*argv: str) -> Options:
    return parse_args(argv, today=TODAY)


class _DownTransport:
    """A transport that fails every request and remembers it."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        raise httpx.ConnectError("down", request=request)

    def osv_posts(self) -> int:
        return sum(1 for r in self.requests if r.method == "POST" and r.url.host == "api.osv.dev")


def _node(
    signals: Signals,
    infos: tuple[PathInfo, ...],
    services: int,
    manifests: tuple[str, ...] = ("web",),
) -> GraphNode:
    return GraphNode(
        key=signals.purl.removeprefix("pkg:"),
        purl=signals.purl,
        manifests=manifests,
        path_infos=infos,
        services_affected=services,
        example_paths=(ExamplePath(service=manifests[0], nodes=(signals.purl,)),),
        path_witnesses=(),
    )


def _inputs(mode: InputMode = "purl") -> Inputs:
    return Inputs(mode=mode, services=(), syft_version=None, lockfiles=(), cli_warnings=())


def _argv(call: dict[str, object]) -> list[str]:
    argv = call["argv"]
    assert isinstance(argv, list)
    return [str(a) for a in argv]


# ------------------------------------------------------------------------------------ rank


def test_rank_sets_exposure_from_the_node() -> None:
    signals = anchor_signals("request")
    infos = (PathInfo(runtime=False, direct=True),)
    node = _node(signals, infos, 1)
    report = rank(
        [node], [make_source_result(signals)], NO_STATS, None, _inputs("syft"), _opts_for(), TODAY
    )
    row = report.rows[0]
    assert row.signals.paths == infos
    assert row.signals.services_affected == 1
    assert row.scoring.exposure == pytest.approx(0.2)  # dev (0.2) x direct (1.0)
    assert row.scoring.exposure_assumed is False
    assert row.node is node


def test_rank_leaves_exposure_assumed_without_a_node() -> None:
    signals = anchor_signals("request")
    report = rank(
        [None], [make_source_result(signals)], NO_STATS, None, _inputs(), _opts_for(), TODAY
    )
    row = report.rows[0]
    assert row.signals.paths is None
    assert row.scoring.exposure_assumed is True
    assert row.scoring.exposure == 1.0


def test_exposure_changes_the_order() -> None:
    """The reason D8 exists: the same packages rank differently once the graph is used."""
    names = ["request", "left-pad", "nose"]
    signals = [anchor_signals(n) for n in names]
    results = [make_source_result(s) for s in signals]
    dev = (PathInfo(runtime=False, direct=True),)
    run = (PathInfo(runtime=True, direct=True),)
    nodes = [_node(signals[0], dev, 1), _node(signals[1], run, 1), _node(signals[2], dev, 1)]
    assumed = rank([None] * 3, results, NO_STATS, None, _inputs(), _opts_for(), TODAY)
    planned = rank(nodes, results, NO_STATS, None, _inputs("syft"), _opts_for(), TODAY)

    def order(report: Report) -> list[str]:
        return [row.scoring.purl for row in report.rows]

    assert order(assumed) != order(planned)
    assert order(planned)[0] == signals[1].purl  # left-pad, runtime and direct, ranks first


def test_item_error_is_reported_and_not_ranked() -> None:
    good = anchor_signals("six")
    bad = SourceResult(
        input_purl="pkg:npm/broken",
        signals=None,
        error=ItemError("MISSING_VERSION", "package URL has no version"),
    )
    report = rank(
        [None, None],
        [make_source_result(good), bad],
        NO_STATS,
        None,
        _inputs(),
        _opts_for("--fail-on", "dead"),
        TODAY,
    )
    assert [row.scoring.purl for row in report.rows] == [good.purl]
    assert report.item_errors == (("pkg:npm/broken", bad.error),)
    assert report.exit_code is ExitCode.OK


def test_equal_priorities_resolve_by_purl() -> None:
    a, b = anchor_signals("left-pad"), anchor_signals("node-uuid")
    results = [make_source_result(b), make_source_result(a)]  # given in the "wrong" order
    report = rank([None, None], results, NO_STATS, None, _inputs(), _opts_for(), TODAY)
    assert report.rows[0].scoring.priority == report.rows[1].scoring.priority
    assert [r.scoring.purl for r in report.rows] == sorted([a.purl, b.purl])
    assert [r.rank for r in report.rows] == [1, 2]


def test_matches_follow_fail_on() -> None:
    names = ["request", "six", "express"]
    results = [make_source_result(anchor_signals(n)) for n in names]
    for words, expected in [
        ("dead", 1),
        ("cursed", 1),
        ("ailing", 0),
        ("ailing,cursed", 1),
    ]:
        report = rank(
            [None] * 3, results, NO_STATS, None, _inputs(), _opts_for("--fail-on", words), TODAY
        )
        assert len(report.matches) == expected
        assert report.exit_code is (ExitCode.GATE_TRIPPED if expected else ExitCode.OK)
    none = rank([None] * 3, results, NO_STATS, None, _inputs(), _opts_for(), TODAY)
    assert none.matches == ()
    assert none.exit_code is ExitCode.OK


def test_cli_warnings_are_sorted_and_services_come_from_the_graph() -> None:
    from cli.model import CliWarning

    warnings = (
        CliWarning("LOCKFILE_UNREADABLE", "b", "web"),
        CliWarning("GITHUB_TOKEN_MISSING", "a", None),
    )
    inputs = Inputs("syft", (), "1.56.0", (("web", "uv.lock", False),), warnings)
    report = rank([], [], NO_STATS, None, inputs, _opts_for(), TODAY)
    assert [w.code for w in report.cli_warnings] == ["GITHUB_TOKEN_MISSING", "LOCKFILE_UNREADABLE"]
    assert report.syft_version == "1.56.0"
    assert report.lockfiles == (("web", "uv.lock", False),)
    assert report.model_version is None


def _opts_for(*extra: str) -> Options:
    return _opts("autopsy", "--purl", "pkg:npm/request@2.88.2", *extra)


# ------------------------------------------------------------------------------ merge_stats


def test_merge_stats_sums_per_source_counters() -> None:
    one = SourceStats({"osv": 1, "depsdev": 4}, {"osv": 1}, 2, 3, 1)
    two = SourceStats({"osv": 2, "github": 1}, {}, 5, 1, 0)
    merged = merge_stats([one, two])
    assert dict(merged.requests) == {"depsdev": 4, "github": 1, "osv": 3}
    assert dict(merged.failures) == {"osv": 1}
    assert (merged.cache_hits, merged.cache_misses, merged.s9_skipped) == (7, 4, 1)
    assert merge_stats([]) == NO_STATS


# ----------------------------------------------------------------------------- make_config


def test_make_config_contact_and_fallback() -> None:
    assert make_config(make_env(contact="ops@example.org")).contact == "ops@example.org"
    assert (
        make_config(make_env()).contact
        == DEFAULT_CONTACT
        == "https://github.com/olajaido/graveyard"
    )
    assert make_config(make_env(contact="bad\x00contact")).contact == DEFAULT_CONTACT
    assert make_config(make_env(contact="   ")).contact == DEFAULT_CONTACT


# --------------------------------------------------------------------------------- chunking


def test_requests_are_collected_in_chunks_in_one_session_and_keep_their_order() -> None:
    names = [
        "request",
        "node-uuid",
        "left-pad",
        "express",
        "uuid",
        "moment",
        "pycrypto",
        "nose",
        "six",
    ]
    requests = [(anchor_signals(n).purl, TODAY) for n in names]
    base = SourcesConfig.default(contact="ops@example.org")
    config = SourcesConfig(
        hosts=base.hosts,
        contact=base.contact,
        retry=RetryPolicy(max_attempts=1),
        limits=Limits(max_packages_per_call=2),
    )
    down = _DownTransport()
    results, stats = asyncio.run(
        autopsy_requests(requests, make_env(), down.transport, FakeClock(START), config=config)
    )
    assert [r.input_purl for r in results] == [purl for purl, _ in requests]
    assert down.osv_posts() == 5  # ceil(9 / 2) collect calls, one OSV batch each
    assert stats.requests["osv"] == 5


# ------------------------------------------------------------------------------- analyse


def test_purl_mode_never_touches_syft_and_defaults_as_of_to_the_clock() -> None:
    down = _DownTransport()
    opts = _opts("autopsy", "--purl", "pkg:npm/request@2.88.2", "--syft", "/nonexistent/syft")
    report = analyse(opts, make_env(), down.transport, FakeClock(START))
    assert report.input_mode == "purl"
    assert report.services == ()
    assert report.syft_version is None
    assert report.as_of == date(2026, 11, 10)
    assert [r.scoring.purl for r in report.rows] == ["pkg:npm/request@2.88.2"]
    assert report.rows[0].node is None
    assert report.rows[0].scoring.exposure_assumed is True


def test_as_of_option_overrides_the_clock() -> None:
    down = _DownTransport()
    opts = _opts("autopsy", "--purl", "pkg:npm/request@2.88.2", "--as-of", "2026-11-03")
    report = analyse(opts, make_env(), down.transport, FakeClock(START))
    assert report.as_of == date(2026, 11, 3)


def test_token_warnings() -> None:
    opts = _opts("autopsy", "--purl", "pkg:npm/request@2.88.2")
    codes = {}
    for label, env in [
        ("missing", make_env()),
        ("invalid", make_env(token_rejected=True)),
        ("present", make_env(token=SecretToken("a-valid-looking-token"))),
    ]:
        report = analyse(opts, env, _DownTransport().transport, FakeClock(START))
        codes[label] = [w.code for w in report.cli_warnings]
    assert codes == {
        "missing": ["GITHUB_TOKEN_MISSING"],
        "invalid": ["GITHUB_TOKEN_INVALID"],
        "present": [],
    }


def test_a_bad_cyclonedx_document_is_an_input_error(tmp_path: Path) -> None:
    sbom = tmp_path / "bad.json"
    sbom.write_text('{"bomFormat": "CycloneDX", "specVersion": "9.9"}', encoding="utf-8")
    opts = _opts("autopsy", str(tmp_path), "--sbom", str(sbom))
    with pytest.raises(CliError) as caught:
        analyse(opts, make_env(), _DownTransport().transport, FakeClock(START))
    assert caught.value.message.startswith("the input is not a usable SBOM: ")
    assert "\n" not in caught.value.message


# ---------------------------------------------------------------------------- collect_inputs


def test_syft_mode_two_services_scopes_and_one_version_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = make_stub_syft(tmp_path)
    checks: list[str] = []
    real = check_version

    def counting(exe: str, syft_env: Mapping[str, str]) -> str:
        checks.append(exe)
        return real(exe, syft_env)

    monkeypatch.setattr("cli.pipeline.check_version", counting)
    opts = _opts("autopsy", str(PROJECT), "--syft", str(stub.path))
    inputs = collect_inputs(opts, make_env())
    assert len(checks) == 1
    assert inputs.mode == "syft"
    assert inputs.syft_version == "1.56.0"
    assert [s.path for s in inputs.services] == ["api", "web"]
    assert all(s.scopes is not None for s in inputs.services)
    assert inputs.lockfiles == (("api", "uv.lock", True), ("web", "package-lock.json", True))
    assert inputs.cli_warnings == ()
    # no nested services, so no --exclude
    for call in stub.calls():
        assert "--exclude" not in _argv(call)
    assert build_graph(inputs.services).warnings == ()


def test_nested_services_are_excluded_from_their_parent(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    (project / "web" / "sub").mkdir(parents=True)
    (project / "web" / "package-lock.json").write_text("{}", encoding="utf-8")
    (project / "web" / "sub" / "requirements.txt").write_text("six==1.17.0\n", encoding="utf-8")
    sboms = tmp_path / "sboms"
    sboms.mkdir()
    shutil.copy(DEFAULT_SBOM_DIR / "web.cdx.json", sboms / "web.cdx.json")
    shutil.copy(DEFAULT_SBOM_DIR / "api.cdx.json", sboms / "sub.cdx.json")
    stub = make_stub_syft(tmp_path, sbom_dir=sboms)
    collect_inputs(_opts("autopsy", str(project), "--syft", str(stub.path)), make_env())
    argvs = {_argv(call)[0].rsplit("/", 1)[-1]: _argv(call) for call in stub.calls()}
    assert argvs["web"][4:] == ["--exclude", "./sub/**"]
    assert argvs["sub"][4:] == []


def test_a_failing_service_is_fatal_and_later_services_are_not_run(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    for name in ("a", "b", "c"):
        (project / name).mkdir(parents=True)
        (project / name / "requirements.txt").write_text("six==1.17.0\n", encoding="utf-8")
    sboms = tmp_path / "sboms"
    sboms.mkdir()
    for name in ("a", "c"):  # "b" has no SBOM, so the stub exits non-zero for it
        shutil.copy(DEFAULT_SBOM_DIR / "api.cdx.json", sboms / f"{name}.cdx.json")
    stub = make_stub_syft(tmp_path, sbom_dir=sboms)
    with pytest.raises(CliError) as caught:
        collect_inputs(_opts("autopsy", str(project), "--syft", str(stub.path)), make_env())
    assert "'b'" in caught.value.message
    assert len(stub.calls()) == 2  # a, then b; c never ran


def test_an_unreadable_lockfile_is_a_warning_and_the_run_continues(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    (project / "api").mkdir(parents=True)
    (project / "api" / "uv.lock").write_text("this is [[ not toml", encoding="utf-8")
    sboms = tmp_path / "sboms"
    sboms.mkdir()
    shutil.copy(DEFAULT_SBOM_DIR / "api.cdx.json", sboms / "api.cdx.json")
    stub = make_stub_syft(tmp_path, sbom_dir=sboms)
    inputs = collect_inputs(_opts("autopsy", str(project), "--syft", str(stub.path)), make_env())
    assert [w.code for w in inputs.cli_warnings] == ["LOCKFILE_UNREADABLE"]
    assert inputs.cli_warnings[0].service == "api"
    assert inputs.services[0].scopes is None
    assert inputs.lockfiles == (("api", "uv.lock", False),)
    graph_codes = {w.code for w in build_graph(inputs.services).warnings}
    assert "SCOPE_ASSUMED" in graph_codes


def test_syft_mode_without_lockfiles_is_an_input_error(tmp_path: Path) -> None:
    with pytest.raises(CliError) as caught:
        collect_inputs(_opts("autopsy", str(tmp_path)), make_env())
    assert "--sbom" in caught.value.message


def test_sbom_mode_is_one_service_and_assumes_scopes_without_lockfiles() -> None:
    sbom = DEFAULT_SBOM_DIR / "api.cdx.json"
    inputs = collect_inputs(_opts("autopsy", str(PROJECT), "--sbom", str(sbom)), make_env())
    assert inputs.mode == "sbom"
    assert inputs.syft_version is None
    assert [s.path for s in inputs.services] == ["."]
    assert inputs.services[0].scopes is None  # the project root has no lockfile of its own
    assert inputs.lockfiles == ()
    codes = {w.code for w in build_graph(inputs.services).warnings}
    assert codes == {"SCOPE_ASSUMED"}


def test_sbom_mode_reads_lockfiles_directly_in_path_only(tmp_path: Path) -> None:
    shutil.copy(PROJECT / "api" / "uv.lock", tmp_path / "uv.lock")
    (tmp_path / "web").mkdir()
    shutil.copy(PROJECT / "web" / "package-lock.json", tmp_path / "web" / "package-lock.json")
    sbom = DEFAULT_SBOM_DIR / "api.cdx.json"
    inputs = collect_inputs(_opts("autopsy", str(tmp_path), "--sbom", str(sbom)), make_env())
    assert inputs.lockfiles == ((".", "uv.lock", True),)  # web/ is not looked at
    assert inputs.services[0].scopes is not None


def test_collect_inputs_refuses_purl_mode() -> None:
    with pytest.raises(ValueError):
        collect_inputs(_opts("autopsy", "--purl", "pkg:npm/request@2.88.2"), make_env())


# --------------------------------------------------- T12.7: direct edges from the lockfiles


def _without_root_edge(document: dict[str, Any], ref_prefix: str) -> dict[str, Any]:
    """The document as real Syft writes it: the root does not link to the dev direct."""
    out = copy.deepcopy(document)
    root_prefixes = ("pkg:npm/anchors-web@", "pkg:pypi/anchors-api@")
    for entry in out["dependencies"]:
        if entry["ref"].startswith(root_prefixes):
            entry["dependsOn"] = [t for t in entry["dependsOn"] if not t.startswith(ref_prefix)]
    return out


def _real_shaped_sboms(tmp_path: Path) -> Path:
    """A directory of SBOMs where request and nose are not linked to their roots."""
    sboms = tmp_path / "sboms"
    sboms.mkdir()
    for service, prefix in (("web", "pkg:npm/request@"), ("api", "pkg:pypi/nose@")):
        document = json.loads((DEFAULT_SBOM_DIR / f"{service}.cdx.json").read_text("utf-8"))
        (sboms / f"{service}.cdx.json").write_text(
            json.dumps(_without_root_edge(document, prefix)), encoding="utf-8"
        )
    return sboms


def test_project_mode_adds_the_dev_edges_the_sbom_lacks(tmp_path: Path) -> None:
    stub = make_stub_syft(tmp_path, sbom_dir=_real_shaped_sboms(tmp_path))
    inputs = collect_inputs(_opts("autopsy", str(PROJECT), "--syft", str(stub.path)), make_env())
    assert inputs.direct_edges_added == 2  # request (web) and nose (api)
    assert [w.code for w in inputs.cli_warnings] == []  # added edges are not warnings
    graph = build_graph(inputs.services)
    assert graph.warnings == ()
    request, nose = graph.node("npm/request@2.88.2"), graph.node("pypi/nose@1.3.7")
    assert request is not None and nose is not None
    assert [(p.runtime, p.direct) for p in request.path_infos] == [(False, True)]
    assert [(p.runtime, p.direct) for p in nose.path_infos] == [(False, True)]
    uuid = graph.node("npm/uuid@3.4.0")
    assert uuid is not None
    assert [(p.runtime, p.direct) for p in uuid.path_infos] == [(False, False)]


def test_a_declared_direct_with_no_component_is_one_warning_per_service(tmp_path: Path) -> None:
    sboms = tmp_path / "sboms"
    sboms.mkdir()
    web = json.loads((DEFAULT_SBOM_DIR / "web.cdx.json").read_text("utf-8"))
    gone = [c["bom-ref"] for c in web["components"] if c.get("name") == "moment"]
    assert gone
    web["components"] = [c for c in web["components"] if c["bom-ref"] not in gone]
    for entry in web["dependencies"]:
        entry["dependsOn"] = [t for t in entry.get("dependsOn", []) if t not in gone]
    (sboms / "web.cdx.json").write_text(json.dumps(web), encoding="utf-8")
    shutil.copy(DEFAULT_SBOM_DIR / "api.cdx.json", sboms / "api.cdx.json")
    stub = make_stub_syft(tmp_path, sbom_dir=sboms)
    inputs = collect_inputs(_opts("autopsy", str(PROJECT), "--syft", str(stub.path)), make_env())
    [warning] = [w for w in inputs.cli_warnings if w.code == "DIRECT_NOT_IN_SBOM"]
    assert warning.service == "web"
    assert warning.subjects == ("npm/moment@2.29.1",)
    assert warning.detail == (
        "1 direct dependency declared in the lockfile has no component in the SBOM; not analysed"
    )


def test_sbom_mode_adds_edges_when_lockfiles_are_in_path(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    shutil.copy(PROJECT / "api" / "uv.lock", project / "uv.lock")
    sbom = _real_shaped_sboms(tmp_path) / "api.cdx.json"
    inputs = collect_inputs(_opts("autopsy", str(project), "--sbom", str(sbom)), make_env())
    assert inputs.lockfiles == ((".", "uv.lock", True),)
    assert inputs.direct_edges_added == 1  # nose
    assert build_graph(inputs.services).warnings == ()


def test_sbom_mode_without_lockfiles_adds_nothing(tmp_path: Path) -> None:
    sbom = _real_shaped_sboms(tmp_path) / "api.cdx.json"
    empty = tmp_path / "empty"
    empty.mkdir()
    inputs = collect_inputs(_opts("autopsy", str(empty), "--sbom", str(sbom)), make_env())
    assert inputs.direct_edges_added == 0
    assert inputs.cli_warnings == ()
    assert inputs.services[0].scopes is None


def test_the_count_reaches_the_report_and_purl_mode_has_none(tmp_path: Path) -> None:
    stub = make_stub_syft(tmp_path, sbom_dir=_real_shaped_sboms(tmp_path))
    down = _DownTransport()
    report = analyse(
        _opts("autopsy", str(PROJECT), "--syft", str(stub.path)),
        make_env(),
        down.transport,
        FakeClock(START),
    )
    assert report.direct_edges_added == 2
    purl_report = analyse(_opts_for(), make_env(), _DownTransport().transport, FakeClock(START))
    assert purl_report.direct_edges_added == 0
