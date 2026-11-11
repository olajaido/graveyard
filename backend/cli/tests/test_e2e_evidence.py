"""Gate only on evidence that was seen, end to end (T14.6; CLI-EVID-9).

Real warnings, produced by the sources over the recorded cassette: without a token every
package with a repository carries a `GITHUB_DISABLED` warning that lists the signals it could
not read; `pycrypto` and `nose` have no repository, so nothing was skipped for them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cli.tests.test_e2e_project import PURLS, Run, run_cli
from cli.tests.test_e2e_purl import run_purl

SIX = PURLS["six"]


@pytest.fixture(scope="module")
def no_token(tmp_path_factory: pytest.TempPathFactory) -> Run:
    """The anchors project, no token, gate on dead and cursed."""
    # The default width (100): the short WHY text has to fit it (CLI-EVID-5).
    return run_cli(
        tmp_path_factory.mktemp("evidence"), "run", "--fail-on", "dead,cursed", token=False
    )


@pytest.fixture(scope="module")
def with_token(tmp_path_factory: pytest.TempPathFactory) -> Run:
    return run_cli(
        tmp_path_factory.mktemp("evidence-token"), "run", "--fail-on", "dead,cursed", token=True
    )


def _package(run: Run, name: str) -> dict[str, object]:
    return next(p for p in run.report["packages"] if p["purl"] == PURLS[name])


# ------------------------------------------------------------- the project, no token


def test_without_a_token_the_gate_still_trips_on_declared_deaths_and_cursed(no_token: Run) -> None:
    assert no_token.log.unmatched == []
    assert no_token.code == 1
    matches = no_token.report["summary"]["gate"]["matches"]
    assert matches == [
        PURLS["pycrypto"],  # Dead by score and Cursed: always gated
        PURLS["left-pad"],  # declared dead
        PURLS["request"],  # declared dead and Cursed
        PURLS["node-uuid"],  # declared dead
        PURLS["nose"],  # Dead by score, no repository: nothing was skipped
    ]


def test_six_is_dead_on_partial_evidence_unverified_and_not_gated(no_token: Run) -> None:
    six = _package(no_token, "six")
    assert six["state"] == "Dead"
    assert six["dead_reason"] == "score"
    assert six["gate_eligible"] is False
    assert six["unverified_reason"] == "github data unavailable"  # the JSON keeps the long form
    assert str(six["why"]).startswith("unverified: no GitHub data")
    assert SIX not in no_token.report["summary"]["gate"]["matches"]


def test_nose_has_no_repo_so_it_is_gated(no_token: Run) -> None:
    nose = _package(no_token, "nose")
    assert nose["state"] == "Dead" and nose["dead_reason"] == "score"
    assert nose["repo"] is None
    assert nose["gate_eligible"] is True
    assert nose["unverified_reason"] is None
    assert nose["warnings"] == []  # nothing was skipped for a package with nothing to look up


def test_declared_deaths_and_cursed_are_always_eligible(no_token: Run) -> None:
    for name in ("request", "node-uuid", "left-pad", "pycrypto"):
        package = _package(no_token, name)
        assert package["gate_eligible"] is True, name
        assert package["unverified_reason"] is None, name
    assert _package(no_token, "request")["warnings"]  # GITHUB_DISABLED, yet still eligible


def test_only_six_is_unverified(no_token: Run) -> None:
    unverified = [p["purl"] for p in no_token.report["packages"] if not p["gate_eligible"]]
    assert unverified == [SIX]
    assert no_token.report["summary"]["stats"]["unverified"] == 1


def test_the_table_footer_and_the_notes(no_token: Run) -> None:
    lines = no_token.out.splitlines()
    assert lines[-1] == "1 unverified, not gated; set GITHUB_TOKEN to verify"
    six_line = next(line for line in lines if "six@1.17.0" in line)
    assert "unverified: no GitHub data" in six_line  # whole, at 100 columns, not cut
    assert max(len(line) for line in lines[:10]) <= 100
    assert "note: 1 package is unverified and was not gated" in no_token.err.splitlines()
    assert "gate: 5 packages match --fail-on cursed,dead: " in no_token.err


def test_the_other_states_are_not_touched(no_token: Run) -> None:
    for name, state in (("express", "Alive"), ("moment", "Alive"), ("uuid", "Alive")):
        package = _package(no_token, name)
        assert package["state"] == state
        assert package["gate_eligible"] is True


# ------------------------------------------------------------------ the project, a token


def test_with_a_token_nothing_is_unverified_and_six_is_resting(with_token: Run) -> None:
    assert with_token.log.unmatched == []
    assert with_token.code == 1
    six = _package(with_token, "six")
    assert six["state"] == "Resting"
    assert six["gate_eligible"] is True
    assert with_token.report["summary"]["stats"]["unverified"] == 0
    assert "unverified" not in with_token.out
    assert "unverified" not in with_token.err
    assert with_token.report["summary"]["gate"]["matches"] == [
        PURLS["pycrypto"],
        PURLS["left-pad"],
        PURLS["request"],
        PURLS["node-uuid"],
        PURLS["nose"],
    ]


# ------------------------------------------------------------------------ single package


def test_six_alone_without_a_token_exits_zero_with_six_unverified(tmp_path: Path) -> None:
    result = run_purl(tmp_path, "--purl", SIX, "--fail-on", "dead,cursed")
    assert result.log.unmatched == []
    assert result.code == 0
    report = result.report
    six = report["packages"][0]
    assert six["purl"] == SIX
    assert six["state"] == "Dead" and six["dead_reason"] == "score"
    assert six["gate_eligible"] is False
    assert six["unverified_reason"] == "github data unavailable"
    assert report["summary"]["gate"] == {
        "fail_on": ["cursed", "dead"],
        "tripped": False,
        "matches": [],
    }
    assert report["summary"]["stats"]["unverified"] == 1
    assert "note: 1 package is unverified and was not gated" in result.err
    assert "gate:" not in result.err
    assert result.out.splitlines()[-1] == "1 unverified, not gated; set GITHUB_TOKEN to verify"


def test_a_dead_declared_package_alone_without_a_token_still_blocks(tmp_path: Path) -> None:
    result = run_purl(tmp_path, "--purl", PURLS["request"], "--fail-on", "dead,cursed")
    assert result.code == 1
    assert result.report["packages"][0]["gate_eligible"] is True
