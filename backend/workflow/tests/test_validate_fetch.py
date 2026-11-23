import json
import logging
from typing import Any

import httpx
import pytest

from core.scan.errors import (
    GITHUB_AUTH_FAILED,
    INTERNAL,
    INVALID_INPUT,
    NO_MANIFESTS,
    REPO_NOT_FOUND,
    TOO_LARGE,
    TREE_TRUNCATED,
)
from workflow import fetch, validate
from workflow.tests.support import SCAN_ID, make_deps, queued_scan

SHA = "c" * 40
TOKEN = "ghs_" + "q" * 36
LIMITS = {
    "max_services": 50,
    "max_manifest_bytes": 10_000,
    "max_file_bytes": 5_000,
    "max_purls": 2000,
}
EVENT: dict[str, Any] = {
    "scanId": SCAN_ID,
    "source": {"type": "github", "repo": "olajaido/haunted-house"},
    "limits": LIMITS,
}


def github(
    tree: list[dict[str, Any]], blob: bytes = b"{}", truncated: bool = False, tree_status: int = 200
) -> httpx.MockTransport:
    def respond(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/access_tokens"):
            return httpx.Response(201, json={"token": TOKEN})
        if "/git/trees/" in path:
            if tree_status != 200:
                return httpx.Response(tree_status)
            return httpx.Response(
                200,
                json={"truncated": truncated, "tree": tree},
                headers={"x-ratelimit-remaining": "4990"},
            )
        if "/git/blobs/" in path:
            return httpx.Response(200, content=blob)
        return httpx.Response(404)

    return httpx.MockTransport(respond)


def entry(path: str, size: int = 2) -> dict[str, Any]:
    return {"path": path, "type": "blob", "mode": "100644", "sha": SHA, "size": size}


def test_validate_sets_running_and_returns_limits() -> None:
    deps, table, _, _ = make_deps()
    queued_scan(table)
    out = validate.run({"scanId": SCAN_ID, "source": EVENT["source"]}, deps)
    assert out["limits"]["max_purls"] == 2000
    assert (
        table.scans[SCAN_ID]["status"] == "RUNNING" and table.scans[SCAN_ID]["stage"] == "VALIDATE"
    )


@pytest.mark.parametrize(
    "source",
    [
        {"type": "sbom"},
        {"type": "github", "repo": "http://x/y"},
        {"type": "github", "repo": "a/b", "ref": "a..b"},
        "x",
    ],
)
def test_validate_rejects(source: object) -> None:
    deps, table, _, _ = make_deps()
    queued_scan(table)
    with pytest.raises(INVALID_INPUT):
        validate.run({"scanId": SCAN_ID, "source": source}, deps)
    with pytest.raises(INVALID_INPUT):
        validate.run({"scanId": "../x", "source": EVENT["source"]}, deps)


def test_fetch_success() -> None:
    tree = [
        entry("package-lock.json"),
        entry("services/worker/requirements.txt"),
        entry("README.md"),
    ]
    deps, table, artefacts, recorder = make_deps(github(tree, blob=b"{}"))
    queued_scan(table)
    out = fetch.run(EVENT, deps)
    assert out["services"] == 2 and out["files"] == 2 and out["bytes"] == 4
    assert out["serviceItems"] == [{"scanId": SCAN_ID, "index": 0}, {"scanId": SCAN_ID, "index": 1}]
    assert f"scans/{SCAN_ID}/manifests/0/package-lock.json" in artefacts.objects
    assert f"scans/{SCAN_ID}/manifests/1/requirements.txt" in artefacts.objects
    services = json.loads(artefacts.objects[out["servicesKey"]])
    assert services[1]["path"] == "services/worker" and len(services[0]["files"][0]["sha256"]) == 64
    assert ("GitHubRateRemaining", 4990, {}) in recorder.metrics
    assert table.scans[SCAN_ID]["stage"] == "FETCH"
    assert TOKEN not in json.dumps(out)


def test_fetch_stores_the_services_for_the_ui() -> None:
    tree = [
        entry("package-lock.json"),
        entry("requirements.txt"),
        entry("services/worker/uv.lock"),
    ]
    deps, table, _, _ = make_deps(github(tree, blob=b"{}"))
    queued_scan(table)
    fetch.run(EVENT, deps)
    assert table.scans[SCAN_ID]["services"] == [
        {
            "id": ".",
            "manifests": [
                {"ecosystem": "npm", "path": "package-lock.json"},
                {"ecosystem": "pypi", "path": "requirements.txt"},
            ],
        },
        {
            "id": "services/worker",
            "manifests": [{"ecosystem": "pypi", "path": "services/worker/uv.lock"}],
        },
    ]
    assert TOKEN not in json.dumps(table.scans[SCAN_ID])


def test_fetch_errors() -> None:
    cases: list[tuple[httpx.MockTransport, type[Exception]]] = [
        (github([], tree_status=404), REPO_NOT_FOUND),
        (github([entry("a.py")]), NO_MANIFESTS),
        (github([], truncated=True), TREE_TRUNCATED),
        (github([entry("package-lock.json", size=6000)]), TOO_LARGE),
        (
            github([entry("a/uv.lock", 4000), entry("b/uv.lock", 4000), entry("c/uv.lock", 4000)]),
            TOO_LARGE,
        ),
    ]
    for transport, error in cases:
        deps, table, _, _ = make_deps(transport)
        queued_scan(table)
        with pytest.raises(error):
            fetch.run(EVENT, deps)


def test_fetch_downloaded_bytes_are_capped_even_if_the_tree_lied() -> None:
    deps, table, _, _ = make_deps(github([entry("package-lock.json", 1)], blob=b"x" * 6000))
    queued_scan(table)
    with pytest.raises(TOO_LARGE):
        fetch.run(EVENT, deps)


def test_fetch_unset_app_id_is_auth_failure() -> None:
    deps, table, _, _ = make_deps(
        github([entry("uv.lock")]), params={"github/reader/installation-id": "UNSET"}
    )
    queued_scan(table)
    with pytest.raises(GITHUB_AUTH_FAILED):
        fetch.run(EVENT, deps)


def test_unexpected_exception_becomes_internal_and_the_token_is_not_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    deps, table, artefacts, _ = make_deps(github([entry("uv.lock")]))
    queued_scan(table)

    def boom(key: str, body: bytes) -> None:
        raise RuntimeError(f"disk full {TOKEN}")

    artefacts.put = boom  # type: ignore[method-assign]
    with caplog.at_level(logging.DEBUG), pytest.raises(INTERNAL):
        fetch.run(EVENT, deps)
    assert "task failed: RuntimeError" in caplog.text
    assert TOKEN not in caplog.text and "disk full" not in caplog.text
