"""End-to-end tests of ``graveyard autopsy PATH`` (T9; CLI-TEST-3, CLI-TEST-4, CLI-TEST-7,
CLI-SEC-5, CLI-JSON-8).

Each run goes through ``app.run`` with a real stub Syft executable, the hand-built fixture
project (two services holding the nine anchor packages) and the recorded cassette replayed by
``httpx.MockTransport``. No network. Every run asserts ``log.unmatched == []`` so a request
the cassette cannot answer fails loudly instead of degrading silently.

The expected states, the rank order and the exposure figures below are written out as
literals; they are not read from the scoring code. The order comes from design §9.2.
"""

from __future__ import annotations

import io
import json
import re
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from cli.app import run
from cli.tests.support import (
    FakeClock,
    StubMode,
    StubSyft,
    make_env,
    make_stub_syft,
    subset_replay_transport,
)
from core.sources.model import EVIDENCE_KEYS
from core.sources.secret import SecretToken
from core.sources.tests import recorded as rec
from sources.tests.transports import ReplayLog, replay_transport

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PROJECT = FIXTURES / "anchors-project"
WEB_SBOM = FIXTURES / "sboms" / "web.cdx.json"
API_SBOM = FIXTURES / "sboms" / "api.cdx.json"
SENTINEL = "e2e-sentinel-4f1c9a"
CLOCK_START = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)

PURLS = {
    "request": "pkg:npm/request@2.88.2",
    "node-uuid": "pkg:npm/node-uuid@1.4.8",
    "left-pad": "pkg:npm/left-pad@1.3.0",
    "express": "pkg:npm/express@4.17.1",
    "uuid": "pkg:npm/uuid@3.4.0",
    "moment": "pkg:npm/moment@2.29.1",
    "pycrypto": "pkg:pypi/pycrypto@2.6.1",
    "nose": "pkg:pypi/nose@1.3.7",
    "six": "pkg:pypi/six@1.17.0",
}

# MM-ANC-1…9: name -> (state, dead_reason, cursed, wounded)
MM_ANC = {
    "request": ("Dead", "declared", True, False),
    "node-uuid": ("Dead", "declared", False, False),
    "left-pad": ("Dead", "declared", False, False),
    "express": ("Alive", None, False, True),
    "uuid": ("Alive", None, False, True),
    "moment": ("Alive", None, False, True),
    "pycrypto": ("Dead", "score", True, False),
    "nose": ("Dead", "score", False, False),
    "six": ("Resting", None, False, False),
}

# Design §9.2: the rank order once the graph sets the exposure.
PLANNED_ORDER = [
    "pycrypto",
    "left-pad",
    "request",
    "node-uuid",
    "nose",
    "six",
    "uuid",
    "moment",
    "express",
]
# The same packages with exposure assumed (what the order would be if D8 were not applied).
ASSUMED_ORDER = [
    "pycrypto",
    "request",
    "nose",
    "left-pad",
    "node-uuid",
    "six",
    "uuid",
    "moment",
    "express",
]
DEAD_IN_RANK_ORDER = ["pycrypto", "left-pad", "request", "node-uuid", "nose"]

# Design §9.2: name -> (services_affected, direct, scope)
GRAPH_FIELDS = {
    "pycrypto": (1, True, "runtime"),
    "left-pad": (1, True, "runtime"),
    "request": (1, True, "dev"),
    "node-uuid": (1, False, "runtime"),
    "nose": (1, True, "dev"),
    "six": (1, True, "runtime"),
    "uuid": (1, False, "dev"),
    "moment": (1, True, "runtime"),
    "express": (1, True, "runtime"),
}


@dataclass(frozen=True)
class Run:
    code: int
    out: str
    err: str
    json_path: Path
    log: ReplayLog
    stub: StubSyft

    @property
    def json_text(self) -> str:
        return self.json_path.read_text(encoding="utf-8")

    @property
    def report(self) -> dict[str, Any]:
        loaded = json.loads(self.json_text)
        assert isinstance(loaded, dict)
        return loaded

    def purls(self) -> list[str]:
        return [package["purl"] for package in self.report["packages"]]

    def names(self) -> list[str]:
        by_purl = {purl: name for name, purl in PURLS.items()}
        return [by_purl[purl] for purl in self.purls()]

    def dir_calls(self) -> list[dict[str, object]]:
        calls = self.stub.calls()
        return [c for c in calls if any(str(a).startswith("dir:") for a in _argv(c))]


def run_cli(
    root: Path,
    label: str,
    *extra: str,
    project: Path = PROJECT,
    token: bool = True,
    mode: StubMode = "ok",
    subset: bool = False,
    width: int = 100,
) -> Run:
    work = root / label
    work.mkdir()
    stub = make_stub_syft(work, mode=mode)
    json_path = work / "report.json"
    # The exact cassette answers the nine-package run as recorded. Runs over fewer packages send
    # smaller OSV bodies, so those use the derived transport (no token: no GitHub request).
    transport, log = (
        subset_replay_transport(rec.cassette()) if subset else replay_transport(rec.cassette())
    )
    out, err = io.StringIO(), io.StringIO()
    code = run(
        [
            "autopsy",
            str(project),
            "--syft",
            str(stub.path),
            "--as-of",
            "2026-11-03",
            "--json",
            str(json_path),
            "--all",
            *extra,
        ],
        env=make_env(token=SecretToken(SENTINEL) if token else None, width=width),
        out=out,
        err=err,
        transport=transport,
        clock=FakeClock(CLOCK_START),
    )
    return Run(code, out.getvalue(), err.getvalue(), json_path, log, stub)


def _argv(call: dict[str, object]) -> list[str]:
    argv = call["argv"]
    assert isinstance(argv, list)
    return [str(a) for a in argv]


def table_purls(out: str) -> list[str]:
    """The purls in the order the table lists them."""
    found: list[str] = []
    for line in out.splitlines()[1:]:
        if not line.strip():
            break
        match = re.search(r"\b(npm|pypi) (\S+)@(\S+)", line)
        assert match is not None, line
        found.append(f"pkg:{match.group(1)}/{match.group(2)}@{match.group(3)}")
    return found


@pytest.fixture(scope="module")
def main(tmp_path_factory: pytest.TempPathFactory) -> Run:
    return run_cli(tmp_path_factory.mktemp("main"), "run")


# ------------------------------------------------------------------ T9.2: the main scenario


def test_main_run_exits_zero_and_replays_only_recorded_requests(main: Run) -> None:
    assert main.code == 0
    assert main.log.unmatched == []
    assert len(main.dir_calls()) == 2
    assert main.err == ""  # a token is set, nothing degraded, no gate asked for


def test_the_nine_states_dead_reasons_and_overlays(main: Run) -> None:
    packages = {p["purl"]: p for p in main.report["packages"]}
    assert set(packages) == set(PURLS.values())
    for name, (state, reason, cursed, wounded) in MM_ANC.items():
        package = packages[PURLS[name]]
        assert (
            package["state"],
            package["dead_reason"],
            package["cursed"],
            package["wounded"],
        ) == (state, reason, cursed, wounded), name


def test_rank_order_is_the_planned_one_and_differs_from_the_assumed_one(main: Run) -> None:
    assert main.names() == PLANNED_ORDER
    assert main.names() != ASSUMED_ORDER  # the order would not move if exposure were not plumbed
    assert [p["rank"] for p in main.report["packages"]] == list(range(1, 10))


def test_exposure_is_set_from_the_graph_for_every_package(main: Run) -> None:
    for package in main.report["packages"]:
        assert package["exposure_assumed"] is False, package["purl"]
    by_name = dict(zip(main.names(), main.report["packages"], strict=True))
    for name, (services, direct, scope) in GRAPH_FIELDS.items():
        package = by_name[name]
        assert (package["services_affected"], package["direct"], package["scope"]) == (
            services,
            direct,
            scope,
        ), name
    # the figures behind the order: dev x direct = 0.2, runtime x transitive = 0.6
    assert by_name["request"]["exposure"] == pytest.approx(0.2)
    assert by_name["node-uuid"]["exposure"] == pytest.approx(0.6)
    assert by_name["pycrypto"]["exposure"] == pytest.approx(1.0)
    assert by_name["uuid"]["exposure"] == pytest.approx(0.12)


def test_manifests_and_example_paths(main: Run) -> None:
    by_name = dict(zip(main.names(), main.report["packages"], strict=True))
    assert by_name["request"]["manifests"] == ["web"]
    assert by_name["pycrypto"]["manifests"] == ["api"]
    assert by_name["uuid"]["example_paths"][0]["service"] == "web"
    assert len(by_name["uuid"]["example_paths"][0]["nodes"]) == 2  # request -> uuid


def test_table_and_json_list_the_same_packages_in_the_same_order(main: Run) -> None:
    assert table_purls(main.out) == main.purls()


def test_input_block(main: Run) -> None:
    assert main.report["input"] == {
        "mode": "syft",
        "syft_version": "1.56.0",
        "services": ["api", "web"],
        "lockfiles": [
            {"service": "api", "file": "uv.lock", "used": True},
            {"service": "web", "file": "package-lock.json", "used": True},
        ],
    }


def test_summary_counts(main: Run) -> None:
    summary = main.report["summary"]
    assert summary["packages"] == 9
    assert summary["states"] == {"Dead": 5, "Unknown": 0, "Resting": 1, "Ailing": 0, "Alive": 3}
    assert (summary["cursed"], summary["wounded"], summary["item_errors"]) == (2, 3, 0)
    assert summary["degraded"] is False
    assert summary["gate"] == {"fail_on": [], "tripped": False, "matches": []}
    assert summary["exit_code"] == 0
    assert main.report["errors"] == []
    assert main.report["warnings"] == []


def test_every_package_has_the_eleven_evidence_keys(main: Run) -> None:
    for package in main.report["packages"]:
        assert list(package["evidence"]) == list(EVIDENCE_KEYS)
        assert len(package["evidence"]) == 11


def test_a_signal_is_traceable_to_a_link_and_a_time(main: Run) -> None:
    pycrypto = next(p for p in main.report["packages"] if p["purl"] == PURLS["pycrypto"])
    release = pycrypto["evidence"]["s2_latest_release_at"]
    assert release["value"] == "2014-06-20"
    assert release["source_url"].startswith("https://")
    assert release["fetched_at"] == "2026-11-10T09:00:00+00:00"


def test_no_absolute_path_and_no_token_anywhere(main: Run) -> None:
    text = main.json_text
    assert "/Users/" not in text
    assert "/home/" not in text
    assert "/private/var" not in text

    def strings(node: Any) -> Iterator[str]:
        if isinstance(node, str):
            yield node
        elif isinstance(node, dict):
            for key, value in node.items():
                yield key
                yield from strings(value)
        elif isinstance(node, list):
            for item in node:
                yield from strings(item)

    assert not [s for s in strings(main.report) if s.startswith("/")]
    for stream in (main.out, main.err, text):  # CLI-SEC-5
        assert SENTINEL not in stream


# ------------------------------------------------------------------------ T9.3: the gate


@pytest.mark.parametrize(
    ("fail_on", "code", "matches"),
    [
        ("dead", 1, DEAD_IN_RANK_ORDER),
        ("cursed", 1, ["pycrypto", "request"]),
        ("ailing", 0, []),
        ("ailing,cursed", 1, ["pycrypto", "request"]),
        ("dead,cursed,ailing", 1, DEAD_IN_RANK_ORDER),
    ],
)
def test_gate_matrix(tmp_path: Path, fail_on: str, code: int, matches: list[str]) -> None:
    result = run_cli(tmp_path, "gate", "--fail-on", fail_on)
    assert result.log.unmatched == []
    assert result.code == code
    gate = result.report["summary"]["gate"]
    assert gate["tripped"] is bool(matches)
    assert gate["matches"] == [PURLS[name] for name in matches]
    assert gate["fail_on"] == sorted(fail_on.split(","))
    assert result.report["summary"]["exit_code"] == code
    if matches:
        count = len(matches)
        noun = "package matches" if count == 1 else "packages match"
        assert f"gate: {count} {noun} --fail-on " in result.err
        listed = result.err.splitlines()[0].split(": ", 2)[2]
        assert listed.split(", ") == [PURLS[name] for name in matches]
    else:
        assert "gate:" not in result.err


def test_no_fail_on_never_trips(main: Run) -> None:
    assert main.code == 0
    assert main.report["summary"]["gate"]["tripped"] is False


# --------------------------------------------------------------------- T9.4: the variants


def test_sbom_mode_with_the_web_document_and_its_lockfile(tmp_path: Path) -> None:
    """CLI-TEST-4a: `--sbom` with `PATH` the web service, which holds a package-lock.json."""
    result = run_cli(
        tmp_path, "sbom", "--sbom", str(WEB_SBOM), project=PROJECT / "web", token=False, subset=True
    )
    assert result.log.unmatched == []
    assert result.code == 0
    assert result.stub.calls() == []  # Syft is never run with --sbom
    report = result.report
    assert report["input"] == {
        "mode": "sbom",
        "syft_version": None,
        "services": ["."],
        "lockfiles": [{"service": ".", "file": "package-lock.json", "used": True}],
    }
    npm = {name: PURLS[name] for name in PURLS if PURLS[name].startswith("pkg:npm/")}
    states = {
        p["purl"]: (p["state"], p["dead_reason"], p["cursed"], p["wounded"])
        for p in report["packages"]
    }
    assert states == {purl: MM_ANC[name] for name, purl in npm.items()}
    by_name = dict(zip(result.names(), report["packages"], strict=True))
    assert by_name["request"]["scope"] == "dev"  # the lockfile says so, via the added edge
    assert by_name["uuid"]["scope"] == "dev"
    assert by_name["express"]["scope"] == "runtime"
    assert report["summary"]["stats"]["direct_edges_added"] == 1  # request
    assert not any(w["origin"] == "graph" for w in report["warnings"])


def test_sbom_mode_without_a_lockfile_assumes_scopes_and_leaves_nose_unreachable(
    tmp_path: Path,
) -> None:
    empty = tmp_path / "no-lockfile"
    empty.mkdir()
    result = run_cli(
        tmp_path, "sbom2", "--sbom", str(API_SBOM), project=empty, token=False, subset=True
    )
    assert result.log.unmatched == []
    assert result.code == 0
    report = result.report
    assert report["input"]["lockfiles"] == []
    assert [w["code"] for w in report["warnings"] if w["origin"] == "graph"] == ["SCOPE_ASSUMED"]
    by_name = dict(zip(result.names(), report["packages"], strict=True))
    assert by_name["pycrypto"]["scope"] == "runtime"
    nose = by_name["nose"]  # listed by Syft, linked from nowhere, and no lockfile to say more
    assert nose["path_infos"] == []
    assert nose["exposure_assumed"] is True
    assert report["summary"]["stats"]["direct_edges_added"] == 0


def test_no_token_degrades_but_works(main: Run, tmp_path: Path) -> None:
    result = run_cli(tmp_path, "notoken", token=False)
    assert result.log.unmatched == []  # no GitHub request is sent without a token
    assert result.code == 0
    report = result.report
    assert any(
        w["origin"] == "cli" and w["code"] == "GITHUB_TOKEN_MISSING" for w in report["warnings"]
    )
    assert result.err.count("warning: no GITHUB_TOKEN set") == 1
    assert report["summary"]["degraded"] is True
    with_repo = [p for p in report["packages"] if p["repo"] is not None]
    assert with_repo
    for package in with_repo:
        assert any(w["code"] == "GITHUB_DISABLED" for w in package["warnings"]), package["purl"]
    before = {p["purl"]: p["confidence"] for p in main.report["packages"]}
    after = {p["purl"]: p["confidence"] for p in report["packages"]}
    assert any(after[purl] < before[purl] for purl in before)
    assert all(after[purl] <= before[purl] for purl in before)
    assert SENTINEL not in result.out + result.err + result.json_text


def test_an_unreadable_lockfile_is_a_warning_and_the_graph_says_what_it_lost(
    tmp_path: Path,
) -> None:
    """With no scopes there is nothing to augment from (CLI-AUG-7, limit CLI-AUG-9).

    The real Syft BOM then has an orphan dev package (`request`) with edges of its own, which
    `core.graph` reads as a second root and drops. The run still completes and says so.
    """
    project = tmp_path / "project"
    shutil.copytree(PROJECT, project)
    (project / "web" / "package-lock.json").write_text("this is not json", encoding="utf-8")
    result = run_cli(tmp_path, "badlock", project=project, token=False, subset=True)
    assert result.log.unmatched == []
    assert result.code == 0
    report = result.report
    lockfile_warnings = [w for w in report["warnings"] if w["code"] == "LOCKFILE_UNREADABLE"]
    assert len(lockfile_warnings) == 1
    assert lockfile_warnings[0]["origin"] == "cli"
    assert lockfile_warnings[0]["service"] == "web"
    assert result.err.count("warning: web: could not read lockfile package-lock.json") == 1
    graph = {(w["code"], w["service"]) for w in report["warnings"] if w["origin"] == "graph"}
    assert ("SCOPE_ASSUMED", "web") in graph
    assert ("MULTIPLE_ROOTS", "web") in graph
    assert PURLS["request"] not in result.purls()  # dropped as a second root
    assert {"service": "web", "file": "package-lock.json", "used": False} in report["input"][
        "lockfiles"
    ]
    by_name = dict(zip(result.names(), report["packages"], strict=True))
    assert by_name["nose"]["scope"] == "dev"  # the api service is untouched
    assert report["summary"]["stats"]["direct_edges_added"] == 1  # nose only


def test_a_failing_syft_is_exit_3_and_writes_nothing(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "failing", mode="fail")
    assert result.code == 3
    assert result.out == ""
    assert not result.json_path.exists()
    assert "STUB-SYFT-SECRET-STDERR" not in result.err
    assert result.log.matched == []  # it failed before any HTTP request


def test_an_invalid_fail_on_is_exit_2_and_nothing_runs(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "usage", "--fail-on", "zombie")
    assert result.code == 2
    assert result.out == ""
    assert not result.stub.log_path.exists()
    assert not result.json_path.exists()
    assert result.log.matched == [] and result.log.unmatched == []


# --------------------------------------------------------------- T9.5: determinism (CLI-TEST-7)


def test_two_runs_are_byte_identical(main: Run, tmp_path: Path) -> None:
    again = run_cli(tmp_path, "again")
    assert again.out == main.out
    assert again.json_text == main.json_text
    assert again.err == main.err
