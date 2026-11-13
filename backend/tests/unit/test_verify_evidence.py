"""Unit tests for scripts/verify_evidence.py (pure logic only; no network)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "verify_evidence.py"
_spec = importlib.util.spec_from_file_location("verify_evidence", _SCRIPT)
assert _spec and _spec.loader
ve = importlib.util.module_from_spec(_spec)
sys.modules["verify_evidence"] = ve
_spec.loader.exec_module(ve)


def test_collapse_ws() -> None:
    assert ve.collapse_ws("  a \n\t b\u00a0 c ") == "a b c"


def test_match_raw_with_whitespace_runs() -> None:
    r = ve.match_quote("is no longer\nmaintained", "this is   no longer \n maintained.")
    assert r.found and r.view == "raw"


def test_match_html_stripped_and_unescaped() -> None:
    body = "<p>Don&#39;t use <b>this</b> package</p>"
    r = ve.match_quote("Don't use this package", body)
    assert r.found and r.view == "html"


def test_match_html_tags_between_words_without_space() -> None:
    r = ve.match_quote("foo bar", "<p>foo</p><p>bar</p>")
    assert r.found and r.view == "html"


def test_match_json_string_values() -> None:
    body = '{"deprecated": "use \\"x\\" instead", "n": 1}'
    r = ve.match_quote('use "x" instead', body)
    assert r.found and r.view == "json"


def test_json_keys_do_not_count() -> None:
    assert ve.match_quote("secretkey", '{"secretkey": "v"}').view != "json"


def test_no_case_folding() -> None:
    assert not ve.match_quote("deprecated", "DEPRECATED").found


def test_no_quote_folding() -> None:
    assert not ve.match_quote("don't", "don\u2019t").found


def test_empty_quote_never_matches() -> None:
    assert not ve.match_quote("   ", "anything").found


def test_not_found() -> None:
    assert not ve.match_quote("absent", "<p>present</p>").found


@pytest.mark.parametrize(
    "quote,json_body,expected",
    [
        ("2026-05-14T10:11:12Z", False, True),
        ("2026-05-14T10:11:12.123456+00:00", False, True),
        ('"upload_time": "2026-05-14T10:11:12"', False, True),
        ("upload_time_iso_8601", False, True),
        ('"created_at": "2026-05-14"', False, True),
        ('"time": {"1.0": "x"}', False, True),
        ("2026-05-14", True, True),
        ("2026-05-14", False, False),
        ("Released 2026-05-14", True, False),
        ("2.34.2 (2026-05-14)", False, False),
        ("Release notes for the first time", False, False),
    ],
)
def test_is_machine_timestamp(quote: str, json_body: bool, expected: bool) -> None:
    assert ve.is_machine_timestamp(quote, json_body=json_body) is expected


def test_amendment_flag_only_for_alive() -> None:
    assert ve.amendment_1_3_flag("alive", "2026-05-14T10:11:12Z")
    assert not ve.amendment_1_3_flag("dead", "2026-05-14T10:11:12Z")


def _row(label: str = "finished-healthy", **kw: str) -> dict[str, str]:
    base = {
        "ecosystem": "pypi",
        "name": "p",
        "version": "1.0",
        "label": label,
        "evidence_kind": "feature_complete_readme",
        "evidence_url": "https://example.org/x",
        "evidence_quote": "complete",
    }
    base.update(kw)
    return base


def test_still_works_flag() -> None:
    k = ("pypi", "p", "1.0")
    assert ve.still_works_fail_flag(_row(), {k: "pass"}) == ""
    assert ve.still_works_fail_flag(_row(), {k: "pass_install_only"}) == ""
    assert "fail_import" in ve.still_works_fail_flag(_row(), {k: "fail_import"})
    assert ve.still_works_fail_flag(_row(), {}) == "no still-works result"
    assert ve.still_works_fail_flag(_row("dead"), {k: "fail_import"}) == ""


@pytest.mark.parametrize(
    "addr,blocked",
    [
        ("127.0.0.1", True),
        ("::1", True),
        ("10.1.2.3", True),
        ("192.168.0.1", True),
        ("172.16.5.5", True),
        ("169.254.169.254", True),
        ("fe80::1", True),
        ("fc00::1", True),
        ("0.0.0.0", True),
        ("::ffff:127.0.0.1", True),
        ("100.64.0.1", True),
        ("8.8.8.8", False),
        ("2606:4700:4700::1111", False),
        ("not-an-ip", True),
    ],
)
def test_blocked_address_reason(addr: str, blocked: bool) -> None:
    assert bool(ve.blocked_address_reason(addr)) is blocked


def test_select_public_address_refuses_if_any_private() -> None:
    infos = [(0, 0, 0, "", ("8.8.8.8", 443)), (0, 0, 0, "", ("10.0.0.1", 443))]
    addr, reason = ve.select_public_address(infos)
    assert addr == "" and "private" in reason
    ok = [(0, 0, 0, "", ("8.8.8.8", 443))]
    assert ve.select_public_address(ok) == ("8.8.8.8", "")
    assert ve.select_public_address([])[1] == "no addresses"


@pytest.mark.parametrize(
    "url,refused",
    [
        ("https://example.org/a", False),
        ("http://example.org/a", True),
        ("ftp://example.org/a", True),
        ("https:///nohost", True),
        ("https://user:pw@example.org/", True),
    ],
)
def test_check_url(url: str, refused: bool) -> None:
    assert bool(ve.check_url(url)) is refused


def test_throttle_spaces_same_host_only() -> None:
    now = [100.0]
    slept: list[float] = []

    def sleep(s: float) -> None:
        slept.append(s)
        now[0] += s

    t = ve.HostThrottle(1.0, clock=lambda: now[0], sleep=sleep)
    t.wait("a")
    t.wait("b")
    assert slept == []
    now[0] += 0.4
    t.wait("a")
    assert slept == [pytest.approx(0.6)]


def test_verify_row_statuses_and_flags() -> None:
    t = ve.HostThrottle(0, sleep=lambda _s: None)
    sw = {("pypi", "p", "1.0"): "fail_install"}

    out = ve.verify_row(_row(), sw, lambda u: ve.FetchResult(body="all complete"), t)
    assert out["status"] == "found" and out["flags"] == "still_works_fail"

    out = ve.verify_row(_row(), sw, lambda u: ve.FetchResult(body="nope"), t)
    assert out["status"] == "not_found"

    out = ve.verify_row(_row(), sw, lambda u: ve.FetchResult(error="HTTP 404"), t)
    assert out["status"] == "fetch_error" and "HTTP 404" in out["detail"]

    alive = _row("alive", evidence_quote="2026-05-14T10:11:12Z")
    out = ve.verify_row(
        alive, {}, lambda u: ve.FetchResult(body='{"t": "2026-05-14T10:11:12Z"}'), t
    )
    assert out["status"] == "found" and out["flags"] == "amendment_1_3"
    assert ve.needs_attention(out)


def test_fetch_refuses_non_https_without_network() -> None:
    assert ve.fetch("http://example.org/").error.startswith("refused")


def test_sanitize_cell_and_columns() -> None:
    assert ve.sanitize_cell("a\tb\nc") == "a b c"
    assert ve.COLUMNS == (
        "ecosystem",
        "name",
        "label",
        "evidence_kind",
        "status",
        "flags",
        "detail",
    )
