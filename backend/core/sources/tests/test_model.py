"""Unit tests for ``core.sources.model`` (SRC-API-2/3, SRC-SEC-3, SRC-WARN-2/3)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from types import MappingProxyType
from typing import Any, cast

import pytest

from core.scoring.types import Signals
from core.sources.model import (
    EVIDENCE_KEYS,
    MAX_DETAIL,
    MAX_INPUT_PURL,
    SOURCE_NAMES,
    WARNING_CODES,
    BatchResult,
    Evidence,
    ItemError,
    JsonValue,
    SourceResult,
    SourceStats,
    SourceWarning,
)
from core.sources.secret import REDACTED

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
URL = "https://api.deps.dev/v3/example"
SHAPED = "ghp_" + "A" * 36  # token-shaped; built at runtime


def empty_evidence() -> dict[str, Evidence]:
    return {key: Evidence(None, None, None) for key in EVIDENCE_KEYS}


def signals() -> Signals:
    return Signals(purl="pkg:npm/left-pad@1.3.0", as_of=date(2026, 11, 3))


def ok_result(**kwargs: Any) -> SourceResult:
    return SourceResult(
        input_purl="pkg:npm/left-pad@1.3.0",
        signals=signals(),
        error=None,
        evidence=empty_evidence(),
        **kwargs,
    )


def warning(**kwargs: Any) -> SourceWarning:
    fields: dict[str, Any] = {
        "code": "TIMEOUT",
        "source": "osv",
        "signals": ("s7_advisories",),
        "detail": "timed out",
    }
    fields.update(kwargs)
    return SourceWarning(**fields)


# --- closed sets ----------------------------------------------------------------------------


def test_evidence_keys_are_the_eleven_signals_in_anchor_order() -> None:
    assert len(EVIDENCE_KEYS) == 11
    assert len(set(EVIDENCE_KEYS)) == 11
    assert EVIDENCE_KEYS[0] == "s1_declared_death"
    assert EVIDENCE_KEYS[-1] == "s9_weekly_downloads"


def test_closed_sets_hold_expected_members() -> None:
    assert {"TIMEOUT", "OUT_OF_DOMAIN", "INTERNAL_ERROR", "GITHUB_DISABLED"} <= WARNING_CODES
    assert {"depsdev", "osv", "github", "pypistats", "internal"} <= SOURCE_NAMES


def test_every_closed_code_is_accepted() -> None:
    for code in WARNING_CODES:
        assert warning(code=code).code == code
    for source in SOURCE_NAMES:
        assert warning(source=source).source == source


def test_unknown_warning_code_is_rejected() -> None:
    with pytest.raises(ValueError):
        warning(code="NOPE")


def test_unknown_warning_source_is_rejected() -> None:
    with pytest.raises(ValueError):
        warning(source="nope")


def test_unknown_signal_key_in_warning_is_rejected() -> None:
    with pytest.raises(ValueError):
        warning(signals=("s99_nonsense",))


def test_unknown_item_error_code_is_rejected() -> None:
    bad: Any = "NOPE"
    with pytest.raises(ValueError):
        ItemError(code=bad, detail="x")


# --- Evidence -------------------------------------------------------------------------------


def test_evidence_without_value_needs_nothing() -> None:
    evidence = Evidence(None, None, None)
    assert evidence.value is None
    assert evidence.extra_source_urls == ()
    assert evidence.note is None


@pytest.mark.parametrize("value", [0, False, "", [], {}, 1, "x", 2.5])
def test_evidence_with_value_needs_url_and_time(value: Any) -> None:
    assert Evidence(value, URL, NOW).value == value
    with pytest.raises(ValueError):
        Evidence(value, None, NOW)
    with pytest.raises(ValueError):
        Evidence(value, URL, None)
    with pytest.raises(ValueError):
        Evidence(value, None, None)


def test_evidence_accepts_utc_instants_in_any_utc_spelling() -> None:
    assert Evidence(1, URL, datetime(2026, 11, 3, tzinfo=UTC)).fetched_at is not None


@pytest.mark.parametrize(
    "moment",
    [
        datetime(2026, 11, 3, 12, 0),  # naive
        datetime(2026, 11, 3, 12, 0, tzinfo=timezone(timedelta(hours=1))),
        datetime(2026, 11, 3, 12, 0, tzinfo=timezone(timedelta(hours=-5))),
    ],
)
def test_evidence_rejects_naive_and_non_utc_fetched_at(moment: datetime) -> None:
    with pytest.raises(ValueError):
        Evidence(1, URL, moment)
    with pytest.raises(ValueError):
        Evidence(None, None, moment)


def test_evidence_is_frozen() -> None:
    evidence = Evidence(1, URL, NOW)
    with pytest.raises(AttributeError):
        cast(Any, evidence).value = 2


def test_extra_source_urls_are_sorted_and_unique() -> None:
    evidence = Evidence(1, URL, NOW, extra_source_urls=("https://b", "https://a", "https://b"))
    assert evidence.extra_source_urls == ("https://a", "https://b")


def test_extra_source_urls_never_repeat_the_primary_url_after_redaction() -> None:
    """Two URLs that differ only in a token-shaped part are equal once redacted (T6.4 finding)."""
    other = SHAPED[:-1] + ("0" if SHAPED[-1] != "0" else "1")
    evidence = Evidence(
        1,
        f"https://example.test/{SHAPED}",
        NOW,
        extra_source_urls=(f"https://example.test/{other}", "https://a"),
    )
    assert evidence.source_url == f"https://example.test/{REDACTED}"
    assert evidence.extra_source_urls == ("https://a",)


def test_evidence_redacts_token_shapes_everywhere() -> None:
    evidence = Evidence(
        value={SHAPED: [SHAPED, {"k": f"x {SHAPED} y"}], "n": 1},
        source_url=f"https://example.test/{SHAPED}",
        fetched_at=NOW,
        extra_source_urls=(f"https://example.test/{SHAPED}",),
        note=f"note {SHAPED}",
    )
    text = repr(evidence)
    assert SHAPED not in text
    assert REDACTED in text
    assert evidence.value == {REDACTED: [REDACTED, {"k": f"x {REDACTED} y"}], "n": 1}
    assert evidence.note == f"note {REDACTED}"


def test_evidence_clean_value_is_unchanged() -> None:
    value: JsonValue = {"a": [1, 2.5, "x", None, True], "b": {"c": "d"}}
    assert Evidence(value, URL, NOW).value == value


@pytest.mark.parametrize("value", [float("nan"), float("inf"), (1, 2), {1, 2}, object()])
def test_evidence_rejects_non_json_values(value: Any) -> None:
    with pytest.raises(ValueError):
        Evidence(value, URL, NOW)


def test_evidence_rejects_non_string_keys_and_deep_nesting() -> None:
    bad_key: Any = {1: "x"}
    with pytest.raises(ValueError):
        Evidence(bad_key, URL, NOW)
    deep: Any = "leaf"
    for _ in range(40):
        deep = [deep]
    with pytest.raises(ValueError):
        Evidence(deep, URL, NOW)


# --- SourceWarning / ItemError --------------------------------------------------------------


def test_warning_detail_is_truncated_to_200() -> None:
    assert len(warning(detail="x" * 500).detail) == MAX_DETAIL == 200
    assert warning(detail="x" * 200).detail == "x" * 200


def test_warning_redacts_before_truncating() -> None:
    out = warning(detail="a" * 190 + SHAPED + "b" * 30).detail
    assert "ghp_" not in out
    assert out == "a" * 190 + REDACTED
    assert len(out) == 200


def test_warning_signals_are_sorted_and_unique() -> None:
    w = warning(signals=("s7_advisories", "s1_declared_death", "s7_advisories"))
    assert w.signals == ("s1_declared_death", "s7_advisories")


def test_warning_keeps_status() -> None:
    assert warning(status=503).status == 503
    assert warning().status is None


def test_item_error_truncates_and_redacts() -> None:
    error = ItemError("INVALID_PURL", "y" * 500)
    assert len(error.detail) == 200
    assert SHAPED not in ItemError("INVALID_PURL", SHAPED).detail


# --- SourceResult ---------------------------------------------------------------------------


def test_result_with_signals_and_full_evidence_is_valid() -> None:
    result = ok_result()
    assert result.error is None
    assert list(result.evidence) == list(EVIDENCE_KEYS)


def test_result_with_error_and_no_evidence_is_valid() -> None:
    result = SourceResult("not a purl", None, ItemError("INVALID_PURL", "bad"))
    assert result.signals is None
    assert dict(result.evidence) == {}


def test_result_needs_exactly_one_of_signals_and_error() -> None:
    with pytest.raises(ValueError):
        SourceResult("p", None, None)
    with pytest.raises(ValueError):
        SourceResult("p", signals(), ItemError("INVALID_PURL", "bad"), evidence=empty_evidence())


def test_result_evidence_must_be_exactly_the_eleven_keys() -> None:
    short = empty_evidence()
    del short["s9_weekly_downloads"]
    with pytest.raises(ValueError):
        SourceResult("p", signals(), None, evidence=short)
    extra = empty_evidence()
    extra["s99_extra"] = Evidence(None, None, None)
    with pytest.raises(ValueError):
        SourceResult("p", signals(), None, evidence=extra)
    with pytest.raises(ValueError):
        SourceResult("p", signals(), None)


def test_result_with_error_rejects_evidence() -> None:
    with pytest.raises(ValueError):
        SourceResult(
            "p",
            None,
            ItemError("INVALID_PURL", "bad"),
            evidence={"s2_latest_release_at": empty_evidence()["s2_latest_release_at"]},
        )


def test_result_evidence_follows_key_order_not_input_order() -> None:
    reversed_evidence = dict(reversed(list(empty_evidence().items())))
    result = SourceResult("p", signals(), None, evidence=reversed_evidence)
    assert list(result.evidence) == list(EVIDENCE_KEYS)


def test_result_evidence_is_read_only() -> None:
    source = empty_evidence()
    result = SourceResult("p", signals(), None, evidence=source)
    assert isinstance(result.evidence, MappingProxyType)
    view: Any = result.evidence
    with pytest.raises(TypeError):
        view["s2_latest_release_at"] = Evidence(None, None, None)
    with pytest.raises(TypeError):
        del view["s2_latest_release_at"]
    # Changing the caller's dict afterwards does not reach the result.
    source["s2_latest_release_at"] = Evidence(1, URL, NOW)
    assert result.evidence["s2_latest_release_at"].value is None


def test_error_result_evidence_is_read_only_too() -> None:
    result = SourceResult("p", None, ItemError("MISSING_VERSION", "x"))
    assert isinstance(result.evidence, MappingProxyType)
    view: Any = result.evidence
    with pytest.raises(TypeError):
        view["k"] = 1


def test_result_input_purl_is_truncated() -> None:
    result = SourceResult("p" * 1000, None, ItemError("INVALID_PURL", "x"))
    assert len(result.input_purl) == MAX_INPUT_PURL == 200


def test_result_input_purl_is_redacted() -> None:
    result = SourceResult(f"pkg:{SHAPED}", None, ItemError("INVALID_PURL", "x"))
    assert SHAPED not in result.input_purl


def test_result_warnings_are_sorted_and_unique() -> None:
    late = warning(code="TIMEOUT")
    early = warning(code="HTTP_STATUS", status=500)
    result = ok_result(warnings=(late, early, late))
    assert result.warnings == (early, late)


def test_result_warning_order_is_independent_of_input_order() -> None:
    a = warning(code="HTTP_STATUS", status=500)
    b = warning(code="HTTP_STATUS", status=None)
    c = warning(code="INVALID_JSON", source="depsdev")
    assert ok_result(warnings=(a, b, c)).warnings == ok_result(warnings=(c, b, a)).warnings
    assert ok_result(warnings=(a, b, c)).warnings[0] == b  # no status sorts first


def test_result_rejects_unknown_repo_via() -> None:
    bad: Any = "somewhere"
    with pytest.raises(ValueError):
        ok_result(repo_via=bad)
    assert ok_result(repo_via="registry").repo_via == "registry"


# --- SourceStats / BatchResult --------------------------------------------------------------


def test_stats_mappings_are_sorted_and_read_only() -> None:
    stats = SourceStats(
        requests={"osv": 1, "depsdev": 2},
        failures={"github": 1},
        cache_hits=3,
        cache_misses=4,
        s9_skipped=5,
    )
    assert list(stats.requests) == ["depsdev", "osv"]
    assert isinstance(stats.requests, MappingProxyType)
    assert isinstance(stats.failures, MappingProxyType)
    view: Any = stats.requests
    with pytest.raises(TypeError):
        view["osv"] = 9
    assert (stats.cache_hits, stats.cache_misses, stats.s9_skipped) == (3, 4, 5)


def test_stats_reject_unknown_sources() -> None:
    with pytest.raises(ValueError):
        SourceStats({"nope": 1}, {}, 0, 0, 0)
    with pytest.raises(ValueError):
        SourceStats({}, {"nope": 1}, 0, 0, 0)


def test_batch_result_holds_results_as_a_tuple_in_order() -> None:
    first = SourceResult("a", None, ItemError("INVALID_PURL", "x"))
    second = ok_result()
    stats = SourceStats({}, {}, 0, 0, 0)
    batch = BatchResult(results=cast(Any, [first, second]), stats=stats)
    assert batch.results == (first, second)
    assert isinstance(batch.results, tuple)
    assert batch.stats is stats


# --- userinfo never reaches evidence (SRC-SEC-3) ----------------------------------------------


def test_evidence_strips_userinfo_from_every_url() -> None:
    evidence = Evidence(
        1,
        "https://user:password@api.deps.dev/v3/example",
        NOW,
        extra_source_urls=(
            "https://u2:pw2@api.osv.dev/v1/vulns/GHSA-1",
            "https://api.osv.dev/v1/querybatch",
        ),
    )
    assert evidence.source_url == "https://api.deps.dev/v3/example"
    assert evidence.extra_source_urls == (
        "https://api.osv.dev/v1/querybatch",
        "https://api.osv.dev/v1/vulns/GHSA-1",
    )
    text = repr(evidence)
    for secret in ("user", "password", "u2", "pw2"):
        assert secret not in text


def test_evidence_with_no_value_strips_userinfo_too() -> None:
    evidence = Evidence(None, "https://user:password@api.deps.dev/x", None)
    assert evidence.source_url == "https://api.deps.dev/x"


def test_evidence_stripping_can_make_an_extra_url_equal_the_primary() -> None:
    evidence = Evidence(
        1,
        "https://api.deps.dev/x",
        NOW,
        extra_source_urls=("https://u:p@api.deps.dev/x",),
    )
    assert evidence.extra_source_urls == ()


def test_evidence_urls_without_userinfo_are_unchanged() -> None:
    evidence = Evidence(1, URL, NOW, extra_source_urls=("https://registry.npmjs.org/%40a%2Fb",))
    assert evidence.source_url == URL
    assert evidence.extra_source_urls == ("https://registry.npmjs.org/%40a%2Fb",)
