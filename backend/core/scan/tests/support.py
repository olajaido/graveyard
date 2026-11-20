"""Test builders shared by the scan tests."""

from __future__ import annotations

from datetime import UTC, date, datetime

from core.scoring.types import Advisory, Signals
from core.sources.model import EVIDENCE_KEYS, Evidence, SourceResult, SourceWarning

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
AS_OF = date(2026, 11, 20)


def make_signals(purl: str = "pkg:npm/left-pad@1.3.0", **overrides: object) -> Signals:
    values: dict[str, object] = {
        "purl": purl,
        "as_of": AS_OF,
        "s1_declared_death": False,
        "s1b_version_deprecated": False,
        "s2_latest_release_at": date(2024, 1, 5),
        "s3_last_push_at": date(2025, 6, 1),
        "s4_maintained": 3.0,
        "s5_committers": 2,
        "s6_open_issues": 4,
        "s6_closed_issues": 40,
        "s7_advisories": (Advisory(id="GHSA-xxxx", has_fix=True, published_at=date(2025, 1, 1)),),
        "s8_overall": 5.5,
        "s9_weekly_downloads": 1000,
    }
    values.update(overrides)
    return Signals(**values)  # type: ignore[arg-type]


def make_result(purl: str = "pkg:npm/left-pad@1.3.0", **overrides: object) -> SourceResult:
    signals = make_signals(purl, **overrides)
    evidence = {
        key: Evidence(
            value=None if key == "s7_advisories" else 1,
            source_url="https://api.deps.dev/v3/x",
            fetched_at=NOW,
            note="fixed note",
        )
        for key in EVIDENCE_KEYS
    }
    return SourceResult(
        input_purl=purl,
        signals=signals,
        error=None,
        evidence=evidence,
        warnings=(
            SourceWarning(
                code="GITHUB_DISABLED",
                source="github",
                signals=("s3_last_push_at",),
                detail="no GitHub token configured",
            ),
        ),
        repo="github.com/stevemao/left-pad",
        repo_via="depsdev",
        resolved_version="1.3.0",
        latest_version="1.3.0",
    )
