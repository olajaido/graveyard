"""Tests for the CLI test support module (T4.4)."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

import httpx
import pytest

from cli.tests.support import (
    DEFAULT_SBOM_DIR,
    STUB_STDERR_SENTINEL,
    OsvAgnosticUse,
    ReplayLog,
    StubMode,
    make_source_result,
    make_stub_syft,
    recorded_github,
    shape,
    single_repo_github,
    subset_replay_transport,
    version_agnostic_osv,
)
from core.scoring.types import Signals
from core.sources.cassette import thaw_json
from core.sources.parse.osv import parse_query_results
from core.sources.tests import recorded as rec

OSV = rec.OSV_QUERYBATCH_URL
NPM_LAST_WEEK = "https://api.npmjs.org/downloads/point/last-week/"


def _run(path: Path, *args: str, timeout: float = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(path), *args], capture_output=True, text=True, timeout=timeout, check=False
    )


# ------------------------------------------------------------------------------ stub Syft


def test_stub_version(tmp_path: Path) -> None:
    stub = make_stub_syft(tmp_path, version="9.9.9")
    result = _run(stub.path, "--version")
    assert result.stdout == "syft 9.9.9\n"
    assert stub.calls() == []


def test_stub_ok_prints_sbom_of_segment(tmp_path: Path) -> None:
    stub = make_stub_syft(tmp_path)
    result = _run(stub.path, "dir:/some/where/web", "-q", "-o", "cyclonedx-json")
    assert result.returncode == 0
    doc = json.loads(result.stdout)
    assert isinstance(doc, dict)
    purls = {c.get("purl") for c in doc["components"]}
    assert rec.anchor_purl("request") in purls
    assert rec.anchor_purl("express") in purls
    assert rec.anchor_purl("pycrypto") not in purls
    api = json.loads(_run(stub.path, "dir:/x/api").stdout)
    assert rec.anchor_purl("pycrypto") in {c.get("purl") for c in api["components"]}


def test_stub_log_records_argv_and_env_keys(tmp_path: Path) -> None:
    stub = make_stub_syft(tmp_path)
    _run(stub.path, "dir:/a/web", "-q")
    _run(stub.path, "dir:/a/api")
    calls = stub.calls()
    assert [c["argv"] for c in calls] == [["dir:/a/web", "-q"], ["dir:/a/api"]]
    assert isinstance(calls[0]["env_keys"], list)
    assert calls[0]["env_keys"] == sorted(calls[0]["env_keys"])


def test_stub_fail(tmp_path: Path) -> None:
    result = _run(make_stub_syft(tmp_path, mode="fail").path, "dir:/a/web")
    assert result.returncode == 2
    assert STUB_STDERR_SENTINEL in result.stderr
    assert result.stdout == ""


def test_stub_sleep_times_out(tmp_path: Path) -> None:
    stub = make_stub_syft(tmp_path, mode="sleep")
    with pytest.raises(subprocess.TimeoutExpired):
        subprocess.run([str(stub.path), "dir:/a/web"], timeout=0.5, check=False)


def test_stub_garbage_and_array(tmp_path: Path) -> None:
    garbage = _run(make_stub_syft(tmp_path, mode="garbage").path, "dir:/a/web")
    assert garbage.stdout.strip() == "not json"
    with pytest.raises(ValueError):
        json.loads(garbage.stdout)
    (tmp_path / "arr").mkdir()
    array = _run(make_stub_syft(tmp_path / "arr", mode="array").path, "dir:/a/web")
    assert json.loads(array.stdout) == []


def test_stub_big(tmp_path: Path) -> None:
    result = _run(make_stub_syft(tmp_path, mode="big").path, "dir:/a/web")
    assert len(result.stdout) > 1024 * 1024
    assert isinstance(json.loads(result.stdout), dict)


def test_stub_modes_are_literals(tmp_path: Path) -> None:
    mode: StubMode = "ok"
    stub = make_stub_syft(tmp_path, mode=mode, sbom_dir=DEFAULT_SBOM_DIR)
    text = stub.path.read_text(encoding="utf-8")
    assert text.startswith("#!")
    assert str(DEFAULT_SBOM_DIR) in text


# --------------------------------------------------------------------------- transport


def _post(transport: httpx.MockTransport, body: object) -> httpx.Response:
    with httpx.Client(transport=transport) as client:
        return client.post(OSV, json=body)


def _get(transport: httpx.MockTransport, url: str) -> httpx.Response:
    with httpx.Client(transport=transport) as client:
        return client.get(url)


def _recorded_batch() -> tuple[Sequence[object], Sequence[object]]:
    item = rec.entry(OSV, "POST")
    request = thaw_json(item.request_body)
    response = thaw_json(item.response_body)
    assert isinstance(request, dict) and isinstance(response, dict)
    queries, results = request["queries"], response["results"]
    assert isinstance(queries, list) and isinstance(results, list)
    return queries, results


def test_osv_single_query_gets_recorded_result() -> None:
    transport, log = subset_replay_transport(rec.cassette())
    queries, results = _recorded_batch()
    query = {"package": {"ecosystem": "npm", "name": "request"}, "version": "2.88.2"}
    assert queries[4] == query
    response = _post(transport, {"queries": [query]})
    assert response.status_code == 200
    assert response.json() == {"results": [results[4]]}
    assert log.unmatched == []


def test_osv_two_queries_in_order() -> None:
    transport, log = subset_replay_transport(rec.cassette())
    queries, results = _recorded_batch()
    response = _post(transport, {"queries": [queries[4], queries[0]]})
    assert response.json() == {"results": [results[4], results[0]]}
    assert log.unmatched == []


def test_derived_osv_answer_is_accepted_by_parser() -> None:
    transport, _ = subset_replay_transport(rec.cassette())
    queries, _results = _recorded_batch()
    response = _post(transport, {"queries": [queries[4], queries[6]]})
    parsed = parse_query_results(response.json(), 2)
    assert parsed is not None
    assert len(parsed) == 2


def test_npm_single_name_answered_from_bulk() -> None:
    transport, log = subset_replay_transport(rec.cassette())
    bulk = rec.body(rec.NPM_BULK_URL)
    response = _get(transport, NPM_LAST_WEEK + "request")
    assert response.status_code == 200
    assert response.json() == bulk["request"]
    assert log.unmatched == []


def test_unknown_requests_are_logged_as_unmatched() -> None:
    transport, log = subset_replay_transport(rec.cassette())
    unknown = {"package": {"ecosystem": "npm", "name": "nope"}, "version": "0.0.1"}
    with pytest.raises(httpx.ConnectError):
        _post(transport, {"queries": [unknown]})
    with pytest.raises(httpx.ConnectError):
        _get(transport, NPM_LAST_WEEK + "nope")
    with pytest.raises(httpx.ConnectError):
        _get(transport, "https://example.org/other")
    assert [u.url for u in log.unmatched] == [
        OSV,
        NPM_LAST_WEEK + "nope",
        "https://example.org/other",
    ]


def test_recorded_urls_pass_through_unchanged() -> None:
    transport, log = subset_replay_transport(rec.cassette())
    url = "https://registry.npmjs.org/request"
    response = _get(transport, url)
    assert response.json() == rec.body(url)
    assert _get(transport, rec.NPM_BULK_URL).json() == rec.body(rec.NPM_BULK_URL)
    assert len(log.matched) == 2
    assert log.unmatched == []


# --------------------------------------------------------------------------- builders


def test_make_source_result_has_all_keys() -> None:
    from datetime import date

    from core.sources.model import EVIDENCE_KEYS

    result = make_source_result(Signals(purl="pkg:npm/a@1.0.0", as_of=date(2026, 11, 3)))
    assert tuple(result.evidence) == EVIDENCE_KEYS
    assert result.error is None
    assert all(e.value is None for e in result.evidence.values())


def test_shape() -> None:
    value = {"a": [{"b": 1, "c": "x"}, {"zz": 1}], "d": [], "e": None, "f": True, "g": 1.5}
    assert shape(value) == {
        "a": {"b": "integer", "c": "string"},
        "d": "empty",
        "e": "null",
        "f": "boolean",
        "g": "number",
    }


def test_shape_bool_is_not_integer_and_int_is_not_number() -> None:
    assert shape(True) == "boolean"
    assert shape(False) == "boolean"
    assert shape(0) == "integer"
    assert shape(-7) == "integer"
    assert shape(1.0) == "number"
    assert shape(0.0) == "number"


def test_a_subset_of_the_recorded_bulk_downloads_url_is_derived() -> None:
    transport, log = subset_replay_transport(rec.cassette())
    url = f"{NPM_LAST_WEEK}express,left-pad,moment"
    response = _get(transport, url)
    body = response.json()
    assert list(body) == ["express", "left-pad", "moment"]
    assert body["express"] == rec.body(rec.NPM_BULK_URL)["express"]
    assert log.unmatched == []
    with pytest.raises(httpx.ConnectError):
        _get(transport, f"{NPM_LAST_WEEK}express,not-recorded")
    assert [u.url for u in log.unmatched] == [f"{NPM_LAST_WEEK}express,not-recorded"]


# ------------------------------------------------------------ version-agnostic OSV wrapper


def _agnostic() -> tuple[httpx.MockTransport, OsvAgnosticUse, ReplayLog]:
    cassette = rec.cassette()
    inner, log = subset_replay_transport(cassette)
    wrapped, use = version_agnostic_osv(inner, cassette)
    return wrapped, use, log


def test_agnostic_osv_answers_other_version_with_recorded_answer() -> None:
    wrapped, use, log = _agnostic()
    _queries, results = _recorded_batch()
    other = {"package": {"ecosystem": "npm", "name": "request"}, "version": "9.9.9"}
    response = _post(wrapped, {"queries": [other]})
    assert response.json() == {"results": [results[4]]}
    assert use.uses == 1
    assert use.rewritten == [("request", "9.9.9", "2.88.2")]
    assert log.unmatched == []


def test_agnostic_osv_leaves_recorded_and_unknown_queries_alone() -> None:
    wrapped, use, log = _agnostic()
    queries, results = _recorded_batch()
    assert _post(wrapped, {"queries": [queries[4]]}).json() == {"results": [results[4]]}
    assert use.uses == 0
    unknown = {"package": {"ecosystem": "npm", "name": "nope"}, "version": "1.0.0"}
    with pytest.raises(httpx.ConnectError):
        _post(wrapped, {"queries": [unknown]})
    assert use.uses == 0
    assert len(log.unmatched) == 1


def test_agnostic_osv_does_not_touch_other_requests() -> None:
    wrapped, use, _log = _agnostic()
    url = "https://registry.npmjs.org/request"
    assert _get(wrapped, url).json() == rec.body(url)
    assert use.uses == 0


# ------------------------------------------------------------ single-repository GitHub wrapper

GRAPHQL = "https://api.github.com/graphql"


def _github(transport: httpx.MockTransport, variables: dict[str, str]) -> httpx.Response:
    with httpx.Client(transport=transport) as client:
        return client.post(GRAPHQL, json={"query": "query", "variables": variables})


def _single() -> tuple[httpx.MockTransport, ReplayLog]:
    cassette = rec.cassette()
    inner, log = subset_replay_transport(cassette)
    return single_repo_github(inner, log, cassette), log


def test_single_repo_github_returns_the_recorded_object_as_r0() -> None:
    recorded = recorded_github(rec.cassette())
    assert recorded is not None
    rvars, data = recorded
    index = 3  # any recorded repository; not the first, so r0 is not the identity
    response = _github(_single()[0], {"o0": rvars[f"o{index}"], "n0": rvars[f"n{index}"]})
    assert response.status_code == 200
    assert response.json() == {"data": {"rateLimit": data["rateLimit"], "r0": data[f"r{index}"]}}


def test_single_repo_github_logs_the_derived_answer_as_matched() -> None:
    recorded = recorded_github(rec.cassette())
    assert recorded is not None
    rvars, _data = recorded
    transport, log = _single()
    _github(transport, {"o0": rvars["o2"], "n0": rvars["n2"]})
    assert log.matched == [f"github-single:{rvars['o2']}/{rvars['n2']}"]
    assert log.unmatched == []


def test_single_repo_github_unrecorded_repo_falls_through_to_inner() -> None:
    transport, log = _single()
    with pytest.raises(httpx.ConnectError):
        _github(transport, {"o0": "nobody", "n0": "not-recorded"})
    assert [u.url for u in log.unmatched] == [GRAPHQL]
    assert log.matched == []


def test_single_repo_github_multi_repo_body_falls_through_unchanged() -> None:
    cassette = rec.cassette()
    item = next(e for e in cassette.entries if e.method == "POST" and e.url == GRAPHQL)
    request = thaw_json(item.request_body)
    response = thaw_json(item.response_body)
    assert isinstance(request, dict) and isinstance(response, dict)
    transport, log = _single()
    with httpx.Client(transport=transport) as client:
        answer = client.post(GRAPHQL, json=request)
    assert answer.json() == response  # the recorded batch itself, not rewritten
    assert log.matched == [log.matched[0]] and not log.matched[0].startswith("github-single")
    assert log.unmatched == []
