"""End-to-end tests of ``graveyard autopsy --purl`` (T10; CLI-TEST-11, CLI-PURL-1…6).

This is the mode the dead-install-blocker hook uses. Single-package runs send requests the
cassette has no recording for (a one-query OSV body, a single-name downloads URL), so those
tests use ``subset_replay_transport``, which derives the two answers from the recorded batch
ones (design §9.4). The nine-package run sends exactly the recorded requests and uses the
plain cassette replay.

Every run asserts ``log.unmatched == []`` (CLI-TEST-1). The rejection tests use a transport
that fails the test if it is called at all.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest

from cli.app import run
from cli.tests.support import FakeClock, make_env, subset_replay_transport
from cli.tests.test_e2e_project import (
    ASSUMED_ORDER,
    CLOCK_START,
    MM_ANC,
    PROJECT,
    PURLS,
    SENTINEL,
    WEB_SBOM,
)
from core.sources.secret import SecretToken
from core.sources.tests import recorded as rec
from sources.tests.transports import ReplayLog, replay_transport

REQUEST = PURLS["request"]
EXPRESS = PURLS["express"]
NO_SUCH_SYFT = "/definitely/not/a/syft"


@dataclass(frozen=True)
class PurlRun:
    code: int
    out: str
    err: str
    json_path: Path
    log: ReplayLog

    @property
    def report(self) -> dict[str, Any]:
        loaded = json.loads(self.json_path.read_text(encoding="utf-8"))
        assert isinstance(loaded, dict)
        return loaded


def run_purl(
    work: Path,
    *args: str,
    token: bool = False,
    exact_replay: bool = False,
) -> PurlRun:
    work.mkdir(parents=True, exist_ok=True)
    json_path = work / "report.json"
    if exact_replay:
        transport, log = replay_transport(rec.cassette())
    else:
        transport, log = subset_replay_transport(rec.cassette())
    out, err = io.StringIO(), io.StringIO()
    code = run(
        ["autopsy", *args, "--as-of", "2026-11-03", "--json", str(json_path)],
        env=make_env(token=SecretToken(SENTINEL) if token else None),
        out=out,
        err=err,
        transport=transport,
        clock=FakeClock(CLOCK_START),
    )
    return PurlRun(code, out.getvalue(), err.getvalue(), json_path, log)


class _MustNotBeCalled(httpx.MockTransport):
    def __init__(self) -> None:
        super().__init__(self._fail)

    @staticmethod
    def _fail(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"a rejected command made an HTTP request: {request.url}")


def run_rejected(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = run(
        list(argv),
        env=make_env(),
        out=out,
        err=err,
        transport=_MustNotBeCalled(),
        clock=FakeClock(CLOCK_START),
    )
    return code, out.getvalue(), err.getvalue()


# ------------------------------------------------------------------- T10.2: the hook cases


def test_dead_package_with_fail_on_dead_exits_1(tmp_path: Path) -> None:
    result = run_purl(tmp_path, "--purl", REQUEST, "--fail-on", "dead")
    assert result.log.unmatched == []
    assert result.code == 1
    report = result.report
    assert report["input"] == {
        "mode": "purl",
        "syft_version": None,
        "services": [],
        "lockfiles": [],
    }
    assert len(report["packages"]) == 1
    package = report["packages"][0]
    assert package["purl"] == REQUEST
    assert package["state"] == "Dead"
    assert package["dead_reason"] == "declared"
    assert package["exposure_assumed"] is True
    assert package["exposure"] == 1.0
    assert package["services_affected"] is None
    assert package["direct"] is None
    assert package["scope"] is None
    assert package["manifests"] == []
    assert package["path_infos"] == []
    assert package["example_paths"] == []
    assert report["summary"]["gate"] == {"fail_on": ["dead"], "tripped": True, "matches": [REQUEST]}
    assert report["summary"]["exit_code"] == 1
    assert f"gate: 1 package matches --fail-on dead: {REQUEST}" in result.err
    assert "warning: no GITHUB_TOKEN set" in result.err
    assert "npm request@2.88.2" in result.out


def test_alive_package_with_fail_on_dead_exits_0(tmp_path: Path) -> None:
    result = run_purl(tmp_path, "--purl", EXPRESS, "--fail-on", "dead")
    assert result.log.unmatched == []
    assert result.code == 0
    package = result.report["packages"][0]
    assert package["state"] == "Alive"
    assert result.report["summary"]["gate"]["tripped"] is False
    assert result.report["summary"]["exit_code"] == 0
    assert "gate:" not in result.err


def test_a_single_purl_run_degrades_without_a_token_and_says_so(tmp_path: Path) -> None:
    result = run_purl(tmp_path, "--purl", REQUEST)
    assert result.code == 0  # no --fail-on: the gate cannot trip
    summary = result.report["summary"]
    assert summary["degraded"] is True
    assert any(w["code"] == "GITHUB_TOKEN_MISSING" for w in result.report["warnings"])
    assert "partial evidence" not in result.err  # only said when --fail-on is set


def test_a_degraded_gate_run_notes_partial_evidence(tmp_path: Path) -> None:
    result = run_purl(tmp_path, "--purl", EXPRESS, "--fail-on", "dead")
    assert "partial evidence" in result.err
    assert "0 packages Unknown" in result.err


# -------------------------------------------------------------- T10.3: nine --purl arguments


def _nine_args(order: list[str]) -> list[str]:
    args: list[str] = []
    for name in order:
        args += ["--purl", PURLS[name]]
    return args


def test_nine_purls_replay_the_recording_and_rank_with_assumed_exposure(tmp_path: Path) -> None:
    shuffled = [
        "six",
        "uuid",
        "request",
        "nose",
        "express",
        "left-pad",
        "pycrypto",
        "moment",
        "node-uuid",
    ]
    result = run_purl(tmp_path / "a", *_nine_args(shuffled), token=True, exact_replay=True)
    assert result.log.unmatched == []
    assert result.code == 0
    report = result.report
    by_purl = {p["purl"]: p for p in report["packages"]}
    by_name = {name: by_purl[purl] for name, purl in PURLS.items()}
    assert [p["purl"] for p in report["packages"]] == [PURLS[n] for n in ASSUMED_ORDER]
    for name, (state, reason, cursed, wounded) in MM_ANC.items():
        package = by_name[name]
        assert (
            package["state"],
            package["dead_reason"],
            package["cursed"],
            package["wounded"],
        ) == (
            state,
            reason,
            cursed,
            wounded,
        ), name
    assert all(p["exposure_assumed"] is True for p in report["packages"])
    assert all(p["exposure"] == 1.0 for p in report["packages"])
    assert report["summary"]["degraded"] is False
    assert SENTINEL not in result.out + result.err + result.json_path.read_text(encoding="utf-8")


def test_the_result_does_not_depend_on_the_argument_order(tmp_path: Path) -> None:
    forward = run_purl(tmp_path / "a", *_nine_args(list(PURLS)), token=True, exact_replay=True)
    backward = run_purl(
        tmp_path / "b", *_nine_args(list(reversed(PURLS))), token=True, exact_replay=True
    )
    assert forward.log.unmatched == [] and backward.log.unmatched == []
    assert forward.out == backward.out
    assert forward.json_path.read_text(encoding="utf-8") == backward.json_path.read_text(
        encoding="utf-8"
    )


def test_a_repeated_purl_is_analysed_once(tmp_path: Path) -> None:
    result = run_purl(tmp_path, "--purl", REQUEST, "--purl", REQUEST)
    assert result.log.unmatched == []
    assert result.code == 0
    assert [p["purl"] for p in result.report["packages"]] == [REQUEST]
    assert len(result.log.matched) == len(set(result.log.matched))  # no request sent twice


def test_syft_is_never_looked_up_in_purl_mode(tmp_path: Path) -> None:
    result = run_purl(tmp_path, "--syft", NO_SUCH_SYFT, "--purl", REQUEST)
    assert result.code == 0
    assert result.log.unmatched == []


# ---------------------------------------------------------------------- T10.4: rejections


@pytest.mark.parametrize(
    "argv",
    [
        ["autopsy", "--purl", "not-a-purl"],
        ["autopsy", "--purl", "pkg:npm/request"],
        ["autopsy", "--purl", "pkg:maven/org.example/thing@1.0.0"],
        ["autopsy", "--purl", REQUEST, "--purl", "not-a-purl"],
        ["autopsy", str(PROJECT), "--purl", REQUEST],
        ["autopsy", "--purl", REQUEST, "--sbom", str(WEB_SBOM)],
        ["autopsy"],
    ],
    ids=[
        "not-a-purl",
        "no-version",
        "maven",
        "one-bad-of-two",
        "path-and-purl",
        "sbom-and-purl",
        "no-input",
    ],
)
def test_rejections_exit_2_without_any_request(argv: list[str], tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    code, out, err = run_rejected(*argv, "--syft", NO_SUCH_SYFT, "--json", str(report))
    assert code == 2
    assert out == ""
    assert err.startswith("graveyard: error: ")
    assert "usage:" in err
    assert not report.exists()


def test_a_hostile_purl_is_shown_sanitised_and_short() -> None:
    code, _out, err = run_rejected("autopsy", "--purl", "\x1b[31m" + "x" * 500)
    assert code == 2
    assert "\x1b" not in err
    assert "x" * 101 not in err
