"""Tests for ``scripts/record_source_responses.py`` (T11.4; SRC-REC-1…5, SRC-SEC-7, D7).

The script is loaded by path with ``importlib`` and its functions are called directly. ``main`` is
driven over ``httpx.MockTransport`` with a stubbed ``autopsy_async``; nothing here touches the
network, and the script itself is never run against the live sources (that is T12, by hand).

The anchors come from the committed fixtures in ``core/scoring/tests/fixtures/anchors``. The
MM-ANC table of the script is first checked against those fixtures, so the table is known to be
right before it is used as the refusal rule.
"""

from __future__ import annotations

import ast
import asyncio
import copy
import gzip
import importlib.util
import io
import json
import random
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from core.scoring import score_package
from core.scoring.tests.test_anchors import signals_from_fixture
from core.scoring.types import BaseState, Signals
from core.sources import assemble as asm
from core.sources.cassette import cassette_from_obj
from core.sources.model import (
    EVIDENCE_KEYS,
    BatchResult,
    Evidence,
    SourceResult,
    SourceStats,
)
from core.sources.urls import ALLOWED_HOSTS, scorecard_url

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "record_source_responses.py"


def _load_script() -> Any:
    spec = importlib.util.spec_from_file_location("record_source_responses", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["record_source_responses"] = module  # dataclasses look the module up by name
    spec.loader.exec_module(module)
    return module


script: Any = _load_script()

TOKEN = "tok-record-secret-9f3a1c77"
CONTACT = "ops@example.org"
ENV = {"GITHUB_TOKEN": TOKEN, "GRAVEYARD_CONTACT": CONTACT}
SHAPED = "ghp_" + "A1b2C3d4E5" * 3 + "F6g7H8"  # token-shaped, built at runtime
AS_OF = date(2026, 11, 3)
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)

FIXTURES: dict[str, dict[str, Any]] = script.load_anchor_fixtures(script.ANCHOR_FIXTURES)
NAMES: tuple[str, ...] = script.ANCHOR_ORDER


# ------------------------------------------------------------------------ helpers


def scored_from_fixture(name: str) -> Any:
    return score_package(signals_from_fixture(FIXTURES[name]))


def result_from_fixture(
    name: str, doctor: Callable[[dict[str, Any]], None] | None = None
) -> SourceResult:
    """A ``SourceResult`` whose signals are the committed fixture's (optionally doctored)."""
    fixture = copy.deepcopy(FIXTURES[name])
    if doctor is not None:
        doctor(fixture)
    evidence = {key: Evidence(None, None, None, note="n") for key in EVIDENCE_KEYS}
    return SourceResult(
        input_purl=fixture["purl"],
        signals=signals_from_fixture(fixture),
        error=None,
        evidence=evidence,
        warnings=(),
        repo=fixture["repo"],
        repo_via=None,
        resolved_version=fixture["resolved_version"],
        latest_version=fixture["latest_version"],
    )


def all_results(
    doctors: Mapping[str, Callable[[dict[str, Any]], None]] | None = None,
) -> dict[str, SourceResult]:
    doctors = doctors or {}
    return {name: result_from_fixture(name, doctors.get(name)) for name in NAMES}


def batch_of(results: Mapping[str, SourceResult]) -> BatchResult:
    return BatchResult(
        results=tuple(results[name] for name in NAMES), stats=SourceStats({}, {}, 0, 0, 0)
    )


def with_signals(result: SourceResult, **changes: Any) -> SourceResult:
    assert result.signals is not None
    return replace(result, signals=replace(result.signals, **changes))


def json_ok(
    data: object, status: int = 200, headers: Mapping[str, str] | None = None
) -> httpx.Response:
    return httpx.Response(status, json=data, headers=dict(headers or {}))


# ------------------------------------------------------------- the MM-ANC table


def test_the_table_has_the_nine_anchors_in_order() -> None:
    assert NAMES == (
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
    assert set(script.EXPECTED) == set(NAMES)


@pytest.mark.parametrize("name", NAMES)
def test_the_table_agrees_with_the_committed_fixtures(name: str) -> None:
    # Before the table is used as a refusal rule it must hold for the data it was written from.
    assert script.check_expectations(name, scored_from_fixture(name)) == []


def _flip(value: bool) -> bool:
    return not value


@pytest.mark.parametrize(
    ("name", "field", "changes"),
    [
        ("request", "base_state", {"base_state": BaseState.ALIVE}),
        ("request", "dead_reason", {"dead_reason": "score"}),
        ("request", "cursed", {"cursed": False}),
        ("request", "wounded", {"wounded": True}),
        ("node-uuid", "cursed", {"cursed": True}),
        ("node-uuid", "dead_reason", {"dead_reason": None}),
        ("left-pad", "mortality", {"mortality": 91.0}),
        ("left-pad", "wounded", {"wounded": True}),
        ("express", "base_state", {"base_state": BaseState.AILING}),
        ("express", "wounded", {"wounded": False}),
        ("express", "cursed", {"cursed": True}),
        ("uuid", "wounded", {"wounded": False}),
        ("moment", "base_state", {"base_state": BaseState.DEAD}),
        ("moment", "wounded", {"wounded": False}),
        ("pycrypto", "dead_reason", {"dead_reason": "declared"}),
        ("pycrypto", "cursed", {"cursed": False}),
        ("pycrypto", "confidence", {"confidence": 0.5}),
        ("nose", "wounded", {"wounded": True}),
        ("nose", "cursed", {"cursed": True}),
        ("nose", "confidence", {"confidence": 0.3}),
        ("six", "base_state", {"base_state": BaseState.AILING}),
        ("six", "mortality", {"mortality": 44.3}),
        ("six", "mortality", {"mortality": 59.9}),
        ("six", "cursed", {"cursed": True}),
        ("six", "wounded", {"wounded": True}),
        ("express", "exposure", {"exposure": 0.9}),
        ("express", "exposure_assumed", {"exposure_assumed": False}),
    ],
)
def test_each_field_of_the_table_is_enforced(
    name: str, field: str, changes: dict[str, Any]
) -> None:
    doctored = replace(scored_from_fixture(name), **changes)
    problems = script.check_expectations(name, doctored)
    assert problems, "the doctored result passed the table"
    assert any(p.startswith(f"{name}: {field} ") for p in problems), problems


def test_a_clean_result_has_no_problems_and_messages_carry_no_secrets() -> None:
    doctored = replace(scored_from_fixture("six"), base_state=BaseState.ALIVE, mortality=10.0)
    text = " ".join(script.check_expectations("six", doctored))
    assert TOKEN not in text and SHAPED not in text


def test_six_mortality_is_held_to_the_sentinel_within_half_a_point() -> None:
    six = scored_from_fixture("six")
    for value, ok in ((43.2, True), (44.2, True), (43.1, False), (44.3, False)):
        problems = script.check_expectations("six", replace(six, mortality=value))
        assert (problems == []) is ok, (value, problems)


# -------------------------------------------------------------------- evaluate


def test_a_clean_run_has_neither_mismatches_nor_parity_differences() -> None:
    evaluation = script.evaluate(all_results(), FIXTURES)
    assert evaluation.mismatches == () and evaluation.parity == ()
    assert set(evaluation.scored) == set(NAMES)


def test_a_state_change_is_a_mismatch_that_names_the_anchor() -> None:
    def alive(fixture: dict[str, Any]) -> None:
        fixture["signals"]["s1_declared_death"]["value"] = False
        fixture["signals"]["s7_advisories"]["value"] = []
        fixture["signals"]["s2_latest_release_at"]["value"] = "2026-10-01"

    evaluation = script.evaluate(all_results({"request": alive}), FIXTURES)
    assert evaluation.mismatches
    assert all(m.startswith("request: ") for m in evaluation.mismatches)


def test_an_item_error_is_a_mismatch_not_a_crash() -> None:
    results = all_results()
    del results["nose"]
    evaluation = script.evaluate(results, FIXTURES)
    assert evaluation.mismatches == ("nose: not analysed (no result)",)


# ---------------------------------------------------------------------- parity


def parity(name: str, result: SourceResult | None = None) -> list[str]:
    found: list[str] = script.parity_differences(
        name, result or result_from_fixture(name), FIXTURES[name]
    )
    return found


def test_identical_data_has_no_parity_differences() -> None:
    for name in NAMES:
        assert parity(name) == []


def test_repo_versions_s1b_and_s2_must_be_equal() -> None:
    base = result_from_fixture("express")
    assert any("repo is" in m for m in parity("express", replace(base, repo="github.com/o/r")))
    assert any("repo is" in m for m in parity("express", replace(base, repo=None)))
    assert any(
        "resolved_version" in m for m in parity("express", replace(base, resolved_version="9"))
    )
    assert any("latest_version" in m for m in parity("express", replace(base, latest_version="9")))
    assert any(
        "s1b" in m for m in parity("express", with_signals(base, s1b_version_deprecated=True))
    )
    assert any(
        "s2_latest_release_at" in m
        for m in parity("express", with_signals(base, s2_latest_release_at=date(2020, 1, 1)))
    )


def test_a_repo_in_another_case_is_the_same_repo() -> None:
    base = result_from_fixture("express")
    assert base.repo is not None
    assert (
        parity("express", replace(base, repo=base.repo.upper().replace("GITHUB.COM", "github.com")))
        == []
    )


def test_s1_may_be_none_where_the_fixture_has_false_but_not_where_it_has_true() -> None:
    express = result_from_fixture("express")
    assert FIXTURES["express"]["signals"]["s1_declared_death"]["value"] is False
    assert parity("express", with_signals(express, s1_declared_death=None)) == []
    assert any(
        "s1_declared_death" in m
        for m in parity("express", with_signals(express, s1_declared_death=True))
    )
    request = result_from_fixture("request")
    assert any(
        "s1_declared_death" in m
        for m in parity("request", with_signals(request, s1_declared_death=None))
    )


def test_advisories_must_all_be_there_with_the_same_fix_and_date() -> None:
    express = result_from_fixture("express")
    assert express.signals is not None and express.signals.s7_advisories
    first, *rest = express.signals.s7_advisories
    assert any(
        "no longer listed" in m
        for m in parity("express", with_signals(express, s7_advisories=tuple(rest)))
    )
    flipped = replace(first, has_fix=not first.has_fix)
    assert any(
        "has_fix" in m
        for m in parity("express", with_signals(express, s7_advisories=(flipped, *rest)))
    )
    dated = replace(first, published_at=date(1999, 1, 1))
    assert any(
        "published_at" in m
        for m in parity("express", with_signals(express, s7_advisories=(dated, *rest)))
    )
    extra = replace(first, id="GHSA-new-new-new")
    messages = parity("express", with_signals(express, s7_advisories=(first, *rest, extra)))
    assert messages == ["express: extra advisory GHSA-new-new-new"]
    assert any(
        "s7_advisories is missing" in m
        for m in parity("express", with_signals(express, s7_advisories=None))
    )


@pytest.mark.parametrize(
    ("name", "key", "moved", "ok"),
    [
        ("request", "s3_last_push_at", 14, True),
        ("request", "s3_last_push_at", 15, False),
        ("request", "s4_maintained", 0.5, True),
        ("request", "s4_maintained", 0.6, False),
        ("request", "s8_overall", -0.5, True),
        ("request", "s8_overall", -0.6, False),
        ("request", "s5_committers", 1, True),
        ("request", "s5_committers", 2, False),
        ("request", "s6_open_issues", 10, True),
        ("request", "s6_open_issues", 11, False),
        ("request", "s6_closed_issues", 108, True),  # 5 % of 2,176
        ("request", "s6_closed_issues", 110, False),
        ("request", "s9_weekly_downloads", 3_000_000, True),  # about 21 % of 14.1 M
        ("request", "s9_weekly_downloads", 4_000_000, False),  # about 28 %
    ],
)
def test_live_counters_are_held_to_their_stated_tolerance(
    name: str, key: str, moved: float, ok: bool
) -> None:
    base = result_from_fixture(name)
    assert base.signals is not None
    old = getattr(base.signals, key)
    new: Any
    if isinstance(old, date):
        new = date.fromordinal(old.toordinal() + int(moved))
    elif isinstance(old, float) or isinstance(moved, float):
        new = old + moved
    else:
        new = old + int(moved)
    messages = parity(name, with_signals(base, **{key: new}))
    assert (messages == []) is ok, messages
    if not ok:
        assert any(key in m and "outside tolerance" in m for m in messages)


def test_a_live_counter_must_be_present_when_the_fixture_has_it_and_the_reverse() -> None:
    request = result_from_fixture("request")
    assert any(
        "(presence)" in m for m in parity("request", with_signals(request, s5_committers=None))
    )
    pycrypto = result_from_fixture("pycrypto")
    assert any(
        "(presence)" in m
        for m in parity("pycrypto", with_signals(pycrypto, s3_last_push_at=date(2024, 1, 1)))
    )


def test_pypi_downloads_not_fetched_for_a_package_that_cannot_be_resting_are_not_compared() -> None:
    pycrypto = result_from_fixture("pycrypto")
    skipped = replace(
        with_signals(pycrypto, s9_weekly_downloads=None),
        evidence={
            **pycrypto.evidence,
            "s9_weekly_downloads": Evidence(None, None, None, note=asm.NOTE_S9_SKIPPED),
        },
    )
    assert parity("pycrypto", skipped) == []
    # Without the note a missing value is a presence difference.
    unexplained = with_signals(pycrypto, s9_weekly_downloads=None)
    assert any("s9_weekly_downloads" in m for m in parity("pycrypto", unexplained))


# ------------------------------------------------------ the recording transport


def exchange_world(handler: Callable[[httpx.Request], httpx.Response]) -> Any:
    return script.RecordingTransport(httpx.MockTransport(handler))


def drive(recorder: Any, *calls: tuple[str, str, Any, dict[str, str]]) -> list[httpx.Response]:
    async def run() -> list[httpx.Response]:
        async with httpx.AsyncClient(transport=recorder) as client:
            out = []
            for method, url, body, headers in calls:
                out.append(await client.request(method, url, json=body, headers=headers))
            return out

    return asyncio.run(run())


def test_the_recorder_keeps_method_url_bodies_and_the_two_response_headers() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return json_ok({"results": [1]}, headers={"Retry-After": "7"})
        return json_ok({"ok": True})

    recorder = exchange_world(handler)
    responses = drive(
        recorder,
        ("GET", "https://api.deps.dev/v3/x", None, {}),
        ("POST", "https://api.osv.dev/v1/querybatch", {"queries": [{"a": 1}]}, {}),
    )
    assert [r.json() for r in responses] == [{"ok": True}, {"results": [1]}]
    first, second = recorder.exchanges
    assert (first.method, first.url, first.request_body, first.status) == (
        "GET",
        "https://api.deps.dev/v3/x",
        None,
        200,
    )
    assert first.content_type == "application/json" and first.retry_after is None
    assert second.method == "POST" and second.request_body == {"queries": [{"a": 1}]}
    assert second.response_body == {"results": [1]} and second.retry_after == "7"
    assert recorder.unrecorded == []


def test_the_recorder_never_stores_a_request_header() -> None:
    recorder = exchange_world(lambda request: json_ok({"ok": True}))
    secret = "Bearer " + TOKEN
    drive(
        recorder,
        (
            "GET",
            "https://api.github.com/graphql",
            None,
            {"Authorization": secret, "Cookie": "sid=" + TOKEN},
        ),
    )
    [exchange] = recorder.exchanges
    assert TOKEN not in repr(exchange) and "Authorization" not in repr(exchange)
    assert set(script.Exchange.__dataclass_fields__) == {
        "method",
        "url",
        "request_body",
        "status",
        "content_type",
        "retry_after",
        "response_body",
    }


def test_a_gzip_response_is_recorded_decoded_and_the_client_still_reads_it() -> None:
    payload = json.dumps({"big": "x" * 500}).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=gzip.compress(payload),
            headers={"content-encoding": "gzip", "content-type": "application/json"},
        )

    recorder = exchange_world(handler)
    [response] = drive(recorder, ("GET", "https://pypi.org/pypi/six/json", None, {}))
    assert response.json() == {"big": "x" * 500}
    assert recorder.exchanges[0].response_body == {"big": "x" * 500}


def test_error_statuses_with_json_bodies_are_recorded_with_retry_after() -> None:
    recorder = exchange_world(
        lambda r: json_ok(
            {"error": "slow down"}, 429, {"Retry-After": "Wed, 11 Nov 2026 07:28:00 GMT"}
        )
    )
    drive(recorder, ("GET", "https://pypistats.org/api/packages/six/recent", None, {}))
    [exchange] = recorder.exchanges
    assert exchange.status == 429 and exchange.retry_after == "Wed, 11 Nov 2026 07:28:00 GMT"


@pytest.mark.parametrize(
    ("status", "body"),
    [(200, b"<html>no</html>"), (404, b"<html>gone</html>"), (200, b'{"x": NaN}'), (200, b"")],
)
def test_a_body_that_is_not_json_is_not_recorded_but_is_listed(status: int, body: bytes) -> None:
    recorder = exchange_world(lambda request: httpx.Response(status, content=body))
    [response] = drive(recorder, ("GET", "https://api.deps.dev/v3/x", None, {}))
    assert response.status_code == status and response.content == body  # the client still gets it
    assert recorder.exchanges == []
    [dropped] = recorder.unrecorded
    assert (dropped.status, dropped.reason) == (status, "response body is not JSON")


def test_parse_json_bytes_never_raises() -> None:
    assert script.parse_json_bytes(b'{"a": [1, 2]}') == (True, {"a": [1, 2]})
    assert script.parse_json_bytes(b"\xff\xfe") == (False, None)
    assert script.parse_json_bytes(b"[" * 100_000) == (False, None)
    assert script.parse_json_bytes(b"Infinity") == (False, None)


# ----------------------------------------------------------- building the cassette


def exchange(url: str, body: Any = None, status: int = 200, response: Any = None) -> Any:
    return script.Exchange(
        "GET" if body is None else "POST",
        url,
        body,
        status,
        "application/json",
        None,
        {"ok": True} if response is None else response,
    )


def test_of_identical_requests_the_last_answer_wins_and_is_counted() -> None:
    built = script.build_cassette(
        [
            exchange("https://a.test/x", response={"v": 1}, status=503),
            exchange("https://a.test/x", response={"v": 2}),
            exchange("https://b.test/y"),
        ]
    )
    assert built.superseded == 1
    by_url = {e.url: e for e in built.cassette.entries}
    assert by_url["https://a.test/x"].status == 200
    assert dict(by_url["https://a.test/x"].response_body) == {"v": 2}


def test_the_rendered_cassette_does_not_depend_on_exchange_order() -> None:
    exchanges = [
        exchange("https://api.osv.dev/v1/querybatch", body={"q": i}, response={"i": i})
        for i in range(6)
    ] + [exchange(f"https://api.deps.dev/v3/{i}") for i in range(6)]
    reference = script.render_cassette(script.build_cassette(exchanges).cassette)
    rng = random.Random(7)
    for _ in range(5):
        shuffled = list(exchanges)
        rng.shuffle(shuffled)
        assert script.render_cassette(script.build_cassette(shuffled).cassette) == reference
    assert reference.endswith("\n") and not reference.endswith("\n\n")


def test_the_rendered_cassette_round_trips() -> None:
    built = script.build_cassette(
        [exchange("https://a.test/x", body={"b": [1, {"c": None}]}, response={"é": "ü"})]
    )
    text = script.render_cassette(built.cassette)
    assert cassette_from_obj(json.loads(text)) == built.cassette
    assert "é" in text  # not escaped: diffs stay readable


# ------------------------------------------------------------------------ sizes


def big(size: int) -> Any:
    return exchange("https://a.test/big", response={"d": "x" * size})


def test_a_body_over_two_mebibytes_is_flagged_and_exactly_at_the_limit_is_not() -> None:
    limit = script.MAX_BODY_BYTES
    overhead = len(json.dumps({"d": ""}, separators=(",", ":")))
    at_limit = script.build_cassette([big(limit - overhead)]).cassette
    assert script.check_sizes(at_limit) == []
    over = script.build_cassette([big(limit - overhead + 1)]).cassette
    [message] = script.check_sizes(over)
    assert "over" in message and "https://a.test/big" in message


def test_bodies_together_over_six_mebibytes_are_flagged() -> None:
    each = 1_900_000  # each under 2 MiB
    exchanges = [exchange(f"https://a.test/{i}", response={"d": "x" * each}) for i in range(4)]
    messages = script.check_sizes(script.build_cassette(exchanges).cassette)
    assert len(messages) == 1 and messages[0].startswith("bodies total")
    three = script.check_sizes(script.build_cassette(exchanges[:3]).cassette)
    assert three == []


# ---------------------------------------------------------------- secret scanning


def test_find_secrets_reports_what_was_found_and_never_the_secret() -> None:
    assert script.find_secrets("nothing here", TOKEN) == []
    assert script.find_secrets(f"a {TOKEN} b", TOKEN) == ["the GitHub token"]
    assert script.find_secrets(f"a {SHAPED} b", TOKEN) == ["a GitHub-token-shaped string"]
    both = script.find_secrets(f"{TOKEN} {SHAPED}", TOKEN)
    assert both == ["the GitHub token", "a GitHub-token-shaped string"]
    assert TOKEN not in " ".join(both) and SHAPED not in " ".join(both)
    assert script.find_secrets(f"a {SHAPED} b", None) == ["a GitHub-token-shaped string"]


# ------------------------------------------------------------------ atomic writes


def test_write_atomic_creates_replaces_and_leaves_no_temporary_file(tmp_path: Path) -> None:
    target = tmp_path / "sub" / "cassette.json"
    script.write_atomic(target, "one\n")
    assert target.read_text(encoding="utf-8") == "one\n"
    script.write_atomic(target, "two\n")
    assert target.read_text(encoding="utf-8") == "two\n"
    assert [p.name for p in target.parent.iterdir()] == ["cassette.json"]


def test_a_failed_replace_keeps_the_old_file_and_removes_the_temporary_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "cassette.json"
    script.write_atomic(target, "old\n")

    def boom(src: object, dst: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(script.os, "replace", boom)
    with pytest.raises(OSError):
        script.write_atomic(target, "new\n")
    assert target.read_text(encoding="utf-8") == "old\n"
    assert [p.name for p in tmp_path.iterdir()] == ["cassette.json"]


# ---------------------------------------------------------------------- README


def test_provenance_rows_create_the_readme_and_are_appended_to_it(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    row = script.ProvenanceRow(
        "a.json", "deps.dev | OSV", "cmd --x", date(2026, 11, 10), "9 anchors\nline"
    )
    script.append_provenance(readme, [row], "0.28.1")
    text = readme.read_text(encoding="utf-8")
    assert text.startswith("# Recorded source responses")
    assert "| File | Source | Command | httpx | Recorded on | Notes |" in text
    assert "| a.json | deps.dev / OSV | cmd --x | 0.28.1 | 2026-11-10 | 9 anchors line |" in text
    script.append_provenance(readme, [replace(row, file="b.json")], "0.28.1")
    again = readme.read_text(encoding="utf-8")
    assert again.startswith(text) and "| b.json |" in again
    assert again.count("# Recorded source responses") == 1


# -------------------------------------------------------------------- environment


def test_a_missing_variable_is_named_and_no_value_is_shown() -> None:
    both = script.read_environment({})
    assert isinstance(both, str) and "GITHUB_TOKEN and GRAVEYARD_CONTACT are not set" in both
    only_token = script.read_environment({"GITHUB_TOKEN": TOKEN})
    assert isinstance(only_token, str) and only_token.startswith("GRAVEYARD_CONTACT is not set")
    assert TOKEN not in only_token
    blank = script.read_environment({"GITHUB_TOKEN": "  ", "GRAVEYARD_CONTACT": CONTACT})
    assert isinstance(blank, str) and blank.startswith("GITHUB_TOKEN is not set")
    ok = script.read_environment({"GITHUB_TOKEN": f" {TOKEN} ", "GRAVEYARD_CONTACT": CONTACT})
    assert (ok.token, ok.contact) == (TOKEN, CONTACT)


def run_main(
    argv: list[str],
    *,
    environ: Mapping[str, str] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()

    async def no_sleep(seconds: float) -> None:
        return None

    code = script.main(
        argv,
        environ=ENV if environ is None else environ,
        transport=transport,
        out=out,
        err=err,
        sleep=no_sleep,
    )
    return code, out.getvalue(), err.getvalue()


def test_main_without_the_variables_exits_2_with_a_message_and_no_network(tmp_path: Path) -> None:
    code, out, err = run_main(["--out-dir", str(tmp_path)], environ={})
    assert code == 2 and out == ""
    assert "GITHUB_TOKEN" in err and "GRAVEYARD_CONTACT" in err
    assert list(tmp_path.iterdir()) == []


def test_main_with_only_the_contact_missing_never_prints_the_token(tmp_path: Path) -> None:
    code, out, err = run_main(["--out-dir", str(tmp_path)], environ={"GITHUB_TOKEN": TOKEN})
    assert code == 2 and TOKEN not in out + err and "GRAVEYARD_CONTACT" in err


@pytest.mark.parametrize(
    "environ",
    [
        {"GITHUB_TOKEN": "has a space inside", "GRAVEYARD_CONTACT": CONTACT},
        {"GITHUB_TOKEN": TOKEN, "GRAVEYARD_CONTACT": "ops@example.org\nX-Evil: 1"},
    ],
)
def test_main_with_an_invalid_value_exits_2_and_does_not_show_it(
    environ: dict[str, str], tmp_path: Path
) -> None:
    code, out, err = run_main(["--out-dir", str(tmp_path)], environ=environ)
    assert code == 2
    assert "inside" not in out + err and "X-Evil" not in out + err
    assert list(tmp_path.iterdir()) == []


def test_main_prints_an_exception_as_its_type_name_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def explode(*args: Any, **kwargs: Any) -> BatchResult:
        raise RuntimeError(f"leak {TOKEN} and {SHAPED}")

    monkeypatch.setattr(script, "autopsy_async", explode)
    code, out, err = run_main(["--out-dir", str(tmp_path)])
    assert code == 1
    assert err.strip() == "error: RuntimeError"
    assert TOKEN not in out + err and SHAPED not in out + err
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------- main, over a fake run


def stub_autopsy(
    monkeypatch: pytest.MonkeyPatch,
    results: Mapping[str, SourceResult],
    calls: list[tuple[str, str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Replace ``autopsy_async``: make ``calls`` through the given transport, return ``results``."""
    seen: list[dict[str, Any]] = []

    async def fake(
        requests: Any, *, config: Any, token: Any, transport: Any, **_: Any
    ) -> BatchResult:
        seen.append({"requests": list(requests), "token": token, "transport": transport})
        async with httpx.AsyncClient(transport=transport) as client:
            for method, url, body in calls or []:
                await client.request(method, url, json=body)
        return batch_of(results)

    monkeypatch.setattr(script, "autopsy_async", fake)
    return seen


def echo_handler(request: httpx.Request) -> httpx.Response:
    if "no-such" in str(request.url):
        return json_ok({"code": 404, "message": "not found"}, 404)
    return json_ok({"url": str(request.url)})


GOOD_CALLS: list[tuple[str, str, Any]] = [
    ("GET", "https://api.deps.dev/v3/systems/npm/packages/request/versions/2.88.2", None),
    ("POST", "https://api.osv.dev/v1/querybatch", {"queries": [{"version": "1"}]}),
]


def written(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir())


def test_a_clean_run_writes_the_cassette_and_a_readme_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = stub_autopsy(monkeypatch, all_results(), GOOD_CALLS)
    code, out, err = run_main(
        ["--out-dir", str(tmp_path)], transport=httpx.MockTransport(echo_handler)
    )
    assert (code, err) == (0, "")
    assert written(tmp_path) == ["README.md", "anchors.cassette.json"]
    # the nine purls of the committed fixtures at as_of 2026-11-03, one batch, in MM-ANC order
    [call] = seen
    assert call["requests"] == [(FIXTURES[n]["purl"], AS_OF) for n in NAMES]
    cassette = cassette_from_obj(
        json.loads((tmp_path / "anchors.cassette.json").read_text("utf-8"))
    )
    assert [(e.method, e.url) for e in cassette.entries] == sorted(
        [(m, u) for m, u, _ in GOOD_CALLS], key=lambda pair: pair[1]
    )
    assert "| anchors.cassette.json |" in (tmp_path / "README.md").read_text("utf-8")
    assert "Wrote anchors.cassette.json: 2 exchanges." in out
    for name in NAMES:
        assert f"[{name}]" in out
    assert TOKEN not in out


def test_the_token_reaches_the_autopsy_call_as_a_secret_token_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = stub_autopsy(monkeypatch, all_results(), GOOD_CALLS)
    run_main(["--out-dir", str(tmp_path)], transport=httpx.MockTransport(echo_handler))
    token = seen[0]["token"]
    assert type(token).__name__ == "SecretToken" and TOKEN not in repr(token) + str(token)
    assert isinstance(seen[0]["transport"], script.RecordingTransport)


def test_a_state_change_refuses_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def alive(fixture: dict[str, Any]) -> None:
        fixture["signals"]["s1_declared_death"]["value"] = False
        fixture["signals"]["s7_advisories"]["value"] = []
        fixture["signals"]["s2_latest_release_at"]["value"] = "2026-10-01"

    stub_autopsy(monkeypatch, all_results({"request": alive}), GOOD_CALLS)
    code, out, err = run_main(
        ["--out-dir", str(tmp_path), "--fallbacks", "--probe-pypistats"],
        transport=httpx.MockTransport(echo_handler),
    )
    assert code == 1 and err == ""
    assert list(tmp_path.iterdir()) == []  # not even the probe, nor the README
    assert "REFUSING" in out and "Nothing was written." in out
    assert "refused: request: " in out
    assert "Probing pypistats" not in out  # a refusal stops before the probe


def test_even_a_message_that_contains_the_token_is_redacted_before_it_is_printed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Defence in depth: simulate a bug that builds a message with the token in it.
    stub_autopsy(monkeypatch, all_results(), GOOD_CALLS)
    leaky = script.Evaluation(
        mismatches=(f"request: base_state is {TOKEN}",),
        parity=(f"request: repo is {TOKEN}",),
        scored={},
    )
    monkeypatch.setattr(script, "evaluate", lambda results, fixtures: leaky)
    code, out, err = run_main(
        ["--out-dir", str(tmp_path)], transport=httpx.MockTransport(echo_handler)
    )
    assert code == 1
    assert TOKEN not in out + err
    assert "[REDACTED]" in out
    assert list(tmp_path.iterdir()) == []


def test_a_missing_anchor_result_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    results = all_results()
    results["six"] = replace(results["six"], signals=None, error=_item_error(), evidence={})
    stub_autopsy(monkeypatch, results, GOOD_CALLS)
    code, out, _ = run_main(
        ["--out-dir", str(tmp_path)], transport=httpx.MockTransport(echo_handler)
    )
    assert code == 1 and "refused: six: not analysed (INVALID_PURL)" in out
    assert list(tmp_path.iterdir()) == []


def _item_error() -> Any:
    from core.sources.model import ItemError

    return ItemError("INVALID_PURL", "bad purl")


def drifted(results: dict[str, SourceResult]) -> dict[str, SourceResult]:
    results["express"] = with_signals(results["express"], s2_latest_release_at=date(2020, 1, 1))
    return results


def test_parity_differences_are_warnings_without_strict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_autopsy(monkeypatch, drifted(all_results()), GOOD_CALLS)
    code, out, _ = run_main(
        ["--out-dir", str(tmp_path)], transport=httpx.MockTransport(echo_handler)
    )
    assert code == 0
    assert "parity: express: s2_latest_release_at is 2020-01-01" in out
    assert "anchors.cassette.json" in written(tmp_path)


def test_parity_differences_refuse_with_strict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_autopsy(monkeypatch, drifted(all_results()), GOOD_CALLS)
    code, out, _ = run_main(
        ["--out-dir", str(tmp_path), "--strict"], transport=httpx.MockTransport(echo_handler)
    )
    assert code == 1 and "parity difference(s) and --strict is set" in out
    assert list(tmp_path.iterdir()) == []


def test_a_body_over_the_limit_refuses_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def huge(request: httpx.Request) -> httpx.Response:
        return json_ok({"d": "x" * (script.MAX_BODY_BYTES + 1)})

    stub_autopsy(monkeypatch, all_results(), GOOD_CALLS)
    code, out, _ = run_main(["--out-dir", str(tmp_path)], transport=httpx.MockTransport(huge))
    assert code == 1 and "refused: body of GET" in out
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("leak", [TOKEN, SHAPED])
def test_a_secret_in_a_response_refuses_and_is_not_printed(
    leak: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def leaky(request: httpx.Request) -> httpx.Response:
        return json_ok({"echo": f"your token is {leak}"})

    stub_autopsy(monkeypatch, all_results(), GOOD_CALLS)
    code, out, err = run_main(["--out-dir", str(tmp_path)], transport=httpx.MockTransport(leaky))
    assert code == 1 and "refused: output contains" in out
    assert leak not in out + err
    assert list(tmp_path.iterdir()) == []


def test_a_2xx_response_that_is_not_json_refuses_but_a_404_one_is_left_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def html(request: httpx.Request) -> httpx.Response:
        status = 404 if request.method == "GET" else 200
        return httpx.Response(status, content=b"<html>x</html>")

    stub_autopsy(monkeypatch, all_results(), GOOD_CALLS)
    code, out, _ = run_main(["--out-dir", str(tmp_path)], transport=httpx.MockTransport(html))
    assert code == 1
    assert "left out: GET https://api.deps.dev" in out
    assert "refused: POST https://api.osv.dev/v1/querybatch: response body is not JSON" in out
    assert list(tmp_path.iterdir()) == []

    only_404 = [GOOD_CALLS[0]]
    stub_autopsy(monkeypatch, all_results(), only_404)
    again = tmp_path / "again"
    code, out, _ = run_main(["--out-dir", str(again)], transport=httpx.MockTransport(html))
    assert code == 0 and "left out: GET" in out
    assert (
        cassette_from_obj(json.loads((again / "anchors.cassette.json").read_text("utf-8"))).entries
        == ()
    )


# -------------------------------------------------------------------- --fallbacks


def test_the_fallback_requests_are_built_by_urls_py_on_allowed_hosts() -> None:
    repos = [FIXTURES[n]["repo"] for n in NAMES if FIXTURES[n]["repo"]]
    items = script.fallback_requests(repos + repos)  # duplicates collapse
    urls = [item.request.url for item in items]
    assert len(set(repos)) == 7
    for repo in set(repos):
        _, owner, name = repo.split("/")
        assert scorecard_url(owner, name) in urls
    assert "https://registry.npmjs.org/left-pad" in urls
    assert "https://registry.npmjs.org/node-uuid" in urls
    assert "https://api.deps.dev/v3/systems/npm/packages/left-pad" in urls
    assert "https://api.deps.dev/v3/systems/pypi/packages/six" in urls
    assert sum("no-such" in u for u in urls) == 2
    assert len(items) == 7 + 2 + 2 + 2
    assert all(item.request.not_found_ok and item.request.method == "GET" for item in items)
    assert {url.split("/")[2] for url in urls} <= ALLOWED_HOSTS


def test_fallbacks_are_recorded_through_the_same_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_autopsy(monkeypatch, all_results(), GOOD_CALLS)
    code, out, _ = run_main(
        ["--out-dir", str(tmp_path), "--fallbacks"], transport=httpx.MockTransport(echo_handler)
    )
    assert code == 0 and "Recording fallback endpoints..." in out
    cassette = cassette_from_obj(
        json.loads((tmp_path / "anchors.cassette.json").read_text("utf-8"))
    )
    recorded = {e.url: e.status for e in cassette.entries}
    assert recorded["https://registry.npmjs.org/left-pad"] == 200
    assert recorded["https://api.deps.dev/v3/systems/pypi/packages/six"] == 200
    assert sorted(status for url, status in recorded.items() if "no-such" in url) == [404, 404]
    assert len(recorded) == len(GOOD_CALLS) + 13
    readme = (tmp_path / "README.md").read_text("utf-8")
    assert "--fallbacks" in readme


# ---------------------------------------------------------------------- the probe


def rec(interval: float, status: int | None, package: str = "p") -> Any:
    return script.ProbeRecord(interval, package, status, None if status else "ConnectError", None)


def series(*pairs: tuple[float, int | None]) -> list[Any]:
    return [rec(interval, status) for interval, status in pairs]


@pytest.mark.parametrize(
    ("records", "expected"),
    [
        ([], None),
        (series((3.0, 200), (3.0, 200), (3.0, 200)), 3.0),
        (series((3.0, 200), (3.0, 429)), None),
        (series((3.0, 429)), None),
        (series(*[(3.0, 200)] * 3, *[(2.0, 200)] * 3, (1.0, 200), (1.0, 429)), 2.0),
        (series(*[(3.0, 200)] * 3, (2.0, 200), (2.0, 429)), 3.0),
        (
            series(
                *[(i, 200) for i in (3.0, 3.0, 3.0, 2.0, 2.0, 2.0, 1.0, 1.0, 1.0, 0.5, 0.5, 0.5)]
            ),
            0.5,
        ),
        # errors other than 429 are ignored; a group of only errors is not a 429
        (series((3.0, 200), (3.0, None), (3.0, 500), (2.0, None)), 2.0),
    ],
)
def test_the_safe_interval_is_the_last_group_without_a_429(
    records: list[Any], expected: float | None
) -> None:
    assert script.safe_interval_seconds(records) == expected


def pypistats_world(
    sequence: Sequence[httpx.Response | Exception],
) -> tuple[httpx.AsyncClient, list[str]]:
    urls: list[str] = []
    replies = iter(sequence)

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        reply = next(replies)
        if isinstance(reply, Exception):
            raise reply
        return reply

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), urls


def test_the_probe_sends_twelve_sequential_requests_at_the_stated_intervals() -> None:
    client, urls = pypistats_world([json_ok({"data": {}})] * 12)
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async def run() -> list[Any]:
        async with client:
            found: list[Any] = await script.run_probe(client, sleep)
            return found

    records = asyncio.run(run())
    assert sleeps == [3.0] * 3 + [2.0] * 3 + [1.0] * 3 + [0.5] * 3
    assert [r.package for r in records] == list(script.PROBE_PACKAGES)
    assert urls == [f"https://pypistats.org/api/packages/{p}/recent" for p in script.PROBE_PACKAGES]
    assert script.safe_interval_seconds(records) == 0.5
    assert {r.status for r in records} == {200}


def test_the_probe_stops_at_the_first_429_and_keeps_only_the_rate_limit_headers() -> None:
    limited = json_ok(
        {"error": "x"},
        429,
        {
            "Retry-After": "30",
            "X-RateLimit-Remaining": "0",
            "RateLimit-Reset": "12",
            "Set-Cookie": "sid=" + TOKEN,
            "Server": "gunicorn",
        },
    )
    client, urls = pypistats_world(
        [json_ok({}), json_ok({}), json_ok({}), json_ok({}), limited, json_ok({})]
    )

    async def sleep(seconds: float) -> None:
        return None

    async def run() -> list[Any]:
        async with client:
            found: list[Any] = await script.run_probe(client, sleep)
            return found

    records = asyncio.run(run())
    assert len(records) == 5 and len(urls) == 5  # nothing after the 429
    last = records[-1]
    assert (last.interval_seconds, last.status, last.retry_after) == (2.0, 429, "30")
    assert dict(last.ratelimit_headers) == {"ratelimit-reset": "12", "x-ratelimit-remaining": "0"}
    assert TOKEN not in repr(records)
    assert script.safe_interval_seconds(records) == 3.0


def test_the_probe_records_a_connection_error_and_goes_on() -> None:
    request = httpx.Request("GET", "https://pypistats.org/x")
    client, _ = pypistats_world(
        [httpx.ConnectError("no route", request=request)] + [json_ok({})] * 11
    )

    async def sleep(seconds: float) -> None:
        return None

    async def run() -> list[Any]:
        async with client:
            found: list[Any] = await script.run_probe(client, sleep)
            return found

    records = asyncio.run(run())
    assert (records[0].status, records[0].error) == (None, "ConnectError")
    assert len(records) == 12


def test_probe_header_values_are_cleaned_and_bounded() -> None:
    assert script._clean_header_value("ok\x00\n\x7f" + "é" * 300) == "ok???" + "?" * 95


def test_the_probe_document_has_the_documented_keys() -> None:
    records = series((3.0, 200), (3.0, 200), (3.0, 200), (2.0, 429))
    document = script.probe_document(records, date(2026, 11, 10), 3.0)
    assert set(document) == {
        "host",
        "recorded_on",
        "configured_interval_seconds",
        "stopped_at_429",
        "safe_interval_seconds",
        "requests",
    }
    assert document["host"] == "pypistats.org" and document["recorded_on"] == "2026-11-10"
    assert document["stopped_at_429"] is True and document["safe_interval_seconds"] == 3.0
    assert document["configured_interval_seconds"] == 3.0
    assert set(document["requests"][0]) == {
        "interval_seconds",
        "package",
        "status",
        "error",
        "retry_after",
        "ratelimit_headers",
    }
    json.dumps(document)  # serialisable


def test_main_with_the_probe_writes_the_probe_file_and_a_readme_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_autopsy(monkeypatch, all_results(), GOOD_CALLS)
    code, out, _ = run_main(
        ["--out-dir", str(tmp_path), "--probe-pypistats"],
        transport=httpx.MockTransport(echo_handler),
    )
    assert code == 0 and written(tmp_path) == [
        "README.md",
        "anchors.cassette.json",
        "pypistats_probe.json",
    ]
    probe = json.loads((tmp_path / "pypistats_probe.json").read_text("utf-8"))
    assert probe["safe_interval_seconds"] == 0.5 and probe["stopped_at_429"] is False
    # the default pypistats spacing (1.2 s since the probe, SRC-S9-4)
    assert probe["configured_interval_seconds"] == 1.2 and len(probe["requests"]) == 12
    assert "safe_interval_seconds = 0.5" in out
    assert "| pypistats_probe.json |" in (tmp_path / "README.md").read_text("utf-8")


def test_the_probe_never_changes_the_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = script.SourcesConfig.default(contact=CONTACT).hosts["pypistats.org"]
    stub_autopsy(monkeypatch, all_results(), GOOD_CALLS)

    def limited(request: httpx.Request) -> httpx.Response:
        return (
            json_ok({"error": "x"}, 429)
            if "pypistats" in str(request.url)
            else echo_handler(request)
        )

    run_main(
        ["--out-dir", str(tmp_path), "--probe-pypistats"], transport=httpx.MockTransport(limited)
    )
    probe = json.loads((tmp_path / "pypistats_probe.json").read_text("utf-8"))
    assert probe["safe_interval_seconds"] is None and probe["stopped_at_429"] is True
    after = script.SourcesConfig.default(contact=CONTACT).hosts["pypistats.org"]
    assert after == before


# ------------------------------------------------------------------ the command


def test_arguments_and_the_command_line_recorded_in_the_readme() -> None:
    plain = script.parse_args([])
    assert (plain.fallbacks, plain.probe_pypistats, plain.strict) == (False, False, False)
    assert plain.out_dir == script.RECORDED_DIR
    assert script.command_line(plain) == "uv run python ../scripts/record_source_responses.py"
    full = script.parse_args(["--fallbacks", "--probe-pypistats", "--strict"])
    assert script.command_line(full).endswith("--fallbacks --probe-pypistats --strict")
    with pytest.raises(SystemExit):
        script.parse_args(["--no-such-option"])


def test_default_paths_are_the_documented_ones() -> None:
    root = Path(script.__file__).resolve().parent.parent
    assert root / "backend/core/sources/tests/fixtures/recorded" == script.RECORDED_DIR
    assert root / "backend/core/scoring/tests/fixtures/anchors" == script.ANCHOR_FIXTURES
    assert script.AS_OF == AS_OF


def test_missing_anchor_fixtures_are_reported(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="request.json is missing"):
        script.load_anchor_fixtures(tmp_path)
    for name in NAMES:
        (tmp_path / f"{name}.json").write_text(json.dumps({"as_of": "2026-01-01", "purl": "x"}))
    with pytest.raises(ValueError, match="as_of"):
        script.load_anchor_fixtures(tmp_path)


# --------------------------------------------------------------- static guarantees


def _enclosing_functions(tree: ast.AST) -> list[tuple[ast.AST, str | None]]:
    out: list[tuple[ast.AST, str | None]] = []

    def walk(node: ast.AST, current: str | None) -> None:
        for child in ast.iter_child_nodes(node):
            name = (
                child.name if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) else current
            )
            out.append((child, name))
            walk(child, name)

    walk(tree, None)
    return out


def test_the_environment_is_read_in_main_only() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    uses = [
        function
        for node, function in _enclosing_functions(tree)
        if isinstance(node, ast.Attribute) and node.attr in ("environ", "getenv")
    ]
    assert uses, "the script should read os.environ somewhere"
    assert set(uses) == {"main"}, "os.environ / os.getenv are read in main and nowhere else (D7)"


def test_everything_printed_goes_through_the_redacting_emit_or_is_a_fixed_error_in_main() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    prints = [
        (node, function)
        for node, function in _enclosing_functions(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "print"
    ]
    assert prints
    for node, function in prints:
        assert isinstance(node, ast.Call)
        assert function in ("main", "emit"), f"print() in {function}"
        first = node.args[0]
        # `emit` prints a redacted string; `main` prints either that or a message built from
        # fixed text, the exception type name and `redact(...)`.
        text = ast.unparse(first)
        assert function != "emit" or text.startswith("redact(message, secret)"), text
        assert "env.token" not in text and "{secret" not in text, text


def test_importing_the_script_has_no_side_effects() -> None:
    # `_load_script` ran at import time of this test module: it printed nothing, wrote nothing,
    # and the backend directory is on the path for `python ../scripts/...`.
    assert str(script.BACKEND) in sys.path
    assert script.main.__module__ == "record_source_responses"


def test_the_script_uses_the_cassette_types_of_the_pure_half_only() -> None:
    signals: Signals = signals_from_fixture(FIXTURES["six"])
    assert signals.purl.startswith("pkg:pypi/six@")
    assert script.Cassette.__module__ == "core.sources.cassette"
