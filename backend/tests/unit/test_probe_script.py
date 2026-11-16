"""Offline tests for scripts/probe_moved_repo.py (MV2-SRC-2, T2.5).

The script is loaded with ``importlib`` like ``test_capture_script.py`` loads the capture
scripts. No test performs a request: ``Session.sender`` is a fake, and the one test of
``send`` itself uses an ``httpx.MockTransport``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import httpx
import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
_MODULE_NAMES = ("capture_anchors", "probe_moved_repo")

TOKEN = "ghp_SENTINELTOKEN0123456789abcdefghijkl"
BODY = "SENTINEL-BODY-TEXT-must-never-be-stored"
CONTACT = "probe-test@example.com"
AS_OF = date(2026, 11, 14)


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
        probe = _load("probe_moved_repo")
        yield anchors, probe
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
def probe(scripts: tuple[Any, Any], anchors: Any) -> Any:
    return scripts[1]


class FailingClient:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pytest.fail("httpx.Client must not be created in an offline test")


# --------------------------------------------------------------------------- #
# Fake network behind Session.sender
# --------------------------------------------------------------------------- #
def _node(pushed: str = "2026-10-01T00:00:00Z", open_issues: int = 5) -> dict[str, Any]:
    return {
        "isArchived": False,
        "pushedAt": pushed,
        "open": {"totalCount": open_issues},
        "closed": {"totalCount": 9},
        "description": BODY,
        "defaultBranchRef": {
            "target": {
                "history": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [
                        {"author": {"name": "n", "email": "e@x.test", "user": {"login": "a"}}}
                    ],
                }
            }
        },
    }


def _project(overall: float = 6.5) -> dict[str, Any]:
    return {
        "description": BODY,
        "scorecard": {"overallScore": overall, "checks": [{"name": "Maintained", "score": 7}]},
    }


class FakeNet:
    """A fake ``Session.sender``. Names are case-insensitive; every call is recorded.

    ``ids`` maps ``owner/name`` (lower) to a repository id, ``current`` maps an id to its
    ``full_name``. A name that is in ``ids`` and whose current name differs answers REST with
    a 301. ``pushes`` scripts the successive ``pushedAt`` of a name (the last one repeats).
    """

    def __init__(self) -> None:
        self.ids: dict[str, str] = {}
        self.current: dict[str, str] = {}
        self.nodes: dict[str, dict[str, Any]] = {}  # by id
        self.projects: dict[str, dict[str, Any]] = {}  # by lower-case name
        self.pushes: dict[str, list[str]] = {}
        self.location: dict[str, str] = {}  # override of the 301 Location, by lower old name
        self.calls: list[tuple[str, str]] = []

    def add(self, old: str, new: str, rid: str, *, moved: bool = True) -> None:
        self.ids[old.lower()] = rid
        self.ids[new.lower()] = rid
        self.current[rid] = new if moved else old
        self.nodes[rid] = _node()

    def count(self, method: str, fragment: str) -> int:
        return sum(1 for m, u in self.calls if m == method and fragment in u)

    def __call__(
        self, method: str, url: str, *, body: dict[str, Any] | None = None, delay: float = 1.0
    ) -> Any:
        self.calls.append((method, url))
        reply = sys.modules["probe_moved_repo"].Reply
        api = "https://api.github.com"
        if url == f"{api}/graphql":
            return reply(200, {}, self._graphql(body or {}))
        if url.startswith(f"{api}/repositories/"):
            rid = url.rsplit("/", 1)[1]
            if rid not in self.current:
                return reply(404, {}, {"message": BODY})
            return reply(200, {}, {"full_name": self.current[rid], "description": BODY})
        if url.startswith(f"{api}/repos/"):
            old = url.removeprefix(f"{api}/repos/")
            rid = self.ids.get(old.lower())
            if rid is None:
                return reply(404, {}, {"message": BODY})
            if self.current[rid].lower() == old.lower():
                return reply(200, {}, {"full_name": self.current[rid], "description": BODY})
            loc = self.location.get(old.lower(), f"{api}/repositories/{rid}")
            return reply(301, {"location": loc}, {"message": BODY})
        if url.startswith("https://api.deps.dev/v3/projects/"):
            name = unquote(url.rsplit("/", 1)[1]).removeprefix("github.com/").lower()
            doc = self.projects.get(name)
            return reply(200, {}, doc if doc is not None else _project())
        return reply(404, {}, None)

    def _graphql(self, body: dict[str, Any]) -> dict[str, Any]:
        variables = body["variables"]
        data: dict[str, Any] = {}
        i = 0
        while f"o{i}" in variables:
            name = f"{variables[f'o{i}']}/{variables[f'n{i}']}"
            rid = self.ids.get(name.lower())
            if "since" in variables:  # capture-path query
                node = None if rid is None else dict(self.nodes[rid])
                script = self.pushes.get(name.lower())
                if node is not None and script:
                    node["pushedAt"] = script.pop(0) if len(script) > 1 else script[0]
                data[f"r{i}"] = node
            else:  # nameWithOwner query
                data[f"r{i}"] = (
                    None
                    if rid is None
                    else {"nameWithOwner": self.current[rid], "description": BODY}
                )
            i += 1
        return {"data": data}


@pytest.fixture
def net(probe: Any) -> FakeNet:
    return FakeNet()


def _session(probe: Any, net: FakeNet) -> Any:
    return probe.Session(sender=net, delay=1.0)


# --------------------------------------------------------------------------- #
# Redirects: 301 is not followed, Location is validated
# --------------------------------------------------------------------------- #
def test_send_does_not_follow_a_301(
    probe: Any, anchors: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            301, headers={"Location": "https://api.github.com/repositories/42"}, json={"m": BODY}
        )

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    monkeypatch.setattr(probe, "_client", client)
    monkeypatch.setattr(anchors, "_TOKEN", TOKEN)
    reply = probe.send("GET", "https://api.github.com/repos/old/name", delay=0)
    assert reply.status == 301
    assert reply.headers["location"] == "https://api.github.com/repositories/42"
    assert len(seen) == 1
    assert seen[0].headers["Authorization"] == f"Bearer {TOKEN}"
    client.close()


def test_send_token_only_to_github_and_other_hosts_refused(
    probe: Any, anchors: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    monkeypatch.setattr(probe, "_client", client)
    monkeypatch.setattr(anchors, "_TOKEN", TOKEN)
    probe.send("GET", "https://api.deps.dev/v3/projects/x", delay=0)
    assert "Authorization" not in seen[0].headers
    for url in ("https://evil.example/x", "http://api.github.com/x"):
        with pytest.raises(probe.ProbeError):
            probe.send("GET", url, delay=0)
    assert len(seen) == 1
    client.close()


@pytest.mark.parametrize(
    "location",
    [
        "https://evil.example/repositories/42",
        "https://api.github.com.evil.example/repositories/42",
        "http://api.github.com/repositories/42",
        "https://api.github.com:8443/repositories/42",
        "https://user@api.github.com/repositories/42",
        "https://api.github.com/repositories/42?x=1",
        "https://api.github.com/repositories/42/issues",
        "https://api.github.com/repositories/abc",
        "https://api.github.com/repos/other/name",
        "",
    ],
)
def test_unacceptable_location_is_rejected(probe: Any, net: FakeNet, location: str) -> None:
    net.add("old/name", "new/name", "42")
    net.location["old/name"] = location
    status, rid, current, note = probe.confirm_moved(_session(probe, net), "old/name")
    assert (status, rid, current) == ("301", "", None)
    assert "unacceptable Location" in note
    assert net.count("GET", "/repositories/") == 0  # nothing was fetched from the bad Location


def test_valid_301_is_read_once_and_confirmed_by_id(probe: Any, net: FakeNet) -> None:
    net.add("old/name", "new/name", "42")
    status, rid, current, note = probe.confirm_moved(_session(probe, net), "old/name")
    assert (status, rid, current, note) == ("301", "42", "new/name", "")
    assert net.count("GET", "/repos/old/name") == 1
    assert net.count("GET", "/repositories/42") == 1


def test_non_301_reply_is_not_moved(probe: Any, net: FakeNet) -> None:
    net.add("same/name", "same/name", "7", moved=False)
    status, rid, current, note = probe.confirm_moved(_session(probe, net), "same/name")
    assert (status, rid, current) == ("200", "", None)
    assert "not a 301" in note


# --------------------------------------------------------------------------- #
# Subjects: not moved
# --------------------------------------------------------------------------- #
def test_seed_with_same_current_name_is_not_moved(probe: Any, net: FakeNet) -> None:
    net.add("Owner/Repo", "owner/repo", "9", moved=False)
    [subject] = probe.seed_subjects(_session(probe, net), [("Owner/Repo", "9")])
    assert subject.confirmed_moved is False
    assert subject.note == "not moved"
    assert net.count("GET", "/repos/") == 0  # REST is not asked for a seed that did not move


def test_seed_that_moved_is_confirmed(probe: Any, net: FakeNet) -> None:
    net.add("old/name", "new/name", "42")
    [subject] = probe.seed_subjects(_session(probe, net), [("old/name", "42")])
    assert subject.confirmed_moved is True
    assert (subject.current_name, subject.repository_id) == ("new/name", "42")


def test_seed_id_differing_from_redirect_id_is_not_moved(probe: Any, net: FakeNet) -> None:
    net.add("old/name", "new/name", "42")
    net.current["43"] = "new/name"
    net.location["old/name"] = "https://api.github.com/repositories/43"
    [subject] = probe.seed_subjects(_session(probe, net), [("old/name", "42")])
    assert subject.confirmed_moved is False
    assert "differs from redirect id" in subject.note


def test_fixture_repo_whose_name_is_unchanged_is_not_a_subject(probe: Any, net: FakeNet) -> None:
    net.add("stay/put", "stay/put", "1", moved=False)
    net.add("fx/old", "fx/new", "2")
    subjects = probe.build_subjects(_session(probe, net), [], ["stay/put", "fx/old"])
    assert [s.old_name for s in subjects] == ["fx/old"]
    assert subjects[0].confirmed_moved is True


# --------------------------------------------------------------------------- #
# S3 repeat rule
# --------------------------------------------------------------------------- #
def _subject(probe: Any) -> Any:
    return probe.Subject("old/name", "new/name", "seed", "42", "301", True, "")


def test_pair_not_repeated_when_s3_equal(probe: Any, net: FakeNet) -> None:
    net.add("old/name", "new/name", "42")
    http = probe.SenderHttp(_session(probe, net))
    old, current, first = probe.measure_pair(http, _subject(probe), AS_OF)
    assert first is None
    assert old.values["s3"] == current.values["s3"] == "2026-10-01"
    assert net.count("POST", "/graphql") == 2  # one old, one current


def test_pair_repeated_once_when_s3_differs_and_second_round_recorded(
    probe: Any, net: FakeNet
) -> None:
    net.add("old/name", "new/name", "42")
    net.pushes["old/name"] = ["2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z"]
    http = probe.SenderHttp(_session(probe, net))
    old, current, first = probe.measure_pair(http, _subject(probe), AS_OF)
    assert first == {"old_s3": "2026-09-01", "current_s3": "2026-10-01"}
    assert old.values["s3"] == current.values["s3"] == "2026-10-01"
    assert net.count("POST", "/graphql") == 4


def test_pair_repeated_only_once_when_s3_keeps_differing(probe: Any, net: FakeNet) -> None:
    net.add("old/name", "new/name", "42")
    net.pushes["old/name"] = ["2026-09-01T00:00:00Z"]  # never converges
    http = probe.SenderHttp(_session(probe, net))
    old, current, first = probe.measure_pair(http, _subject(probe), AS_OF)
    assert first is not None
    assert old.values["s3"] != current.values["s3"]
    assert net.count("POST", "/graphql") == 4


def test_measurement_stores_scalars_only(probe: Any, net: FakeNet) -> None:
    net.add("old/name", "new/name", "42")
    http = probe.SenderHttp(_session(probe, net))
    lookup = probe.measure_capture(http, "old/name", AS_OF)
    assert set(lookup.values) == set(probe.SIGNALS)
    assert lookup.values["s4"] == 7 and lookup.values["s8"] == 6.5
    assert lookup.values["s5"] == 1 and lookup.values["archived"] is False
    assert BODY not in json.dumps(lookup.values) + json.dumps(lookup.calls)


# --------------------------------------------------------------------------- #
# main(): end to end with temp directories
# --------------------------------------------------------------------------- #
@pytest.fixture
def env(
    probe: Any, anchors: Any, net: FakeNet, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, list[str]]:
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    monkeypatch.setenv("GRAVEYARD_CONTACT", CONTACT)
    monkeypatch.setattr(probe, "send", net)
    monkeypatch.setattr(httpx, "Client", FailingClient)
    out = tmp_path / "out"
    out.mkdir()
    fixtures = tmp_path / "fixtures"
    (fixtures / "npm").mkdir(parents=True)
    argv = ["--as-of", AS_OF.isoformat(), "--out-dir", str(out), "--fixture-dir", str(fixtures)]
    return out, fixtures, argv


def _seeds(out: Path, rows: list[tuple[str, str]]) -> None:
    lines = ["old_name\trepository_id\tobserved"]
    lines += [f"{old}\t{rid}\tREST returned 301" for old, rid in rows]
    (out / "seeds.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _all_output(out: Path, capsys: pytest.CaptureFixture[str]) -> str:
    text = "".join(p.read_text(encoding="utf-8") for p in sorted(out.iterdir()))
    captured = capsys.readouterr()
    return text + captured.out + captured.err


def test_main_follows_exit_0_and_writes_reports(
    probe: Any, net: FakeNet, env: tuple[Path, Path, list[str]], capsys: pytest.CaptureFixture[str]
) -> None:
    out, fixtures, argv = env
    net.add("old/one", "new/one", "1")
    net.add("old/two", "new/two", "2")
    net.add("fx/old", "fx/new", "3")
    net.add("stay/put", "stay/put", "4", moved=False)
    _seeds(out, [("old/one", "1"), ("old/two", "2")])
    (fixtures / "npm" / "a.json").write_text(json.dumps({"repo": "github.com/fx/old"}))
    (fixtures / "npm" / "b.json").write_text(json.dumps({"repo": "stay/put", "x": BODY}))
    (fixtures / "npm" / "bad.json").write_text("{not json")

    assert probe.main(argv) == 0

    names = sorted(p.name for p in out.iterdir())
    assert names == ["result.md", "results.json", "seeds.tsv", "subjects.tsv"]
    doc = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert doc["verdict"]["outcome"] == "FOLLOWS"
    assert doc["verdict"]["moved_subjects"] == 3
    assert doc["as_of"] == AS_OF.isoformat()
    assert [s["old_name"] for s in doc["subjects"]] == ["old/one", "old/two", "fx/old"]
    rows = (out / "subjects.tsv").read_text(encoding="utf-8").splitlines()
    assert rows[0].split("\t") == list(probe.SUBJECT_COLUMNS)
    assert len(rows) == 4
    assert "Verdict: **FOLLOWS**" in (out / "result.md").read_text(encoding="utf-8")
    assert "\r" not in (out / "results.json").read_text(encoding="utf-8")


def test_main_fails_exit_0_names_failing_source(
    probe: Any, net: FakeNet, env: tuple[Path, Path, list[str]], capsys: pytest.CaptureFixture[str]
) -> None:
    out, _, argv = env
    net.add("old/one", "new/one", "1")
    net.add("old/two", "new/two", "2")
    net.projects["old/one"] = _project(overall=3.0)  # the old name sees another Scorecard
    _seeds(out, [("old/one", "1"), ("old/two", "2")])

    assert probe.main(argv) == 0

    doc = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert doc["verdict"]["outcome"] == "FAILS"
    assert doc["verdict"]["failing_sources"] == ["scorecard"]
    assert doc["verdict"]["failing_signals"] == ["s8"]
    assert "Failing sources: scorecard" in (out / "result.md").read_text(encoding="utf-8")


def test_main_inconclusive_exit_1_with_fewer_than_two_moved(
    probe: Any, net: FakeNet, env: tuple[Path, Path, list[str]], capsys: pytest.CaptureFixture[str]
) -> None:
    out, _, argv = env
    net.add("old/one", "new/one", "1")
    net.add("same/name", "same/name", "2", moved=False)
    _seeds(out, [("old/one", "1"), ("same/name", "2")])

    assert probe.main(argv) == 1

    doc = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert doc["verdict"]["outcome"] == "INCONCLUSIVE"
    assert doc["subjects"][1]["confirmed_moved"] is False
    assert doc["subjects"][1]["measured"] is False


def test_no_body_text_and_no_token_in_any_output(
    probe: Any, net: FakeNet, env: tuple[Path, Path, list[str]], capsys: pytest.CaptureFixture[str]
) -> None:
    out, _, argv = env
    net.add("old/one", "new/one", "1")
    net.add("old/two", "new/two", "2")
    _seeds(out, [("old/one", "1"), ("old/two", "2")])
    assert probe.main(argv) == 0
    text = _all_output(out, capsys)
    assert BODY not in text
    assert TOKEN not in text
    assert "SENTINELTOKEN" not in text


def test_token_in_an_error_is_scrubbed(
    probe: Any, anchors: Any, env: tuple[Path, Path, list[str]], capsys: pytest.CaptureFixture[str]
) -> None:
    out, _, argv = env
    _seeds(out, [("old/one", "1")])

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise probe.ProbeError(f"giving up after retries: {TOKEN}")

    probe.send = boom  # the env fixture's monkeypatch restores ``send``
    assert probe.main(argv) == 1
    text = _all_output(out, capsys)
    assert TOKEN not in text
    assert "[REDACTED]" in text


def test_write_text_atomic_refuses_a_token(probe: Any, anchors: Any, tmp_path: Path) -> None:
    anchors._TOKEN = TOKEN
    with pytest.raises(probe.ProbeError):
        probe.write_text_atomic(tmp_path / "x.txt", f"leak {TOKEN}")
    assert not (tmp_path / "x.txt").exists()
    with pytest.raises(probe.ProbeError):
        probe.write_text_atomic(tmp_path / "y.txt", "ghp_" + "a" * 30)
    probe.write_text_atomic(tmp_path / "z.txt", "fine\n")
    assert (tmp_path / "z.txt").read_bytes() == b"fine\n"


# --------------------------------------------------------------------------- #
# Usage errors
# --------------------------------------------------------------------------- #
@pytest.fixture
def no_network(probe: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("no request may be made on a usage error")

    monkeypatch.setattr(probe, "send", fail)
    monkeypatch.setattr(httpx, "Client", FailingClient)


@pytest.mark.parametrize("missing", ["GITHUB_TOKEN", "GRAVEYARD_CONTACT"])
def test_missing_environment_exit_2(
    probe: Any,
    no_network: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    missing: str,
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    monkeypatch.setenv("GRAVEYARD_CONTACT", CONTACT)
    monkeypatch.setenv(missing, "  ")  # blank counts as missing
    assert probe.main(["--as-of", AS_OF.isoformat(), "--out-dir", str(tmp_path)]) == 2
    assert missing in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_missing_seeds_file_exit_2_before_any_request_or_write(
    probe: Any,
    no_network: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    monkeypatch.setenv("GRAVEYARD_CONTACT", CONTACT)
    assert probe.main(["--as-of", AS_OF.isoformat(), "--out-dir", str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert str(tmp_path / "seeds.tsv") in err
    assert "Traceback" not in err
    assert list(tmp_path.iterdir()) == []


def test_delay_below_minimum_exit_2(
    probe: Any, no_network: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    monkeypatch.setenv("GRAVEYARD_CONTACT", CONTACT)
    assert (
        probe.main(["--as-of", AS_OF.isoformat(), "--delay", "0.1", "--out-dir", str(tmp_path)])
        == 2
    )


def test_missing_as_of_exit_2(probe: Any, no_network: None, tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as info:
        probe.main(["--out-dir", str(tmp_path)])
    assert info.value.code == 2


@pytest.mark.parametrize("value", ["2026-13-01", "14/11/2026", "yesterday", ""])
def test_bad_as_of_format_exit_2(
    probe: Any,
    no_network: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    value: str,
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    monkeypatch.setenv("GRAVEYARD_CONTACT", CONTACT)
    assert probe.main(["--as-of", value, "--out-dir", str(tmp_path)]) == 2
    assert "YYYY-MM-DD" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_future_as_of_exit_2(
    probe: Any,
    no_network: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    monkeypatch.setenv("GRAVEYARD_CONTACT", CONTACT)
    assert probe.main(["--as-of", "2999-01-01", "--out-dir", str(tmp_path)]) == 2
    assert "future" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_unknown_option_exit_2(probe: Any, no_network: None) -> None:
    with pytest.raises(SystemExit) as info:
        probe.main(["--no-such-option"])
    assert info.value.code == 2


def test_exit_code_mapping(probe: Any) -> None:
    for outcome, code in (("FOLLOWS", 0), ("FAILS", 0), ("INCONCLUSIVE", 1)):
        verdict = probe.Verdict(probe.Outcome(outcome), (), 0)
        assert probe.exit_code(verdict) == code
