"""Offline tests for scripts/capture_anchors.py and scripts/capture_eval.py (EV-TEST-6).

The scripts are loaded with ``importlib``; no test performs a request. Every
``http`` object is a fake, and ``httpx.Client`` is replaced by a fake that fails
the test wherever ``main`` could reach it.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
_MODULE_NAMES = ("capture_anchors", "capture_eval")


def _load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses and the sibling import need this
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def scripts() -> Iterator[tuple[Any, Any]]:
    saved_path = list(sys.path)
    saved_modules = {n: sys.modules[n] for n in _MODULE_NAMES if n in sys.modules}
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        anchors = _load("capture_anchors")
        capture_eval = _load("capture_eval")
        yield anchors, capture_eval
    finally:
        sys.path[:] = saved_path
        for n in _MODULE_NAMES:
            sys.modules.pop(n, None)
        sys.modules.update(saved_modules)


@pytest.fixture
def anchors(scripts: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch) -> Any:
    module = scripts[0]
    monkeypatch.setattr(module, "_TOKEN", "")  # restored after each test
    return module


@pytest.fixture
def ev(scripts: tuple[Any, Any]) -> Any:
    return scripts[1]


class FailingClient:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pytest.fail("httpx.Client must not be created in an offline test")


class FakeHttp:
    """Stands in for ``capture_anchors.Http``; records calls, makes no request."""

    def __init__(self, anchors: Any, *, data: Any = None, error: Exception | None = None) -> None:
        self._anchors = anchors
        self._data = data
        self._error = error
        self.bodies: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> Any:
        if kwargs.get("body") is not None:
            self.bodies.append(kwargs["body"])
        if self._error is not None:
            raise self._error
        return self._anchors.Fetched(url=url, data=self._data, fetched_at="2026-11-14T00:00:00Z")

    def get(self, url: str, allow_404: bool = False) -> Any:
        return self.request("GET", url)


GH_KEYS = ("_s1_github", "s3_last_push_at", "s5_committers", "s6_open_issues", "s6_closed_issues")


def _sig(value: Any) -> dict[str, Any]:
    return {
        "value": value,
        "source": "https://example.test/s",
        "fetched_at": "2026-11-03T00:00:00Z",
    }


def _partial(anchors: Any) -> Any:
    signals = {
        k: _sig(None)
        for k in (
            "s1b_version_deprecated",
            "s2_latest_release_at",
            "s4_maintained",
            "s7_advisories",
            "s8_overall",
            "s9_weekly_downloads",
        )
    }
    signals["_s1_registry"] = _sig(False)
    return anchors.Partial(
        package="left-pad",
        ecosystem="npm",
        resolved="1.3.0",
        latest="1.3.0",
        repo=("a", "b"),
        signals=signals,
    )


def _gh(anchors: Any) -> dict[str, dict[str, Any]]:
    return {k: _sig(False if k == "_s1_github" else 1) for k in GH_KEYS}


# --------------------------------------------------------------------------- #
# capture_anchors
# --------------------------------------------------------------------------- #
def test_anchor_constants_unchanged(anchors: Any) -> None:
    assert set(anchors.ANCHORS) == {
        "request",
        "node-uuid",
        "left-pad",
        "express",
        "uuid",
        "moment",
        "pycrypto",
        "nose",
        "six",
    }
    assert date(2026, 11, 3) == anchors.AS_OF


def test_missing_unavailable_marker(anchors: Any) -> None:
    assert "unavailable" not in anchors.missing("x")
    assert anchors.missing("x", unavailable=True)["unavailable"] is True


def test_assemble_as_of_default_and_parameter(anchors: Any) -> None:
    default = anchors.assemble(_partial(anchors), _gh(anchors))
    assert default["as_of"] == "2026-11-03"
    custom = anchors.assemble(_partial(anchors), _gh(anchors), as_of=date(2026, 11, 14))
    assert custom["as_of"] == "2026-11-14"


def test_capture_github_window_uses_as_of(anchors: Any) -> None:
    as_of = date(2026, 11, 14)
    http = FakeHttp(anchors, data={"data": {"r0": None}})
    out = anchors.capture_github(http, [("a", "b")], as_of)
    variables = http.bodies[0]["variables"]
    assert variables["since"].startswith((as_of - timedelta(days=365)).isoformat())
    assert variables["until"].startswith(as_of.isoformat())
    # "repository not found" is not an unavailable source
    assert set(out[("a", "b")]) == set(GH_KEYS)
    assert all("unavailable" not in v for v in out[("a", "b")].values())


def test_capture_github_batch_failure_is_unavailable(anchors: Any) -> None:
    http = FakeHttp(anchors, error=anchors.FetchError("boom"))
    out = anchors.capture_github(http, [("a", "b")], date(2026, 11, 14))
    assert set(out[("a", "b")]) == set(GH_KEYS)
    assert all(v["unavailable"] is True for v in out[("a", "b")].values())


def test_scorecard_fetch_error_is_unavailable(anchors: Any) -> None:
    http = FakeHttp(anchors, error=anchors.FetchError("down"))
    s4, s8 = anchors.collect_scorecard(http, ("a", "b"), None)
    assert s4["unavailable"] is True and s8["unavailable"] is True


def test_scorecard_absent_is_not_unavailable(anchors: Any) -> None:
    http = FakeHttp(anchors, data={})
    s4, s8 = anchors.collect_scorecard(http, ("a", "b"), None)
    assert s4["value"] is None and s8["value"] is None
    assert "unavailable" not in s4 and "unavailable" not in s8
    assert s4["note"] == "absent"


def test_write_fixture_rejects_token_shaped_string(anchors: Any, tmp_path: Path) -> None:
    fixture = {"package": "evil", "note": "ghp_" + "a1B2" * 9}
    out_dir = tmp_path / "npm"
    with pytest.raises(SystemExit):
        anchors.write_fixture(out_dir, fixture)
    assert not out_dir.exists() or list(out_dir.iterdir()) == []


def test_write_fixture_writes_clean_fixture(anchors: Any, tmp_path: Path) -> None:
    path = anchors.write_fixture(tmp_path / "npm", {"package": "ok", "value": 1})
    assert path == tmp_path / "npm" / "ok.json"
    assert path.exists()


# --------------------------------------------------------------------------- #
# capture_eval: pure helpers
# --------------------------------------------------------------------------- #
def test_build_s1_parts_npm(ev: Any) -> None:
    registry, archived = _sig(True), _sig(False)
    parts = ev.build_s1_parts("npm", registry, archived)
    assert parts == {"registry_deprecated": registry, "repo_archived": archived}


def test_build_s1_parts_pypi_registry_is_null_with_note(ev: Any) -> None:
    parts = ev.build_s1_parts("pypi", _sig(True), _sig(False))
    assert parts["registry_deprecated"]["value"] is None
    assert parts["registry_deprecated"]["note"] == "PyPI exposes no deprecation signal"
    assert parts["repo_archived"]["value"] is False


def test_build_s1_parts_no_repo(ev: Any) -> None:
    parts = ev.build_s1_parts("npm", _sig(False), None)
    assert parts["repo_archived"]["value"] is None
    assert parts["repo_archived"]["note"] == "no GitHub repo resolved"
    assert parts["registry_deprecated"]["value"] is False


def test_read_rows(ev: Any, tmp_path: Path) -> None:
    csv_path = tmp_path / "rows.csv"
    csv_path.write_text("ecosystem,name,version\nnpm,left-pad,1.3.0\npypi,six,1.16.0\n")
    assert ev.read_rows(csv_path) == [("npm", "left-pad", "1.3.0"), ("pypi", "six", "1.16.0")]


def test_read_rows_rejects_bad_rows(ev: Any, tmp_path: Path) -> None:
    for body in (
        "ecosystem,name,version\ngo,x,1\n",
        "ecosystem,name,version\nnpm,Bad Name,1\n",
        "ecosystem,name,version\nnpm,x,\n",
        "ecosystem,name,version\nnpm,x,1\nnpm,x,2\n",
    ):
        csv_path = tmp_path / "bad.csv"
        csv_path.write_text(body)
        with pytest.raises(ValueError, match="line"):
            ev.read_rows(csv_path)


def test_parse_only(ev: Any) -> None:
    assert ev.parse_only(None) is None
    assert ev.parse_only(["npm/ms", "pypi/six"]) == {("npm", "ms"), ("pypi", "six")}
    with pytest.raises(ValueError, match="--only"):
        ev.parse_only(["ms"])


# --------------------------------------------------------------------------- #
# capture_eval.main exit codes
# --------------------------------------------------------------------------- #
@pytest.fixture
def offline_env(anchors: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(anchors.httpx, "Client", FailingClient)
    monkeypatch.setenv("GITHUB_TOKEN", "unit-test-token-value")
    monkeypatch.setenv("GRAVEYARD_CONTACT", "test@example.invalid")


def test_main_missing_as_of_exits_2(ev: Any, offline_env: None) -> None:
    with pytest.raises(SystemExit) as info:
        ev.main([])
    assert info.value.code == 2


def test_main_future_as_of_exits_2(ev: Any, offline_env: None) -> None:
    future = (date.today() + timedelta(days=2)).isoformat()
    assert ev.main(["--as-of", future]) == 2


def test_main_low_delay_exits_2(ev: Any, offline_env: None) -> None:
    assert ev.main(["--as-of", "2026-11-03", "--delay", "0.1"]) == 2


def test_main_missing_token_exits_2(
    ev: Any, offline_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN")
    assert ev.main(["--as-of", "2026-11-03"]) == 2


def test_main_missing_contact_exits_2(
    ev: Any, offline_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GRAVEYARD_CONTACT")
    assert ev.main(["--as-of", "2026-11-03"]) == 2
