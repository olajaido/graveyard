"""The two tools through the SDK's in-memory client/server pair (T11.3; KPW-TEST-12).

No subprocess, no socket. The cassette answers every request; the stub Syft stands in for
Syft (found on ``PATH``, because ``autopsy_project`` has no ``--syft`` argument). Tool errors
reach the client as ``Error executing tool <name>: <message>``, so messages are compared as
the part after that prefix.

``check_tools`` and ``check_shape`` are run on damaged copies too, so they cannot pass
vacuously.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import Client
from mcp_types import ListToolsResult

from cli.args import parse_args
from cli.env import environment_from_mapping
from cli.errors import UsageError
from cli.pipeline import analyse
from cli.report import report_to_dict
from cli.tests.support import make_env
from cli.tests.test_e2e_project import PLANNED_ORDER, PURLS, run_cli
from cli.tests.test_report_shape import check, load_schema
from cli.text import sanitise
from core.sources.tests import recorded as rec
from mcp_server import output, tools
from mcp_server.paths import OUTSIDE_ROOT_MESSAGE
from mcp_server.server import INSTRUCTIONS, PACKAGE_DESCRIPTION, PROJECT_DESCRIPTION, build_server
from mcp_server.tests.support import (
    ANCHORS_PROJECT,
    EXPRESS_PURL,
    FIXTURES_ROOT,
    REQUEST_PURL,
    TOKEN,
    OverlapProbe,
    all_text,
    call_tool,
    cassette_transport,
    first_text,
    fresh_clock,
    list_tools,
    make_token_env,
    use_stub_syft,
)
from mcp_server.tests.test_output import forbidden_in, strings_of
from sources.tests.transports import replay_transport

EXTENSION = Path(__file__).resolve().parent / "fixtures" / "report_v1_mcp_extension.json"
TOOL_NAMES = {"autopsy_package", "autopsy_project"}
HOSTILE = "evil\x1b[31m\u202egpj\x00"


def _made(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def without_fetch_times(value: Any) -> Any:
    """``value`` with every ``fetched_at`` removed (it is the fake clock's reading)."""
    if isinstance(value, dict):
        return {k: without_fetch_times(v) for k, v in value.items() if k != "fetched_at"}
    if isinstance(value, list):
        return [without_fetch_times(v) for v in value]
    return value


def prefix(tool: str) -> str:
    return f"Error executing tool {tool}: "


def package_server(*, env: Any = None, transport: Any = None, root: Path = FIXTURES_ROOT) -> Any:
    seen = cassette_transport()
    server = build_server(
        env or make_env(), root, transport=transport or seen.transport, clock=fresh_clock()
    )
    return server, seen


def error_text(result: Any) -> str:
    assert result.is_error is True
    assert result.structured_content is None
    assert len(result.content) == 1
    return first_text(result)


def cli_package_doc(purl: str = REQUEST_PURL) -> dict[str, Any]:
    """What ``graveyard autopsy --purl`` reports for ``purl``, as plain JSON."""
    clock = fresh_clock()
    opts = parse_args(["autopsy", "--purl", purl, "--all"], today=clock.now().date())
    report = analyse(opts, make_env(), cassette_transport().transport, clock)
    loaded = json.loads(json.dumps(report_to_dict(report)))
    assert isinstance(loaded, dict)
    return loaded


# ------------------------------------------------------------------------------ the shape file


def mcp_schema(*, truncated: bool) -> dict[str, Any]:
    """The committed CLI shape plus the MCP keys of the committed extension file."""
    extension = json.loads(EXTENSION.read_text(encoding="utf-8"))
    schema = load_schema()
    schema.update(extension["always"])
    if truncated:
        schema.update(extension["when_truncated"])
    return schema


def check_shape(doc: dict[str, Any]) -> list[str]:
    return check(doc, mcp_schema(truncated=doc.get("truncated") is True))


def test_the_cli_shape_file_is_unchanged_and_has_no_truncated() -> None:
    assert "truncated" not in load_schema()
    assert list(mcp_schema(truncated=False))[-1] == "truncated"
    assert list(mcp_schema(truncated=True))[-3:] == [
        "truncated",
        "packages_total",
        "packages_returned",
    ]


def test_the_shape_check_catches_damage() -> None:
    good = {**cli_package_doc(), "truncated": False}
    assert check_shape(good) == []
    missing = {k: v for k, v in good.items() if k != "truncated"}
    assert check_shape(missing) != []
    assert check_shape({**good, "truncated": "no"}) != []
    assert check_shape({**good, "packages_total": 1}) != []  # counts only when truncated
    reordered = {"truncated": False, **{k: v for k, v in good.items() if k != "truncated"}}
    assert check_shape(reordered) != []
    assert check_shape({**good, "truncated": True}) != []  # counts missing


# ------------------------------------------------------------------------------- tool listing


def check_tools(listing: ListToolsResult) -> list[str]:
    problems: list[str] = []
    names = [t.name for t in listing.tools]
    if sorted(names) != sorted(TOOL_NAMES):
        problems.append(f"tools are {names}")
    for tool in listing.tools:
        hints = tool.annotations
        if hints is None:
            problems.append(f"{tool.name}: no annotations")
            continue
        got = (
            hints.read_only_hint,
            hints.destructive_hint,
            hints.idempotent_hint,
            hints.open_world_hint,
        )
        if got != (True, False, True, True):
            problems.append(f"{tool.name}: annotations {got}")
    return problems


def test_exactly_two_tools_with_the_read_only_annotations() -> None:
    server, _ = package_server()
    listing = list_tools(server)
    assert check_tools(listing) == []
    assert {t.name for t in listing.tools} == TOOL_NAMES


def test_the_tool_check_catches_a_wrong_listing() -> None:
    server, _ = package_server()
    listing = list_tools(server)
    one, two = listing.tools
    assert one.annotations is not None
    damaged_hint = one.model_copy(
        update={"annotations": one.annotations.model_copy(update={"destructive_hint": True})}
    )
    assert check_tools(listing.model_copy(update={"tools": [damaged_hint, two]})) != []
    assert check_tools(listing.model_copy(update={"tools": [one]})) != []
    assert check_tools(listing.model_copy(update={"tools": [*listing.tools, one]})) != []
    assert (
        check_tools(
            listing.model_copy(
                update={"tools": [one.model_copy(update={"annotations": None}), two]}
            )
        )
        != []
    )


async def _list_everything(server: Any) -> tuple[Any, Any]:
    async with Client(server) as client:
        return await client.list_resources(), await client.list_prompts()


def test_it_advertises_no_prompts_or_resources_empty_lists() -> None:
    server, _ = package_server()
    resources, prompts = anyio.run(_list_everything, server)
    assert resources.resources == []
    assert prompts.prompts == []


def test_descriptions_say_read_only_data_not_instructions_and_what_no_token_means() -> None:
    listing = list_tools(package_server()[0])
    described = {t.name: t.description or "" for t in listing.tools}
    assert described == {
        "autopsy_package": PACKAGE_DESCRIPTION,
        "autopsy_project": PROJECT_DESCRIPTION,
    }
    for text in (*described.values(), INSTRUCTIONS):
        assert "Read-only" in text or "Neither tool changes anything" in text
        assert "not instructions" in text
        assert "GITHUB_TOKEN" in text
        assert "unverified" in text
    assert TOKEN not in INSTRUCTIONS + PACKAGE_DESCRIPTION + PROJECT_DESCRIPTION


# ------------------------------------------------------------------------------ autopsy_package


def test_autopsy_package_equals_the_cli_report_plus_truncated_false_and_has_the_shape() -> None:
    server, seen = package_server()
    result = call_tool(server, "autopsy_package", {"purl": REQUEST_PURL})
    assert result.is_error is False
    assert seen.log.unmatched == []
    doc = result.structured_content
    assert doc == {**cli_package_doc(), "truncated": False}
    assert doc["truncated"] is False
    assert check_shape(doc) == []
    # the text block is the same document, as JSON
    assert json.loads(first_text(result)) == doc
    # the facts that make this the right package
    assert doc["packages"][0]["purl"] == REQUEST_PURL
    assert doc["packages"][0]["state"] == "Dead"
    assert doc["packages"][0]["cursed"] is True


@pytest.mark.parametrize(
    ("purl", "phrase"),
    [
        ("nope", "not a valid npm or PyPI package URL"),
        ("pkg:npm/request", "needs a version"),
        ("pkg:maven/org.example/thing@1.0.0", "not a valid npm or PyPI package URL"),
        ("--json=/tmp/graveyard-mcp-evil.json", "expected one argument"),
    ],
)
def test_bad_purls_are_tool_errors_with_the_cli_message(purl: str, phrase: str) -> None:
    server, seen = package_server()
    result = call_tool(server, "autopsy_package", {"purl": purl})
    text = error_text(result)
    with pytest.raises(UsageError) as caught:
        parse_args(["autopsy", "--purl", purl, "--all"], today=fresh_clock().now().date())
    assert text == prefix("autopsy_package") + sanitise(caught.value.message)
    assert text.endswith(sanitise(caught.value.message))
    assert phrase in text
    assert seen.headers == []  # nothing was requested


def test_a_hostile_purl_is_sanitised_in_the_error() -> None:
    server, _ = package_server()
    text = error_text(call_tool(server, "autopsy_package", {"purl": f"pkg:npm/{HOSTILE}@1"}))
    assert "\x1b" not in text
    assert "\u202e" not in text
    assert "\x00" not in text
    assert "\ufffd" in text


def test_a_hostile_name_in_a_report_is_sanitised_in_the_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = report_to_dict

    def hostile(report: Any) -> dict[str, Any]:
        doc = real(report)
        doc["packages"][0]["name"] = HOSTILE
        doc["packages"][0][HOSTILE] = HOSTILE
        doc["warnings"].append({"origin": "cli", "code": "x", "detail": HOSTILE})
        return doc

    monkeypatch.setattr(tools, "report_to_dict", hostile)
    server, _ = package_server()
    result = call_tool(server, "autopsy_package", {"purl": REQUEST_PURL})
    assert result.is_error is False
    clean = sanitise(HOSTILE)
    doc = result.structured_content
    assert doc["packages"][0]["name"] == clean
    assert doc["packages"][0][clean] == clean
    assert doc["warnings"][-1]["detail"] == clean
    assert not any(forbidden_in(text) for text in strings_of(doc))
    assert not any(forbidden_in(text) for text in strings_of(json.loads(first_text(result))))


def test_an_internal_error_reaches_the_client_as_the_type_name_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(f"SECRET-EXCEPTION-TEXT {TOKEN} /home/someone")

    monkeypatch.setattr(tools, "analyse", explode)
    server, _ = package_server(env=make_token_env())
    text = error_text(call_tool(server, "autopsy_package", {"purl": REQUEST_PURL}))
    assert text == prefix("autopsy_package") + "internal error: RuntimeError"


# ------------------------------------------------------------------------------ autopsy_project


def test_autopsy_project_on_the_anchors_project_returns_the_nine_packages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = use_stub_syft(monkeypatch, tmp_path / "mcp")
    transport, log = replay_transport(rec.cassette())
    server = build_server(make_token_env(), FIXTURES_ROOT, transport=transport, clock=fresh_clock())
    result = call_tool(server, "autopsy_project", {"path": "anchors-project"})
    assert result.is_error is False
    assert log.unmatched == []
    doc = result.structured_content
    assert [p["purl"] for p in doc["packages"]] == [PURLS[name] for name in PLANNED_ORDER]
    assert len(doc["packages"]) == 9
    assert doc["truncated"] is False
    assert check_shape(doc) == []
    assert len(stub.calls()) == 2  # one Syft run per service directory, nothing else
    cli = run_cli(_made(tmp_path / "cli"), "run")
    # The CLI helper runs on a clock ten days later, which only changes ``fetched_at``.
    assert without_fetch_times(doc) == without_fetch_times({**cli.report, "truncated": False})


def test_a_path_outside_the_root_an_escaping_symlink_and_a_file_are_tool_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = use_stub_syft(monkeypatch, tmp_path)
    root = tmp_path / "root"
    root.mkdir()
    (root / "file.txt").write_text("x", encoding="utf-8")
    (root / "escape").symlink_to(ANCHORS_PROJECT, target_is_directory=True)
    outside = tmp_path / "outside-dir-9a2e"
    outside.mkdir()
    server = build_server(make_env(), root, transport=cassette_transport().transport)
    for text in (str(outside), "..", "escape", "file.txt", "missing"):
        message = error_text(call_tool(server, "autopsy_project", {"path": text}))
        assert message == prefix("autopsy_project") + OUTSIDE_ROOT_MESSAGE
        assert "outside-dir-9a2e" not in message
    assert stub.calls() == []


# ------------------------------------------------------------------------------- truncation


def test_truncation_keeps_the_summary_and_reports_the_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The limits are lowered so the nine real packages exceed them; the logic is the real one."""
    use_stub_syft(monkeypatch, tmp_path / "mcp")
    monkeypatch.setattr(output, "MAX_CHARS", 5_000)
    monkeypatch.setattr(output, "MAX_PACKAGES", 4)
    transport, _ = replay_transport(rec.cassette())
    server = build_server(make_token_env(), FIXTURES_ROOT, transport=transport, clock=fresh_clock())
    result = call_tool(server, "autopsy_project", {"path": "anchors-project"})
    assert result.is_error is False
    doc = result.structured_content
    cli = run_cli(_made(tmp_path / "cli"), "run").report
    assert doc["truncated"] is True
    returned = doc["packages_returned"]
    assert 0 < returned <= 4  # the hard size cap may keep fewer than the package limit
    assert [p["purl"] for p in doc["packages"]] == [PURLS[n] for n in PLANNED_ORDER[:returned]]
    assert doc["packages_total"] == 9
    assert len(json.dumps(doc, separators=(",", ":"), ensure_ascii=False)) <= 5_000
    assert doc["summary"] == cli["summary"]
    assert doc["summary"]["packages"] == 9
    for key in ("input", "warnings", "schema", "schema_version", "as_of"):
        assert doc[key] == cli[key], key
    assert check_shape(doc) == []


# ------------------------------------------------------------------ serialisation (KPW-MCP-8)


def test_the_probe_sees_two_overlapping_calls() -> None:
    probe = OverlapProbe()
    slow = probe.wrap(lambda: None)
    threads = [threading.Thread(target=slow) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert probe.max_active == 2


async def _two_calls(server: Any) -> dict[str, Any]:
    results: dict[str, Any] = {}

    async with Client(server) as client:

        async def one(purl: str) -> None:
            results[purl] = await client.call_tool("autopsy_package", {"purl": purl})

        async with anyio.create_task_group() as group:
            group.start_soon(one, REQUEST_PURL)
            group.start_soon(one, EXPRESS_PURL)
    return results


def test_two_concurrent_calls_run_one_after_the_other_in_worker_threads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = OverlapProbe()
    monkeypatch.setattr(tools, "analyse", probe.wrap(analyse))
    server, seen = package_server()
    results = anyio.run(_two_calls, server)
    assert probe.calls == 2
    assert probe.max_active == 1
    assert threading.get_ident() not in probe.threads  # not on the server's own thread
    assert seen.log.unmatched == []
    for purl, result in results.items():
        assert result.is_error is False
        assert result.structured_content["packages"][0]["purl"] == purl


# ----------------------------------------------------------------------------- the token


def test_an_unexpanded_github_token_reference_is_treated_as_absent() -> None:
    env = environment_from_mapping({"GITHUB_TOKEN": "${GITHUB_TOKEN}"}, 100)
    assert env.token is None
    assert env.token_rejected is False
    server, seen = package_server(env=env)
    result = call_tool(server, "autopsy_package", {"purl": REQUEST_PURL})
    assert result.is_error is False
    assert seen.authorization_sent is False
    assert any("no GITHUB_TOKEN set" in w["detail"] for w in result.structured_content["warnings"])


def test_a_real_token_is_sent_to_the_source_but_never_returned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_stub_syft(monkeypatch, tmp_path)
    server, seen = package_server(env=make_token_env())
    texts = [all_text(call_tool(server, "autopsy_package", {"purl": REQUEST_PURL}))]
    assert seen.authorization_sent is True  # the control: the token was used
    # every other way a call can end
    texts += [
        all_text(call_tool(server, "autopsy_package", {"purl": p}))
        for p in ("nope", "pkg:npm/request", "pkg:maven/a/b@1")
    ]
    texts.append(all_text(call_tool(server, "autopsy_package", {"purl": 5})))  # SDK-made error
    texts.append(all_text(call_tool(server, "autopsy_package", {})))
    texts.append(all_text(call_tool(server, "no_such_tool", {})))
    texts.append(all_text(call_tool(server, "autopsy_project", {"path": ".."})))
    texts.append(all_text(call_tool(server, "autopsy_project", {"path": "missing"})))
    monkeypatch.setattr(
        tools, "analyse", lambda *a, **k: (_ for _ in ()).throw(RuntimeError(f"t={TOKEN}"))
    )
    texts.append(all_text(call_tool(server, "autopsy_package", {"purl": REQUEST_PURL})))
    assert len(texts) == 10
    assert [i for i, text in enumerate(texts) if TOKEN in text] == []


def test_nothing_is_written_to_stdout(capfd: pytest.CaptureFixture[str]) -> None:
    server, _ = package_server()
    call_tool(server, "autopsy_package", {"purl": REQUEST_PURL})
    call_tool(server, "autopsy_package", {"purl": "nope"})
    call_tool(server, "autopsy_package", {"purl": 5})
    assert capfd.readouterr().out == ""
