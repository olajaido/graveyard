import httpx
import pytest

from core.scan.errors import (
    GITHUB_RATE_LIMITED,
    NO_MANIFESTS,
    REPO_NOT_FOUND,
    TOO_LARGE,
    TREE_TRUNCATED,
)
from core.sources.secret import SecretToken
from exhume.trees import GithubReader
from exhume.validate import Repo

REPO = Repo("olajaido", "haunted-house")
SHA = "b" * 40


def reader(handler: httpx.MockTransport) -> tuple[GithubReader, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler.handle_request(request)

    client = httpx.Client(transport=httpx.MockTransport(wrapped), base_url="https://api.github.com")
    return GithubReader(client, SecretToken("ghs_" + "x" * 30)), seen


def test_tree_url_and_rate_header() -> None:
    gh, seen = reader(
        httpx.MockTransport(
            lambda r: httpx.Response(
                200,
                json={"truncated": False, "tree": [{"path": "a"}, "junk"]},
                headers={"x-ratelimit-remaining": "4999"},
            )
        )
    )
    assert gh.tree(REPO, "feature/x") == [{"path": "a"}]
    assert str(seen[0].url) == (
        "https://api.github.com/repos/olajaido/haunted-house/git/trees/feature/x?recursive=1"
    )
    assert gh.rate_remaining == 4999
    gh.tree(REPO, None)
    assert "/git/trees/HEAD" in str(seen[1].url)


def test_blob_is_raw_and_capped() -> None:
    gh, seen = reader(httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * 10)))
    assert gh.blob(REPO, SHA, 10) == b"x" * 10
    assert seen[0].headers["accept"] == "application/vnd.github.raw+json"
    with pytest.raises(TOO_LARGE):
        gh.blob(REPO, SHA, 9)


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(404), REPO_NOT_FOUND),
        (httpx.Response(403), REPO_NOT_FOUND),
        (httpx.Response(409), NO_MANIFESTS),
        (httpx.Response(429), GITHUB_RATE_LIMITED),
        (httpx.Response(403, headers={"x-ratelimit-remaining": "0"}), GITHUB_RATE_LIMITED),
        (httpx.Response(200, json={"truncated": True, "tree": []}), TREE_TRUNCATED),
    ],
)
def test_errors(response: httpx.Response, error: type[Exception]) -> None:
    gh, _ = reader(httpx.MockTransport(lambda r: response))
    with pytest.raises(error):
        gh.tree(REPO, None)


def test_every_request_stays_in_the_repo_path() -> None:
    gh, seen = reader(httpx.MockTransport(lambda r: httpx.Response(200, json={"tree": []})))
    gh.tree(REPO, "main")
    for request in seen:
        assert request.url.host == "api.github.com"
        assert request.url.path.startswith("/repos/olajaido/haunted-house/")
