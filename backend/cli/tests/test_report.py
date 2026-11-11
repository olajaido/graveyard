"""Tests for ``cli.report`` (T6.6; CLI-JSON-1…8, CLI-PURL-5)."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any

from cli.errors import ExitCode
from cli.model import CliWarning
from cli.report import SCHEMA_NAME, SCHEMA_VERSION, report_to_dict
from cli.tests.support import anchor_signals, make_report
from core.graph import ExamplePath, GraphNode, GraphWarning
from core.scoring.types import PathInfo, Signals
from core.sources.model import EVIDENCE_KEYS, Evidence, ItemError, SourceResult, SourceWarning
from core.sources.tests import recorded as rec

NINE = [anchor_signals(name) for name in rec.ANCHORS]

TOP_KEYS = [
    "schema",
    "schema_version",
    "model_version",
    "as_of",
    "input",
    "summary",
    "packages",
    "errors",
    "warnings",
]
PACKAGE_KEYS = [
    "rank",
    "purl",
    "key",
    "ecosystem",
    "name",
    "version",
    "state",
    "dead_reason",
    "cursed",
    "wounded",
    "mortality",
    "confidence",
    "priority",
    "exposure",
    "exposure_assumed",
    "services_affected",
    "direct",
    "scope",
    "manifests",
    "path_infos",
    "example_paths",
    "why",
    "normalised_risks",
    "contributions",
    "evidence",
    "repo",
    "repo_via",
    "resolved_version",
    "latest_version",
    "warnings",
]


def _node(signals: Signals) -> GraphNode:
    infos = (PathInfo(runtime=True, direct=False), PathInfo(runtime=False, direct=True))
    return GraphNode(
        key="npm/x@1.0.0",
        purl=signals.purl,
        manifests=("api", "web"),
        path_infos=infos,
        services_affected=2,
        example_paths=(ExamplePath(service="web", nodes=("npm/a@1.0.0", "npm/x@1.0.0")),),
        path_witnesses=(),
    )


def test_top_level_keys_and_header() -> None:
    doc = report_to_dict(make_report(NINE))
    assert list(doc) == TOP_KEYS
    assert doc["schema"] == SCHEMA_NAME == "graveyard.autopsy"
    assert doc["schema_version"] == SCHEMA_VERSION == 1
    assert doc["model_version"] == "v1"
    assert doc["as_of"] == "2026-11-03"


def test_package_key_order_and_rank() -> None:
    doc = report_to_dict(make_report(NINE))
    assert [p["rank"] for p in doc["packages"]] == list(range(1, 10))
    for package in doc["packages"]:
        assert list(package) == PACKAGE_KEYS


def test_state_counts_have_all_five_keys_in_basestate_order() -> None:
    summary = report_to_dict(make_report(NINE))["summary"]
    assert list(summary["states"]) == ["Dead", "Unknown", "Resting", "Ailing", "Alive"]
    assert summary["states"] == {"Dead": 5, "Unknown": 0, "Resting": 1, "Ailing": 0, "Alive": 3}
    assert summary["packages"] == 9
    assert summary["cursed"] == 2
    assert summary["wounded"] == 3


def test_purl_mode_has_nulls_and_empty_lists() -> None:
    doc = report_to_dict(make_report(NINE, input_mode="purl"))
    assert doc["input"] == {"mode": "purl", "syft_version": None, "services": [], "lockfiles": []}
    for package in doc["packages"]:
        assert package["services_affected"] is None
        assert package["direct"] is None
        assert package["scope"] is None
        assert package["manifests"] == []
        assert package["path_infos"] == []
        assert package["example_paths"] == []
        assert package["exposure_assumed"] is True


def test_project_mode_graph_fields_come_from_the_node() -> None:
    signals = anchor_signals("request")
    report = make_report(
        [signals],
        nodes={signals.purl: _node(signals)},
        input_mode="syft",
        services=("api", "web"),
        lockfiles=(("api", "uv.lock", True), ("web", "package-lock.json", False)),
    )
    doc = report_to_dict(report)
    package = doc["packages"][0]
    assert package["services_affected"] == 2
    assert package["direct"] is True
    assert package["scope"] == "runtime"
    assert package["manifests"] == ["api", "web"]
    assert package["path_infos"] == [
        {"runtime": True, "direct": False},
        {"runtime": False, "direct": True},
    ]
    assert package["example_paths"] == [{"service": "web", "nodes": ["npm/a@1.0.0", "npm/x@1.0.0"]}]
    assert doc["input"]["mode"] == "syft"
    assert doc["input"]["syft_version"] == "1.56.0"
    assert doc["input"]["lockfiles"] == [
        {"service": "api", "file": "uv.lock", "used": True},
        {"service": "web", "file": "package-lock.json", "used": False},
    ]


def test_identity_fields_are_parsed_from_the_purl() -> None:
    doc = report_to_dict(
        make_report([Signals(purl="pkg:npm/%40babel/core@7.0.0", as_of=rec.AS_OF)])
    )
    package = doc["packages"][0]
    assert (package["ecosystem"], package["name"], package["version"]) == (
        "npm",
        "@babel/core",
        "7.0.0",
    )
    assert package["key"] == "npm/%40babel/core@7.0.0"  # the canonical purl form, as core.purl


def test_numbers_are_unrounded() -> None:
    doc = report_to_dict(make_report(NINE))
    six = next(p for p in doc["packages"] if p["name"] == "six")
    assert six["mortality"] != round(six["mortality"], 1)
    assert six["priority"] == six["mortality"]  # exposure assumed, not cursed


def test_every_package_has_all_eleven_evidence_keys() -> None:
    for package in report_to_dict(make_report(NINE))["packages"]:
        assert list(package["evidence"]) == list(EVIDENCE_KEYS)
        assert list(package["evidence"]["s2_latest_release_at"]) == [
            "value",
            "source_url",
            "fetched_at",
            "extra_source_urls",
            "note",
        ]


def test_evidence_values_urls_and_times() -> None:
    signals = anchor_signals("six")
    fetched = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
    evidence = {key: Evidence(None, None, None) for key in EVIDENCE_KEYS}
    evidence["s2_latest_release_at"] = Evidence(
        "2024-12-04",
        "https://pypi.org/pypi/six/json",
        fetched,
        extra_source_urls=("https://api.deps.dev/v3/x",),
    )
    source = SourceResult(
        input_purl=signals.purl,
        signals=signals,
        error=None,
        evidence=evidence,
        warnings=(SourceWarning("GITHUB_DISABLED", "github", ("s3_last_push_at",), "no token"),),
        repo="github.com/benjaminp/six",
        repo_via="depsdev",
        resolved_version="1.17.0",
        latest_version="1.17.0",
    )
    doc = report_to_dict(make_report([signals], sources={signals.purl: source}))
    package = doc["packages"][0]
    ev = package["evidence"]["s2_latest_release_at"]
    assert ev == {
        "value": "2024-12-04",
        "source_url": "https://pypi.org/pypi/six/json",
        "fetched_at": "2026-11-10T09:00:00+00:00",
        "extra_source_urls": ["https://api.deps.dev/v3/x"],
        "note": None,
    }
    assert package["repo"] == "github.com/benjaminp/six"
    assert package["repo_via"] == "depsdev"
    assert package["resolved_version"] == package["latest_version"] == "1.17.0"
    assert package["warnings"] == [
        {
            "code": "GITHUB_DISABLED",
            "source": "github",
            "signals": ["s3_last_push_at"],
            "detail": "no token",
            "status": None,
        }
    ]
    summary = doc["summary"]
    assert summary["warnings"]["source"] == 1
    assert summary["degraded"] is True


def test_warnings_and_errors_sections() -> None:
    report = make_report(
        [anchor_signals("six")],
        graph_warnings=(GraphWarning("SCOPE_ASSUMED", "assumed runtime", "web", ("a@1", "b@2")),),
        cli_warnings=(
            CliWarning("LOCKFILE_UNREADABLE", "could not read x", "web"),
            CliWarning("GITHUB_TOKEN_MISSING", "no token", None),
        ),
        item_errors=(("pkg:npm/bad", ItemError("MISSING_VERSION", "package URL has no version")),),
    )
    doc = report_to_dict(report)
    assert doc["warnings"][0] == {
        "origin": "graph",
        "code": "SCOPE_ASSUMED",
        "detail": "assumed runtime",
        "service": "web",
        "subjects": ["a@1", "b@2"],
    }
    assert [w["origin"] for w in doc["warnings"]] == ["graph", "cli", "cli"]
    assert {tuple(w) for w in doc["warnings"]} == {
        ("origin", "code", "detail", "service", "subjects")
    }
    assert doc["errors"] == [
        {"purl": "pkg:npm/bad", "code": "MISSING_VERSION", "detail": "package URL has no version"}
    ]
    assert doc["summary"]["item_errors"] == 1
    assert doc["summary"]["warnings"] == {"graph": 1, "cli": 2, "source": 0}
    assert doc["summary"]["degraded"] is True  # a token warning counts


def test_lockfile_warning_alone_is_not_degraded() -> None:
    report = make_report(
        [anchor_signals("six")],
        cli_warnings=(CliWarning("LOCKFILE_UNREADABLE", "could not read x", "web"),),
    )
    assert report_to_dict(report)["summary"]["degraded"] is False


def test_gate_block_and_exit_code() -> None:
    report = make_report(NINE, fail_on=frozenset({"dead", "cursed"}))
    summary = report_to_dict(report)["summary"]
    assert summary["gate"]["fail_on"] == ["cursed", "dead"]
    assert summary["gate"]["tripped"] is True
    assert len(summary["gate"]["matches"]) == 5
    assert summary["exit_code"] == int(report.exit_code) == 1

    clean = make_report([anchor_signals("express")], fail_on=frozenset({"dead"}))
    gate = report_to_dict(clean)["summary"]["gate"]
    assert gate == {"fail_on": ["dead"], "tripped": False, "matches": []}
    assert report_to_dict(clean)["summary"]["exit_code"] == 0
    assert clean.exit_code is ExitCode.OK


def test_source_statistics_block() -> None:
    sources = report_to_dict(make_report(NINE))["summary"]["sources"]
    assert sources == {
        "requests": {},
        "failures": {},
        "cache_hits": 0,
        "cache_misses": 0,
        "s9_skipped": 0,
    }


def test_json_safe_and_free_of_absolute_paths() -> None:
    doc = report_to_dict(make_report(NINE, fail_on=frozenset({"dead"})))
    text = json.dumps(doc, allow_nan=False)
    assert "/Users/" not in text
    assert "/home/" not in text
    assert json.loads(text) == doc


def test_no_packages_scored_leaves_model_version_null() -> None:
    report = replace(make_report([]), item_errors=(("x", ItemError("INVALID_PURL", "bad")),))
    doc: dict[str, Any] = report_to_dict(report)
    assert doc["model_version"] is None
    assert doc["packages"] == []
    assert doc["summary"]["packages"] == 0
    assert doc["as_of"] == date(2026, 11, 3).isoformat()
